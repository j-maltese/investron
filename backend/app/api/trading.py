"""Trading API — endpoints for paper trading strategies, positions, orders, and activity.

Phase 1: read-only GET endpoints (strategies, positions, orders, activity, portfolio).
Phase 2 will add POST endpoints for start/stop/pause/reset/config.
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.config import get_settings
from app.models.database import get_db
from app.services import trading_db

logger = logging.getLogger(__name__)
router = APIRouter()


def _serialize_row(row: dict) -> dict:
    """Convert Decimal/datetime types for JSON serialization."""
    from decimal import Decimal
    from datetime import datetime, date

    result = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            result[key] = float(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, date):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Strategy endpoints
# ---------------------------------------------------------------------------

@router.get("/strategies")
async def get_strategies(
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """List all configured trading strategies with current status and P&L."""
    strategies = await trading_db.get_all_strategies(db)
    return {"strategies": [_serialize_row(s) for s in strategies]}


@router.get("/strategies/{strategy_id}")
async def get_strategy(
    strategy_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Get detailed view of a single strategy."""
    strategy = await trading_db.get_strategy(db, strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return _serialize_row(strategy)


@router.post("/strategies/{strategy_id}/start")
async def start_strategy(
    strategy_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Set a strategy to 'running' so the trading engine picks it up."""
    settings = get_settings()
    if not settings.trading_enabled:
        raise HTTPException(status_code=503, detail="Trading engine is disabled (TRADING_ENABLED=false)")
    if not settings.alpaca_api_key:
        raise HTTPException(status_code=503, detail="Alpaca API keys not configured")

    strategy = await trading_db.get_strategy(db, strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    await trading_db.update_strategy(db, strategy_id, status="running", last_error=None, error_count=0)
    await trading_db.log_activity(db, strategy_id, "strategy_start", f"Strategy '{strategy['display_name']}' started")

    return {"message": f"Strategy {strategy_id} started", "status": "running"}


@router.post("/strategies/{strategy_id}/stop")
async def stop_strategy(
    strategy_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Stop a strategy — no new trades, but existing positions remain."""
    strategy = await trading_db.get_strategy(db, strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    await trading_db.update_strategy(db, strategy_id, status="stopped")
    await trading_db.log_activity(db, strategy_id, "strategy_stop", f"Strategy '{strategy['display_name']}' stopped")

    return {"message": f"Strategy {strategy_id} stopped", "status": "stopped"}


@router.post("/strategies/{strategy_id}/pause")
async def pause_strategy(
    strategy_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Pause a strategy — monitors positions but opens no new trades."""
    strategy = await trading_db.get_strategy(db, strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    await trading_db.update_strategy(db, strategy_id, status="paused")
    await trading_db.log_activity(db, strategy_id, "strategy_stop", f"Strategy '{strategy['display_name']}' paused")

    return {"message": f"Strategy {strategy_id} paused", "status": "paused"}


@router.patch("/strategies/{strategy_id}/config")
async def update_strategy_config(
    strategy_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Update a strategy's JSONB config."""
    strategy = await trading_db.get_strategy(db, strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    new_config = body.get("config")
    if not new_config or not isinstance(new_config, dict):
        raise HTTPException(status_code=400, detail="config must be a non-empty object")

    # Merge new config with existing (allows partial updates)
    merged = {**strategy.get("config", {}), **new_config}
    await trading_db.update_strategy(db, strategy_id, config=merged)
    await trading_db.log_activity(
        db, strategy_id, "config_update",
        f"Strategy config updated", details={"updated_keys": list(new_config.keys())}
    )

    updated = await trading_db.get_strategy(db, strategy_id)
    return _serialize_row(updated)


@router.post("/strategies/{strategy_id}/reset")
async def reset_strategy(
    strategy_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Reset a strategy to initial capital. Closes all positions."""
    strategy = await trading_db.get_strategy(db, strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    initial = float(strategy["initial_capital"])
    await trading_db.update_strategy(
        db, strategy_id,
        status="stopped",
        current_cash=initial,
        current_portfolio_value=0,
        total_pnl=0,
        total_pnl_pct=0,
        realized_pnl=0,
        unrealized_pnl=0,
        last_error=None,
        error_count=0,
    )
    await trading_db.log_activity(
        db, strategy_id, "strategy_reset",
        f"Strategy reset to ${initial:.2f} initial capital"
    )

    return {"message": f"Strategy {strategy_id} reset to ${initial:.2f}"}


# ---------------------------------------------------------------------------
# Position endpoints
# ---------------------------------------------------------------------------

@router.get("/positions")
async def get_positions(
    strategy_id: str | None = Query(None),
    status: str | None = Query(None, pattern="^(open|closed|assigned|expired)$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Paginated positions, filterable by strategy and status."""
    positions, total = await trading_db.get_positions(db, strategy_id, status, limit, offset)
    return {
        "positions": [_serialize_row(p) for p in positions],
        "total_count": total,
    }


# ---------------------------------------------------------------------------
# Order endpoints
# ---------------------------------------------------------------------------

@router.get("/orders")
async def get_orders(
    strategy_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Paginated order history, newest first."""
    orders, total = await trading_db.get_orders(db, strategy_id, limit, offset)
    return {
        "orders": [_serialize_row(o) for o in orders],
        "total_count": total,
    }


# ---------------------------------------------------------------------------
# Activity log endpoints
# ---------------------------------------------------------------------------

@router.get("/activity")
async def get_activity(
    strategy_id: str | None = Query(None),
    event_type: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Activity log feed, newest first. Supports filtering by event type and date range."""
    events, total = await trading_db.get_activity_log(
        db, strategy_id, event_type=event_type,
        date_from=date_from, date_to=date_to,
        limit=limit, offset=offset,
    )
    return {
        "events": [_serialize_row(e) for e in events],
        "total_count": total,
    }


# ---------------------------------------------------------------------------
# Portfolio endpoints
# ---------------------------------------------------------------------------

@router.get("/portfolio")
async def get_portfolio(
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Aggregated portfolio view across all strategies."""
    summary = await trading_db.get_portfolio_summary(db)
    summary["strategies"] = [_serialize_row(s) for s in summary["strategies"]]
    return summary
