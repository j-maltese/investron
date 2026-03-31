"""Buffett 4-Rules intrinsic value calculator service.

Evaluates a stock against Warren Buffett's four investing rules:
  Rule 1 — Vigilant Leadership: D/E, current ratio, ROE, P/B
  Rule 2 — Long-Term Prospects: EPS history, revenue history, sector
  Rule 3 — Stable & Understandable: BV/share trend, D/E trend, EPS trend, ROE trend
  Rule 4 — Intrinsic Value: Book value DCF (BuffettsBooks.com methodology)

Unit conventions (matching the rest of the app):
  - debt_to_equity: yfinance percentage form (e.g. 42.3 means 0.423 ratio). Divide by 100 for display.
  - roe, dividend_yield: decimal form (e.g. 0.18 means 18%)
  - bv_growth_rate, treasury_rate: decimal form (e.g. 0.069 means 6.9%)

All computation lives here; the API layer just calls get_buffett_analysis()
and proxies the result. Heavy EDGAR data is cached by the existing
get_financial_statements + get_key_metrics cache layer (24h and 15min TTL).
The assembled Buffett result is cached 15 minutes.
"""

import asyncio
import logging
import time

import yfinance as yf
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.financials import get_financial_statements, get_key_metrics
from app.services.company import get_or_create_company
from app.utils.cache import get_cached_data, set_cached_data

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Treasury rate cache — 24h in-memory, avoids DB overhead for a single number.
# Shared across all requests for the same server process.
# ---------------------------------------------------------------------------
_treasury_cache: dict = {"rate": None, "fetched_at": 0}
_TREASURY_TTL = 86400  # 24 hours


def _fetch_treasury_rate_sync() -> float | None:
    """Fetch the 10-year U.S. Treasury yield from yfinance (synchronous).

    yfinance returns ^TNX's regularMarketPrice as the yield in % form
    (e.g. 4.52 means 4.52%). We convert to decimal before returning.
    Raises on network errors so the caller can handle gracefully.
    """
    ticker = yf.Ticker("^TNX")
    info = ticker.info
    rate = info.get("regularMarketPrice")
    if rate is not None and rate > 0:
        return float(rate) / 100
    return None


async def get_treasury_rate() -> float:
    """Get current 10Y Treasury yield as a decimal (e.g. 0.0452 for 4.52%).

    Cached 24h in memory so it isn't re-fetched on every Buffett analysis call.
    Falls back to 0.045 (4.5%) if the live fetch fails entirely.
    Clamped to minimum 0.001 to prevent division-by-zero in the IV annuity formula.
    """
    now = time.time()
    if _treasury_cache["rate"] is not None and (now - _treasury_cache["fetched_at"]) < _TREASURY_TTL:
        return _treasury_cache["rate"]

    loop = asyncio.get_running_loop()
    try:
        rate = await loop.run_in_executor(None, _fetch_treasury_rate_sync)
    except Exception as e:
        logger.warning("Treasury rate fetch failed: %s", e)
        rate = None

    if rate is None:
        # Keep the stale value if we have one; otherwise use a reasonable default
        rate = _treasury_cache["rate"] or 0.045

    rate = max(0.001, rate)  # clamp: annuity formula blows up at r=0
    _treasury_cache["rate"] = rate
    _treasury_cache["fetched_at"] = now
    return rate


# ---------------------------------------------------------------------------
# Time-series helpers
# ---------------------------------------------------------------------------

def _extract_series(statements: list[dict], field: str) -> list[dict]:
    """Extract [{period, value}] for a named field from statement rows.

    Statements come from get_financial_statements() and have the shape:
      {"period": "2023-12-31", "net_income": 12345678, ...}
    Returns only rows where the field is present and non-None, sorted by period.
    """
    return sorted(
        [{"period": s["period"], "value": s[field]} for s in statements if s.get(field) is not None],
        key=lambda x: x["period"],
    )


