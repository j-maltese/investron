"""SEC filing retrieval and caching."""

from datetime import date
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.services import edgar
from app.services.company import get_or_create_company


async def get_filings(
    db: AsyncSession,
    ticker: str,
    filing_types: list[str] | None = None,
) -> dict:
    """Get SEC filings for a company, with caching in DB.

    Args:
        filing_types: Optional filter, e.g. ["10-K", "10-Q", "8-K"]
    """
    company = await get_or_create_company(db, ticker)
    if not company:
        return {"ticker": ticker, "filings": [], "total_count": 0}

    # Check if we have cached filings
    type_filter = ""
    params = {"company_id": company["id"]}
    if filing_types:
        placeholders = ", ".join(f":ft{i}" for i in range(len(filing_types)))
        type_filter = f"AND filing_type IN ({placeholders})"
        for i, ft in enumerate(filing_types):
            params[f"ft{i}"] = ft

    result = await db.execute(
        text(f"""
            SELECT filing_type, filing_date, accession_number, filing_url, description
            FROM filings_cache
            WHERE company_id = :company_id {type_filter}
            ORDER BY filing_date DESC
        """),
        params,
    )
    cached_filings = [dict(row) for row in result.mappings().all()]

    if cached_filings:
        return {
            "ticker": ticker,
            "filings": cached_filings,
            "total_count": len(cached_filings),
        }

    # Fetch from EDGAR
    cik = company.get("cik", "").zfill(10)
    submissions = await edgar.get_company_submissions(cik)
    if not submissions:
        return {"ticker": ticker, "filings": [], "total_count": 0}

    all_filings = edgar.parse_filings_from_submissions(submissions, filing_types)

    # Cache in DB
    for f in all_filings:
        await db.execute(
            text("""
                INSERT INTO filings_cache (company_id, filing_type, filing_date, accession_number, filing_url, description)
                VALUES (:company_id, :filing_type, :filing_date, :accession_number, :filing_url, :description)
                ON CONFLICT (company_id, accession_number) DO NOTHING
            """),
            {
                "company_id": company["id"],
                "filing_type": f["filing_type"],
                "filing_date": date.fromisoformat(f["filing_date"]) if isinstance(f["filing_date"], str) else f["filing_date"],
                "accession_number": f["accession_number"],
                "filing_url": f["filing_url"],
                "description": f["description"],
            },
        )
    await db.commit()

    return {
        "ticker": ticker,
        "filings": all_filings,
        "total_count": len(all_filings),
    }
