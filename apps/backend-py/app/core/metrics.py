import time
from collections.abc import Awaitable, Callable

from prometheus_client import Counter, Gauge, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

APP_LABEL = "dsa-tracker"

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "Duration of HTTP requests in seconds",
    ["method", "route", "status_code", "app_kubernetes_io_name"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5),
)

http_request_total = Counter(
    "http_request_total",
    "Total number of HTTP requests",
    ["method", "route", "status_code", "app_kubernetes_io_name"],
)

http_requests_in_flight = Gauge(
    "http_requests_in_flight",
    "Number of HTTP requests currently being served",
    ["app_kubernetes_io_name"],
)

# Used by the ARQ sync workers (ported in steps 18-20), defined here upfront
# alongside the HTTP metrics, mirroring lib/metrics.ts.
sync_job_duration_seconds = Histogram(
    "sync_job_duration_seconds",
    "Duration of sync jobs in seconds",
    ["platform", "status"],
    buckets=(1, 5, 10, 30, 60, 120),
)

sync_job_total = Counter(
    "sync_job_total",
    "Total number of sync jobs",
    ["platform", "status"],
)

sync_jobs_in_flight = Gauge(
    "sync_jobs_in_flight",
    "Number of sync jobs currently running",
    ["platform"],
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Tracks request count/duration/in-flight, mirroring middlewares/prometheus.ts."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        http_requests_in_flight.labels(APP_LABEL).inc()
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            http_requests_in_flight.labels(APP_LABEL).dec()

        route = request.scope.get("route")
        route_path = route.path if route is not None else request.url.path
        duration = time.perf_counter() - start
        labels = (request.method, route_path, response.status_code, APP_LABEL)

        http_request_duration_seconds.labels(*labels).observe(duration)
        http_request_total.labels(*labels).inc()

        return response
