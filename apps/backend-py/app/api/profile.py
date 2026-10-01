from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.db.models import User
from app.db.session import get_db

router = APIRouter()


@router.get("/profile", response_model=None)
async def get_profile(
    user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, object] | JSONResponse:
    row = await db.get(User, user["userId"])
    if row is None:
        return JSONResponse({"error": "User not found"}, status_code=404)
    # Prisma stores UTC in a naive timestamp column; tag it so JSON gets a "Z" like Express sent.
    return {
        "id": row.id,
        "name": row.name,
        "email": row.email,
        "createdAt": row.created_at.replace(tzinfo=UTC),
        "updatedAt": row.updated_at.replace(tzinfo=UTC),
    }
