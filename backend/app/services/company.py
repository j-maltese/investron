"""Company search and resolution — combines EDGAR and yfinance data."""

import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.services import edgar, yfinance_svc

logger = logging.getLogger(__name__)


async def search_companies(query: str) -> list[dict]:
    """Search for companies by ticker or name.

    Uses SEC EDGAR's company tickers file for comprehensive matching.
    """
    # First try as an exact ticker lookup via yfinance (fast)
    info = await yfinance_svc.get_stock_info(query.upper())
    results = []

    if info and info.get("name"):
        results.append({
            "ticker": info["ticker"],
            "name": info["name"],
            "exchange": info.get("exchange"),
        })

    return results


async def get_or_create_company(db: AsyncSession, ticker: str) -> dict | None:
    """Get company from DB or create by fetching from EDGAR + yfinance."""
    ticker = ticker.upper()

    # Check DB first
    result = await db.execute(
        text("SELECT id, ticker, name, cik, sector, industry, exchange, fiscal_year_end FROM companies WHERE ticker = :ticker"),
        {"ticker": ticker},
    )
    row = result.mappings().first()
    if row:
        # If CIK is missing/placeholder, re-fetch from EDGAR
        if row["cik"] and row["cik"] != "0000000000":
            return dict(row)

    # Fetch from EDGAR
    logger.info(f"Looking up CIK for {ticker} from SEC EDGAR...")
    edgar_info = await edgar.lookup_cik(ticker)
    logger.info(f"EDGAR lookup result for {ticker}: {edgar_info}")
    if not edgar_info:
        return None

    # Supplement with yfinance for sector/industry
    yf_info = await yfinance_svc.get_stock_info(ticker)

    company_data = {
        "ticker": ticker,
        "name": edgar_info.get("name", ""),
        "cik": edgar_info.get("cik", ""),
        "sector": (yf_info or {}).get("sector"),
        "industry": (yf_info or {}).get("industry"),
        "exchange": edgar_info.get("exchange") or (yf_info or {}).get("exchange"),
        "fiscal_year_end": edgar_info.get("fiscal_year_end"),
    }

    # Insert into DB
    result = await db.execute(
        text("""
            INSERT INTO companies (ticker, name, cik, sector, industry, exchange, fiscal_year_end)
            VALUES (:ticker, :name, :cik, :sector, :industry, :exchange, :fiscal_year_end)
            ON CONFLICT (ticker) DO UPDATE SET
                name = EXCLUDED.name,
                cik = EXCLUDED.cik,
                sector = EXCLUDED.sector,
                industry = EXCLUDED.industry,
                exchange = EXCLUDED.exchange,
                fiscal_year_end = EXCLUDED.fiscal_year_end,
                updated_at = NOW()
            RETURNING id, ticker, name, cik, sector, industry, exchange, fiscal_year_end
        """),
        company_data,
    )
    await db.commit()
    return dict(result.mappings().first())
