"""LeetCode -> Postgres sync, streamed to the client as Server-Sent Events.

One pipeline serves both POST /codingprofile/initial-sync and /sync (the Express
versions were near-identical copies).
"""

import asyncio
import json
import math
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import structlog
from sqlalchemy import delete, insert, select

from app.core.metrics import sync_job_duration_seconds, sync_job_total, sync_jobs_in_flight
from app.db.models import LeetCodeContestHistory, LeetCodeHistory, LeetCodeProblem, LeetCodeStats
from app.db.session import async_session_factory
from app.leetcode import fetcher

log = structlog.get_logger("sync")

PLATFORM = "leetcode"

Emit = Callable[[str, dict[str, Any]], None]

SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}

# Syncs keep running after the client disconnects (as in Express); hold a
# reference so the task isn't garbage-collected mid-flight.
_running: set[asyncio.Task[None]] = set()


async def sse_stream(job: Callable[[Emit], Awaitable[None]]) -> AsyncIterator[str]:
    """Runs `job` in the background and yields each emitted event as an SSE frame."""
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def emit(event: str, data: dict[str, Any]) -> None:
        queue.put_nowait(f"event: {event}\ndata: {json.dumps(data)}\n\n")

    async def runner() -> None:
        try:
            await job(emit)
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(runner())
    _running.add(task)
    task.add_done_callback(_running.discard)
    while (frame := await queue.get()) is not None:
        yield frame


def _progress(emit: Emit, stage: str, pct: int, msg: str) -> None:
    emit("progress", {"stage": stage, "pct": pct, "msg": msg})


def js_round(x: float) -> int:
    """Math.round: halves go toward +inf (Python's round() is banker's rounding)."""
    return math.floor(x + 0.5)


async def ingest_rag(*_args: Any, **_kwargs: Any) -> dict[str, int]:
    # Placeholder until the RAG pipeline is ported (step 5); the sync reports
    # "AI indexing skipped" exactly as Express does when ingest throws.
    raise RuntimeError("RAG ingest not available yet")


EMPTY_CONTEST = (
    {"attendedContestsCount": 0, "rating": 0, "globalRanking": 0, "totalParticipants": 0,
     "topPercentage": 0, "badge": None},
    [],
)
EMPTY_QUESTION_PROGRESS = {"numAcceptedQuestions": [], "numFailedQuestions": [], "numUntouchedQuestions": [],
                           "userSessionBeatsPercentage": [], "totalQuestionBeatsPercentage": 0}
EMPTY_SESSION_PROGRESS = {"allQuestionsCount": [], "acSubmissionNum": [], "totalSubmissionNum": []}
EMPTY_SKILL_STATS: dict[str, Any] = {"fundamental": [], "intermediate": [], "advanced": []}
EMPTY_CALENDAR = {"activeYears": [], "streak": 0, "totalActiveDays": 0, "dccBadges": [], "submissionCalendar": {}}


async def _optional(
    emit: Emit, step: int, label: str, stage: str, pct: int,
    call: Callable[[], Awaitable[Any]], fallback: Any, done_msg: Callable[[Any], str],
) -> Any:
    """Fetches one optional dataset; on failure reports a skip and uses `fallback`."""
    _progress(emit, f"fetch_{stage}", pct, f"{step}/9: Fetching {label}...")
    try:
        result = await call()
    except Exception as exc:
        _progress(emit, f"fetch_{stage}_skip", pct + 3, f"{step}/9: {label.capitalize()} skipped — {exc}")
        return fallback
    _progress(emit, f"fetch_{stage}_done", pct + 3, f"{step}/9: {done_msg(result)}")
    return result


async def fetch_all_problems(total_solved: int, emit: Emit) -> list[dict[str, Any]]:
    page_size = 50
    skip = 0
    problems: list[dict[str, Any]] = []
    while skip < total_solved:
        _progress(
            emit, "fetch_questions", 38 + js_round(skip / total_solved * 7),
            f"8/9: Fetching questions {skip + 1}–{min(skip + page_size, total_solved)} of {total_solved}...",
        )
        page = await fetcher.fetch_user_questions(skip, page_size)
        if not page["questions"]:
            break
        problems += [{k: q[k] for k in ("titleSlug", "title", "difficulty", "questionStatus", "lastResult",
                                         "lastSubmittedAt", "numSubmitted", "topicTags")}
                     for q in page["questions"]]
        skip += page_size
        if skip < total_solved:
            await asyncio.sleep(0.3)
    _progress(emit, "fetch_questions_done", 45, f"8/9: Fetched {len(problems)} solved questions")
    return problems


