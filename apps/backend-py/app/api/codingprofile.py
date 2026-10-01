from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import urlsplit

import structlog
from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect

from app.api.leetcode import parse_int
from app.core.config import settings
from app.core.security import CurrentUser
from app.db.models import (
    CodingProfiles,
    LeetCodeContestHistory,
    LeetCodeHistory,
    LeetCodeProblem,
    LeetCodeStats,
)
from app.db.session import get_db
from app.leetcode.sync import SSE_HEADERS, js_round, run_sync, sse_stream

router = APIRouter(prefix="/codingprofile")
log = structlog.get_logger("codingprofile")

Db = Annotated[AsyncSession, Depends(get_db)]


def _json_value(value: Any) -> Any:
    # Prisma stores UTC in naive timestamp columns; tag it so clients don't read local time.
    return value.replace(tzinfo=UTC) if isinstance(value, datetime) else value


def row_to_json(row: Any) -> dict[str, Any]:
    """ORM row -> dict keyed by DB column names (camelCase), i.e. what Prisma returned."""
    return {
        attr.columns[0].name: _json_value(getattr(row, attr.key))
        for attr in inspect(row).mapper.column_attrs
    }


def _server_error(event: str) -> JSONResponse:
    log.exception(event)
    return JSONResponse({"message": "Server Error!"}, status_code=500)


def extract_username(value: str | None) -> str | None:
    """Accepts a bare username or a profile URL like https://leetcode.com/u/name/."""
    if not value:
        return None
    parts = urlsplit(value)
    if not parts.scheme:
        return value
    segments = [s for s in parts.path.split("/") if s]
    return segments[-1] if segments else value


