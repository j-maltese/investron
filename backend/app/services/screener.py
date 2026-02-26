"""Value screener scoring — lightweight Graham/Buffett composite from yfinance data only.

This module computes a composite "value score" for any stock using data from a single
yfinance .info call. It is intentionally simpler than the full 7-criteria Graham Score
in valuation.py (which also requires EDGAR XBRL data). The trade-off: less depth per
stock, but fast enough to score 500+ stocks in a background sweep.

Design decisions:
  - All scoring functions are PURE (no DB, no async, no side effects) for easy testing.
  - Each metric scorer returns 0.0-1.0, then the composite is a weighted sum scaled to 0-100.
  - Warnings flag concerns but NEVER filter stocks out — the user decides what to research.
  - The weights and thresholds are configurable constants at the top of the file.
"""

import math
from typing import Optional


# ============================================================================
# Scoring Weights — must sum to 1.0
# These control how much each metric contributes to the composite score.
# Margin of Safety gets the highest weight because it's the core Graham/Buffett
# principle: buy below intrinsic value. FCF and P/E are next as primary value signals.
# ============================================================================
WEIGHTS = {
    "margin_of_safety": 0.25,  # Graham Number vs. current price
    "pe": 0.15,                # Trailing P/E ratio
    "fcf_yield": 0.15,         # Free cash flow yield (FCF / Market Cap)
    "earnings_yield": 0.10,    # Inverse P/E as absolute yield
    "pb": 0.10,                # Price-to-Book ratio
    "roe": 0.10,               # Return on Equity (quality indicator)
    "debt_equity": 0.10,       # Debt/Equity (financial health)
    "dividend": 0.05,          # Small bonus for dividend payers
}


# ============================================================================
# Individual Metric Scorers
# Each returns 0.0 (worst) to 1.0 (best) using linear interpolation between
# configurable threshold bounds. None/invalid inputs return 0.0 (conservative).
# ============================================================================

def score_pe(pe: Optional[float]) -> float:
    """Score P/E ratio — lower is better for value investors.

    Thresholds: perfect (1.0) at P/E <= 8, zero at P/E >= 30.
    Negative P/E means losses, which scores 0. Linear interpolation between bounds.
    """
    if pe is None or pe <= 0:
        return 0.0
    if pe <= 8:
        return 1.0
    if pe >= 30:
        return 0.0
    return (30 - pe) / (30 - 8)


def score_pb(pb: Optional[float]) -> float:
    """Score P/B ratio — lower is better (buying assets cheaply).

    Thresholds: perfect at P/B <= 1.0 (below book value), zero at P/B >= 5.
    Negative book value (pb <= 0) scores 0 — liabilities exceed assets.
    """
    if pb is None or pb <= 0:
        return 0.0
    if pb <= 1.0:
        return 1.0
    if pb >= 5.0:
        return 0.0
    return (5.0 - pb) / (5.0 - 1.0)


def score_roe(roe: Optional[float]) -> float:
    """Score Return on Equity — higher is better (quality indicator).

    ROE from yfinance is a decimal (0.15 = 15%).
    Perfect at >= 20% (Buffett's threshold). Zero at <= 0%.
    """
    if roe is None or roe <= 0:
        return 0.0
    if roe >= 0.20:
        return 1.0
    return roe / 0.20


def score_debt_equity(de: Optional[float]) -> float:
    """Score Debt/Equity ratio — lower is better (financial safety).

    GOTCHA: yfinance returns D/E as a percentage-like number (e.g., 150 means 150%),
    NOT as a decimal. So D/E of 1.5x shows up as 150.

    Thresholds: perfect at D/E <= 30 (very low debt), zero at D/E >= 200.
    None = unknown = neutral 0.5 (benefit of the doubt for companies without debt data).
    Negative = negative equity = 0.0.
    """
    if de is None:
        return 0.5  # Unknown debt level — give neutral score
    if de < 0:
        return 0.0  # Negative equity is a red flag
    if de <= 30:
        return 1.0
    if de >= 200:
        return 0.0
    return (200 - de) / (200 - 30)


def score_fcf_yield(fcf: Optional[float], market_cap: Optional[float]) -> tuple[Optional[float], float]:
    """Score Free Cash Flow yield — higher is better (cash generation).

    FCF Yield = Free Cash Flow / Market Cap. A 10%+ yield is excellent.
    Returns (raw_yield, score) tuple so we can store both in the DB.
    """
    if not fcf or not market_cap or market_cap <= 0:
        return (None, 0.0)
    yield_val = fcf / market_cap
    if yield_val <= 0:
        return (yield_val, 0.0)
    if yield_val >= 0.10:
        return (yield_val, 1.0)
    return (yield_val, yield_val / 0.10)


