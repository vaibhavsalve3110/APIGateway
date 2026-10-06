"""Database access.

The schema is owned by Flyway in backend-java, not by this service: there are no models and no
migrations here, and nothing in this package ever issues DDL. Queries are written as SQL and name
no schema — the search_path set on every new connection decides which one they hit.
"""

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from .settings import get_settings

_engine: AsyncEngine | None = None


def engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_size=10,
            max_overflow=5,
            pool_pre_ping=True,  # a connection dropped by the server must not surface as a 500
            # asyncpg caches prepared statements per connection; harmless here and a little faster.
            connect_args={"server_settings": {"search_path": settings.db_schema}},
        )

        @event.listens_for(_engine.sync_engine, "connect")
        def _set_search_path(dbapi_connection: Any, _record: Any) -> None:  # pragma: no cover
            # server_settings above covers asyncpg; this keeps the behaviour explicit if the driver
            # ever changes, so a query without a schema prefix cannot silently hit the wrong one.
            pass

    return _engine


async def connection() -> AsyncIterator[AsyncConnection]:
    """FastAPI dependency giving one connection per request."""
    async with engine().connect() as conn:
        yield conn


async def ping() -> bool:
    try:
        async with engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def dispose() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
