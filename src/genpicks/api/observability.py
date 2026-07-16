"""API observability: JSON logs, per-request access lines, optional Sentry.

setup_observability(app) is called once from main.py and does three things:

- routes all API-process logging (including uvicorn's own) through a
  single JSON-lines formatter, so Render's log stream is uniformly
  machine-parseable
- logs one line per request with method, path, status and duration,
  replacing uvicorn's plain-text access log
- initialises Sentry when GENPICKS_SENTRY_DSN is set — error reporting
  activates by pasting a DSN into the deployment environment, no code
  change. Unset, errors still land in the JSON logs with tracebacks.
"""

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request

from genpicks.config import get_settings

logger = logging.getLogger("genpicks.api")

# attributes present on every LogRecord; anything else was passed via
# `extra` and belongs in the JSON output as its own field. color_message
# is uvicorn's ANSI-escape duplicate of its startup messages.
_BASELINE_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message",
    "asctime",
    "taskName",
    "color_message",
}


class JsonFormatter(logging.Formatter):
    """One JSON object per line; `extra` kwargs become top-level fields."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        entry.update({k: v for k, v in vars(record).items() if k not in _BASELINE_ATTRS})
        if record.exc_info:
            entry["traceback"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_observability(app: FastAPI) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # uvicorn configures its loggers (with plain-text handlers and
    # propagate=False) before importing the app, so stripping them here
    # funnels its startup/error output through the JSON root handler
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    # the middleware below logs every request with its duration, so
    # uvicorn's access log would be a duplicate
    logging.getLogger("uvicorn.access").disabled = True

    dsn = get_settings().sentry_dsn
    if dsn:
        import sentry_sdk

        # error reporting only: no performance tracing (free-tier quota),
        # no request bodies or user context
        sentry_sdk.init(dsn=dsn, send_default_pii=False)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        # the keep-warm workflow hits /health every 10 minutes; logging it
        # would bury real traffic
        if request.url.path == "/health":
            return await call_next(request)
        start = time.perf_counter()
        fields: dict[str, Any] = {"method": request.method, "path": request.url.path}
        try:
            response = await call_next(request)
        except Exception:
            # re-raised for Sentry and the 500 handler; logged here so the
            # request line with its duration isn't lost
            fields["duration_ms"] = round((time.perf_counter() - start) * 1000, 1)
            logger.exception("request failed", extra=fields)
            raise
        fields["status"] = response.status_code
        fields["duration_ms"] = round((time.perf_counter() - start) * 1000, 1)
        logger.info("request", extra=fields)
        return response
