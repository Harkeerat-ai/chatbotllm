from __future__ import annotations
import json
import logging
from datetime import datetime
from typing import Dict

try:
    from prometheus_client import Counter, Histogram
except Exception:
    # prometheus_client may not be installed in all environments (tests, dev).
    # Provide no-op stand-ins so observability imports don't fail.
    class _NoopMetric:
        def __init__(self, *args, **kwargs):
            pass

        def labels(self, *args, **kwargs):
            return self

        def inc(self, amount: int = 1):
            return None

        def observe(self, value: float):
            return None

    Counter = _NoopMetric
    Histogram = _NoopMetric


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        default_keys = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
        }

        record_dict: Dict[str, object] = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include any extra attributes on the record for structured logging
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in default_keys and not k.startswith("_")
        }
        if extras:
            record_dict.update(extras)

        if record.exc_info:
            record_dict["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(record_dict, default=str)


# Prometheus metrics
CHAT_REQUESTS = Counter(
    "app_chat_requests_total",
    "Total chat requests",
    ["brand", "outcome"],
)

CHAT_LATENCY = Histogram(
    "app_chat_latency_seconds",
    "Chat request latency in seconds",
    ["brand"],
)

CHROMA_QUERIES = Counter(
    "app_chroma_queries_total",
    "Chroma queries executed",
    ["brand"],
)

CHROMA_ERRORS = Counter(
    "app_chroma_errors_total",
    "Chroma query errors",
    ["brand"],
)

INGEST_BATCHES = Counter(
    "app_ingest_batches_total",
    "Ingest batches upserted to Chroma",
    ["brand"],
)

INGEST_LATENCY = Histogram(
    "app_ingest_latency_seconds",
    "Ingest request latency in seconds",
    ["brand"],
)

OLLAMA_CALLS = Counter(
    "app_ollama_calls_total",
    "Ollama API calls",
    ["type", "status"],
)

OLLAMA_LATENCY = Histogram(
    "app_ollama_latency_seconds",
    "Ollama call latency",
    ["type"],
)

TRACKING_LOOKUPS = Counter(
    "app_tracking_lookups_total",
    "Tracking lookups",
    ["brand", "result"],
)


def init_logging(level: int = logging.INFO) -> None:
    """Initialize root logger with JSONFormatter."""
    root = logging.getLogger()
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root.handlers = []
    root.addHandler(handler)
    root.setLevel(level)
