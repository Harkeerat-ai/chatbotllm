from __future__ import annotations
import os

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    os.environ["CHROMA_PATH"] = str(tmp_path / "chroma")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'db.sqlite'}"
    os.environ["USE_OLLAMA_EMBEDDINGS"] = "false"
    import chromadb
    import app.chroma_client as chroma_client
    monkeypatch.setattr(chroma_client, "get_client", lambda: chromadb.Client())
    monkeypatch.setattr(chroma_client, "_build_embedding_function", lambda: None)


def test_bm25_index():
    from app.hybrid_retriever import BM25Index
    docs = ["apple banana fruit", "banana split dessert", "apple pie dessert"]
    metas = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
    idx = BM25Index(docs, metas)

    scores = idx.score("apple banana")
    assert len(scores) == 3
    assert scores[0] > 0
    assert scores[1] > 0


def test_bm25_prefers_relevant_docs():
    from app.hybrid_retriever import BM25Index
    docs = ["apple banana fruit", "car tire wheel", "apple dessert sweet"]
    metas = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
    idx = BM25Index(docs, metas)

    scores = idx.score("apple")
    assert scores[0] > scores[1]
    assert scores[2] > scores[1]


def test_rrf_combined_scores():
    from app.hybrid_retriever import _rrf
    ranked_lists = [[0, 1, 2], [2, 0, 1]]
    scores = _rrf(ranked_lists, k=60)
    assert len(scores) == 3
    assert scores[2] > 0


def test_hybrid_retriever_creates_and_queries(env):
    from app.hybrid_retriever import get_hybrid_retriever
    import app.chroma_client as chroma_client

    coll = chroma_client.get_collection("testbrand")
    coll.upsert(
        ids=["d1", "d2"],
        documents=["apple banana fruit", "car tire wheel"],
        metadatas=[{"source_name": "faq"}, {"source_name": "faq"}],
    )

    retriever = get_hybrid_retriever("testbrand")
    results = retriever.hybrid_query("apple", top_k=2)
    assert len(results) > 0
    assert any("apple" in r.document for r in results)


def test_hybrid_fallback_when_no_docs(env):
    from app.hybrid_retriever import get_hybrid_retriever
    retriever = get_hybrid_retriever("emptybrand")
    results = retriever.hybrid_query("anything", top_k=5)
    assert results == []


def test_invalidate_retriever(env):
    from app.hybrid_retriever import invalidate_retriever, _retrievers
    invalidate_retriever("testbrand")
    assert "testbrand" not in _retrievers
