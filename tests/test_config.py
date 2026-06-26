from __future__ import annotations


def test_defaults(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CHROMA_PATH", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("USE_OLLAMA_EMBEDDINGS", raising=False)
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("HF_API_TOKEN", raising=False)
    monkeypatch.delenv("CHUNK_SIZE", raising=False)
    monkeypatch.delenv("CHUNK_OVERLAP", raising=False)
    monkeypatch.delenv("ALLOWED_CRAWL_DOMAINS", raising=False)
    monkeypatch.delenv("CLARIFICATION_THRESHOLD", raising=False)
    from app.config import Settings
    s = Settings(_env_file=None)
    assert s.database_url == "sqlite:///./app.db"
    assert s.chroma_path == "./vector_db"
    assert s.ollama_base_url == "http://localhost:11434"
    assert s.ollama_embed_model == "nomic-embed-text"
    assert s.use_ollama_embeddings is True
    assert s.admin_username == "admin"
    assert s.admin_password == "change-me-now"
    assert s.session_secret == "replace-with-a-long-random-string"
    assert s.allow_unverified_tracking is False
    assert s.groq_api_key == ""
    assert s.groq_model == "llama-3.1-8b-instant"
    assert s.groq_base_url == "https://api.groq.com/openai/v1"
    assert s.hf_api_token == ""
    assert s.hf_embed_model == "sentence-transformers/all-MiniLM-L6-v2"
    assert s.chunk_size == 512
    assert s.chunk_overlap == 64
    assert s.default_top_k == 10
    assert s.clarification_threshold == 0.25
    assert s.default_language == "en"
    assert s.crawler_max_pages == 50
    assert s.crawler_timeout == 10
    assert s.allowed_crawl_domains == []


def test_env_override(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///custom.db")
    monkeypatch.setenv("CHROMA_PATH", "/custom/chroma")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://custom:11434")
    monkeypatch.setenv("USE_OLLAMA_EMBEDDINGS", "false")
    monkeypatch.setenv("ADMIN_USERNAME", "custom_admin")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("HF_API_TOKEN", "hf_test")
    monkeypatch.setenv("CHUNK_SIZE", "1024")
    monkeypatch.setenv("CLARIFICATION_THRESHOLD", "0.5")

    from app.config import Settings
    s = Settings()
    assert s.database_url == "sqlite:///custom.db"
    assert s.chroma_path == "/custom/chroma"
    assert s.ollama_base_url == "http://custom:11434"
    assert s.use_ollama_embeddings is False
    assert s.admin_username == "custom_admin"
    assert s.groq_api_key == "gsk_test"
    assert s.hf_api_token == "hf_test"
    assert s.chunk_size == 1024
    assert s.clarification_threshold == 0.5


def test_allowed_crawl_domains_parsed(monkeypatch):
    monkeypatch.setenv("ALLOWED_CRAWL_DOMAINS", '["foo.com","bar.com"]')

    from app.config import Settings
    s = Settings()
    assert s.allowed_crawl_domains == ["foo.com", "bar.com"]


def test_get_settings_cache():
    from app.config import get_settings
    a = get_settings()
    b = get_settings()
    assert a is b
