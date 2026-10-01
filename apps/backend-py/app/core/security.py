from datetime import UTC, datetime, timedelta
from typing import Annotated, TypedDict

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

ACCESS_TOKEN_EXPIRY = timedelta(minutes=15)
REFRESH_TOKEN_EXPIRY = timedelta(days=7)
SALT_ROUNDS = 10


class TokenPayload(TypedDict):
    userId: str
    email: str


def _sign(payload: TokenPayload, secret: str, expires_in: timedelta) -> str:
    now = datetime.now(UTC)
    return jwt.encode({**payload, "iat": now, "exp": now + expires_in}, secret, algorithm="HS256")


def _verify(token: str, secret: str) -> TokenPayload:
    claims = jwt.decode(token, secret, algorithms=["HS256"])
    return {"userId": claims["userId"], "email": claims["email"]}


def generate_access_token(payload: TokenPayload) -> str:
    return _sign(payload, settings.jwt_access_secret, ACCESS_TOKEN_EXPIRY)


def generate_refresh_token(payload: TokenPayload) -> str:
    return _sign(payload, settings.jwt_refresh_secret, REFRESH_TOKEN_EXPIRY)


def verify_access_token(token: str) -> TokenPayload:
    return _verify(token, settings.jwt_access_secret)


def verify_refresh_token(token: str) -> TokenPayload:
    return _verify(token, settings.jwt_refresh_secret)


# Node's bcrypt silently truncates to 72 bytes; bcrypt>=5 raises instead.
# Truncating here keeps hashes made by the Express backend verifiable.
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(SALT_ROUNDS)).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode()[:72], hashed.encode())


_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> TokenPayload:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        return verify_access_token(credentials.credentials)
    except (jwt.PyJWTError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None


CurrentUser = Annotated[TokenPayload, Depends(get_current_user)]
