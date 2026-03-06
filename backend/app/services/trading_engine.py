"""Trading engine — background loop that runs trading strategies.

Architecture mirrors scanner.py:
  - trading_loop() is an infinite async coroutine started from FastAPI's lifespan.
  - Each cycle checks all strategies with status='running' and executes their logic.
  - Strategies are pluggable: simple_stock and wheel each have their own service module.
  - Market hours check: only runs strategies when US markets are open.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta, date as date_type

from app.config import get_settings
from app.models import database as _db
from app.services import trading_db

logger = logging.getLogger(__name__)

# Track last auto-index date to gate daily filing indexing (resets on app restart)
_last_auto_index_date: date_type | None = None

# US market hours in Eastern Time (UTC-5 standard, UTC-4 DST)
# We use a conservative window: 9:35 AM - 3:55 PM ET
MARKET_OPEN_UTC = 14  # 9 AM ET = 14:00 UTC (standard time, approximate)
MARKET_CLOSE_UTC = 21  # 4 PM ET = 21:00 UTC


def _is_market_hours() -> bool:
    """Check if US stock market is currently open (approximate).

    Uses UTC-based check. Not DST-aware — off by an hour during summer,
    but good enough to avoid trading at 2 AM.
    """
    now = datetime.now(timezone.utc)
    # Skip weekends
    if now.weekday() >= 5:
        return False
    # Check if within market hours (with buffer)
    return MARKET_OPEN_UTC <= now.hour < MARKET_CLOSE_UTC


async def run_trading_cycle() -> None:
    """Run one cycle: check each running strategy and execute its logic.

    For each strategy with status='running':
      1. Check safety limits (max drawdown)
      2. Sync positions with Alpaca (poll for fills, assignments)
      3. Run the appropriate strategy cycle
      4. Update strategy P&L
    """
    if _db.async_session_factory is None:
        logger.error("Database not initialized, cannot run trading cycle")
        return

    async with _db.async_session_factory() as db:
        strategies = await trading_db.get_all_strategies(db)

    # Sync pending orders for paused strategies — orders can fill on Alpaca
    # even when we've paused. Without this, cash/positions stay stale until restart.
    for strategy in strategies:
        if strategy["status"] != "paused":
            continue
        strategy_id = strategy["id"]
        strategy_type = strategy["strategy_type"]
        try:
            async with _db.async_session_factory() as db:
                if strategy_type == "simple_stock":
                    from app.services.simple_stock_strategy import _sync_pending_orders
                    await _sync_pending_orders(db, strategy_id)
                elif strategy_type == "wheel":
                    from app.services.wheel_strategy import _sync_option_orders
                    await _sync_option_orders(db, strategy_id)
        except Exception as e:
            logger.warning("Order sync failed for paused strategy %s: %s", strategy_id, e)

    for strategy in strategies:
        if strategy["status"] != "running":
            continue

        strategy_id = strategy["id"]
        strategy_type = strategy["strategy_type"]

        try:
            async with _db.async_session_factory() as db:
                # Check safety: has drawdown exceeded max_loss_pct?
                initial = float(strategy["initial_capital"])
                cash = float(strategy["current_cash"])
                portfolio = float(strategy.get("current_portfolio_value", 0))
                current_value = cash + portfolio
                drawdown_pct = ((initial - current_value) / initial * 100) if initial > 0 else 0

                max_loss = float(strategy.get("max_loss_pct", 20.0))
                if drawdown_pct > max_loss:
                    logger.warning(
                        "Strategy %s hit max loss (%.1f%% > %.1f%%), pausing",
                        strategy_id, drawdown_pct, max_loss,
                    )
                    await trading_db.update_strategy(db, strategy_id, status="paused")
                    await trading_db.log_activity(
                        db, strategy_id, "circuit_breaker",
                        f"Strategy paused: drawdown {drawdown_pct:.1f}% exceeds max {max_loss:.1f}%",
                        details={"drawdown_pct": drawdown_pct, "max_loss_pct": max_loss},
                    )
                    continue

                # Run strategy-specific logic
                if strategy_type == "simple_stock":
                    # Daily auto-index: index SEC filings for top candidates (once per day)
                    global _last_auto_index_date
                    today = date_type.today()
                    if _last_auto_index_date != today:
                        try:
                            from app.services.simple_stock_strategy import run_auto_index_cycle
                            logger.info("Running daily auto-index for simple stock candidates...")
                            await run_auto_index_cycle(db, strategy)
                            _last_auto_index_date = today
                        except Exception as e:
                            logger.error("Auto-index failed (will retry next cycle): %s", e)

                    from app.services.simple_stock_strategy import run_simple_stock_cycle
                    await run_simple_stock_cycle(db, strategy)
                elif strategy_type == "wheel":
                    from app.services.wheel_strategy import run_wheel_cycle
                    await run_wheel_cycle(db, strategy)

                # Update last_run timestamp
                await trading_db.update_strategy(
                    db, strategy_id,
                    last_run_at=datetime.now(timezone.utc),
                )

        except Exception as e:
            logger.error("Error running strategy %s: %s", strategy_id, e, exc_info=True)
            try:
                async with _db.async_session_factory() as db:
                    error_count = strategy.get("error_count", 0) + 1
                    await trading_db.update_strategy(
                        db, strategy_id,
                        last_error=str(e)[:500],
                        error_count=error_count,
                    )
                    await trading_db.log_activity(
                        db, strategy_id, "error",
                        f"Strategy error: {str(e)[:200]}",
                        details={"error": str(e)},
                    )
            except Exception:
                pass  # Don't let error logging cascade


async def trading_loop() -> None:
    """Infinite loop that runs trading cycles at regular intervals.

    Started as an asyncio.Task from FastAPI's lifespan context manager.
    The loop never exits on its own; it's cancelled when the app shuts down.
    """
    settings = get_settings()
    logger.info(
        "Trading engine starting (interval=%ds)...",
        settings.trading_check_interval,
    )

    # Brief delay: let the app finish starting and DB connections warm up
    await asyncio.sleep(5)

    while True:
        if not _is_market_hours():
            # Sleep longer outside market hours — check every 5 minutes
            await asyncio.sleep(300)
            continue

        try:
            await run_trading_cycle()
        except Exception as e:
            logger.error("Trading engine error: %s", e, exc_info=True)
            await asyncio.sleep(60)
            continue

        await asyncio.sleep(settings.trading_check_interval)
