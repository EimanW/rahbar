"""Ollama provider: ollama-host (laptop Ollama via host.minikube.internal) or
ollama-incluster (an Ollama Deployment). Same code, different OLLAMA_URL (section 3.5).

Constrained decoding: the Answer JSON schema goes in Ollama's `format` field, so the
reply is valid JSON of that shape. services/generation.py still validates it, because
structure can be guaranteed and truth cannot.
"""

from __future__ import annotations

from typing import Any

import httpx

from ...config import Settings
from .base import Completion


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.Client(timeout=httpx.Timeout(settings.llm_timeout, connect=5.0))

    def complete(self, messages: list[dict[str, str]], schema: dict[str, Any],
                 temperature: float) -> Completion:
        response = self._client.post(
            f"{self.settings.ollama_url.rstrip('/')}/api/chat",
            json={
                "model": self.settings.llm_model,
                "messages": messages,
                "format": schema,
                "stream": False,
                "options": {"temperature": temperature, "num_ctx": self.settings.num_ctx},
            },
        )
        response.raise_for_status()
        body = response.json()
        return Completion(text=body["message"]["content"],
                          tokens_in=int(body.get("prompt_eval_count", 0)),
                          tokens_out=int(body.get("eval_count", 0)))
