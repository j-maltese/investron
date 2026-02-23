import logging
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


engine = None
async_session_factory = None


def init_db():
    global engine, async_session_factory
    settings = get_settings()
    db_url = settings.database_url

    if not db_url:
        logger.warning("DATABASE_URL not set — database features will be unavailable")
        return

    # Convert postgres:// to postgresql+asyncpg://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url, echo=settings.debug)
    async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    logger.info("Database connection initialized")


async def get_db() -> AsyncSession:
    if async_session_factory is None:
        init_db()
    if async_session_factory is None:
        raise RuntimeError("Database not configured. Set DATABASE_URL in .env")
    async with async_session_factory() as session:
        yield session
