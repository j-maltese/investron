"""AI Research Assistant — streaming chat endpoint.

POST /chat accepts a ticker + conversation history, assembles all available
structured data into the system prompt, and streams the OpenAI response back
as Server-Sent Events (SSE).
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
from app.services.ai_context import build_ticker_context
from app.services.ai_prompts import build_system_prompt
from app.services.ai_service import stream_chat_response
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
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/chat")
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Stream an AI research analysis response for the given ticker."""
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

    system_prompt = build_system_prompt(request.ticker, context_data)
    openai_messages = [{"role": m.role, "content": m.content} for m in request.messages]

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
