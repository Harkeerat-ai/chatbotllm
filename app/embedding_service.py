"""TTL-cached embedding wrapper around OllamaEmbeddingFunction."""
from __future__ import annotations

import hashlib
import threading

from cachetools import TTLCache

_EMBED_CACHE: TTLCache = TTLCache(maxsize=512, ttl=3600)
_CACHE_LOCK = threading.Lock()


def _make_key(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def get_cached_embedding(query: str) -> list[float]:
    """Return embedding for ``query`` from cache.

    Raises ``KeyError`` on cache miss — caller should fall back to the
    underlying embedding function and call ``store_embedding()``.
    """
    key = _make_key(query)
    with _CACHE_LOCK:
        cached = _EMBED_CACHE.get(key)
        if cached is not None:
            return cached
    raise KeyError(key)


def store_embedding(query: str, embedding: list[float]) -> None:
    """Store an embedding result in the cache."""
    key = _make_key(query)
    with _CACHE_LOCK:
        _EMBED_CACHE[key] = embedding


class CachedEmbeddingWrapper:
    """Wraps an embedding callable (e.g. ``OllamaEmbeddingFunction``)
    with a TTL cache keyed by MD5 of the input text.

    Usage::

        raw_ef = OllamaEmbeddingFunction(url=..., model_name=...)
        cached_ef = CachedEmbeddingWrapper(raw_ef)
        coll = client.get_or_create_collection(embedding_function=cached_ef)
    """

    def __init__(self, embed_fn):
        self._embed_fn = embed_fn

    def name(self) -> str:
        return "default"

    def embed_query(self, input: str | list[str]) -> list[float] | list[list[float]]:
        return self.__call__(input)

    def __call__(self, input: str | list[str]) -> list[float] | list[list[float]]:
        single = isinstance(input, str)
        texts = [input] if single else input

        results: list[list[float] | None] = []
        miss_indices: list[tuple[int, str]] = []

        for idx, text in enumerate(texts):
            key = _make_key(text)
            with _CACHE_LOCK:
                cached = _EMBED_CACHE.get(key)
            if cached is not None:
                results.append(cached)
            else:
                miss_indices.append((idx, text))
                results.append(None)

        if miss_indices:
            uncached_texts = [t for _, t in miss_indices]
            fetched = self._embed_fn(uncached_texts)
            for (idx, text), emb in zip(miss_indices, fetched):
                key = _make_key(text)
                with _CACHE_LOCK:
                    _EMBED_CACHE[key] = emb
                results[idx] = emb

        return results[0] if single else results
