import logging
import sys
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings

SERVICE_NAME = "dsa-tracker"


def _add_static_context(
    _logger: object, _method_name: str, event_dict: dict[str, object]
) -> dict[str, object]:
    event_dict.setdefault("env", settings.node_env)
    event_dict.setdefault("service", SERVICE_NAME)
    return event_dict


def configure_logging() -> None:
    level = logging.DEBUG if settings.node_env != "production" else logging.INFO

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if settings.node_env == "production":
        import logging_loki

        handlers.append(
            logging_loki.LokiHandler(
                url=settings.loki_url or "http://loki:3100/loki/api/v1/push",
                tags={"service": SERVICE_NAME},
                version="1",
            )
        )

    logging.basicConfig(level=level, handlers=handlers, format="%(message)s", force=True)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_static_context,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs one structured line per request, mirroring pino-http.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        logger = structlog.get_logger("http")
        request_id = str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(
            request_id=request_id, method=request.method, path=request.url.path
        )
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("request_failed")
            structlog.contextvars.clear_contextvars()
            raise
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info("request_completed", status_code=response.status_code, duration_ms=duration_ms)
        structlog.contextvars.clear_contextvars()
        return response
