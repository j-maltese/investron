"""pgvector similarity search for filing chunks.

Combines metadata WHERE filters (ticker, filing_type, category, date)
with cosine similarity on the embedding vector in a single SQL query.
The HNSW index on filing_chunks accelerates the vector part.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.embedding_service import generate_single_embedding

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    chunk_text: str
    filing_type: str
    filing_date: str
    section_name: str
    category: str
    topics: list[str]
    is_table: bool
    similarity: float
    token_count: int


async def search_filing_chunks(
    db: AsyncSession,
    ticker: str,
    query_text: str,
    top_k: int = 8,
    max_tokens: int | None = None,
    filing_types: list[str] | None = None,
    categories: list[str] | None = None,
    min_date: str | None = None,
) -> list[SearchResult]:
    """Search filing chunks by semantic similarity with optional metadata filters.

    Args:
        db: Async database session.
        ticker: Company ticker (always filtered).
        query_text: User's search query.
        top_k: Maximum number of results to return.
        max_tokens: Stop adding results when cumulative tokens exceed this.
        filing_types: Optional filter to specific filing types.
        categories: Optional filter to specific section categories.
        min_date: Optional minimum filing date (YYYY-MM-DD).

    Returns:
        Ordered list of SearchResult (most similar first), within token budget.
    """
    settings = get_settings()
    if max_tokens is None:
        max_tokens = settings.rag_max_context_tokens

    # Generate embedding for the query
    query_embedding = await generate_single_embedding(query_text)

    # Build SQL with dynamic filters
    # pgvector uses <=> for cosine distance; similarity = 1 - distance
    where_clauses = ["ticker = :ticker"]
    # Pass embedding as list — our registered pgvector codec serializes it
    params: dict = {"ticker": ticker.upper(), "query_embedding": query_embedding}

    if filing_types:
        where_clauses.append("filing_type = ANY(:filing_types)")
        params["filing_types"] = filing_types

    if categories:
        where_clauses.append("category = ANY(:categories)")
        params["categories"] = categories

    if min_date:
        where_clauses.append("filing_date >= :min_date")
        params["min_date"] = min_date

    where_sql = " AND ".join(where_clauses)

    # Fetch more than top_k to allow token budget trimming
    fetch_limit = top_k * 2

    # No ::vector cast needed — our registered pgvector codec handles
    # serialization, and asyncpg infers the vector type from the <=> operator.
    sql = text(f"""
        SELECT chunk_text, filing_type, filing_date::text, section_name,
               category, topics, is_table, token_count,
               1 - (embedding <=> :query_embedding) AS similarity
        FROM filing_chunks
        WHERE {where_sql}
        ORDER BY embedding <=> :query_embedding
        LIMIT :fetch_limit
    """)
    params["fetch_limit"] = fetch_limit

    result = await db.execute(sql, params)
    rows = result.mappings().all()

    # Accumulate results within token budget
    results: list[SearchResult] = []
    cumulative_tokens = 0

    for row in rows:
        tokens = row["token_count"] or 0
        if cumulative_tokens + tokens > max_tokens and results:
            break  # Don't exceed budget (but always return at least 1 result)

        results.append(SearchResult(
            chunk_text=row["chunk_text"],
            filing_type=row["filing_type"],
            filing_date=row["filing_date"],
            section_name=row["section_name"] or "Unknown Section",
            category=row["category"] or "general",
            topics=row["topics"] or [],
            is_table=row["is_table"],
            similarity=float(row["similarity"]),
            token_count=tokens,
        ))
        cumulative_tokens += tokens

        if len(results) >= top_k:
            break

    logger.info(
        f"Filing search for '{query_text[:60]}' on {ticker}: "
        f"{len(results)} results ({cumulative_tokens} tokens, "
        f"top similarity={results[0].similarity:.3f})" if results else
        f"Filing search for '{query_text[:60]}' on {ticker}: 0 results"
    )
    return results


def format_search_results_for_llm(results: list[SearchResult]) -> str:
    """Format search results into a text block for injection into the LLM context.

    Groups by filing and section with citation headers for readability.
    """
    if not results:
        return (
            "No relevant filing excerpts found for this query. "
            "The indexed filings may not cover this specific topic."
        )

    blocks: list[str] = []
    for r in results:
        header = f"--- From {r.filing_type} ({r.filing_date}) | {r.section_name} ---"
        if r.is_table:
            header += " [Table]"
        blocks.append(f"{header}\n{r.chunk_text}")

    return "\n\n".join(blocks)
