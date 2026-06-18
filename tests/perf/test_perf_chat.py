"""Component-level and full-pipeline latency benchmarks for the chat system."""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import patch

import pytest

from app import models
from app.config import get_settings
from app.rag_service import RAGService, rag_service
from app.ollama_client import ollama as live_ollama

pytestmark = pytest.mark.perf

settings = get_settings()


# ---------------------------------------------------------------------------
# DB benchmarks
# ---------------------------------------------------------------------------

def test_bench_db_conversation_new(benchmark, db_session):
    """Time to create a conversation row + first user message + commit."""
    brand = models.Brand(slug="perf-db", name="Perf DB")
    db_session.add(brand)
    db_session.commit()
    db_session.refresh(brand)

    def _run():
        conv = models.Conversation(brand_id=brand.id, session_id="perf-session")
        db_session.add(conv)
        db_session.commit()
        db_session.refresh(conv)
        msg = models.Message(conversation_id=conv.id, role="user", content="hello")
        db_session.add(msg)
        db_session.commit()
        return conv

    result = benchmark(_run)
    assert result.id is not None


def test_bench_db_conversation_history(benchmark, db_session):
    """Time to load 12 messages for an existing conversation."""
    brand = models.Brand(slug="perf-db-2", name="Perf DB 2")
    db_session.add(brand)
    db_session.commit()
    db_session.refresh(brand)

    conv = models.Conversation(brand_id=brand.id, session_id="perf-session-2")
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)
    for i in range(12):
        db_session.add(models.Message(conversation_id=conv.id, role="user" if i % 2 == 0 else "assistant", content=f"msg {i}"))
    db_session.commit()

    def _run():
        q = (
            db_session.query(models.Message)
            .filter_by(conversation_id=conv.id)
            .order_by(models.Message.created_at.desc())
            .limit(12)
            .all()
        )
        _ = [{"role": m.role, "content": m.content} for m in reversed(q)]

    benchmark(_run)


def test_bench_db_write_assistant(benchmark, db_session):
    """Time to db.add() + db.commit() an assistant message."""
    brand = models.Brand(slug="perf-db-3", name="Perf DB 3")
    db_session.add(brand)
    db_session.commit()
    db_session.refresh(brand)
    conv = models.Conversation(brand_id=brand.id, session_id="perf-session-3")
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)

    def _run():
        msg = models.Message(conversation_id=conv.id, role="assistant", content="performance test answer", latency_ms=123)
        db_session.add(msg)
        db_session.commit()

    benchmark(_run)


# ---------------------------------------------------------------------------
# Chroma query benchmarks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n_results", [1, 5, 10, 25])
def test_bench_chroma_query(benchmark, brand_with_collection, n_results):
    """Time Chroma vector query with varying top_k."""
    _brand, coll = brand_with_collection

    def _run():
        results = coll.query(query_texts=["performance benchmark"], n_results=n_results)
        return results

    result = benchmark(_run)
    assert len(result.get("documents", [[]])[0]) <= n_results


@pytest.mark.parametrize("collection_size", [50, 200, 500])
def test_bench_chroma_collection_size(benchmark, db_session, monkeypatch, collection_size):
    """Time Chroma query at different collection sizes (top_k=5)."""
    import chromadb
    import app.chroma_client as chroma_client
    monkeypatch.setattr(chroma_client, "get_client", lambda: chromadb.Client())
    monkeypatch.setattr(chroma_client, "_build_embedding_function", lambda: None)

    from app.brand_service import brand_service
    brand = brand_service.get_or_create(db_session, f"perf-size-{collection_size}")
    coll = chroma_client.get_collection(brand.slug)
    ids = [f"doc_{i}" for i in range(collection_size)]
    docs = [f"Performance test document number {i}." for i in range(collection_size)]
    metas = [{"source_name": "perf"} for _ in range(collection_size)]
    coll.upsert(ids=ids, documents=docs, metadatas=metas)

    def _run():
        return coll.query(query_texts=["test"], n_results=5)

    benchmark(_run)


# ---------------------------------------------------------------------------
# Prompt construction benchmarks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("context_kb", [0.5, 5, 25])
def test_bench_prompt_build(benchmark, context_kb):
    """Time to assemble system prompt + history + context."""
    context = ("word " * 200)[:int(context_kb * 1000)]
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"} for i in range(12)]
    system = "You are a helpful assistant for {brand_name}."
    brand_name = "PerfBrand"

    def _run():
        sys_prompt = system.format(brand_name=brand_name)
        llm_messages = history + [{"role": "user", "content": "benchmark query"}]
        return sys_prompt, llm_messages

    _, msgs = benchmark(_run)
    assert len(msgs) == len(history) + 1


