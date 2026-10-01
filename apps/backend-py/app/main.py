from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.api import auth, leetcode, profile
from app.core.config import settings
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.core.metrics import PrometheusMiddleware
from app.core.security import get_current_user

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


api_v1.include_router(auth.router)
api_v1.include_router(leetcode.router)

# Everything below requires a valid access token, same as Express's
# router.use(authenticateToken) placed after the public routes.
protected = APIRouter(dependencies=[Depends(get_current_user)])
protected.include_router(profile.router)
api_v1.include_router(protected)


# The frontend reads `body.error || body.message`, so errors keep the Express
# shapes instead of FastAPI's default {"detail": ...}.
async def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    messages = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"][1:]) or "body"
        messages.append(f"{field}: {err['msg'].removeprefix('Value error, ')}")
    return JSONResponse({"error": "; ".join(messages)}, status_code=422)


async def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    return JSONResponse({"message": exc.detail}, status_code=exc.status_code, headers=exc.headers)


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title="LeetPlus API",
        debug=settings.node_env == "development",
        docs_url="/docs" if settings.node_env != "production" else None,
        redoc_url="/redoc" if settings.node_env != "production" else None,
    )
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)

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
