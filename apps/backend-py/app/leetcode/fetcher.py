import json
import time
from typing import Any

import httpx

from app.core.config import settings
from app.leetcode import queries

GRAPHQL_URL = "https://leetcode.com/graphql"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://leetcode.com",
    "Origin": "https://leetcode.com",
}

_client = httpx.AsyncClient(headers=HEADERS, timeout=30)


class LeetCodeError(Exception):
    pass


def has_session() -> bool:
    return bool(settings.leetcode_session and settings.leetcode_csrf)


async def graphql(
    query: str, variables: dict[str, Any], *, auth: bool = False, check_errors: bool = True
) -> dict[str, Any]:
    """POSTs one GraphQL document. `auth` attaches LEETCODE_SESSION/CSRF cookies.

    `check_errors=False` mirrors the leetcode-query package, which returns `data`
    even when LeetCode also reports GraphQL errors (graphql-request throws instead).
    """
    headers = {}
    if auth:
        headers = {
            "Cookie": f"csrftoken={settings.leetcode_csrf}; LEETCODE_SESSION={settings.leetcode_session};",
            "x-csrftoken": settings.leetcode_csrf or "",
        }
    res = await _client.post(GRAPHQL_URL, json={"query": query, "variables": variables}, headers=headers)
    res.raise_for_status()
    body = res.json()
    if check_errors and body.get("errors"):
        raise LeetCodeError(body["errors"][0].get("message", "GraphQL error"))
    return body.get("data") or {}


def _find(items: list[dict[str, Any]] | None, difficulty: str) -> dict[str, Any] | None:
    return next((i for i in items or [] if i["difficulty"] == difficulty), None)