def _summary_columns(profile: dict[str, Any], contest: dict[str, Any], streak: int) -> dict[str, Any]:
    """Columns shared by LeetCodeStats and LeetCodeHistory."""
    return {
        "total_solved": profile["totalSolved"], "total_questions": profile["totalQuestions"],
        "easy_solved": profile["easySolved"], "medium_solved": profile["mediumSolved"],
        "hard_solved": profile["hardSolved"], "ranking": profile["ranking"],
        "acceptance_rate": profile["acceptanceRate"], "streak": streak,
        "contest_rating": contest["rating"], "contest_global_ranking": contest["globalRanking"],
        "contest_top_percentage": contest["topPercentage"],
        "attended_contests_count": contest["attendedContestsCount"],
    }


async def run_sync(user_id: str, username: str, emit: Emit) -> None:
    sync_jobs_in_flight.labels(PLATFORM).inc()
    start = time.perf_counter()
    status = "completed"
    try:
        await _run_sync(user_id, username, emit)
    except Exception as exc:
        status = "failed"
        log.exception("sync_failed", userId=user_id, username=username)
        emit("error", {"stage": "error", "pct": 0, "msg": f"Sync failed: {exc}"})
    finally:
        sync_jobs_in_flight.labels(PLATFORM).dec()
        sync_job_duration_seconds.labels(PLATFORM, status).observe(time.perf_counter() - start)
        sync_job_total.labels(PLATFORM, status).inc()


