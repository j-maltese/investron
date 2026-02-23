from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.database import get_db
from app.services.company import search_companies, get_or_create_company

router = APIRouter()


@router.get("/search")
async def search(q: str = Query(..., min_length=1)):
    """Search companies by ticker or name."""
    results = await search_companies(q)
    return {"results": results}


@router.get("/{ticker}")
async def get_company(ticker: str, db: AsyncSession = Depends(get_db)):
    """Get company details by ticker."""
    company = await get_or_create_company(db, ticker)
    if not company:
        return {"error": f"Company not found: {ticker}"}
    return company