def _compute_cagr(series: list[dict]) -> float | None:
    """Annualized growth rate from a sorted [{period, value}] list.

    CAGR = (newest / oldest)^(1 / n_years) - 1
    Returns None when there are fewer than 2 data points, or when the base
    value is <= 0 (CAGR is undefined for zero/negative starting values —
    e.g. a company that had negative EPS can't have a meaningful CAGR).
    """
    valid = [e for e in series if e.get("value") is not None]
    if len(valid) < 2:
        return None
    oldest_val = valid[0]["value"]
    newest_val = valid[-1]["value"]
    years = len(valid) - 1
    if not oldest_val or oldest_val <= 0:
        return None
    try:
        return (newest_val / oldest_val) ** (1 / years) - 1
    except (ValueError, ZeroDivisionError):
        return None


def _count_consecutive_positive(series: list[dict]) -> int:
    """Count trailing consecutive positive values working backward from the most recent."""
    count = 0
    for entry in reversed(series):
        val = entry.get("value")
        if val is not None and val > 0:
            count += 1
        else:
            break
    return count


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

async def get_buffett_analysis(ticker: str, db: AsyncSession) -> dict:
    """Compute Buffett 4-rule analysis for a ticker.

    Orchestrates data fetching from yfinance (key_metrics, already cached 15min)
    and EDGAR (financial statements, already cached 24h), then runs all four
    rule calculations. The assembled result is itself cached 15 min.

    Errors in individual rules are isolated: a failed EDGAR fetch won't prevent
    Rule 1 (which only needs yfinance data) from showing results.

    Returns a rich dict with keys: ticker, company_name, price, rule1, rule2, rule3, rule4.
    On fatal error (company not found, metrics unavailable), returns {"error": True}.
    """
    settings = get_settings()
    company = await get_or_create_company(db, ticker)
    if not company:
        return {"ticker": ticker, "error": True, "error_message": "Company not found"}

    # Check assembled cache (avoids re-running all rule logic on repeat calls)
    cached = await get_cached_data(db, company["id"], "buffett", "analysis", "current")
    if cached:
        return cached

    # Fetch all sources in parallel — EDGAR calls are already cached 24h internally
    metrics, income_data, balance_data, treasury_rate = await asyncio.gather(
        get_key_metrics(db, ticker),
        get_financial_statements(db, ticker, "income_statement", "annual"),
        get_financial_statements(db, ticker, "balance_sheet", "annual"),
        get_treasury_rate(),
    )

    if metrics.get("error"):
        return {"ticker": ticker, "error": True, "error_message": metrics.get("error_message")}

    income_statements = income_data.get("statements", [])
    balance_statements = balance_data.get("statements", [])

    # -----------------------------------------------------------------------
    # Extract time series from statement rows
    # -----------------------------------------------------------------------

    # Income statement fields
    eps_series = (
        _extract_series(income_statements, "eps_diluted")
        or _extract_series(income_statements, "eps_basic")
    )
    revenue_series = _extract_series(income_statements, "revenue")
    net_income_series = _extract_series(income_statements, "net_income")
    # Prefer diluted shares; fall back to basic for BV/share computation
    shares_series = (
        _extract_series(income_statements, "shares_diluted")
        or _extract_series(income_statements, "shares_outstanding")
    )

    # Balance sheet fields
    equity_series = _extract_series(balance_statements, "stockholders_equity")
    debt_series = _extract_series(balance_statements, "long_term_debt")

    # Period-indexed lookup tables for joining income + balance data
    equity_by_period = {e["period"]: e["value"] for e in equity_series}
    shares_by_period = {e["period"]: e["value"] for e in shares_series}
    net_income_by_period = {e["period"]: e["value"] for e in net_income_series}
    debt_by_period = {e["period"]: e["value"] for e in debt_series}

    # BV/share per year — the foundation of Rule 3 and Rule 4 history
    bv_history = []
    for period in sorted(equity_by_period):
        equity = equity_by_period[period]
        shares = shares_by_period.get(period)
        if equity is not None and shares and shares > 0:
            bv_history.append({"period": period, "value": round(equity / shares, 4)})

    # D/E history per year (ratio form = long_term_debt / stockholders_equity)
    # NOTE: This is ratio form (0-n), not the % form yfinance returns for current D/E.
    # We use ratio form here so the sparkline shows 0.42x, not 42.3%.
    de_history = []
    for period in sorted(equity_by_period):
        equity = equity_by_period[period]
        debt = debt_by_period.get(period)
        if equity is not None and equity != 0 and debt is not None:
            de_history.append({"period": period, "value": round(debt / equity, 4)})

    # ROE history per year (decimal form — net_income / stockholders_equity)
    roe_history = []
    for period in sorted(equity_by_period):
        equity = equity_by_period[period]
        net_inc = net_income_by_period.get(period)
        if equity is not None and equity != 0 and net_inc is not None:
            roe_history.append({"period": period, "value": round(net_inc / equity, 4)})

    # -----------------------------------------------------------------------
    # Derived current-period values from yfinance
    # -----------------------------------------------------------------------
    current_de = metrics.get("debt_to_equity")       # % form (42.3 = 0.423 ratio)
    current_ratio = metrics.get("current_ratio")
    current_roe = metrics.get("roe")                 # decimal (0.18 = 18%)
    pb_ratio = metrics.get("pb_ratio")
    book_value = metrics.get("book_value")           # per share
    price = metrics.get("price")
    sector = metrics.get("sector") or ""
    industry = metrics.get("industry") or ""
    company_name = metrics.get("name") or ""

    # Negative equity: book_value < 0 or D/E < 0 (yfinance signals this with negative value)
    negative_equity = (
        (book_value is not None and book_value < 0)
        or (current_de is not None and current_de < 0)
    )

    # Financial sector warning: D/E thresholds don't apply to banks/insurance companies
    # because they inherently carry high leverage as part of their business model.
    financial_sector_warning = sector.lower() in (
        "financial services", "banks", "insurance", "diversified financials"
    )

    # -----------------------------------------------------------------------
    # Rule 1 — Vigilant Leadership
    # Checks whether management maintains a conservative balance sheet.
    # -----------------------------------------------------------------------
    rule1 = {
        "debt_to_equity": current_de,      # yfinance % form; frontend divides by 100 for display
        "current_ratio": current_ratio,
        "roe": current_roe,                # decimal form
        "pb_ratio": pb_ratio,
        "negative_equity": negative_equity,
        "financial_sector_warning": financial_sector_warning,
    }

    # -----------------------------------------------------------------------
    # Rule 2 — Long-Term Prospects
    # Checks whether the business has a durable, growing track record.
    # No hard pass/fail here — it's informational + optional AI deep-dive.
    # -----------------------------------------------------------------------
    rule2 = {
        "sector": sector,
        "industry": industry,
        "eps_history": eps_series,
        "revenue_history": revenue_series,
        "eps_cagr": _compute_cagr(eps_series),
        "revenue_cagr": _compute_cagr(revenue_series),
        "consecutive_positive_eps_years": _count_consecutive_positive(eps_series),
        "years_of_data": len(eps_series),
    }

    # -----------------------------------------------------------------------
    # Rule 3 — Stable & Understandable
    # Checks whether key fundamentals trend in a consistent direction over time.
    # -----------------------------------------------------------------------
    rule3 = {
        "bv_history": bv_history,
        "de_history": de_history,   # ratio form; consistent with BV scale
        "eps_history": eps_series,  # reuse from Rule 2 (same data)
        "roe_history": roe_history, # decimal form
        "years_of_data": len(bv_history),
    }

    # -----------------------------------------------------------------------
    # Rule 4 — Intrinsic Value (BuffettsBooks.com DCF methodology)
    #
    # IV = PV of book value projected 10 years forward
    #    + PV of dividend annuity over those 10 years
    #
    # Step 1: BV growth rate = (current_bv / oldest_bv)^(1 / years) − 1
    # Step 2: BV_future = current_bv × (1 + growth_rate)^10
    #         PV_of_BV = BV_future / (1 + treasury_rate)^10
    #         PV_of_divs = annual_div × [1 − (1 + r)^−10] / r
    #         IV = PV_of_BV + PV_of_divs
    # -----------------------------------------------------------------------

    # Determine annual dividend amount:
    # Prefer dividendRate ($ per share per year) from yfinance — exact dollar amount.
    # Fall back to price × dividendYield if dividendRate isn't available.
    # Zero dividend is valid — PV_of_divs will simply be 0.
    dividend_rate = metrics.get("dividend_rate")
    dividend_yield = metrics.get("dividend_yield")

    if dividend_rate is not None and dividend_rate > 0:
        annual_dividend = float(dividend_rate)
        dividend_source = "dividendRate"
    elif price and dividend_yield:
        annual_dividend = float(price) * float(dividend_yield)
        dividend_source = "price × yield"
    else:
        annual_dividend = 0.0
        dividend_source = "none"

    rule4: dict = {
        "treasury_rate": treasury_rate,
        "annual_dividend": annual_dividend,
        "dividend_source": dividend_source,
        "dividend_yield": dividend_yield,
        "current_bv": book_value,
        "oldest_bv": None,
        "years_between": None,
        "bv_growth_rate": None,
        "bv_future": None,
        "pv_of_bv": None,
        "pv_of_divs": None,
        "intrinsic_value": None,
        "margin_of_safety_pct": None,
        "current_price": price,
        "inapplicable": False,
        "inapplicable_reason": None,
        "high_growth_warning": False,
        "insufficient_history": False,
    }

    if negative_equity:
        rule4["inapplicable"] = True
        rule4["inapplicable_reason"] = (
            "Negative shareholders' equity — book value DCF is not applicable. "
            "Common in companies with aggressive buyback programs (e.g. MCD, SBUX) "
            "where cumulative repurchases exceed retained earnings."
        )
    elif not book_value or book_value <= 0:
        rule4["inapplicable"] = True
        rule4["inapplicable_reason"] = "Book value per share not available from data source"
    elif len(bv_history) < 3:
        rule4["inapplicable"] = True
        rule4["insufficient_history"] = True
        rule4["inapplicable_reason"] = (
            f"Insufficient BV history: {len(bv_history)} year(s) available from EDGAR, "
            f"need at least 3 to compute a reliable growth rate"
        )
    else:
        oldest_bv = bv_history[0]["value"]
        years_between = len(bv_history) - 1

        rule4["oldest_bv"] = oldest_bv
        rule4["years_between"] = years_between

        try:
            bv_growth_rate = (book_value / oldest_bv) ** (1 / years_between) - 1
            rule4["bv_growth_rate"] = round(bv_growth_rate, 6)
        except (ValueError, ZeroDivisionError) as e:
            logger.warning("BV growth rate calc failed for %s: %s", ticker, e)
            rule4["inapplicable"] = True
            rule4["inapplicable_reason"] = "Could not compute BV growth rate (check for negative book values in history)"
            bv_growth_rate = None

        if bv_growth_rate is not None:
            if bv_growth_rate > 0.20:
                # Growth companies with >20% BV CAGR violate the stability assumption
                # underlying the DCF — the model will likely over-estimate IV significantly.
                rule4["high_growth_warning"] = True

            r = treasury_rate
            try:
                bv_future = book_value * (1 + bv_growth_rate) ** 10
                pv_of_bv = bv_future / (1 + r) ** 10

                # Present value of annuity: PV = C × [1 − (1 + r)^−n] / r
                # When r ≈ 0 (clamped to 0.001), the formula still works.
                pv_of_divs = annual_dividend * (1 - (1 + r) ** -10) / r

                iv = pv_of_bv + pv_of_divs
                rule4["bv_future"] = round(bv_future, 2)
                rule4["pv_of_bv"] = round(pv_of_bv, 2)
                rule4["pv_of_divs"] = round(pv_of_divs, 2)
                rule4["intrinsic_value"] = round(iv, 2)

                if price and price > 0:
                    rule4["margin_of_safety_pct"] = round((iv - price) / price * 100, 2)

            except Exception as e:
                logger.warning("IV calculation failed for %s: %s", ticker, e)

    # -----------------------------------------------------------------------
    # Assemble final result and cache it
    # -----------------------------------------------------------------------
    result = {
        "ticker": ticker.upper(),
        "company_name": company_name,
        "price": price,
        "rule1": rule1,
        "rule2": rule2,
        "rule3": rule3,
        "rule4": rule4,
    }

    await set_cached_data(
        db, company["id"], "buffett", "analysis", "current",
        result, settings.cache_ttl_prices,  # 15-minute TTL
    )

    return result