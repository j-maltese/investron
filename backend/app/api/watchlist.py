from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.database import get_db
from app.models.schemas import WatchlistItemCreate, WatchlistItemUpdate
from app.services import yfinance_svc

router = APIRouter()


@router.get("")
async def get_watchlist(db: AsyncSession = Depends(get_db)):
    """Get all watchlist items with current prices."""
    result = await db.execute(
        text("""
            SELECT w.id, w.ticker, c.name as company_name, w.notes, w.target_price, w.added_at
            FROM watchlist_items w
            LEFT JOIN companies c ON w.company_id = c.id
            ORDER BY w.added_at DESC
        """)
    )
    items = [dict(row) for row in result.mappings().all()]

    # Enrich with current prices
    for item in items:
        info = await yfinance_svc.get_stock_info(item["ticker"])
        if info:
            item["current_price"] = info.get("price")
            item["price_change_pct"] = None  # Could compute from historical data

    return {"items": items}


@router.post("")
async def add_to_watchlist(item: WatchlistItemCreate, db: AsyncSession = Depends(get_db)):
    """Add a ticker to the watchlist."""
    # Ensure company exists in DB
    from app.services.company import get_or_create_company
    company = await get_or_create_company(db, item.ticker)
    company_id = company["id"] if company else None

    result = await db.execute(
        text("""
            INSERT INTO watchlist_items (ticker, company_id, notes, target_price)
            VALUES (:ticker, :company_id, :notes, :target_price)
            ON CONFLICT (ticker) DO UPDATE SET
                notes = COALESCE(EXCLUDED.notes, watchlist_items.notes),
                target_price = COALESCE(EXCLUDED.target_price, watchlist_items.target_price)
            RETURNING id, ticker, notes, target_price, added_at
        """),
        {
            "ticker": item.ticker.upper(),
            "company_id": company_id,
            "notes": item.notes,
            "target_price": item.target_price,
        },
    )
    await db.commit()
    return dict(result.mappings().first())


@router.delete("/{ticker}")
async def remove_from_watchlist(ticker: str, db: AsyncSession = Depends(get_db)):
    """Remove a ticker from the watchlist."""
    result = await db.execute(
        text("DELETE FROM watchlist_items WHERE ticker = :ticker RETURNING id"),
        {"ticker": ticker.upper()},
    )
    await db.commit()
    deleted = result.mappings().first()
    if not deleted:
        raise HTTPException(status_code=404, detail=f"{ticker} not found in watchlist")
    return {"message": f"Removed {ticker} from watchlist"}


@router.patch("/{ticker}")
async def update_watchlist_item(ticker: str, update: WatchlistItemUpdate, db: AsyncSession = Depends(get_db)):
    """Update notes or target price for a watchlist item."""
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
    result = await db.execute(
        text(f"UPDATE watchlist_items SET {', '.join(set_clauses)} WHERE ticker = :ticker RETURNING id, ticker, notes, target_price"),
        updates,
    )
    await db.commit()
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"{ticker} not found in watchlist")
    return dict(row)


@router.get("/alerts")
async def get_alerts(db: AsyncSession = Depends(get_db)):
    """Get alerts for watchlist items near their target price."""
    result = await db.execute(
        text("""
            SELECT w.ticker, c.name as company_name, w.target_price
            FROM watchlist_items w
            LEFT JOIN companies c ON w.company_id = c.id
            WHERE w.target_price IS NOT NULL
        """)
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
