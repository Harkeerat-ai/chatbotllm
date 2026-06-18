import os


def test_rag_integration(tmp_path, monkeypatch):
    """Seed a small in-memory Chroma collection and verify RAG retrieval is used
    by `rag_service.ask()` (we monkeypatch the LLM to capture passed context).
    """
    # Use an isolated chroma path for the test
    os.environ["CHROMA_PATH"] = str(tmp_path / "vector_db")
    # Disable Ollama embedding integration for deterministic upserts
    os.environ["USE_OLLAMA_EMBEDDINGS"] = "false"

    import chromadb

    # Ensure chroma client is in-memory for tests
    import app.chroma_client as chroma_client

    monkeypatch.setattr(chroma_client, "get_client", lambda: chromadb.Client())
    monkeypatch.setattr(chroma_client, "_build_embedding_function", lambda: None)

    # Create DB and a brand, then create a collection and upsert docs
    # Use isolated sqlite file for this test to avoid collisions with repo DB
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'app_test.db'}"
    from app.db import init_db, SessionLocal
    from app import models

    init_db()
    db = SessionLocal()
    try:
        from app.brand_service import brand_service
        brand = brand_service.get_or_create(db, "testbrand")

        coll = chroma_client.get_collection(brand.slug)
        coll.upsert(
            ids=["d1", "d2"],
            documents=["Doc about X: usage and details.", "Other content about Y."],
            metadatas=[{"source_name": "faq"}, {"source_name": "doc"}],
        )

        # Monkeypatch ollama.chat to capture the context argument
        import app.ollama_client as ollama_client

        captured = {}

        async def fake_chat(system_prompt, messages, context, append_rag_instruction=True):
            captured["context"] = context
            return ("__FAKE_ANSWER__", 1)

        monkeypatch.setattr(ollama_client.ollama, "chat", fake_chat)

        # Call rag_service.ask and assert the captured context contains our doc
        from app.services import rag_service
        import asyncio

        res = asyncio.run(rag_service.ask(db=db, brand=brand, session_id="s1", user_message="Tell me about X", top_k=2))
        assert res["answer"] == "__FAKE_ANSWER__"
        assert "Doc about X" in captured.get("context", "")
    finally:
        db.close()
