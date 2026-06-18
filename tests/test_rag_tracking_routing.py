"""Ensure order-tracking queries route to tracking_service, not FAQ RAG."""
from __future__ import annotations

import asyncio
import os

import chromadb
import pytest

TRACKING_QUERY = "Where is my order KALP-1001?"


@pytest.fixture
def tracking_test_env(tmp_path, monkeypatch):
    """Isolated DB + in-memory Chroma with FAQ content that could compete on 'KALP'."""
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'tracking_routing.db'}"
    os.environ["CHROMA_PATH"] = str(tmp_path / "vector_db")
    os.environ["USE_OLLAMA_EMBEDDINGS"] = "false"

    import app.chroma_client as chroma_client

    monkeypatch.setattr(chroma_client, "get_client", lambda: chromadb.Client())
    monkeypatch.setattr(chroma_client, "_build_embedding_function", lambda: None)

    import app.ollama_client as ollama_client

    llm_calls: dict = {"rag": False, "rag_context": ""}

    async def fake_chat(system_prompt, messages, context, append_rag_instruction=True):
        if append_rag_instruction:
            llm_calls["rag"] = True
            llm_calls["rag_context"] = context
            return ("__FAQ_RAG_ANSWER__", 1)
        return ("Your KALP order is on its way.", 1)

    monkeypatch.setattr(ollama_client.ollama, "chat", fake_chat)

    from app.db import init_db, SessionLocal

    init_db()
    db = SessionLocal()
    try:
        from app.brand_service import brand_service
        from app.services import tracking_service

        tracking_service.ensure_defaults(db)
        brand = brand_service.get_or_create(db, "kalp")

        coll = chroma_client.get_collection(brand.slug)
        coll.upsert(
            ids=["faq-kalp", "faq-track"],
            documents=[
                "Q: What is KALP?\nA: KALP is a premium cocoa bar brand.",
                "Q: How can I track my KALP order?\n"
                "A: You will receive a tracking link via email.",
            ],
            metadatas=[{"source_name": "faq"}, {"source_name": "faq"}],
        )

        yield db, brand, llm_calls
    finally:
        db.close()


def _set_context_state(db, brand, session_id: str, state: str):
    from app.conversation import state_machine
    from app.conversation_repository import conversation_repo

    conv = conversation_repo.save_conversation(db, brand.id, session_id)
    ctx = state_machine.get_context(db, conv.id)
    ctx.state = state
    db.commit()
    return conv


def _ask_tracking(db, brand, session_id: str, message: str = TRACKING_QUERY):
    from app.services import rag_service

    return asyncio.run(
        rag_service.ask(
            db=db,
            brand=brand,
            session_id=session_id,
            user_message=message,
            allow_unverified_tracking=True,
        )
    )


@pytest.mark.parametrize(
    "session_id, stale_state",
    [
        ("fresh-idle", None),
        ("stale-completed", "completed"),
        ("stale-performing", "performing_lookup"),
        ("stale-displaying", "displaying_result"),
        ("stale-error-terminal", "error_terminal"),
    ],
)
def test_tracking_query_uses_tracking_service_not_faq(tracking_test_env, session_id, stale_state):
    db, brand, llm_calls = tracking_test_env
    llm_calls["rag"] = False
    llm_calls["rag_context"] = ""

    if stale_state:
        _set_context_state(db, brand, session_id, stale_state)

    result = _ask_tracking(db, brand, session_id)

    assert result["sources"] == ["tracking_system"]
    assert result["answer"] != "__FAQ_RAG_ANSWER__"
    assert "tracking link via email" not in result["answer"].lower()
    assert llm_calls["rag"] is False


def test_genuine_faq_still_uses_rag(tracking_test_env):
    db, brand, llm_calls = tracking_test_env
    llm_calls["rag"] = False

    result = _ask_tracking(db, brand, "faq-only", "What is KALP?")

    assert result["answer"] == "__FAQ_RAG_ANSWER__"
    assert llm_calls["rag"] is True
    assert "faq" in result.get("sources", [])
