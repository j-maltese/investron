from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_cached_data(
    db: AsyncSession,
    company_id: int,
    source: str,
    data_type: str,
    period_type: str = "annual",
) -> dict | None:
    """Retrieve cached financial data if not expired."""
    result = await db.execute(
        text("""
            SELECT data, fetched_at, expires_at
            FROM financial_data_cache
            WHERE company_id = :company_id
              AND source = :source
              AND data_type = :data_type
              AND period_type = :period_type
              AND expires_at > :now
            ORDER BY fetched_at DESC
            LIMIT 1
        """),
        {
            "company_id": company_id,
            "source": source,
            "data_type": data_type,
            "period_type": period_type,
            "now": datetime.now(timezone.utc),
        },
    )
    row = result.mappings().first()
    if row:
        return row["data"]
    return None


async def set_cached_data(
    db: AsyncSession,
    company_id: int,
    source: str,
    data_type: str,
    period_type: str,
    data: dict,
    ttl_seconds: int,
) -> None:
    """Store data in cache with expiration."""
    now = datetime.now(timezone.utc)
    await db.execute(
        text("""
            INSERT INTO financial_data_cache (company_id, source, data_type, period_type, data, fetched_at, expires_at)
            VALUES (:company_id, :source, :data_type, :period_type, CAST(:data AS jsonb), :now, :expires_at)
            ON CONFLICT (company_id, source, data_type, period_type)
            DO UPDATE SET data = CAST(:data AS jsonb), fetched_at = :now, expires_at = :expires_at
        """),
        {
            "company_id": company_id,
            "source": source,
            "data_type": data_type,
            "period_type": period_type,
            "data": data if isinstance(data, str) else __import__("json").dumps(data),
            "now": now,
            "expires_at": datetime.fromtimestamp(now.timestamp() + ttl_seconds, tz=timezone.utc),
        },
    )
    await db.commit()
