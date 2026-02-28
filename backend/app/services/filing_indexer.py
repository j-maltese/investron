"""Orchestrates the full filing indexing pipeline.

For a given ticker: fetches filings from the cache (or EDGAR), then for each
filing runs: fetch HTML → parse sections → chunk → extract topics → embed →
INSERT chunks into the filing_chunks table.

Filings are processed sequentially (respects SEC rate limits).  If one filing
fails the pipeline skips it and continues — partial progress is better than
nothing.  Status is tracked in filing_index_status throughout.
"""

import asyncio
import logging
import time
from datetime import date, datetime, timezone
from typing import Callable, Awaitable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.company import get_or_create_company
from app.services.filings import get_filings
from app.services.filing_fetcher import fetch_filing_html, FilingFetchError
from app.services.filing_parser import parse_filing_html
from app.services.filing_chunker import chunk_filing
from app.services.filing_topics import extract_section_topics
from app.services.embedding_service import generate_embeddings

logger = logging.getLogger(__name__)

# Tracks in-flight indexing to block concurrent requests for the same ticker
_indexing_locks: dict[str, asyncio.Lock] = {}

# In-memory progress messages — polled by the status endpoint during indexing
_indexing_progress: dict[str, str] = {}


def get_indexing_progress(ticker: str) -> str | None:
    """Get the current progress message for an in-flight indexing job."""
    return _indexing_progress.get(ticker.upper())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def index_company_filings(
    db: AsyncSession,
    ticker: str,
    filing_types: list[str] | None = None,
    progress_callback: Callable[[str], Awaitable[None]] | None = None,
) -> dict:
    """Index SEC filings for a company into vectorized chunks.

    Args:
        db: Async database session.
        ticker: Company ticker symbol.
        filing_types: Which filing types to index (default: 10-K, 10-Q).
        progress_callback: Optional async callback for progress messages.

    Returns:
        Summary dict with filings_indexed, chunks_total, and any errors.
    """
    settings = get_settings()
    ticker = ticker.upper()
    if filing_types is None:
        filing_types = ["10-K", "10-Q", "8-K"]

    # Per-type limits: 10-K covers years (fewer needed), 10-Q covers quarters,
    # 8-K covers material events (small docs, cheap to index)
    type_limits = {
        "10-K": settings.filing_index_max_10k,
        "10-Q": settings.filing_index_max_10q,
        "8-K": settings.filing_index_max_8k,
    }

    # Acquire per-ticker lock to prevent concurrent indexing
    if ticker not in _indexing_locks:
        _indexing_locks[ticker] = asyncio.Lock()
    lock = _indexing_locks[ticker]

    if lock.locked():
        logger.warning(f"Indexing already in progress for {ticker}, skipping")
        return {"error": "Indexing already in progress", "ticker": ticker}

    async with lock:
        return await _run_indexing_pipeline(
            db, ticker, filing_types, type_limits, progress_callback,
        )


