"""Financial data aggregation — combines EDGAR XBRL and yfinance with caching."""

from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.services import edgar, yfinance_svc
from app.services.company import get_or_create_company
from app.utils.cache import get_cached_data, set_cached_data


async def get_financial_statements(
    db: AsyncSession,
    ticker: str,
    statement_type: str = "income_statement",
    period_type: str = "annual",
) -> dict:
    """Get financial statements with caching.

    Args:
        statement_type: "income_statement" | "balance_sheet" | "cash_flow"
        period_type: "annual" | "quarterly"
    """
    settings = get_settings()
    company = await get_or_create_company(db, ticker)
    if not company:
        return {"ticker": ticker, "statement_type": statement_type, "period_type": period_type, "statements": []}

    # Check cache
    cached = await get_cached_data(db, company["id"], "edgar_xbrl", statement_type, period_type)
    if cached:
        return cached

    # Fetch from EDGAR
    cik = company.get("cik", "").zfill(10)
    facts = await edgar.get_xbrl_company_facts(cik)
    if not facts:
        return {"ticker": ticker, "statement_type": statement_type, "period_type": period_type, "statements": []}

    # Pick the right concept mapping
    concept_map = {
        "income_statement": edgar.INCOME_STATEMENT_CONCEPTS,
        "balance_sheet": edgar.BALANCE_SHEET_CONCEPTS,
        "cash_flow": edgar.CASH_FLOW_CONCEPTS,
    }.get(statement_type, edgar.INCOME_STATEMENT_CONCEPTS)

    time_series = edgar.extract_financial_time_series(facts, concept_map, period_type)

    # Pivot into per-period statements
    all_periods = set()
    for series in time_series.values():
        for entry in series:
            all_periods.add(entry["period"])

    statements = []
    for period in sorted(all_periods):
        row = {"period": period}
        for field, series in time_series.items():
            match = next((e for e in series if e["period"] == period), None)
            if match:
                row[field] = match["value"]
        statements.append(row)

    result = {
        "ticker": ticker,
        "statement_type": statement_type,
        "period_type": period_type,
        "statements": statements,
    }

    # Cache it
    await set_cached_data(
        db, company["id"], "edgar_xbrl", statement_type, period_type,
        result, settings.cache_ttl_financials,
    )

    return result


async def get_key_metrics(db: AsyncSession, ticker: str) -> dict:
    """Get key financial metrics from yfinance (real-time) with caching."""
    settings = get_settings()
    company = await get_or_create_company(db, ticker)
    if not company:
        return {"ticker": ticker}

    # Check cache (shorter TTL for price-sensitive data)
    cached = await get_cached_data(db, company["id"], "yfinance", "key_metrics", "current")
    if cached:
        return cached

    # Fetch from yfinance
    info = await yfinance_svc.get_stock_info(ticker)
    if not info:
        return {"ticker": ticker}

    # Cache with price TTL
    await set_cached_data(
        db, company["id"], "yfinance", "key_metrics", "current",
        info, settings.cache_ttl_prices,
    )

    return info


async def get_growth_metrics(db: AsyncSession, ticker: str) -> dict:
    """Calculate growth/emerging company metrics from EDGAR + yfinance data."""
    company = await get_or_create_company(db, ticker)
    if not company:
        return {"ticker": ticker}

    cik = company.get("cik", "").zfill(10)

    # Get XBRL data for time series analysis
    facts = await edgar.get_xbrl_company_facts(cik)
    if not facts:
        return {"ticker": ticker}

    # Revenue growth rates
    revenue_series = edgar.extract_financial_time_series(
        facts, {"Revenues": "revenue", "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue"}, "annual"
    ).get("revenue", [])

    growth_rates = []
    for i in range(1, len(revenue_series)):
        prev = revenue_series[i - 1].get("value", 0)
        curr = revenue_series[i].get("value", 0)
        if prev and prev > 0:
            rate = (curr - prev) / prev
            growth_rates.append({"period": revenue_series[i]["period"], "growth_rate": round(rate, 4)})

    # Cash and burn rate
    cash_series = edgar.extract_financial_time_series(
        facts, {"CashAndCashEquivalentsAtCarryingValue": "cash"}, "quarterly"
    ).get("cash", [])

    cash_on_hand = cash_series[-1]["value"] if cash_series else None
    burn_rate = None
    if len(cash_series) >= 2:
        recent_cash = cash_series[-1]["value"] or 0
        prev_cash = cash_series[-2]["value"] or 0
        burn_rate = prev_cash - recent_cash  # Positive = burning cash

    runway = None
    if burn_rate and burn_rate > 0 and cash_on_hand:
        runway = cash_on_hand / burn_rate  # Quarters of runway

    # Share count (dilution tracking)
    share_concepts = {
        "CommonStockSharesOutstanding": "shares",
        "WeightedAverageNumberOfDilutedSharesOutstanding": "shares",
    }
    share_series = edgar.extract_financial_time_series(facts, share_concepts, "annual").get("shares", [])

    dilution_rate = None
    if len(share_series) >= 2:
        earliest = share_series[0].get("value", 0)
        latest = share_series[-1].get("value", 0)
        years = len(share_series) - 1
        if earliest and years > 0:
            dilution_rate = ((latest / earliest) ** (1 / years) - 1)

    # R&D intensity
    rd_series = edgar.extract_financial_time_series(
        facts, {"ResearchAndDevelopmentExpense": "rd"}, "annual"
    ).get("rd", [])
    rd_expense = rd_series[-1]["value"] if rd_series else None
    rd_pct = None
    if rd_expense and revenue_series and revenue_series[-1].get("value"):
        rd_pct = rd_expense / revenue_series[-1]["value"]

    # Insider activity from yfinance
    insiders = await yfinance_svc.get_insider_transactions(ticker)
    buys = sum(1 for t in insiders if "purchase" in str(t.get("Text", "")).lower() or "buy" in str(t.get("Text", "")).lower())
    sells = sum(1 for t in insiders if "sale" in str(t.get("Text", "")).lower() or "sell" in str(t.get("Text", "")).lower())

    return {
        "ticker": ticker,
        "revenue_growth_rates": growth_rates,
        "cash_on_hand": cash_on_hand,
        "burn_rate": burn_rate,
        "cash_runway_quarters": round(runway, 1) if runway else None,
        "share_count_history": [{"period": e["period"], "shares": e["value"]} for e in share_series],
        "dilution_rate": round(dilution_rate, 4) if dilution_rate else None,
        "rd_expense": rd_expense,
        "rd_as_pct_revenue": round(rd_pct, 4) if rd_pct else None,
        "insider_buys_6m": buys,
        "insider_sells_6m": sells,
    }
