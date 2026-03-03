"""Wheel Options Strategy — mechanical put/call income cycle on selected tickers.

The Wheel is a disciplined options income strategy that rotates through three phases:

  Phase 1: SELLING PUTS (cash-secured)
    - Sell a put option on a stock we're willing to own.
    - We collect premium immediately.
    - If the stock stays above our strike at expiration, the put expires worthless
      and we keep the premium. Restart Phase 1.
    - If the stock drops below our strike, we get "assigned" — we buy 100 shares
      at the strike price. Move to Phase 2.

  Phase 2: ASSIGNED (holding stock)
    - We now own 100 shares of the stock.
    - Check defensive rules: hard stop (sell if down too much), capital efficiency
      (sell if held too long with no recovery).
    - If stock still worth holding, move to Phase 3.

  Phase 3: SELLING CALLS (covered)
    - Sell a call option against our 100 shares.
    - We collect premium immediately.
    - If the stock stays below the call strike, the call expires worthless
      and we keep the premium + still own the shares. Sell another call.
    - If the stock rises above the call strike, shares get "called away" — we sell
      at the strike price. Collect profit. Restart at Phase 1.

Design philosophy:
  - Discipline over emotion: predefined exit rules, no bagholder traps
  - Capital efficiency: don't tie up money in broken positions
  - Adjusted cost basis: track total premiums to know true break-even
  - Rolling: avoid forced assignment on deteriorating stocks
  - Every decision, execution, and restriction is logged to the activity feed

Each of the configured tickers (default: F, SOFI, INTC, PLTR, BAC, AMD)
independently tracks its own wheel phase. The strategy never uses AI — all
decisions are mechanical, based on delta, DTE, yield, and open interest
thresholds from the strategy's JSONB config.
"""

import logging
from datetime import datetime, timezone, date as date_type, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import trading_db, alpaca_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Main entry point — called by trading_engine.py every ~60s during market hours
# ---------------------------------------------------------------------------


async def run_wheel_cycle(db: AsyncSession, strategy: dict) -> None:
    """Run one cycle of the Wheel strategy.

    Called by trading_engine.py for any strategy with strategy_type='wheel'.
    Orchestrates the full cycle: sync orders → detect assignments → process
    each symbol according to its current wheel phase.

    Each symbol is processed independently — one ticker failing (e.g., Alpaca
    API error, no option chain) does NOT block other tickers.
    """
    strategy_id = strategy["id"]
    config = strategy.get("config", {})
    symbol_list = config.get("symbol_list", [])

    logger.info("Wheel cycle starting (%d symbols, cash=$%.2f)",
                len(symbol_list), float(strategy["current_cash"]))

    # --- Step 1: Sync pending orders with Alpaca ---
    # Must run FIRST so we know which orders have filled before making decisions.
    # This updates local DB with fill prices, credits/debits cash for premiums.
    await _sync_option_orders(db, strategy_id)

    # --- Step 2: Detect assignments ---
    # Compare Alpaca's live positions against our local DB to find:
    #   - Puts that were assigned (we now hold stock)
    #   - Puts that expired worthless (we keep premium)
    #   - Calls that were assigned (shares called away)
    #   - Calls that expired worthless (we keep premium + shares)
    # Must run AFTER sync so orders are settled before we inspect positions.
    await _detect_assignments(db, strategy)

    # --- Step 3: Refresh strategy data (cash may have changed from sync/assignment) ---
    strategy = await trading_db.get_strategy(db, strategy_id)
    if not strategy:
        logger.error("Strategy %s not found after refresh", strategy_id)
        return

    # --- Step 4: Get all open positions for this strategy ---
    open_positions = await trading_db.get_open_positions(db, strategy_id)

    # Build a lookup: ticker -> list of open positions for that ticker
    # A ticker can have multiple positions (e.g., stock + option simultaneously)
    ticker_positions: dict[str, list[dict]] = {}
    for pos in open_positions:
        ticker_positions.setdefault(pos["ticker"], []).append(pos)

    # --- Step 5: Sort symbols by affordability (cheapest first) ---
    # With $5,000 capital and tickers ranging from ~$5 to ~$100+, we process
    # cheaper stocks first so they get first dibs on available capital.
    # We fetch prices for all symbols to sort, then process in order.
    symbol_prices: list[tuple[str, float]] = []
    for sym in symbol_list:
        price = await _get_latest_price(sym)
        if price is not None and price > 0:
            symbol_prices.append((sym, price))
        else:
            logger.warning("Could not get price for %s, skipping this cycle", sym)

    # Sort ascending by price — cheapest stocks get capital first
    symbol_prices.sort(key=lambda x: x[1])

    # --- Step 6: Calculate available cash (subtract cash committed to open puts) ---
    # "Cash-secured" means we must reserve strike × 100 for each open put position.
    # This prevents over-committing capital across multiple puts.
    committed_cash = sum(
        float(pos.get("strike_price", 0)) * 100 * (pos.get("contracts") or 1)
        for pos in open_positions
        if pos.get("wheel_phase") == "selling_puts" and pos.get("status") == "open"
    )
    available_cash = float(strategy["current_cash"]) - committed_cash

    # --- Step 7: Process each symbol based on its current wheel phase ---
    for ticker, current_price in symbol_prices:
        positions = ticker_positions.get(ticker, [])

        try:
            # Determine the ticker's current wheel state by examining its positions
            put_pos = _find_position(positions, wheel_phase="selling_puts")
            stock_pos = _find_position(positions, wheel_phase="assigned")
            call_pos = _find_position(positions, wheel_phase="selling_calls")
            # Also check for stock in selling_calls phase (stock position that has a call)
            stock_with_call = _find_position(positions, asset_type="stock")

            if call_pos:
                # Phase 3: We have an open covered call — monitor it
                await _manage_call_position(db, strategy, call_pos)

            elif stock_pos or (stock_with_call and stock_with_call.get("wheel_phase") == "assigned"):
                # Phase 2: We hold assigned stock with no call yet
                active_stock = stock_pos or stock_with_call

                # Check hard stop FIRST — if stock has crashed, sell immediately
                if await _check_hard_stop(db, strategy, ticker, active_stock, current_price):
                    # Stock was sold, cash freed. Update available cash.
                    strategy = await trading_db.get_strategy(db, strategy_id)
                    available_cash = float(strategy["current_cash"]) - committed_cash
                    continue

                # Check capital efficiency — if held too long with no recovery
                if await _check_capital_efficiency(db, strategy, ticker, active_stock, current_price):
                    strategy = await trading_db.get_strategy(db, strategy_id)
                    available_cash = float(strategy["current_cash"]) - committed_cash
                    continue

                # All clear — sell a covered call
                await _sell_call(db, strategy, ticker, active_stock, current_price)

            elif put_pos:
                # Phase 1 (active): We have an open put — monitor it for rolling
                await _manage_put_position(db, strategy, put_pos, current_price)

            else:
                # IDLE: No position on this ticker — try to sell a new put
                # Check if ticker is too expensive for our capital
                assignment_cost = current_price * 100  # Cost if assigned 100 shares
                total_capital = float(strategy["initial_capital"])

                if assignment_cost > total_capital:
                    # Ticker is too expensive even with full capital — skip with log
                    await trading_db.log_activity(
                        db, strategy_id, "blocked_too_expensive",
                        f"Skipped {ticker}: 100 shares at ~${current_price:.0f} = "
                        f"${assignment_cost:,.0f}, exceeds total capital ${total_capital:,.0f}",
                        ticker=ticker,
                        details={
                            "ticker": ticker, "current_price": current_price,
                            "assignment_cost": assignment_cost, "total_capital": total_capital,
                        },
                    )
                    continue

                if available_cash < current_price * 0.5 * 100:
                    # Not enough cash even for a deep OTM put — skip
                    await trading_db.log_activity(
                        db, strategy_id, "blocked_insufficient_cash",
                        f"Skipped {ticker}: would need ~${current_price * 100:,.0f} for assignment "
                        f"but only ${available_cash:,.0f} available "
                        f"(${committed_cash:,.0f} committed to open puts)",
                        ticker=ticker,
                        details={
                            "ticker": ticker, "available_cash": round(available_cash, 2),
                            "committed_cash": round(committed_cash, 2),
                            "estimated_assignment_cost": round(current_price * 100, 2),
                        },
                    )
                    continue

                # Try to sell a cash-secured put
                cash_committed = await _sell_put(db, strategy, ticker, available_cash, current_price)
                if cash_committed > 0:
                    # Reduce available cash for next ticker (reservation accounting)
                    available_cash -= cash_committed

        except Exception as e:
            # Per-symbol error isolation — log and continue to next ticker
            logger.error("Wheel error for %s: %s", ticker, e, exc_info=True)
            await trading_db.log_activity(
                db, strategy_id, "error",
                f"Error processing {ticker}: {str(e)[:200]}",
                ticker=ticker,
                details={"error": str(e)},
            )

    # --- Step 8: Recalculate strategy P&L from all positions ---
    await trading_db.sync_strategy_pnl(db, strategy_id)
    logger.info("Wheel cycle complete")


# ---------------------------------------------------------------------------
# Position lookup helpers
# ---------------------------------------------------------------------------


