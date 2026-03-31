"""Buffett Option B — AI Alternative Valuation Service.

Used when Rule 4 (Book Value DCF) is inapplicable (negative equity, insufficient
history, or book value unavailable). Assembles a rich prompt from multiple sources
and streams a reasoning-model response.

Context injected into the prompt:
  - All 4 Buffett rules data (already computed by buffett_service)
  - Growth metrics: cash, burn rate, runway (from financials.get_growth_metrics)
  - Analyst consensus: price targets, recommendation (from yfinance, now in key_metrics)
  - News headlines: top 5 from Serper API (skipped gracefully if key not configured)
  - Filing context: semantic search over indexed 10-K + 10-Q chunks (via pgvector RAG)

The filing context is always RAG-based — the caller (buffett.py endpoint) is
responsible for ensuring the ticker is indexed before calling build_valuation_prompt.
"""

import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.vector_search import search_filing_chunks, format_search_results_for_llm

logger = logging.getLogger(__name__)

# Serper search endpoint
_SERPER_URL = "https://google.serper.dev/search"
_SERPER_TIMEOUT = 10  # seconds

# Token budgets for filing context (per filing type, from rag_max_context_tokens config)
# We split the budget evenly between 10-K and 10-Q.
_FILING_QUERIES = {
    "10-K": [
        "business model revenue streams competitive advantage moat",
        "risk factors key risks challenges threats",
        "management discussion analysis revenue growth margins outlook",
    ],
    "10-Q": [
        "quarterly revenue results operating performance",
        "management discussion analysis recent developments outlook guidance",
    ],
}


# ---------------------------------------------------------------------------
# News search
# ---------------------------------------------------------------------------

