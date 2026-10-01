from sqlalchemy.orm import configure_mappers

from app.db import models


def test_mappers_configure_without_error() -> None:
    configure_mappers()


def test_table_names_and_columns_match_prisma_schema() -> None:
    tables = models.Base.metadata.tables

    assert set(tables) == {
        "User",
        "CodingProfiles",
        "LeetCodeStats",
        "LeetCodeHistory",
        "LeetCodeContestHistory",
        "LeetCodeProblem",
        "RagChunkHash",
    }

    assert {c.name for c in tables["User"].columns} == {
        "id", "name", "email", "password", "createdAt", "updatedAt",
    }
    assert {c.name for c in tables["RagChunkHash"].columns} == {
        "userId", "chunkId", "hash", "updatedAt",
    }
    assert [c.name for c in tables["RagChunkHash"].primary_key.columns] == ["userId", "chunkId"]


def test_unique_indexes_match_prisma_not_table_constraints() -> None:
    """Prisma implements @unique/@@unique as CREATE UNIQUE INDEX, never as an
    ALTER TABLE ... ADD CONSTRAINT. Using the wrong DDL object type here would
    make Alembic autogenerate see a spurious diff against the live DB."""
    user_indexes = {(i.name, i.unique) for i in models.Base.metadata.tables["User"].indexes}
    assert ("User_email_key", True) in user_indexes
    assert len(models.Base.metadata.tables["User"].constraints) == 1  # PK only, no UniqueConstraint

    problem = models.Base.metadata.tables["LeetCodeProblem"]
    assert {(i.name, tuple(c.name for c in i.columns), i.unique) for i in problem.indexes} == {
        ("LeetCodeProblem_userId_titleSlug_key", ("userId", "titleSlug"), True),
        ("LeetCodeProblem_userId_idx", ("userId",), False),
    }


def test_foreign_keys_match_prisma_ondelete_onupdate() -> None:
    for table_name in ("CodingProfiles", "LeetCodeStats"):
        fks = list(models.Base.metadata.tables[table_name].foreign_keys)
        assert len(fks) == 1
        assert fks[0].column.table.name == "User"
        assert fks[0].ondelete == "RESTRICT"
        assert fks[0].onupdate == "CASCADE"

    # These three intentionally have no FK to User in the Prisma schema.
    for table_name in ("LeetCodeHistory", "LeetCodeContestHistory", "LeetCodeProblem"):
        assert not models.Base.metadata.tables[table_name].foreign_keys
