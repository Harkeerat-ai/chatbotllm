from __future__ import annotations
import json

import pytest


def test_cache_key_format():
    from app.rag_service import _cache_key
    key = _cache_key("testbrand", "what is this?")
    assert len(key) == 32
    assert isinstance(key, str)


def test_cache_key_deterministic():
    from app.rag_service import _cache_key
    assert _cache_key("b", "hello") == _cache_key("b", "hello")


def test_cache_key_differs_for_different_brands():
    from app.rag_service import _cache_key
    assert _cache_key("a", "hello") != _cache_key("b", "hello")


def test_cache_key_differs_for_different_messages():
    from app.rag_service import _cache_key
    assert _cache_key("b", "hello") != _cache_key("b", "world")


def test_cache_key_with_history():
    from app.rag_service import _cache_key
    history = [{"role": "user", "content": "what is this?"}, {"role": "assistant", "content": "that is a test"}]
    no_history = _cache_key("b", "hello")
    with_history = _cache_key("b", "hello", history)
    assert no_history != with_history


def test_cache_key_history_different():
    from app.rag_service import _cache_key
    h1 = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    h2 = [{"role": "user", "content": "bye"}, {"role": "assistant", "content": "goodbye"}]
    assert _cache_key("b", "hello", h1) != _cache_key("b", "hello", h2)


def test_cache_ttl_structure():
    from cachetools import TTLCache
    cache = TTLCache(maxsize=256, ttl=3600)
    cache["key1"] = {"answer": "test"}
    assert cache["key1"]["answer"] == "test"
    assert len(cache) == 1


def test_cache_maxsize_eviction():
    from cachetools import TTLCache
    cache = TTLCache(maxsize=2, ttl=3600)
    cache["a"] = 1
    cache["b"] = 2
    cache["c"] = 3
    assert len(cache) == 2
    assert "a" not in cache


def test_cache_lock_pattern():
    import threading
    lock = threading.Lock()
    cache = {}
    with lock:
        cache["key"] = "value"
    with lock:
        val = cache.get("key")
    assert val == "value"


def test_cache_miss_returns_none():
    from cachetools import TTLCache
    cache = TTLCache(maxsize=10, ttl=60)
    assert cache.get("nonexistent") is None


def test_clear_response_cache():
    from app.rag_service import _resp_cache, _resp_lock, clear_response_cache
    clear_response_cache()
    with _resp_lock:
        _resp_cache["foo"] = "bar"
    assert len(_resp_cache) == 1
    clear_response_cache()
    assert len(_resp_cache) == 0


def test_cache_hit_in_ask_stream_returns_immediately(monkeypatch):
    from app.rag_service import rag_service, _resp_cache, _resp_lock, _cache_key

    class FakeBrand:
        slug = "testbrand"
        id = 1
        name = "Test Brand"

    key = _cache_key("testbrand", "cached_msg")
    with _resp_lock:
        _resp_cache.clear()
        _resp_cache[key] = {"answer": "cached reply", "brand": "testbrand", "session_id": "sess",
                            "sources": [], "citations": [], "urls": [], "latency_ms": 0, "message_id": None}

    import asyncio

    async def run():
        chunks = []
        async for chunk in rag_service.ask_stream(None, FakeBrand(), "sess", "cached_msg"):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(run())
    assert len(chunks) == 1
    data = json.loads(chunks[0].replace("data: ", "").strip())
    assert data["answer"] == "cached reply"


def test_cache_hit_in_ask(monkeypatch):
    import asyncio
    from app.rag_service import rag_service, _resp_cache, _resp_lock, _cache_key

    class FakeBrand:
        slug = "testbrand"
        id = 1
        name = "Test Brand"

    key = _cache_key("testbrand", "cached_q")
    with _resp_lock:
        _resp_cache.clear()
        _resp_cache[key] = {"answer": "cached", "brand": "testbrand", "session_id": "sess",
                            "sources": [], "citations": [], "urls": [], "latency_ms": 0}

    async def run():
        return await rag_service.ask(None, FakeBrand(), "sess", "cached_q")

    result = asyncio.run(run())
    assert result["answer"] == "cached"



