from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.database import get_db
from app.models.schemas import DCFInput, ScenarioModelInput
from app.services.financials import get_key_metrics, get_financial_statements
from app.services.valuation import calculate_dcf, calculate_scenario_model

router = APIRouter()


@router.post("/{ticker}/dcf")
async def run_dcf(ticker: str, inputs: DCFInput, db: AsyncSession = Depends(get_db)):
    """Calculate DCF valuation with user-provided assumptions."""
    metrics = await get_key_metrics(db, ticker)
    fcf = metrics.get("free_cash_flow", 0) or 0
    price = metrics.get("price")

    # Get shares outstanding from financials
    cash_flow = await get_financial_statements(db, ticker, "income_statement", "annual")
    statements = cash_flow.get("statements", [])

    shares = None
    if statements:
        latest = statements[-1]
        shares = latest.get("shares_diluted") or latest.get("shares_outstanding")

    if not shares:
        # Fallback: estimate from market cap and price
        market_cap = metrics.get("market_cap", 0) or 0
        if price and price > 0:
            shares = market_cap / price

    if not shares or shares <= 0:
        return {"error": "Could not determine shares outstanding"}

    return calculate_dcf(ticker, fcf, shares, price, inputs)


@router.post("/{ticker}/scenario")
async def run_scenario(ticker: str, inputs: ScenarioModelInput, db: AsyncSession = Depends(get_db)):
    """Run bull/base/bear scenario analysis."""
    metrics = await get_key_metrics(db, ticker)
    price = metrics.get("price")
    revenue = metrics.get("total_revenue", 0) or 0

    # Get shares outstanding
    income = await get_financial_statements(db, ticker, "income_statement", "annual")
    statements = income.get("statements", [])
    shares = None
    if statements:
        latest = statements[-1]
        shares = latest.get("shares_diluted") or latest.get("shares_outstanding")

    if not shares:
        market_cap = metrics.get("market_cap", 0) or 0
        if price and price > 0:
            shares = market_cap / price

    if not shares or shares <= 0:
        return {"error": "Could not determine shares outstanding"}

    return calculate_scenario_model(ticker, revenue, shares, price, inputs)
