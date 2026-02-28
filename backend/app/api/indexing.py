"""API endpoints for triggering and managing SEC filing indexing.

POST   /api/ai/filings/{ticker}/index   — trigger indexing (background task)
GET    /api/ai/filings/{ticker}/status   — get indexing status
DELETE /api/ai/filings/{ticker}/index    — delete index and reset
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import text

from app.config import get_settings
from app.models.database import get_db
from app.models import database as _db
from app.services.filing_indexer import (
    index_company_filings,
    get_index_status,
    get_indexing_progress,
    delete_company_index,
)
from app.auth.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


async def _run_indexing_background(ticker: str):
    """Background task wrapper — creates its own DB session."""
    if _db.async_session_factory is None:
        logger.error("Cannot run indexing: database not configured")
        return

    async with _db.async_session_factory() as db:
        try:
            result = await index_company_filings(db, ticker)
            logger.info(f"Background indexing for {ticker} completed: {result}")
        except Exception as e:
            logger.error(f"Background indexing for {ticker} failed: {e}")


@router.post("/{ticker}/index")
async def trigger_indexing(
    ticker: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Trigger filing indexing for a company.

    Runs in the background and returns immediately.  Poll the status endpoint
    to track progress.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="AI features not configured — set OPENAI_API_KEY.",
        )

    ticker_upper = ticker.upper()

    # Check if already indexing
    status = await get_index_status(db, ticker_upper)
    if status and status["status"] == "indexing":
        return {
            "message": "Indexing already in progress",
            "status": status,
        }

    # Write 'indexing' status immediately so the first poll finds it
    # (avoids race condition where the background task hasn't started yet)
    await db.execute(
        text("""
            INSERT INTO filing_index_status (ticker, status, filings_indexed, chunks_total, updated_at)
            VALUES (:ticker, 'indexing', 0, 0, NOW())
            ON CONFLICT (ticker) DO UPDATE SET
                status = 'indexing', filings_indexed = 0, chunks_total = 0,
                error_message = NULL, updated_at = NOW()
        """),
        {"ticker": ticker_upper},
    )
    await db.commit()

    # Kick off in background
    background_tasks.add_task(_run_indexing_background, ticker_upper)

    return {
        "message": f"Indexing started for {ticker_upper}",
        "ticker": ticker_upper,
    }


@router.get("/{ticker}/status")
async def check_status(
    ticker: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get the current filing index status for a company."""
    status = await get_index_status(db, ticker)
    if not status:
        return {
            "ticker": ticker.upper(),
            "status": "not_indexed",
            "filings_indexed": 0,
            "chunks_total": 0,
        }

    # Include live progress message from in-memory tracker during indexing
    if status["status"] == "indexing":
        progress = get_indexing_progress(ticker)
        if progress:
            status["progress_message"] = progress

    # Include filing type breakdown when indexed (e.g. {"10-K": 3, "10-Q": 5, "8-K": 7})
    if status["status"] == "ready":
        breakdown = await db.execute(
            text("""
                SELECT filing_type, COUNT(*) AS chunk_count,
                       COUNT(DISTINCT filing_date) AS filing_count
                FROM filing_chunks
                WHERE ticker = :ticker
                GROUP BY filing_type
                ORDER BY filing_type
            """),
            {"ticker": ticker.upper()},
        )
        status["filing_type_breakdown"] = {
            row.filing_type: row.filing_count
            for row in breakdown
        }

    return status


@router.delete("/{ticker}/index")
async def remove_index(
    ticker: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Delete all indexed filing chunks and reset status for a company."""
    await delete_company_index(db, ticker)
    return {"message": f"Filing index deleted for {ticker.upper()}"}
