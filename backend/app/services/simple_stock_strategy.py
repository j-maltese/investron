"""Simple Stock Strategy — AI-powered stock trading using screener scores + GPT-4o signals.

Two-tier signal approach to keep costs low:
  1. Filter: Query pre-computed screener composite scores (free, already in DB).
     Pull top N from the screener for discovery.
  2. Confirm: Only tickers passing the score threshold get sent to GPT-4o
     for a buy/hold/sell signal with confidence rating.

RAG enhancement: daily auto-indexes SEC filings for top candidates, then injects
relevant filing excerpts (risk factors, MD&A, guidance) into trade signal prompts.

Buy logic:
  - Score above min_screener_score AND AI confidence above min_ai_confidence → buy
  - Position sized by max_position_pct of total strategy capital

Sell logic:
  - Stop-loss: price dropped > stop_loss_pct from entry
  - Take-profit: price up > take_profit_pct from entry
  - AI says sell with sufficient confidence

Each cycle syncs pending orders with Alpaca, then evaluates new opportunities.
"""

import json
import logging
from datetime import datetime, timezone, timedelta

import openai
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services import trading_db, alpaca_client
from app.services.ai_context import build_ticker_context
from app.services.filing_indexer import index_company_filings, get_index_status
from app.services.vector_search import search_filing_chunks, format_search_results_for_llm

logger = logging.getLogger(__name__)

# Focused trade-decision prompt — much shorter than the research prompt
TRADE_SIGNAL_PROMPT = """You are a disciplined value investor managing a ${capital:.0f} paper trading portfolio.
Today is {current_date}. Analyze the financial data below and decide whether to {action_type} this stock.

Respond with ONLY valid JSON (no markdown, no explanation outside the JSON):
{{"action": "buy"|"hold"|"sell", "confidence": 0.0-1.0, "reasoning": "1-2 sentence explanation"}}

Rules:
- Only recommend BUY if the stock is clearly undervalued with a margin of safety
- Only recommend SELL if fundamentals have deteriorated, valuation is stretched, or risk/reward is unfavorable
- confidence must reflect how certain you are (0.5 = coin flip, 0.8+ = high conviction)
- Be conservative — when in doubt, HOLD
- If SEC filing excerpts are provided, factor them into your analysis (especially risks, guidance, and recent events)
- Weight recent filings more heavily than older ones

{context_data}"""


async def _get_candidate_tickers(db: AsyncSession, strategy: dict) -> list[dict]:
    """Pull top N stocks from the screener that pass the minimum score threshold.

    No hardcoded watchlist — lets the screener composite scores and AI signals
    decide what's worth buying.
    """
    config = strategy.get("config", {})
    screener_top_n = config.get("screener_top_n", 20)
    min_score = config.get("min_screener_score", 60.0)

    result = await db.execute(
        text("""
            SELECT ticker, composite_score, company_name
            FROM screener_scores
            WHERE composite_score >= :min_score
            ORDER BY composite_score DESC
            LIMIT :top_n
        """),
        {"min_score": min_score, "top_n": screener_top_n},
    )
    candidates = [
        {"ticker": row["ticker"], "composite_score": float(row["composite_score"]), "company_name": row["company_name"]}
        for row in result.mappings().all()
    ]

    logger.info(
        "Simple stock candidates: %d from screener (min_score=%.0f, top_n=%d)",
        len(candidates), min_score, screener_top_n,
    )
    return candidates


