"""Valuation calculations: Graham Score, DCF, Scenario Modeling."""

from app.models.schemas import (
    GrahamCriterion,
    GrahamScoreResponse,
    DCFInput,
    DCFResult,
    ScenarioModelInput,
    ScenarioResult,
)
import math


def calculate_graham_score(metrics: dict, financials: dict) -> GrahamScoreResponse:
    """Evaluate a stock against Benjamin Graham's 7 criteria from The Intelligent Investor.

    Graham's criteria for defensive investors:
    1. Adequate size (revenue > $2B adjusted for inflation)
    2. Strong financial condition (current ratio > 2)
    3. Earnings stability (positive earnings each of past 10 years)
    4. Dividend record (uninterrupted dividends for 20+ years) — relaxed to any dividend
    5. Earnings growth (at least 33% growth in EPS over 10 years)
    6. Moderate P/E ratio (P/E < 15)
    7. Moderate price-to-book (P/B < 1.5, or P/E × P/B < 22.5)
    """
    criteria = []
    score = 0
    ticker = metrics.get("ticker", "")

    # 1. Adequate size
    revenue = metrics.get("total_revenue") or 0
    threshold_revenue = 2_000_000_000  # $2B
    passed = revenue >= threshold_revenue
    if passed:
        score += 1
    criteria.append(GrahamCriterion(
        name="Adequate Size",
        description="Annual revenue > $2B",
        passed=passed,
        value=f"${revenue / 1e9:.1f}B" if revenue else "N/A",
        threshold="$2.0B",
    ))

    # 2. Strong financial condition
    current_ratio = metrics.get("current_ratio")
    passed = current_ratio is not None and current_ratio >= 2.0
    if passed:
        score += 1
    criteria.append(GrahamCriterion(
        name="Strong Financial Condition",
        description="Current ratio >= 2.0",
        passed=passed,
        value=f"{current_ratio:.2f}" if current_ratio else "N/A",
        threshold="2.0",
    ))

    # 3. Earnings stability (positive net income for recent years)
    net_income_series = financials.get("net_income", [])
    years_positive = sum(1 for entry in net_income_series if (entry.get("value") or 0) > 0)
    total_years = len(net_income_series)
    passed = total_years >= 5 and years_positive == total_years
    if passed:
        score += 1
    criteria.append(GrahamCriterion(
        name="Earnings Stability",
        description="Positive earnings in each of the past 5+ years",
        passed=passed,
        value=f"{years_positive}/{total_years} years positive",
        threshold="All years positive",
    ))

    # 4. Dividend record
    dividend_yield = metrics.get("dividend_yield")
    passed = dividend_yield is not None and dividend_yield > 0
    if passed:
        score += 1
    criteria.append(GrahamCriterion(
        name="Dividend Record",
        description="Currently pays dividends",
        passed=passed,
        value=f"{dividend_yield * 100:.2f}%" if dividend_yield else "None",
        threshold="Any dividend",
    ))

    # 5. Earnings growth
    eps_series = financials.get("eps_diluted", []) or financials.get("eps_basic", [])
    eps_growth = None
    if len(eps_series) >= 2:
        earliest = eps_series[0].get("value")
        latest = eps_series[-1].get("value")
        if earliest and latest and earliest > 0:
            eps_growth = (latest - earliest) / abs(earliest)
    passed = eps_growth is not None and eps_growth >= 0.33
    if passed:
        score += 1
    criteria.append(GrahamCriterion(
        name="Earnings Growth",
        description="EPS growth >= 33% over available history",
        passed=passed,
        value=f"{eps_growth * 100:.1f}%" if eps_growth is not None else "N/A",
        threshold="33%",
    ))

    # 6. Moderate P/E ratio
    pe = metrics.get("pe_ratio")
    passed = pe is not None and 0 < pe <= 15
    if passed:
        score += 1
    criteria.append(GrahamCriterion(
        name="Moderate P/E Ratio",
        description="P/E ratio <= 15",
        passed=passed,
        value=f"{pe:.1f}" if pe else "N/A",
        threshold="15.0",
    ))

    # 7. Moderate P/E × P/B (Graham Number check)
    pb = metrics.get("pb_ratio")
    pe_pb_product = None
    if pe and pb and pe > 0 and pb > 0:
        pe_pb_product = pe * pb
    passed_pb = pb is not None and 0 < pb <= 1.5
    passed_product = pe_pb_product is not None and pe_pb_product <= 22.5
    passed = passed_pb or passed_product
    if passed:
        score += 1
    criteria.append(GrahamCriterion(
        name="Moderate Price-to-Assets",
        description="P/B <= 1.5 or P/E × P/B <= 22.5",
        passed=passed,
        value=f"P/B={pb:.1f}, P/E×P/B={pe_pb_product:.1f}" if pb and pe_pb_product else "N/A",
        threshold="P/B≤1.5 or product≤22.5",
    ))

    # Graham Number = sqrt(22.5 × EPS × Book Value)
    eps_val = metrics.get("eps")
    book_val = metrics.get("book_value")
    graham_number = None
    if eps_val and book_val and eps_val > 0 and book_val > 0:
        graham_number = math.sqrt(22.5 * eps_val * book_val)

    # Margin of safety
    price = metrics.get("price")
    margin_of_safety = None
    if graham_number and price and price > 0:
        margin_of_safety = (graham_number - price) / price * 100  # Positive = undervalued

    return GrahamScoreResponse(
        ticker=ticker,
        score=score,
        max_score=7,
        criteria=criteria,
        graham_number=round(graham_number, 2) if graham_number else None,
        margin_of_safety=round(margin_of_safety, 1) if margin_of_safety else None,
    )


