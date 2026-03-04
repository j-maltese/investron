import asyncio

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.database import get_db
from app.services.financials import get_financial_statements, get_key_metrics, get_growth_metrics
from app.services.valuation import calculate_graham_score

router = APIRouter()

# Per-endpoint timeout for yfinance-dependent calls (seconds).
# yfinance_svc retries internally (3 attempts, 1s+2s backoff = ~6s worst case),
# so 10s gives headroom without hanging the request indefinitely.
_ENDPOINT_TIMEOUT = 10


@router.get("/{ticker}/statements")
async def get_statements(
    ticker: str,
    statement_type: str = Query("income_statement", pattern="^(income_statement|balance_sheet|cash_flow)$"),
    period_type: str = Query("annual", pattern="^(annual|quarterly)$"),
    db: AsyncSession = Depends(get_db),
):
    """Get financial statements (income, balance sheet, cash flow)."""
    return await get_financial_statements(db, ticker, statement_type, period_type)


@router.get("/{ticker}/metrics")
async def get_metrics(ticker: str, db: AsyncSession = Depends(get_db)):
    """Get key financial metrics (P/E, P/B, ROE, margins, etc.)."""
    try:
        result = await asyncio.wait_for(get_key_metrics(db, ticker), timeout=_ENDPOINT_TIMEOUT)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Data fetch timed out — please try again.")

    if result.get("error"):
        raise HTTPException(status_code=502, detail=result.get("error_message", "Data unavailable"))

    return result


@router.get("/{ticker}/graham-score")
async def get_graham_score(ticker: str, db: AsyncSession = Depends(get_db)):
    """Evaluate stock against Graham's 7 criteria."""
    try:
        metrics = await asyncio.wait_for(get_key_metrics(db, ticker), timeout=_ENDPOINT_TIMEOUT)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Data fetch timed out — please try again.")

    if metrics.get("error"):
        raise HTTPException(status_code=502, detail=metrics.get("error_message", "Data unavailable"))

    financials = await get_financial_statements(db, ticker, "income_statement", "annual")

    # Build a simplified financials dict for the Graham scorer
    income_data = {}
    if financials.get("statements"):
        # Extract time series for net income and EPS
        from app.services import edgar
        from app.services.company import get_or_create_company
        company = await get_or_create_company(db, ticker)
        if company:
            cik = company.get("cik", "").zfill(10)
            facts = await edgar.get_xbrl_company_facts(cik)
            if facts:
                income_data = edgar.extract_financial_time_series(
                    facts, edgar.INCOME_STATEMENT_CONCEPTS, "annual"
                )

    return calculate_graham_score(metrics, income_data)


@router.get("/{ticker}/growth-metrics")
async def get_growth(ticker: str, db: AsyncSession = Depends(get_db)):
    """Get growth/emerging company metrics (burn rate, runway, dilution, etc.)."""
    try:
        result = await asyncio.wait_for(get_growth_metrics(db, ticker), timeout=_ENDPOINT_TIMEOUT)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Data fetch timed out — please try again.")

    if result.get("error"):
        raise HTTPException(status_code=502, detail=result.get("error_message", "Data unavailable"))

    return result