# ---------------------------------------------------------------------------
# Full RAG pipeline benchmarks (mocked Ollama)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("simulated_llm_ms", [100, 500, 1000])
def test_bench_rag_pipeline(benchmark, db_session, brand_with_collection, monkeypatch, simulated_llm_ms):
    """End-to-end rag_service.ask() with mocked Ollama at varying simulated latencies."""
    brand, _coll = brand_with_collection

    async def fake_chat(system_prompt, messages, context, append_rag_instruction=True):
        wait = simulated_llm_ms / 1000.0
        import asyncio
        await asyncio.sleep(wait)
        return (f"__PERF_ANSWER__ (simulated {simulated_llm_ms}ms LLM)", simulated_llm_ms)

    monkeypatch.setattr(live_ollama.__class__, "chat", lambda self, *a, **kw: fake_chat(*a, **kw))

    def _run():
        import asyncio
        return asyncio.run(rag_service.ask(
            db=db_session,
            brand=brand,
            session_id="perf-rag",
            user_message="performance test query",
            top_k=5,
        ))

    result = benchmark(_run)
    assert result["answer"].startswith("__PERF_ANSWER__")


def test_bench_no_context_path(benchmark, db_session):
    """Time for rag_service.ask() fast path when Chroma returns 0 results."""
    import chromadb
    import app.chroma_client as chroma_client
    import importlib
    importlib.reload(chroma_client)

    from app.brand_service import brand_service
    brand = brand_service.get_or_create(db_session, "perf-empty-brand")
    # collection exists but has no docs
    coll = chroma_client.get_collection(brand.slug)

    def _run():
        import asyncio
        return asyncio.run(rag_service.ask(
            db=db_session,
            brand=brand,
            session_id="perf-empty",
            user_message="something not in the knowledge base",
            top_k=5,
        ))

    result = benchmark(_run)
    assert "don't have relevant information" in result["answer"]


def test_bench_tracking_nlp(benchmark, db_session, monkeypatch):
    """Time _generate_nlp_tracking_response with mocked Ollama."""
    brand = models.Brand(slug="perf-trk", name="Perf Tracking")
    db_session.add(brand)
    db_session.commit()

    tracking_data = {
        "status": "in_transit",
        "status_label": "In Transit",
        "eta": "2026-06-15",
        "hub_name": "Atlanta Hub",
        "hub_city": "Atlanta",
        "current_location": "Atlanta, GA",
        "last_updated": "2026-06-09",
        "timeline": ["Picked up", "Arrived at Atlanta Hub", "Departed Atlanta Hub"],
    }

    async def fake_chat(system_prompt, messages, context, append_rag_instruction=True):
        await asyncio.sleep(0.05)
        return ("Your shipment is in transit and expected by 2026-06-15.", 50)

    monkeypatch.setattr(live_ollama.__class__, "chat", lambda self, *a, **kw: fake_chat(*a, **kw))

    def _run():
        import asyncio
        return asyncio.run(rag_service._generate_nlp_tracking_response(brand, tracking_data, [{"role": "user", "content": "where is it?"}]))

    result = benchmark(_run)
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Worst-case combination benchmark
# ---------------------------------------------------------------------------

def test_bench_worst_case(benchmark, db_session, monkeypatch):
    """Full RAG pipeline with large context, top_k=25, slow simulated LLM (500ms)."""
    import chromadb
    import app.chroma_client as chroma_client
    monkeypatch.setattr(chroma_client, "get_client", lambda: chromadb.Client())
    monkeypatch.setattr(chroma_client, "_build_embedding_function", lambda: None)

    from app.brand_service import brand_service
    brand = brand_service.get_or_create(db_session, "perf-worst")
    coll = chroma_client.get_collection(brand.slug)

    large_docs = [f"This is a very long performance test document number {i}. " * 20 for i in range(500)]
    coll.upsert(
        ids=[f"doc_{i}" for i in range(500)],
        documents=large_docs,
        metadatas=[{"source_name": "perf"} for _ in range(500)],
    )

    async def fake_chat(system_prompt, messages, context, append_rag_instruction=True):
        await asyncio.sleep(0.5)
        return ("worst case answer", 500)

    monkeypatch.setattr(live_ollama.__class__, "chat", lambda self, *a, **kw: fake_chat(*a, **kw))

    def _run():
        import asyncio
        return asyncio.run(rag_service.ask(
            db=db_session,
            brand=brand,
            session_id="perf-worst",
            user_message="worst case benchmark query " * 50,
            top_k=25,
        ))

    result = benchmark(_run)
    assert result["answer"] == "worst case answer"