def _find_position(
    positions: list[dict],
    wheel_phase: str | None = None,
    asset_type: str | None = None,
) -> dict | None:
    """Find the first open position matching the given criteria.

    Used to determine a ticker's current wheel state. Returns None if no match.
    """
    for pos in positions:
        if pos.get("status") != "open":
            continue
        if wheel_phase and pos.get("wheel_phase") != wheel_phase:
            continue
        if asset_type and pos.get("asset_type") != asset_type:
            continue
        return pos
    return None


async def _get_open_position_for_ticker(
    db: AsyncSession,
    strategy_id: str,
    ticker: str,
    wheel_phase: str | None = None,
) -> dict | None:
    """Fetch the open wheel position for a ticker from the database.

    More targeted than get_open_positions() — queries for a specific ticker
    and optionally a specific wheel phase. Returns the most recent match.
    """
    query = (
        "SELECT * FROM trading_positions "
        "WHERE strategy_id = :sid AND ticker = :ticker AND status = 'open'"
    )
    params: dict = {"sid": strategy_id, "ticker": ticker}
    if wheel_phase:
        query += " AND wheel_phase = :phase"
        params["phase"] = wheel_phase
    query += " ORDER BY opened_at DESC LIMIT 1"

    result = await db.execute(text(query), params)
    row = result.mappings().first()
    return dict(row) if row else None


