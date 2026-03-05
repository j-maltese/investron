"""Value Screener API — serves pre-computed screening results from the background scanner.

All endpoints are public (no auth required) since screener data is derived from
public market data and contains no user-specific information. This also means the
scanner can populate data without any user being logged in.

Endpoints:
  GET  /results  — Paginated, sortable, filterable ranked stock list
  GET  /status   — Scanner progress and last-updated timestamp
  GET  /sectors  — Distinct sectors for the filter dropdown
  GET  /indices  — Distinct indices for the filter dropdown
  POST /trigger  — Manually start a full scan (if not already running)
"""

import asyncio
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.services.scanner import run_full_scan

router = APIRouter()

# Columns that the frontend is allowed to sort by.
# This allowlist prevents SQL injection via the sort_by parameter.
ALLOWED_SORT_COLUMNS = {
    "composite_score",
    "margin_of_safety",
    "pe_ratio",
    "pb_ratio",
    "dividend_yield",
    "roe",
    "fcf_yield",
    "earnings_yield",
    "price",
    "market_cap",
}


@router.get("/results")
async def get_screener_results(
    sort_by: str = Query("composite_score"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    sector: str | None = Query(None),
    index: str | None = Query(None),
    search: str | None = Query(None, min_length=1, max_length=100),
    min_score: float | None = Query(None, ge=0, le=100),
    limit: int = Query(50, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Get ranked screener results with optional filtering and sorting.

    Query params:
      sort_by: column to sort (validated against allowlist)
      sort_order: "asc" or "desc"
      sector: filter by GICS sector name
      index: filter by index membership (e.g., "S&P 500", "Dow 30")
      search: filter by ticker prefix or company name substring (case-insensitive)
      min_score: minimum composite score threshold
      limit/offset: pagination
    """
    # Validate sort column against allowlist (defense-in-depth beyond Query pattern)
    if sort_by not in ALLOWED_SORT_COLUMNS:
        sort_by = "composite_score"

    # Build dynamic WHERE clause from filters
    where_parts = []
    params: dict = {"limit": limit, "offset": offset}

    if sector:
        where_parts.append("s.sector = :sector")
        params["sector"] = sector

    if index:
        # JSONB @> (contains) operator: filter rows whose indices array contains this index
        where_parts.append("s.indices @> CAST(:index_filter AS jsonb)")
        params["index_filter"] = json.dumps([index])

    if search:
        # Match ticker prefix OR company name substring (case-insensitive)
        where_parts.append("(s.ticker ILIKE :search_prefix OR s.company_name ILIKE :search_substring)")
        params["search_prefix"] = f"{search}%"
        params["search_substring"] = f"%{search}%"

    if min_score is not None:
        where_parts.append("s.composite_score >= :min_score")
        params["min_score"] = min_score

    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    # NULLs should sort last for DESC (best first), first for ASC
    null_order = "NULLS LAST" if sort_order == "desc" else "NULLS FIRST"

    # Compute rank dynamically via ROW_NUMBER() so it always reflects:
    # - The current scores (never stale from a previous/interrupted scan)
    # - The active filter set (rank within "Dow 30" or "Energy", not global)
    result = await db.execute(
        text(f"""
            SELECT
                s.ticker, s.company_name, s.sector, s.industry,
                s.price, s.market_cap, s.pe_ratio, s.pb_ratio,
                s.roe, s.debt_to_equity, s.dividend_yield,
                s.graham_number, s.margin_of_safety,
                s.fcf_yield, s.earnings_yield,
                s.composite_score,
                ROW_NUMBER() OVER (ORDER BY s.composite_score DESC NULLS LAST) AS rank,
                s.warnings, s.indices, s.scored_at
            FROM screener_scores s
            {where_clause}
            ORDER BY s.{sort_by} {sort_order} {null_order}
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = [dict(r) for r in result.mappings().all()]

    # Total count for pagination (uses same filters but no limit/offset)
    count_result = await db.execute(
        text(f"SELECT COUNT(*) as cnt FROM screener_scores s {where_clause}"),
        {k: v for k, v in params.items() if k not in ("limit", "offset")},
    )
    total = count_result.scalar()

    # Last scan completion timestamp from scanner_status
    status_result = await db.execute(
        text("SELECT last_full_scan_completed_at FROM scanner_status WHERE id = 1")
    )
    status_row = status_result.mappings().first()
    last_scan = status_row["last_full_scan_completed_at"] if status_row else None

    return {
        "results": rows,
        "total_count": total,
        "last_scan_completed_at": last_scan,
    }


@router.get("/status")
async def get_scanner_status(db: AsyncSession = Depends(get_db)):
    """Get current scanner status — running state, progress, last completion time.

    Used by the frontend to show "Scanning... (150/2000)" and "Last updated: ..." indicators.
    """
    result = await db.execute(
        text("SELECT * FROM scanner_status WHERE id = 1")
    )
    row = result.mappings().first()
    if not row:
        return {
            "is_running": False,
            "tickers_scanned": 0,
            "tickers_total": 0,
        }
    return dict(row)


@router.get("/sectors")
async def get_sectors(db: AsyncSession = Depends(get_db)):
    """Get distinct sectors present in screener results — populates the filter dropdown."""
    result = await db.execute(
        text("SELECT DISTINCT sector FROM screener_scores WHERE sector IS NOT NULL ORDER BY sector")
    )
    sectors = [row["sector"] for row in result.mappings().all()]
    return {"sectors": sectors}


@router.get("/indices")
async def get_indices(db: AsyncSession = Depends(get_db)):
    """Get distinct index names from all scored stocks — populates the index filter dropdown.

    Uses jsonb_array_elements_text() to unnest the JSONB indices arrays and
    return a flat, sorted list of unique index names.
    """
    result = await db.execute(
        text("""
            SELECT DISTINCT idx
            FROM screener_scores, jsonb_array_elements_text(indices) AS idx
            ORDER BY idx
        """)
    )
    indices = [row["idx"] for row in result.mappings().all()]
    return {"indices": indices}


@router.post("/trigger")
async def trigger_scan(db: AsyncSession = Depends(get_db)):
    """Manually start a full scan — used to re-run the screener on demand.

    Returns 409 if a scan is already in progress (prevents stacking scans).
    The scan runs as a background task; poll GET /status for progress.
    """
    result = await db.execute(
        text("SELECT is_running FROM scanner_status WHERE id = 1")
    )
    row = result.mappings().first()
    if row and row["is_running"]:
        return JSONResponse(status_code=409, content={"message": "Scan already running"})

    # Fire-and-forget: launch scan as a background asyncio task
    asyncio.create_task(run_full_scan())
    return {"message": "Scan started"}
