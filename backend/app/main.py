import asyncio
import logging
import pathlib
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.models.database import init_db
from app.api import companies, financials, filings, watchlist, valuation, release_notes, screener, ai
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


# Background scanner task reference — kept at module level so we can cancel on shutdown
_scanner_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: initialize DB and optionally start the background scanner.

    The scanner runs as an asyncio task for the lifetime of the app, continuously
    scoring S&P 500 stocks even when no users are logged in.
    """
    global _scanner_task
    init_db()

    settings = get_settings()
    if settings.scanner_enabled:
        logger.info("Starting background scanner task...")
        _scanner_task = asyncio.create_task(scanner_loop())
    else:
        logger.info("Background scanner is disabled (SCANNER_ENABLED=false)")

    yield

    # Graceful shutdown: cancel the scanner if it's running
    if _scanner_task and not _scanner_task.done():
        _scanner_task.cancel()
        try:
            await _scanner_task
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


@app.get("/health")
async def health_check():
    return {"status": "healthy", "app": settings.app_name}
