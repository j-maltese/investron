from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.database import get_db
from app.services.filings import get_filings

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