async def search_news(ticker: str, company_name: str, serper_key: str) -> list[dict]:
    """Fetch top 5 recent news headlines for a ticker via Serper API.

    Returns a list of {title, snippet, source} dicts. Returns [] silently if:
      - serper_key is empty (feature not configured)
      - Any network or parsing error occurs

    Never raises — news is optional context; the valuation proceeds without it.
    """
    if not serper_key:
        return []

    query = f"{company_name} {ticker} stock analyst outlook investor"
    try:
        async with httpx.AsyncClient(timeout=_SERPER_TIMEOUT) as client:
            resp = await client.post(
                _SERPER_URL,
                headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                json={"q": query, "num": 5},
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("organic", [])[:5]:
            results.append({
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                # "source" is the domain/publisher name; fall back to link domain
                "source": item.get("source") or item.get("link", "")[:60],
            })
        return results

    except Exception as e:
        logger.warning("Serper news search failed for %s: %s", ticker, e)
        return []


# ---------------------------------------------------------------------------
# Filing context via RAG
# ---------------------------------------------------------------------------

async def get_filing_context(
    db: AsyncSession,
    ticker: str,
    filing_type: str,
) -> str:
    """Retrieve semantically relevant filing sections for a ticker via pgvector search.

    Runs multiple targeted queries (defined in _FILING_QUERIES) for the given
    filing type, deduplicates results, and formats them for LLM injection.

    The token budget is split evenly between 10-K and 10-Q by using half of
    settings.rag_max_context_tokens per filing type.

    Returns formatted text ready to inject into the prompt, or an empty string
    if no indexed chunks are found (caller notes this gap in the prompt).
    """
    settings = get_settings()
    queries = _FILING_QUERIES.get(filing_type, [])
    if not queries:
        return ""

    # Split the total RAG budget evenly across the two filing types
    per_filing_token_budget = settings.rag_max_context_tokens // 2
    per_query_top_k = 4  # fetch top 4 per query, deduplicate across queries

    seen_texts: set[str] = set()
    all_results = []

    for query in queries:
        try:
            results = await search_filing_chunks(
                db=db,
                ticker=ticker,
                query_text=query,
                top_k=per_query_top_k,
                max_tokens=per_filing_token_budget,
                filing_types=[filing_type],
            )
            for r in results:
                # Deduplicate by chunk text to avoid the same passage appearing
                # in multiple query results (common for short filings)
                if r.chunk_text not in seen_texts:
                    seen_texts.add(r.chunk_text)
                    all_results.append(r)
        except Exception as e:
            logger.warning("Filing context search failed for %s %s '%s': %s", ticker, filing_type, query, e)

    if not all_results:
        return ""

    # Sort by similarity (best first) and enforce the total token budget
    all_results.sort(key=lambda r: r.similarity, reverse=True)
    trimmed = []
    total_tokens = 0
    for r in all_results:
        if total_tokens + r.token_count > per_filing_token_budget and trimmed:
            break
        trimmed.append(r)
        total_tokens += r.token_count

    return format_search_results_for_llm(trimmed)


# ---------------------------------------------------------------------------
# Analyst fields extractor
# ---------------------------------------------------------------------------

def get_analyst_fields(metrics: dict) -> dict:
    """Extract analyst consensus fields from the key_metrics dict.

    These are sourced from yfinance and added to the result in yfinance_svc.py.
    Returns a dict with all fields; values may be None if yfinance didn't return them
    (e.g. small-cap stocks with no analyst coverage).
    """
    return {
        "target_mean_price": metrics.get("target_mean_price"),
        "target_high_price": metrics.get("target_high_price"),
        "target_low_price": metrics.get("target_low_price"),
        "recommendation_mean": metrics.get("recommendation_mean"),
        "recommendation_key": metrics.get("recommendation_key"),
        "number_of_analyst_opinions": metrics.get("number_of_analyst_opinions"),
    }


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a senior equity research analyst providing an alternative valuation for a company where the standard Buffett Book Value DCF is not applicable.

STEP 1 — CLASSIFY THE COMPANY before writing your analysis. Determine which category applies:

  Category A — MATURE / VALUE: Profitable, consistent positive EPS for 3+ years, stable or growing revenue, established market position. Traditional valuation methods are reliable.

  Category B — GROWTH / SCALING: Revenue growing rapidly (>20% YoY), reinvesting heavily, profitable or near-profitable, business model proven but not yet fully mature.

  Category C — PRE-PROFITABLE / EMERGING: Negative or highly inconsistent earnings, early-stage or burning cash, operating in an emerging technology or industry where eventual market size is uncertain. Traditional valuation is unreliable — use the investment thesis framework instead.

State the category you assigned and briefly explain why.

---

FOR CATEGORY A OR B — VALUATION ANALYSIS

**1. Business Overview & Quality**
What does this company do, how does it make money, and is the business model understandable and predictable? Draw on the 10-K/10-Q language but synthesize it — do not quote at length.

**2. Analyst Consensus & Market Sentiment**
Summarize the analyst price target range, consensus rating, and recent news tone. Flag meaningful divergences: a wide target spread signals analyst disagreement; bullish consensus against negative news may signal an inflection point. Note if analyst coverage is thin (<5 analysts).

**3. Valuation Methodology & Assumptions**
Select the most appropriate method and explain why:
  - Earnings DCF: for stable, positive EPS with a visible multi-year growth trajectory
  - Graham Formula: IV = √(22.5 × EPS × BVPS) for traditional value stocks
  - Revenue Multiple: for growth-stage companies with variable earnings (anchor to sector comps)
  - EV/EBITDA: for capital-intensive or margin-driven businesses

Show your assumptions explicitly — growth rate, discount rate, terminal multiple, years. A reader should be able to reproduce your estimate.

**4. Estimated Value Range — Bear / Base / Bull**
For each scenario: state the key driving assumption and the resulting estimated value per share. Compare to current price and analyst target midpoint.
End with: UNDERVALUED / FAIRLY VALUED / OVERVALUED and a confidence level (Low / Medium / High).

**5. Key Risks & What to Watch**
Top 3 risks drawn from the 10-K/10-Q and your analysis. For each: near-term or long-term, and what metric or event would confirm or dismiss it.

---

FOR CATEGORY C — INVESTMENT THESIS ANALYSIS

**1. What This Company Is Betting On**
In plain language: what is the core thesis? What market opportunity is management pursuing, and what is their claimed edge? Be specific — name the market, the product, the customer.

**2. What Needs to Go Right**
The 3–5 specific, falsifiable things that must happen for this to be a good investment:
  - Milestones: revenue targets, gross margin inflection, regulatory approvals, customer wins, technology proof points
  - The single most important variable — if you had to name one thing the whole thesis hinges on, what is it?

**3. Failure Modes — What Could Go Wrong**
The specific scenarios that cause this investment to fail permanently:
  - Competitive displacement: who could make this company irrelevant, and how?
  - Technology or execution risk: what must be built or proven that isn't yet?
  - Market timing risk: can this business only succeed in a narrow window?
  - Management risk: are there signs in the filings of execution problems (guidance misses, leadership turnover, auditor concerns, going-concern language)?

**4. Capital Runway Analysis**
Using the cash on hand and burn rate provided:
  - State the runway in quarters clearly
  - < 4 quarters: STATE DIRECTLY — "Acute survival risk: this company may need capital within [N] quarters. The investment thesis depends on either a near-term financing event or a rapid improvement in unit economics."
  - < 8 quarters: FLAG PROMINENTLY — "Material capital risk: runway is limited. The company will likely need to raise capital before proving its model."
  - > 12 quarters: Note it as adequate and move on.
  - Distinguish: burning cash to grow (revenue growing faster than burn — acceptable) vs. burning cash with no clear path to breakeven (danger signal).

**5. Analyst Consensus & Market Sentiment**
Summarize analyst targets and recent news. For early-stage companies, note if coverage is thin. High analyst disagreement on a growth company is normal — describe the range and what drives it.

**6. Rough Valuation Context (with appropriate humility)**
Do not force a precise DCF you cannot support. Instead:
  - If the company reaches its stated targets, what does a reasonable exit multiple imply about fair value?
  - What is the market currently pricing in — is the stock cheap or expensive relative to its own growth expectations?
  - Is this a large binary bet or a more predictable path?

**7. Eyes-Open Summary**
3–5 sentences in plain language. What you are betting on. The most likely way it works. The most likely way it fails. Whether the current price offers adequate compensation for the risk. End with a risk profile label: SPECULATIVE / MODERATE RISK / LOWER RISK.

---

STANDARDS FOR ALL CATEGORIES

Be direct. Show your reasoning. Surface the hard questions, not just the upside.
If data is thin, say so — a well-reasoned low-confidence estimate is more useful than false precision.
Do not recommend buying or selling. Estimate value and surface risk — let the investor decide with their eyes open."""


def build_valuation_prompt(
    analysis: dict,
    growth_metrics: dict,
    metrics: dict,
    news: list[dict],
    filing_10k: str,
    filing_10q: str,
) -> tuple[str, str]:
    """Assemble the (system_prompt, user_message) pair for the valuation AI call.

    The user_message contains all structured data; the system_prompt contains
    the reasoning framework. Gaps (no news, no filings) are noted explicitly
    so the model doesn't silently ignore missing context.
    """
    rule1 = analysis.get("rule1", {})
    rule2 = analysis.get("rule2", {})
    rule4 = analysis.get("rule4", {})
    ticker = analysis.get("ticker", "")
    company_name = analysis.get("company_name") or ticker
    price = analysis.get("price")

    analyst = get_analyst_fields(metrics)

    # Precompute formatted values to avoid backslash-in-f-string-expression,
    # which is a SyntaxError in Python < 3.12.
    price_str = f"${price:.2f}" if price else "N/A"
    eps_cagr = rule2.get("eps_cagr")
    rev_cagr = rule2.get("revenue_cagr")
    eps_cagr_str = f"{eps_cagr * 100:.1f}%" if eps_cagr is not None else "N/A"
    rev_cagr_str = f"{rev_cagr * 100:.1f}%" if rev_cagr is not None else "N/A"
    current_bv = rule4.get("current_bv")
    annual_div = rule4.get("annual_dividend")
    div_yield = rule4.get("dividend_yield")
    current_bv_str = f"${current_bv:.2f}" if current_bv is not None else "N/A"
    annual_div_str = f"${annual_div:.2f}" if annual_div is not None else "N/A"
    div_yield_str = f"{div_yield * 100:.2f}%" if div_yield is not None else "N/A"

    # ---- Financial data section ----
    lines = [
        "== COMPANY ==",
        f"Ticker: {ticker}",
        f"Name: {company_name}",
        f"Current Price: {price_str}",
        f"Sector: {rule2.get('sector') or 'N/A'} / {rule2.get('industry') or 'N/A'}",
        "",
        "== RULE 1 — BALANCE SHEET HEALTH ==",
        f"D/E Ratio (yfinance %form, divide by 100 for ratio): {rule1.get('debt_to_equity') or 'N/A'}",
        f"Current Ratio: {rule1.get('current_ratio') or 'N/A'}",
        f"ROE (decimal): {rule1.get('roe') or 'N/A'}",
        f"P/B Ratio: {rule1.get('pb_ratio') or 'N/A'}",
        f"Negative Equity: {rule1.get('negative_equity', False)}",
        f"Financial Sector Warning: {rule1.get('financial_sector_warning', False)}",
        "",
        "== RULE 2 — EPS & REVENUE HISTORY ==",
        f"EPS CAGR: {eps_cagr_str}",
        f"Revenue CAGR: {rev_cagr_str}",
        f"Consecutive positive EPS years: {rule2.get('consecutive_positive_eps_years', 0)}",
        f"Years of data: {rule2.get('years_of_data', 0)}",
    ]

    # EPS history table
    eps_history = rule2.get("eps_history", [])
    if eps_history:
        lines.append("EPS history (annual):")
        for e in eps_history[-10:]:
            year = e.get("period", "")[:4]
            val = e.get("value")
            lines.append(f"  {year}: {'${:.2f}'.format(val) if val is not None else 'N/A'}")

    # Revenue history table
    rev_history = rule2.get("revenue_history", [])
    if rev_history:
        lines.append("Revenue history (annual, raw $):")
        for e in rev_history[-10:]:
            year = e.get("period", "")[:4]
            val = e.get("value")
            lines.append(f"  {year}: {'${:,.0f}'.format(val) if val is not None else 'N/A'}")

    lines += [
        "",
        "== RULE 4 — INTRINSIC VALUE STATUS ==",
        f"Rule 4 inapplicable: {rule4.get('inapplicable', False)}",
        f"Reason: {rule4.get('inapplicable_reason') or 'N/A'}",
        f"Current BV/share: {current_bv_str}",
        f"Annual Dividend: {annual_div_str}",
        f"Dividend Yield: {div_yield_str}",
    ]

    # ---- Growth metrics / capital runway ----
    lines.append("")
    lines.append("== CAPITAL & GROWTH METRICS ==")
    if growth_metrics and not growth_metrics.get("error"):
        cash = growth_metrics.get("cash_on_hand")
        burn = growth_metrics.get("burn_rate")
        runway = growth_metrics.get("cash_runway_quarters")
        dilution = growth_metrics.get("dilution_rate")

        lines.append(f"Cash on hand: {'${:,.0f}'.format(cash) if cash is not None else 'N/A'}")
        lines.append(f"Quarterly burn rate: {'${:,.0f}'.format(burn) if burn is not None else 'N/A'}")
        lines.append(f"Estimated runway: {f'{runway:.1f} quarters' if runway is not None else 'N/A'}")
        lines.append(f"Annual dilution rate: {f'{dilution * 100:.1f}%' if dilution is not None else 'N/A'}")

        rg = growth_metrics.get("revenue_growth_rates", [])
        if rg:
            lines.append("Recent revenue growth rates (quarterly):")
            for r in rg[-6:]:
                lines.append(f"  {r.get('period', '')[:4]}: {r.get('growth_rate', 0) * 100:.1f}%")
    else:
        lines.append("Growth metrics unavailable.")

    # ---- Analyst consensus ----
    lines.append("")
    lines.append("== ANALYST CONSENSUS ==")
    n = analyst.get("number_of_analyst_opinions")
    if n:
        lines.append(f"Analysts covering: {n}")
        lines.append(f"Consensus rating: {analyst.get('recommendation_key') or 'N/A'} (mean score: {analyst.get('recommendation_mean') or 'N/A'} — 1=Strong Buy, 5=Strong Sell)")
        lo = analyst.get("target_low_price")
        mean = analyst.get("target_mean_price")
        hi = analyst.get("target_high_price")
        lines.append(f"Price target range: {f'${lo:.2f}' if lo else 'N/A'} — {f'${mean:.2f}' if mean else 'N/A'} — {f'${hi:.2f}' if hi else 'N/A'} (low / mean / high)")
    else:
        lines.append("No analyst coverage data available.")

    # ---- News ----
    lines.append("")
    lines.append("== RECENT NEWS HEADLINES ==")
    if news:
        for item in news:
            lines.append(f"[{item.get('source', '')}] {item.get('title', '')}")
            if item.get("snippet"):
                lines.append(f"  {item['snippet']}")
    else:
        lines.append("News data unavailable (Serper API not configured or search failed).")

    # ---- Filing context ----
    lines.append("")
    lines.append("== 10-K FILING EXCERPTS (most recent annual report) ==")
    if filing_10k:
        lines.append(filing_10k)
    else:
        lines.append("10-K context unavailable — ticker may not yet be indexed in the filing database.")

    lines.append("")
    lines.append("== 10-Q FILING EXCERPTS (most recent quarterly report) ==")
    if filing_10q:
        lines.append(filing_10q)
    else:
        lines.append("10-Q context unavailable — ticker may not yet be indexed in the filing database.")

    user_message = "\n".join(lines)
    return _SYSTEM_PROMPT, user_message