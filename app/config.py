import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./app.db"
    chroma_path: str = "./vector_db"

    ollama_base_url: str = "http://localhost:11434"
    ollama_embed_model: str = "nomic-embed-text"
    use_ollama_embeddings: bool = True

    admin_username: str = "admin"
    admin_password: str = "change-me-now"
    session_secret: str = "replace-with-a-long-random-string"
    allow_unverified_tracking: bool = False

    # Cloud LLM (Groq)
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # Cloud embeddings (HuggingFace)
    hf_api_token: str = ""
    hf_embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Cloud embeddings (Google — deprecated, kept for backwards compat)
    gg_api_key: str = ""
    gg_embed_model: str = "text-embedding-005"

    # Chunk settings
    chunk_size: int = 512
    chunk_overlap: int = 64
    default_top_k: int = 10

    # Crawler limits
    crawler_max_pages: int = 50
    crawler_timeout: int = 10

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