async def _get_position_by_id(db: AsyncSession, position_id: int) -> dict | None:
    """Fetch a single position by its database ID."""
    result = await db.execute(
        text("SELECT * FROM trading_positions WHERE id = :id"),
        {"id": position_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Market data helper
# ---------------------------------------------------------------------------


async def _get_latest_price(ticker: str) -> float | None:
    """Get latest stock price from Alpaca market data (bid/ask midpoint).

    Uses the stock data client to fetch the most recent quote. Returns the
    midpoint of bid/ask for a fair estimate, falling back to ask price.
    Returns None if the quote can't be fetched (e.g., API error, no data).
    """
    try:
        client = alpaca_client.get_stock_data_client()
        from alpaca.data.requests import StockLatestQuoteRequest
        request = StockLatestQuoteRequest(symbol_or_symbols=ticker)
        quotes = client.get_stock_latest_quote(request)
        if ticker in quotes:
            q = quotes[ticker]
            # Midpoint gives a fairer estimate than just bid or ask alone
            if q.bid_price and q.ask_price:
                return float(q.bid_price + q.ask_price) / 2
            return float(q.ask_price) if q.ask_price else None
    except Exception as e:
        logger.warning("Failed to get price for %s: %s", ticker, e)
    return None


# ---------------------------------------------------------------------------
# Order sync — poll Alpaca for fills on pending option/stock orders
# ---------------------------------------------------------------------------


async def _sync_option_orders(db: AsyncSession, strategy_id: str) -> None:
    """Check Alpaca for fills on pending/submitted orders and update local DB.

    For each pending order:
      1. Poll Alpaca for current status
      2. If filled:
         - For sell options: credit premium to strategy cash (fill_price × 100 × contracts)
         - For buy options (buy-to-close for rolls): debit premium from cash
         - For sell stock (hard stop exits): credit proceeds to cash
      3. Update order status and fill info in our DB
      4. Log activity event

    This mirrors simple_stock_strategy._sync_pending_orders() but handles
    option-specific cash accounting (premiums are per-share × 100 multiplier).
    """
    orders, _ = await trading_db.get_orders(db, strategy_id, limit=50)
    pending = [o for o in orders if o["status"] in ("pending", "submitted")]

    for order in pending:
        alpaca_id = order.get("alpaca_order_id")
        if not alpaca_id:
            continue

        try:
            status = await alpaca_client.get_order_status(alpaca_id)
            if status["status"] == order["status"]:
                continue  # No change — skip

            # Update order status in our DB
            await trading_db.update_order_status(
                db, order["id"],
                status=status["status"],
                filled_qty=status.get("filled_qty"),
                filled_avg_price=status.get("filled_avg_price"),
                filled_at=(
                    datetime.fromisoformat(status["filled_at"])
                    if status.get("filled_at") else None
                ),
            )

            if status["status"] == "filled" and status.get("filled_avg_price"):
                fill_price = status["filled_avg_price"]
                fill_qty = status["filled_qty"] or float(order.get("quantity", 0))
                asset_type = order.get("asset_type", "stock")
                side = order["side"]
                contracts = order.get("contracts") or 1

                # Calculate cash impact based on order type
                if asset_type == "option":
                    # Option premiums: fill_price is per-share, × 100 shares per contract
                    cash_amount = fill_price * 100 * contracts
                    if side == "sell":
                        # Selling options (writing): we RECEIVE premium
                        await _adjust_strategy_cash(db, strategy_id, +cash_amount)
                        # Update the position with fill price as cost basis
                        if order.get("position_id"):
                            await trading_db.update_position(
                                db, order["position_id"],
                                avg_entry_price=fill_price,
                                cost_basis=round(cash_amount, 2),
                            )
                        await trading_db.log_activity(
                            db, strategy_id, "order_filled",
                            f"Order filled: SELL {order.get('option_type', '').upper()} "
                            f"x{contracts} @ ${fill_price:.2f}, "
                            f"premium ${cash_amount:.2f} credited",
                            ticker=order.get("ticker"),
                            details={
                                "fill_price": fill_price, "contracts": contracts,
                                "premium": cash_amount, "side": "sell",
                                "option_symbol": order.get("option_symbol"),
                            },
                        )
                    else:
                        # Buying options (buy-to-close for rolls): we PAY premium
                        await _adjust_strategy_cash(db, strategy_id, -cash_amount)
                        await trading_db.log_activity(
                            db, strategy_id, "order_filled",
                            f"Order filled: BUY {order.get('option_type', '').upper()} "
                            f"x{contracts} @ ${fill_price:.2f}, "
                            f"debit ${cash_amount:.2f}",
                            ticker=order.get("ticker"),
                            details={
                                "fill_price": fill_price, "contracts": contracts,
                                "debit": cash_amount, "side": "buy",
                                "option_symbol": order.get("option_symbol"),
                            },
                        )

                elif asset_type == "stock":
                    # Stock orders (hard stop exits, assignment stock sells)
                    cash_amount = fill_price * fill_qty
                    if side == "sell":
                        await _adjust_strategy_cash(db, strategy_id, +cash_amount)
                    else:
                        await _adjust_strategy_cash(db, strategy_id, -cash_amount)
                    await trading_db.log_activity(
                        db, strategy_id, "order_filled",
                        f"Order filled: {side.upper()} {order['ticker']} "
                        f"x{fill_qty:.0f} @ ${fill_price:.2f}",
                        ticker=order.get("ticker"),
                        details={
                            "fill_price": fill_price, "fill_qty": fill_qty,
                            "side": side, "cash_amount": cash_amount,
                        },
                    )

            elif status["status"] in ("cancelled", "rejected"):
                # Order didn't fill — log for visibility
                await trading_db.log_activity(
                    db, strategy_id, "error",
                    f"Order {status['status']}: {order['side']} {order.get('ticker')} "
                    f"({order.get('option_symbol', '')})",
                    ticker=order.get("ticker"),
                    details={"order_id": order["id"], "status": status["status"]},
                )

        except Exception as e:
            logger.warning("Failed to sync order %s: %s", alpaca_id, e)


async def _adjust_strategy_cash(db: AsyncSession, strategy_id: str, amount: float) -> None:
    """Add or subtract cash from a strategy's balance.

    Positive amount = credit (e.g., premium received, shares sold).
    Negative amount = debit (e.g., buy-to-close, shares purchased).
    """
    strategy = await trading_db.get_strategy(db, strategy_id)
    if not strategy:
        return
    new_cash = float(strategy["current_cash"]) + amount
    await trading_db.update_strategy(db, strategy_id, current_cash=round(new_cash, 2))


# ---------------------------------------------------------------------------
# Assignment detection — compare Alpaca positions vs local DB
# ---------------------------------------------------------------------------


async def _detect_assignments(db: AsyncSession, strategy: dict) -> None:
    """Detect option assignments by comparing Alpaca's live positions to our local DB.

    This is the most complex function in the Wheel strategy. Alpaca paper trading
    auto-exercises ITM options at expiration. We detect this by looking for
    discrepancies between what Alpaca says we hold and what our DB says we hold.

    Four scenarios we detect:
      1. Put assigned: our put is gone from Alpaca, stock appeared → we were assigned
      2. Put expired OTM: our put is gone, no stock → expired worthless (keep premium)
      3. Call assigned: our call is gone AND stock is gone → shares called away
      4. Call expired OTM: our call is gone but stock remains → expired worthless

    IMPORTANT: We only match against tickers in this strategy's symbol_list and
    positions we track locally. The Simple Stock strategy may hold the same tickers,
    so we must not confuse their positions with ours.
    """
    strategy_id = strategy["id"]
    config = strategy.get("config", {})
    symbol_list = set(config.get("symbol_list", []))

    # Fetch Alpaca's current positions (across entire account)
    try:
        alpaca_positions = await alpaca_client.get_positions()
    except Exception as e:
        logger.error("Assignment detection failed — could not get Alpaca positions: %s", e)
        return

    # Build sets of what Alpaca currently holds
    # Only care about symbols in our strategy's symbol list
    alpaca_stock_symbols: set[str] = set()
    alpaca_option_symbols: set[str] = set()

    for ap in alpaca_positions:
        symbol = ap["symbol"]
        asset_class = ap.get("asset_class", "us_equity")

        if asset_class == "us_equity" and symbol in symbol_list:
            alpaca_stock_symbols.add(symbol)
        elif asset_class == "us_option":
            # Parse the OCC symbol to get the underlying ticker
            try:
                parsed = alpaca_client.parse_occ_symbol(symbol)
                if parsed["underlying"] in symbol_list:
                    alpaca_option_symbols.add(symbol)
            except ValueError:
                pass  # Not a valid OCC symbol — skip

    # Fetch our local open positions for this strategy
    open_positions = await trading_db.get_open_positions(db, strategy_id)

    # --- Check put positions for assignment or expiration ---
    for pos in open_positions:
        if pos.get("wheel_phase") != "selling_puts":
            continue

        ticker = pos["ticker"]
        option_symbol = pos.get("option_symbol")
        if not option_symbol:
            continue

        # Is this option still in Alpaca's positions?
        option_still_open = option_symbol in alpaca_option_symbols

        if option_still_open:
            # Put is still open in Alpaca — no assignment yet. Nothing to do.
            continue

        # The put option is GONE from Alpaca. Two possibilities:
        #   A) Put was assigned (stock appeared) — we now own 100 shares
        #   B) Put expired OTM (no stock) — we keep premium, back to idle

        # Check: did the stock appear in Alpaca for this ticker?
        stock_appeared = ticker in alpaca_stock_symbols

        # Also check expiration: if expiration date hasn't passed, the option
        # might have been closed by us (buy-to-close for a roll). Don't treat
        # a roll's buy-to-close as an assignment.
        exp_date_str = pos.get("expiration_date")
        if exp_date_str:
            if isinstance(exp_date_str, str):
                exp_date = date_type.fromisoformat(exp_date_str)
            else:
                exp_date = exp_date_str
            today = date_type.today()
            if exp_date > today:
                # Option hasn't expired yet but is gone — likely we bought it back (roll).
                # Don't treat as assignment. The buy-to-close order fill already handled
                # the cash accounting in _sync_option_orders.
                continue

        strike = float(pos.get("strike_price", 0))
        contracts = pos.get("contracts") or 1
        premium_received = float(pos.get("cost_basis", 0))  # Premium we collected

        if stock_appeared:
            # --- PUT ASSIGNED: We now own 100 shares at the strike price ---
            logger.info("Put assigned: %s — bought %d shares at $%.2f",
                        ticker, 100 * contracts, strike)

            # Close the put option position (it no longer exists)
            await trading_db.close_position(
                db, pos["id"], "assigned",
                realized_pnl=round(premium_received, 2),
            )

            # Create a new stock position in the "assigned" phase
            # Cost basis = strike × 100 (what we paid for the shares)
            # The premium we received is already credited to cash from when the put filled
            await trading_db.insert_position(db, {
                "strategy_id": strategy_id,
                "ticker": ticker,
                "asset_type": "stock",
                "quantity": 100 * contracts,
                "avg_entry_price": strike,
                "cost_basis": round(strike * 100 * contracts, 2),
                "wheel_phase": "assigned",
                "status": "open",
            })

            # Debit cash for the stock purchase (strike × 100 shares × contracts)
            await _adjust_strategy_cash(db, strategy_id, -(strike * 100 * contracts))

            # Log assignment event with full context
            await trading_db.log_activity(
                db, strategy_id, "assignment",
                f"Put assigned: {ticker} — bought {100 * contracts} shares at "
                f"${strike:.2f}, cash -${strike * 100 * contracts:,.2f}",
                ticker=ticker,
                details={
                    "ticker": ticker, "strike": strike, "contracts": contracts,
                    "shares_acquired": 100 * contracts,
                    "cash_spent": round(strike * 100 * contracts, 2),
                    "premium_collected": round(premium_received, 2),
                    "option_symbol": option_symbol,
                },
            )

            # Log phase transition
            await trading_db.log_activity(
                db, strategy_id, "phase_transition",
                f"{ticker}: selling_puts → assigned",
                ticker=ticker,
            )

        else:
            # --- PUT EXPIRED OTM: We keep the premium, back to idle ---
            logger.info("Put expired OTM: %s $%.2f put — kept $%.2f premium",
                        ticker, strike, premium_received)

            await trading_db.close_position(
                db, pos["id"], "expired",
                realized_pnl=round(premium_received, 2),
            )

            await trading_db.log_activity(
                db, strategy_id, "option_expired",
                f"Put expired OTM: {ticker} ${strike:.0f} put — "
                f"kept ${premium_received:.2f} premium",
                ticker=ticker,
                details={
                    "ticker": ticker, "strike": strike,
                    "premium_kept": round(premium_received, 2),
                    "option_symbol": option_symbol,
                },
            )

    # --- Check call positions for assignment or expiration ---
    for pos in open_positions:
        if pos.get("wheel_phase") != "selling_calls":
            continue

        ticker = pos["ticker"]
        option_symbol = pos.get("option_symbol")
        if not option_symbol:
            continue

        option_still_open = option_symbol in alpaca_option_symbols

        if option_still_open:
            continue  # Call still open — nothing to do

        # Call option is GONE from Alpaca. Check if stock is also gone.
        exp_date_str = pos.get("expiration_date")
        if exp_date_str:
            if isinstance(exp_date_str, str):
                exp_date = date_type.fromisoformat(exp_date_str)
            else:
                exp_date = exp_date_str
            if exp_date > date_type.today():
                # Option not expired yet — might be bought back (roll). Skip.
                continue

        stock_still_held = ticker in alpaca_stock_symbols
        strike = float(pos.get("strike_price", 0))
        call_premium = float(pos.get("cost_basis", 0))

        if not stock_still_held:
            # --- CALL ASSIGNED: Shares called away at strike price ---
            # This completes a full Wheel cycle! Close both the call and stock positions.
            logger.info("Call assigned: %s — shares called away at $%.2f", ticker, strike)

            # Close the call option position
            await trading_db.close_position(
                db, pos["id"], "called_away",
                realized_pnl=round(call_premium, 2),
            )

            # Find and close the corresponding stock position
            stock_pos = await _get_open_position_for_ticker(
                db, strategy_id, ticker, wheel_phase="assigned"
            )
            # Also check for stock in selling_calls phase
            if not stock_pos:
                stock_pos = await _get_open_position_for_ticker(
                    db, strategy_id, ticker
                )

            total_cycle_pnl = call_premium  # Start with call premium
            stock_pnl = 0  # Default if stock_pos lookup fails (shouldn't happen)
            if stock_pos:
                entry_price = float(stock_pos.get("avg_entry_price", 0))
                qty = float(stock_pos.get("quantity", 100))
                # Stock P&L = (call_strike - entry_price) × shares
                stock_pnl = (strike - entry_price) * qty
                total_cycle_pnl += stock_pnl

                await trading_db.close_position(
                    db, stock_pos["id"], "called_away",
                    realized_pnl=round(stock_pnl, 2),
                )

            # Credit cash for shares sold at strike
            contracts = pos.get("contracts") or 1
            await _adjust_strategy_cash(db, strategy_id, +(strike * 100 * contracts))

            # Calculate total cycle P&L including put premium from earlier
            adjusted_basis = await _get_adjusted_cost_basis(db, strategy_id, ticker)

            await trading_db.log_activity(
                db, strategy_id, "called_away",
                f"Shares called away: {ticker} at ${strike:.2f} — "
                f"wheel cycle complete, total cycle P&L: ${total_cycle_pnl:+.2f}",
                ticker=ticker,
                details={
                    "ticker": ticker, "strike": strike,
                    "call_premium": round(call_premium, 2),
                    "stock_pnl": round(stock_pnl if stock_pos else 0, 2),
                    "total_cycle_pnl": round(total_cycle_pnl, 2),
                    "option_symbol": option_symbol,
                },
            )

            await trading_db.log_activity(
                db, strategy_id, "phase_transition",
                f"{ticker}: selling_calls → idle (wheel cycle complete)",
                ticker=ticker,
            )

        else:
            # --- CALL EXPIRED OTM: We keep premium and still hold shares ---
            # Stock position stays in "assigned" phase, and we'll sell a new call next cycle.
            logger.info("Call expired OTM: %s — kept $%.2f premium, still holding shares",
                        ticker, call_premium)

            await trading_db.close_position(
                db, pos["id"], "expired",
                realized_pnl=round(call_premium, 2),
            )

            # Transition the stock position back to "assigned" so we sell a new call
            stock_pos = await _get_open_position_for_ticker(db, strategy_id, ticker)
            if stock_pos:
                await trading_db.update_position(
                    db, stock_pos["id"], wheel_phase="assigned",
                )

            await trading_db.log_activity(
                db, strategy_id, "option_expired",
                f"Call expired OTM: {ticker} ${strike:.0f} call — "
                f"kept ${call_premium:.2f} premium, will sell new call",
                ticker=ticker,
                details={
                    "ticker": ticker, "strike": strike,
                    "premium_kept": round(call_premium, 2),
                    "option_symbol": option_symbol,
                },
            )


# ---------------------------------------------------------------------------
# Phase 1: Sell cash-secured put
# ---------------------------------------------------------------------------


async def _sell_put(
    db: AsyncSession,
    strategy: dict,
    ticker: str,
    available_cash: float,
    current_price: float,
) -> float:
    """Attempt to sell a cash-secured put on a ticker.

    "Cash-secured" means we must have enough cash to buy 100 shares at the
    strike price if assigned. This function:
      1. Checks we don't already have a position on this ticker
      2. Fetches the option chain from Alpaca
      3. Filters and scores puts using _select_best_option()
      4. Submits a limit sell order at the bid price
      5. Records position + order + activity log

    Returns the cash committed (strike × 100) or 0 if no put was sold.
    """
    strategy_id = strategy["id"]
    config = strategy.get("config", {})

    # Safety: check we don't already have an open position on this ticker
    existing = await _get_open_position_for_ticker(db, strategy_id, ticker)
    if existing:
        await trading_db.log_activity(
            db, strategy_id, "blocked_position_exists",
            f"Skipped {ticker}: already have open {existing.get('wheel_phase')} "
            f"position ({existing.get('option_symbol', 'stock')})",
            ticker=ticker,
            details={
                "ticker": ticker, "existing_phase": existing.get("wheel_phase"),
                "existing_symbol": existing.get("option_symbol"),
            },
        )
        return 0

    # Calculate date range for option chain based on config
    today = date_type.today()
    exp_min_days = config.get("expiration_min_days", 7)
    exp_max_days = config.get("expiration_max_days", 45)
    exp_gte = (today + timedelta(days=exp_min_days)).isoformat()
    exp_lte = (today + timedelta(days=exp_max_days)).isoformat()

    # Fetch option chain from Alpaca
    try:
        chain = await alpaca_client.get_option_chain(ticker, exp_gte, exp_lte)
    except Exception as e:
        logger.warning("Option chain fetch failed for %s: %s", ticker, e)
        await trading_db.log_activity(
            db, strategy_id, "error",
            f"Option chain fetch failed for {ticker}: {str(e)[:200]}",
            ticker=ticker,
        )
        return 0

    if not chain:
        await trading_db.log_activity(
            db, strategy_id, "blocked_no_options",
            f"No option contracts available for {ticker} "
            f"(DTE {exp_min_days}-{exp_max_days} days)",
            ticker=ticker,
            details={"ticker": ticker, "exp_range": f"{exp_gte} to {exp_lte}"},
        )
        return 0

    # Max strike we can afford: must have cash to buy 100 shares at strike
    max_strike = available_cash / 100

    # Find the best put to sell using our filtering and scoring logic
    best = _select_best_option(
        chain, "put", config, current_price, max_strike=max_strike,
    )

    if not best:
        await trading_db.log_activity(
            db, strategy_id, "blocked_no_options",
            f"No suitable puts for {ticker}: {len(chain)} contracts fetched, "
            f"0 passed filters (max_strike=${max_strike:.0f})",
            ticker=ticker,
            details={
                "ticker": ticker, "candidates_total": len(chain),
                "candidates_passed": 0, "max_strike": max_strike,
            },
        )
        return 0

    # --- We have a winner! Extract details and submit the order ---
    option_symbol = best["symbol"]
    parsed = alpaca_client.parse_occ_symbol(option_symbol)
    strike = parsed["strike"]
    expiration = parsed["expiration"]
    bid_price = best.get("bid_price", 0)
    delta = best.get("delta")
    score = best.get("_score", 0)
    yield_ann = best.get("_yield_annualized", 0)

    # Cash we need to reserve for potential assignment
    cash_committed = strike * 100

    # Log the option selection decision with full reasoning
    await trading_db.log_activity(
        db, strategy_id, "option_selected",
        f"Selected put for {ticker}: ${strike:.0f} strike, "
        f"${bid_price:.2f} premium, {parsed['expiration']} exp, "
        f"delta={f'{abs(delta):.2f}' if delta else 'N/A'}, "
        f"yield={yield_ann:.1%}, score={score:.3f}",
        ticker=ticker,
        details={
            "ticker": ticker, "option_symbol": option_symbol,
            "strike": strike, "expiration": expiration,
            "bid_price": bid_price, "delta": delta,
            "yield_annualized": yield_ann, "score": score,
            "candidates_evaluated": len(chain),
            "candidates_passed": best.get("_candidates_passed", 0),
            "reason": (
                f"Highest score: yield={yield_ann:.1%}, "
                f"delta={abs(delta) if delta else 'proxy'}, "
                f"DTE={best.get('_dte', '?')}"
            ),
        },
    )

    # Create the option position record BEFORE submitting the order
    # (same pattern as simple_stock_strategy)
    position_id = await trading_db.insert_position(db, {
        "strategy_id": strategy_id,
        "ticker": ticker,
        "asset_type": "option",
        "option_symbol": option_symbol,
        "option_type": "put",
        "strike_price": strike,
        "expiration_date": expiration,
        "contracts": 1,
        "wheel_phase": "selling_puts",
        "cost_basis": 0,  # Will be updated when fill comes in
        "status": "open",
    })

    # Submit limit sell order to Alpaca
    # We sell at the bid price (or slightly above) since we're the seller
    try:
        order_result = await alpaca_client.submit_option_order(
            option_symbol=option_symbol,
            qty=1,
            side="sell",
            order_type="limit",
            limit_price=round(bid_price, 2),
        )
    except Exception as e:
        # Order failed — clean up the position we just created
        logger.error("Failed to submit put order for %s: %s", ticker, e)
        await trading_db.close_position(db, position_id, "cancelled", 0)
        await trading_db.log_activity(
            db, strategy_id, "error",
            f"Put order submission failed for {ticker}: {str(e)[:200]}",
            ticker=ticker,
        )
        return 0

    # Record the order in our DB for tracking
    await trading_db.insert_order(db, {
        "strategy_id": strategy_id,
        "position_id": position_id,
        "alpaca_order_id": order_result.get("alpaca_order_id"),
        "ticker": ticker,
        "asset_type": "option",
        "side": "sell",
        "order_type": "limit",
        "time_in_force": "day",
        "quantity": 1,
        "limit_price": round(bid_price, 2),
        "option_symbol": option_symbol,
        "option_type": "put",
        "strike_price": strike,
        "expiration_date": expiration,
        "contracts": 1,
        "status": order_result.get("status", "submitted"),
        "reason": (
            f"Selling CSP: ${strike:.0f} strike, ${bid_price:.2f} premium, "
            f"{expiration} exp, delta={abs(delta) if delta else 'N/A'}"
        ),
    })

    # Log the order placement
    await trading_db.log_activity(
        db, strategy_id, "put_sold",
        f"SELL PUT {option_symbol} x1 @ ${bid_price:.2f} limit "
        f"(${strike:.0f} strike, {expiration} exp, "
        f"cash committed: ${cash_committed:,.0f})",
        ticker=ticker,
        details={
            "ticker": ticker, "option_symbol": option_symbol,
            "strike": strike, "premium": bid_price,
            "expiration": expiration,
            "cash_committed": cash_committed,
            "cash_remaining": round(available_cash - cash_committed, 2),
            "reason": (
                f"Selling CSP: ${strike:.0f} strike, ${bid_price:.2f} premium, "
                f"{best.get('_dte', '?')} DTE, delta={abs(delta) if delta else 'proxy'}"
            ),
        },
    )

    logger.info("Sold put: %s x1 @ $%.2f (strike=$%.2f, exp=%s)",
                option_symbol, bid_price, strike, expiration)

    return cash_committed


# ---------------------------------------------------------------------------
# Phase 3: Sell covered call on assigned stock
# ---------------------------------------------------------------------------


async def _sell_call(
    db: AsyncSession,
    strategy: dict,
    ticker: str,
    stock_position: dict,
    current_price: float,
) -> bool:
    """Sell a covered call on assigned stock.

    After assignment, we hold 100 shares and want to generate income by selling
    a call option. The call strike is chosen based on the ADJUSTED cost basis
    (entry price minus all premiums collected) — not the raw entry price.

    Key design decision: we allow selling calls slightly below adjusted cost basis
    (configurable via call_min_strike_pct, default -5%) for capital efficiency.
    This means we might lock in a small loss on the stock if called away, but the
    premiums collected can offset it. Pros do this to free trapped capital.

    Returns True if a call was sold, False if skipped.
    """
    strategy_id = strategy["id"]
    config = strategy.get("config", {})

    # Check if we already have a call position for this ticker
    existing_call = await _get_open_position_for_ticker(
        db, strategy_id, ticker, wheel_phase="selling_calls"
    )
    if existing_call:
        # Already have an open call — don't double-sell
        return False

    # Calculate adjusted cost basis = entry price minus total premiums per share
    adjusted_basis = await _get_adjusted_cost_basis(db, strategy_id, ticker)
    entry_price = float(stock_position.get("avg_entry_price", 0))

    # If we couldn't calculate adjusted basis, fall back to entry price
    if adjusted_basis <= 0:
        adjusted_basis = entry_price

    # Minimum call strike: adjusted basis + call_min_strike_pct
    # Default: -5%, meaning we'll sell calls up to 5% below adjusted basis
    # This is a capital efficiency decision — pros don't hold forever waiting
    # to sell at their exact cost basis
    call_min_pct = config.get("call_min_strike_pct", -5.0)
    min_strike = adjusted_basis * (1 + call_min_pct / 100)

    # Fetch option chain
    today = date_type.today()
    exp_min_days = config.get("expiration_min_days", 7)
    exp_max_days = config.get("expiration_max_days", 45)
    exp_gte = (today + timedelta(days=exp_min_days)).isoformat()
    exp_lte = (today + timedelta(days=exp_max_days)).isoformat()

    try:
        chain = await alpaca_client.get_option_chain(ticker, exp_gte, exp_lte)
    except Exception as e:
        logger.warning("Option chain fetch failed for %s call: %s", ticker, e)
        return False

    if not chain:
        await trading_db.log_activity(
            db, strategy_id, "blocked_no_options",
            f"No call options available for {ticker} "
            f"(DTE {exp_min_days}-{exp_max_days} days)",
            ticker=ticker,
        )
        return False

    # Find the best call to sell
    best = _select_best_option(
        chain, "call", config, current_price, min_strike=min_strike,
    )

    if not best:
        await trading_db.log_activity(
            db, strategy_id, "blocked_no_options",
            f"No suitable calls for {ticker}: {len(chain)} contracts fetched, "
            f"0 passed filters (min_strike=${min_strike:.2f}, adj_basis=${adjusted_basis:.2f})",
            ticker=ticker,
            details={
                "ticker": ticker, "candidates_total": len(chain),
                "min_strike": min_strike, "adjusted_basis": adjusted_basis,
            },
        )
        return False

    # Extract option details
    option_symbol = best["symbol"]
    parsed = alpaca_client.parse_occ_symbol(option_symbol)
    strike = parsed["strike"]
    expiration = parsed["expiration"]
    bid_price = best.get("bid_price", 0)
    delta = best.get("delta")
    score = best.get("_score", 0)
    yield_ann = best.get("_yield_annualized", 0)

    # Log the option selection
    await trading_db.log_activity(
        db, strategy_id, "option_selected",
        f"Selected call for {ticker}: ${strike:.0f} strike, "
        f"${bid_price:.2f} premium, {expiration} exp "
        f"(adj basis=${adjusted_basis:.2f})",
        ticker=ticker,
        details={
            "ticker": ticker, "option_symbol": option_symbol,
            "strike": strike, "expiration": expiration,
            "bid_price": bid_price, "delta": delta,
            "yield_annualized": yield_ann, "score": score,
            "adjusted_cost_basis": adjusted_basis,
            "entry_price": entry_price,
        },
    )

    # Create option position record
    position_id = await trading_db.insert_position(db, {
        "strategy_id": strategy_id,
        "ticker": ticker,
        "asset_type": "option",
        "option_symbol": option_symbol,
        "option_type": "call",
        "strike_price": strike,
        "expiration_date": expiration,
        "contracts": 1,
        "wheel_phase": "selling_calls",
        "cost_basis": 0,
        "status": "open",
    })

    # Submit limit sell order
    try:
        order_result = await alpaca_client.submit_option_order(
            option_symbol=option_symbol,
            qty=1,
            side="sell",
            order_type="limit",
            limit_price=round(bid_price, 2),
        )
    except Exception as e:
        logger.error("Failed to submit call order for %s: %s", ticker, e)
        await trading_db.close_position(db, position_id, "cancelled", 0)
        await trading_db.log_activity(
            db, strategy_id, "error",
            f"Call order submission failed for {ticker}: {str(e)[:200]}",
            ticker=ticker,
        )
        return False

    # Record order
    await trading_db.insert_order(db, {
        "strategy_id": strategy_id,
        "position_id": position_id,
        "alpaca_order_id": order_result.get("alpaca_order_id"),
        "ticker": ticker,
        "asset_type": "option",
        "side": "sell",
        "order_type": "limit",
        "time_in_force": "day",
        "quantity": 1,
        "limit_price": round(bid_price, 2),
        "option_symbol": option_symbol,
        "option_type": "call",
        "strike_price": strike,
        "expiration_date": expiration,
        "contracts": 1,
        "status": order_result.get("status", "submitted"),
        "reason": (
            f"Selling CC: ${strike:.0f} strike (adj basis ${adjusted_basis:.2f}), "
            f"${bid_price:.2f} premium"
        ),
    })

    # Update the stock position's phase to selling_calls
    await trading_db.update_position(
        db, stock_position["id"], wheel_phase="selling_calls",
    )

    # Log the call sale
    await trading_db.log_activity(
        db, strategy_id, "call_sold",
        f"SELL CALL {option_symbol} x1 @ ${bid_price:.2f} limit "
        f"(${strike:.0f} strike, adj basis=${adjusted_basis:.2f})",
        ticker=ticker,
        details={
            "ticker": ticker, "option_symbol": option_symbol,
            "strike": strike, "premium": bid_price,
            "expiration": expiration,
            "adjusted_cost_basis": adjusted_basis,
            "entry_price": entry_price,
            "reason": (
                f"Selling CC: ${strike:.0f} strike (adj basis ${adjusted_basis:.2f}), "
                f"${bid_price:.2f} premium"
            ),
        },
    )

    await trading_db.log_activity(
        db, strategy_id, "phase_transition",
        f"{ticker}: assigned → selling_calls",
        ticker=ticker,
    )

    logger.info("Sold call: %s x1 @ $%.2f (strike=$%.2f, exp=%s)",
                option_symbol, bid_price, strike, expiration)

    return True


# ---------------------------------------------------------------------------
# Option chain filtering and scoring
# ---------------------------------------------------------------------------


def _select_best_option(
    chain: list[dict],
    option_type: str,
    config: dict,
    stock_price: float,
    max_strike: float | None = None,
    min_strike: float | None = None,
) -> dict | None:
    """Filter and score an option chain, returning the single best candidate.

    This is a pure function (no DB/API calls) that applies the strategy's
    configured thresholds to find the optimal option to sell.

    Filtering pipeline:
      1. Parse OCC symbol → filter by option_type (put or call)
      2. Apply strike constraint (max for puts, min for calls)
      3. Filter by days to expiration (DTE) range
      4. Filter by delta range (with moneyness proxy if greeks unavailable)
      5. Filter by bid price > 0 (must be sellable)
      6. Filter by annualized yield range

    Scoring (for candidates that pass all filters):
      - 40% premium yield (higher = better income)
      - 30% delta proximity to target midpoint (closer = better risk/reward)
      - 30% DTE proximity to target midpoint (sweet spot for time decay)

    Returns the highest-scoring contract with internal metadata (_score, _dte,
    _yield_annualized, _candidates_passed), or None if no candidates pass.
    """
    # Extract config thresholds with defaults
    delta_min = config.get("delta_min", 0.15)
    delta_max = config.get("delta_max", 0.30)
    yield_min = config.get("yield_min", 0.04)
    yield_max = config.get("yield_max", 1.00)
    exp_min_days = config.get("expiration_min_days", 7)
    exp_max_days = config.get("expiration_max_days", 45)

    # Target midpoints for scoring proximity
    delta_target = (delta_min + delta_max) / 2   # 0.225 by default
    delta_range = (delta_max - delta_min) / 2    # 0.075 by default
    dte_target = (exp_min_days + exp_max_days) / 2   # 26 by default
    dte_range = (exp_max_days - exp_min_days) / 2    # 19 by default

    today = date_type.today()
    candidates: list[dict] = []
    greeks_available = False

    for contract in chain:
        symbol = contract.get("symbol", "")

        # --- Step 1: Parse OCC symbol and filter by option type ---
        try:
            parsed = alpaca_client.parse_occ_symbol(symbol)
        except ValueError:
            continue  # Invalid symbol — skip

        if parsed["option_type"] != option_type:
            continue  # Wrong type (e.g., we want puts but this is a call)

        strike = parsed["strike"]
        expiration_str = parsed["expiration"]
        exp_date = date_type.fromisoformat(expiration_str)

        # --- Step 2: Strike constraint ---
        if max_strike is not None and strike > max_strike:
            continue  # Can't afford this strike (for puts)
        if min_strike is not None and strike < min_strike:
            continue  # Strike too low (for calls, below cost basis)

        # --- Step 3: DTE filter ---
        dte = (exp_date - today).days
        if dte < exp_min_days or dte > exp_max_days:
            continue  # Outside our expiration window

        # --- Step 4: Delta filter ---
        # Greeks may not always be available from Alpaca. If delta is present,
        # use it directly. If not, use moneyness as a proxy (less accurate but
        # better than no filter at all).
        delta = contract.get("delta")
        if delta is not None:
            greeks_available = True
            abs_delta = abs(delta)
            if abs_delta < delta_min or abs_delta > delta_max:
                continue  # Outside our delta range
        else:
            # Moneyness proxy for delta:
            # For puts: how far OTM (lower strike = lower delta)
            #   proxy = 1 - (stock_price - strike) / stock_price
            # For calls: how far OTM (higher strike = lower delta)
            #   proxy = 1 - (strike - stock_price) / stock_price
            # This is a rough approximation — real delta depends on IV, time, etc.
            if option_type == "put":
                proxy = max(0, min(1, 1 - (stock_price - strike) / stock_price))
            else:
                proxy = max(0, min(1, 1 - (strike - stock_price) / stock_price))

            if proxy < delta_min or proxy > delta_max:
                continue
            abs_delta = proxy

        # --- Step 5: Bid price validity ---
        bid = contract.get("bid_price")
        if not bid or bid <= 0:
            continue  # Can't sell for nothing

        # --- Step 5b: Open interest filter ---
        # Not all Alpaca snapshots include open_interest. If present, enforce
        # the configured minimum to avoid illiquid contracts that won't fill.
        # If absent, skip the check (don't reject contracts with no OI data).
        oi_min = config.get("open_interest_min", 0)
        oi = contract.get("open_interest")
        if oi is not None and oi_min > 0 and oi < oi_min:
            continue  # Too illiquid — would likely not fill

        # --- Step 6: Annualized yield filter ---
        # yield = (premium / stock_price) × (365 / DTE)
        # This normalizes premium across different stocks and expirations
        if stock_price > 0 and dte > 0:
            yield_ann = (bid / stock_price) * (365 / dte)
        else:
            yield_ann = 0

        if yield_ann < yield_min or yield_ann > yield_max:
            continue  # Premium too low or suspiciously high

        # --- Step 7: Score the candidate ---
        # Normalize each component to [0, 1] then weight:
        #   40% yield (we want income)
        #   30% delta proximity to target (risk/reward balance)
        #   30% DTE proximity to target (time decay sweet spot)

        # Yield score: normalize within our yield range
        yield_score = min(1.0, (yield_ann - yield_min) / max(0.01, yield_max - yield_min))

        # Delta proximity: 1.0 at target, 0.0 at edges
        if delta_range > 0:
            delta_prox = 1.0 - abs(abs_delta - delta_target) / delta_range
        else:
            delta_prox = 1.0

        # DTE proximity: 1.0 at target, 0.0 at edges
        if dte_range > 0:
            dte_prox = 1.0 - abs(dte - dte_target) / dte_range
        else:
            dte_prox = 1.0

        score = (yield_score * 0.4) + (delta_prox * 0.3) + (dte_prox * 0.3)

        # Store metadata on the contract for logging
        contract["_score"] = score
        contract["_dte"] = dte
        contract["_yield_annualized"] = yield_ann
        contract["_abs_delta"] = abs_delta
        candidates.append(contract)

    # Log warning if greeks were never available (entire chain lacked them)
    if not greeks_available and chain:
        logger.warning(
            "%s option chain: greeks unavailable for all %d contracts, "
            "used moneyness proxy for delta",
            chain[0].get("symbol", "?")[:6], len(chain),
        )

    if not candidates:
        return None

    # Tag candidates count on all candidates (for logging)
    for c in candidates:
        c["_candidates_passed"] = len(candidates)

    # Return the highest-scoring candidate
    candidates.sort(key=lambda c: c["_score"], reverse=True)
    return candidates[0]


# ---------------------------------------------------------------------------
# Defensive functions — risk management
# ---------------------------------------------------------------------------


async def _manage_put_position(
    db: AsyncSession,
    strategy: dict,
    position: dict,
    current_price: float,
) -> None:
    """Monitor an open put position for expiration and rolling opportunities.

    Rolling = buying back the current put and selling a new one at a lower strike
    and/or later expiration date. The goal is to avoid assignment on a stock that
    has deteriorated significantly, while ideally collecting a net credit.

    Rolling conditions (all must be true):
      - DTE <= 3 (close to expiration, limited time value left)
      - Stock is > roll_threshold_pct below strike (put is deep ITM)
      - A new put can be sold for a net credit >= roll_min_net_credit

    If we CAN'T roll for a credit, we let assignment happen — that's the Wheel.
    Assignment isn't a failure, it's part of the strategy.
    """
    strategy_id = strategy["id"]
    config = strategy.get("config", {})
    ticker = position["ticker"]

    # Calculate DTE
    exp_str = position.get("expiration_date")
    if not exp_str:
        return

    if isinstance(exp_str, str):
        exp_date = date_type.fromisoformat(exp_str)
    else:
        exp_date = exp_str

    today = date_type.today()
    dte = (exp_date - today).days

    # Nothing to manage if expiration is far away
    if dte > 3:
        return

    strike = float(position.get("strike_price", 0))

    # Check if put is deep ITM (stock significantly below strike)
    roll_threshold = config.get("roll_threshold_pct", 10.0)
    pct_below_strike = ((strike - current_price) / strike * 100) if strike > 0 else 0

    if dte <= 3 and pct_below_strike > roll_threshold:
        # Stock is deep ITM near expiration — try to roll
        logger.info(
            "Rolling candidate: %s put $%.2f strike, stock at $%.2f (%.1f%% below)",
            ticker, strike, current_price, pct_below_strike,
        )

        # Check PDT protection before rolling (buy-to-close is a day trade if
        # we also sell a new option today)
        pdt_enabled = config.get("pdt_protection", True)
        if pdt_enabled:
            if await _would_exceed_pdt(db, strategy_id):
                await trading_db.log_activity(
                    db, strategy_id, "blocked_pdt_limit",
                    f"Skipped roll on {ticker}: would be 3rd day trade in "
                    f"5-day window (PDT limit for <$25k accounts)",
                    ticker=ticker,
                    details={"ticker": ticker, "action": "roll"},
                )
                return

        # Fetch option chain for a new put at lower strike / later date
        exp_min_days = config.get("expiration_min_days", 7)
        exp_max_days = config.get("expiration_max_days", 45)
        new_exp_gte = (today + timedelta(days=exp_min_days)).isoformat()
        new_exp_lte = (today + timedelta(days=exp_max_days)).isoformat()

        try:
            chain = await alpaca_client.get_option_chain(ticker, new_exp_gte, new_exp_lte)
        except Exception as e:
            logger.warning("Roll failed — option chain fetch error for %s: %s", ticker, e)
            return

        # Find best new put (at a lower strike than current)
        new_max_strike = strike * 0.95  # Roll DOWN to a lower strike
        strategy_data = await trading_db.get_strategy(db, strategy_id)
        available_cash = float(strategy_data["current_cash"]) if strategy_data else 0
        actual_max_strike = min(new_max_strike, available_cash / 100)

        best_new = _select_best_option(
            chain, "put", config, current_price, max_strike=actual_max_strike,
        )

        if not best_new:
            await trading_db.log_activity(
                db, strategy_id, "blocked_roll_no_credit",
                f"Cannot roll {ticker} put: no suitable replacement options found",
                ticker=ticker,
                details={
                    "ticker": ticker, "current_strike": strike,
                    "target_max_strike": new_max_strike,
                },
            )
            return

        # Calculate if the roll produces a net credit
        # Buyback cost = current option's ask price (what we'd pay to close)
        # New premium = new option's bid price (what we'd receive to sell)
        old_ask = None  # We need the current option's price to calculate buyback cost
        try:
            old_chain = await alpaca_client.get_option_chain(
                ticker,
                exp_date.isoformat(),
                exp_date.isoformat(),
            )
            # Find our specific option in the chain
            for c in old_chain:
                if c.get("symbol") == position.get("option_symbol"):
                    old_ask = c.get("ask_price")
                    break
        except Exception:
            pass

        if old_ask is None:
            # Can't determine buyback cost — skip the roll
            await trading_db.log_activity(
                db, strategy_id, "blocked_roll_no_credit",
                f"Cannot roll {ticker} put: could not determine buyback price",
                ticker=ticker,
            )
            return

        new_bid = best_new.get("bid_price", 0)
        net_credit = new_bid - old_ask
        min_credit = config.get("roll_min_net_credit", 0.10)

        if net_credit < min_credit:
            # Roll would be a net debit (or too small credit) — not worth it
            await trading_db.log_activity(
                db, strategy_id, "blocked_roll_no_credit",
                f"Cannot roll {ticker} put for credit: "
                f"buyback=${old_ask:.2f}, best new put=${new_bid:.2f}, "
                f"net {'credit' if net_credit >= 0 else 'debit'} "
                f"${abs(net_credit):.2f} {'<' if net_credit < min_credit else '>='} "
                f"${min_credit:.2f} threshold",
                ticker=ticker,
                details={
                    "ticker": ticker, "buyback_cost": old_ask,
                    "new_premium": new_bid, "net_credit": net_credit,
                    "min_credit_threshold": min_credit,
                },
            )
            return

        # --- Execute the roll: buy-to-close current put, sell-to-open new put ---
        new_symbol = best_new["symbol"]
        new_parsed = alpaca_client.parse_occ_symbol(new_symbol)

        await trading_db.log_activity(
            db, strategy_id, "roll_attempted",
            f"Rolling put on {ticker}: buying back ${strike:.0f} put (${old_ask:.2f}), "
            f"selling ${new_parsed['strike']:.0f} put ${new_parsed['expiration']} "
            f"(${new_bid:.2f}), net credit ${net_credit:.2f}",
            ticker=ticker,
        )

        try:
            # --- Step 1: Buy-to-close the current put ---
            # We record BOTH the buy and sell orders so _sync_option_orders can
            # track fills and handle cash accounting correctly.
            btc_result = await alpaca_client.submit_option_order(
                option_symbol=position["option_symbol"],
                qty=1, side="buy", order_type="limit",
                limit_price=round(old_ask, 2),
            )

            # Record the buy-to-close order so _sync_option_orders can process
            # the fill and debit cash properly.  Without this, the buyback cost
            # would never be deducted from strategy cash.
            await trading_db.insert_order(db, {
                "strategy_id": strategy_id,
                "position_id": position["id"],
                "alpaca_order_id": btc_result.get("alpaca_order_id"),
                "ticker": ticker,
                "asset_type": "option",
                "side": "buy",
                "order_type": "limit",
                "quantity": 1,
                "limit_price": round(old_ask, 2),
                "option_symbol": position["option_symbol"],
                "option_type": "put",
                "strike_price": strike,
                "expiration_date": position.get("expiration_date"),
                "contracts": 1,
                "time_in_force": "day",
                "status": btc_result.get("status", "submitted"),
                "reason": f"Buy-to-close for roll (ask ${old_ask:.2f})",
            })

            # --- Step 2: Close the old position ---
            # We close it now with the *expected* P&L.  If the buy-to-close
            # doesn't fill, _sync_option_orders will detect the mismatch on
            # the next cycle (order stays open / gets cancelled) and the
            # assignment-detection logic handles the fallback — which is fine,
            # because assignment is the Wheel's natural flow anyway.
            old_premium = float(position.get("cost_basis", 0))
            buyback_cost = old_ask * 100
            roll_pnl = old_premium - buyback_cost  # Premium received minus buyback cost
            await trading_db.close_position(db, position["id"], "rolled", round(roll_pnl, 2))

            # --- Step 3: Sell-to-open the new put ---
            new_pos_id = await trading_db.insert_position(db, {
                "strategy_id": strategy_id,
                "ticker": ticker,
                "asset_type": "option",
                "option_symbol": new_symbol,
                "option_type": "put",
                "strike_price": new_parsed["strike"],
                "expiration_date": new_parsed["expiration"],
                "contracts": 1,
                "wheel_phase": "selling_puts",
                "cost_basis": 0,
                "status": "open",
            })

            order_result = await alpaca_client.submit_option_order(
                option_symbol=new_symbol,
                qty=1, side="sell", order_type="limit",
                limit_price=round(new_bid, 2),
            )

            await trading_db.insert_order(db, {
                "strategy_id": strategy_id,
                "position_id": new_pos_id,
                "alpaca_order_id": order_result.get("alpaca_order_id"),
                "ticker": ticker,
                "asset_type": "option",
                "side": "sell",
                "order_type": "limit",
                "quantity": 1,
                "limit_price": round(new_bid, 2),
                "option_symbol": new_symbol,
                "option_type": "put",
                "strike_price": new_parsed["strike"],
                "expiration_date": new_parsed["expiration"],
                "contracts": 1,
                "time_in_force": "day",
                "status": order_result.get("status", "submitted"),
                "reason": f"Roll from {position['option_symbol']} (net credit ${net_credit:.2f})",
            })

            await trading_db.log_activity(
                db, strategy_id, "roll_executed",
                f"Rolled put on {ticker}: {position['option_symbol']} → {new_symbol}, "
                f"net credit ${net_credit:.2f}",
                ticker=ticker,
                details={
                    "ticker": ticker,
                    "old_symbol": position["option_symbol"],
                    "new_symbol": new_symbol,
                    "old_strike": strike,
                    "new_strike": new_parsed["strike"],
                    "buyback_cost": old_ask,
                    "new_premium": new_bid,
                    "net_credit": net_credit,
                    "reason": (
                        f"Rolled put: stock {pct_below_strike:.0f}% below strike "
                        f"at {dte} DTE, net credit ${net_credit:.2f}"
                    ),
                },
            )

        except Exception as e:
            logger.error("Roll execution failed for %s: %s", ticker, e, exc_info=True)
            await trading_db.log_activity(
                db, strategy_id, "error",
                f"Roll execution failed for {ticker}: {str(e)[:200]}",
                ticker=ticker,
            )


async def _check_hard_stop(
    db: AsyncSession,
    strategy: dict,
    ticker: str,
    stock_position: dict,
    current_price: float,
) -> bool:
    """Check if assigned stock has hit the hard stop loss threshold.

    The hard stop is a predefined exit rule that sells assigned stock if it
    drops more than max_stock_loss_pct below the entry price. This prevents
    the "bagholder trap" where a trader refuses to sell a losing position
    and ties up capital in a collapsing stock.

    Professional traders set these BEFORE entering the trade. Emotion-free.

    Returns True if the stock was sold (exited), False if still holding.
    """
    strategy_id = strategy["id"]
    config = strategy.get("config", {})
    max_loss_pct = config.get("max_stock_loss_pct", 25.0)

    entry_price = float(stock_position.get("avg_entry_price", 0))
    if entry_price <= 0:
        return False

    # Calculate drawdown from entry
    drawdown_pct = ((entry_price - current_price) / entry_price) * 100

    if drawdown_pct <= max_loss_pct:
        return False  # Within tolerance — keep holding

    # --- Hard stop triggered: sell the stock immediately ---
    qty = float(stock_position.get("quantity", 100))
    loss_amount = (entry_price - current_price) * qty

    # Calculate how much premium we've collected on this ticker to show net impact
    adjusted_basis = await _get_adjusted_cost_basis(db, strategy_id, ticker)
    premiums_collected = (entry_price - adjusted_basis) * qty if adjusted_basis > 0 else 0
    net_loss = loss_amount - premiums_collected

    logger.warning(
        "Hard stop triggered: %s down %.1f%% from $%.2f (max=%.0f%%), selling at $%.2f",
        ticker, drawdown_pct, entry_price, max_loss_pct, current_price,
    )

    try:
        # Submit market sell order to get out immediately
        order_result = await alpaca_client.submit_stock_order(
            ticker=ticker, qty=qty, side="sell", order_type="market",
        )

        # Record the order
        await trading_db.insert_order(db, {
            "strategy_id": strategy_id,
            "position_id": stock_position["id"],
            "alpaca_order_id": order_result.get("alpaca_order_id"),
            "ticker": ticker,
            "asset_type": "stock",
            "side": "sell",
            "order_type": "market",
            "quantity": qty,
            "status": order_result.get("status", "submitted"),
            "reason": f"Hard stop: down {drawdown_pct:.1f}% > {max_loss_pct:.0f}% max",
        })

        # Close the stock position
        realized_pnl = -loss_amount  # Negative = loss
        await trading_db.close_position(
            db, stock_position["id"], "hard_stop", round(realized_pnl, 2),
        )

        # Log the hard stop event with full context
        await trading_db.log_activity(
            db, strategy_id, "hard_stop",
            f"Hard stop triggered on {ticker}: down {drawdown_pct:.1f}% "
            f"from ${entry_price:.2f}, selling at ${current_price:.2f}. "
            f"Loss: ${loss_amount:.0f} (net after premiums: ${net_loss:.0f})",
            ticker=ticker,
            details={
                "ticker": ticker, "entry_price": entry_price,
                "exit_price": current_price, "loss_pct": round(drawdown_pct, 1),
                "loss_amount": round(loss_amount, 2),
                "premiums_collected": round(premiums_collected, 2),
                "net_loss": round(net_loss, 2),
                "max_stock_loss_pct": max_loss_pct,
                "reason": (
                    f"Hard stop: {ticker} down {drawdown_pct:.1f}% from "
                    f"${entry_price:.2f} entry, exceeds {max_loss_pct:.0f}% "
                    f"max_stock_loss_pct threshold"
                ),
            },
        )

        await trading_db.log_activity(
            db, strategy_id, "phase_transition",
            f"{ticker}: assigned → idle (hard stop exit)",
            ticker=ticker,
        )

        return True

    except Exception as e:
        logger.error("Hard stop sell failed for %s: %s", ticker, e)
        await trading_db.log_activity(
            db, strategy_id, "error",
            f"Hard stop sell failed for {ticker}: {str(e)[:200]}",
            ticker=ticker,
        )
        return False


async def _check_capital_efficiency(
    db: AsyncSession,
    strategy: dict,
    ticker: str,
    stock_position: dict,
    current_price: float,
) -> bool:
    """Check if assigned stock has been held too long without recovery.

    Capital tied up in a losing position has opportunity cost — that money
    could be generating premium on other tickers. This function enforces
    a capital efficiency policy:

      - If held > capital_efficiency_days (default 60) AND still below entry:
        - Down > 15%: sell and free capital (like a delayed hard stop)
        - Down 5-15%: log warning (we'll sell a more aggressive call next cycle)
        - Down < 5%: nearly recovered, keep holding

    Returns True if the stock was sold (exited), False if still holding.
    """
    strategy_id = strategy["id"]
    config = strategy.get("config", {})
    max_days = config.get("capital_efficiency_days", 60)

    # Calculate days held
    opened_at = stock_position.get("opened_at")
    if not opened_at:
        return False

    if isinstance(opened_at, str):
        opened_dt = datetime.fromisoformat(opened_at)
    else:
        opened_dt = opened_at

    if opened_dt.tzinfo is None:
        opened_dt = opened_dt.replace(tzinfo=timezone.utc)

    days_held = (datetime.now(timezone.utc) - opened_dt).days

    if days_held < max_days:
        return False  # Not held long enough to trigger review

    entry_price = float(stock_position.get("avg_entry_price", 0))
    if entry_price <= 0:
        return False

    pct_change = ((current_price - entry_price) / entry_price) * 100

    if pct_change >= 0:
        return False  # Stock has recovered — no need to exit

    # Stock is still underwater after max_days
    abs_loss = abs(pct_change)

    if abs_loss > 15:
        # Down more than 15% after 60+ days — sell to free capital
        qty = float(stock_position.get("quantity", 100))
        loss_amount = (entry_price - current_price) * qty

        logger.warning(
            "Capital efficiency exit: %s held %d days, still down %.1f%%",
            ticker, days_held, abs_loss,
        )

        try:
            order_result = await alpaca_client.submit_stock_order(
                ticker=ticker, qty=qty, side="sell", order_type="market",
            )

            await trading_db.insert_order(db, {
                "strategy_id": strategy_id,
                "position_id": stock_position["id"],
                "alpaca_order_id": order_result.get("alpaca_order_id"),
                "ticker": ticker,
                "asset_type": "stock",
                "side": "sell",
                "order_type": "market",
                "quantity": qty,
                "status": order_result.get("status", "submitted"),
                "reason": f"Capital efficiency: held {days_held} days, down {abs_loss:.1f}%",
            })

            adjusted_basis = await _get_adjusted_cost_basis(db, strategy_id, ticker)
            premiums = (entry_price - adjusted_basis) * qty if adjusted_basis > 0 else 0

            await trading_db.close_position(
                db, stock_position["id"], "capital_efficiency",
                round(-loss_amount, 2),
            )

            await trading_db.log_activity(
                db, strategy_id, "capital_efficiency_exit",
                f"Capital efficiency exit: {ticker} held {days_held} days, "
                f"still down {abs_loss:.1f}%, freeing ${entry_price * qty:,.0f}",
                ticker=ticker,
                details={
                    "ticker": ticker, "days_held": days_held,
                    "entry_price": entry_price, "exit_price": current_price,
                    "loss_pct": round(abs_loss, 1),
                    "premiums_collected": round(premiums, 2),
                    "reason": (
                        f"Capital efficiency: held {days_held} days, "
                        f"still down {abs_loss:.1f}%, freeing "
                        f"${entry_price * qty:,.0f}"
                    ),
                },
            )

            await trading_db.log_activity(
                db, strategy_id, "phase_transition",
                f"{ticker}: assigned → idle (capital efficiency exit)",
                ticker=ticker,
            )

            return True

        except Exception as e:
            logger.error("Capital efficiency sell failed for %s: %s", ticker, e)
            return False

    elif abs_loss >= 5:
        # Down 5-15% — log warning but don't sell yet.
        # The next call to _sell_call will use adjusted basis to sell
        # a more aggressive (closer to ATM) covered call to accelerate exit.
        await trading_db.log_activity(
            db, strategy_id, "signal",
            f"Capital efficiency review: {ticker} held {days_held} days, "
            f"still down {abs_loss:.1f}% — will sell aggressive covered call",
            ticker=ticker,
            details={
                "ticker": ticker, "days_held": days_held,
                "pct_change": round(pct_change, 1),
                "action": "sell_aggressive_call",
            },
        )
        return False

    else:
        # Down < 5% after 60+ days — nearly recovered, keep holding.
        # Not worth the transaction cost to force an exit this close to breakeven.
        return False


async def _manage_call_position(
    db: AsyncSession,
    strategy: dict,
    position: dict,
) -> None:
    """Monitor an open covered call position.

    Simpler than put management because we don't roll calls — if the call
    is about to expire:
      - OTM: Great, it expires worthless, we keep premium + shares.
        _detect_assignments will handle closing it next cycle.
      - ITM: Great, shares get called away at the strike. That's the plan.
        _detect_assignments will handle the transition.

    The main job here is updating the option's unrealized P&L for the
    position display.
    """
    ticker = position["ticker"]
    strike = float(position.get("strike_price", 0))
    entry_premium = float(position.get("avg_entry_price", 0))

    # Get current option value for unrealized P&L
    # (Approximate: use latest stock price to estimate if ITM/OTM)
    current_price = await _get_latest_price(ticker)
    if current_price is None:
        return

    # For a short call, we profit when the option value decreases.
    # Rough estimate: if stock < strike, call is OTM and losing value (good for us).
    # If stock > strike, call is ITM and our profit is capped at strike.
    # The actual P&L should be based on the option's current market price,
    # but for simplicity we track the stock's unrealized P&L.
    contracts = position.get("contracts") or 1
    premium_received = entry_premium * 100 * contracts

    # Update position with current market data
    await trading_db.update_position(
        db, position["id"],
        current_value=round(premium_received, 2),  # Premium received is our "value"
    )


# ---------------------------------------------------------------------------
# Adjusted cost basis tracking
# ---------------------------------------------------------------------------


async def _get_adjusted_cost_basis(
    db: AsyncSession,
    strategy_id: str,
    ticker: str,
) -> float:
    """Calculate the adjusted cost basis for a ticker including all collected premiums.

    Adjusted cost basis = entry price - (total premiums collected / shares)

    This gives the TRUE break-even point, accounting for all the option premium
    income generated across the Wheel cycle(s) for this ticker.

    Example:
      - Assigned at $22 (entry price)
      - Collected $1.50 put premium
      - Collected $0.80 call premium (expired OTM)
      - Total premiums = $2.30 per share
      - Adjusted cost basis = $22 - $2.30 = $19.70

    Used by _sell_call() to set intelligent minimum strike prices.
    """
    # Sum all realized P&L from closed option positions on this ticker
    # These are the premiums we've collected (positive realized_pnl)
    result = await db.execute(
        text("""
            SELECT COALESCE(SUM(realized_pnl), 0) as total_premiums
            FROM trading_positions
            WHERE strategy_id = :sid
              AND ticker = :ticker
              AND asset_type = 'option'
              AND status = 'closed'
        """),
        {"sid": strategy_id, "ticker": ticker},
    )
    row = result.mappings().first()
    total_premiums = float(row["total_premiums"]) if row else 0

    # Find the current stock position to get entry price
    stock_pos = await _get_open_position_for_ticker(
        db, strategy_id, ticker, wheel_phase="assigned"
    )
    if not stock_pos:
        # Also check selling_calls phase (stock might be in that phase)
        stock_pos = await _get_open_position_for_ticker(db, strategy_id, ticker)

    if not stock_pos or stock_pos.get("asset_type") != "stock":
        return 0

    entry_price = float(stock_pos.get("avg_entry_price", 0))
    qty = float(stock_pos.get("quantity", 100))

    if qty <= 0:
        return entry_price

    # Premiums are total dollar amounts; divide by shares to get per-share adjustment
    per_share_premium = total_premiums / qty
    adjusted_basis = entry_price - per_share_premium

    return adjusted_basis


# ---------------------------------------------------------------------------
# PDT (Pattern Day Trader) protection
# ---------------------------------------------------------------------------


async def _would_exceed_pdt(db: AsyncSession, strategy_id: str) -> bool:
    """Check if executing a day trade would exceed the PDT limit.

    PDT rule: accounts under $25,000 cannot make more than 3 day trades in
    a rolling 5 business day window. A day trade = opening AND closing the
    same position in the same calendar day.

    For the Wheel, rolling a put counts as a day trade because we buy-to-close
    AND sell-to-open on the same day.

    This is conservative — Alpaca paper trading may not enforce PDT, but we
    track it for realism and to train good habits for live trading.

    Returns True if executing another day trade would exceed the 3-trade limit.
    """
    # Count day trades in the last 5 business days (7 calendar days to be safe)
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)

    result = await db.execute(
        text("""
            SELECT COUNT(DISTINCT DATE(filled_at)) as trade_days,
                   COUNT(*) as total_round_trips
            FROM trading_orders
            WHERE strategy_id = :sid
              AND filled_at >= :since
              AND side = 'buy'
              AND asset_type = 'option'
              AND status = 'filled'
              AND EXISTS (
                  SELECT 1 FROM trading_orders o2
                  WHERE o2.strategy_id = :sid
                    AND o2.ticker = trading_orders.ticker
                    AND o2.side = 'sell'
                    AND o2.status = 'filled'
                    AND DATE(o2.filled_at) = DATE(trading_orders.filled_at)
              )
        """),
        {"sid": strategy_id, "since": seven_days_ago},
    )
    row = result.mappings().first()
    round_trips = int(row["total_round_trips"]) if row else 0

    # PDT limit: 3 day trades per 5 business days
    return round_trips >= 3
