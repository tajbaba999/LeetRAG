import asyncio
import re
from typing import Annotated

import jwt
import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    TokenPayload,
    generate_access_token,
    generate_refresh_token,
    hash_password,
    verify_password,
    verify_refresh_token,
)
from app.db.models import User
from app.db.session import get_db

router = APIRouter()
log = structlog.get_logger("auth")

Db = Annotated[AsyncSession, Depends(get_db)]


class SignupRequest(BaseModel):
    name: str
    email: EmailStr
    password: str

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Name must be at least 2 characters")
        return v

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one number")
        if not re.search(r"[^a-zA-Z0-9]", v):
            raise ValueError("Password must contain at least one special character")
        return v


class SigninRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class RefreshTokenRequest(BaseModel):
    refreshToken: str

    @field_validator("refreshToken")
    @classmethod
    def _strip(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Refresh token is required")
        return v.strip()


def _tokens(user: User) -> dict[str, str]:
    payload: TokenPayload = {"userId": user.id, "email": user.email}
    return {"accessToken": generate_access_token(payload), "refreshToken": generate_refresh_token(payload)}


@router.post("/signup", status_code=201, response_model=None)
async def signup(body: SignupRequest, db: Db) -> dict[str, str] | JSONResponse:
    if await db.scalar(select(User).where(User.email == body.email)):
        log.warning("signup_email_taken", email=body.email)
        return JSONResponse({"error": "User already exists"}, status_code=400)

    password = await asyncio.to_thread(hash_password, body.password)
    user = User(name=body.name, email=body.email, password=password)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:  # lost a race with a concurrent signup for the same email
        await db.rollback()
        return JSONResponse({"error": "User already exists"}, status_code=400)

    log.info("user_registered", userId=user.id, email=user.email)
    return _tokens(user)


@router.post("/signin", response_model=None)
async def signin(body: SigninRequest, db: Db) -> dict[str, str] | JSONResponse:
    user = await db.scalar(select(User).where(User.email == body.email))
    if user is None:
        log.warning("signin_unknown_email", email=body.email)
        return JSONResponse({"error": "User not found"}, status_code=404)

    if not await asyncio.to_thread(verify_password, body.password, user.password):
        log.warning("signin_bad_password", userId=user.id)
        return JSONResponse({"error": "Invalid password"}, status_code=401)

    log.info("user_signed_in", userId=user.id)
    return _tokens(user)


@router.post("/refresh-token", response_model=None)
async def refresh_token(body: RefreshTokenRequest) -> dict[str, str] | JSONResponse:
    try:
        payload = verify_refresh_token(body.refreshToken)
    except (jwt.PyJWTError, KeyError):
        log.warning("refresh_token_invalid")
        return JSONResponse(
            {"error": "Refresh token is invalid or expired, please log in again"}, status_code=401
        )
    return {"accessToken": generate_access_token(payload)}
