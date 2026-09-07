"""
LLM client — chat generation via OpenRouter (OpenAI-compatible).

Falls back to Groq if OPENROUTER_API_KEY is unset but GROQ_API_KEY is present.
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
from app.translations import get_text, DEFAULT_LANGUAGE

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMClient:
    def __init__(self):
        if settings.openrouter_api_key:
            self.provider = "openrouter"
            self.base_url = settings.openrouter_base_url
            self.chat_model = settings.openrouter_model
            self._api_key = settings.openrouter_api_key
        else:
            self.provider = "groq"
            self.base_url = settings.groq_base_url
            self.chat_model = settings.groq_model
            self._api_key = settings.groq_api_key

    def _is_available(self) -> bool:
        return bool(self._api_key)

    def _build_headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if self.provider == "openrouter":
            headers["HTTP-Referer"] = settings.openrouter_site_url
            headers["X-Title"] = settings.openrouter_app_name
        return headers

    async def stream_chat(
        self,
        system_prompt: str,
        messages: list[dict],
        context: str,
        append_rag_instruction: bool = True,
    ) -> AsyncGenerator[str, None]:
        """Async generator yielding string chunks from Groq as they arrive."""
        if not self._api_key:
            yield get_text("llm.error.api_key", DEFAULT_LANGUAGE)
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

        payload: dict = {
            "model": self.chat_model,
            "messages": [{"role": "system", "content": full_system}] + messages,
            "stream": True,
            "max_tokens": 180,
            "temperature": 0.3,
        }
        if self.provider == "openrouter" and settings.openrouter_providers:
            payload["provider"] = {
                "order": settings.openrouter_providers,
                "allow_fallbacks": True,
            }

        url = f"{self.base_url}/chat/completions"
        headers = self._build_headers()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code == 401:
                        yield get_text("llm.error.http", DEFAULT_LANGUAGE).format(status_code=401, message="invalid API key")
                        return
                    if resp.status_code == 429:
                        yield get_text("llm.error.rate_limited", DEFAULT_LANGUAGE)
                        return
                    if resp.status_code != 200:
                        body = await resp.aread()
                        yield get_text("llm.error.http", DEFAULT_LANGUAGE).format(
                            status_code=resp.status_code,
                            message=body.decode(errors='replace')[:200]
                        )
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
            yield get_text("llm.error.unavailable", DEFAULT_LANGUAGE)
        except TimeoutException:
            yield get_text("llm.error.timeout", DEFAULT_LANGUAGE)
        except Exception as e:
            yield get_text("llm.error.generic", DEFAULT_LANGUAGE).format(error=str(e))

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
        """Verify the LLM API key works and log available models."""
        if not self._api_key:
            logger.warning("%s API key not set — skipping warmup", self.provider.upper())
            return
        try:
            r = requests.get(
                f"{self.base_url}/models",
                headers=self._build_headers(),
                timeout=5,
            )
            if r.status_code == 200:
                models = [m["id"] for m in r.json().get("data", [])]
                logger.info(
                    "%s API ready — %d models available, using %s",
                    self.provider.upper(), len(models), self.chat_model,
                )
            else:
                logger.warning("%s API check returned %s", self.provider.upper(), r.status_code)
        except Exception as e:
            logger.warning("%s API check failed: %s", self.provider.upper(), e)


llm = LLMClient()
