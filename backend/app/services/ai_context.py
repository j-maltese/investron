"""Assemble all available structured data for a ticker into LLM-readable context."""

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.financials import get_key_metrics, get_growth_metrics, get_financial_statements
from app.services.valuation import calculate_graham_score
from app.services import edgar
from app.services.company import get_or_create_company

logger = logging.getLogger(__name__)


def _fmt_number(value, prefix="$", suffix="", decimals=2) -> str:
    """Format a number for display, handling None and large values."""
    if value is None:
        return "N/A"
    if prefix == "$":
        abs_val = abs(value)
        if abs_val >= 1e12:
            return f"${value / 1e12:.{decimals}f}T"
        if abs_val >= 1e9:
            return f"${value / 1e9:.{decimals}f}B"
        if abs_val >= 1e6:
            return f"${value / 1e6:.1f}M"
        return f"${value:,.{decimals}f}"
    return f"{prefix}{value:.{decimals}f}{suffix}"


def _fmt_pct(value) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.2f}%"


def _fmt_ratio(value) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}"


def _format_metrics(metrics: dict) -> str:
    """Format key metrics into readable text."""
    ticker = metrics.get("ticker", "?")
    lines = [f"== KEY METRICS ({ticker}) =="]

    price = metrics.get("price")
    mcap = metrics.get("market_cap")
    lines.append(f"Price: {_fmt_number(price)} | Market Cap: {_fmt_number(mcap)}")

    pe = metrics.get("pe_ratio")
    fpe = metrics.get("forward_pe")
    pe_str = _fmt_ratio(pe) if pe and pe > 0 else "N/A (negative earnings)" if pe and pe < 0 else "N/A"
    fpe_str = _fmt_ratio(fpe) if fpe and fpe > 0 else "N/A"
    lines.append(f"P/E (trailing): {pe_str} | Forward P/E: {fpe_str}")

    lines.append(
        f"P/B: {_fmt_ratio(metrics.get('pb_ratio'))} | "
        f"P/S: {_fmt_ratio(metrics.get('ps_ratio'))}"
    )
    lines.append(
        f"Debt/Equity: {_fmt_ratio(metrics.get('debt_to_equity'))} | "
        f"Current Ratio: {_fmt_ratio(metrics.get('current_ratio'))}"
    )
    lines.append(
        f"ROE: {_fmt_pct(metrics.get('roe'))} | "
        f"ROA: {_fmt_pct(metrics.get('roa'))}"
    )
    lines.append(
        f"Net Margin: {_fmt_pct(metrics.get('net_margin'))} | "
        f"Gross Margin: {_fmt_pct(metrics.get('gross_margin'))} | "
        f"Operating Margin: {_fmt_pct(metrics.get('operating_margin'))}"
    )

    eps = metrics.get("eps")
    lines.append(f"EPS: {_fmt_number(eps) if eps else 'N/A'} | Book Value: {_fmt_number(metrics.get('book_value'))}")

    lines.append(
        f"Free Cash Flow: {_fmt_number(metrics.get('free_cash_flow'))} | "
        f"Revenue: {_fmt_number(metrics.get('total_revenue'))}"
    )
    lines.append(
        f"Revenue Growth: {_fmt_pct(metrics.get('revenue_growth'))} | "
        f"Earnings Growth: {_fmt_pct(metrics.get('earnings_growth'))}"
    )
    lines.append(
        f"Dividend Yield: {_fmt_pct(metrics.get('dividend_yield')) if metrics.get('dividend_yield') else 'None'}"
    )
    lines.append(f"Beta: {_fmt_ratio(metrics.get('beta'))}")

    high = metrics.get("fifty_two_week_high")
    low = metrics.get("fifty_two_week_low")
    lines.append(f"52-Week Range: {_fmt_number(low)} – {_fmt_number(high)}")

    return "\n".join(lines)


