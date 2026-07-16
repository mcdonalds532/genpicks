"""JSON log formatting and the per-request access log."""

import json
import logging
import sys

from fastapi.testclient import TestClient

from genpicks.api.main import app
from genpicks.api.observability import JsonFormatter


def format_record(**kwargs) -> dict:
    logger = logging.getLogger("genpicks.test")
    record = logger.makeRecord(
        "genpicks.test", logging.INFO, __file__, 1, "hello %s", ("world",), None, extra=kwargs
    )
    return json.loads(JsonFormatter().format(record))


def test_formatter_emits_message_and_extras_as_fields():
    entry = format_record(method="GET", duration_ms=1.5)
    assert entry["message"] == "hello world"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "genpicks.test"
    assert entry["method"] == "GET"
    assert entry["duration_ms"] == 1.5
    assert "ts" in entry


def test_formatter_includes_traceback():
    logger = logging.getLogger("genpicks.test")
    try:
        raise ValueError("boom")
    except ValueError:
        record = logger.makeRecord(
            "genpicks.test", logging.ERROR, __file__, 1, "failed", (), sys.exc_info()
        )
    entry = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in entry["traceback"]


def test_request_log_carries_method_path_status_duration(caplog):
    with caplog.at_level(logging.INFO, logger="genpicks.api"), TestClient(app) as client:
        client.get("/no-such-route")
    (record,) = [r for r in caplog.records if r.name == "genpicks.api"]
    assert record.method == "GET"
    assert record.path == "/no-such-route"
    assert record.status == 404
    assert record.duration_ms >= 0


def test_health_pings_are_not_logged(caplog):
    """The keep-warm workflow polls /health every 10 minutes."""
    with caplog.at_level(logging.INFO, logger="genpicks.api"), TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
    assert not [r for r in caplog.records if r.name == "genpicks.api"]
