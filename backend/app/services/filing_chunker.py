"""Section-aware chunking engine for parsed SEC filings.

Rules:
1. Tables are NEVER split — each becomes its own chunk regardless of size.
2. Text chunks respect section boundaries — never cross sections.
3. Token counting uses tiktoken cl100k_base (matches text-embedding-3-small).
4. chunk_index is sequential across the entire filing.
"""

import logging
from dataclasses import dataclass

import tiktoken

from app.config import get_settings
from app.services.filing_parser import ParsedFiling

logger = logging.getLogger(__name__)

# Cache the tokenizer — same encoding used by text-embedding-3-small
_enc = tiktoken.get_encoding("cl100k_base")


@dataclass
class Chunk:
    text: str
    token_count: int
    section_name: str
    category: str
    is_table: bool
    chunk_index: int  # position within the filing


def count_tokens(text: str) -> int:
    """Count tokens using the cl100k_base encoding."""
    return len(_enc.encode(text))


def chunk_filing(
    parsed: ParsedFiling,
    max_tokens: int | None = None,
    overlap: int | None = None,
) -> list[Chunk]:
    """Chunk a parsed filing into embedding-ready pieces.

    Args:
        parsed: Output of parse_filing_html().
        max_tokens: Max tokens per text chunk (default from config).
        overlap: Overlap tokens between consecutive text chunks (default from config).

    Returns:
        Ordered list of Chunks with sequential chunk_index values.
    """
    settings = get_settings()
    if max_tokens is None:
        max_tokens = settings.chunk_max_tokens
    if overlap is None:
        overlap = settings.chunk_overlap_tokens

    chunks: list[Chunk] = []
    idx = 0
    n_tables = 0
    n_text = 0

    for section in parsed.sections:
        # Chunk the text content (respects section boundary)
        if section.text_content.strip():
            text_chunks = _split_text_by_tokens(section.text_content, max_tokens, overlap)
            for chunk_text, token_count in text_chunks:
                chunks.append(Chunk(
                    text=chunk_text,
                    token_count=token_count,
                    section_name=section.section_name,
                    category=section.category,
                    is_table=False,
                    chunk_index=idx,
                ))
                idx += 1
                n_text += 1

        # Each table is its own chunk — never split
        for table_md in section.tables:
            token_count = count_tokens(table_md)
            chunks.append(Chunk(
                text=table_md,
                token_count=token_count,
                section_name=section.section_name,
                category=section.category,
                is_table=True,
                chunk_index=idx,
            ))
            idx += 1
            n_tables += 1

    total_tokens = sum(c.token_count for c in chunks)
    avg_tokens = total_tokens // len(chunks) if chunks else 0
    logger.info(
        f"Chunked {parsed.filing_type} into {len(chunks)} chunks "
        f"({n_tables} tables, {n_text} text, avg {avg_tokens} tokens, "
        f"quality={parsed.parse_quality})"
    )
    return chunks


def _split_text_by_tokens(
    text: str,
    max_tokens: int,
    overlap_tokens: int,
) -> list[tuple[str, int]]:
    """Split text into chunks by token count, respecting sentence boundaries.

    Returns list of (chunk_text, token_count) tuples.
    """
    tokens = _enc.encode(text)
    total = len(tokens)

    if total <= max_tokens:
        return [(text, total)]

    chunks: list[tuple[str, int]] = []
    start = 0

    while start < total:
        end = min(start + max_tokens, total)
        chunk_tokens = tokens[start:end]
        chunk_text = _enc.decode(chunk_tokens).strip()

        if chunk_text:
            chunks.append((chunk_text, len(chunk_tokens)))

        # Advance by (max_tokens - overlap) to create overlap between chunks
        start += max_tokens - overlap_tokens

    return chunks