def calculate_dcf(
    ticker: str,
    current_fcf: float,
    shares_outstanding: float,
    current_price: float | None,
    inputs: DCFInput,
) -> DCFResult:
    """Calculate Discounted Cash Flow valuation."""
    fcf = inputs.fcf_override or current_fcf
    projected_fcf = []
    total_pv = 0.0

    for year in range(1, inputs.projection_years + 1):
        future_fcf = fcf * (1 + inputs.growth_rate) ** year
        pv = future_fcf / (1 + inputs.discount_rate) ** year
        total_pv += pv
        projected_fcf.append({
            "year": year,
            "fcf": round(future_fcf, 0),
            "present_value": round(pv, 0),
        })

    # Terminal value (perpetuity growth model)
    terminal_fcf = fcf * (1 + inputs.growth_rate) ** inputs.projection_years
    terminal_value = terminal_fcf * (1 + inputs.terminal_growth_rate) / (
        inputs.discount_rate - inputs.terminal_growth_rate
    )
    terminal_pv = terminal_value / (1 + inputs.discount_rate) ** inputs.projection_years
    total_pv += terminal_pv

    intrinsic_per_share = total_pv / shares_outstanding if shares_outstanding > 0 else 0

    margin = None
    if current_price and current_price > 0:
        margin = (intrinsic_per_share - current_price) / current_price * 100

    return DCFResult(
        ticker=ticker,
        intrinsic_value_per_share=round(intrinsic_per_share, 2),
        current_price=current_price,
        margin_of_safety=round(margin, 1) if margin is not None else None,
        projected_fcf=projected_fcf,
        terminal_value=round(terminal_value, 0),
        assumptions=inputs,
    )


def calculate_scenario_model(
    ticker: str,
    current_revenue: float,
    shares_outstanding: float,
    current_price: float | None,
    inputs: ScenarioModelInput,
) -> ScenarioResult:
    """Run bull/base/bear scenario analysis for growth/emerging companies."""
    scenario_results = []
    weighted_value = 0.0

    for scenario in inputs.scenarios:
        # Project revenue forward 5 years
        projected_revenue = current_revenue
        for _ in range(5):
            projected_revenue *= (1 + scenario.revenue_growth_rate)

        # Apply terminal margin to get earnings
        projected_earnings = projected_revenue * scenario.terminal_margin

        # Account for dilution
        future_shares = shares_outstanding
        for _ in range(5):
            future_shares *= (1 + scenario.annual_dilution)

        # Simple earnings-based valuation (15x multiple for mature company)
        valuation_multiple = 15
        implied_total_value = projected_earnings * valuation_multiple

        # Discount back to present
        implied_pv = implied_total_value / (1 + scenario.discount_rate) ** 5
        implied_per_share = implied_pv / future_shares if future_shares > 0 else 0

        scenario_results.append({
            "name": scenario.name,
            "implied_value": round(implied_per_share, 2),
            "probability": scenario.probability,
            "projected_revenue_5y": round(projected_revenue, 0),
            "projected_earnings_5y": round(projected_earnings, 0),
        })
        weighted_value += implied_per_share * scenario.probability

    upside = None
    if current_price and current_price > 0:
        upside = (weighted_value - current_price) / current_price * 100

    return ScenarioResult(
        ticker=ticker,
        current_price=current_price,
        scenarios=scenario_results,
        probability_weighted_value=round(weighted_value, 2),
        upside_downside=round(upside, 1) if upside is not None else None,
    )
