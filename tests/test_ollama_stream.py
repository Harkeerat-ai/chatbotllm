"""Tests for ollama_client stream_chat response parsing."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_stream_chat_skips_done_true_chunk():
    """Verify that a final `done:true` chunk with empty content is NOT leaked
    as raw JSON into the answer (regression test for the bug where
    `{"message":{"role":"assistant","content":""},"done":true,...}` was
    yielded as a raw line)."""
    from app.ollama_client import ollama

    content_lines = [
        '{"model":"g","message":{"role":"assistant","content":"Hello"},"done":false}\n',
        '{"model":"g","message":{"role":"assistant","content":" world"},"done":false}\n',
        '{"model":"g","message":{"role":"assistant","content":""},"done":true,"done_reason":"stop"}\n',
    ]

    class FakeResponse:
        status_code = 200

        async def aiter_text(self):
            for line in content_lines:
                yield line

    class FakeStreamCM:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *a):
            pass

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        def stream(self, *a, **kw):
            return FakeStreamCM()

    with patch("httpx.AsyncClient", return_value=FakeAsyncClient()):
        collected = []
        async for chunk in ollama.stream_chat("system", [], "context"):
            collected.append(chunk)

    answer = "".join(collected)
    assert answer == "Hello world", f"Expected 'Hello world', got {answer!r}"
    assert "{" not in answer, f"Raw JSON leaked into answer: {answer!r}"
    assert '"done"' not in answer, f"Raw JSON leaked into answer: {answer!r}"


@pytest.mark.asyncio
async def test_stream_chat_handles_no_message_done_chunk():
    """Verify that a `done:true` chunk with NO message key is also skipped."""
    from app.ollama_client import ollama

    content_lines = [
        '{"model":"g","message":{"role":"assistant","content":"Hi"},"done":false}\n',
        '{"model":"g","done":true,"done_reason":"stop"}\n',
    ]

    class FakeResponse:
        status_code = 200

        async def aiter_text(self):
            for line in content_lines:
                yield line

    class FakeStreamCM:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *a):
            pass

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        def stream(self, *a, **kw):
            return FakeStreamCM()

    with patch("httpx.AsyncClient", return_value=FakeAsyncClient()):
        collected = []
        async for chunk in ollama.stream_chat("system", [], "context"):
            collected.append(chunk)

    answer = "".join(collected)
    assert answer == "Hi", f"Expected 'Hi', got {answer!r}"
    assert "{" not in answer, f"Raw JSON leaked: {answer!r}"
