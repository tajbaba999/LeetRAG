import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.leetcode import fetcher
from app.main import app

client = TestClient(app)
sent: list[dict[str, Any]] = []


def stub_leetcode(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    """Every GraphQL POST gets `payload`; requests are recorded in `sent`."""
    sent.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append({"body": json.loads(request.content), "headers": request.headers})
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(fetcher, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_calculate_streak_counts_back_from_today() -> None:
    day = 86400
    now = 100 * day + 5
    cal = {str(100 * day): 2, str(99 * day): 1, str(97 * day): 4}
    assert fetcher.calculate_streak(cal, now) == 2
    assert fetcher.calculate_streak({}, now) == 0
    assert fetcher.parse_calendar('{"1": 2}') == {"1": 2}
    assert fetcher.parse_calendar("not json") == {}


def test_profile_maps_graphql_response(monkeypatch: pytest.MonkeyPatch) -> None:
    stats = [
        {"difficulty": "All", "count": 10, "submissions": 40},
        {"difficulty": "Easy", "count": 6, "submissions": 10},
        {"difficulty": "Medium", "count": 3, "submissions": 20},
        {"difficulty": "Hard", "count": 1, "submissions": 10},
    ]
    stub_leetcode(monkeypatch, {"data": {
        "allQuestionsCount": [{"difficulty": "All", "count": 3000}],
        "matchedUser": {
            "profile": {"ranking": 1234, "reputation": 0},
            "submissionCalendar": "{}",
            "submitStats": {"acSubmissionNum": stats, "totalSubmissionNum": stats},
        },
        "recentSubmissionList": [],
        "matchedUserStats": {"submitStats": {"acSubmissionNum": stats, "totalSubmissionNum": stats}},
    }})
    res = client.get("/api/v1/leetcode/profile?username=ada")
    assert res.status_code == 200
    body = res.json()
    assert body["username"] == "ada"
    assert (body["totalSolved"], body["easySolved"], body["hardSolved"]) == (10, 6, 1)
    assert body["acceptanceRate"] == 25
    assert body["totalQuestions"] == 3000
    assert body["totalSubmissions"] == 40
    assert sent[0]["body"]["variables"] == {"username": "ada"}
    assert "cookie" not in sent[0]["headers"]


def test_graphql_errors_become_500_message(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_leetcode(monkeypatch, {"errors": [{"message": "That user does not exist."}], "data": None})
    res = client.get("/api/v1/leetcode/skill-stats?username=ghost")
    assert res.status_code == 500
    assert res.json() == {"message": "Failed to fetch skill stats"}


def test_username_falls_back_to_env_then_400(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_leetcode(monkeypatch, {"data": {"matchedUser": {"languageProblemCount": []}}})
    monkeypatch.setattr(settings, "leetcode_username", "envuser")
    assert client.get("/api/v1/leetcode/language-stats").json() == {"username": "envuser", "languageStats": []}

    monkeypatch.setattr(settings, "leetcode_username", None)
    res = client.get("/api/v1/leetcode/language-stats")
    assert res.status_code == 400


def test_progress_needs_session_and_sends_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "leetcode_session", None)
    assert client.get("/api/v1/leetcode/progress").status_code == 500

    monkeypatch.setattr(settings, "leetcode_session", "sess")
    monkeypatch.setattr(settings, "leetcode_csrf", "tok")
    stub_leetcode(monkeypatch, {"data": {"userProgressQuestionList": {"totalNum": 120, "questions": [{}] * 3}}})
    body = client.get("/api/v1/leetcode/progress?skip=100&limit=abc").json()
    assert body == {"totalNum": 120, "skip": 100, "limit": 50, "hasMore": True, "questions": [{}] * 3}
    assert sent[0]["body"]["variables"] == {"filters": {"skip": 100, "limit": 50}}
    assert "LEETCODE_SESSION=sess" in sent[0]["headers"]["cookie"]
    assert sent[0]["headers"]["x-csrftoken"] == "tok"


def test_catch_all_username_route_is_last(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_leetcode(monkeypatch, {"data": {"matchedUser": None}, "errors": [{"message": "nope"}]})
    # leetcode-query semantics: GraphQL errors are not raised, data is returned as-is.
    assert client.get("/api/v1/leetcode/somebody").json() == {"matchedUser": None}
    assert "query ($username" in sent[0]["body"]["query"]
