"""End-to-end /codingprofile tests against a real, disposable Postgres.

Opt-in: INTEGRATION_DB=1 DATABASE_URL=<throwaway db> uv run python -m pytest tests/test_codingprofile.py
Tables are created and dropped by the test, so never point this at a real database.
"""

import json
import os
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.codingprofile import extract_username
from app.core.security import generate_access_token
from app.db.models import Base, User
from app.db.session import async_session_factory, engine
from app.leetcode import fetcher
from app.main import app

pytestmark = pytest.mark.skipif(os.environ.get("INTEGRATION_DB") != "1", reason="needs INTEGRATION_DB=1")

DAY = 86400
STATS = [
    {"difficulty": "All", "count": 10, "submissions": 20},
    {"difficulty": "Easy", "count": 5, "submissions": 8},
    {"difficulty": "Medium", "count": 4, "submissions": 9},
    {"difficulty": "Hard", "count": 1, "submissions": 3},
]
LEETCODE: dict[str, dict[str, Any]] = {
    "getUserProfile": {
        "allQuestionsCount": [{"difficulty": "All", "count": 3000}],
        "matchedUser": {"profile": {"ranking": 500}, "submissionCalendar": "{}",
                        "submitStats": {"acSubmissionNum": STATS, "totalSubmissionNum": STATS}},
        "recentSubmissionList": [{"title": "Two Sum", "titleSlug": "two-sum", "timestamp": "1",
                                  "statusDisplay": "Accepted", "lang": "python3"}],
        "matchedUserStats": {"submitStats": {"acSubmissionNum": STATS, "totalSubmissionNum": STATS}},
    },
    "userContestRankingInfo": {
        "userContestRanking": {"attendedContestsCount": 2, "rating": 1600.4, "globalRanking": 9000,
                               "totalParticipants": 100000, "topPercentage": 12.5, "badge": None},
        "userContestRankingHistory": [
            {"attended": True, "trendDirection": "UP", "problemsSolved": 3, "totalProblems": 4,
             "finishTimeInSeconds": 3000, "rating": 1550.0, "ranking": 800,
             "contest": {"title": "Weekly Contest 1", "startTime": 1700000000}},
        ],
    },
    "userProfileUserQuestionProgressV2": {"userProfileUserQuestionProgressV2": {
        "numAcceptedQuestions": [], "numFailedQuestions": [], "numUntouchedQuestions": [],
        "userSessionBeatsPercentage": [], "totalQuestionBeatsPercentage": 50.0}},
    "userSessionProgress": {"allQuestionsCount": [], "matchedUser": {
        "submitStats": {"acSubmissionNum": STATS, "totalSubmissionNum": STATS}}},
    "skillStats": {"matchedUser": {"tagProblemCounts": {
        "fundamental": [{"tagName": "Array", "tagSlug": "array", "problemsSolved": 10}],
        "intermediate": [{"tagName": "Hash Table", "tagSlug": "hash-table", "problemsSolved": 3}],
        "advanced": [],
    }}},
    "languageStats": {"matchedUser": {"languageProblemCount": [{"languageName": "Python3", "problemsSolved": 10}]}},
    "userProfileCalendar": {"matchedUser": {"userCalendar": {
        "activeYears": [2024], "streak": 2, "totalActiveDays": 3, "dccBadges": [],
        "submissionCalendar": json.dumps({str(19723 * DAY): 2, str(19724 * DAY): 1, str(19754 * DAY): 4}),
    }}},
    # No session cookie -> LeetCode returns null here (same as production today).
    "userProgressQuestionList": {"userProgressQuestionList": None},
}


def leetcode_handler(request: httpx.Request) -> httpx.Response:
    query = json.loads(request.content)["query"]
    name = next(k for k in LEETCODE if f"query {k}" in query)
    return httpx.Response(200, json={"data": LEETCODE[name]})


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    fetcher._client = httpx.AsyncClient(transport=httpx.MockTransport(leetcode_handler))

    async def setup() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with async_session_factory() as db:
            db.add(User(id="u1", name="Ada", email="ada@example.com", password="x"))
            await db.commit()

    async def teardown() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    with TestClient(app) as c:
        c.portal.call(setup)  # type: ignore[union-attr]
        c.headers["Authorization"] = f"Bearer {generate_access_token({'userId': 'u1', 'email': 'ada@example.com'})}"
        yield c
        c.portal.call(teardown)  # type: ignore[union-attr]