def _sse(user_id: str, username: str) -> StreamingResponse:
    return StreamingResponse(
        sse_stream(lambda emit: run_sync(user_id, username, emit)),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/initial-sync", response_model=None)
async def initial_sync(
    user: CurrentUser, db: Db, body: Annotated[dict[str, Any] | None, Body()] = None
) -> StreamingResponse | JSONResponse:
    raw = (body or {}).get("leetcode")
    username = extract_username(raw if isinstance(raw, str) else None) or (
        (settings.leetcode_username or "").strip() or None
    )
    if not username:
        return JSONResponse(
            {"message": "LeetCode username is required. Provide in body or set LEETCODE_USERNAME in .env"},
            status_code=400,
        )

    exists = await db.scalar(select(CodingProfiles.id).where(CodingProfiles.user_id == user["userId"]))
    if not exists:
        db.add(CodingProfiles(user_id=user["userId"], leetcode=username))
        await db.commit()

    return _sse(user["userId"], username)


@router.post("/sync", response_model=None)
async def sync(user: CurrentUser, db: Db) -> StreamingResponse | JSONResponse:
    profile = await db.scalar(select(CodingProfiles).where(CodingProfiles.user_id == user["userId"]))
    if profile is None:
        return JSONResponse(
            {"message": "No coding profile linked. Call POST /codingprofile/initial-sync first."}, status_code=404
        )
    username = profile.leetcode or (settings.leetcode_username or "").strip()
    if not username:
        return JSONResponse({"message": "No LeetCode username linked."}, status_code=400)
    return _sse(user["userId"], username)


@router.get("/", response_model=None)
async def get_coding_profile(user: CurrentUser, db: Db) -> Any:
    uid = user["userId"]
    try:
        # One AsyncSession can't run queries concurrently, so these go one by one.
        profiles = await db.scalar(select(CodingProfiles).where(CodingProfiles.user_id == uid))
        stats = await db.scalar(select(LeetCodeStats).where(LeetCodeStats.user_id == uid))
        problems = await db.scalar(select(func.count()).where(LeetCodeProblem.user_id == uid))
        contests = await db.scalar(select(func.count()).where(LeetCodeContestHistory.user_id == uid))
    except Exception:
        return _server_error("coding_profile_failed")

    if profiles is None:
        return JSONResponse({"message": "Coding profiles not found. Create them first."}, status_code=404)
    return {
        "profiles": row_to_json(profiles),
        "stats": {"leetcode": row_to_json(stats) if stats else None},
        "counts": {"problems": problems, "contests": contests},
    }


HISTORY_FIELDS = (
    "id", "snapshotAt", "totalSolved", "totalQuestions", "easySolved", "mediumSolved", "hardSolved", "ranking",
    "acceptanceRate", "streak", "contestRating", "contestGlobalRanking", "contestTopPercentage",
    "attendedContestsCount", "problemsSolvedList", "contestHistory", "skillStats", "languageStats",
)


@router.get("/history", response_model=None)
async def history(user: CurrentUser, db: Db, limit: str | None = None) -> Any:
    take = min(max(parse_int(limit, 30), 1), 100)
    try:
        rows = (await db.scalars(
            select(LeetCodeHistory).where(LeetCodeHistory.user_id == user["userId"])
            .order_by(LeetCodeHistory.snapshot_at.desc()).limit(take)
        )).all()
    except Exception:
        return _server_error("history_failed")
    snapshots = [{k: v for k, v in row_to_json(r).items() if k in HISTORY_FIELDS} for r in rows]
    return {"snapshots": snapshots, "total": len(snapshots)}


@router.get("/history/diff", response_model=None)
async def history_diff(
    user: CurrentUser, db: Db, from_id: Annotated[str | None, Query(alias="from")] = None, to: str | None = None
) -> Any:
    uid = user["userId"]
    try:
        if from_id and to:
            by_id = select(LeetCodeHistory).where(LeetCodeHistory.user_id == uid)
            older = await db.scalar(by_id.where(LeetCodeHistory.id == from_id))
            newer = await db.scalar(by_id.where(LeetCodeHistory.id == to))
        else:
            latest = (await db.scalars(
                select(LeetCodeHistory).where(LeetCodeHistory.user_id == uid)
                .order_by(LeetCodeHistory.snapshot_at.desc()).limit(2)
            )).all()
            newer = latest[0] if latest else None
            older = latest[1] if len(latest) > 1 else None
    except Exception:
        return _server_error("history_diff_failed")

    if older is None or newer is None:
        return JSONResponse({"message": "Need at least 2 snapshots to compute diff"}, status_code=404)

    old_slugs = {p["titleSlug"] for p in older.problems_solved_list or []} \
        if isinstance(older.problems_solved_list, list) else set()
    new_list = newer.problems_solved_list if isinstance(newer.problems_solved_list, list) else []
    newly_solved = [p for p in new_list if p["titleSlug"] not in old_slugs]

    return {
        "from": {"snapshotAt": _json_value(older.snapshot_at), "totalSolved": older.total_solved},
        "to": {"snapshotAt": _json_value(newer.snapshot_at), "totalSolved": newer.total_solved},
        "diff": {
            "totalSolved": newer.total_solved - older.total_solved,
            "easy": newer.easy_solved - older.easy_solved,
            "medium": newer.medium_solved - older.medium_solved,
            "hard": newer.hard_solved - older.hard_solved,
            "contestRating": js_round((newer.contest_rating - older.contest_rating) * 100) / 100,
            "ranking": newer.ranking - older.ranking,
            "newlySolvedCount": len(newly_solved),
            "newlySolved": newly_solved,
        },
    }


@router.get("/activity", response_model=None)
async def activity(user: CurrentUser, db: Db, year: str | None = None, month: str | None = None) -> Any:
    try:
        stats = await db.scalar(select(LeetCodeStats).where(LeetCodeStats.user_id == user["userId"]))
    except Exception:
        return _server_error("activity_failed")
    if stats is None or not stats.calendar_data:
        return JSONResponse({"message": "No calendar data yet. Run a sync first."}, status_code=404)

    cal = stats.calendar_data
    y = parse_int(year, 0) or None
    m = parse_int(month, 0) or None
    month_prefix = f"{y or datetime.now(UTC).year}-{m:02d}" if m else None

    days = []
    for ts, count in (cal.get("submissionCalendar") or {}).items():
        d = datetime.fromtimestamp(int(ts), UTC)
        date = d.date().isoformat()
        if y and not date.startswith(str(y)):
            continue
        if month_prefix and not date.startswith(month_prefix):
            continue
        days.append({"date": date, "dayOfWeek": (d.weekday() + 1) % 7, "submissions": count, "timestamp": int(ts)})
    days.sort(key=lambda d: d["timestamp"])

    return {
        "username": stats.username,
        "activeYears": cal.get("activeYears"),
        "totalActiveDays": cal.get("totalActiveDays"),
        "streak": stats.streak,
        "query": {"year": y or "all", "month": m or "all"},
        "totalDaysActive": len(days),
        "totalSubmissions": sum(d["submissions"] for d in days),
        "submissions": days,
    }


@router.get("/questions", response_model=None)
async def questions(
    user: CurrentUser, db: Db, limit: str | None = None, offset: str | None = None,
    difficulty: str | None = None, tag: str | None = None,
) -> Any:
    take = min(max(parse_int(limit, 30), 1), 100)
    skip = max(parse_int(offset, 0), 0)
    try:
        rows = (await db.scalars(
            select(LeetCodeProblem).where(LeetCodeProblem.user_id == user["userId"])
            .order_by(LeetCodeProblem.last_submitted_at.desc())
        )).all()
        problems = [row_to_json(r) for r in rows]

        # Fallback: no problem rows yet -> latest history snapshot's list.
        if not problems:
            latest = await db.scalar(
                select(LeetCodeHistory.problems_solved_list).where(LeetCodeHistory.user_id == user["userId"])
                .order_by(LeetCodeHistory.snapshot_at.desc()).limit(1)
            )
            if isinstance(latest, list):
                problems = [{
                    "titleSlug": p["titleSlug"], "title": p["title"], "difficulty": p["difficulty"],
                    "questionStatus": p.get("questionStatus", ""), "lastResult": p.get("lastResult", ""),
                    "lastSubmittedAt": p.get("lastSubmittedAt", ""), "numSubmitted": p.get("numSubmitted", 0),
                    "topicTags": p.get("topicTags", []),
                } for p in latest]
    except Exception:
        return _server_error("questions_failed")

    if difficulty:
        wanted = difficulty.capitalize()
        problems = [p for p in problems if p["difficulty"] == wanted]
    if tag:
        needle = tag.lower()
        problems = [
            p for p in problems
            if isinstance(p["topicTags"], list)
            and any(needle in t["name"].lower() or needle in t["slug"].lower() for t in p["topicTags"])
        ]

    page = problems[skip:skip + take]
    keys = ("title", "titleSlug", "difficulty", "lastResult", "questionStatus", "lastSubmittedAt",
            "numSubmitted", "topicTags")
    return {
        "total": len(problems),
        "limit": take,
        "offset": skip,
        "hasMore": skip + take < len(problems),
        "difficulty": difficulty or "all",
        "tag": tag or "all",
        "questions": [{k: p[k] for k in keys} for p in page],
    }


TOPIC_CONFIG: list[tuple[str, tuple[str, ...]]] = [
    ("Array", ("array",)),
    ("String", ("string",)),
    ("Hash Table", ("hash table", "hash map")),
    ("DP", ("dynamic programming",)),
    ("Tree", ("tree", "binary tree", "binary search tree", "n-ary tree")),
    ("Graph", ("graph",)),
    ("Two Pointers", ("two pointers", "two pointer")),
    ("Sliding Window", ("sliding window",)),
    ("Linked List", ("linked list",)),
    ("Matrix", ("matrix",)),
    ("Backtracking", ("backtracking",)),
    ("Stack", ("stack",)),
    ("Heap", ("heap", "priority queue")),
    ("Union Find", ("union find", "union-find", "disjoint set")),
    ("Binary Search", ("binary search",)),
    ("Greedy", ("greedy",)),
    ("Sorting", ("sort", "sorting")),
    ("Prefix Sum", ("prefix sum",)),
]
TOPIC_BY_ALIAS = {alias: display for display, aliases in TOPIC_CONFIG for alias in aliases}
TOPIC_NAMES = [display for display, _ in TOPIC_CONFIG]


def _empty_matrix() -> list[dict[str, Any]]:
    return [{"topic": t, "easy": 0, "medium": 0, "hard": 0} for t in TOPIC_NAMES]


@router.get("/topic-matrix", response_model=None)
async def topic_matrix(user: CurrentUser, db: Db) -> Any:
    try:
        rows = (await db.execute(
            select(LeetCodeProblem.difficulty, LeetCodeProblem.topic_tags)
            .where(LeetCodeProblem.user_id == user["userId"])
        )).all()
        stats = None if rows else await db.scalar(
            select(LeetCodeStats).where(LeetCodeStats.user_id == user["userId"])
        )
    except Exception:
        return _server_error("topic_matrix_failed")

    if rows:
        matrix = {t: {"easy": 0, "medium": 0, "hard": 0} for t in TOPIC_NAMES}
        for difficulty, tags in rows:
            if not isinstance(tags, list):
                continue
            diff = "easy" if difficulty == "Easy" else "hard" if difficulty == "Hard" else "medium"
            for t in tags:
                if topic := TOPIC_BY_ALIAS.get(t["name"].lower()):
                    matrix[topic][diff] += 1
        return [{"topic": t, **matrix[t]} for t in TOPIC_NAMES]

    # Fallback: estimate from skillStats + overall difficulty ratios.
    if stats is None or not stats.skill_stats:
        return _empty_matrix()

    solved_by_topic: dict[str, int] = {}
    for tier in ("fundamental", "intermediate", "advanced"):
        for t in stats.skill_stats.get(tier) or []:
            if topic := TOPIC_BY_ALIAS.get(t["tagName"].lower()):
                solved_by_topic[topic] = solved_by_topic.get(topic, 0) + t["problemsSolved"]

    total = stats.easy_solved + stats.medium_solved + stats.hard_solved
    easy_ratio = stats.easy_solved / total if total else 0.4
    hard_ratio = stats.hard_solved / total if total else 0.2

    result = []
    for topic in TOPIC_NAMES:
        solved = solved_by_topic.get(topic, 0)
        easy = js_round(solved * easy_ratio)
        hard = js_round(solved * hard_ratio)
        result.append({"topic": topic, "easy": easy, "medium": max(0, solved - easy - hard), "hard": hard})
    return result
