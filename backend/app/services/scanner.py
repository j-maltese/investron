"""Background scanner — continuously scores stocks across multiple indices for the value screener.

Architecture:
  - scanner_loop() is an infinite async coroutine started from FastAPI's lifespan.
  - It calls run_full_scan() which processes tickers in batches, respecting the
    existing yfinance rate limiter (5 req/2sec) shared with user-initiated requests.
  - Each ticker: fetch yfinance .info -> compute composite score -> upsert to DB.
  - After a full scan, ranks are recalculated via SQL window function.
  - The scanner_status table (single row) tracks progress for the frontend.

Rate limiting strategy:
  - Batch of 10 tickers scored concurrently (rate limiter queues excess requests).
  - 5-second delay between batches leaves headroom for user requests on the Research page.
  - Full scan of ~2000 unique tickers takes ~35 minutes. Scan repeats every hour.

Error resilience:
  - Individual ticker failures are logged and skipped — one bad ticker doesn't stop the scan.
  - Full scan failures are caught, logged, and retried after a delay.
  - The outer loop never crashes — it runs for the lifetime of the container.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.config import get_settings
from app.models import database as _db
from app.services import yfinance_svc
from app.services.screener import compute_composite_score
from app.services.universe import load_universe

logger = logging.getLogger(__name__)


async def _update_scanner_status(db, **kwargs) -> None:
    """Update the single-row scanner_status table with arbitrary fields.

    Uses dynamic SQL building from kwargs. Safe because keys come from our code,
    not user input. Values are parameterized.
    """
    set_parts = []
    params = {"now": datetime.now(timezone.utc)}
    for key, value in kwargs.items():
        set_parts.append(f"{key} = :{key}")
        params[key] = value
    set_parts.append("updated_at = :now")

    await db.execute(
        text(f"UPDATE scanner_status SET {', '.join(set_parts)} WHERE id = 1"),
        params,
    )
    await db.commit()


async def _upsert_score(db, score_data: dict) -> None:
    """Insert or update a screener score row using PostgreSQL UPSERT.

    Uses ON CONFLICT (ticker) DO UPDATE to atomically insert new tickers or
    refresh existing ones. The EXCLUDED pseudo-table references the proposed row.
    """
    now = datetime.now(timezone.utc)
    await db.execute(
        text("""
            INSERT INTO screener_scores (
                ticker, company_name, sector, industry,
                price, market_cap, pe_ratio, forward_pe, pb_ratio, ps_ratio,
                debt_to_equity, current_ratio, roe, eps, book_value,
                free_cash_flow, total_revenue, dividend_yield,
                revenue_growth, earnings_growth, net_margin, beta,
                fifty_two_week_high, fifty_two_week_low,
                graham_number, margin_of_safety,
                pe_score, pb_score, roe_score, debt_equity_score,
                fcf_yield, fcf_yield_score, earnings_yield, earnings_yield_score,
                dividend_score, margin_of_safety_score,
                composite_score, warnings, indices, scored_at, metrics_fetched_at
            ) VALUES (
                :ticker, :company_name, :sector, :industry,
                :price, :market_cap, :pe_ratio, :forward_pe, :pb_ratio, :ps_ratio,
                :debt_to_equity, :current_ratio, :roe, :eps, :book_value,
                :free_cash_flow, :total_revenue, :dividend_yield,
                :revenue_growth, :earnings_growth, :net_margin, :beta,
                :fifty_two_week_high, :fifty_two_week_low,
                :graham_number, :margin_of_safety,
                :pe_score, :pb_score, :roe_score, :debt_equity_score,
                :fcf_yield, :fcf_yield_score, :earnings_yield, :earnings_yield_score,
                :dividend_score, :margin_of_safety_score,
                :composite_score, CAST(:warnings AS jsonb), CAST(:indices AS jsonb),
                :scored_at, :metrics_fetched_at
            )
            ON CONFLICT (ticker) DO UPDATE SET
                company_name = EXCLUDED.company_name,
                sector = EXCLUDED.sector, industry = EXCLUDED.industry,
                price = EXCLUDED.price, market_cap = EXCLUDED.market_cap,
                pe_ratio = EXCLUDED.pe_ratio, forward_pe = EXCLUDED.forward_pe,
                pb_ratio = EXCLUDED.pb_ratio, ps_ratio = EXCLUDED.ps_ratio,
                debt_to_equity = EXCLUDED.debt_to_equity, current_ratio = EXCLUDED.current_ratio,
                roe = EXCLUDED.roe, eps = EXCLUDED.eps, book_value = EXCLUDED.book_value,
                free_cash_flow = EXCLUDED.free_cash_flow, total_revenue = EXCLUDED.total_revenue,
                dividend_yield = EXCLUDED.dividend_yield,
                revenue_growth = EXCLUDED.revenue_growth, earnings_growth = EXCLUDED.earnings_growth,
                net_margin = EXCLUDED.net_margin, beta = EXCLUDED.beta,
                fifty_two_week_high = EXCLUDED.fifty_two_week_high,
                fifty_two_week_low = EXCLUDED.fifty_two_week_low,
                graham_number = EXCLUDED.graham_number, margin_of_safety = EXCLUDED.margin_of_safety,
                pe_score = EXCLUDED.pe_score, pb_score = EXCLUDED.pb_score,
                roe_score = EXCLUDED.roe_score, debt_equity_score = EXCLUDED.debt_equity_score,
                fcf_yield = EXCLUDED.fcf_yield, fcf_yield_score = EXCLUDED.fcf_yield_score,
                earnings_yield = EXCLUDED.earnings_yield,
                earnings_yield_score = EXCLUDED.earnings_yield_score,
                dividend_score = EXCLUDED.dividend_score,
                margin_of_safety_score = EXCLUDED.margin_of_safety_score,
                composite_score = EXCLUDED.composite_score,
                warnings = EXCLUDED.warnings,
                indices = EXCLUDED.indices,
                scored_at = EXCLUDED.scored_at,
                metrics_fetched_at = EXCLUDED.metrics_fetched_at
        """),
        {
            **score_data,
            "warnings": json.dumps(score_data["warnings"]),
            "indices": json.dumps(score_data.get("indices", [])),
            "scored_at": now,
            "metrics_fetched_at": now,
        },
    )
    await db.commit()


async def _update_ranks(db) -> None:
    """Recalculate rank for all scored stocks based on composite_score.

    Uses a SQL window function (ROW_NUMBER) for efficient in-DB ranking.
    Rank 1 = highest composite score = best value opportunity.
    """
    await db.execute(text("""
        UPDATE screener_scores s
        SET rank = sub.rnk
        FROM (
            SELECT ticker, ROW_NUMBER() OVER (ORDER BY composite_score DESC) AS rnk
            FROM screener_scores
        ) sub
        WHERE s.ticker = sub.ticker
    """))
    await db.commit()


async def _score_ticker(ticker: str, timeout: int) -> dict | None:
    """Fetch yfinance data and compute score for a single ticker.

    Returns the score dict on success, None on failure (timeout, missing data, etc.).
    Failures are expected for some tickers (delisted, data gaps) and are logged but not raised.
    """
    try:
        metrics = await asyncio.wait_for(
            yfinance_svc.get_stock_info(ticker),
            timeout=timeout,
        )
        if not metrics or not metrics.get("price"):
            logger.debug("No data for %s, skipping", ticker)
            return None
        return compute_composite_score(metrics)
    except asyncio.TimeoutError:
        logger.warning("Timeout fetching %s", ticker)
        return None
    except Exception as e:
        logger.warning("Error scoring %s: %s", ticker, e)
        return None


async def run_full_scan() -> None:
    """Run a full scan of all tickers across all configured indices.

    Processes tickers in batches, upserting each score to the DB.
    After all tickers are processed, recalculates ranks.
    Called by scanner_loop() on each cycle.
    """
    settings = get_settings()

    if _db.async_session_factory is None:
        logger.error("Database not initialized, cannot run scanner")
        return

    universe = load_universe()
    if not universe:
        logger.error("No tickers loaded from universe files")
        return

    # Build lookup: ticker → list of index names (e.g., {"AAPL": ["S&P 500", "NASDAQ-100", "Dow 30"]})
    ticker_indices: dict[str, list[str]] = {
        entry["ticker"]: entry["indices"] for entry in universe
    }
    tickers = list(ticker_indices.keys())

    batch_size = settings.scanner_batch_size
    batch_delay = settings.scanner_batch_delay
    ticker_timeout = settings.scanner_ticker_timeout

    logger.info("Starting full scan of %d tickers (batch_size=%d, delay=%.1fs)",
                len(tickers), batch_size, batch_delay)

    # Mark scan as started
    async with _db.async_session_factory() as db:
        await _update_scanner_status(
            db,
            is_running=True,
            tickers_scanned=0,
            tickers_total=len(tickers),
            last_full_scan_started_at=datetime.now(timezone.utc),
            last_error=None,
        )

    scanned = 0
    errors = 0

    # Process in batches — rate limiter handles per-request throttling,
    # batch delay provides additional breathing room for user requests.
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]

        # Score batch concurrently (asyncio.gather + rate limiter = controlled parallelism)
        results = await asyncio.gather(
            *[_score_ticker(t, ticker_timeout) for t in batch],
            return_exceptions=True,
        )

        # Persist results to DB
        async with _db.async_session_factory() as db:
            for ticker, result in zip(batch, results):
                if isinstance(result, Exception):
                    logger.warning("Exception scoring %s: %s", ticker, result)
                    errors += 1
                    continue
                if result is None:
                    errors += 1
                    continue

                try:
                    # Inject index memberships before upserting
                    result["indices"] = ticker_indices.get(ticker, [])
                    await _upsert_score(db, result)
                    scanned += 1
                except Exception as e:
                    logger.warning("DB error upserting %s: %s", ticker, e)
                    errors += 1

            # Update progress for the status endpoint
            await _update_scanner_status(
                db,
                current_ticker=batch[-1],
                tickers_scanned=scanned,
            )

        # Pause between batches to leave rate limit headroom
        await asyncio.sleep(batch_delay)

    # Recalculate ranks now that all scores are updated
    async with _db.async_session_factory() as db:
        await _update_ranks(db)
        await _update_scanner_status(
            db,
            is_running=False,
            current_ticker=None,
            tickers_scanned=scanned,
            last_full_scan_completed_at=datetime.now(timezone.utc),
        )

    logger.info("Full scan complete: %d scored, %d errors out of %d tickers",
                scanned, errors, len(tickers))


async def scanner_loop() -> None:
    """Infinite loop that runs full scans at regular intervals.

    Started as an asyncio.Task from FastAPI's lifespan context manager.
    Runs independently of HTTP requests — no user login needed.
    The loop never exits on its own; it's cancelled when the app shuts down.
    """
    settings = get_settings()
    logger.info("Background scanner starting (interval=%ds)...", settings.scanner_interval_seconds)

    # Brief delay: let the app finish starting and DB connections warm up
    await asyncio.sleep(2)

    while True:
        try:
            await run_full_scan()
        except Exception as e:
            logger.error("Scanner error: %s", e, exc_info=True)
            # Record the error in status for visibility
            try:
                if _db.async_session_factory:
                    async with _db.async_session_factory() as db:
                        await _update_scanner_status(
                            db,
                            is_running=False,
                            last_error=str(e)[:500],
                        )
            except Exception:
                pass  # Don't let status update failures cascade
            # Wait before retrying after an error
            await asyncio.sleep(60)
            continue

        logger.info("Next scan in %d seconds", settings.scanner_interval_seconds)
        await asyncio.sleep(settings.scanner_interval_seconds)
