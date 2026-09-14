from collections.abc import Awaitable, Callable

from fastapi import APIRouter, FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.core.metrics import PrometheusMiddleware

api_v1 = APIRouter(prefix="/api/v1")

# Subset of helmet()'s default headers that are meaningful for a JSON-only API.
# Content-Security-Policy is deliberately omitted: it governs what a browser
# page may load, which doesn't apply to an API that only ever returns JSON.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "X-DNS-Prefetch-Control": "off",
    "X-Download-Options": "noopen",
    "X-Permitted-Cross-Domain-Policies": "none",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Origin-Agent-Cluster": "?1",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-XSS-Protection": "0",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response


@api_v1.get("/")
async def api_root() -> dict[str, str]:
    return {"message": "API - 👋🌎🌍🌏"}


# Public: stays outside any future auth-required grouping, same as Express
# mounting /metrics before the authenticateToken gate.
@api_v1.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title="LeetPlus API",
        debug=settings.node_env == "development",
        docs_url="/docs" if settings.node_env != "production" else None,
        redoc_url="/redoc" if settings.node_env != "production" else None,
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(PrometheusMiddleware)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"message": "🦄🌈✨👋🌎🌍🌏✨🌈🦄"}

    app.include_router(api_v1)

    return app


app = create_app()
