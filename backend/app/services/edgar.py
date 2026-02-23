"""SEC EDGAR API client for fetching company data, XBRL financials, and filings."""

import httpx
from app.config import get_settings
from app.utils.rate_limiter import edgar_rate_limiter

BASE_URL = "https://data.sec.gov"
EFTS_URL = "https://efts.sec.gov/LATEST"

# Mapping of common XBRL concepts to readable names
INCOME_STATEMENT_CONCEPTS = {
    "Revenues": "revenue",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "SalesRevenueNet": "revenue",
    "CostOfGoodsAndServicesSold": "cost_of_revenue",
    "CostOfRevenue": "cost_of_revenue",
    "GrossProfit": "gross_profit",
    "ResearchAndDevelopmentExpense": "rd_expense",
    "SellingGeneralAndAdministrativeExpense": "sga_expense",
    "OperatingIncomeLoss": "operating_income",
    "OperatingExpenses": "operating_expenses",
    "InterestExpense": "interest_expense",
    "IncomeTaxExpenseBenefit": "income_tax",
    "NetIncomeLoss": "net_income",
    "EarningsPerShareBasic": "eps_basic",
    "EarningsPerShareDiluted": "eps_diluted",
    "WeightedAverageNumberOfShareOutstandingBasicAndDiluted": "shares_outstanding",
    "WeightedAverageNumberOfDilutedSharesOutstanding": "shares_diluted",
    "CommonStockSharesOutstanding": "shares_outstanding",
}

BALANCE_SHEET_CONCEPTS = {
    "CashAndCashEquivalentsAtCarryingValue": "cash_and_equivalents",
    "ShortTermInvestments": "short_term_investments",
    "AccountsReceivableNetCurrent": "accounts_receivable",
    "InventoryNet": "inventory",
    "AssetsCurrent": "current_assets",
    "PropertyPlantAndEquipmentNet": "ppe_net",
    "Goodwill": "goodwill",
    "Assets": "total_assets",
    "AccountsPayableCurrent": "accounts_payable",
    "LongTermDebt": "long_term_debt",
    "LongTermDebtNoncurrent": "long_term_debt",
    "LiabilitiesCurrent": "current_liabilities",
    "Liabilities": "total_liabilities",
    "StockholdersEquity": "stockholders_equity",
    "RetainedEarningsAccumulatedDeficit": "retained_earnings",
    "LiabilitiesAndStockholdersEquity": "total_liabilities_and_equity",
}

CASH_FLOW_CONCEPTS = {
    "NetCashProvidedByUsedInOperatingActivities": "operating_cash_flow",
    "NetCashProvidedByUsedInInvestingActivities": "investing_cash_flow",
    "NetCashProvidedByUsedInFinancingActivities": "financing_cash_flow",
    "PaymentsToAcquirePropertyPlantAndEquipment": "capex",
    "DepreciationDepletionAndAmortization": "depreciation_amortization",
    "PaymentOfDividends": "dividends_paid",
    "PaymentsForRepurchaseOfCommonStock": "share_repurchases",
}


def _get_headers() -> dict:
    settings = get_settings()
    return {
        "User-Agent": settings.sec_edgar_user_agent,
        "Accept": "application/json",
    }


async def lookup_cik(ticker: str) -> dict | None:
    """Look up a company's CIK and basic info from SEC EDGAR by ticker.

    Returns dict with keys: cik, name, ticker, exchange, or None if not found.
    """
    await edgar_rate_limiter.acquire()
    ticker = ticker.upper()
    async with httpx.AsyncClient() as client:
        # Use SEC's company_tickers.json to map ticker -> CIK
        resp = await client.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=_get_headers(),
        )
        if resp.status_code != 200:
            return await _search_company(ticker)

        data = resp.json()
        # data is a dict of {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
        match = None
        for entry in data.values():
            if entry.get("ticker", "").upper() == ticker:
                match = entry
                break

        if not match:
            return await _search_company(ticker)

        cik = str(match["cik_str"]).zfill(10)

        # Now fetch full company details from submissions endpoint using the CIK
        await edgar_rate_limiter.acquire()
        sub_resp = await client.get(
            f"{BASE_URL}/submissions/CIK{cik}.json",
            headers=_get_headers(),
        )
        if sub_resp.status_code == 200:
            sub_data = sub_resp.json()
            return {
                "cik": cik,
                "name": sub_data.get("name", match.get("title", "")),
                "ticker": ticker,
                "exchange": sub_data.get("exchanges", [""])[0] if sub_data.get("exchanges") else "",
                "sic": sub_data.get("sic", ""),
                "sic_description": sub_data.get("sicDescription", ""),
                "fiscal_year_end": sub_data.get("fiscalYearEnd", ""),
            }

        return {
            "cik": cik,
            "name": match.get("title", ""),
            "ticker": ticker,
        }