async def get_index_status(db: AsyncSession, ticker: str) -> dict | None:
    """Get the current filing index status for a ticker.

    Returns None if the ticker has never been indexed.
    """
    result = await db.execute(
        text("""
            SELECT ticker, status, filings_indexed, chunks_total,
                   last_indexed_at, last_filing_date, error_message,
                   created_at, updated_at
            FROM filing_index_status
            WHERE ticker = :ticker
        """),
        {"ticker": ticker.upper()},
    )
    row = result.mappings().first()
    if not row:
        return None
    return {
        **dict(row),
        # Serialize datetimes for JSON
        "last_indexed_at": row["last_indexed_at"].isoformat() if row["last_indexed_at"] else None,
        "last_filing_date": row["last_filing_date"].isoformat() if row["last_filing_date"] else None,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


async def delete_company_index(db: AsyncSession, ticker: str) -> None:
    """Delete all indexed chunks and reset status for a ticker."""
    ticker = ticker.upper()
    await db.execute(
        text("DELETE FROM filing_chunks WHERE ticker = :ticker"),
        {"ticker": ticker},
    )
    await db.execute(
        text("DELETE FROM filing_index_status WHERE ticker = :ticker"),
        {"ticker": ticker},
    )
    await db.commit()
    logger.info(f"Deleted filing index for {ticker}")


# ---------------------------------------------------------------------------
# Internal pipeline
# ---------------------------------------------------------------------------

async def _run_indexing_pipeline(
    db: AsyncSession,
    ticker: str,
    filing_types: list[str],
    type_limits: dict[str, int],
    progress_callback: Callable[[str], Awaitable[None]] | None,
) -> dict:
    """Execute the full indexing pipeline for a ticker."""
    start_time = time.time()

    async def _progress(msg: str):
        logger.info(f"[{ticker}] {msg}")
        _indexing_progress[ticker] = msg
        if progress_callback:
            await progress_callback(msg)

    # Step 1: Resolve company
    company = await get_or_create_company(db, ticker)
    if not company:
        await _update_status(db, ticker, None, "error", error="Company not found")
        return {"error": "Company not found", "ticker": ticker}

    company_id = company["id"]

    # Upsert initial status
    await _update_status(db, ticker, company_id, "indexing")
    await _progress("Starting filing indexing pipeline")

    # Step 2: Get filings from cache (or fetch from EDGAR)
    filings_data = await get_filings(db, ticker, filing_types)
    all_filings = filings_data.get("filings", [])

    if not all_filings:
        await _update_status(db, ticker, company_id, "error", error="No filings found")
        return {"error": "No filings found", "ticker": ticker}

    # Group by type and take the most recent N per type
    filings_by_type: dict[str, list[dict]] = {}
    for f in all_filings:
        ft = f["filing_type"]
        if ft in filing_types:
            filings_by_type.setdefault(ft, []).append(f)

    # Sort each group by date descending and take top N
    filings_to_index: list[dict] = []
    for ft, filings_list in filings_by_type.items():
        sorted_filings = sorted(
            filings_list,
            key=lambda f: f.get("filing_date", ""),
            reverse=True,
        )
        limit = type_limits.get(ft, 2)  # default 2 if type not in limits
        filings_to_index.extend(sorted_filings[:limit])

    if not filings_to_index:
        await _update_status(db, ticker, company_id, "error",
                             error=f"No {', '.join(filing_types)} filings found")
        return {"error": "No matching filings", "ticker": ticker}

    await _progress(f"Found {len(filings_to_index)} filings to index")

    # Step 3: Delete existing chunks for this ticker (fresh re-index)
    await db.execute(
        text("DELETE FROM filing_chunks WHERE ticker = :ticker"),
        {"ticker": ticker},
    )
    await db.commit()

    # Step 4: Process each filing
    total_chunks = 0
    filings_indexed = 0
    errors: list[str] = []
    latest_filing_date: str | None = None

    for i, filing in enumerate(filings_to_index, 1):
        filing_type = filing["filing_type"]
        filing_date = filing.get("filing_date", "unknown")
        filing_url = filing.get("filing_url", "")

        await _progress(
            f"Processing {filing_type} ({filing_date}) [{i}/{len(filings_to_index)}]"
        )

        if not filing_url:
            errors.append(f"{filing_type} {filing_date}: no URL")
            logger.warning(f"[{ticker}] Skipping {filing_type} {filing_date}: no filing_url")
            continue

        try:
            n_chunks = await _index_single_filing(
                db=db,
                company_id=company_id,
                ticker=ticker,
                filing=filing,
                progress_callback=_progress,
            )
            total_chunks += n_chunks
            filings_indexed += 1

            # Track latest filing date
            if filing_date and (not latest_filing_date or filing_date > latest_filing_date):
                latest_filing_date = filing_date

            # Update status with progress
            await _update_status(
                db, ticker, company_id, "indexing",
                filings_indexed=filings_indexed,
                chunks_total=total_chunks,
            )

        except Exception as e:
            error_msg = f"{filing_type} {filing_date}: {e}"
            errors.append(error_msg)
            logger.error(f"[{ticker}] Failed to index {filing_type} {filing_date}: {e}")
            continue

    # Step 5: Finalize status
    elapsed = time.time() - start_time
    if filings_indexed == 0:
        final_status = "error"
        error_msg = f"All filings failed: {'; '.join(errors)}"
    else:
        final_status = "ready"
        error_msg = "; ".join(errors) if errors else None

    await _update_status(
        db, ticker, company_id, final_status,
        filings_indexed=filings_indexed,
        chunks_total=total_chunks,
        last_filing_date=latest_filing_date,
        error=error_msg,
    )

    summary = {
        "ticker": ticker,
        "status": final_status,
        "filings_indexed": filings_indexed,
        "chunks_total": total_chunks,
        "elapsed_seconds": round(elapsed, 1),
        "errors": errors or None,
    }
    await _progress(
        f"Indexing complete: {filings_indexed} filings, "
        f"{total_chunks} chunks in {elapsed:.1f}s"
    )
    # Clean up ephemeral progress now that indexing is done
    _indexing_progress.pop(ticker, None)
    return summary


async def _index_single_filing(
    db: AsyncSession,
    company_id: int,
    ticker: str,
    filing: dict,
    progress_callback: Callable[[str], Awaitable[None]],
) -> int:
    """Index a single filing: fetch → parse → chunk → topics → embed → insert.

    Returns the number of chunks inserted.
    """
    filing_type = filing["filing_type"]
    filing_url = filing["filing_url"]
    filing_date_str = filing.get("filing_date", "")

    # Resolve filing_id from filings_cache
    filing_id = await _resolve_filing_id(db, company_id, filing)

    # 1. Fetch HTML
    await progress_callback(f"Fetching {filing_type} HTML from EDGAR...")
    html = await fetch_filing_html(filing_url)

    # 2. Parse into sections
    await progress_callback(f"Parsing {filing_type} sections...")
    parsed = parse_filing_html(html, filing_type)

    # 3. Chunk
    chunks = chunk_filing(parsed)
    if not chunks:
        logger.warning(f"[{ticker}] No chunks produced from {filing_type} {filing_date_str}")
        return 0

    # 4. Extract topics per section (deduplicate — only call once per section)
    await progress_callback(f"Extracting topics from {len(parsed.sections)} sections...")
    section_topics: dict[str, list[str]] = {}
    for section in parsed.sections:
        topics = await extract_section_topics(
            section_name=section.section_name,
            section_text=section.text_content,
            filing_type=filing_type,
            ticker=ticker,
        )
        section_topics[section.section_name] = topics

    # 5. Generate embeddings for all chunks in one batch
    await progress_callback(f"Generating embeddings for {len(chunks)} chunks...")
    chunk_texts = [c.text for c in chunks]
    embeddings = await generate_embeddings(chunk_texts)

    # 6. Insert chunks into DB
    await progress_callback(f"Inserting {len(chunks)} chunks into database...")
    # filing_date may already be a date object (from DB) or a string (from API)
    raw_date = filing.get("filing_date")
    if isinstance(raw_date, date):
        filing_date = raw_date
    elif isinstance(raw_date, str) and raw_date:
        filing_date = date.fromisoformat(raw_date)
    else:
        filing_date = date.today()

    for chunk, embedding in zip(chunks, embeddings):
        topics = section_topics.get(chunk.section_name, [])
        # Pass Python lists directly — asyncpg handles list → text[] natively,
        # and our registered pgvector codec handles list → vector serialization.
        await db.execute(
            text("""
                INSERT INTO filing_chunks
                    (company_id, filing_id, ticker, filing_type, filing_date,
                     section_name, category, topics, chunk_index, chunk_text,
                     token_count, is_table, embedding)
                VALUES
                    (:company_id, :filing_id, :ticker, :filing_type, :filing_date,
                     :section_name, :category, :topics,
                     :chunk_index, :chunk_text,
                     :token_count, :is_table, :embedding)
            """),
            {
                "company_id": company_id,
                "filing_id": filing_id,
                "ticker": ticker,
                "filing_type": filing_type,
                "filing_date": filing_date,
                "section_name": chunk.section_name,
                "category": chunk.category,
                "topics": topics,
                "chunk_index": chunk.chunk_index,
                "chunk_text": chunk.text,
                "token_count": chunk.token_count,
                "is_table": chunk.is_table,
                "embedding": embedding,
            },
        )

    await db.commit()
    logger.info(
        f"[{ticker}] Indexed {filing_type} ({filing_date_str}): "
        f"{len(chunks)} chunks, {len(parsed.sections)} sections"
    )
    return len(chunks)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _resolve_filing_id(
    db: AsyncSession, company_id: int, filing: dict
) -> int | None:
    """Look up the filings_cache.id for a filing by accession number."""
    accession = filing.get("accession_number")
    if not accession:
        return None

    result = await db.execute(
        text("""
            SELECT id FROM filings_cache
            WHERE company_id = :company_id AND accession_number = :accession
        """),
        {"company_id": company_id, "accession": accession},
    )
    row = result.scalar_one_or_none()
    return row


async def _update_status(
    db: AsyncSession,
    ticker: str,
    company_id: int | None,
    status: str,
    filings_indexed: int = 0,
    chunks_total: int = 0,
    last_filing_date: str | None = None,
    error: str | None = None,
) -> None:
    """Upsert the filing_index_status row for a ticker."""
    now = datetime.now(timezone.utc)

    await db.execute(
        text("""
            INSERT INTO filing_index_status
                (company_id, ticker, status, filings_indexed, chunks_total,
                 last_indexed_at, last_filing_date, error_message, updated_at)
            VALUES
                (:company_id, :ticker, :status, :filings_indexed, :chunks_total,
                 :last_indexed_at, :last_filing_date, :error_message, :now)
            ON CONFLICT (ticker) DO UPDATE SET
                status = EXCLUDED.status,
                filings_indexed = EXCLUDED.filings_indexed,
                chunks_total = EXCLUDED.chunks_total,
                last_indexed_at = CASE
                    WHEN EXCLUDED.status = 'ready' THEN :now
                    ELSE filing_index_status.last_indexed_at
                END,
                last_filing_date = COALESCE(EXCLUDED.last_filing_date, filing_index_status.last_filing_date),
                error_message = EXCLUDED.error_message,
                updated_at = :now
        """),
        {
            "company_id": company_id,
            "ticker": ticker,
            "status": status,
            "filings_indexed": filings_indexed,
            "chunks_total": chunks_total,
            "last_indexed_at": now if status == "ready" else None,
            "last_filing_date": (
                last_filing_date if isinstance(last_filing_date, date)
                else date.fromisoformat(last_filing_date) if last_filing_date
                else None
            ),
            "error_message": error,
            "now": now,
        },
    )
    await db.commit()
