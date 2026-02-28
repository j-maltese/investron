"""OpenAI embedding generation for filing chunks.

Supports batch embedding (for indexing) and single embedding (for queries).
Uses text-embedding-3-small by default (1536 dimensions, $0.02/1M tokens).
"""

import logging
import time

import openai

from app.config import get_settings

logger = logging.getLogger(__name__)


async def generate_embeddings(
    texts: list[str],
    model: str | None = None,
) -> list[list[float]]:
    """Generate embeddings for a batch of texts.

    OpenAI supports up to 2048 texts per API call.  For larger batches,
    this function splits into multiple calls automatically.

    Returns list of float vectors in the same order as the input texts.
    """
    settings = get_settings()
    model = model or settings.embedding_model
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

    all_embeddings: list[list[float]] = []
    total_tokens = 0
    start = time.time()

    # Process in batches of 2048 (OpenAI limit)
    batch_size = 2048
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = await client.embeddings.create(model=model, input=batch)
        for item in resp.data:
            all_embeddings.append(item.embedding)
        total_tokens += resp.usage.total_tokens

    elapsed = time.time() - start
    logger.info(
        f"Generated {len(all_embeddings)} embeddings in {elapsed:.1f}s "
        f"({total_tokens:,} tokens, model={model})"
    )
    return all_embeddings


async def generate_single_embedding(
    text: str,
    model: str | None = None,
) -> list[float]:
    """Generate a single embedding vector (used for query-time search)."""
    results = await generate_embeddings([text], model=model)
    return results[0]