def parse_calendar(raw: str | dict[str, int] | None) -> dict[str, int]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def calculate_streak(calendar: dict[str, int], now: float | None = None) -> int:
    """Consecutive days with submissions, counting back from today (UTC day buckets)."""
    day = int((time.time() if now is None else now) // 86400)
    streak = 0
    while calendar.get(str(day * 86400), 0) > 0:
        streak += 1
        day -= 1
    return streak


async def fetch_profile(username: str) -> dict[str, Any]:
    data = await graphql(queries.GET_USER_PROFILE, {"username": username})
    user = data.get("matchedUser")
    if not user:
        raise LeetCodeError(f'LeetCode user "{username}" not found')

    ac = user["submitStats"]["acSubmissionNum"]
    ac_all = _find(ac, "All")
    total_all = _find(((data.get("matchedUserStats") or {}).get("submitStats") or {}).get("totalSubmissionNum"), "All")

    return {
        "username": username,
        "totalSolved": ac_all["count"] if ac_all else 0,
        "totalQuestions": (_find(data.get("allQuestionsCount"), "All") or {}).get("count", 0),
        "easySolved": (_find(ac, "Easy") or {}).get("count", 0),
        "mediumSolved": (_find(ac, "Medium") or {}).get("count", 0),
        "hardSolved": (_find(ac, "Hard") or {}).get("count", 0),
        "ranking": user["profile"]["ranking"],
        "acceptanceRate": ac_all["count"] / (ac_all["submissions"] or 1) * 100 if ac_all else 0,
        "streak": calculate_streak(parse_calendar(user.get("submissionCalendar"))),
        "totalSubmissions": total_all["submissions"] if total_all else 0,
        "recentSubmissions": data.get("recentSubmissionList") or [],
    }


async def fetch_contest(username: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = await graphql(queries.GET_CONTEST_RANKING, {"username": username})
    r = data.get("userContestRanking")
    info = {
        "attendedContestsCount": r["attendedContestsCount"] if r else 0,
        "rating": r["rating"] if r else 0,
        "globalRanking": r["globalRanking"] if r else 0,
        "totalParticipants": r["totalParticipants"] if r else 0,
        "topPercentage": r["topPercentage"] if r else 0,
        "badge": (r.get("badge") or {}).get("name") if r else None,
    }
    history = [
        {
            "attended": e["attended"],
            "rating": e["rating"],
            "ranking": e["ranking"],
            "trendDirection": e["trendDirection"],
            "problemsSolved": e["problemsSolved"],
            "totalProblems": e["totalProblems"],
            "finishTimeInSeconds": e["finishTimeInSeconds"],
            "contest": {"title": e["contest"]["title"], "startTime": e["contest"]["startTime"]},
        }
        for e in data.get("userContestRankingHistory") or []
    ]
    return info, history


async def fetch_question_progress(username: str) -> dict[str, Any]:
    data = await graphql(queries.GET_QUESTION_PROGRESS, {"username": username})
    p = data.get("userProfileUserQuestionProgressV2")
    if not p:
        raise LeetCodeError(f'Question progress not found for "{username}"')
    keys = ("numAcceptedQuestions", "numFailedQuestions", "numUntouchedQuestions",
            "userSessionBeatsPercentage", "totalQuestionBeatsPercentage")
    return {k: p[k] for k in keys}


async def fetch_session_progress(username: str) -> dict[str, Any]:
    data = await graphql(queries.GET_SESSION_PROGRESS, {"username": username})
    user = data.get("matchedUser")
    if not user:
        raise LeetCodeError(f'Session progress not found for "{username}"')
    return {
        "allQuestionsCount": data["allQuestionsCount"],
        "acSubmissionNum": user["submitStats"]["acSubmissionNum"],
        "totalSubmissionNum": user["submitStats"]["totalSubmissionNum"],
    }


async def fetch_skill_stats(username: str) -> dict[str, Any]:
    data = await graphql(queries.GET_SKILL_STATS, {"username": username})
    user = data.get("matchedUser")
    if not user:
        raise LeetCodeError(f'Skill stats not found for "{username}"')
    counts = user["tagProblemCounts"]
    return {k: counts[k] for k in ("fundamental", "intermediate", "advanced")}


async def fetch_language_stats(username: str) -> list[dict[str, Any]]:
    data = await graphql(queries.GET_LANGUAGE_STATS, {"username": username})
    return (data.get("matchedUser") or {}).get("languageProblemCount") or []


async def fetch_calendar(username: str, year: int | None = None) -> dict[str, Any]:
    data = await graphql(queries.GET_CALENDAR, {"username": username, "year": year})
    cal = (data.get("matchedUser") or {}).get("userCalendar") or {}
    return {
        "activeYears": cal.get("activeYears") or [],
        "streak": cal.get("streak") or 0,
        "totalActiveDays": cal.get("totalActiveDays") or 0,
        "dccBadges": cal.get("dccBadges") or [],
        "submissionCalendar": parse_calendar(cal.get("submissionCalendar")),
    }


async def fetch_public_profile(username: str) -> dict[str, Any]:
    return await graphql(queries.GET_PUBLIC_PROFILE, {"username": username}, check_errors=False)


async def fetch_progress_questions(skip: int, limit: int) -> dict[str, Any]:
    """Raw userProgressQuestionList for the LEETCODE_SESSION account (leetcode-query behavior)."""
    data = await graphql(
        queries.GET_USER_PROGRESS_QUESTIONS, {"filters": {"skip": skip, "limit": limit}},
        auth=True, check_errors=False,
    )
    result = data.get("userProgressQuestionList")
    if result is None:
        raise LeetCodeError("userProgressQuestionList returned null (is LEETCODE_SESSION valid?)")
    return result


async def fetch_user_questions(skip: int = 0, limit: int = 50) -> dict[str, Any]:
    """Normalized question list, as used by the coding-profile sync helpers.

    Sends no session cookie, same as the Express version.
    """
    data = await graphql(queries.GET_USER_PROGRESS_QUESTIONS, {"filters": {"skip": skip, "limit": limit}})
    result = data.get("userProgressQuestionList")
    if not result:
        return {"totalNum": 0, "questions": []}
    return {
        "totalNum": result["totalNum"],
        "questions": [
            {
                "frontendId": q["frontendId"],
                "title": q.get("translatedTitle") or q["title"],
                "titleSlug": q["titleSlug"],
                "difficulty": q["difficulty"],
                "lastSubmittedAt": q.get("lastSubmittedAt") or "",
                "numSubmitted": q["numSubmitted"],
                "questionStatus": q["questionStatus"],
                "lastResult": q["lastResult"],
                "topicTags": [
                    {"name": t["name"], "nameTranslated": t.get("nameTranslated") or t["name"], "slug": t["slug"]}
                    for t in q["topicTags"]
                ],
            }
            for q in result["questions"]
        ],
    }