async def _run_sync(user_id: str, username: str, emit: Emit) -> None:
    _progress(emit, "fetch_profile", 5, "1/9: Fetching LeetCode profile...")
    profile = await fetcher.fetch_profile(username)
    _progress(emit, "fetch_profile_done", 10,
              f"1/9: Profile fetched — {profile['totalSolved']} solved, ranking #{profile['ranking']}")

    contest_info, contest_history = await _optional(
        emit, 2, "contest info", "contest", 12, lambda: fetcher.fetch_contest(username), EMPTY_CONTEST,
        lambda r: f"Contest info fetched — rating {r[0]['rating']:.0f}, {len(r[1])} contests",
    )
    question_progress = await _optional(
        emit, 3, "question progress", "question_progress", 17,
        lambda: fetcher.fetch_question_progress(username), EMPTY_QUESTION_PROGRESS,
        lambda _: "Question progress fetched",
    )
    session_progress = await _optional(
        emit, 4, "session progress", "session_progress", 21,
        lambda: fetcher.fetch_session_progress(username), EMPTY_SESSION_PROGRESS,
        lambda _: "Session progress fetched",
    )
    skill_stats = await _optional(
        emit, 5, "skill stats", "skill_stats", 25, lambda: fetcher.fetch_skill_stats(username), EMPTY_SKILL_STATS,
        lambda r: f"Skill stats fetched — {sum(len(v) for v in r.values())} topics",
    )
    language_stats = await _optional(
        emit, 6, "language stats", "language_stats", 29, lambda: fetcher.fetch_language_stats(username), [],
        lambda r: f"Language stats fetched — {len(r)} languages",
    )
    calendar = await _optional(
        emit, 7, "activity calendar", "calendar", 33, lambda: fetcher.fetch_calendar(username), EMPTY_CALENDAR,
        lambda r: f"Calendar fetched — {r['totalActiveDays']} active days, streak {r['streak']}",
    )

    _progress(emit, "fetch_questions", 38, f"8/9: Fetching {profile['totalSolved']} solved questions (paginated)...")
    try:
        problems = await fetch_all_problems(profile["totalSolved"], emit)
    except Exception as exc:
        problems = []
        _progress(emit, "fetch_questions_skip", 45,
                  f"8/9: Question fetch skipped (need LEETCODE_SESSION cookie) — {exc}")

    _progress(emit, "db_save", 46, "9/9: Saving to database...")
    summary = _summary_columns(profile, contest_info, calendar["streak"])

    async with async_session_factory() as db:
        stats = await db.scalar(select(LeetCodeStats).where(LeetCodeStats.user_id == user_id))
        if stats is None:
            stats = LeetCodeStats(user_id=user_id)
            db.add(stats)
        for key, value in {
            **summary,
            "username": username,
            "question_progress": question_progress,
            "session_progress": session_progress,
            "skill_stats": skill_stats,
            "language_stats": language_stats,
            "recent_submissions": profile["recentSubmissions"],
            "calendar_data": {"activeYears": calendar["activeYears"], "totalActiveDays": calendar["totalActiveDays"],
                              "submissionCalendar": calendar["submissionCalendar"]},
        }.items():
            setattr(stats, key, value)
        await db.commit()
        _progress(emit, "db_stats_done", 52, "Stats saved to LeetCodeStats")

        if problems:
            await db.execute(delete(LeetCodeProblem).where(LeetCodeProblem.user_id == user_id))
            batch_size = 100
            for i in range(0, len(problems), batch_size):
                batch = problems[i:i + batch_size]
                await db.execute(insert(LeetCodeProblem), [
                    {"user_id": user_id, "title_slug": p["titleSlug"], "title": p["title"],
                     "difficulty": p["difficulty"], "question_status": p["questionStatus"],
                     "last_result": p["lastResult"], "last_submitted_at": p["lastSubmittedAt"],
                     "num_submitted": p["numSubmitted"], "topic_tags": p["topicTags"]}
                    for p in batch
                ])
                _progress(emit, "db_problems", 52 + js_round((i + len(batch)) / len(problems) * 6),
                          f"Saved {min(i + batch_size, len(problems))}/{len(problems)} questions to database...")
            await db.commit()
            _progress(emit, "db_problems_done", 58, f"{len(problems)} questions saved with topic tags")

        await db.execute(delete(LeetCodeContestHistory).where(LeetCodeContestHistory.user_id == user_id))
        if contest_history:
            await db.execute(insert(LeetCodeContestHistory), [
                {"user_id": user_id, "contest_title": e["contest"]["title"], "start_time": e["contest"]["startTime"],
                 "attended": e["attended"], "rating": e["rating"], "ranking": e["ranking"],
                 "trend_direction": e["trendDirection"], "problems_solved": e["problemsSolved"],
                 "total_problems": e["totalProblems"], "finish_time_in_seconds": e["finishTimeInSeconds"]}
                for e in contest_history
            ])
        await db.commit()
        _progress(emit, "db_contests_done", 60, f"{len(contest_history)} contest entries saved")

        db.add(LeetCodeHistory(
            user_id=user_id, username=username, **summary,
            problems_solved_list=[
                {k: p[k] for k in ("titleSlug", "title", "difficulty", "lastResult", "lastSubmittedAt", "topicTags")}
                for p in problems
            ] or None,
            contest_history=[
                {"title": e["contest"]["title"], "startTime": e["contest"]["startTime"], "rating": e["rating"],
                 "ranking": e["ranking"], "problemsSolved": e["problemsSolved"], "totalProblems": e["totalProblems"]}
                for e in contest_history
            ] or None,
            skill_stats=skill_stats, language_stats=language_stats,
        ))
        await db.commit()
        _progress(emit, "history_done", 62, "History snapshot saved")

    _progress(emit, "rag_started", 64, f"Building RAG documents from {len(problems) + 10} data chunks...")
    sync_result = {"profile": profile, "contest": {"info": contest_info, "history": contest_history},
                   "questionProgress": question_progress, "sessionProgress": session_progress,
                   "skillStats": skill_stats, "languageStats": language_stats, "calendar": calendar}
    try:
        rag = await ingest_rag(
            user_id, username, sync_result, problems,
            lambda _stage, pct, msg: _progress(emit, "rag_progress", 64 + js_round(pct / 100 * 36), msg),
        )
        _progress(emit, "completed", 100,
                  f"Sync complete! {profile['totalSolved']} solved, {len(problems)} questions saved, "
                  f"{rag['upserted']} RAG chunks indexed")
    except Exception as exc:
        log.warning("rag_ingest_failed", userId=user_id, err=str(exc))
        _progress(emit, "completed", 100,
                  f"DB sync complete! {profile['totalSolved']} solved, {len(problems)} questions saved. "
                  f"AI indexing skipped: {exc}")

    emit("done", {"stage": "done", "pct": 100, "msg": "Sync finished"})
