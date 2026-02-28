"""AI Research Assistant — streaming chat endpoint.

POST /chat accepts a ticker + conversation history, assembles all available
structured data into the system prompt, and streams the OpenAI response back
as Server-Sent Events (SSE).

When the company has indexed filings, the endpoint switches to agentic mode
with tool-calling — the LLM can search filing text via the search_filings tool.
"""

import json
import logging
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database import get_db
from app.models import database as _db
from app.services.ai_context import build_ticker_context, get_filing_index_info
from app.services.ai_prompts import build_system_prompt
from app.services.ai_service import stream_chat_response, stream_chat_response_with_tools
from app.services.vector_search import search_filing_chunks, format_search_results_for_llm
from app.auth.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    ticker: str
    messages: list[ChatMessage]
    include_financials: bool = True
    include_growth: bool = True


# ---------------------------------------------------------------------------
# Simple in-memory rate limiter (resets on server restart — fine for single instance)
# ---------------------------------------------------------------------------

_request_times: dict[str, list[float]] = defaultdict(list)
_MAX_RPM = 20  # Requests per minute per user


def _check_rate_limit(user_id: str) -> bool:
    now = time.time()
    cutoff = now - 60
    _request_times[user_id] = [t for t in _request_times[user_id] if t > cutoff]
    if len(_request_times[user_id]) >= _MAX_RPM:
        return False
    _request_times[user_id].append(now)
    return True


# ---------------------------------------------------------------------------
# Tool definitions for agentic filing search
# ---------------------------------------------------------------------------

FILING_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_filings",
        "description": (
            "Search indexed SEC filings (10-K, 10-Q, 8-K) for specific information. "
            "Returns relevant excerpts from filing sections ranked by semantic similarity."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Semantic search query. Be specific — e.g., 'china supply chain risk' "
                        "rather than just 'risk'."
                    ),
                },
                "filing_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["10-K", "10-Q", "8-K"]},
                    "description": "Optional filter to specific filing types.",
                },
                "categories": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "risk_factors", "financial_discussion", "business_overview",
                            "financial_statements", "legal", "regulatory", "market_info",
                            "events_transactions", "corporate_governance", "guidance_outlook",
                        ],
                    },
                    "description": "Optional filter to specific section categories.",
                },
            },
            "required": ["query"],
        },
    },
}


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/chat")
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Stream an AI research analysis response for the given ticker.

    When the company has indexed filings, uses agentic tool-calling so the
    LLM can search filing text.  Otherwise, falls back to simple streaming.
    """
    settings = get_settings()

    if not settings.openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="AI features not configured — set OPENAI_API_KEY in your environment.",
        )

    if not _check_rate_limit(user["id"]):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait a moment before sending another message.",
        )

    # Build context from all available data
    context_data = await build_ticker_context(
        db,
        request.ticker,
        include_financials=request.include_financials,
        include_growth=request.include_growth,
    )

    # Check if filings are indexed for this ticker
    filing_info = await get_filing_index_info(db, request.ticker)
    use_tools = filing_info is not None and filing_info.get("status") == "ready"

    system_prompt = build_system_prompt(request.ticker, context_data, filing_info)
    openai_messages = [{"role": m.role, "content": m.content} for m in request.messages]

    if use_tools:
        # Agentic mode: LLM can call search_filings tool
        ticker_upper = request.ticker.upper()

        async def tool_executor(tool_name: str, args: dict) -> str:
            """Execute a tool call from the LLM."""
            if tool_name != "search_filings":
                return f"Unknown tool: {tool_name}"

            # Tool executor needs its own session since the request session
            # may have been committed/closed during streaming
            async with _db.async_session_factory() as tool_db:
                results = await search_filing_chunks(
                    db=tool_db,
                    ticker=ticker_upper,
                    query_text=args.get("query", ""),
                    filing_types=args.get("filing_types"),
                    categories=args.get("categories"),
                )
                return format_search_results_for_llm(results)

        async def event_stream():
            try:
                async for event in stream_chat_response_with_tools(
                    system_prompt, openai_messages,
                    tools=[FILING_SEARCH_TOOL],
                    tool_executor=tool_executor,
                ):
                    if event["type"] == "token":
                        yield f"data: {json.dumps({'token': event['content']})}\n\n"
                    elif event["type"] == "status":
                        yield f"data: {json.dumps({'status': event['content']})}\n\n"
                    elif event["type"] == "done":
                        yield f"data: {json.dumps({'done': True})}\n\n"
            except Exception as e:
                logger.error(f"AI streaming error for {request.ticker}: {e}")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
    else:
        # Simple mode: no tools, direct streaming
        async def event_stream():
            try:
                async for token in stream_chat_response(system_prompt, openai_messages):
                    yield f"data: {json.dumps({'token': token})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
            except Exception as e:
                logger.error(f"AI streaming error for {request.ticker}: {e}")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Prevent proxy buffering
        },
    )
