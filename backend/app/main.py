import pathlib
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.models.database import init_db
from app.api import companies, financials, filings, watchlist, valuation, release_notes
from app.auth import routes as auth_routes

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
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


@app.get("/health")
async def health_check():
    return {"status": "healthy", "app": settings.app_name}