def _format_graham(graham_resp) -> str:
    """Format Graham score response into readable text."""
    lines = [f"== GRAHAM DEFENSIVE SCORE: {graham_resp.score}/{graham_resp.max_score} =="]
    for c in graham_resp.criteria:
        status = "PASS" if c.passed else "FAIL"
        lines.append(f"[{status}] {c.name}: {c.value} (threshold: {c.threshold})")

    if graham_resp.graham_number:
        lines.append(f"Graham Number: ${graham_resp.graham_number:.2f}")
    if graham_resp.margin_of_safety is not None:
        lines.append(f"Margin of Safety: {graham_resp.margin_of_safety:+.1f}% (positive = undervalued)")

    return "\n".join(lines)


def _format_growth(growth: dict) -> str:
    """Format growth/emerging company metrics."""
    lines = ["== GROWTH / EMERGING COMPANY METRICS =="]

    cash = growth.get("cash_on_hand")
    burn = growth.get("burn_rate")
    runway = growth.get("cash_runway_quarters")
    lines.append(
        f"Cash on Hand: {_fmt_number(cash)} | "
        f"Quarterly Burn Rate: {_fmt_number(burn)} | "
        f"Cash Runway: {f'{runway:.1f} quarters' if runway else 'N/A'}"
    )

    dilution = growth.get("dilution_rate")
    lines.append(f"Annual Dilution Rate: {_fmt_pct(dilution) if dilution else 'N/A'}")

    rd = growth.get("rd_expense")
    rd_pct = growth.get("rd_as_pct_revenue")
    lines.append(
        f"R&D Expense: {_fmt_number(rd)} "
        f"({_fmt_pct(rd_pct) + ' of revenue' if rd_pct else 'N/A % of revenue'})"
    )

    buys = growth.get("insider_buys_6m", 0)
    sells = growth.get("insider_sells_6m", 0)
    lines.append(f"Insider Activity (6mo): {buys} buys, {sells} sells")

    rates = growth.get("revenue_growth_rates", [])
    if rates:
        lines.append("Revenue Growth History:")
        for r in rates[-5:]:  # Last 5 years
            lines.append(f"  {r['period']}: {r['growth_rate']:+.1%}")

    return "\n".join(lines)


def _format_statements(data: dict) -> str:
    """Format financial statements into readable text. Keep concise — last 3 periods."""
    stmt_type = data.get("statement_type", "unknown")
    label = stmt_type.replace("_", " ").title()
    statements = data.get("statements", [])
    if not statements:
        return f"== {label.upper()} ==\nNo data available."

    # Last 3 periods to keep token count manageable
    recent = statements[-3:]
    lines = [f"== {label.upper()} (last {len(recent)} periods) =="]

    for stmt in recent:
        period = stmt.get("period", "?")
        items = [f"  {k}: {_fmt_number(v)}" for k, v in stmt.items() if k != "period" and v is not None]
        lines.append(f"\n{period}:")
        lines.extend(items[:15])  # Cap at 15 line items per period

    return "\n".join(lines)


def _format_screener(row: dict) -> str:
    """Format screener score data."""
    lines = ["== SCREENER DATA =="]
    score = row.get("composite_score")
    rank = row.get("rank")
    lines.append(f"Composite Value Score: {score:.1f}/100 | Rank: #{rank}" if score else "Not yet scored")

    mos = row.get("margin_of_safety")
    if mos is not None:
        lines.append(f"Margin of Safety: {mos:+.1f}%")

    fcf_y = row.get("fcf_yield")
    ey = row.get("earnings_yield")
    lines.append(f"FCF Yield: {_fmt_pct(fcf_y)} | Earnings Yield: {_fmt_pct(ey)}")

    warnings = row.get("warnings", [])
    if warnings:
        warn_strs = [f"{w.get('code', '?')} ({w.get('severity', '?')})" for w in warnings]
        lines.append(f"Warnings: {', '.join(warn_strs)}")

    indices = row.get("indices", [])
    if indices:
        lines.append(f"Index Memberships: {', '.join(indices)}")

    return "\n".join(lines)


