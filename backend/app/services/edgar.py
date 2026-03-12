"""SEC EDGAR API client for fetching company data, XBRL financials, and filings."""

import logging
from collections import Counter
from datetime import date as date_type

import httpx
from app.config import get_settings
from app.utils.rate_limiter import edgar_rate_limiter

logger = logging.getLogger(__name__)

BASE_URL = "https://data.sec.gov"
EFTS_URL = "https://efts.sec.gov/LATEST"

# Mapping of common XBRL concepts to readable names.
# Companies switch taxonomy concepts over time (e.g. ASC 606 moved many from
# "Revenues" to "RevenueFromContractWithCustomerExcludingAssessedTax").
# We list ALL known variants for each field — extract_financial_time_series()
# merges them, preferring the most recently filed value when periods overlap.
INCOME_STATEMENT_CONCEPTS = {
    # Revenue — companies switched en masse around 2018 for ASC 606 adoption
    "Revenues": "revenue",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "RevenueFromContractWithCustomerIncludingAssessedTax": "revenue",
    "SalesRevenueNet": "revenue",
    "SalesRevenueGoodsNet": "revenue",
    "SalesRevenueServicesNet": "revenue",
    # Cost of revenue — "CostOfGoodsSold" used pre-2018 by many companies
    "CostOfGoodsAndServicesSold": "cost_of_revenue",
    "CostOfRevenue": "cost_of_revenue",
    "CostOfGoodsSold": "cost_of_revenue",
    "GrossProfit": "gross_profit",
    "ResearchAndDevelopmentExpense": "rd_expense",
    "SellingGeneralAndAdministrativeExpense": "sga_expense",
    "OperatingIncomeLoss": "operating_income",
    # Operating expenses — some filers use "CostsAndExpenses" (total) instead
    "OperatingExpenses": "operating_expenses",
    "CostsAndExpenses": "operating_expenses",
    "InterestExpense": "interest_expense",
    "IncomeTaxExpenseBenefit": "income_tax",
    "NetIncomeLoss": "net_income",
    "ProfitLoss": "net_income",
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
    "LongTermDebtAndCapitalLeaseObligations": "long_term_debt",
    "LiabilitiesCurrent": "current_liabilities",
    "Liabilities": "total_liabilities",
    "StockholdersEquity": "stockholders_equity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": "stockholders_equity",
    "RetainedEarningsAccumulatedDeficit": "retained_earnings",
    "LiabilitiesAndStockholdersEquity": "total_liabilities_and_equity",
}

