from datetime import datetime

from fastapi.testclient import TestClient

from app.core.security import generate_access_token, generate_refresh_token, hash_password
from app.db.models import User
from app.db.session import get_db
from app.main import app


class FakeDb:
    """Just enough AsyncSession for the auth/profile routes: one in-memory user table."""

    def __init__(self) -> None:
        self.users: dict[str, User] = {}

    async def scalar(self, stmt: object) -> User | None:
        email = stmt.whereclause.right.value  # type: ignore[attr-defined]
        return next((u for u in self.users.values() if u.email == email), None)

    async def get(self, _model: type, user_id: str) -> User | None:
        return self.users.get(user_id)

    def add(self, user: User) -> None:
        user.id = user.id or "u-1"
        self.users[user.id] = user

    async def commit(self) -> None:
        pass


db = FakeDb()
app.dependency_overrides[get_db] = lambda: db
client = TestClient(app)

GOOD = {"name": "Ada", "email": "ada@example.com", "password": "Passw0rd!"}


def test_signup_validation_uses_express_error_shape() -> None:
    res = client.post("/api/v1/signup", json={**GOOD, "password": "password"})
    assert res.status_code == 422
    assert "uppercase" in res.json()["error"]


def test_signup_signin_and_duplicate() -> None:
    db.users.clear()
    res = client.post("/api/v1/signup", json=GOOD)
    assert res.status_code == 201
    assert set(res.json()) == {"accessToken", "refreshToken"}

    assert client.post("/api/v1/signup", json=GOOD).json() == {"error": "User already exists"}

    ok = client.post("/api/v1/signin", json={"email": GOOD["email"], "password": GOOD["password"]})
    assert ok.status_code == 200
    bad = client.post("/api/v1/signin", json={"email": GOOD["email"], "password": "nope"})
    assert bad.status_code == 401
    missing = client.post("/api/v1/signin", json={"email": "x@example.com", "password": "x"})
    assert missing.status_code == 404


def test_signin_accepts_hash_from_node_bcrypt() -> None:
    # $2b$10$ hash of "Passw0rd!" produced by the Express backend's bcrypt.hashSync.
    db.users.clear()
    db.add(User(id="u-node", name="N", email="n@example.com",
                password="$2b$10$LQ7jh8xF3U.5C3Po8nph..6mj2LVR0zm2V4yWFAQWH1nUX.lxvOqO"))
    res = client.post("/api/v1/signin", json={"email": "n@example.com", "password": "Passw0rd!"})
    assert res.status_code == 200


def test_refresh_token() -> None:
    refresh = generate_refresh_token({"userId": "u-1", "email": "a@b.co"})
    assert "accessToken" in client.post("/api/v1/refresh-token", json={"refreshToken": refresh}).json()

    # An access token must not be accepted as a refresh token (different secret).
    access = generate_access_token({"userId": "u-1", "email": "a@b.co"})
    assert client.post("/api/v1/refresh-token", json={"refreshToken": access}).status_code == 401


def test_protected_routes_require_access_token() -> None:
    assert client.get("/api/v1/profile").json() == {"message": "Unauthorized"}
    res = client.get("/api/v1/profile", headers={"Authorization": "Bearer garbage"})
    assert res.status_code == 401
    assert res.json() == {"message": "Invalid or expired token"}

    db.users.clear()
    now = datetime(2026, 1, 1)
    db.add(User(id="u-9", name="P", email="p@example.com", password=hash_password("x"),
                created_at=now, updated_at=now))
    token = generate_access_token({"userId": "u-9", "email": "p@example.com"})
    res = client.get("/api/v1/profile", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["createdAt"] == "2026-01-01T00:00:00+00:00"
    assert "password" not in res.json()
