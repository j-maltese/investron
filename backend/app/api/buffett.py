"""Buffett 4-Rules Intrinsic Value Calculator API.

GET  /api/buffett/{ticker}                  — Full 4-rule analysis (cached 15min)
POST /api/buffett/{ticker}/ai-analysis      — On-demand Rule 2 AI durability analysis (streamed)
POST /api/buffett/{ticker}/valuation-ai     — On-demand Option B AI valuation (streamed)
                                              Used when Rule 4 is inapplicable. Assembles a rich
                                              prompt from financials, analyst data, news, and
                                              indexed SEC filings, then streams a reasoning-model
                                              response. Frontend must ensure ticker is indexed first.

The GET endpoint is cheap: it calls buffett_service.get_buffett_analysis() which
assembles data from already-cached yfinance + EDGAR calls. The POST endpoints are
expensive (reasoning model) and must be manually triggered by the user.
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database import get_db
from app.services.buffett_service import get_buffett_analysis
from app.services.financials import get_growth_metrics, get_key_metrics
from app.services.ai_service import stream_chat_response
from app.services.buffett_valuation_ai import search_news, get_filing_context, build_valuation_prompt
from app.auth.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

_ENDPOINT_TIMEOUT = 30  # seconds; EDGAR + yfinance + treasury in parallel


@router.get("/{ticker}")
async def get_analysis(
    ticker: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Return the full Buffett 4-rule scorecard for a ticker.

    Data is assembled from cached yfinance (key_metrics, 15min TTL) and
    EDGAR (financial statements, 24h TTL) sources, then cached itself for
    15 minutes. Typical response time is <100ms when warm, ~3-5s cold.
    """
    import asyncio
    try:
        result = await asyncio.wait_for(
            get_buffett_analysis(ticker.upper(), db),
            timeout=_ENDPOINT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Data fetch timed out — please try again.")

    if result.get("error"):
        raise HTTPException(status_code=502, detail=result.get("error_message", "Data unavailable"))

    return result


@router.post("/{ticker}/ai-analysis")
async def ai_analysis(
    ticker: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Stream a Rule 2 durability analysis for the given ticker.

    Uses a reasoning-capable model (configurable via BUFFETT_AI_MODEL env var)
    to assess whether the company's business will still exist and thrive in 30 years.
    Focuses on: (1) product/service durability, (2) business model predictability,
    (3) competitive moat and key durability risks.

    This endpoint is intentionally NOT auto-triggered — it requires a manual button
    click because the model is expensive and the analysis takes time.
    """
    settings = get_settings()

    if not settings.openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="AI features not configured — set OPENAI_API_KEY in your environment.",
        )

    # Fetch the analysis result so we can inject real numbers into the prompt
    import asyncio
    try:
        analysis = await asyncio.wait_for(
            get_buffett_analysis(ticker.upper(), db),
            timeout=_ENDPOINT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Data fetch timed out.")

    if analysis.get("error"):
        raise HTTPException(status_code=502, detail=analysis.get("error_message", "Data unavailable"))

    rule2 = analysis.get("rule2", {})
    company_name = analysis.get("company_name") or ticker.upper()
    sector = rule2.get("sector") or "Unknown"
    industry = rule2.get("industry") or "Unknown"
    eps_cagr = rule2.get("eps_cagr")
    revenue_cagr = rule2.get("revenue_cagr")
    consecutive_eps = rule2.get("consecutive_positive_eps_years", 0)
    years_of_data = rule2.get("years_of_data", 0)

    # Format the historical series into a readable table for the prompt
    def _fmt_series(series: list[dict], label: str, pct: bool = False) -> str:
        if not series:
            return f"{label}: no data available"
        rows = []
        for e in series[-10:]:  # max 10 years
            val = e.get("value")
            period = e.get("period", "")[:4]  # just the year
            if val is None:
                rows.append(f"  {period}: N/A")
            elif pct:
                rows.append(f"  {period}: {val * 100:.1f}%")
            else:
                rows.append(f"  {period}: {val:,.2f}")
        return f"{label}:\n" + "\n".join(rows)

    eps_table = _fmt_series(rule2.get("eps_history", []), "EPS (diluted, $)")
    revenue_table = _fmt_series(rule2.get("revenue_history", []), "Revenue ($)")

    cagr_summary = []
    if eps_cagr is not None:
        cagr_summary.append(f"EPS CAGR ({years_of_data}yr): {eps_cagr * 100:.1f}%")
    if revenue_cagr is not None:
        cagr_summary.append(f"Revenue CAGR ({years_of_data}yr): {revenue_cagr * 100:.1f}%")
    if consecutive_eps:
        cagr_summary.append(f"Consecutive positive EPS years: {consecutive_eps}")

    system_prompt = (
        "You are a long-term business durability analyst following Warren Buffett's investing principles. "
        "You assess whether a business has the characteristics of a 'forever holding' — a company so "
        "fundamentally sound and durable that Buffett would be comfortable owning it for 30+ years.\n\n"
        "Structure your response with these three sections:\n"
        "1. **Will This Business Exist in 30 Years?** — assess product/service permanence, "
        "   technological disruption risk, and whether the core need it fills is enduring.\n"
        "2. **Is the Business Model Understandable and Predictable?** — can you describe in one "
        "   sentence how the company makes money? Is revenue recurring or lumpy? Are margins stable?\n"
        "3. **Key Durability Risks** — what are the top 2-3 threats to this business over a multi-decade "
        "   horizon? Be specific and honest — not every company is a Buffett stock.\n\n"
        "Be concise but substantive. Use the financial data provided as evidence. "
        "Do not hedge everything — give a clear view. If the data suggests this is NOT a Buffett-style "
        "business, say so directly."
    )

    user_message = (
        f"Company: {company_name} ({ticker.upper()})\n"
        f"Sector: {sector} / {industry}\n\n"
        f"{eps_table}\n\n"
        f"{revenue_table}\n\n"
        + ("\n".join(cagr_summary) if cagr_summary else "")
    )

    async def event_stream():
        try:
            async for token in stream_chat_response(
                system_prompt,
                [{"role": "user", "content": user_message}],
                model_override=settings.buffett_ai_model,
            ):
                yield f"data: {json.dumps({'token': token})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            logger.error("Buffett AI analysis error for %s: %s", ticker, e)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{ticker}/valuation-ai")
async def valuation_ai(
    ticker: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Stream an Option B AI valuation for a ticker where Rule 4 is inapplicable.

    Assembles a rich prompt from:
      - Buffett 4-rule analysis (cached)
      - Growth metrics: cash, burn rate, runway (cached)
      - Key metrics including analyst consensus fields (cached)
      - Recent news headlines via Serper API (optional, skipped if not configured)
      - Indexed 10-K and 10-Q filing excerpts via pgvector semantic search

    The frontend is responsible for ensuring the ticker is indexed before calling
    this endpoint — this endpoint always uses the RAG path (no direct EDGAR fallback).
    Filing context will be empty (and noted in the prompt) if not yet indexed.

    Uses settings.buffett_valuation_model (default: o4-mini). Temperature is omitted
    so reasoning models work correctly.
    """
    import asyncio

    settings = get_settings()

    if not settings.openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="AI features not configured — set OPENAI_API_KEY in your environment.",
        )

    # Parallel fetch of all cached data sources — all three are fast cache hits
    # after the initial cold load. Running them together saves ~200ms.
    try:
        analysis, growth_metrics, metrics = await asyncio.wait_for(
            asyncio.gather(
                get_buffett_analysis(ticker.upper(), db),
                get_growth_metrics(db, ticker),
                get_key_metrics(db, ticker),
            ),
            timeout=_ENDPOINT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Data fetch timed out — please try again.")

    if analysis.get("error"):
        raise HTTPException(status_code=502, detail=analysis.get("error_message", "Data unavailable"))

    company_name = analysis.get("company_name") or ticker.upper()

    async def event_stream():
        try:
            # Emit status immediately so the UI shows feedback during the pre-fetch phase
            yield f"data: {json.dumps({'status': 'Gathering financial data, news, and filing context...'})}\n\n"

            # Fetch news + filing context in parallel — these are the slow I/O operations.
            # Filing context uses pgvector semantic search on the already-indexed chunks.
            news, filing_10k, filing_10q = await asyncio.gather(
                search_news(ticker, company_name, settings.serper_api_key),
                get_filing_context(db, ticker, "10-K"),
                get_filing_context(db, ticker, "10-Q"),
            )

            system_prompt, user_message = build_valuation_prompt(
                analysis=analysis,
                growth_metrics=growth_metrics,
                metrics=metrics,
                news=news,
                filing_10k=filing_10k,
                filing_10q=filing_10q,
            )

            # Stream from the reasoning model — temperature=None omits the parameter,
            # which is required for o1/o3/o4-* models (they reject temperature != 1.0).
            async for token in stream_chat_response(
                system_prompt,
                [{"role": "user", "content": user_message}],
                model_override=settings.buffett_valuation_model,
                temperature=None,
            ):
                yield f"data: {json.dumps({'token': token})}\n\n"

            yield f"data: {json.dumps({'done': True})}\n\n"

        except Exception as e:
            logger.error("Buffett valuation AI error for %s: %s", ticker, e)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )