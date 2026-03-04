"""Background scanner — scores stocks across multiple indices for the value screener.

Architecture:
  - scanner_loop() is an infinite async coroutine started from FastAPI's lifespan.
  - It calls run_full_scan() which processes tickers in batches, respecting the
    existing yfinance rate limiter shared with user-initiated requests.
  - Each ticker: fetch yfinance .info -> compute composite score -> upsert to DB.
  - After a full scan, ranks are recalculated via SQL window function.
  - The scanner_status table (single row) tracks progress for the frontend.

Scheduling:
  - Runs once daily, targeting scanner_preferred_hour_local in scanner_timezone
    (default 17:00 America/New_York = 5 PM ET, DST-aware).
  - On startup, runs immediately unless a recent scan exists (<20h old).
  - After each scan, sleeps until the next preferred hour.
  - Fundamental data doesn't change intraday, so once daily is sufficient.

Rate limiting strategy:
  - Batch of 10 tickers scored concurrently (rate limiter queues excess requests).
  - 3-second delay between batches leaves headroom for user requests on the Research page.
  - Full scan of ~2000 unique tickers takes ~20-25 minutes.

Error resilience:
  - Individual ticker failures are tagged by category (no_data, timeout, error) and skipped.
  - After the main pass, a retry pass re-attempts timeout/error tickers with relaxed settings.
  - Full scan failures are caught, logged, and retried after a delay.
  - The outer loop never crashes — it runs for the lifetime of the container.

Failure categories:
  - no_data: yfinance returned None / no price (delisted, OTC, data gap) — not retried
  - timeout: yfinance call exceeded timeout — retried in second pass with longer timeout
  - error: unexpected exception during scoring — retried in second pass
"""

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

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


async def _score_ticker(ticker: str, timeout: int) -> tuple[dict | None, str]:
    """Fetch yfinance data and compute score for a single ticker.

    Returns (score_dict, status) where status is one of:
      'success'  — scored successfully
      'no_data'  — yfinance returned no data (delisted, OTC, data gap) — don't retry
      'timeout'  — yfinance call exceeded timeout — retry candidate
      'error'    — unexpected exception — retry candidate
    """
    try:
        metrics = await asyncio.wait_for(
            yfinance_svc.get_stock_info(ticker),
            timeout=timeout,
        )
        if not metrics or not metrics.get("price"):
            logger.info("No data for %s — no price in yfinance", ticker)
            return None, "no_data"
        return compute_composite_score(metrics), "success"
    except asyncio.TimeoutError:
        logger.warning("Timeout fetching %s (>%ds)", ticker, timeout)
        return None, "timeout"
    except Exception as e:
        logger.warning("Error scoring %s: %s", ticker, e)
        return None, "error"


async def _scan_batch(
    tickers: list[str],
    ticker_indices: dict[str, list[str]],
    batch_size: int,
    batch_delay: float,
    ticker_timeout: int,
    counters: dict,
    failed: dict[str, list[str]],
    label: str = "Main pass",
) -> None:
    """Score a list of tickers in batches, upserting results and tracking failures.

    Shared by the main scan and the retry pass. Mutates `counters` and `failed` in place.
    """
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
                # Unpack tagged result or handle gather exceptions
                if isinstance(result, Exception):
                    logger.warning("Exception scoring %s: %s", ticker, result)
                    counters["error"] += 1
                    failed.setdefault("error", []).append(ticker)
                    continue

                score_data, status = result

                if status != "success":
                    counters[status] += 1
                    if status in ("timeout", "error"):
                        failed.setdefault(status, []).append(ticker)
                    continue

                try:
                    score_data["indices"] = ticker_indices.get(ticker, [])
                    await _upsert_score(db, score_data)
                    counters["success"] += 1
                except Exception as e:
                    logger.warning("DB error upserting %s: %s", ticker, e)
                    counters["error"] += 1
                    failed.setdefault("error", []).append(ticker)

            # Update progress for the status endpoint
            await _update_scanner_status(
                db,
                current_ticker=batch[-1],
                tickers_scanned=counters["success"],
                tickers_no_data=counters["no_data"],
                tickers_timeout=counters["timeout"],
                tickers_error=counters["error"],
            )

        await asyncio.sleep(batch_delay)


