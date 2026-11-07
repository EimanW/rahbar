"""Hosted free-tier provider (Groq, Google AI Studio's OpenAI endpoint, OpenRouter).

The key arrives as LLM_API_KEY from a Kubernetes Secret created on the command
line. It never appears in a file you commit, and never in a log line.

All three expose an OpenAI-compatible POST {HOSTED_BASE_URL}/chat/completions. We ask
for JSON mode with response_format; the schema itself is also in the system prompt,
and services/generation.py validates the reply either way.
"""

from __future__ import annotations

from typing import Any

import httpx

from ...config import Settings
from .base import Completion


class HostedProvider:
    name = "hosted"

    def __init__(self, settings: Settings) -> None:
        if not settings.hosted_base_url or not settings.llm_api_key:
            raise ValueError("LLM_PROVIDER=hosted needs HOSTED_BASE_URL (ConfigMap) and "
                             "LLM_API_KEY (Secret rahbar-secret)")
        self.settings = settings
        self._client = httpx.Client(
            timeout=httpx.Timeout(settings.llm_timeout, connect=5.0),
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        )

    def complete(self, messages: list[dict[str, str]], schema: dict[str, Any],
                 temperature: float) -> Completion:
        response = self._client.post(
            f"{self.settings.hosted_base_url.rstrip('/')}/chat/completions",
            json={"model": self.settings.llm_model, "messages": messages,
                  "temperature": temperature, "response_format": {"type": "json_object"}},
        )
        response.raise_for_status()
        body = response.json()
        usage = body.get("usage") or {}
        return Completion(text=body["choices"][0]["message"]["content"] or "",
                          tokens_in=int(usage.get("prompt_tokens", 0)),
                          tokens_out=int(usage.get("completion_tokens", 0)))
