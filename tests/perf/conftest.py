"""Shared fixtures and mocks for performance benchmarks."""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import AsyncGenerator

import pytest

from app.config import get_settings
from app.ollama_client import OllamaClient

# ---------------------------------------------------------------------------
# Configuration via env vars
# ---------------------------------------------------------------------------
PERF_COLLECTION_SIZE = int(os.environ.get("PERF_COLLECTION_SIZE", "200"))


# ---------------------------------------------------------------------------
# Timed mock for Ollama streaming
# ---------------------------------------------------------------------------

class TimedMockStream:
    """Simulate Ollama streaming with configurable latency profile.

    Yields JSON-lines mimicking Ollama's streaming format at the specified
    cadence so benchmarks measure realistic wait times.
    """

    def __init__(
        self,
        first_token_ms: int = 50,
        inter_token_ms: int = 10,
        token_count: int = 100,
    ):
        self.first_token_ms = first_token_ms
        self.inter_token_ms = inter_token_ms
        self.token_count = token_count
        self.token_text = "token " * token_count
        self._tokens = self.token_text.split()
        self._idx = 0

    async def generate(self) -> AsyncGenerator[str, None]:
        """Yields JSON-line chunks with realistic timing."""
        for i, t in enumerate(self._tokens):
            delay = self.first_token_ms if i == 0 else self.inter_token_ms
            await asyncio.sleep(delay / 1000.0)
            chunk = json.dumps({"message": {"content": t + " "}})
            yield chunk + "\n"
        # final done marker
        yield json.dumps({"done": True}) + "\n"


class MockResponse:
    def __init__(self, stream_gen):
        self._gen = stream_gen
        self.status_code = 200

    async def aiter_text(self):
        async for chunk in self._gen():
            yield chunk


class MockStreamContext:
    def __init__(self, stream_gen):
        self.response = MockResponse(stream_gen)

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *a):
        pass


class MockTimedAsyncClient:
    """Replaces httpx.AsyncClient for streaming benchmarks.

    Pass a stream_generator callable to control latency profile.
    When instantiated (``httpx.AsyncClient(timeout=...)``) returns self,
    so it can be used directly with ``unittest.mock.patch`` as the replacement class.
    """

    def __init__(self, stream_generator, **kwargs):
        self._stream_gen = stream_generator

    def __call__(self, *args, **kwargs):
        """Make instances callable so they can replace httpx.AsyncClient directly."""
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    def stream(self, method, url, **kw):
        return MockStreamContext(self._stream_gen)


@pytest.fixture
def mock_timed_client():
    """Returns a factory: mock_timed_client(first_token_ms, inter_token_ms, token_count)."""
    def _factory(first_token_ms=50, inter_token_ms=10, token_count=100):
        stream = TimedMockStream(first_token_ms, inter_token_ms, token_count)
        return MockTimedAsyncClient(stream.generate)
    return _factory


# ---------------------------------------------------------------------------
# Brand + Chroma collection setup
# ---------------------------------------------------------------------------

@pytest.fixture
def brand_with_collection(db_session, monkeypatch):
    """Create a brand and a Chroma collection pre-populated with documents.

    Size controlled by PERF_COLLECTION_SIZE env var (default 200).
    Uses in-memory Chroma to avoid file I/O noise.
    """
    import chromadb
    import app.chroma_client as chroma_client

    # Patch chroma to use in-memory client
    monkeypatch.setattr(chroma_client, "get_client", lambda: chromadb.Client())
    monkeypatch.setattr(chroma_client, "_build_embedding_function", lambda: None)

    from app.brand_service import brand_service
    brand = brand_service.get_or_create(db_session, "perf-bench-brand")

    coll = chroma_client.get_collection(brand.slug)
    ids = []
    docs = []
    metas = []
    for i in range(PERF_COLLECTION_SIZE):
        ids.append(f"doc_{i}")
        docs.append(f"Performance benchmark document number {i}. This document contains sample text for vector similarity search testing.")
        metas.append({"source_name": f"perf_source_{i % 10}", "index": i})
    coll.upsert(ids=ids, documents=docs, metadatas=metas)

    return brand, coll


# ---------------------------------------------------------------------------
# Memory tracking fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def track_memory(request):
    """Fixture that wraps a benchmark with tracemalloc memory tracking.

    Records peak memory (MB) into benchmark.extra_info['peak_memory_mb'].
    Use alongside the ``benchmark`` fixture:
        def test_foo(benchmark, track_memory):
            result = benchmark(some_func)
    """
    import tracemalloc

    tracemalloc.start()
    yield
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    try:
        if hasattr(request.node, "benchmark"):
            request.node.benchmark.extra_info.setdefault("peak_memory_mb", peak / 1_048_576)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Bare-minimum Ollama client for microbenchmarks
# ---------------------------------------------------------------------------

@pytest.fixture
def ollama_bench_client():
    """Return a bare OllamaClient instance with circuit breaker disabled."""
    client = OllamaClient()
    client._cb.is_open = lambda: False
    client._is_available = lambda: True
    return client


# ---------------------------------------------------------------------------
# PerfReporter helper for concurrent tests
# ---------------------------------------------------------------------------

class PerfReporter:
    """Collects timing data and prints a summary table."""

    def __init__(self, name: str):
        self.name = name
        self._timings: list[float] = []

    def record(self, seconds: float) -> None:
        self._timings.append(seconds * 1000)  # store in ms

    @property
    def count(self) -> int:
        return len(self._timings)

    @property
    def min_ms(self) -> float:
        return min(self._timings) if self._timings else 0.0

    @property
    def max_ms(self) -> float:
        return max(self._timings) if self._timings else 0.0

    @property
    def avg_ms(self) -> float:
        return sum(self._timings) / len(self._timings) if self._timings else 0.0

    def percentile(self, p: float) -> float:
        if not self._timings:
            return 0.0
        sorted_t = sorted(self._timings)
        idx = int(len(sorted_t) * p / 100.0)
        return sorted_t[min(idx, len(sorted_t) - 1)]

    def report(self) -> str:
        if not self._timings:
            return f"{self.name:40s}  no data"
        return (
            f"{self.name:40s}  "
            f"{self.count:>5} req  "
            f"{self.min_ms:>7.2f} min  "
            f"{self.avg_ms:>7.2f} avg  "
            f"{self.percentile(50):>7.2f} p50  "
            f"{self.percentile(95):>7.2f} p95  "
            f"{self.percentile(99):>7.2f} p99  "
        )


@pytest.fixture
def perf_reporter():
    return PerfReporter