async def run_full_scan() -> None:
    """Run a full scan of all tickers across all configured indices.

    Two-pass approach:
      1. Main pass — score all tickers with standard settings
      2. Retry pass — re-attempt timeout/error tickers with relaxed settings

    After both passes, recalculates ranks and logs a detailed failure summary.
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

    logger.info("Starting full scan of %d tickers (batch_size=%d, delay=%.1fs, timeout=%ds)",
                len(tickers), batch_size, batch_delay, ticker_timeout)

    # Mark scan as started
    async with _db.async_session_factory() as db:
        await _update_scanner_status(
            db,
            is_running=True,
            tickers_scanned=0,
            tickers_total=len(tickers),
            tickers_no_data=0,
            tickers_timeout=0,
            tickers_error=0,
            last_full_scan_started_at=datetime.now(timezone.utc),
            last_error=None,
        )

    # Failure tracking — counters and lists of failed tickers by category
    counters = {"success": 0, "no_data": 0, "timeout": 0, "error": 0}
    failed: dict[str, list[str]] = {}

    # --- Main pass ---
    await _scan_batch(
        tickers, ticker_indices,
        batch_size, batch_delay, ticker_timeout,
        counters, failed, label="Main pass",
    )

    logger.info(
        "Main pass complete: %d success, %d no_data, %d timeout, %d error out of %d",
        counters["success"], counters["no_data"], counters["timeout"], counters["error"],
        len(tickers),
    )

    # --- Retry pass for timeout/error tickers ---
    retry_tickers = failed.get("timeout", []) + failed.get("error", [])
    recovered = 0

    if retry_tickers and settings.scanner_retry_failed:
        logger.info("Retry pass: %d tickers to retry (waiting 30s for cooldown)...", len(retry_tickers))
        await asyncio.sleep(30)

        # Relaxed settings: longer timeout, smaller batches, more delay
        retry_counters = {"success": 0, "no_data": 0, "timeout": 0, "error": 0}
        retry_failed: dict[str, list[str]] = {}

        await _scan_batch(
            retry_tickers, ticker_indices,
            batch_size=5, batch_delay=5.0, ticker_timeout=20,
            counters=retry_counters, failed=retry_failed, label="Retry pass",
        )

        recovered = retry_counters["success"]
        counters["success"] += retry_counters["success"]
        # Reduce the original failure counts by recovered amount
        counters["timeout"] = counters["timeout"] - recovered + retry_counters["timeout"]
        counters["error"] = counters["error"] - recovered + retry_counters["error"]
        counters["no_data"] += retry_counters["no_data"]

        logger.info("Retry pass: recovered %d of %d failed tickers", recovered, len(retry_tickers))

    # Log top timeout tickers for diagnosis (helps identify stale CSV entries)
    remaining_timeouts = failed.get("timeout", [])
    if len(remaining_timeouts) > 0:
        sample = remaining_timeouts[:20]
        logger.warning("Top timeout tickers (%d total): %s", len(remaining_timeouts), ", ".join(sample))

    # Recalculate ranks now that all scores are updated
    async with _db.async_session_factory() as db:
        await _update_ranks(db)

        # Store failure summary for API visibility
        failure_summary = json.dumps({
            "success": counters["success"],
            "no_data": counters["no_data"],
            "timeout": counters["timeout"],
            "error": counters["error"],
            "retry_recovered": recovered,
        })

        await _update_scanner_status(
            db,
            is_running=False,
            current_ticker=None,
            tickers_scanned=counters["success"],
            tickers_no_data=counters["no_data"],
            tickers_timeout=counters["timeout"],
            tickers_error=counters["error"],
            last_full_scan_completed_at=datetime.now(timezone.utc),
            last_error=failure_summary,
        )

    logger.info(
        "Full scan complete: %d scored, %d no_data, %d timeout, %d error "
        "(%d recovered via retry) out of %d tickers",
        counters["success"], counters["no_data"], counters["timeout"], counters["error"],
        recovered, len(tickers),
    )


def _seconds_until_preferred_hour(preferred_hour: int, tz_name: str) -> float:
    """Calculate seconds until the next occurrence of preferred_hour in the given timezone.

    Handles DST transitions automatically via ZoneInfo. For example, 5 PM Eastern
    maps to UTC 22:00 during EDT and UTC 21:00 during EST — this function accounts
    for whichever is current.
    """
    tz = ZoneInfo(tz_name)
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(tz)

    # Build today's target in the local timezone
    target_local = now_local.replace(hour=preferred_hour, minute=0, second=0, microsecond=0)

    if now_local >= target_local:
        # Already past today's target — schedule for tomorrow
        target_local += timedelta(days=1)

    # Convert back to UTC for the delta
    target_utc = target_local.astimezone(timezone.utc)
    return (target_utc - now_utc).total_seconds()


async def scanner_loop() -> None:
    """Infinite loop that runs a full scan once daily at the preferred hour.

    Started as an asyncio.Task from FastAPI's lifespan context manager.
    Runs independently of HTTP requests — no user login needed.
    The loop never exits on its own; it's cancelled when the app shuts down.

    Scheduling: targets scanner_preferred_hour_local in scanner_timezone
    (default 17:00 America/New_York = 5 PM ET). On first startup, runs
    immediately to ensure data is fresh, then sleeps until the next preferred hour.
    """
    settings = get_settings()
    preferred_hour = settings.scanner_preferred_hour_local
    tz_name = settings.scanner_timezone
    logger.info(
        "Background scanner starting (daily at %02d:00 %s)...",
        preferred_hour, tz_name,
    )

    # Brief delay: let the app finish starting and DB connections warm up
    await asyncio.sleep(2)

    # Check if a scan completed recently — skip the immediate run if so.
    # This prevents a full re-scan on every deploy (Railway restarts the container).
    first_run = True
    try:
        if _db.async_session_factory:
            async with _db.async_session_factory() as db:
                row = (await db.execute(
                    text("SELECT last_full_scan_completed_at FROM scanner_status WHERE id = 1")
                )).mappings().first()
                if row and row["last_full_scan_completed_at"]:
                    age_hours = (datetime.now(timezone.utc) - row["last_full_scan_completed_at"]).total_seconds() / 3600
                    if age_hours < 20:
                        # Last scan is less than 20 hours old — skip immediate run,
                        # wait for the next scheduled hour instead.
                        logger.info(
                            "Last scan completed %.1f hours ago — skipping startup scan",
                            age_hours,
                        )
                        first_run = False
                    else:
                        logger.info(
                            "Last scan completed %.1f hours ago — running startup scan",
                            age_hours,
                        )
    except Exception as e:
        logger.warning("Could not check last scan time: %s — running startup scan", e)

    while True:
        if not first_run:
            # Sleep until the next preferred hour
            sleep_secs = _seconds_until_preferred_hour(preferred_hour, tz_name)
            hours_until = sleep_secs / 3600
            logger.info(
                "Next scan in %.1f hours (at %02d:00 %s)",
                hours_until, preferred_hour, tz_name,
            )
            await asyncio.sleep(sleep_secs)

        first_run = False

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
            # Wait 5 min before retrying after an error (not a full day)
            await asyncio.sleep(300)
            continue