async def run_auto_index_cycle(db: AsyncSession, strategy: dict) -> None:
    """Auto-index SEC filings for top screener candidates once daily.

    Indexes tickers that are either never-indexed, in error state, or stale (>7 days).
    Non-blocking for individual failures — one ticker failing won't stop the rest.
    The filing_indexer has per-ticker locks, so concurrent calls are safe.
    """
    settings = get_settings()
    top_n = settings.trading_auto_index_top_n

    candidates = await _get_candidate_tickers(db, strategy)
    tickers_to_check = [c["ticker"] for c in candidates[:top_n]]

    if not tickers_to_check:
        logger.info("Auto-index: no screener candidates to index")
        return

    # Determine which tickers actually need indexing
    tickers_to_index: list[str] = []
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)

    for ticker in tickers_to_check:
        status = await get_index_status(db, ticker)
        if status is None:
            tickers_to_index.append(ticker)
        elif status.get("status") == "error":
            tickers_to_index.append(ticker)
        elif status.get("last_indexed_at"):
            last_indexed = status["last_indexed_at"]
            if isinstance(last_indexed, str):
                last_indexed = datetime.fromisoformat(last_indexed)
            if last_indexed.tzinfo is None:
                last_indexed = last_indexed.replace(tzinfo=timezone.utc)
            if last_indexed < seven_days_ago:
                tickers_to_index.append(ticker)
        # else: recently indexed and ready — skip

    if not tickers_to_index:
        logger.info("Auto-index: all %d candidates already indexed and fresh", len(tickers_to_check))
        return

    logger.info("Auto-index: indexing %d tickers: %s", len(tickers_to_index), tickers_to_index)

    strategy_id = strategy["id"]
    await trading_db.log_activity(
        db, strategy_id, "auto_index",
        f"Starting daily auto-index for {len(tickers_to_index)} tickers: {', '.join(tickers_to_index)}",
        details={"tickers": tickers_to_index},
    )

    indexed_count = 0
    for ticker in tickers_to_index:
        try:
            result = await index_company_filings(db, ticker)
            if result.get("status") == "ready":
                indexed_count += 1
                logger.info("Auto-index: %s complete (%d filings, %d chunks)",
                            ticker, result.get("filings_indexed", 0), result.get("chunks_total", 0))
            else:
                logger.warning("Auto-index: %s finished with status=%s: %s",
                               ticker, result.get("status"), result.get("errors"))
        except Exception as e:
            logger.error("Auto-index: failed for %s: %s", ticker, e)

    await trading_db.log_activity(
        db, strategy_id, "auto_index",
        f"Daily auto-index complete: {indexed_count}/{len(tickers_to_index)} tickers indexed",
        details={"indexed": indexed_count, "attempted": len(tickers_to_index)},
    )