async def _search_company(query: str) -> dict | None:
    """Search for a company via EDGAR full-text search API."""
    await edgar_rate_limiter.acquire()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{EFTS_URL}/search-index",
            params={"q": query, "dateRange": "custom", "startdt": "2020-01-01"},
            headers=_get_headers(),
        )
        if resp.status_code != 200:
            return None
        # Parse search results to extract CIK
        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            return None
        first = hits[0].get("_source", {})
        cik = str(first.get("entity_id", "")).zfill(10)
        return {
            "cik": cik,
            "name": first.get("entity_name", ""),
            "ticker": query.upper(),
        }


async def get_company_submissions(cik: str) -> dict | None:
    """Fetch company submission history (filings list) from EDGAR.

    Args:
        cik: Zero-padded 10-digit CIK number.
    """
    await edgar_rate_limiter.acquire()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/submissions/CIK{cik}.json",
            headers=_get_headers(),
        )
        if resp.status_code != 200:
            return None
        return resp.json()


async def get_xbrl_company_facts(cik: str) -> dict | None:
    """Fetch all XBRL financial data for a company.

    Returns the full companyfacts JSON which contains all reported
    US-GAAP values across all filings as time series.

    Args:
        cik: Zero-padded 10-digit CIK number.
    """
    await edgar_rate_limiter.acquire()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/xbrl/companyfacts/CIK{cik}.json",
            headers=_get_headers(),
        )
        if resp.status_code != 200:
            return None
        return resp.json()


def extract_financial_time_series(
    company_facts: dict,
    concept_mapping: dict,
    period_type: str = "annual",
) -> dict[str, list[dict]]:
    """Extract time series data from XBRL companyfacts for given concepts.

    Args:
        company_facts: Raw JSON from the companyfacts endpoint.
        concept_mapping: Dict mapping XBRL concept names to readable field names.
        period_type: "annual" for 10-K data, "quarterly" for 10-Q data.

    Returns:
        Dict mapping readable field names to lists of {period, value} dicts.
    """
    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})
    results: dict[str, list[dict]] = {}

    for xbrl_concept, field_name in concept_mapping.items():
        concept_data = us_gaap.get(xbrl_concept)
        if not concept_data:
            continue

        # XBRL data can be in different units (USD, shares, USD/shares for EPS)
        for unit_type, entries in concept_data.get("units", {}).items():
            series = []
            seen_periods = set()

            for entry in entries:
                # Filter by form type to get annual (10-K) vs quarterly (10-Q)
                form = entry.get("form", "")
                if period_type == "annual" and form not in ("10-K", "10-K/A"):
                    continue
                if period_type == "quarterly" and form not in ("10-Q", "10-Q/A"):
                    continue

                period_end = entry.get("end")
                if not period_end or period_end in seen_periods:
                    continue

                # Skip instant vs duration mismatch for income/cash flow items
                # (balance sheet items are "instant", income/cash flow are "duration")
                seen_periods.add(period_end)
                series.append({
                    "period": period_end,
                    "value": entry.get("val"),
                    "form": form,
                    "filed": entry.get("filed"),
                })

            if series:
                # Sort by period date
                series.sort(key=lambda x: x["period"])
                # If we already have data for this field (from a different XBRL concept),
                # keep the one with more data points
                if field_name not in results or len(series) > len(results[field_name]):
                    results[field_name] = series

    return results


def parse_filings_from_submissions(submissions: dict, filing_types: list[str] | None = None) -> list[dict]:
    """Parse filing entries from EDGAR submissions data.

    Args:
        submissions: Raw JSON from the submissions endpoint.
        filing_types: Optional filter for specific filing types (e.g., ["10-K", "10-Q", "8-K"]).

    Returns:
        List of filing dicts with type, date, accession number, and URL.
    """
    recent = submissions.get("filings", {}).get("recent", {})
    if not recent:
        return []

    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    descriptions = recent.get("primaryDocDescription", [])

    cik = str(submissions.get("cik", "")).zfill(10)
    filings = []

    for i in range(len(forms)):
        form_type = forms[i] if i < len(forms) else ""
        if filing_types and form_type not in filing_types:
            continue

        accession = accessions[i] if i < len(accessions) else ""
        accession_no_dash = accession.replace("-", "")
        primary_doc = primary_docs[i] if i < len(primary_docs) else ""

        filing_url = ""
        if accession and primary_doc:
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dash}/{primary_doc}"

        filings.append({
            "filing_type": form_type,
            "filing_date": dates[i] if i < len(dates) else "",
            "accession_number": accession,
            "filing_url": filing_url,
            "description": descriptions[i] if i < len(descriptions) else "",
        })

    return filings