def sse_events(res: httpx.Response) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for frame in res.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in frame.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_extract_username() -> None:
    assert extract_username("https://leetcode.com/u/ada/") == "ada"
    assert extract_username("ada") == "ada"


def test_full_flow(client: TestClient) -> None:
    assert client.get("/api/v1/codingprofile/").status_code == 404
    assert client.post("/api/v1/codingprofile/sync").status_code == 404

    res = client.post("/api/v1/codingprofile/initial-sync", json={"leetcode": "https://leetcode.com/u/ada/"})
    assert res.headers["content-type"].startswith("text/event-stream")
    events = sse_events(res)
    assert events[-1] == ("done", {"stage": "done", "pct": 100, "msg": "Sync finished"})
    assert not [e for e in events if e[0] == "error"]
    stages = [d["stage"] for _, d in events]
    assert "fetch_questions_done" in stages and "history_done" in stages
    assert "AI indexing skipped" in next(d["msg"] for _, d in events if d["stage"] == "completed")

    body = client.get("/api/v1/codingprofile/").json()
    assert body["profiles"]["leetcode"] == "ada"
    leetcode = body["stats"]["leetcode"]
    assert (leetcode["totalSolved"], leetcode["streak"], leetcode["contestRating"]) == (10, 2, 1600.4)
    assert leetcode["recentSubmissions"][0]["titleSlug"] == "two-sum"
    assert body["counts"] == {"problems": 0, "contests": 1}

    # Second sync: stats upserted (not duplicated), contests replaced, new snapshot.
    LEETCODE["getUserProfile"]["matchedUser"]["submitStats"]["acSubmissionNum"] = [
        {**s, "count": s["count"] + (2 if s["difficulty"] in ("All", "Easy") else 0)} for s in STATS
    ]
    LEETCODE["userContestRankingInfo"]["userContestRanking"]["rating"] = 1580.4
    assert sse_events(client.post("/api/v1/codingprofile/sync"))[-1][0] == "done"
    assert client.get("/api/v1/codingprofile/").json()["counts"] == {"problems": 0, "contests": 1}

    history = client.get("/api/v1/codingprofile/history?limit=5").json()
    assert history["total"] == 2
    assert [s["totalSolved"] for s in history["snapshots"]] == [12, 10]
    assert history["snapshots"][0]["snapshotAt"].endswith("+00:00")

    diff = client.get("/api/v1/codingprofile/history/diff").json()["diff"]
    assert (diff["totalSolved"], diff["easy"], diff["hard"], diff["contestRating"]) == (2, 2, 0, -20)


def test_activity_questions_topic_matrix(client: TestClient) -> None:
    act = client.get("/api/v1/codingprofile/activity").json()
    assert [d["date"] for d in act["submissions"]] == ["2024-01-01", "2024-01-02", "2024-02-01"]
    assert act["submissions"][0]["dayOfWeek"] == 1  # 2024-01-01 was a Monday
    assert act["totalSubmissions"] == 7

    jan = client.get("/api/v1/codingprofile/activity?year=2024&month=1").json()
    assert (jan["totalDaysActive"], jan["query"]) == (2, {"year": 2024, "month": 1})

    q = client.get("/api/v1/codingprofile/questions").json()
    assert (q["total"], q["questions"], q["difficulty"]) == (0, [], "all")

    # No problem rows -> estimate from skillStats using the latest easy/medium/hard split (7/4/1).
    matrix = {row["topic"]: row for row in client.get("/api/v1/codingprofile/topic-matrix").json()}
    assert len(matrix) == 18
    total = 7 + 4 + 1
    array = matrix["Array"]
    assert array["easy"] + array["medium"] + array["hard"] == 10
    assert array["easy"] == int(10 * 7 / total + 0.5)
    assert matrix["Graph"] == {"topic": "Graph", "easy": 0, "medium": 0, "hard": 0}


def test_signup_and_profile_against_real_db(client: TestClient) -> None:
    # Regression: tz-aware updatedAt values made every real INSERT fail.
    res = client.post("/api/v1/signup", json={"name": "Bo", "email": "bo@example.com", "password": "Passw0rd!"})
    assert res.status_code == 201
    token = res.json()["accessToken"]
    me = client.get("/api/v1/profile", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["email"] == "bo@example.com"