def score_earnings_yield(pe: Optional[float]) -> tuple[Optional[float], float]:
    """Score Earnings Yield (1/P/E) — higher is better.

    This is the Greenblatt Magic Formula's preferred value metric.
    Perfect at >= 10% yield (i.e., P/E = 10). Zero for negative earnings.
    Returns (raw_yield, score) tuple.
    """
    if pe is None or pe <= 0:
        return (None, 0.0)
    ey = 1.0 / pe
    if ey >= 0.10:
        return (ey, 1.0)
    return (ey, ey / 0.10)


def score_dividend(dividend_yield: Optional[float]) -> float:
    """Score dividend presence and yield — a small bonus in the composite.

    dividend_yield from yfinance is a decimal (0.02 = 2%).
    Any dividend > 0 gets a 0.5 base score. Full 1.0 at 4%+ yield.
    No dividend = 0.0 (not a penalty, just no bonus).
    """
    if dividend_yield is None or dividend_yield <= 0:
        return 0.0
    if dividend_yield >= 0.04:
        return 1.0
    # Linear from 0.5 at yield=0 to 1.0 at yield=4%
    return 0.5 + (dividend_yield / 0.04) * 0.5


def compute_graham_number(eps: Optional[float], book_value: Optional[float]) -> Optional[float]:
    """Graham Number = sqrt(22.5 * EPS * Book Value).

    Same formula used in valuation.py for the full Graham Score.
    22.5 comes from Graham's maximum acceptable P/E (15) * P/B (1.5).
    Only valid when both EPS and Book Value are positive.
    """
    if not eps or not book_value or eps <= 0 or book_value <= 0:
        return None
    return math.sqrt(22.5 * eps * book_value)


def score_margin_of_safety(
    price: Optional[float], graham_number: Optional[float]
) -> tuple[Optional[float], float]:
    """Score Margin of Safety — the cornerstone of value investing.

    MoS = (Graham Number - Price) / Price * 100
    Positive MoS = stock is undervalued (trading below intrinsic value).
    Negative MoS = stock is overvalued.

    Score: 1.0 at MoS >= +50% (deeply undervalued), 0.0 at MoS <= -50%.
    Linear interpolation across the 100-point range.
    """
    if not price or not graham_number or price <= 0:
        return (None, 0.0)
    mos = (graham_number - price) / price * 100
    if mos >= 50:
        return (mos, 1.0)
    if mos <= -50:
        return (mos, 0.0)
    # Linear: -50% -> 0.0, +50% -> 1.0
    return (mos, (mos + 50) / 100)


# ============================================================================
# Warning Detection
# Warnings inform but never filter. A stock with negative earnings still gets
# scored and ranked — the warning just gives context for why it might be cheap.
# ============================================================================

def detect_warnings(metrics: dict) -> list[dict]:
    """Detect health/quality warning flags from yfinance metrics.

    Returns list of warning dicts: [{"code": str, "severity": "high"|"medium"|"low", "message": str}]
    Severity levels:
      - high: fundamental problems (losing money, crushing debt, negative book value)
      - medium: concerning trends (declining revenue, cash burn, poor profitability)
      - low: informational flags (very high P/E, near 52-week low)
    """
    warnings = []

    # --- High severity ---
    eps = metrics.get("eps")
    if eps is not None and eps < 0:
        warnings.append({
            "code": "negative_earnings",
            "severity": "high",
            "message": f"Negative EPS ({eps:.2f}) — company is losing money",
        })

    de = metrics.get("debt_to_equity")
    if de is not None and de > 200:
        warnings.append({
            "code": "high_debt",
            "severity": "high",
            "message": f"Debt/Equity of {de:.0f}% is very high",
        })

    bv = metrics.get("book_value")
    if bv is not None and bv < 0:
        warnings.append({
            "code": "negative_book_value",
            "severity": "high",
            "message": "Negative book value — liabilities exceed assets",
        })

    # --- Medium severity ---
    rg = metrics.get("revenue_growth")
    if rg is not None and rg < -0.05:
        warnings.append({
            "code": "declining_revenue",
            "severity": "medium",
            "message": f"Revenue declining {abs(rg) * 100:.1f}% year-over-year",
        })

    fcf = metrics.get("free_cash_flow")
    if fcf is not None and fcf < 0:
        warnings.append({
            "code": "negative_fcf",
            "severity": "medium",
            "message": "Negative free cash flow — burning cash",
        })

    roe = metrics.get("roe")
    if roe is not None and roe < 0:
        warnings.append({
            "code": "negative_roe",
            "severity": "medium",
            "message": f"Negative ROE ({roe * 100:.1f}%) — poor profitability",
        })

    # --- Low severity (informational) ---
    pe = metrics.get("pe_ratio")
    if pe is not None and pe > 50:
        warnings.append({
            "code": "very_high_pe",
            "severity": "low",
            "message": f"P/E of {pe:.1f} is very high for a value stock",
        })

    price = metrics.get("price")
    low_52w = metrics.get("fifty_two_week_low")
    if price and low_52w and low_52w > 0:
        pct_above_low = (price - low_52w) / low_52w * 100
        if pct_above_low < 5:
            warnings.append({
                "code": "near_52w_low",
                "severity": "low",
                "message": f"Trading within 5% of 52-week low (${low_52w:.2f})",
            })

    return warnings


