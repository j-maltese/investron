from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.models.database import init_db
from app.api import companies, financials, filings, watchlist, valuation
from app.auth import routes as auth_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
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


@app.get("/health")
async def health_check():
    return {"status": "healthy", "app": settings.app_name}


@app.get("/debug/yfinance/{ticker}")
async def debug_yfinance(ticker: str):
    """Temporary debug endpoint — remove after deployment is verified."""
    import yfinance as yf
    from app.services.yfinance_svc import _ticker
    try:
        stock = _ticker(ticker.upper())
        info = stock.info
        return {"ticker": ticker, "keys": list(info.keys()) if info else [], "sample": {k: info.get(k) for k in ["regularMarketPrice", "currentPrice", "longName", "shortName", "symbol"] if info}}
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}
