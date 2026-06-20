from __future__ import annotations
import os

import pytest


def _make_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import Base
    import app.models  # noqa: F401 - register tables on Base.metadata
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


@pytest.fixture
def env(tmp_path, monkeypatch):
    os.environ["CHROMA_PATH"] = str(tmp_path / "chroma")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'db.sqlite'}"
    os.environ["USE_OLLAMA_EMBEDDINGS"] = "false"
    import chromadb
    import app.chroma_client as chroma_client
    monkeypatch.setattr(chroma_client, "get_client", lambda: chromadb.Client())
    monkeypatch.setattr(chroma_client, "_build_embedding_function", lambda: None)


def test_clarification_state_transition(env):
    db = _make_db()
    try:
        from app.brand_service import brand_service
        brand = brand_service.get_or_create(db, "testbrand")
        from app.conversation_repository import conversation_repo
        from app.conversation import state_machine
        conv = conversation_repo.save_conversation(db, brand.id, "sess1")
        ctx = state_machine.get_context(db, conv.id)
        assert ctx.state == "idle"

        state_machine.apply_transition(db, ctx, "clarification_needed")
        assert ctx.state == "awaiting_clarification"

        state_machine.set_slot(ctx, "clarification_original_query", "what is this?")
        assert state_machine.get_slot(ctx, "clarification_original_query") == "what is this?"

        state_machine.apply_transition(db, ctx, "clarification_provided")
        assert ctx.state == "idle"
    finally:
        db.close()


def test_clarification_question_generation(env, monkeypatch):
    from app.rag_service import RAGService
    import app.ollama_client as ollama_client

    async def fake_chat(system, messages, context, append_rag_instruction=True):
        return ("Could you specify which product you're asking about?", 1)

    monkeypatch.setattr(ollama_client.ollama, "chat", fake_chat)

    svc = RAGService()
    import asyncio
    answer = asyncio.run(svc._generate_clarification_question(
        ["Doc about X product."], [{"source_name": "faq"}], "TestBrand",
    ))
    assert "specify" in answer


def test_clarification_fallback_when_no_topics():
    from app.rag_service import RAGService
    svc = RAGService()
    import asyncio
    answer = asyncio.run(svc._generate_clarification_question(
        [], [], "TestBrand",
    ))
    assert "more details" in answer


def test_clarification_skipped_transition(env):
    db = _make_db()
    try:
        from app.brand_service import brand_service
        brand = brand_service.get_or_create(db, "testbrand")
        from app.conversation_repository import conversation_repo
        from app.conversation import state_machine
        conv = conversation_repo.save_conversation(db, brand.id, "sess_skip")
        ctx = state_machine.get_context(db, conv.id)
        state_machine.apply_transition(db, ctx, "clarification_needed")
        assert ctx.state == "awaiting_clarification"
        state_machine.apply_transition(db, ctx, "clarification_skipped")
        assert ctx.state == "idle"
    finally:
        db.close()
