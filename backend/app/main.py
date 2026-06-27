import asyncio
import logging
import pathlib
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.models.database import init_db
from app.api import companies, financials, filings, watchlist, valuation, release_notes, screener, ai, indexing, trading, buffett
from app.auth import routes as auth_routes
from app.services.scanner import scanner_loop

# Configure root logger so all app.* loggers emit to stdout.
# Uvicorn only configures its own loggers; without this, our scanner/screener
# log calls are silently swallowed.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:  %(name)s - %(message)s")
logger = logging.getLogger(__name__)

# Read version from VERSION file at repo root
_version = "0.0.0"
for _candidate in [
    pathlib.Path(__file__).resolve().parent.parent.parent / "VERSION",
    pathlib.Path("../VERSION"),
    pathlib.Path("VERSION"),
]:
    if _candidate.exists():
        _version = _candidate.read_text().strip()
        break


# Background task references — kept at module level so we can cancel on shutdown
_scanner_task: asyncio.Task | None = None
_trading_task: asyncio.Task | None = None


async def _run_migrations():
    """Run idempotent ALTER TABLE statements to add columns that may be missing.

    This bridges the gap between schema.sql (only runs on fresh DB init) and
    existing production/dev databases that were created before new columns were added.
    Each statement uses IF NOT EXISTS so it's safe to run on every startup.
    """
    from app.models import database as _db
    if not _db.async_session_factory:
        return
    try:
        async with _db.async_session_factory() as db:
            # Scanner status columns
            await db.execute(text(
                "ALTER TABLE scanner_status "
                "ADD COLUMN IF NOT EXISTS tickers_no_data INT DEFAULT 0"
            ))
            await db.execute(text(
                "ALTER TABLE scanner_status "
                "ADD COLUMN IF NOT EXISTS tickers_timeout INT DEFAULT 0"
            ))
            await db.execute(text(
                "ALTER TABLE scanner_status "
                "ADD COLUMN IF NOT EXISTS tickers_error INT DEFAULT 0"
            ))

            # Trading: underlying_price for position display
            await db.execute(text(
                "ALTER TABLE trading_positions "
                "ADD COLUMN IF NOT EXISTS underlying_price DECIMAL(12,4)"
            ))

            # Trading: peak_price high-water mark for the Wheel runner trailing stop.
            # Tracks the highest underlying price a position has reached so the
            # trailing stop can ratchet up and protect an appreciated position.
            await db.execute(text(
                "ALTER TABLE trading_positions "
                "ADD COLUMN IF NOT EXISTS peak_price DECIMAL(12,4)"
            ))

            # Per-user watchlists: user_email column + unique constraint swap
            await db.execute(text(
                "ALTER TABLE watchlist_items "
                "ADD COLUMN IF NOT EXISTS user_email VARCHAR(255)"
            ))
            await db.execute(text(
                "ALTER TABLE watchlist_items "
                "DROP CONSTRAINT IF EXISTS watchlist_items_ticker_key"
            ))
            await db.execute(text("""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'watchlist_items_ticker_user_email_key'
                    ) THEN
                        ALTER TABLE watchlist_items
                        ADD CONSTRAINT watchlist_items_ticker_user_email_key
                        UNIQUE (ticker, user_email);
                    END IF;
                END $$
            """))
            # Tag any untagged watchlist items (first deploy only)
            await db.execute(text(
                "UPDATE watchlist_items SET user_email = 'mmalt01@gmail.com' "
                "WHERE ticker IN ('TPL', 'CVSA') AND user_email IS NULL"
            ))
            await db.execute(text(
                "UPDATE watchlist_items SET user_email = 'john.maltese@gmail.com' "
                "WHERE user_email IS NULL"
            ))

            # Cleanup: remove orphaned positions created by failed orders
            # (bug where position was created before order submission — now fixed)
            # Step 1: find orphaned position IDs
            orphaned_ids = await db.execute(text(
                "SELECT id, ticker, option_symbol, status, opened_at "
                "FROM trading_positions "
                "WHERE avg_entry_price IS NULL "
                "AND (cost_basis IS NULL OR cost_basis = 0) "
                "AND asset_type = 'option'"
            ))
            orphaned_rows = orphaned_ids.mappings().all()
            if orphaned_rows:
                ids = [row["id"] for row in orphaned_rows]
                # Step 2: delete referencing orders first (also orphaned/failed)
                await db.execute(text(
                    "DELETE FROM trading_orders WHERE position_id = ANY(:ids)"
                ), {"ids": ids})
                # Step 3: now delete the orphaned positions
                await db.execute(text(
                    "DELETE FROM trading_positions WHERE id = ANY(:ids)"
                ), {"ids": ids})
                for row in orphaned_rows:
                    logger.info(
                        "Cleaned up orphaned position: id=%s ticker=%s symbol=%s status=%s opened=%s",
                        row["id"], row["ticker"], row["option_symbol"], row["status"], row["opened_at"],
                    )

            # Ticker notes table: decoupled from watchlist so notes follow the
            # ticker (not the watchlist entry) and track who wrote each note.
            await db.execute(text("""
                CREATE TABLE IF NOT EXISTS ticker_notes (
                    id SERIAL PRIMARY KEY,
                    ticker VARCHAR(10) NOT NULL,
                    user_email VARCHAR(255) NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(ticker, user_email)
                )
            """))
            await db.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_ticker_notes_ticker ON ticker_notes(ticker)"
            ))
            # One-time migration: copy existing watchlist notes into ticker_notes
            await db.execute(text("""
                INSERT INTO ticker_notes (ticker, user_email, notes, created_at)
                SELECT ticker, user_email, notes, added_at
                FROM watchlist_items
                WHERE notes IS NOT NULL AND notes != ''
                ON CONFLICT (ticker, user_email) DO NOTHING
            """))

            # ML feedback loop (Phase 0): point-in-time decision snapshots + a daily
            # archive of screener metrics. These are the labeled data + feature store
            # for the Simple Stock buy/skip model. Created BEFORE the RLS block below so
            # the dynamic loop enables RLS on them in this same migration run.
            await db.execute(text("""
                CREATE TABLE IF NOT EXISTS trading_decisions (
                    id SERIAL PRIMARY KEY,
                    strategy_id VARCHAR(30) REFERENCES trading_strategies(id),
                    ticker VARCHAR(10) NOT NULL,
                    decided_at TIMESTAMPTZ DEFAULT NOW(),
                    action VARCHAR(10) NOT NULL,
                    horizon_days INT,
                    decision_price DECIMAL(12,4),
                    benchmark_price DECIMAL(12,4),
                    screener_score DECIMAL(6,2),
                    features JSONB,
                    ai_signal JSONB,
                    model_prediction JSONB,
                    label_status VARCHAR(20) DEFAULT 'pending',
                    matured_at TIMESTAMPTZ,
                    forward_price DECIMAL(12,4),
                    forward_return_pct DECIMAL(10,4),
                    benchmark_return_pct DECIMAL(10,4),
                    excess_return_pct DECIMAL(10,4),
                    beat_market BOOLEAN
                )
            """))
            await db.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_td_strategy ON trading_decisions(strategy_id)"
            ))
            await db.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_td_ticker ON trading_decisions(ticker)"
            ))
            await db.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_td_label_status ON trading_decisions(label_status)"
            ))
            await db.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_td_decided ON trading_decisions(decided_at DESC)"
            ))
            await db.execute(text("""
                CREATE TABLE IF NOT EXISTS screener_scores_history (
                    id SERIAL PRIMARY KEY,
                    ticker VARCHAR(10) NOT NULL,
                    snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
                    composite_score DECIMAL(6,2),
                    price DECIMAL(12,4),
                    features JSONB NOT NULL,
                    scored_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(ticker, snapshot_date)
                )
            """))
            await db.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_ssh_ticker_date "
                "ON screener_scores_history(ticker, snapshot_date DESC)"
            ))
            await db.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_ssh_date "
                "ON screener_scores_history(snapshot_date DESC)"
            ))
            # Ensure the label horizon is present on the simple_stock config (idempotent)
            await db.execute(text(
                "UPDATE trading_strategies "
                "SET config = config || '{\"ml_label_horizon_days\": 30}'::jsonb "
                "WHERE id = 'simple_stock' AND NOT (config ? 'ml_label_horizon_days')"
            ))

            # Security: enable Row Level Security on every public table.
            # Supabase exposes the `public` schema through its anon-key REST API
            # (PostgREST); with RLS off, anyone holding the publishable key (it
            # ships in the frontend bundle) could read/write our tables directly,
            # bypassing the backend. We never use that Data API — the frontend
            # uses Supabase only for auth and routes all data through this backend
            # (which connects as the `postgres` role and BYPASSES RLS, so it's
            # unaffected). Enabling RLS with no policies = deny-all to the API.
            # Dynamic loop so current and future tables are always covered;
            # idempotent (re-enabling is a no-op).
            await db.execute(text("""
                DO $$
                DECLARE t record;
                BEGIN
                    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public'
                    LOOP
                        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.tablename);
                    END LOOP;
                END $$
            """))

            await db.commit()
        logger.info("Schema migrations applied successfully")
    except Exception as e:
        logger.warning("Schema migration failed (non-fatal): %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: initialize DB and optionally start background tasks.

    The scanner and trading engine run as asyncio tasks for the lifetime of the app,
    continuously working even when no users are logged in.
    """
    global _scanner_task, _trading_task
    init_db()

    # Run idempotent schema migrations so new columns are added on deploy
    # without requiring manual SQL. Safe to run repeatedly (IF NOT EXISTS).
    await _run_migrations()

    settings = get_settings()
    if settings.scanner_enabled:
        logger.info("Starting background scanner task...")
        _scanner_task = asyncio.create_task(scanner_loop())
    else:
        logger.info("Background scanner is disabled (SCANNER_ENABLED=false)")

    if settings.trading_enabled:
        from app.services.trading_engine import trading_loop
        logger.info("Starting trading engine task...")
        _trading_task = asyncio.create_task(trading_loop())
    else:
        logger.info("Trading engine is disabled (TRADING_ENABLED=false)")

    yield

    # Graceful shutdown: cancel background tasks
    for task_name, task in [("scanner", _scanner_task), ("trading", _trading_task)]:
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=_version,
    lifespan=lifespan,
)

import json as _json

# Parse CORS origins: supports both JSON array '["http://..."]' and plain
# comma-separated 'http://..., http://...' formats.
try:
    _origins = _json.loads(settings.cors_origins)
except (ValueError, TypeError):
    _origins = [o.strip() for o in settings.cors_origins.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth_routes.router, prefix="/auth", tags=["auth"])
app.include_router(companies.router, prefix="/api/companies", tags=["companies"])
app.include_router(financials.router, prefix="/api/financials", tags=["financials"])
app.include_router(filings.router, prefix="/api/filings", tags=["filings"])
app.include_router(watchlist.router, prefix="/api/watchlist", tags=["watchlist"])
app.include_router(valuation.router, prefix="/api/valuation", tags=["valuation"])
app.include_router(release_notes.router, prefix="/api/release-notes", tags=["release-notes"])
app.include_router(screener.router, prefix="/api/screener", tags=["screener"])
app.include_router(ai.router, prefix="/api/ai", tags=["ai"])
app.include_router(indexing.router, prefix="/api/ai/filings", tags=["filing-indexing"])
app.include_router(trading.router, prefix="/api/trading", tags=["trading"])
app.include_router(buffett.router, prefix="/api/buffett", tags=["buffett"])


@app.get("/health")
async def health_check():
    return {"status": "healthy", "app": settings.app_name}
