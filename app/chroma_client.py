import chromadb
from chromadb.api.collection_configuration import HNSWConfiguration
from chromadb.api.types import EmbeddingFunction, Embeddings, Documents
from app.config import get_settings
import logging
import requests
import numpy as np

settings = get_settings()

_client: chromadb.PersistentClient | None = None
logger = logging.getLogger(__name__)


class HuggingFaceEmbeddingFunction(EmbeddingFunction[Documents]):
    """Embedding via HuggingFace Inference API (free tier)."""

    def __init__(self, model: str, api_token: str = ""):
        self.model = model
        self.api_token = api_token

    def __call__(self, input: Documents) -> Embeddings:
        from huggingface_hub import InferenceClient

        texts = [input] if isinstance(input, str) else input
        client = InferenceClient(token=self.api_token or None)
        return [
            np.array(
                client.feature_extraction(text, model=self.model), dtype=np.float32
            )
            for text in texts
        ]

    @staticmethod
    def name() -> str:
        return "huggingface"

    def default_space(self) -> str:
        return "cosine"


class KeepAliveEmbeddingFunction(EmbeddingFunction[Documents]):
    """Custom embedding function that passes keep_alive to Ollama."""

    def __init__(self, url: str, model_name: str):
        self.url = url.rstrip("/")
        self.model_name = model_name

    def __call__(self, input: Documents) -> Embeddings:
        texts = [input] if isinstance(input, str) else input
        embeddings = []
        for text in texts:
            r = requests.post(
                f"{self.url}/api/embeddings",
                json={"model": self.model_name, "prompt": text, "keep_alive": -1},
                timeout=60,
            )
            r.raise_for_status()
            embeddings.append(np.array(r.json()["embedding"], dtype=np.float32))
        return embeddings

    @staticmethod
    def name() -> str:
        return "ollama"

    def default_space(self) -> str:
        return "cosine"


def get_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=settings.chroma_path)
    return _client


def _build_embedding_function():
    from app.embedding_service import CachedEmbeddingWrapper

    if settings.hf_api_token:
        return CachedEmbeddingWrapper(
            HuggingFaceEmbeddingFunction(
                model=settings.hf_embed_model,
                api_token=settings.hf_api_token,
            )
        )
    if settings.use_ollama_embeddings:
        return CachedEmbeddingWrapper(
            KeepAliveEmbeddingFunction(
                url=settings.ollama_base_url,
                model_name=settings.ollama_embed_model,
            )
        )
    return None


def get_collection(brand_slug: str):
    """Get or create the ChromaDB collection for a brand."""
    client = get_client()
    ef = _build_embedding_function()
    # Try to create/get the collection with the configured embedding function.
    # If a persisted collection already exists with a different embedding
    # configuration, fall back to retrieving the existing collection to avoid
    # raising an embedding-function conflict from the client.
    try:
        kwargs: dict = {
            "name": brand_slug,
            "embedding_function": ef,
            "metadata": {"hnsw:space": "cosine"},
        }
        if ef is not None:
            kwargs["configuration"] = {
                "hnsw": HNSWConfiguration(
                    max_neighbors=16,
                    ef_search=50,
                    space="cosine",
                ),
            }
        return client.get_or_create_collection(**kwargs)
    except Exception as e:
        logger.warning(
            "get_or_create_collection failed for '%s': %s. Falling back to get_collection().",
            brand_slug,
            e,
            exc_info=True,
        )
        return client.get_collection(name=brand_slug)


def delete_collection(brand_slug: str) -> None:
    """Drop a brand's vector collection entirely."""
    client = get_client()
    try:
        client.delete_collection(name=brand_slug)
    except Exception:
        pass


def collection_count(brand_slug: str) -> int:
    try:
        return get_collection(brand_slug).count()
    except Exception:
        return 0


def query_collection(
    brand_slug: str,
    query_text: str,
    n_results: int = 3,
    where: dict | None = None,
) -> dict:
    """Query the brand's vector collection with optional metadata filtering."""
    collection = get_collection(brand_slug)
    kwargs: dict = {"query_texts": [query_text], "n_results": n_results}
    if where is not None:
        kwargs["where"] = where
    return collection.query(**kwargs)