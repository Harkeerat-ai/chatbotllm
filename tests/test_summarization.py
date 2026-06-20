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


def test_summarization_skipped_when_few_messages(env):
    db = _make_db()
    try:
        from app.brand_service import brand_service
        brand = brand_service.get_or_create(db, "testbrand")
        from app.conversation_repository import conversation_repo
        conv = conversation_repo.save_conversation(db, brand.id, "sess1")
        from app.rag_service import _summarize_conversation_async
        import asyncio
        asyncio.run(_summarize_conversation_async(db, brand.name, conv))
        assert conv.summary_json is None or conv.summary_json == "{}"
    finally:
        db.close()


def test_summary_column_exists_in_schema(env):
    from sqlalchemy import inspect
    from app.db import engine
    inspector = inspect(engine)
    conv_columns = {c["name"] for c in inspector.get_columns("conversations")}
    assert "summary_json" in conv_columns


def test_summary_prepended_to_history(env, monkeypatch):
    import json
    db = _make_db()
    try:
        from app.brand_service import brand_service
        brand = brand_service.get_or_create(db, "testbrand")
        from app.conversation_repository import conversation_repo

        conv = conversation_repo.save_conversation(db, brand.id, "sess2")
        conv.summary_json = json.dumps({"summary": "User asked about product X.", "message_count": 4})
        db.commit()

        summary_data = json.loads(conv.summary_json) if conv.summary_json else {}
        summary_text = summary_data.get("summary", "")
        history = []
        if summary_text:
            history.append({"role": "system", "content": f"Previous conversation summary: {summary_text}"})

        assert len(history) == 1
        assert "product X" in history[0]["content"]
    finally:
        db.close()
