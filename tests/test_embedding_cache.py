"""Tests for the TTL-cached embedding wrapper."""
from __future__ import annotations

import threading
import time

import pytest

from app.embedding_service import (
    CachedEmbeddingWrapper,
    get_cached_embedding,
    store_embedding,
    _EMBED_CACHE,
    _CACHE_LOCK,
)
import app.embedding_service as es


def _dummy_embed_fn(inputs: list[str]) -> list[list[float]]:
    """Return a deterministic embedding based on each char's ordinal."""
    return [[float(sum(ord(c) for c in t))] * 4 for t in inputs]


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the shared cache before each test."""
    with _CACHE_LOCK:
        _EMBED_CACHE.clear()
    yield


# ---------------------------------------------------------------------------
# Standalone get_cached_embedding / store_embedding
# ---------------------------------------------------------------------------


def test_standalone_miss_raises_keyerror():
    """A query not yet cached should raise KeyError."""
    with pytest.raises(KeyError):
        get_cached_embedding("never-seen-query")


def test_standalone_store_then_hit():
    """Stored embedding should be retrievable via get_cached_embedding."""
    store_embedding("hello", [0.1, 0.2, 0.3, 0.4])
    result = get_cached_embedding("hello")
    assert result == [0.1, 0.2, 0.3, 0.4]


def test_standalone_cache_key_is_md5():
    """Same text should produce the same cache key (not tested directly, but via hit)."""
    store_embedding("same text", [1.0, 2.0, 3.0, 4.0])
    assert get_cached_embedding("same text") == [1.0, 2.0, 3.0, 4.0]


# ---------------------------------------------------------------------------
# CachedEmbeddingWrapper
# ---------------------------------------------------------------------------


def test_wrapper_miss_then_hit():
    """First call misses cache, second call hits — embed function only called once."""
    call_count = 0

    def counting_embed(inputs: list[str]) -> list[list[float]]:
        nonlocal call_count
        call_count += 1
        return _dummy_embed_fn(inputs)

    wrapper = CachedEmbeddingWrapper(counting_embed)
    result1 = wrapper("test query")
    result2 = wrapper("test query")

    assert call_count == 1
    assert result1 == result2


def test_wrapper_different_queries():
    """Different queries should each call the embed function."""
    call_count = 0

    def counting_embed(inputs: list[str]) -> list[list[float]]:
        nonlocal call_count
        call_count += 1
        return _dummy_embed_fn(inputs)

    wrapper = CachedEmbeddingWrapper(counting_embed)
    r1 = wrapper("query A")
    r2 = wrapper("query B")

    assert call_count == 2
    assert r1 is not r2


def test_wrapper_batch_input():
    """Batch call with mixed cache state should fetch only uncached items."""
    store_embedding("cached", [9.0, 9.0, 9.0, 9.0])

    called_with = None

    def capture_embed(inputs: list[str]) -> list[list[float]]:
        nonlocal called_with
        called_with = inputs
        return _dummy_embed_fn(inputs)

    wrapper = CachedEmbeddingWrapper(capture_embed)
    results = wrapper(["cached", "new"])

    assert called_with == ["new"]
    assert results[0] == [9.0, 9.0, 9.0, 9.0]
    assert results[1] == [float(sum(ord(c) for c in "new"))] * 4


def test_wrapper_single_string_vs_list():
    """Single string returns a single vector, list returns a list of vectors."""
    wrapper = CachedEmbeddingWrapper(_dummy_embed_fn)

    single_result = wrapper("hello")
    list_result = wrapper(["hello"])

    assert isinstance(single_result, list)
    assert isinstance(single_result[0], float)
    assert isinstance(list_result, list)
    assert isinstance(list_result[0], list)
    assert single_result == list_result[0]


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------


def test_cache_ttl_expiry():
    """After TTL expires, a previously cached query should miss."""
    from cachetools import TTLCache

    fast_expire = TTLCache(maxsize=64, ttl=0.01)
    with _CACHE_LOCK:
        old_cache = es._EMBED_CACHE
        es._EMBED_CACHE = fast_expire

    try:
        store_embedding("ephemeral", [1.0, 2.0, 3.0, 4.0])
        time.sleep(0.02)
        with pytest.raises(KeyError):
            get_cached_embedding("ephemeral")
    finally:
        with _CACHE_LOCK:
            es._EMBED_CACHE = old_cache


# ---------------------------------------------------------------------------
# Maxsize eviction
# ---------------------------------------------------------------------------


def test_cache_maxsize_eviction():
    """Insert more than maxsize entries — oldest should be evicted."""
    from cachetools import TTLCache

    small = TTLCache(maxsize=5, ttl=3600)
    with _CACHE_LOCK:
        old_cache = es._EMBED_CACHE
        es._EMBED_CACHE = small

    try:
        for i in range(10):
            store_embedding(f"key-{i}", [float(i)] * 4)
        with pytest.raises(KeyError):
            get_cached_embedding("key-0")
        with pytest.raises(KeyError):
            get_cached_embedding("key-1")
        get_cached_embedding("key-9")
        get_cached_embedding("key-8")
    finally:
        with _CACHE_LOCK:
            es._EMBED_CACHE = old_cache


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


def test_thread_safety():
    """Concurrent calls with the same query should all return the same result w/o corruption."""
    wrapper = CachedEmbeddingWrapper(_dummy_embed_fn)
    results: list[list[float] | None] = [None] * 50

    def worker(idx: int):
        results[idx] = wrapper("thread-safe-query")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(r == results[0] for r in results)
    assert get_cached_embedding("thread-safe-query") == results[0]
