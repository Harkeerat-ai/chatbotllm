"""Throughput and concurrent-load benchmarks for the chat system."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from app import models
from app.config import get_settings
from app.ollama_client import ollama as live_ollama

pytestmark = pytest.mark.perf

settings = get_settings()


# ---------------------------------------------------------------------------
# Helper: run concurrent tasks with timing
# ---------------------------------------------------------------------------

async def _timed_ask(rag_service, db, brand, session_id, user_message, top_k=5):
    """Single rag_service.ask() call returning (result, elapsed_ms)."""
    t0 = time.monotonic()
    result = await rag_service.ask(
        db=db, brand=brand, session_id=session_id,
        user_message=user_message, top_k=top_k,
    )
    elapsed = (time.monotonic() - t0) * 1000
    return result, elapsed


@pytest.fixture
def mock_llm_fast(monkeypatch):
    """Patch ollama.chat with a fast (10ms) fake."""
    async def fake_chat(*a, **kw):
        await asyncio.sleep(0.01)
        return ("__CONCURRENT_PERF_ANSWER__", 10)

    monkeypatch.setattr(live_ollama.__class__, "chat", lambda self, *a, **kw: fake_chat(*a, **kw))


@pytest.fixture
def mock_llm_slow(monkeypatch):
    """Patch ollama.chat with a slower (200ms) fake for saturation testing."""
    async def fake_chat(*a, **kw):
        await asyncio.sleep(0.2)
        return ("__CONCURRENT_PERF_ANSWER__", 200)

    monkeypatch.setattr(live_ollama.__class__, "chat", lambda self, *a, **kw: fake_chat(*a, **kw))


# ---------------------------------------------------------------------------
# Serial baseline
# ---------------------------------------------------------------------------

def test_serial_baseline(db_session, brand_with_collection, mock_llm_fast, perf_reporter):
    """10 sequential requests — baseline single-user latency."""
    brand, _coll = brand_with_collection
    reporter = perf_reporter("serial_baseline")
    from app.services import rag_service

    for i in range(10):
        _, elapsed = asyncio.run(_timed_ask(
            rag_service, db_session, brand, f"serial-{i}", f"question {i}", top_k=5,
        ))
        reporter.record(elapsed / 1000.0)

    print(f"\n{reporter.report()}")
    assert reporter.count == 10


# ---------------------------------------------------------------------------
# Concurrent load
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("concurrency", [5, 10, 20])
def test_concurrent_load(db_session, brand_with_collection, mock_llm_fast, perf_reporter, concurrency):
    """N simultaneous requests — measure throughput and latency distribution."""
    brand, _coll = brand_with_collection
    reporter = perf_reporter(f"concurrent_{concurrency}")
    from app.services import rag_service

    async def _run_concurrent():
        tasks = []
        for i in range(concurrency):
            tasks.append(_timed_ask(rag_service, db_session, brand, f"conc-{i}", f"question {i}", top_k=5))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                reporter.record(9999.0)
            else:
                _result, elapsed = r
                reporter.record(elapsed / 1000.0)

    asyncio.run(_run_concurrent())
    print(f"\n{reporter.report()}")
    assert reporter.count == concurrency


# ---------------------------------------------------------------------------
# Multi-brand concurrent
# ---------------------------------------------------------------------------

def test_multi_brand_concurrent(db_session, monkeypatch, mock_llm_fast, perf_reporter):
    """10 requests spread across 3 brands — cross-brand resource sharing cost."""
    import chromadb
    import app.chroma_client as chroma_client
    monkeypatch.setattr(chroma_client, "get_client", lambda: chromadb.Client())
    monkeypatch.setattr(chroma_client, "_build_embedding_function", lambda: None)

    from app.brand_service import brand_service
    brands = {}
    for slug in ["perf-mb-a", "perf-mb-b", "perf-mb-c"]:
        brand = brand_service.get_or_create(db_session, slug)
        coll = chroma_client.get_collection(brand.slug)
        coll.upsert(
            ids=[f"doc_{i}" for i in range(50)],
            documents=[f"Brand {slug} document {i}." for i in range(50)],
            metadatas=[{"source_name": "perf"} for _ in range(50)],
        )
        brands[slug] = brand

    reporter = perf_reporter("multi_brand_10")
    from app.services import rag_service

    brand_slugs = list(brands.keys())

    async def _run():
        tasks = []
        for i in range(10):
            slug = brand_slugs[i % len(brand_slugs)]
            tasks.append(_timed_ask(rag_service, db_session, brands[slug], f"mb-{i}", f"question {i}", top_k=5))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                reporter.record(9999.0)
            else:
                _result, elapsed = r
                reporter.record(elapsed / 1000.0)

    asyncio.run(_run())
    print(f"\n{reporter.report()}")
    assert reporter.count == 10


# ---------------------------------------------------------------------------
# Conversation growth — latency trend across turns
# ---------------------------------------------------------------------------

def test_conversation_growth(db_session, brand_with_collection, mock_llm_fast, perf_reporter):
    """10-turn conversation — measure per-turn latency to detect history accumulation overhead."""
    brand, _coll = brand_with_collection
    from app.services import rag_service
    reporter = perf_reporter("conversation_growth")

    session_id = "growth-session"
    for turn in range(10):
        _, elapsed = asyncio.run(_timed_ask(
            rag_service, db_session, brand, session_id,
            f"turn number {turn} in the conversation",
            top_k=5,
        ))
        reporter.record(elapsed / 1000.0)

    print(f"\n{reporter.report()}")
    assert reporter.count == 10


# ---------------------------------------------------------------------------
# Chat under background seed — performance isolation
# ---------------------------------------------------------------------------

def test_chat_after_seed(db_session, brand_with_collection, mock_llm_fast, perf_reporter):
    """Chat requests after knowledge has been seeded — measure DB with more data."""
    brand, _coll = brand_with_collection
    from app.services import rag_service

    reporter = perf_reporter("chat_after_seed")

    async def _run():
        tasks = [
            _timed_ask(rag_service, db_session, brand, f"seed-noise-{i}", f"question {i}", top_k=5)
            for i in range(5)
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)

    chat_results = asyncio.run(_run())

    for r in chat_results:
        if isinstance(r, Exception):
            reporter.record(9999.0)
        else:
            _result, elapsed = r
            reporter.record(elapsed / 1000.0)

    print(f"\n{reporter.report()}")


# ---------------------------------------------------------------------------
# Memory growth across sequential requests
# ---------------------------------------------------------------------------

def test_memory_growth(db_session, brand_with_collection, mock_llm_fast, perf_reporter):
    """50 sequential requests measuring memory evolution."""
    import tracemalloc

    brand, _coll = brand_with_collection
    from app.services import rag_service

    reporter = perf_reporter("memory_growth")
    session_id = "mem-growth"

    tracemalloc.start()
    snapshots = []

    for i in range(50):
        _, elapsed = asyncio.run(_timed_ask(
            rag_service, db_session, brand, session_id,
            f"memory test iteration {i}",
            top_k=5,
        ))
        reporter.record(elapsed / 1000.0)
        if i % 10 == 9:
            snapshots.append(tracemalloc.take_snapshot())

    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    start_size = snapshots[0].statistics("lineno")[0].size if snapshots else 0
    end_size = snapshots[-1].statistics("lineno")[0].size if snapshots else 0
    growth_mb = (end_size - start_size) / 1_048_576

    print(f"\n{reporter.report()}")
    print(f"  Peak memory: {peak / 1_048_576:.2f} MB")
    print(f"  Memory growth (snapshot 1->5): {growth_mb:.2f} MB")
    if growth_mb > 10:
        print(f"  ⚠ Memory growth >10MB — possible leak")
