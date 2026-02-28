"""LLM-based topic extraction for filing sections.

Uses GPT-4o-mini to extract 3-8 free-form topic phrases per section.
Called once per section (not per chunk) to keep costs very low (~$0.01
per full 10-K).  All chunks within a section inherit the same topics.

Topics are enhancement metadata — extraction failures fall back to an
empty list and never block the indexing pipeline.
"""

import json
import logging

import openai

from app.config import get_settings
from app.services.filing_chunker import count_tokens

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
Extract 3-8 key topic phrases from this SEC filing section.

Return ONLY a JSON array of short phrases (2-5 words each).
Focus on specific business risks, strategies, financial themes,
or notable disclosures — not generic labels.

Company: {ticker}
Filing type: {filing_type}
Section: {section_name}

Section text (may be truncated):
{text}"""

# Truncate section text to ~3000 tokens to keep extraction cheap
_MAX_EXTRACTION_TOKENS = 3000


async def extract_section_topics(
    section_name: str,
    section_text: str,
    filing_type: str,
    ticker: str,
) -> list[str]:
    """Extract free-form topic phrases from a filing section.

    Returns list of short phrases like ["china supply chain risk",
    "tariff exposure", "customer concentration"].

    Falls back to [] on any error — topics are nice-to-have, not critical.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        return []

    # Truncate to keep prompt small and cost low
    if count_tokens(section_text) > _MAX_EXTRACTION_TOKENS:
        # Rough character estimate: ~4 chars per token
        section_text = section_text[: _MAX_EXTRACTION_TOKENS * 4]

    prompt = _EXTRACTION_PROMPT.format(
        ticker=ticker.upper(),
        filing_type=filing_type,
        section_name=section_name,
        text=section_text,
    )

    try:
        client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        resp = await client.chat.completions.create(
            model=settings.topic_extraction_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.3,
        )
        content = resp.choices[0].message.content.strip()

        # Parse JSON array from the response
        # Handle cases where model wraps in ```json ... ```
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]

        topics = json.loads(content)
        if isinstance(topics, list):
            topics = [str(t).strip() for t in topics if t]
            logger.debug(f"Extracted {len(topics)} topics from {section_name}: {topics}")
            return topics[:8]  # Cap at 8

    except Exception as e:
        logger.warning(f"Topic extraction failed for {section_name}: {e}")

    return []
