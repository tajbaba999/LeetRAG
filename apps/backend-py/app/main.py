from fastapi import APIRouter, FastAPI

from app.core.config import settings

api_v1 = APIRouter(prefix="/api/v1")


@api_v1.get("/")
async def api_root() -> dict[str, str]:
    return {"message": "API - 👋🌎🌍🌏"}


def create_app() -> FastAPI:
    app = FastAPI(
        title="LeetPlus API",
        debug=settings.node_env == "development",
        docs_url="/docs" if settings.node_env != "production" else None,
        redoc_url="/redoc" if settings.node_env != "production" else None,
    )

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"message": "🦄🌈✨👋🌎🌍🌏✨🌈🦄"}

    app.include_router(api_v1)

    return app


app = create_app()
