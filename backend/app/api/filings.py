from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.database import get_db
from app.services.filings import get_filings, refresh_filings

router = APIRouter()


@router.get("/{ticker}")
async def list_filings(
    ticker: str,
    types: str = Query(None, description="Comma-separated filing types, e.g. '10-K,10-Q,8-K'"),
    db: AsyncSession = Depends(get_db),
):
    """List SEC filings for a company."""
    filing_types = [t.strip() for t in types.split(",")] if types else None
    return await get_filings(db, ticker, filing_types)


@router.post("/{ticker}/refresh")
async def refresh_filing_list(
    ticker: str,
    types: str = Query(None, description="Comma-separated filing types, e.g. '10-K,10-Q,8-K'"),
    db: AsyncSession = Depends(get_db),
):
    """Re-fetch the filing list from EDGAR to pick up new submissions.

    Metadata-only refresh — does not trigger embedding/indexing for RAG.
    Returns the updated filing list plus a count of newly discovered filings.
    """
    filing_types = [t.strip() for t in types.split(",")] if types else None
    return await refresh_filings(db, ticker, filing_types)
