import os


def test_api_chat_endpoint(tmp_path, monkeypatch):
    """End-to-end test for the `/api/{brand}/chat` endpoint using TestClient.
    The test configures an isolated DB and in-memory Chroma client, injects a
    fake LLM, then calls the chat endpoint and asserts a successful response.
    """
    # Isolate file-backed DB and Chroma path for the test
    db_file = tmp_path / "test_app.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["CHROMA_PATH"] = str(tmp_path / "vector_db")
    os.environ["USE_OLLAMA_EMBEDDINGS"] = "false"

    import chromadb

    import app.chroma_client as chroma_client
    monkeypatch.setattr(chroma_client, "get_client", lambda: chromadb.Client())
    monkeypatch.setattr(chroma_client, "_build_embedding_function", lambda: None)

    # Provide a deterministic fake LLM response
    import app.ollama_client as ollama_client

    async def fake_chat(system_prompt, messages, context, append_rag_instruction=True):
        return ("__API_FAKE_ANSWER__", 5)

    monkeypatch.setattr(ollama_client.ollama, "chat", fake_chat)

    # Now import the FastAPI app (after env and monkeypatch) and create a brand
    from app.main import app as fastapi_app
    from fastapi.testclient import TestClient
    from app.db import init_db, SessionLocal
    from app import models

    init_db()
    db = SessionLocal()
    try:
        from app.brand_service import brand_service
        brand = brand_service.get_or_create(db, "api-brand")

        # Upsert a small document into the brand collection so RAG has context
        coll = chroma_client.get_collection(brand.slug)
        coll.upsert(ids=["a1"], documents=["API doc about testing."], metadatas=[{"source_name": "faq"}])
    finally:
        db.close()

    client = TestClient(fastapi_app)

    payload = {"session_id": "s-api", "message": "Tell me about testing.", "top_k": 3}
    resp = client.post(f"/api/{brand.slug}/chat", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["answer"] == "__API_FAKE_ANSWER__"
    assert isinstance(data.get("sources"), list)
