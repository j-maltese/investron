"""Trading database helpers — CRUD for strategies, positions, orders, and activity log.

Follows the same patterns as scanner.py: raw SQL via text(), parameterized queries,
dynamic SET building for updates. All functions receive an AsyncSession.
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

async def get_strategy(db: AsyncSession, strategy_id: str) -> dict | None:
    """Fetch a single strategy row by ID."""
    result = await db.execute(
        text("SELECT * FROM trading_strategies WHERE id = :id"),
        {"id": strategy_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def get_all_strategies(db: AsyncSession) -> list[dict]:
    """Fetch all configured strategies."""
    result = await db.execute(
        text("SELECT * FROM trading_strategies ORDER BY created_at")
    )
    return [dict(row) for row in result.mappings().all()]


async def update_strategy(db: AsyncSession, strategy_id: str, **kwargs) -> None:
    """Update arbitrary fields on a strategy row.

    Keys come from our code (not user input), so dynamic SQL is safe here.
    Values are parameterized.
    """
    if not kwargs:
        return

    set_parts = []
    params = {"id": strategy_id, "now": datetime.now(timezone.utc)}
    for key, value in kwargs.items():
        if key == "config" and isinstance(value, dict):
            set_parts.append(f"{key} = CAST(:{key} AS jsonb)")
            params[key] = json.dumps(value)
        else:
            set_parts.append(f"{key} = :{key}")
            params[key] = value
    set_parts.append("updated_at = :now")

    await db.execute(
        text(f"UPDATE trading_strategies SET {', '.join(set_parts)} WHERE id = :id"),
        params,
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

async def get_open_positions(db: AsyncSession, strategy_id: str | None = None) -> list[dict]:
    """Fetch open positions, optionally filtered by strategy."""
    if strategy_id:
        result = await db.execute(
            text("SELECT * FROM trading_positions WHERE status = 'open' AND strategy_id = :sid ORDER BY opened_at DESC"),
            {"sid": strategy_id},
        )
    else:
        result = await db.execute(
            text("SELECT * FROM trading_positions WHERE status = 'open' ORDER BY opened_at DESC")
        )
    return [dict(row) for row in result.mappings().all()]


async def get_positions(
    db: AsyncSession,
    strategy_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Fetch paginated positions with optional filters. Returns (rows, total_count)."""
    where_parts = []
    params: dict = {"limit": limit, "offset": offset}

    if strategy_id:
        where_parts.append("strategy_id = :sid")
        params["sid"] = strategy_id
    if status:
        where_parts.append("status = :status")
        params["status"] = status

    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    # Count
    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM trading_positions {where_clause}"), params
    )
    total = count_result.scalar() or 0

    # Rows — join screener_scores to get company_name for tooltip display
    result = await db.execute(
        text(f"""
            SELECT p.*, ss.company_name
            FROM trading_positions p
            LEFT JOIN screener_scores ss ON ss.ticker = p.ticker
            {where_clause}
            ORDER BY p.opened_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    return [dict(row) for row in result.mappings().all()], total


async def insert_position(db: AsyncSession, data: dict) -> int:
    """Insert a new position and return its ID."""
    result = await db.execute(
        text("""
            INSERT INTO trading_positions (
                strategy_id, ticker, asset_type, quantity, avg_entry_price,
                option_symbol, option_type, strike_price, expiration_date, contracts,
                wheel_phase, cost_basis, status
            ) VALUES (
                :strategy_id, :ticker, :asset_type, :quantity, :avg_entry_price,
                :option_symbol, :option_type, :strike_price, :expiration_date, :contracts,
                :wheel_phase, :cost_basis, :status
            ) RETURNING id
        """),
        {
            "strategy_id": data.get("strategy_id"),
            "ticker": data.get("ticker"),
            "asset_type": data.get("asset_type", "stock"),
            "quantity": data.get("quantity", 0),
            "avg_entry_price": data.get("avg_entry_price"),
            "option_symbol": data.get("option_symbol"),
            "option_type": data.get("option_type"),
            "strike_price": data.get("strike_price"),
            "expiration_date": data.get("expiration_date"),
            "contracts": data.get("contracts"),
            "wheel_phase": data.get("wheel_phase"),
            "cost_basis": data.get("cost_basis"),
            "status": data.get("status", "open"),
        },
    )
    await db.commit()
    return result.scalar()


async def close_position(
    db: AsyncSession,
    position_id: int,
    close_reason: str,
    realized_pnl: float = 0,
) -> None:
    """Mark a position as closed with reason and realized P&L."""
    await db.execute(
        text("""
            UPDATE trading_positions
            SET status = 'closed', close_reason = :reason, realized_pnl = :pnl,
                closed_at = :now, updated_at = :now
            WHERE id = :id
        """),
        {
            "id": position_id,
            "reason": close_reason,
            "pnl": realized_pnl,
            "now": datetime.now(timezone.utc),
        },
    )
    await db.commit()


async def update_position(db: AsyncSession, position_id: int, **kwargs) -> None:
    """Update arbitrary fields on a position."""
    if not kwargs:
        return

    set_parts = []
    params = {"id": position_id, "now": datetime.now(timezone.utc)}
    for key, value in kwargs.items():
        set_parts.append(f"{key} = :{key}")
        params[key] = value
    set_parts.append("updated_at = :now")

    await db.execute(
        text(f"UPDATE trading_positions SET {', '.join(set_parts)} WHERE id = :id"),
        params,
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

async def insert_order(db: AsyncSession, data: dict) -> int:
    """Insert a new order and return its ID."""
    ai_signal = data.get("ai_signal")
    result = await db.execute(
        text("""
            INSERT INTO trading_orders (
                strategy_id, position_id, alpaca_order_id, ticker, asset_type,
                side, order_type, time_in_force, quantity, limit_price, stop_price,
                option_symbol, option_type, strike_price, expiration_date, contracts,
                status, reason, ai_signal
            ) VALUES (
                :strategy_id, :position_id, :alpaca_order_id, :ticker, :asset_type,
                :side, :order_type, :time_in_force, :quantity, :limit_price, :stop_price,
                :option_symbol, :option_type, :strike_price, :expiration_date, :contracts,
                :status, :reason, CAST(:ai_signal AS jsonb)
            ) RETURNING id
        """),
        {
            "strategy_id": data.get("strategy_id"),
            "position_id": data.get("position_id"),
            "alpaca_order_id": data.get("alpaca_order_id"),
            "ticker": data.get("ticker"),
            "asset_type": data.get("asset_type", "stock"),
            "side": data.get("side"),
            "order_type": data.get("order_type", "market"),
            "time_in_force": data.get("time_in_force", "day"),
            "quantity": data.get("quantity"),
            "limit_price": data.get("limit_price"),
            "stop_price": data.get("stop_price"),
            "option_symbol": data.get("option_symbol"),
            "option_type": data.get("option_type"),
            "strike_price": data.get("strike_price"),
            "expiration_date": data.get("expiration_date"),
            "contracts": data.get("contracts"),
            "status": data.get("status", "pending"),
            "reason": data.get("reason"),
            "ai_signal": json.dumps(ai_signal) if ai_signal else None,
        },
    )
    await db.commit()
    return result.scalar()


async def update_order_status(
    db: AsyncSession,
    order_id: int,
    status: str,
    filled_qty: float | None = None,
    filled_avg_price: float | None = None,
    filled_at: datetime | None = None,
) -> None:
    """Update an order's status and fill information."""
    params: dict = {
        "id": order_id,
        "status": status,
        "now": datetime.now(timezone.utc),
    }
    set_parts = ["status = :status", "updated_at = :now"]

    if filled_qty is not None:
        set_parts.append("filled_quantity = :fq")
        params["fq"] = filled_qty
    if filled_avg_price is not None:
        set_parts.append("filled_avg_price = :fap")
        params["fap"] = filled_avg_price
    if filled_at is not None:
        set_parts.append("filled_at = :fat")
        params["fat"] = filled_at

    await db.execute(
        text(f"UPDATE trading_orders SET {', '.join(set_parts)} WHERE id = :id"),
        params,
    )
    await db.commit()


async def get_orders(
    db: AsyncSession,
    strategy_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Fetch paginated orders, newest first."""
    where_parts = []
    params: dict = {"limit": limit, "offset": offset}

    if strategy_id:
        where_parts.append("strategy_id = :sid")
        params["sid"] = strategy_id

    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM trading_orders {where_clause}"), params
    )
    total = count_result.scalar() or 0

    # Join screener_scores to get company_name for tooltip display
    result = await db.execute(
        text(f"""
            SELECT o.*, ss.company_name
            FROM trading_orders o
            LEFT JOIN screener_scores ss ON ss.ticker = o.ticker
            {where_clause}
            ORDER BY o.submitted_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    return [dict(row) for row in result.mappings().all()], total


# ---------------------------------------------------------------------------
# Activity Log
# ---------------------------------------------------------------------------

async def log_activity(
    db: AsyncSession,
    strategy_id: str,
    event_type: str,
    message: str,
    ticker: str | None = None,
    details: dict | None = None,
) -> None:
    """Append an event to the activity log."""
    await db.execute(
        text("""
            INSERT INTO trading_activity_log (strategy_id, event_type, ticker, message, details)
            VALUES (:sid, :event, :ticker, :message, CAST(:details AS jsonb))
        """),
        {
            "sid": strategy_id,
            "event": event_type,
            "ticker": ticker,
            "message": message,
            "details": json.dumps(details or {}, default=str),
        },
    )
    await db.commit()


async def get_activity_log(
    db: AsyncSession,
    strategy_id: str | None = None,
    event_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Fetch paginated activity log, newest first.

    Supports filtering by:
      - strategy_id: single strategy
      - event_type: exact match (e.g., 'order_filled') or prefix match for
        category filters (e.g., 'blocked' matches all blocked_* events)
      - date_from / date_to: ISO date strings for date range filtering
    """
    where_parts = []
    params: dict = {"limit": limit, "offset": offset}

    if strategy_id:
        where_parts.append("strategy_id = :sid")
        params["sid"] = strategy_id

    if event_type:
        # Support prefix matching: "blocked" matches "blocked_insufficient_cash", etc.
        # This enables the frontend's category filter pills.
        if event_type in ("blocked", "order", "option", "capital"):
            where_parts.append("event_type LIKE :etype")
            params["etype"] = f"{event_type}%"
        else:
            where_parts.append("event_type = :etype")
            params["etype"] = event_type

    if date_from:
        where_parts.append("created_at >= :date_from::timestamptz")
        params["date_from"] = date_from

    if date_to:
        # ISO datetime strings (contain 'T') use exact comparison;
        # plain date strings get end-of-day inclusion for backward compat.
        if 'T' in date_to:
            where_parts.append("created_at <= :date_to::timestamptz")
        else:
            where_parts.append("created_at < (:date_to::date + interval '1 day')")
        params["date_to"] = date_to

    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM trading_activity_log {where_clause}"), params
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        text(f"SELECT * FROM trading_activity_log {where_clause} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
        params,
    )
    return [dict(row) for row in result.mappings().all()], total


# ---------------------------------------------------------------------------
# Collateral helpers
# ---------------------------------------------------------------------------

async def get_put_collateral(db: AsyncSession, strategy_id: str) -> float:
    """Sum cash-secured collateral for open sold puts (strike × 100 × contracts).

    This is money reserved for potential assignment — it's not a loss, just
    committed capital.  The circuit breaker adds this back so drawdown
    reflects real risk, not the collateral set-aside.
    """
    result = await db.execute(
        text("""
            SELECT COALESCE(SUM(
                COALESCE(strike_price, 0) * 100 * COALESCE(contracts, 1)
            ), 0) as total_collateral
            FROM trading_positions
            WHERE strategy_id = :sid
              AND status = 'open'
              AND wheel_phase = 'selling_puts'
        """),
        {"sid": strategy_id},
    )
    row = result.mappings().first()
    return float(row["total_collateral"]) if row else 0


# ---------------------------------------------------------------------------
# Portfolio Aggregation
# ---------------------------------------------------------------------------

async def get_portfolio_summary(db: AsyncSession) -> dict:
    """Compute aggregated portfolio metrics across all strategies."""
    strategies = await get_all_strategies(db)

    total_initial = sum(float(s.get("initial_capital", 0)) for s in strategies)
    total_cash = sum(float(s.get("current_cash", 0)) for s in strategies)
    total_portfolio = sum(float(s.get("current_portfolio_value", 0)) for s in strategies)
    total_value = total_cash + total_portfolio
    total_pnl = total_value - total_initial
    total_pnl_pct = (total_pnl / total_initial * 100) if total_initial > 0 else 0

    return {
        "total_value": total_value,
        "total_cash": total_cash,
        "total_portfolio_value": total_portfolio,
        "total_initial_capital": total_initial,
        "total_pnl": total_pnl,
        "total_pnl_pct": round(total_pnl_pct, 4),
        "strategies": strategies,
    }


async def sync_strategy_pnl(db: AsyncSession, strategy_id: str) -> None:
    """Recalculate a strategy's portfolio value and P&L from its positions.

    Recomputes current_portfolio_value as the sum of current_value for all
    open positions, then derives total P&L from cash + portfolio - initial.
    This ensures the strategy card always reflects live position values
    rather than stale fill-time snapshots.
    """
    result = await db.execute(
        text("""
            SELECT
                COALESCE(SUM(realized_pnl), 0) as total_realized,
                COALESCE(SUM(CASE WHEN status = 'open' THEN unrealized_pnl ELSE 0 END), 0) as total_unrealized,
                COALESCE(SUM(CASE WHEN status = 'open' THEN current_value ELSE 0 END), 0) as total_current_value
            FROM trading_positions
            WHERE strategy_id = :sid
        """),
        {"sid": strategy_id},
    )
    row = result.mappings().first()
    realized = float(row["total_realized"]) if row else 0
    unrealized = float(row["total_unrealized"]) if row else 0
    portfolio_value = float(row["total_current_value"]) if row else 0

    strategy = await get_strategy(db, strategy_id)
    if not strategy:
        return

    initial = float(strategy["initial_capital"])
    cash = float(strategy["current_cash"])
    total_pnl = (cash + portfolio_value) - initial
    total_pnl_pct = (total_pnl / initial * 100) if initial > 0 else 0

    await update_strategy(
        db, strategy_id,
        current_portfolio_value=round(portfolio_value, 2),
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        total_pnl=round(total_pnl, 2),
        total_pnl_pct=round(total_pnl_pct, 4),
    )
