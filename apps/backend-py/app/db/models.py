import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    # Naive UTC: the columns are `timestamp without time zone` (Prisma's default),
    # and asyncpg rejects tz-aware values for them.
    return datetime.now(UTC).replace(tzinfo=None)


# Prisma's `@default(uuid())` and `@updatedAt` are both client-side behaviors,
# not DB defaults/triggers - the migrations confirm `id`/`updatedAt` columns
# carry no DEFAULT in Postgres. These two mirror that on the Python side so
# inserts/updates produce the same values Prisma would have.
def _id_column() -> Mapped[str]:
    return mapped_column(Text, primary_key=True, default=_uuid)


def _updated_at_column() -> Mapped[datetime]:
    return mapped_column("updatedAt", TIMESTAMP(precision=3), nullable=False, default=_now, onupdate=_now)


class User(Base):
    __tablename__ = "User"
    # Prisma implements `@unique` as a plain CREATE UNIQUE INDEX, not an
    # ALTER TABLE ... ADD CONSTRAINT - matching that exactly (rather than
    # SQLAlchemy's unique=True column shorthand, which emits a table
    # constraint) keeps Alembic autogenerate quiet against the existing DB.
    __table_args__ = (Index("User_email_key", "email", unique=True),)

    id: Mapped[str] = _id_column()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt", TIMESTAMP(precision=3), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = _updated_at_column()

    coding_profile: Mapped["CodingProfiles | None"] = relationship(back_populates="user", uselist=False)
    leetcode_stats: Mapped["LeetCodeStats | None"] = relationship(back_populates="user", uselist=False)


