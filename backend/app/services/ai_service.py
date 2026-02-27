"""OpenAI async streaming wrapper for the AI Research Assistant."""

import logging
from collections.abc import AsyncGenerator

import openai

from app.config import get_settings

logger = logging.getLogger(__name__)


async def stream_chat_response(
    system_prompt: str,
    messages: list[dict],
) -> AsyncGenerator[str, None]:
    """Stream tokens from OpenAI, yielding each content delta.

    Args:
        system_prompt: The full system prompt including ticker data context.
        messages: Conversation history in OpenAI format [{role, content}, ...].

    Yields:
        Individual text tokens as they arrive from the API.
    """
    settings = get_settings()
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

    full_messages = [
        {"role": "system", "content": system_prompt},
        *messages,
    ]

    stream = await client.chat.completions.create(
        model=settings.openai_model,
        messages=full_messages,
        max_tokens=settings.ai_max_tokens,
        temperature=0.7,
        stream=True,
    )

    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content