# ============================================================================
# Composite Scoring — the main entry point
# ============================================================================

def compute_composite_score(metrics: dict) -> dict:
    """Compute the full composite value score from a yfinance metrics dict.

    This is the main entry point called by the scanner for each ticker.
    Takes the dict from yfinance_svc.get_stock_info() and returns a flat dict
    with all raw metrics, individual score components, the weighted composite,
    and any warning flags.

    The composite score (0-100) is a weighted sum of normalized component scores.
    Higher = more undervalued / better value. A score of 100 would mean every
    metric is at its ideal threshold (extremely rare in practice).
    """
    # Extract relevant metrics from yfinance data
    pe = metrics.get("pe_ratio")
    pb = metrics.get("pb_ratio")
    roe = metrics.get("roe")
    de = metrics.get("debt_to_equity")
    fcf = metrics.get("free_cash_flow")
    market_cap = metrics.get("market_cap")
    dividend_yield = metrics.get("dividend_yield")
    eps = metrics.get("eps")
    book_value = metrics.get("book_value")
    price = metrics.get("price")

    # Compute individual component scores (each 0.0-1.0)
    pe_sc = score_pe(pe)
    pb_sc = score_pb(pb)
    roe_sc = score_roe(roe)
    de_sc = score_debt_equity(de)
    fcf_yield_raw, fcf_yield_sc = score_fcf_yield(fcf, market_cap)
    ey_raw, ey_sc = score_earnings_yield(pe)
    div_sc = score_dividend(dividend_yield)

    # Graham Number and Margin of Safety
    graham_num = compute_graham_number(eps, book_value)
    mos_raw, mos_sc = score_margin_of_safety(price, graham_num)

    # Weighted composite: sum of (weight * score) for each component, scaled to 0-100
    composite = (
        WEIGHTS["margin_of_safety"] * mos_sc
        + WEIGHTS["pe"] * pe_sc
        + WEIGHTS["pb"] * pb_sc
        + WEIGHTS["earnings_yield"] * ey_sc
        + WEIGHTS["fcf_yield"] * fcf_yield_sc
        + WEIGHTS["roe"] * roe_sc
        + WEIGHTS["debt_equity"] * de_sc
        + WEIGHTS["dividend"] * div_sc
    ) * 100

    # Detect warning flags (informational, not filters)
    warnings = detect_warnings(metrics)

    # Return flat dict matching the screener_scores table columns
    return {
        "ticker": metrics.get("ticker", ""),
        "company_name": metrics.get("name", ""),
        "sector": metrics.get("sector"),
        "industry": metrics.get("industry"),
        # Raw metrics snapshot
        "price": price,
        "market_cap": market_cap,
        "pe_ratio": pe,
        "forward_pe": metrics.get("forward_pe"),
        "pb_ratio": pb,
        "ps_ratio": metrics.get("ps_ratio"),
        "debt_to_equity": de,
        "current_ratio": metrics.get("current_ratio"),
        "roe": roe,
        "eps": eps,
        "book_value": book_value,
        "free_cash_flow": fcf,
        "total_revenue": metrics.get("total_revenue"),
        "dividend_yield": dividend_yield,
        "revenue_growth": metrics.get("revenue_growth"),
        "earnings_growth": metrics.get("earnings_growth"),
        "net_margin": metrics.get("net_margin"),
        "beta": metrics.get("beta"),
        "fifty_two_week_high": metrics.get("fifty_two_week_high"),
        "fifty_two_week_low": metrics.get("fifty_two_week_low"),
        # Derived scores
        "graham_number": round(graham_num, 4) if graham_num else None,
        "margin_of_safety": round(mos_raw, 4) if mos_raw is not None else None,
        "pe_score": round(pe_sc, 4),
        "pb_score": round(pb_sc, 4),
        "roe_score": round(roe_sc, 4),
        "debt_equity_score": round(de_sc, 4),
        "fcf_yield": round(fcf_yield_raw, 6) if fcf_yield_raw is not None else None,
        "fcf_yield_score": round(fcf_yield_sc, 4),
        "earnings_yield": round(ey_raw, 6) if ey_raw is not None else None,
        "earnings_yield_score": round(ey_sc, 4),
        "dividend_score": round(div_sc, 4),
        "margin_of_safety_score": round(mos_sc, 4),
        # Composite
        "composite_score": round(composite, 2),
        "warnings": warnings,
    }
