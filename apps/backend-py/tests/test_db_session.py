from app.db.session import to_asyncpg_url


def test_rewrites_scheme_and_strips_sslmode() -> None:
    url, connect_args = to_asyncpg_url(
        "postgresql://user:pass@ep-xxx.neon.tech/leetplus?sslmode=require"
    )
    assert url == "postgresql+asyncpg://user:pass@ep-xxx.neon.tech/leetplus"
    assert connect_args == {"ssl": "require"}


def test_leaves_url_without_sslmode_untouched() -> None:
    url, connect_args = to_asyncpg_url("postgresql://user:pass@localhost:5432/leetplus")
    assert url == "postgresql+asyncpg://user:pass@localhost:5432/leetplus"
    assert connect_args == {}