class CodingProfiles(Base):
    __tablename__ = "CodingProfiles"
    __table_args__ = (Index("CodingProfiles_userId_key", "userId", unique=True),)

    id: Mapped[str] = _id_column()
    user_id: Mapped[str] = mapped_column(
        "userId", Text, ForeignKey("User.id", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False
    )
    leetcode: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt", TIMESTAMP(precision=3), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = _updated_at_column()

    user: Mapped["User"] = relationship(back_populates="coding_profile")


class LeetCodeStats(Base):
    __tablename__ = "LeetCodeStats"
    __table_args__ = (Index("LeetCodeStats_userId_key", "userId", unique=True),)

    id: Mapped[str] = _id_column()
    user_id: Mapped[str] = mapped_column(
        "userId", Text, ForeignKey("User.id", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False
    )
    username: Mapped[str] = mapped_column(Text, nullable=False)
    total_solved: Mapped[int] = mapped_column("totalSolved", Integer, nullable=False, server_default="0")
    total_questions: Mapped[int] = mapped_column("totalQuestions", Integer, nullable=False, server_default="0")
    easy_solved: Mapped[int] = mapped_column("easySolved", Integer, nullable=False, server_default="0")
    medium_solved: Mapped[int] = mapped_column("mediumSolved", Integer, nullable=False, server_default="0")
    hard_solved: Mapped[int] = mapped_column("hardSolved", Integer, nullable=False, server_default="0")
    ranking: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    acceptance_rate: Mapped[float] = mapped_column(
        "acceptanceRate", DOUBLE_PRECISION, nullable=False, server_default="0"
    )
    streak: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        "createdAt", TIMESTAMP(precision=3), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = _updated_at_column()
    contest_rating: Mapped[float] = mapped_column(
        "contestRating", DOUBLE_PRECISION, nullable=False, server_default="0"
    )
    contest_global_ranking: Mapped[int] = mapped_column(
        "contestGlobalRanking", Integer, nullable=False, server_default="0"
    )
    contest_top_percentage: Mapped[float] = mapped_column(
        "contestTopPercentage", DOUBLE_PRECISION, nullable=False, server_default="0"
    )
    attended_contests_count: Mapped[int] = mapped_column(
        "attendedContestsCount", Integer, nullable=False, server_default="0"
    )
    question_progress: Mapped[Any | None] = mapped_column("questionProgress", JSONB)
    session_progress: Mapped[Any | None] = mapped_column("sessionProgress", JSONB)
    skill_stats: Mapped[Any | None] = mapped_column("skillStats", JSONB)
    language_stats: Mapped[Any | None] = mapped_column("languageStats", JSONB)
    recent_submissions: Mapped[Any | None] = mapped_column("recentSubmissions", JSONB)
    calendar_data: Mapped[Any | None] = mapped_column("calendarData", JSONB)

    user: Mapped["User"] = relationship(back_populates="leetcode_stats")


class LeetCodeHistory(Base):
    __tablename__ = "LeetCodeHistory"
    __table_args__ = (
        Index("LeetCodeHistory_userId_idx", "userId"),
        Index("LeetCodeHistory_userId_snapshotAt_idx", "userId", "snapshotAt"),
    )

    id: Mapped[str] = _id_column()
    user_id: Mapped[str] = mapped_column("userId", Text, nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(
        "snapshotAt", TIMESTAMP(precision=3), nullable=False, server_default=func.now()
    )
    total_solved: Mapped[int] = mapped_column("totalSolved", Integer, nullable=False, server_default="0")
    total_questions: Mapped[int] = mapped_column("totalQuestions", Integer, nullable=False, server_default="0")
    easy_solved: Mapped[int] = mapped_column("easySolved", Integer, nullable=False, server_default="0")
    medium_solved: Mapped[int] = mapped_column("mediumSolved", Integer, nullable=False, server_default="0")
    hard_solved: Mapped[int] = mapped_column("hardSolved", Integer, nullable=False, server_default="0")
    ranking: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    acceptance_rate: Mapped[float] = mapped_column(
        "acceptanceRate", DOUBLE_PRECISION, nullable=False, server_default="0"
    )
    streak: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    contest_rating: Mapped[float] = mapped_column(
        "contestRating", DOUBLE_PRECISION, nullable=False, server_default="0"
    )
    contest_global_ranking: Mapped[int] = mapped_column(
        "contestGlobalRanking", Integer, nullable=False, server_default="0"
    )
    contest_top_percentage: Mapped[float] = mapped_column(
        "contestTopPercentage", DOUBLE_PRECISION, nullable=False, server_default="0"
    )
    attended_contests_count: Mapped[int] = mapped_column(
        "attendedContestsCount", Integer, nullable=False, server_default="0"
    )
    problems_solved_list: Mapped[Any | None] = mapped_column("problemsSolvedList", JSONB)
    contest_history: Mapped[Any | None] = mapped_column("contestHistory", JSONB)
    skill_stats: Mapped[Any | None] = mapped_column("skillStats", JSONB)
    language_stats: Mapped[Any | None] = mapped_column("languageStats", JSONB)


class LeetCodeContestHistory(Base):
    __tablename__ = "LeetCodeContestHistory"
    __table_args__ = (
        Index("LeetCodeContestHistory_userId_contestTitle_key", "userId", "contestTitle", unique=True),
        Index("LeetCodeContestHistory_userId_idx", "userId"),
    )

    id: Mapped[str] = _id_column()
    user_id: Mapped[str] = mapped_column("userId", Text, nullable=False)
    contest_title: Mapped[str] = mapped_column("contestTitle", Text, nullable=False)
    start_time: Mapped[int] = mapped_column("startTime", Integer, nullable=False)
    attended: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rating: Mapped[float] = mapped_column(DOUBLE_PRECISION, nullable=False)
    ranking: Mapped[int] = mapped_column(Integer, nullable=False)
    trend_direction: Mapped[str] = mapped_column("trendDirection", Text, nullable=False, server_default="''")
    problems_solved: Mapped[int] = mapped_column("problemsSolved", Integer, nullable=False, server_default="0")
    total_problems: Mapped[int] = mapped_column("totalProblems", Integer, nullable=False, server_default="0")
    finish_time_in_seconds: Mapped[int] = mapped_column(
        "finishTimeInSeconds", Integer, nullable=False, server_default="0"
    )


class LeetCodeProblem(Base):
    __tablename__ = "LeetCodeProblem"
    __table_args__ = (
        Index("LeetCodeProblem_userId_titleSlug_key", "userId", "titleSlug", unique=True),
        Index("LeetCodeProblem_userId_idx", "userId"),
    )

    id: Mapped[str] = _id_column()
    user_id: Mapped[str] = mapped_column("userId", Text, nullable=False)
    title_slug: Mapped[str] = mapped_column("titleSlug", Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[str] = mapped_column(Text, nullable=False)
    question_status: Mapped[str] = mapped_column("questionStatus", Text, nullable=False)
    last_result: Mapped[str] = mapped_column("lastResult", Text, nullable=False)
    # Text, not a timestamp - matches Prisma's `lastSubmittedAt String`.
    last_submitted_at: Mapped[str] = mapped_column("lastSubmittedAt", Text, nullable=False)
    num_submitted: Mapped[int] = mapped_column("numSubmitted", Integer, nullable=False, server_default="0")
    topic_tags: Mapped[Any] = mapped_column("topicTags", JSONB, nullable=False)


class RagChunkHash(Base):
    __tablename__ = "RagChunkHash"

    user_id: Mapped[str] = mapped_column("userId", Text, primary_key=True)
    chunk_id: Mapped[str] = mapped_column("chunkId", Text, primary_key=True)
    hash: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = _updated_at_column()
