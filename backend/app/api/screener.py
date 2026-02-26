"""Value Screener API — serves pre-computed screening results from the background scanner.

All endpoints are public (no auth required) since screener data is derived from
public market data and contains no user-specific information. This also means the
scanner can populate data without any user being logged in.

Endpoints:
  GET /results  — Paginated, sortable, filterable ranked stock list
  GET /status   — Scanner progress and last-updated timestamp
  GET /sectors  — Distinct sectors for the filter dropdown
  GET /indices  — Distinct indices for the filter dropdown
"""

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db

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
    min_score: float | None = Query(None, ge=0, le=100),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Get ranked screener results with optional filtering and sorting.

    Query params:
      sort_by: column to sort (validated against allowlist)
      sort_order: "asc" or "desc"
      sector: filter by GICS sector name
      index: filter by index membership (e.g., "S&P 500", "Dow 30")
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

    if min_score is not None:
        where_parts.append("s.composite_score >= :min_score")
        params["min_score"] = min_score

    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    # NULLs should sort last for DESC (best first), first for ASC
    null_order = "NULLS LAST" if sort_order == "desc" else "NULLS FIRST"

    # Fetch results — sort_by is validated against ALLOWED_SORT_COLUMNS above
    result = await db.execute(
        text(f"""
            SELECT
                s.ticker, s.company_name, s.sector, s.industry,
                s.price, s.market_cap, s.pe_ratio, s.pb_ratio,
                s.roe, s.debt_to_equity, s.dividend_yield,
                s.graham_number, s.margin_of_safety,
                s.fcf_yield, s.earnings_yield,
                s.composite_score, s.rank,
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