async def get_filing_index_info(db: AsyncSession, ticker: str) -> dict | None:
    """Check if a ticker has indexed filings for RAG search.

    Returns dict with status info if indexed, None otherwise.
    """
    result = await db.execute(
        text("""
            SELECT status, filings_indexed, chunks_total,
                   last_indexed_at, last_filing_date
            FROM filing_index_status
            WHERE ticker = :ticker AND status = 'ready'
        """),
        {"ticker": ticker.upper()},
    )
    row = result.mappings().first()
    if not row:
        return None
    return {
        "status": row["status"],
        "filings_indexed": row["filings_indexed"],
        "chunks_total": row["chunks_total"],
        "last_filing_date": (
            row["last_filing_date"].isoformat() if row["last_filing_date"] else None
        ),
    }


async def build_ticker_context(
    db: AsyncSession,
    ticker: str,
    include_financials: bool = True,
    include_growth: bool = True,
) -> str:
    """Gather all available data for a ticker and format as LLM-readable context.

    Fetches in parallel from existing services. Each section is independently
    fault-tolerant — if one data source fails, the others still appear.
    """
    sections: list[str] = []
    ticker_upper = ticker.upper()

    # --- Parallel fetch: metrics, growth, screener, and optionally financials ---
    tasks = {
        "metrics": get_key_metrics(db, ticker),
    }
    if include_growth:
        tasks["growth"] = get_growth_metrics(db, ticker)

    if include_financials:
        tasks["income"] = get_financial_statements(db, ticker, "income_statement", "annual")
        tasks["balance"] = get_financial_statements(db, ticker, "balance_sheet", "annual")
        tasks["cashflow"] = get_financial_statements(db, ticker, "cash_flow", "annual")

    # Screener score via direct SQL (lightweight, no service call needed)
    async def _get_screener_row():
        result = await db.execute(
            text("""
                SELECT ticker, company_name, sector, industry,
                       composite_score, rank, margin_of_safety,
                       fcf_yield, earnings_yield, warnings, indices
                FROM screener_scores WHERE ticker = :ticker
            """),
            {"ticker": ticker_upper},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    tasks["screener"] = _get_screener_row()

    # Run all in parallel
    keys = list(tasks.keys())
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    data = {}
    for key, result in zip(keys, results):
        if isinstance(result, Exception):
            logger.warning(f"AI context: failed to fetch {key} for {ticker}: {result}")
            data[key] = None
        else:
            data[key] = result

    # --- Company header ---
    metrics = data.get("metrics") or {}
    screener = data.get("screener") or {}
    company_name = screener.get("company_name") or metrics.get("name") or ticker_upper
    sector = screener.get("sector") or metrics.get("sector") or "Unknown"
    industry = screener.get("industry") or metrics.get("industry") or "Unknown"
    sections.append(f"== COMPANY: {company_name} ({ticker_upper}) ==")
    sections.append(f"Sector: {sector} | Industry: {industry}")

    # --- Key metrics ---
    if metrics and len(metrics) > 1:  # More than just {"ticker": "..."}
        sections.append("")
        sections.append(_format_metrics(metrics))

    # --- Graham score (computed from metrics + income data) ---
    try:
        if metrics and len(metrics) > 1:
            # Get income data for Graham score calculation
            company = await get_or_create_company(db, ticker)
            income_data = {}
            if company:
                cik = company.get("cik", "").zfill(10)
                facts = await edgar.get_xbrl_company_facts(cik)
                if facts:
                    income_data = edgar.extract_financial_time_series(
                        facts, edgar.INCOME_STATEMENT_CONCEPTS, "annual"
                    )
            graham = calculate_graham_score(metrics, income_data)
            sections.append("")
            sections.append(_format_graham(graham))
    except Exception as e:
        logger.warning(f"AI context: Graham score failed for {ticker}: {e}")

    # --- Growth metrics ---
    growth = data.get("growth")
    if growth and len(growth) > 1:
        sections.append("")
        sections.append(_format_growth(growth))

    # --- Screener data ---
    if screener:
        sections.append("")
        sections.append(_format_screener(screener))

    # --- Financial statements ---
    if include_financials:
        for key, label in [("income", "Income Statement"), ("balance", "Balance Sheet"), ("cashflow", "Cash Flow")]:
            stmt = data.get(key)
            if stmt and stmt.get("statements"):
                sections.append("")
                sections.append(_format_statements(stmt))

    return "\n".join(sections)
