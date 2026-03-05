"""Company search and resolution — combines EDGAR and yfinance data."""

import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.services import edgar, yfinance_svc

logger = logging.getLogger(__name__)


async def search_companies(query: str, db: AsyncSession | None = None) -> list[dict]:
    """Search for companies by ticker or name.

    Strategy: first search the local screener_scores table (fast, covers ~2000
    scored stocks) by both ticker prefix and company name substring. If no local
    matches are found, fall back to yfinance for an exact ticker lookup so the
    user can still find stocks outside the scored universe.

    The db session should be passed from the API endpoint via FastAPI's Depends(get_db).
    """
    query = query.strip()
    if not query:
        return []

    results: list[dict] = []

    # Search screener_scores for ticker prefix OR company name substring (case-insensitive)
    if db is not None:
        try:
            rows = await db.execute(
                text("""
                    SELECT ticker, company_name, sector
                    FROM screener_scores
                    WHERE ticker ILIKE :prefix OR company_name ILIKE :substring
                    ORDER BY
                        -- Exact ticker match first, then prefix match, then name match
                        CASE
                            WHEN UPPER(ticker) = UPPER(:raw) THEN 0
                            WHEN ticker ILIKE :prefix THEN 1
                            ELSE 2
                        END,
                        composite_score DESC NULLS LAST
                    LIMIT 10
                """),
                {"prefix": f"{query}%", "substring": f"%{query}%", "raw": query},
            )
            for row in rows.mappings().all():
                results.append({
                    "ticker": row["ticker"],
                    "name": row["company_name"] or "",
                    "exchange": None,
                })
        except Exception:
            # DB might not have screener_scores yet (first run); fall through to yfinance
            logger.debug("screener_scores search failed, falling back to yfinance", exc_info=True)

    # If no local matches, try yfinance exact ticker lookup as fallback
    if not results:
        info = await yfinance_svc.get_stock_info(query.upper())
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
