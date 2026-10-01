from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.leetcode import fetcher

router = APIRouter(prefix="/leetcode")
log = structlog.get_logger("leetcode")


def _username_required() -> JSONResponse:
    return JSONResponse(
        {"message": "username query param is required (or set LEETCODE_USERNAME in .env)"}, status_code=400
    )


def parse_int(raw: str | None, default: int) -> int:
    """JS `Number(raw) || default`: anything unparsable or zero falls back."""
    try:
        return int(float(raw or "")) or default
    except (ValueError, OverflowError):
        return default


def _resolve_username(username: str | None) -> str | None:
    """Falls back to LEETCODE_USERNAME when ?username= is not provided."""
    if username and username.strip():
        return username.strip()
    return (settings.leetcode_username or "").strip() or None


async def _respond(
    event: str, failure: str, call: Callable[[], Awaitable[Any]]
) -> Any:
    try:
        return await call()
    except Exception:
        log.exception(event)
        return JSONResponse({"message": failure}, status_code=500)


@router.get("/progress", response_model=None)
async def progress(skip: str | None = None, limit: str | None = None) -> Any:
    if not fetcher.has_session():
        return JSONResponse(
            {"message": "LEETCODE_SESSION and LEETCODE_CSRF must be set in .env"}, status_code=500
        )
    s = max(parse_int(skip, 0), 0)
    lim = min(max(parse_int(limit, 50), 1), 100)

    async def call() -> dict[str, Any]:
        batch = await fetcher.fetch_progress_questions(s, lim)
        return {
            "totalNum": batch["totalNum"],
            "skip": s,
            "limit": lim,
            "hasMore": s + len(batch["questions"]) < batch["totalNum"],
            "questions": batch["questions"],
        }

    return await _respond("progress_failed", "Failed to fetch question progress", call)


@router.get("/my-contests", response_model=None)
async def my_contests(username: str | None = None) -> Any:
    if not (name := _resolve_username(username)):
        return _username_required()

    async def call() -> dict[str, Any]:
        info, history = await fetcher.fetch_contest(name)
        return {**info, "history": history}

    return await _respond("contests_failed", "Failed to fetch contest history", call)


@router.get("/language-stats", response_model=None)
async def language_stats(username: str | None = None) -> Any:
    if not (name := _resolve_username(username)):
        return _username_required()

    async def call() -> dict[str, Any]:
        return {"username": name, "languageStats": await fetcher.fetch_language_stats(name)}

    return await _respond("language_stats_failed", "Failed to fetch language stats", call)


@router.get("/skill-stats", response_model=None)
async def skill_stats(username: str | None = None) -> Any:
    if not (name := _resolve_username(username)):
        return _username_required()

    async def call() -> dict[str, Any]:
        return {"username": name, "skillStats": await fetcher.fetch_skill_stats(name)}

    return await _respond("skill_stats_failed", "Failed to fetch skill stats", call)


@router.get("/question-progress", response_model=None)
async def question_progress(username: str | None = None) -> Any:
    if not (name := _resolve_username(username)):
        return _username_required()

    async def call() -> dict[str, Any]:
        return {"username": name, **await fetcher.fetch_question_progress(name)}

    return await _respond("question_progress_failed", "Failed to fetch question progress", call)


@router.get("/session-progress", response_model=None)
async def session_progress(username: str | None = None) -> Any:
    if not (name := _resolve_username(username)):
        return _username_required()

    async def call() -> dict[str, Any]:
        return {"username": name, **await fetcher.fetch_session_progress(name)}

    return await _respond("session_progress_failed", "Failed to fetch session progress", call)


@router.get("/calendar", response_model=None)
async def calendar(username: str | None = None, year: str | None = None) -> Any:
    if not (name := _resolve_username(username)):
        return _username_required()
    y = parse_int(year, 0) or None  # optional: omitted -> LeetCode's current year

    async def call() -> dict[str, Any]:
        return {"username": name, **await fetcher.fetch_calendar(name, y)}

    return await _respond("calendar_failed", "Failed to fetch calendar", call)


@router.get("/profile", response_model=None)
async def profile(username: str | None = None) -> Any:
    if not (name := _resolve_username(username)):
        return _username_required()
    return await _respond(
        "profile_failed", "Failed to fetch LeetCode profile", lambda: fetcher.fetch_profile(name)
    )


# Catch-all: must stay registered last so it doesn't shadow the routes above.
@router.get("/{username}", response_model=None)
async def public_profile(username: str) -> Any:
    return await _respond(
        "public_profile_failed", "Failed to fetch LeetCode profile",
        lambda: fetcher.fetch_public_profile(username),
    )
