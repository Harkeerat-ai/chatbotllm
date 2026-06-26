from __future__ import annotations

import json
import logging
import sys

import pytest

from app.observability import JSONFormatter, init_logging


def _make_record(msg: str, level: int = logging.INFO, exc_info: bool = False) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test_logger",
        level=level,
        pathname=__file__,
        lineno=42,
        msg=msg,
        args=(),
        exc_info=None,
        func="test_func",
    )
    if exc_info:
        try:
            raise ValueError("test error")
        except ValueError:
            record.exc_info = sys.exc_info()
    return record


def test_json_format_basic():
    formatter = JSONFormatter()
    record = _make_record("hello world")
    output = formatter.format(record)
    data = json.loads(output)

    assert data["level"] == "INFO"
    assert data["logger"] == "test_logger"
    assert data["message"] == "hello world"
    assert "timestamp" in data


def test_json_format_with_extra():
    formatter = JSONFormatter()
    record = _make_record("with extra")
    record.user_id = "abc123"
    record.request_id = "req-456"
    output = formatter.format(record)
    data = json.loads(output)

    assert data["user_id"] == "abc123"
    assert data["request_id"] == "req-456"


def test_json_format_with_exc_info():
    formatter = JSONFormatter()
    record = _make_record("error occurred", level=logging.ERROR, exc_info=True)
    output = formatter.format(record)
    data = json.loads(output)

    assert "exc_info" in data
    assert isinstance(data["exc_info"], str)
    assert "ValueError" in data["exc_info"]
    assert "test error" in data["exc_info"]


def test_json_format_excludes_private_attrs():
    formatter = JSONFormatter()
    record = _make_record("private check")
    record._internal = "should not appear"
    record.public = "should appear"
    output = formatter.format(record)
    data = json.loads(output)

    assert "public" in data
    assert data["public"] == "should appear"
    assert "_internal" not in data


def test_init_logging():
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        init_logging(logging.DEBUG)
        assert root.level == logging.DEBUG
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JSONFormatter)
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)


def test_noop_metrics_do_not_crash():
    from app.observability import Counter, Histogram

    c = Counter("test_total", "desc", ["label"])
    c.labels(label="x").inc()
    c.inc()

    h = Histogram("test_seconds", "desc", ["label"])
    h.labels(label="x").observe(1.0)
    h.observe(0.5)

    assert True  # reached without exception