async def _get_ai_trade_signal(
    db: AsyncSession,
    ticker: str,
    action_type: str,
    capital: float,
) -> dict:
    """Call GPT-4o for a trade signal. Returns {action, confidence, reasoning}.

    Builds full financial context (metrics, Graham, growth, financial statements)
    and optionally injects RAG filing excerpts if the ticker has been indexed.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        return {"action": "hold", "confidence": 0, "reasoning": "OpenAI API key not configured"}

    # Full financial context — includes last 3 periods of income/balance/cashflow
    context_data = await build_ticker_context(db, ticker, include_financials=True, include_growth=True)

    # RAG: inject relevant SEC filing excerpts if available
    if settings.trading_rag_enabled:
        try:
            index_status = await get_index_status(db, ticker)
            if index_status and index_status.get("status") == "ready":
                if "buy" in action_type.lower():
                    query = f"{ticker} financial performance revenue earnings growth risks competitive position outlook"
                else:
                    query = f"{ticker} financial risks earnings deterioration guidance warning concerns"

                results = await search_filing_chunks(
                    db, ticker, query,
                    top_k=5,
                    max_tokens=settings.trading_rag_max_tokens,
                    categories=["financial_discussion", "risk_factors", "guidance_outlook"],
                )
                if results:
                    context_data += (
                        "\n\n== SEC FILING EXCERPTS (from indexed 10-K, 10-Q, 8-K filings) ==\n"
                        + format_search_results_for_llm(results)
                    )
                    logger.info("RAG: injected %d filing chunks (%d tokens) for %s trade signal",
                                len(results), sum(r.token_count for r in results), ticker)
        except Exception as e:
            logger.warning("RAG search failed for %s, proceeding without filing context: %s", ticker, e)

    prompt = TRADE_SIGNAL_PROMPT.format(
        capital=capital,
        current_date=datetime.now(timezone.utc).strftime("%B %d, %Y"),
        action_type=action_type,
        context_data=context_data,
    )

    try:
        client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
            temperature=0.3,  # Lower temp for more consistent trade decisions
        )
        content = response.choices[0].message.content.strip()

        # Parse JSON response — strip markdown fences if model wraps them
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        signal = json.loads(content)
        logger.info("AI signal for %s: %s (conf=%.2f)", ticker, signal.get("action"), signal.get("confidence", 0))
        return signal

    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to parse AI signal for %s: %s — raw: %s", ticker, e, content[:200] if 'content' in dir() else "N/A")
        return {"action": "hold", "confidence": 0, "reasoning": f"Parse error: {e}"}
    except Exception as e:
        logger.error("AI signal request failed for %s: %s", ticker, e)
        return {"action": "hold", "confidence": 0, "reasoning": f"API error: {e}"}


async def _sync_pending_orders(db: AsyncSession, strategy_id: str) -> None:
    """Check Alpaca for fills on our pending/submitted orders and update local DB."""
    orders, _ = await trading_db.get_orders(db, strategy_id, limit=50)
    pending = [o for o in orders if o["status"] in ("pending", "pending_new", "submitted", "accepted", "new")]

    for order in pending:
        alpaca_id = order.get("alpaca_order_id")
        if not alpaca_id:
            continue

        try:
            status = await alpaca_client.get_order_status(alpaca_id)
            if status["status"] != order["status"]:
                await trading_db.update_order_status(
                    db, order["id"],
                    status=status["status"],
                    filled_qty=status.get("filled_qty"),
                    filled_avg_price=status.get("filled_avg_price"),
                    filled_at=datetime.fromisoformat(status["filled_at"]) if status.get("filled_at") else None,
                )

                # If order filled, update the position
                if status["status"] == "filled" and status.get("filled_avg_price"):
                    fill_price = status["filled_avg_price"]
                    fill_qty = status["filled_qty"] or float(order.get("quantity", 0))

                    if order["side"] == "buy":
                        # Update position with fill info
                        if order.get("position_id"):
                            await trading_db.update_position(
                                db, order["position_id"],
                                avg_entry_price=fill_price,
                                quantity=fill_qty,
                                cost_basis=round(fill_price * fill_qty, 2),
                                current_value=round(fill_price * fill_qty, 2),
                            )
                        # Deduct cash (portfolio value is recomputed by sync_strategy_pnl)
                        strategy = await trading_db.get_strategy(db, strategy_id)
                        if strategy:
                            new_cash = float(strategy["current_cash"]) - (fill_price * fill_qty)
                            await trading_db.update_strategy(
                                db, strategy_id,
                                current_cash=round(new_cash, 2),
                            )

                    elif order["side"] == "sell":
                        # Close position, calculate realized P&L
                        if order.get("position_id"):
                            pos = await _get_position_by_id(db, order["position_id"])
                            if pos:
                                entry = float(pos.get("avg_entry_price", 0))
                                pnl = (fill_price - entry) * fill_qty
                                await trading_db.close_position(db, order["position_id"], "sold", round(pnl, 2))
                        # Add cash back
                        strategy = await trading_db.get_strategy(db, strategy_id)
                        if strategy:
                            new_cash = float(strategy["current_cash"]) + (fill_price * fill_qty)
                            await trading_db.update_strategy(db, strategy_id, current_cash=round(new_cash, 2))

                    await trading_db.log_activity(
                        db, strategy_id, "order_filled",
                        f"Order filled: {order['side'].upper()} {order['ticker']} x{fill_qty:.2f} @ ${fill_price:.2f}",
                        ticker=order["ticker"],
                        details={"fill_price": fill_price, "fill_qty": fill_qty},
                    )

        except Exception as e:
            logger.warning("Failed to sync order %s: %s", alpaca_id, e)


async def _get_position_by_id(db: AsyncSession, position_id: int) -> dict | None:
    """Fetch a single position by ID."""
    result = await db.execute(
        text("SELECT * FROM trading_positions WHERE id = :id"),
        {"id": position_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def _get_latest_price(ticker: str) -> float | None:
    """Get latest price from Alpaca market data.

    Returns the last trade price when available (actual executed transaction),
    falling back to bid/ask midpoint if no recent trade exists.
    """
    result = await _get_price_details(ticker)
    return result["price"] if result else None


async def _get_price_details(ticker: str) -> dict | None:
    """Fetch detailed price data from Alpaca for audit-quality logging.

    Returns dict with:
      - price: best available price (last trade preferred, then bid/ask midpoint)
      - source: "last_trade" | "bid_ask_midpoint" | "ask_only"
      - bid, ask, last_trade: raw values for logging
    Returns None if all price sources fail.
    """
    try:
        client = alpaca_client.get_stock_data_client()

        # Try last trade first — represents an actual executed transaction,
        # more reliable than bid/ask which can have momentary wide spreads
        from alpaca.data.requests import StockLatestTradeRequest
        trade_req = StockLatestTradeRequest(symbol_or_symbols=ticker)
        trades = client.get_stock_latest_trade(trade_req)
        last_trade = None
        if ticker in trades and trades[ticker].price:
            last_trade = float(trades[ticker].price)

        # Also fetch quote for bid/ask context (useful for logging)
        from alpaca.data.requests import StockLatestQuoteRequest
        quote_req = StockLatestQuoteRequest(symbol_or_symbols=ticker)
        quotes = client.get_stock_latest_quote(quote_req)
        bid, ask = None, None
        if ticker in quotes:
            q = quotes[ticker]
            bid = float(q.bid_price) if q.bid_price else None
            ask = float(q.ask_price) if q.ask_price else None

        # Prefer last trade price — it's an actual transaction
        if last_trade:
            return {
                "price": last_trade,
                "source": "last_trade",
                "last_trade": last_trade,
                "bid": bid,
                "ask": ask,
            }

        # Fall back to bid/ask midpoint
        if bid and ask:
            return {
                "price": (bid + ask) / 2,
                "source": "bid_ask_midpoint",
                "last_trade": None,
                "bid": bid,
                "ask": ask,
            }

        # Last resort: ask price only
        if ask:
            return {
                "price": ask,
                "source": "ask_only",
                "last_trade": None,
                "bid": bid,
                "ask": ask,
            }

    except Exception as e:
        logger.warning("Failed to get price for %s: %s", ticker, e)
    return None


async def run_simple_stock_cycle(db: AsyncSession, strategy: dict) -> None:
    """Run one cycle of the simple stock strategy.

    1. Sync pending orders with Alpaca
    2. Check existing positions for sell signals
    3. Look for new buy opportunities
    """
    strategy_id = strategy["id"]
    config = strategy.get("config", {})
    min_ai_confidence = config.get("min_ai_confidence", 0.7)
    max_position_pct = config.get("max_position_pct", 25.0)
    stop_loss_pct = config.get("stop_loss_pct", 10.0)
    take_profit_pct = config.get("take_profit_pct", 20.0)
    use_ai = config.get("use_ai_signals", True)
    capital = float(strategy["initial_capital"])
    cash = float(strategy["current_cash"])

    logger.info("Simple stock cycle starting (cash=$%.2f)", cash)

    # --- Step 1: Sync pending orders ---
    await _sync_pending_orders(db, strategy_id)

    # --- Step 2: Check existing positions for sell signals ---
    open_positions = await trading_db.get_open_positions(db, strategy_id)
    held_tickers = set()

    for pos in open_positions:
        ticker = pos["ticker"]
        held_tickers.add(ticker)
        entry_price = float(pos.get("avg_entry_price", 0))
        if entry_price <= 0:
            continue

        price_data = await _get_price_details(ticker)
        if not price_data:
            continue
        current_price = price_data["price"]

        qty = float(pos.get("quantity", 0))
        change_pct = ((current_price - entry_price) / entry_price) * 100

        # Update unrealized P&L and current stock price
        unrealized = round((current_price - entry_price) * qty, 2)
        await trading_db.update_position(
            db, pos["id"],
            current_value=round(current_price * qty, 2),
            unrealized_pnl=unrealized,
            underlying_price=round(current_price, 4),
        )

        # Build price context dict for audit logging — included in every sell decision
        price_ctx = {
            "price_used": current_price,
            "price_source": price_data["source"],
            "bid": price_data.get("bid"),
            "ask": price_data.get("ask"),
            "last_trade": price_data.get("last_trade"),
            "entry_price": entry_price,
            "change_pct": round(change_pct, 2),
        }

        # Check stop-loss — re-fetch to confirm before executing.
        # A single bad quote shouldn't trigger an irreversible sell.
        if change_pct <= -stop_loss_pct:
            logger.info("Stop-loss initial trigger for %s (%.1f%%), re-fetching to confirm...", ticker, change_pct)
            confirm_data = await _get_price_details(ticker)
            if confirm_data:
                confirm_price = confirm_data["price"]
                confirm_pct = ((confirm_price - entry_price) / entry_price) * 100
                price_ctx["confirm_price"] = confirm_price
                price_ctx["confirm_source"] = confirm_data["source"]
                price_ctx["confirm_change_pct"] = round(confirm_pct, 2)

                if confirm_pct <= -stop_loss_pct:
                    # Confirmed — use the confirmation price for the sell
                    logger.info("Stop-loss CONFIRMED for %s (%.1f%% on re-fetch)", ticker, confirm_pct)
                    price_ctx["threshold"] = -stop_loss_pct
                    await _execute_sell(db, strategy_id, pos, qty, "stop_loss", confirm_price, price_context=price_ctx)
                    continue
                else:
                    # First fetch was a bad read — log it but don't sell
                    logger.warning(
                        "Stop-loss NOT confirmed for %s: initial=%.1f%% but re-fetch=%.1f%%, skipping",
                        ticker, change_pct, confirm_pct,
                    )
                    await trading_db.log_activity(
                        db, strategy_id, "blocked_stop_loss",
                        f"Stop-loss for {ticker} not confirmed on re-fetch: "
                        f"initial {change_pct:.1f}% → re-fetch {confirm_pct:.1f}% "
                        f"(threshold: {stop_loss_pct:.0f}%)",
                        ticker=ticker,
                        details=price_ctx,
                    )
                    continue

        # Check take-profit
        if change_pct >= take_profit_pct:
            logger.info("Take-profit triggered for %s (%.1f%%)", ticker, change_pct)
            price_ctx["threshold"] = take_profit_pct
            await _execute_sell(db, strategy_id, pos, qty, "take_profit", current_price, price_context=price_ctx)
            continue

        # AI sell check (less frequent — only if AI is enabled)
        if use_ai and qty > 0:
            signal = await _get_ai_trade_signal(db, ticker, "hold or sell", capital)
            if signal.get("action") == "sell" and signal.get("confidence", 0) >= min_ai_confidence:
                logger.info("AI sell signal for %s (conf=%.2f)", ticker, signal["confidence"])
                await _execute_sell(db, strategy_id, pos, qty, "ai_signal", current_price, ai_signal=signal, price_context=price_ctx)
                continue

    # --- Step 3: Look for new buy opportunities ---
    # Refresh cash after any sells
    strategy = await trading_db.get_strategy(db, strategy_id)
    cash = float(strategy["current_cash"])

    # Need enough cash for at least a small position
    min_buy_amount = capital * 0.05  # At least 5% of capital
    if cash < min_buy_amount:
        logger.info("Insufficient cash ($%.2f < $%.2f min), skipping buy scan", cash, min_buy_amount)
        return

    candidates = await _get_candidate_tickers(db, strategy)
    candidates = [c for c in candidates if c["ticker"] not in held_tickers]

    if not candidates:
        logger.info("No buy candidates after filtering")
        return

    # Evaluate top candidates with AI (limit to avoid excessive API costs)
    max_ai_calls = config.get("max_ai_calls_per_cycle", 5)
    evaluated = 0

    for candidate in candidates:
        if evaluated >= max_ai_calls:
            break
        if cash < min_buy_amount:
            break

        ticker = candidate["ticker"]
        score = candidate["composite_score"]

        if use_ai:
            signal = await _get_ai_trade_signal(db, ticker, "buy", capital)
            evaluated += 1

            if signal.get("action") != "buy" or signal.get("confidence", 0) < min_ai_confidence:
                await trading_db.log_activity(
                    db, strategy_id, "signal",
                    f"AI passed on {ticker}: {signal.get('action')} (conf={signal.get('confidence', 0):.2f}) — {signal.get('reasoning', '')[:100]}",
                    ticker=ticker,
                    details={"signal": signal, "screener_score": score},
                )
                continue
        else:
            signal = {"action": "buy", "confidence": score / 100, "reasoning": f"Screener score {score:.1f}"}

        # Calculate position size
        max_amount = cash * (max_position_pct / 100)
        current_price = await _get_latest_price(ticker)
        if current_price is None or current_price <= 0:
            continue

        shares = int(max_amount / current_price)  # Whole shares only
        if shares < 1:
            continue

        buy_amount = shares * current_price

        # Execute buy
        await _execute_buy(db, strategy_id, ticker, shares, current_price, signal, score)
        cash -= buy_amount

    # Sync P&L after all trades
    await trading_db.sync_strategy_pnl(db, strategy_id)
    logger.info("Simple stock cycle complete")


async def _execute_buy(
    db: AsyncSession,
    strategy_id: str,
    ticker: str,
    shares: int,
    estimated_price: float,
    ai_signal: dict,
    screener_score: float,
) -> None:
    """Submit a buy order and create local position/order records."""
    try:
        # Create position record first
        position_id = await trading_db.insert_position(db, {
            "strategy_id": strategy_id,
            "ticker": ticker,
            "asset_type": "stock",
            "quantity": shares,
            "avg_entry_price": estimated_price,
            "cost_basis": round(estimated_price * shares, 2),
            "status": "open",
        })

        # Submit order to Alpaca
        order_result = await alpaca_client.submit_stock_order(
            ticker=ticker, qty=shares, side="buy", order_type="market",
        )

        # Record the order
        await trading_db.insert_order(db, {
            "strategy_id": strategy_id,
            "position_id": position_id,
            "alpaca_order_id": order_result.get("alpaca_order_id"),
            "ticker": ticker,
            "asset_type": "stock",
            "side": "buy",
            "order_type": "market",
            "quantity": shares,
            "status": order_result.get("status", "submitted"),
            "reason": f"Screener score {screener_score:.1f}, AI: {ai_signal.get('reasoning', '')[:200]}",
            "ai_signal": ai_signal,
        })

        await trading_db.log_activity(
            db, strategy_id, "order_placed",
            f"BUY {ticker} x{shares} @ ~${estimated_price:.2f} (score={screener_score:.1f}, AI conf={ai_signal.get('confidence', 0):.2f})",
            ticker=ticker,
            details={"shares": shares, "price": estimated_price, "screener_score": screener_score, "ai_signal": ai_signal},
        )

        logger.info("Buy order placed: %s x%d @ ~$%.2f", ticker, shares, estimated_price)

    except Exception as e:
        logger.error("Failed to execute buy for %s: %s", ticker, e)
        await trading_db.log_activity(
            db, strategy_id, "error",
            f"Buy order failed for {ticker}: {str(e)[:200]}",
            ticker=ticker,
        )


async def _execute_sell(
    db: AsyncSession,
    strategy_id: str,
    position: dict,
    qty: float,
    reason: str,
    current_price: float,
    ai_signal: dict | None = None,
    price_context: dict | None = None,
) -> None:
    """Submit a sell order for an existing position.

    Args:
        price_context: Audit dict with price_used, price_source, bid, ask,
            last_trade, entry_price, change_pct, threshold — logged in activity
            so every sell decision can be traced back to the exact data that
            triggered it.
    """
    ticker = position["ticker"]
    try:
        order_result = await alpaca_client.submit_stock_order(
            ticker=ticker, qty=qty, side="sell", order_type="market",
        )

        await trading_db.insert_order(db, {
            "strategy_id": strategy_id,
            "position_id": position["id"],
            "alpaca_order_id": order_result.get("alpaca_order_id"),
            "ticker": ticker,
            "asset_type": "stock",
            "side": "sell",
            "order_type": "market",
            "quantity": qty,
            "status": order_result.get("status", "submitted"),
            "reason": reason,
            "ai_signal": ai_signal,
        })

        entry = float(position.get("avg_entry_price", 0))
        pnl = round((current_price - entry) * qty, 2)

        # Merge price audit context into the activity details so every sell
        # decision is fully traceable: what price was used, where it came from,
        # what threshold triggered it, and the raw bid/ask/trade data.
        details: dict = {
            "shares": qty, "price": current_price, "reason": reason, "pnl": pnl,
        }
        if price_context:
            details["price_audit"] = price_context
        if ai_signal:
            details["ai_signal"] = ai_signal

        await trading_db.log_activity(
            db, strategy_id, "order_placed",
            f"SELL {ticker} x{qty:.0f} @ ~${current_price:.2f} ({reason}, "
            f"change: {price_context['change_pct']:.1f}%, "
            f"source: {price_context['price_source']})"
            if price_context else
            f"SELL {ticker} x{qty:.0f} @ ~${current_price:.2f} ({reason}, P&L: ${pnl:+.2f})",
            ticker=ticker,
            details=details,
        )

        logger.info("Sell order placed: %s x%.0f @ ~$%.2f (%s)", ticker, qty, current_price, reason)

    except Exception as e:
        logger.error("Failed to execute sell for %s: %s", ticker, e)
        await trading_db.log_activity(
            db, strategy_id, "error",
            f"Sell order failed for {ticker}: {str(e)[:200]}",
            ticker=ticker,
        )
