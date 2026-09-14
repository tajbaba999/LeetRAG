from collections.abc import AsyncIterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


def to_asyncpg_url(database_url: str) -> tuple[str, dict[str, object]]:
    """Rewrites a libpq-style DATABASE_URL for SQLAlchemy's async asyncpg driver.

    asyncpg doesn't understand `sslmode` in the DSN the way `pg` (used by
    Prisma's adapter today) does - Neon's connection strings include it, so it
    has to be pulled out of the URL and passed as a connect_args `ssl` option
    instead, or asyncpg rejects the connection kwarg outright.
    """
    parts = urlsplit(database_url)
    query = dict(parse_qsl(parts.query))
    sslmode = query.pop("sslmode", None)

    connect_args: dict[str, object] = {}
    if sslmode in ("require", "verify-ca", "verify-full"):
        connect_args["ssl"] = "require"

    url = urlunsplit(("postgresql+asyncpg", parts.netloc, parts.path, urlencode(query), parts.fragment))
    return url, connect_args


_url, _connect_args = to_asyncpg_url(settings.database_url)

engine = create_async_engine(_url, connect_args=_connect_args, pool_pre_ping=True)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
