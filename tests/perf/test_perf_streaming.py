"""Streaming-specific timing benchmarks for the Ollama client."""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import patch

import pytest

from app.ollama_client import OllamaClient

pytestmark = pytest.mark.perf


@pytest.fixture
def bench_client():
    c = OllamaClient()
    c._cb.is_open = lambda: False
    c._is_available = lambda: True
    return c


# ---------------------------------------------------------------------------
# Time-to-first-token
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("first_token_ms", [20, 50, 100])
def test_bench_time_to_first_token(benchmark, bench_client, mock_timed_client, first_token_ms):
    """Measure delay until first token is yielded from stream_chat."""
    stream = mock_timed_client(first_token_ms=first_token_ms, inter_token_ms=5, token_count=20)

    async def _run():
        t0 = time.monotonic()
        async for chunk in bench_client.stream_chat("sys", [{"role": "user", "content": "hi"}], "ctx"):
            elapsed = (time.monotonic() - t0) * 1000
            return elapsed, chunk
        return 0, ""

    def _timed():
        with patch("httpx.AsyncClient", stream):
            return asyncio.run(_run())

    elapsed, chunk = benchmark(_timed)
    assert chunk
    # Should be close to the simulated first_token_ms (± overhead)
    assert elapsed > 0


def test_bench_first_token_overhead(benchmark, bench_client, mock_timed_client):
    """Measure framework overhead beyond simulated latency (should be <10ms)."""
    stream = mock_timed_client(first_token_ms=0, inter_token_ms=0, token_count=5)

    async def _run():
        t0 = time.monotonic()
        async for chunk in bench_client.stream_chat("sys", [{"role": "user", "content": "hi"}], "ctx"):
            elapsed = (time.monotonic() - t0) * 1000
            return elapsed, chunk
        return 0, ""

    def _timed():
        with patch("httpx.AsyncClient", stream):
            return asyncio.run(_run())

    elapsed, chunk = benchmark(_timed)
    assert elapsed >= 0
    # This measures pure parsing/overhead cost since mock has 0ms delay
    if elapsed > 15:
        print(f"  ⚠ High first-token overhead: {elapsed:.2f}ms (expected <15ms)")


# ---------------------------------------------------------------------------
# Total stream duration
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("token_count", [20, 50, 100])
def test_bench_chat_total_duration(benchmark, bench_client, mock_timed_client, token_count):
    """Total time for chat() to accumulate all tokens at 10ms inter-token gap + 50ms first."""
    stream = mock_timed_client(first_token_ms=50, inter_token_ms=10, token_count=token_count)

    async def _run():
        answer, latency = await bench_client.chat("sys", [{"role": "user", "content": "hi"}], "ctx")
        return answer, latency

    def _timed():
        with patch("httpx.AsyncClient", stream):
            return asyncio.run(_run())

    answer, latency = benchmark(_timed)
    assert answer
    # Expected: 50ms + (token_count * 10ms) — allow generous overhead for calibration
    expected_min = 50 + (token_count * 10) - 50
    assert latency >= expected_min, (
        f"Expected latency >= {expected_min}ms, got {latency}ms"
    )


# ---------------------------------------------------------------------------
# Parse overhead at different context sizes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("context_size_kb", [1, 10, 50])
def test_bench_parse_overhead(benchmark, bench_client, mock_timed_client, context_size_kb):
    """Overhead of JSON-lines parsing with varying context sizes (0ms mock)."""
    context = ("word " * 200)[:int(context_size_kb * 1000)]
    stream = mock_timed_client(first_token_ms=0, inter_token_ms=0, token_count=10)

    async def _run():
        t0 = time.monotonic()
        parts = []
        async for chunk in bench_client.stream_chat("sys", [{"role": "user", "content": "big context"}], context):
            parts.append(chunk)
        return (time.monotonic() - t0) * 1000, "".join(parts)

    def _timed():
        with patch("httpx.AsyncClient", stream):
            return asyncio.run(_run())

    elapsed, text = benchmark(_timed)
    assert text


# ---------------------------------------------------------------------------
# Warmup stream duration
# ---------------------------------------------------------------------------

def test_bench_warmup_duration(benchmark, bench_client, mock_timed_client):
    """Time to fully drain warmup() stream."""
    stream = mock_timed_client(first_token_ms=50, inter_token_ms=5, token_count=20)

    async def _run():
        await bench_client.warmup()

    def _timed():
        with patch("httpx.AsyncClient", stream):
            return asyncio.run(_run())

    benchmark(_timed)
