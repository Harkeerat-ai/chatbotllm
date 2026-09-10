import os
from functools import lru_cache
from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///./app.db"
    chroma_path: str = "./vector_db"

    ollama_base_url: str = "http://localhost:11434"
    ollama_embed_model: str = "nomic-embed-text"
    use_ollama_embeddings: bool = False

    admin_username: str = "admin"
    admin_password: str = "change-me-now"
    session_secret: str = "replace-with-a-long-random-string"
    csrf_secret: str = "replace-with-a-different-random-string"
    allow_unverified_tracking: bool = False

    # Cloud LLM (OpenRouter — primary)
    openrouter_api_key: str = ""
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = "https://kalp-shop.in"
    openrouter_app_name: str = "KALP Chatbot"
    openrouter_providers: list[str] = Field(
        ["fireworks", "together"],
        description="Preferred OpenRouter providers, in order. Chosen for low TTFT on Llama 3.3 70B.",
    )

    # Cloud LLM (Groq — legacy fallback if openrouter_api_key is unset)
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # Local embeddings (sentence-transformers, no API key)
    use_local_embeddings: bool = True
    local_embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Cloud embeddings (HuggingFace — only used if use_local_embeddings=false and token set)
    hf_api_token: str = ""
    hf_embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Cloud embeddings (Google — deprecated, kept for backwards compat)
    gg_api_key: str = ""
    gg_embed_model: str = "text-embedding-005"

    # Chunk settings
    chunk_size: int = 512
    chunk_overlap: int = 64
    # Recall is vector-only — the hybrid retriever's BM25 half only reorders
    # what the embedder already found, so anything missed here is missed for
    # good. Short queries ("what is the price") were failing to surface their
    # obvious answer within 10, then tripping the clarification threshold; the
    # cross-encoder still trims to the best 3 before the LLM sees anything.
    default_top_k: int = 20
    clarification_threshold: float = 0.25
    default_language: str = "en"

    # Crawler limits
    crawler_max_pages: int = 50
    crawler_timeout: int = 10
    allowed_crawl_domains: list[str] = Field(
        [], description="Domains allowed for crawling even if they resolve to private IPs"
    )

    cors_origins: list[str] = Field(
        ["http://localhost:8000"], description="Allowed CORS origins (restrict in production)"
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