CASH_FLOW_CONCEPTS = {
    "NetCashProvidedByUsedInOperatingActivities": "operating_cash_flow",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations": "operating_cash_flow",
    "NetCashProvidedByUsedInInvestingActivities": "investing_cash_flow",
    "NetCashProvidedByUsedInFinancingActivities": "financing_cash_flow",
    # Capex — AMZN, GE switched from specific PPE to broader "ProductiveAssets"
    "PaymentsToAcquirePropertyPlantAndEquipment": "capex",
    "PaymentsToAcquireProductiveAssets": "capex",
    "DepreciationDepletionAndAmortization": "depreciation_amortization",
    "PaymentOfDividends": "dividends_paid",
    "PaymentsOfDividends": "dividends_paid",
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

    Multiple XBRL concepts can map to the same field (e.g. "Revenues" and
    "RevenueFromContractWithCustomerExcludingAssessedTax" both → "revenue").
    Companies frequently switch taxonomy concepts across filings — for instance,
    ASC 606 adoption moved many companies from "Revenues" to the longer variant.
    We MERGE data from all matching concepts so no periods are lost. When two
    concepts provide data for the same period, the entry with the later filing
    date wins (it reflects the most recent disclosure).

    Args:
        company_facts: Raw JSON from the companyfacts endpoint.
        concept_mapping: Dict mapping XBRL concept names to readable field names.
        period_type: "annual" for 10-K data, "quarterly" for 10-Q data.

    Returns:
        Dict mapping readable field names to lists of {period, value} dicts.
    """
    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})
    # Accumulate entries per field across all matching XBRL concepts.
    # Key = (field_name, period_end), Value = best entry dict for that period.
    merged: dict[str, dict[str, dict]] = {}

    for xbrl_concept, field_name in concept_mapping.items():
        concept_data = us_gaap.get(xbrl_concept)
        if not concept_data:
            continue

        if field_name not in merged:
            merged[field_name] = {}

        # XBRL data can be in different units (USD, shares, USD/shares for EPS)
        for unit_type, entries in concept_data.get("units", {}).items():
            for entry in entries:
                # Filter by form type to get annual (10-K) vs quarterly (10-Q)
                form = entry.get("form", "")
                if period_type == "annual" and form not in ("10-K", "10-K/A"):
                    continue
                if period_type == "quarterly" and form not in ("10-Q", "10-Q/A"):
                    continue

                period_end = entry.get("end")
                if not period_end:
                    continue

                filed = entry.get("filed", "")
                existing = merged[field_name].get(period_end)

                # Keep the entry with the later filing date (most recent disclosure).
                # If no existing entry, or this one was filed more recently, use it.
                if not existing or filed > existing.get("filed", ""):
                    merged[field_name][period_end] = {
                        "period": period_end,
                        "value": entry.get("val"),
                        "form": form,
                        "filed": filed,
                    }

    # Convert merged dicts into sorted lists
    results: dict[str, list[dict]] = {}
    for field_name, period_map in merged.items():
        if period_map:
            results[field_name] = sorted(period_map.values(), key=lambda x: x["period"])

    return results


# ---------------------------------------------------------------------------
# Quarterly standalone / YTD extraction
# ---------------------------------------------------------------------------
# Duration thresholds (days) for classifying XBRL entries by period length.
# Standalone quarter ~90d, 6M YTD ~180d, 9M YTD ~270d, Annual ~365d.
_DUR_STANDALONE = (60, 120)
_DUR_YTD_6M = (150, 210)
_DUR_YTD_9M = (240, 300)
_DUR_ANNUAL = (330, 400)

# Statement types where entries are cumulative (flow statements).
# Balance sheet items are point-in-time and don't need duration logic.
_FLOW_STATEMENT_TYPES = ("income_statement", "cash_flow")


def _detect_fiscal_year_end_month(company_facts: dict) -> int:
    """Detect fiscal year end month by scanning 10-K end dates.

    Returns the most common month (1-12) across all 10-K filings.
    Defaults to 12 (December) if no 10-K data found.
    """
    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})
    month_counts: Counter[int] = Counter()

    for concept_data in us_gaap.values():
        for entries in concept_data.get("units", {}).values():
            for entry in entries:
                if entry.get("form") in ("10-K", "10-K/A"):
                    end = entry.get("end", "")
                    if len(end) >= 7:
                        try:
                            month_counts[int(end[5:7])] += 1
                        except ValueError:
                            continue

    if not month_counts:
        return 12
    return month_counts.most_common(1)[0][0]


def _assign_quarter_label(
    end_date_str: str,
    fy_end_month: int,
) -> tuple[str, str]:
    """Map a period end date to a quarter label based on fiscal year end.

    Args:
        end_date_str: Period end date "YYYY-MM-DD".
        fy_end_month: Fiscal year end month (1-12).

    Returns:
        (quarter_label, sort_key) — e.g. ("Q3 '24", "2024-Q3").
        The sort_key ensures chronological ordering within fiscal years.
    """
    try:
        end_date = date_type.fromisoformat(end_date_str)
    except ValueError:
        return (end_date_str, end_date_str)

    end_month = end_date.month

    # Fiscal quarters: Q1 ends 3 months after FY start, Q2 after 6, etc.
    # FY start month = (fy_end_month % 12) + 1
    # Quarter number = how many 3-month periods from FY start to end_month
    fy_start_month = (fy_end_month % 12) + 1
    # Months since fiscal year start (1-indexed, wrapping around)
    months_in = (end_month - fy_start_month) % 12 + 1
    quarter_num = (months_in - 1) // 3 + 1  # 1-4

    # For display, use calendar year of the end date
    year_short = str(end_date.year)[-2:]
    label = f"Q{quarter_num} '{year_short}"

    # Sort key: fiscal year + quarter number. Fiscal year = calendar year of the
    # fiscal year end. For Dec FY, Q1 (Mar 2024) is FY2024. For Jun FY, Q1
    # (Sep 2023) is FY2024 (ending Jun 2024).
    if end_month <= fy_end_month:
        fiscal_year = end_date.year
    else:
        fiscal_year = end_date.year + 1
    sort_key = f"{fiscal_year}-Q{quarter_num}"

    return (label, sort_key)


def _collect_all_entries(
    company_facts: dict,
    concept_mapping: dict,
) -> dict[str, list[dict]]:
    """Collect ALL XBRL entries (10-Q + 10-K) for each field, keeping start dates.

    Unlike extract_financial_time_series which filters by form type and deduplicates
    by end date, this returns every entry with duration info for downstream processing.
    """
    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})
    # field_name → list of raw entries with start/end/val/form/filed
    collected: dict[str, list[dict]] = {}

    for xbrl_concept, field_name in concept_mapping.items():
        concept_data = us_gaap.get(xbrl_concept)
        if not concept_data:
            continue
        if field_name not in collected:
            collected[field_name] = []

        for entries in concept_data.get("units", {}).values():
            for entry in entries:
                form = entry.get("form", "")
                if form not in ("10-K", "10-K/A", "10-Q", "10-Q/A"):
                    continue
                end = entry.get("end")
                if not end:
                    continue

                collected[field_name].append({
                    "start": entry.get("start"),  # None for balance sheet
                    "end": end,
                    "value": entry.get("val"),
                    "form": form,
                    "filed": entry.get("filed", ""),
                })

    return collected


def _classify_duration(days: int) -> str | None:
    """Classify a period duration into a category."""
    if _DUR_STANDALONE[0] <= days <= _DUR_STANDALONE[1]:
        return "standalone"
    if _DUR_YTD_6M[0] <= days <= _DUR_YTD_6M[1]:
        return "ytd_6m"
    if _DUR_YTD_9M[0] <= days <= _DUR_YTD_9M[1]:
        return "ytd_9m"
    if _DUR_ANNUAL[0] <= days <= _DUR_ANNUAL[1]:
        return "annual"
    return None


def _best_entry_by_filed(entries: list[dict]) -> dict | None:
    """Pick the most recently filed entry from a list (deduplication)."""
    if not entries:
        return None
    return max(entries, key=lambda e: e.get("filed", ""))


def extract_quarterly_standalone(
    company_facts: dict,
    concept_mapping: dict,
    statement_type: str,
) -> dict[str, list[dict]]:
    """Extract standalone quarterly values from XBRL data.

    For flow statements (income/cash flow): uses start/end duration to find
    ~90-day standalone quarter entries. Falls back to YTD subtraction when
    standalone entries aren't available. Derives Q4 from Annual - 9M YTD.

    For balance sheet: point-in-time, no duration logic needed. Returns entries
    from both 10-Q and 10-K (Q4 snapshot).

    Returns dict mapping field names to lists of:
        {"period": "2024-03-31", "quarter_label": "Q1 '24", "value": ..., "is_derived": bool}
    """
    fy_end_month = _detect_fiscal_year_end_month(company_facts)
    collected = _collect_all_entries(company_facts, concept_mapping)
    is_flow = statement_type in _FLOW_STATEMENT_TYPES
    results: dict[str, list[dict]] = {}

    for field_name, entries in collected.items():
        if is_flow:
            quarter_entries = _isolate_standalone_quarters(entries, fy_end_month)
        else:
            # Balance sheet: point-in-time. Deduplicate by end date (latest filed wins).
            by_end: dict[str, list[dict]] = {}
            for e in entries:
                by_end.setdefault(e["end"], []).append(e)

            quarter_entries = []
            for end_date, group in sorted(by_end.items()):
                best = _best_entry_by_filed(group)
                if best:
                    label, sort_key = _assign_quarter_label(end_date, fy_end_month)
                    quarter_entries.append({
                        "period": end_date,
                        "quarter_label": label,
                        "sort_key": sort_key,
                        "value": best["value"],
                        "is_derived": False,
                    })

        if quarter_entries:
            # Sort by period date for consistent ordering
            quarter_entries.sort(key=lambda x: x["period"])
            results[field_name] = quarter_entries

    return results


def _isolate_standalone_quarters(
    entries: list[dict],
    fy_end_month: int,
) -> list[dict]:
    """Isolate standalone quarter values from a mix of standalone/YTD/annual entries.

    Strategy:
    1. Prefer actual standalone entries (~90 days) when available
    2. Derive missing quarters from YTD subtraction (Q2 = 6M - Q1, Q3 = 9M - 6M)
    3. Derive Q4 from Annual - 9M YTD
    """
    # Classify each entry by duration
    by_category: dict[str, dict[str, list[dict]]] = {
        "standalone": {},  # end_date → entries
        "ytd_6m": {},
        "ytd_9m": {},
        "annual": {},
    }

    for entry in entries:
        start = entry.get("start")
        end = entry.get("end")
        if not start or not end:
            continue
        try:
            start_d = date_type.fromisoformat(start)
            end_d = date_type.fromisoformat(end)
        except ValueError:
            continue

        duration = (end_d - start_d).days
        category = _classify_duration(duration)
        if category:
            by_category[category].setdefault(end, []).append(entry)

    # Pick best entry per end date per category
    standalone: dict[str, dict] = {}  # end_date → best entry
    ytd_6m: dict[str, dict] = {}
    ytd_9m: dict[str, dict] = {}
    annual: dict[str, dict] = {}

    for end_date, group in by_category["standalone"].items():
        best = _best_entry_by_filed(group)
        if best:
            standalone[end_date] = best
    for end_date, group in by_category["ytd_6m"].items():
        best = _best_entry_by_filed(group)
        if best:
            ytd_6m[end_date] = best
    for end_date, group in by_category["ytd_9m"].items():
        best = _best_entry_by_filed(group)
        if best:
            ytd_9m[end_date] = best
    for end_date, group in by_category["annual"].items():
        best = _best_entry_by_filed(group)
        if best:
            annual[end_date] = best

    # Build quarterly results.
    # For each fiscal year, we want Q1-Q4 standalone values.
    result: list[dict] = []

    # Step 1: Use all directly reported standalone quarters
    for end_date, entry in standalone.items():
        label, sort_key = _assign_quarter_label(end_date, fy_end_month)
        result.append({
            "period": end_date,
            "quarter_label": label,
            "sort_key": sort_key,
            "value": entry["value"],
            "is_derived": False,
        })

    # Track which end dates already have values
    have_values = {r["period"] for r in result}

    # Step 2: Derive missing quarters from YTD subtraction.
    # Q1 standalone = 3M YTD (same as standalone, already handled above).
    # Q2 standalone = 6M YTD - most recent Q1 standalone (matching fiscal year).
    # Q3 standalone = 9M YTD - 6M YTD.
    # We match by fiscal year: entries in the same fiscal year should have
    # consecutive end dates ~3 months apart.

    # Derive Q2 from 6M YTD - preceding standalone quarter
    for end_6m, entry_6m in ytd_6m.items():
        if end_6m in have_values:
            continue
        val_6m = entry_6m["value"]
        if val_6m is None:
            continue
        # Find Q1 standalone ending ~3 months before this 6M end
        q1_val = _find_preceding_quarter_value(end_6m, standalone, months_back=3)
        if q1_val is not None:
            derived_val = val_6m - q1_val
            label, sort_key = _assign_quarter_label(end_6m, fy_end_month)
            result.append({
                "period": end_6m,
                "quarter_label": label,
                "sort_key": sort_key,
                "value": derived_val,
                "is_derived": True,
            })
            have_values.add(end_6m)

    # Derive Q3 from 9M YTD - 6M YTD
    for end_9m, entry_9m in ytd_9m.items():
        if end_9m in have_values:
            continue
        val_9m = entry_9m["value"]
        if val_9m is None:
            continue
        ytd6_val = _find_preceding_ytd_value(end_9m, ytd_6m, months_back=3)
        if ytd6_val is not None:
            derived_val = val_9m - ytd6_val
            label, sort_key = _assign_quarter_label(end_9m, fy_end_month)
            result.append({
                "period": end_9m,
                "quarter_label": label,
                "sort_key": sort_key,
                "value": derived_val,
                "is_derived": True,
            })
            have_values.add(end_9m)

    # Step 3: Derive Q4 = Annual - 9M YTD
    for end_annual, entry_annual in annual.items():
        if end_annual in have_values:
            continue
        val_annual = entry_annual["value"]
        if val_annual is None:
            continue
        ytd9_val = _find_preceding_ytd_value(end_annual, ytd_9m, months_back=3)
        if ytd9_val is not None:
            derived_val = val_annual - ytd9_val
            label, sort_key = _assign_quarter_label(end_annual, fy_end_month)
            result.append({
                "period": end_annual,
                "quarter_label": label,
                "sort_key": sort_key,
                "value": derived_val,
                "is_derived": True,
            })
            have_values.add(end_annual)

    return result


def _find_preceding_quarter_value(
    end_date_str: str,
    standalone: dict[str, dict],
    months_back: int = 3,
) -> float | None:
    """Find the standalone quarter value ending ~months_back before end_date_str."""
    try:
        end_d = date_type.fromisoformat(end_date_str)
    except ValueError:
        return None

    # Look for entries ending 75-105 days before (roughly 3 months)
    for candidate_end, entry in standalone.items():
        try:
            cand_d = date_type.fromisoformat(candidate_end)
        except ValueError:
            continue
        diff = (end_d - cand_d).days
        if 75 <= diff <= 105:
            return entry.get("value")
    return None


def _find_preceding_ytd_value(
    end_date_str: str,
    ytd_entries: dict[str, dict],
    months_back: int = 3,
) -> float | None:
    """Find the YTD value ending ~months_back before end_date_str."""
    try:
        end_d = date_type.fromisoformat(end_date_str)
    except ValueError:
        return None

    for candidate_end, entry in ytd_entries.items():
        try:
            cand_d = date_type.fromisoformat(candidate_end)
        except ValueError:
            continue
        diff = (end_d - cand_d).days
        if 75 <= diff <= 105:
            return entry.get("value")
    return None


def extract_quarterly_ytd(
    company_facts: dict,
    concept_mapping: dict,
    statement_type: str,
) -> dict[str, list[dict]]:
    """Extract YTD cumulative quarterly values from XBRL data.

    For flow statements: returns the cumulative YTD values (3M, 6M, 9M, FY).
    For balance sheet: same as standalone (point-in-time).

    Returns dict mapping field names to lists of:
        {"period": "2024-09-30", "quarter_label": "9M '24", "value": ..., "is_derived": false}
    """
    fy_end_month = _detect_fiscal_year_end_month(company_facts)
    collected = _collect_all_entries(company_facts, concept_mapping)
    is_flow = statement_type in _FLOW_STATEMENT_TYPES
    results: dict[str, list[dict]] = {}

    if not is_flow:
        # Balance sheet: delegate to standalone (same logic for point-in-time)
        return extract_quarterly_standalone(company_facts, concept_mapping, statement_type)

    for field_name, entries in collected.items():
        ytd_entries: list[dict] = []

        # Group by end date and duration category
        by_end: dict[str, dict[str, list[dict]]] = {}  # end → category → entries
        for entry in entries:
            start = entry.get("start")
            end = entry.get("end")
            if not start or not end:
                continue
            try:
                start_d = date_type.fromisoformat(start)
                end_d = date_type.fromisoformat(end)
            except ValueError:
                continue
            duration = (end_d - start_d).days
            category = _classify_duration(duration)
            if category:
                by_end.setdefault(end, {}).setdefault(category, []).append(entry)

        # For YTD view, we want the cumulative values:
        # Q1 → standalone (3M, which equals YTD at Q1)
        # Q2 → 6M YTD
        # Q3 → 9M YTD
        # Q4 → Annual (FY total)
        for end_date in sorted(by_end.keys()):
            categories = by_end[end_date]
            best = None
            label_prefix = ""

            # Prefer the longest cumulative period for this end date
            if "annual" in categories:
                best = _best_entry_by_filed(categories["annual"])
                label_prefix = "FY"
            elif "ytd_9m" in categories:
                best = _best_entry_by_filed(categories["ytd_9m"])
                label_prefix = "9M"
            elif "ytd_6m" in categories:
                best = _best_entry_by_filed(categories["ytd_6m"])
                label_prefix = "6M"
            elif "standalone" in categories:
                best = _best_entry_by_filed(categories["standalone"])
                label_prefix = "3M"

            if best:
                try:
                    end_d = date_type.fromisoformat(end_date)
                    year_short = str(end_d.year)[-2:]
                except ValueError:
                    year_short = end_date[:4]
                label = f"{label_prefix} '{year_short}"

                # Sort key: use period end for chronological order
                _, sort_key = _assign_quarter_label(end_date, fy_end_month)

                ytd_entries.append({
                    "period": end_date,
                    "quarter_label": label,
                    "sort_key": sort_key,
                    "value": best["value"],
                    "is_derived": False,
                })

        if ytd_entries:
            ytd_entries.sort(key=lambda x: x["period"])
            results[field_name] = ytd_entries

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
