"""
CSP Document Generation & Email Automation Platform — Database

Async SQLAlchemy engine and session management for PostgreSQL.
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings


settings = get_settings()

# Async engine for the application
engine = create_async_engine(
    settings.database_url,
    echo=settings.database_echo,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

# Session factory
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)



class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


async def get_db() -> AsyncSession:
    """FastAPI dependency — yields an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Alias — some routers import get_session instead of get_db
get_session = get_db


async def init_db():
    """Initialize database connection pool. Called on app startup."""
    # Connection pool is created lazily by SQLAlchemy on first use.
    # This function exists as a hook for any future startup logic.
    pass


async def close_db():
    """Dispose database engine. Called on app shutdown."""
    await engine.dispose()

# Scope every query to the workspace in force. Installed here, once, rather
# than relied on at each call site — see app/workspace_context.py.
from app.workspace_context import install as _install_workspace_scoping  # noqa: E402

_install_workspace_scoping()
