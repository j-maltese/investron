"""Simple Stock Strategy — AI-powered stock trading using screener scores + GPT-4o signals.

Two-tier signal approach to keep costs low:
  1. Filter: Query pre-computed screener composite scores (free, already in DB).
     Pull top N from the screener for discovery.
  2. Confirm: Only tickers passing the score threshold get sent to GPT-4o
     for a buy/hold/sell signal with confidence rating.

RAG enhancement: daily auto-indexes SEC filings for top candidates, then injects
relevant filing excerpts (risk factors, MD&A, guidance) into trade signal prompts.

Layer 1 Execution Safety (prevents false triggers and bad fills):
  - Price staleness: rejects prices with stale last trade during market hours
  - Bid/ask spread: blocks trades on illiquid stocks (spread > 2%)
  - Independent price confirmation: yfinance cross-check for stop-loss/take-profit
    (falls back to Alpaca bid/ask midpoint if yfinance unavailable)
  - Limit/stop-limit orders: no market orders — controlled entry and exit prices

Buy logic:
  - Score above min_screener_score AND AI confidence above min_ai_confidence → buy
  - Position sized by max_position_pct of total strategy capital
  - Limit order at current price + small buffer (buy_limit_offset_pct)

Sell logic:
  - Stop-loss: stop-limit order (3-layer confirmation: re-fetch + safety checks + yfinance)
  - Take-profit: limit order at current price (with yfinance confirmation)
  - AI says sell with sufficient confidence (limit order, no yfinance needed)

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
from app.services.yfinance_svc import get_quick_price

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
      - trade_timestamp: UTC datetime of last trade (for staleness checks)
      - spread_pct: bid/ask spread as percentage of midpoint (for liquidity checks)
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
        trade_timestamp = None
        if ticker in trades and trades[ticker].price:
            last_trade = float(trades[ticker].price)
            # Alpaca trade objects have a .timestamp attribute (UTC datetime)
            if hasattr(trades[ticker], "timestamp") and trades[ticker].timestamp:
                trade_timestamp = trades[ticker].timestamp

        # Also fetch quote for bid/ask context (useful for logging)
        from alpaca.data.requests import StockLatestQuoteRequest
        quote_req = StockLatestQuoteRequest(symbol_or_symbols=ticker)
        quotes = client.get_stock_latest_quote(quote_req)
        bid, ask = None, None
        if ticker in quotes:
            q = quotes[ticker]
            bid = float(q.bid_price) if q.bid_price else None
            ask = float(q.ask_price) if q.ask_price else None

        # Calculate spread percentage when both bid and ask are available
        spread_pct = None
        if bid and ask and bid > 0:
            midpoint = (bid + ask) / 2
            spread_pct = round(((ask - bid) / midpoint) * 100, 3)

        # Prefer last trade price — it's an actual transaction
        if last_trade:
            return {
                "price": last_trade,
                "source": "last_trade",
                "last_trade": last_trade,
                "bid": bid,
                "ask": ask,
                "trade_timestamp": trade_timestamp,
                "spread_pct": spread_pct,
            }

        # Fall back to bid/ask midpoint
        if bid and ask:
            return {
                "price": (bid + ask) / 2,
                "source": "bid_ask_midpoint",
                "last_trade": None,
                "bid": bid,
                "ask": ask,
                "trade_timestamp": None,
                "spread_pct": spread_pct,
            }

        # Last resort: ask price only
        if ask:
            return {
                "price": ask,
                "source": "ask_only",
                "last_trade": None,
                "bid": bid,
                "ask": ask,
                "trade_timestamp": None,
                "spread_pct": None,
            }

    except Exception as e:
        logger.warning("Failed to get price for %s: %s", ticker, e)
    return None


async def _validate_price_for_trade(
    db: AsyncSession,
    strategy_id: str,
    ticker: str,
    price_data: dict,
    action: str,
) -> dict | None:
    """Run Layer 1 execution safety checks before any trade.

    Checks (in order):
      1. Price staleness — reject if last trade > N seconds old during market hours
      2. Bid/ask spread — reject if spread > N% (illiquid stock or bad data)
      3. Independent confirmation (yfinance) — for irreversible actions only

    Returns None if all checks pass.
    Returns a dict {"blocked": True, "reason": str, "event_type": str} if blocked.
    """
    settings = get_settings()
    price = price_data["price"]

    # --- Check 1: Price staleness during market hours ---
    trade_ts = price_data.get("trade_timestamp")
    if trade_ts and settings.price_staleness_max_seconds > 0:
        now_utc = datetime.now(timezone.utc)
        # Only enforce staleness during US market hours (roughly 9:30-16:00 ET = 14:30-21:00 UTC)
        # Outside market hours, stale prices are expected
        utc_hour = now_utc.hour
        is_market_hours = 14 <= utc_hour <= 21  # Rough UTC approximation of US market hours
        if is_market_hours:
            # Ensure trade_ts is timezone-aware for comparison
            if hasattr(trade_ts, "tzinfo") and trade_ts.tzinfo is None:
                trade_ts = trade_ts.replace(tzinfo=timezone.utc)
            age_seconds = (now_utc - trade_ts).total_seconds()
            if age_seconds > settings.price_staleness_max_seconds:
                reason = (
                    f"Price stale: last trade {age_seconds:.0f}s ago "
                    f"(max {settings.price_staleness_max_seconds}s during market hours)"
                )
                await trading_db.log_activity(
                    db, strategy_id, f"blocked_stale_price",
                    f"{action} {ticker} blocked — {reason}",
                    ticker=ticker,
                    details={"age_seconds": age_seconds, "trade_timestamp": str(trade_ts), **price_data},
                )
                return {"blocked": True, "reason": reason, "event_type": "blocked_stale_price"}

    # --- Check 2: Bid/ask spread ---
    spread_pct = price_data.get("spread_pct")
    if spread_pct is not None and spread_pct > settings.spread_max_pct:
        reason = f"Spread too wide: {spread_pct:.2f}% (max {settings.spread_max_pct:.1f}%)"
        await trading_db.log_activity(
            db, strategy_id, "blocked_wide_spread",
            f"{action} {ticker} blocked — {reason}",
            ticker=ticker,
            details={"spread_pct": spread_pct, "bid": price_data.get("bid"), "ask": price_data.get("ask")},
        )
        return {"blocked": True, "reason": reason, "event_type": "blocked_wide_spread"}

    # --- Check 3: Independent price confirmation via yfinance ---
    # Only for irreversible actions (stop-loss, take-profit) — not routine price updates
    if action in ("stop_loss", "take_profit"):
        try:
            yf_price = await get_quick_price(ticker)
            if yf_price and yf_price > 0:
                divergence_pct = abs(price - yf_price) / yf_price * 100
                if divergence_pct > settings.price_confirm_divergence_pct:
                    reason = (
                        f"Price mismatch: Alpaca=${price:.2f} vs yfinance=${yf_price:.2f} "
                        f"({divergence_pct:.1f}% divergence, max {settings.price_confirm_divergence_pct:.0f}%)"
                    )
                    await trading_db.log_activity(
                        db, strategy_id, f"blocked_{action}_price_mismatch",
                        f"{action} {ticker} blocked — {reason}",
                        ticker=ticker,
                        details={
                            "alpaca_price": price, "yfinance_price": yf_price,
                            "divergence_pct": round(divergence_pct, 2),
                            **price_data,
                        },
                    )
                    return {"blocked": True, "reason": reason, "event_type": f"blocked_{action}_price_mismatch"}
                else:
                    logger.info(
                        "Price confirmed for %s %s: Alpaca=$%.2f, yfinance=$%.2f (%.1f%% divergence)",
                        action, ticker, price, yf_price, divergence_pct,
                    )
            else:
                # yfinance returned no price — fall back to Alpaca bid/ask midpoint cross-check
                bid = price_data.get("bid")
                ask = price_data.get("ask")
                if bid and ask:
                    midpoint = (bid + ask) / 2
                    midpoint_divergence = abs(price - midpoint) / midpoint * 100
                    if midpoint_divergence > settings.price_confirm_divergence_pct:
                        reason = (
                            f"Price vs bid/ask mismatch: trade=${price:.2f} vs midpoint=${midpoint:.2f} "
                            f"({midpoint_divergence:.1f}% divergence) — yfinance unavailable"
                        )
                        await trading_db.log_activity(
                            db, strategy_id, f"blocked_{action}_price_mismatch",
                            f"{action} {ticker} blocked — {reason}",
                            ticker=ticker,
                            details={
                                "alpaca_price": price, "midpoint": midpoint,
                                "divergence_pct": round(midpoint_divergence, 2),
                                "yfinance_fallback": True,
                                **price_data,
                            },
                        )
                        return {"blocked": True, "reason": reason, "event_type": f"blocked_{action}_price_mismatch"}
                logger.warning(
                    "yfinance price unavailable for %s %s confirmation, bid/ask cross-check passed",
                    action, ticker,
                )
        except Exception as e:
            # yfinance failure is not fatal — log and proceed with Alpaca price only
            logger.warning("yfinance confirmation failed for %s %s, proceeding: %s", action, ticker, e)

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
            "trade_timestamp": str(price_data.get("trade_timestamp")),
            "spread_pct": price_data.get("spread_pct"),
            "entry_price": entry_price,
            "change_pct": round(change_pct, 2),
        }

        settings = get_settings()

        # Check stop-loss — multi-layer confirmation before executing:
        # 1. Re-fetch from Alpaca (same-source double-check)
        # 2. Validate: staleness, spread, yfinance cross-check
        # 3. Submit stop-limit order (not market) for controlled execution
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
                    # Alpaca re-fetch confirmed — now run Layer 1 safety checks
                    # (staleness, spread, yfinance independent confirmation)
                    block = await _validate_price_for_trade(
                        db, strategy_id, ticker, confirm_data, "stop_loss",
                    )
                    if block:
                        logger.warning("Stop-loss blocked for %s: %s", ticker, block["reason"])
                        continue

                    logger.info("Stop-loss CONFIRMED for %s (%.1f%% on re-fetch, passed all safety checks)", ticker, confirm_pct)
                    price_ctx["threshold"] = -stop_loss_pct

                    # Stop-limit order: stop at current price, limit slightly below
                    # to avoid runaway fill in a flash crash
                    limit_offset = settings.stop_loss_limit_offset_pct
                    stop_price = round(confirm_price, 2)
                    limit_price = round(confirm_price * (1 - limit_offset / 100), 2)

                    await _execute_sell(
                        db, strategy_id, pos, qty, "stop_loss", confirm_price,
                        price_context=price_ctx,
                        order_type="stop_limit", stop_price=stop_price, limit_price=limit_price,
                    )
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

        # Check take-profit — validate price before executing
        if change_pct >= take_profit_pct:
            logger.info("Take-profit initial trigger for %s (%.1f%%)", ticker, change_pct)

            block = await _validate_price_for_trade(
                db, strategy_id, ticker, price_data, "take_profit",
            )
            if block:
                logger.warning("Take-profit blocked for %s: %s", ticker, block["reason"])
                continue

            price_ctx["threshold"] = take_profit_pct
            # Limit order at current price — ensures we get at least this price
            await _execute_sell(
                db, strategy_id, pos, qty, "take_profit", current_price,
                price_context=price_ctx,
                order_type="limit", limit_price=round(current_price, 2),
            )
            continue

        # AI sell check (less frequent — only if AI is enabled)
        # AI sells use limit orders but skip yfinance confirmation (not triggered by price)
        if use_ai and qty > 0:
            signal = await _get_ai_trade_signal(db, ticker, "hold or sell", capital)
            if signal.get("action") == "sell" and signal.get("confidence", 0) >= min_ai_confidence:
                # Still check staleness and spread (basic data quality) but not yfinance
                block = await _validate_price_for_trade(
                    db, strategy_id, ticker, price_data, "ai_sell",
                )
                if block:
                    logger.warning("AI sell blocked for %s: %s", ticker, block["reason"])
                    continue

                logger.info("AI sell signal for %s (conf=%.2f)", ticker, signal["confidence"])
                await _execute_sell(
                    db, strategy_id, pos, qty, "ai_signal", current_price,
                    ai_signal=signal, price_context=price_ctx,
                    order_type="limit", limit_price=round(current_price * 0.995, 2),
                )
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

        # Calculate position size — need full price data for safety checks
        max_amount = cash * (max_position_pct / 100)
        price_data = await _get_price_details(ticker)
        if price_data is None or price_data["price"] <= 0:
            continue
        current_price = price_data["price"]

        # Run Layer 1 safety checks (staleness + spread, no yfinance for buys)
        block = await _validate_price_for_trade(
            db, strategy_id, ticker, price_data, "buy",
        )
        if block:
            logger.warning("Buy blocked for %s: %s", ticker, block["reason"])
            continue

        shares = int(max_amount / current_price)  # Whole shares only
        if shares < 1:
            continue

        # Limit order: buy at current price + small buffer to ensure fill
        settings = get_settings()
        limit_price = round(current_price * (1 + settings.buy_limit_offset_pct / 100), 2)
        buy_amount = shares * limit_price  # Reserve the limit amount from cash

        await _execute_buy(db, strategy_id, ticker, shares, current_price, signal, score, limit_price=limit_price)
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
    limit_price: float | None = None,
) -> None:
    """Submit a buy order and create local position/order records.

    Uses limit orders by default to control entry price.
    Falls back to market if no limit_price provided.
    """
    order_type = "limit" if limit_price else "market"
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

        # Submit order to Alpaca — limit order to control entry price
        order_result = await alpaca_client.submit_stock_order(
            ticker=ticker, qty=shares, side="buy",
            order_type=order_type, limit_price=limit_price,
        )

        # Record the order
        await trading_db.insert_order(db, {
            "strategy_id": strategy_id,
            "position_id": position_id,
            "alpaca_order_id": order_result.get("alpaca_order_id"),
            "ticker": ticker,
            "asset_type": "stock",
            "side": "buy",
            "order_type": order_type,
            "quantity": shares,
            "status": order_result.get("status", "submitted"),
            "reason": f"Screener score {screener_score:.1f}, AI: {ai_signal.get('reasoning', '')[:200]}",
            "ai_signal": ai_signal,
        })

        price_desc = f"limit=${limit_price:.2f}" if limit_price else f"~${estimated_price:.2f}"
        await trading_db.log_activity(
            db, strategy_id, "order_placed",
            f"BUY {ticker} x{shares} @ {price_desc} (score={screener_score:.1f}, AI conf={ai_signal.get('confidence', 0):.2f})",
            ticker=ticker,
            details={
                "shares": shares, "price": estimated_price, "limit_price": limit_price,
                "order_type": order_type, "screener_score": screener_score, "ai_signal": ai_signal,
            },
        )

        logger.info("Buy %s order placed: %s x%d @ %s", order_type, ticker, shares, price_desc)

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
    order_type: str = "limit",
    limit_price: float | None = None,
    stop_price: float | None = None,
) -> None:
    """Submit a sell order for an existing position.

    Args:
        price_context: Audit dict with price_used, price_source, bid, ask,
            last_trade, entry_price, change_pct, threshold — logged in activity
            so every sell decision can be traced back to the exact data that
            triggered it.
        order_type: "limit", "stop_limit", or "market" (avoid market — no price control)
        limit_price: Required for limit/stop_limit orders
        stop_price: Required for stop_limit orders (trigger price)
    """
    ticker = position["ticker"]
    try:
        order_result = await alpaca_client.submit_stock_order(
            ticker=ticker, qty=qty, side="sell",
            order_type=order_type, limit_price=limit_price, stop_price=stop_price,
        )

        await trading_db.insert_order(db, {
            "strategy_id": strategy_id,
            "position_id": position["id"],
            "alpaca_order_id": order_result.get("alpaca_order_id"),
            "ticker": ticker,
            "asset_type": "stock",
            "side": "sell",
            "order_type": order_type,
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
            "order_type": order_type, "limit_price": limit_price, "stop_price": stop_price,
        }
        if price_context:
            details["price_audit"] = price_context
        if ai_signal:
            details["ai_signal"] = ai_signal

        # Build human-readable order type description for the activity log
        if order_type == "stop_limit":
            order_desc = f"stop-limit stop=${stop_price:.2f} limit=${limit_price:.2f}"
        elif order_type == "limit":
            order_desc = f"limit=${limit_price:.2f}" if limit_price else f"~${current_price:.2f}"
        else:
            order_desc = f"~${current_price:.2f}"

        await trading_db.log_activity(
            db, strategy_id, "order_placed",
            f"SELL {ticker} x{qty:.0f} @ {order_desc} ({reason}, "
            f"change: {price_context['change_pct']:.1f}%, "
            f"source: {price_context['price_source']})"
            if price_context else
            f"SELL {ticker} x{qty:.0f} @ {order_desc} ({reason}, P&L: ${pnl:+.2f})",
            ticker=ticker,
            details=details,
        )

        logger.info("Sell %s order placed: %s x%.0f @ %s (%s)", order_type, ticker, qty, order_desc, reason)

    except Exception as e:
        logger.error("Failed to execute sell for %s: %s", ticker, e)
        await trading_db.log_activity(
            db, strategy_id, "error",
            f"Sell order failed for {ticker}: {str(e)[:200]}",
            ticker=ticker,
        )
