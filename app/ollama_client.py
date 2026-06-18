"""
LLM client — chat generation via Groq API (OpenAI-compatible).
"""

from __future__ import annotations
import json
import logging
import time
from typing import AsyncGenerator

import httpx
from httpx import ConnectError, TimeoutException
import requests

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMClient:
    def __init__(self):
        self.base_url = settings.groq_base_url
        self.chat_model = settings.groq_model
        self._groq_api_key = settings.groq_api_key

    def _is_available(self) -> bool:
        return bool(self._groq_api_key)

    async def stream_chat(
        self,
        system_prompt: str,
        messages: list[dict],
        context: str,
        append_rag_instruction: bool = True,
    ) -> AsyncGenerator[str, None]:
        """Async generator yielding string chunks from Groq as they arrive."""
        if not self._groq_api_key:
            yield (
                "[LLM unavailable: GROQ_API_KEY not set. "
                "Add it to .env — see console.groq.com]"
            )
            return

        if append_rag_instruction:
            full_system = (
                f"{system_prompt}\n\n"
                "Use the following context to answer. "
                "If the answer is not in the context, say you don't know.\n\n"
                f"Context:\n{context}"
            )
        else:
            full_system = f"{system_prompt}\n\nData:\n{context}"

        payload = {
            "model": self.chat_model,
            "messages": [{"role": "system", "content": full_system}] + messages,
            "stream": True,
            "max_tokens": 180,
            "temperature": 0.3,
        }

        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._groq_api_key}"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code == 401:
                        yield "[LLM error 401: invalid API key]"
                        return
                    if resp.status_code == 429:
                        yield "[LLM error 429: rate limited — try again shortly]"
                        return
                    if resp.status_code != 200:
                        body = await resp.aread()
                        yield f"[LLM error {resp.status_code}: {body.decode(errors='replace')[:200]}]"
                        return

                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                            content = (
                                obj.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("content", "")
                            )
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            pass
        except ConnectError:
            yield "[LLM unavailable: cannot reach Groq API — check internet]"
        except TimeoutException:
            yield "[LLM error: request timed out]"
        except Exception as e:
            yield f"[LLM error: {e}]"

    async def chat(
        self,
        system_prompt: str,
        messages: list[dict],
        context: str,
        append_rag_instruction: bool = True,
    ) -> tuple[str, int]:
        """Async wrapper that accumulates streamed chunks and returns (answer, latency_ms)."""
        t0 = time.monotonic()
        answer_parts: list[str] = []
        async for chunk in self.stream_chat(
            system_prompt, messages, context,
            append_rag_instruction=append_rag_instruction,
        ):
            answer_parts.append(chunk)
        latency_ms = int((time.monotonic() - t0) * 1000)
        return "".join(answer_parts), latency_ms

    async def warmup(self) -> None:
        """Verify the Groq API key works and log available models."""
        if not self._groq_api_key:
            logger.warning("GROQ_API_KEY not set — skipping warmup")
            return
        try:
            r = requests.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self._groq_api_key}"},
                timeout=5,
            )
            if r.status_code == 200:
                models = [m["id"] for m in r.json().get("data", [])]
                logger.info(
                    "Groq API ready — %d models available, using %s",
                    len(models), self.chat_model,
                )
            else:
                logger.warning("Groq API check returned %s", r.status_code)
        except Exception as e:
            logger.warning("Groq API check failed: %s", e)


ollama = LLMClient()
