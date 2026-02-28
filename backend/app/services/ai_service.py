"""OpenAI async streaming wrapper for the AI Research Assistant.

Provides two streaming modes:
- stream_chat_response: Simple token streaming (no tools)
- stream_chat_response_with_tools: Agentic loop with tool-calling support
"""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Callable, Awaitable

import openai

from app.config import get_settings

logger = logging.getLogger(__name__)

# Type for tool executor: takes (tool_name, arguments_dict), returns string result
ToolExecutor = Callable[[str, dict], Awaitable[str]]


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


async def stream_chat_response_with_tools(
    system_prompt: str,
    messages: list[dict],
    tools: list[dict],
    tool_executor: ToolExecutor,
) -> AsyncGenerator[dict, None]:
    """Stream tokens from OpenAI with agentic tool-calling support.

    Runs a loop: if the model requests tool calls, executes them and feeds
    results back.  Yields structured events:
      {"type": "token", "content": "..."}     — text token
      {"type": "status", "content": "..."}    — tool-call status message
      {"type": "done"}                        — end of response

    The loop runs at most rag_max_tool_iterations rounds.

    Args:
        system_prompt: The full system prompt with ticker context.
        messages: Conversation history in OpenAI format.
        tools: OpenAI tool definitions.
        tool_executor: Async function that executes a tool call.
    """
    settings = get_settings()
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    max_iterations = settings.rag_max_tool_iterations

    full_messages = [
        {"role": "system", "content": system_prompt},
        *messages,
    ]

    for iteration in range(max_iterations):
        # Accumulate the full assistant message from streamed chunks
        content_parts: list[str] = []
        tool_calls_by_index: dict[int, dict] = {}
        finish_reason = None

        stream = await client.chat.completions.create(
            model=settings.openai_model,
            messages=full_messages,
            max_tokens=settings.ai_max_tokens,
            temperature=0.7,
            tools=tools,
            stream=True,
        )

        async for chunk in stream:
            choice = chunk.choices[0]
            delta = choice.delta
            finish_reason = choice.finish_reason or finish_reason

            # Stream content tokens to the client
            if delta.content:
                content_parts.append(delta.content)
                yield {"type": "token", "content": delta.content}

            # Accumulate tool call deltas (streamed in pieces)
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls_by_index:
                        tool_calls_by_index[idx] = {
                            "id": "",
                            "function": {"name": "", "arguments": ""},
                        }
                    tc = tool_calls_by_index[idx]
                    if tc_delta.id:
                        tc["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tc["function"]["name"] += tc_delta.function.name
                        if tc_delta.function.arguments:
                            tc["function"]["arguments"] += tc_delta.function.arguments

        # If the model produced content without tool calls, we're done
        if finish_reason != "tool_calls" or not tool_calls_by_index:
            yield {"type": "done"}
            return

        # Build the assistant message with tool_calls for the conversation
        assistant_msg: dict = {"role": "assistant"}
        if content_parts:
            assistant_msg["content"] = "".join(content_parts)
        assistant_msg["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": tc["function"],
            }
            for tc in sorted(tool_calls_by_index.values(), key=lambda t: t["id"])
        ]
        full_messages.append(assistant_msg)

        # Execute each tool call and append results
        for tc in assistant_msg["tool_calls"]:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                fn_args = {}

            yield {"type": "status", "content": f"Searching filings: {fn_args.get('query', fn_name)}..."}
            logger.info(f"Tool call: {fn_name}({fn_args})")

            try:
                result = await tool_executor(fn_name, fn_args)
            except Exception as e:
                logger.error(f"Tool execution failed: {fn_name}: {e}")
                result = f"Error executing {fn_name}: {e}"

            full_messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })

        logger.info(f"Tool iteration {iteration + 1}/{max_iterations} complete, continuing...")

    # Exhausted iterations — do a final call without tools to get a response
    logger.warning(f"Hit max tool iterations ({max_iterations}), making final call")
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
            yield {"type": "token", "content": delta.content}

    yield {"type": "done"}
