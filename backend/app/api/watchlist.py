import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.database import get_db
from app.models.schemas import WatchlistItemCreate, WatchlistItemUpdate
from app.auth.dependencies import get_current_user
from app.services import yfinance_svc

router = APIRouter()

PRICE_FETCH_TIMEOUT = 8  # seconds per ticker

# Email → display name mapping for the two-user household
USER_DISPLAY_NAMES = {
    "mmalt01@gmail.com": "Mark",
    "john.maltese@gmail.com": "John",
}


async def _fetch_price(item: dict) -> None:
    """Enrich a watchlist item with its current price, with timeout."""
    try:
        info = await asyncio.wait_for(
            yfinance_svc.get_stock_info(item["ticker"]),
            timeout=PRICE_FETCH_TIMEOUT,
        )
        if info:
            item["current_price"] = info.get("price")
            item["price_change_pct"] = None
    except (asyncio.TimeoutError, Exception):
        item["current_price"] = None
        item["price_change_pct"] = None


def _resolve_view_email(view: str | None) -> str | None:
    """Convert a view filter name to an email address, or None for 'all'."""
    if not view or view == "all":
        return None
    lookup = {name.lower(): email for email, name in USER_DISPLAY_NAMES.items()}
    return lookup.get(view.lower())


@router.get("")
async def get_watchlist(
    view: Optional[str] = Query(None, description="Filter: 'all', 'john', or 'mark'"),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get watchlist items, optionally filtered by owner."""
    filter_email = _resolve_view_email(view)

    if filter_email:
        # Specific user's watchlist
        result = await db.execute(
            text("""
                SELECT w.id, w.ticker, c.name as company_name, w.notes, w.target_price, w.added_at, w.user_email
                FROM watchlist_items w
                LEFT JOIN companies c ON w.company_id = c.id
                WHERE w.user_email = :email
                ORDER BY w.added_at DESC
            """),
            {"email": filter_email},
        )
    else:
        # All users' watchlists (default when no view specified, or view=all)
        result = await db.execute(
            text("""
                SELECT w.id, w.ticker, c.name as company_name, w.notes, w.target_price, w.added_at, w.user_email
                FROM watchlist_items w
                LEFT JOIN companies c ON w.company_id = c.id
                ORDER BY w.added_at DESC
            """)
        )

    items = [dict(row) for row in result.mappings().all()]

    # Add display name for each item so the frontend can show owner badges
    for item in items:
        item["owner_name"] = USER_DISPLAY_NAMES.get(item.get("user_email"), "Unknown")

    # Enrich with current prices concurrently
    await asyncio.gather(*[_fetch_price(item) for item in items])

    return {"items": items, "current_user_email": user.get("email")}


@router.post("")
async def add_to_watchlist(
    item: WatchlistItemCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Add a ticker to the authenticated user's watchlist."""
    from app.services.company import get_or_create_company
    company = await get_or_create_company(db, item.ticker)
    company_id = company["id"] if company else None
    user_email = user.get("email")

    result = await db.execute(
        text("""
            INSERT INTO watchlist_items (ticker, company_id, user_email, notes, target_price)
            VALUES (:ticker, :company_id, :user_email, :notes, :target_price)
            ON CONFLICT (ticker, user_email) DO UPDATE SET
                notes = COALESCE(EXCLUDED.notes, watchlist_items.notes),
                target_price = COALESCE(EXCLUDED.target_price, watchlist_items.target_price)
            RETURNING id, ticker, notes, target_price, added_at, user_email
        """),
        {
            "ticker": item.ticker.upper(),
            "company_id": company_id,
            "user_email": user_email,
            "notes": item.notes,
            "target_price": item.target_price,
        },
    )
    await db.commit()
    return dict(result.mappings().first())


@router.delete("/{ticker}")
async def remove_from_watchlist(
    ticker: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Remove a ticker from the authenticated user's watchlist only."""
    result = await db.execute(
        text("DELETE FROM watchlist_items WHERE ticker = :ticker AND user_email = :email RETURNING id"),
        {"ticker": ticker.upper(), "email": user.get("email")},
    )
    await db.commit()
    deleted = result.mappings().first()
    if not deleted:
        raise HTTPException(status_code=404, detail=f"{ticker} not found in your watchlist")
    return {"message": f"Removed {ticker} from watchlist"}


@router.patch("/{ticker}")
async def update_watchlist_item(
    ticker: str,
    update: WatchlistItemUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Update notes or target price for a watchlist item — own items only."""
    updates = {}
    set_clauses = []
    if update.notes is not None:
        set_clauses.append("notes = :notes")
        updates["notes"] = update.notes
    if update.target_price is not None:
        set_clauses.append("target_price = :target_price")
        updates["target_price"] = update.target_price

    if not set_clauses:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates["ticker"] = ticker.upper()
    updates["email"] = user.get("email")
    result = await db.execute(
        text(f"UPDATE watchlist_items SET {', '.join(set_clauses)} WHERE ticker = :ticker AND user_email = :email RETURNING id, ticker, notes, target_price"),
        updates,
    )
    await db.commit()
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"{ticker} not found in your watchlist")
    return dict(row)


@router.get("/notes")
async def get_all_notes(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get all ticker notes grouped by ticker. Notes are decoupled from
    watchlist items — they follow the ticker, not the watchlist entry,
    and track who wrote each note."""
    result = await db.execute(
        text("""
            SELECT n.id, n.ticker, n.notes, n.user_email, n.created_at, n.updated_at
            FROM ticker_notes n
            ORDER BY n.ticker, n.created_at
        """)
    )
    rows = [dict(r) for r in result.mappings().all()]

    # Add display names and group by ticker
    notes_by_ticker: dict[str, list] = {}
    for row in rows:
        row["author_name"] = USER_DISPLAY_NAMES.get(row.get("user_email"), "Unknown")
        notes_by_ticker.setdefault(row["ticker"], []).append(row)

    return {"notes": notes_by_ticker}


@router.post("/notes")
async def create_note(
    update: WatchlistItemUpdate,
    ticker: str = Query(..., description="Ticker to add a note for"),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Create or update a note for any ticker — attributed to the current user.
    Uses upsert so each user can only have one note per ticker."""
    if not update.notes:
        raise HTTPException(status_code=400, detail="No notes provided")

    user_email = user.get("email")
    result = await db.execute(
        text("""
            INSERT INTO ticker_notes (ticker, user_email, notes)
            VALUES (:ticker, :email, :notes)
            ON CONFLICT (ticker, user_email) DO UPDATE SET
                notes = EXCLUDED.notes,
                updated_at = NOW()
            RETURNING id, ticker, notes, user_email, created_at, updated_at
        """),
        {"ticker": ticker.upper(), "email": user_email, "notes": update.notes},
    )
    await db.commit()
    row = result.mappings().first()
    return dict(row)


@router.patch("/notes/{note_id}")
async def update_note_by_id(
    note_id: int,
    update: WatchlistItemUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Update a ticker note by ID — any authenticated user can edit any note."""
    if update.notes is None:
        raise HTTPException(status_code=400, detail="No notes provided")

    result = await db.execute(
        text("""
            UPDATE ticker_notes SET notes = :notes, updated_at = NOW()
            WHERE id = :id
            RETURNING id, ticker, notes, user_email, created_at, updated_at
        """),
        {"notes": update.notes, "id": note_id},
    )
    await db.commit()
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Note not found")
    return dict(row)


@router.delete("/notes/{note_id}")
async def delete_note(
    note_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Delete a ticker note by ID."""
    result = await db.execute(
        text("DELETE FROM ticker_notes WHERE id = :id RETURNING id"),
        {"id": note_id},
    )
    await db.commit()
    if not result.mappings().first():
        raise HTTPException(status_code=404, detail="Note not found")
    return {"message": "Note deleted"}


@router.get("/alerts")
async def get_alerts(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get alerts for the authenticated user's watchlist items near their target price."""
    result = await db.execute(
        text("""
            SELECT w.ticker, c.name as company_name, w.target_price
            FROM watchlist_items w
            LEFT JOIN companies c ON w.company_id = c.id
            WHERE w.target_price IS NOT NULL AND w.user_email = :email
        """),
        {"email": user.get("email")},
    )
    items = [dict(row) for row in result.mappings().all()]

    alerts = []
    for item in items:
        info = await yfinance_svc.get_stock_info(item["ticker"])
        if not info or not info.get("price"):
            continue
        current_price = info["price"]
        target = float(item["target_price"])
        distance_pct = abs(current_price - target) / target * 100

        if distance_pct <= 10:  # Within 10% of target
            direction = "below" if current_price < target else "above"
            alerts.append({
                "ticker": item["ticker"],
                "company_name": item.get("company_name"),
                "current_price": current_price,
                "target_price": target,
                "distance_pct": round(distance_pct, 1),
                "message": f"{item['ticker']} is {distance_pct:.1f}% {direction} target price of ${target:.2f}",
            })

    return {"alerts": alerts}