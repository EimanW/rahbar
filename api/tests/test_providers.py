"""The real providers' request and response handling, against httpx mock transports:
no network. Checks constrained decoding is requested and token counts are read."""

from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.providers.llm import get_provider
from app.providers.llm.hosted import HostedProvider
from app.providers.llm.ollama import OllamaProvider
from app.services.generation import ANSWER_SCHEMA

REPLY = json.dumps({"reasoning": "r", "answer": "a", "citations": [],
                    "answered_from_context": False, "confidence": "low"})


def test_ollama_sends_the_schema_as_format_and_reads_tokens() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": REPLY},
                                         "prompt_eval_count": 321, "eval_count": 45})

    p = OllamaProvider(Settings(llm_model="llama3.2:3b", temperature=0.1))
    p._client = httpx.Client(transport=httpx.MockTransport(handler))
    out = p.complete([{"role": "user", "content": "q"}], ANSWER_SCHEMA, 0.1)
    assert seen["format"] == ANSWER_SCHEMA and seen["stream"] is False
    assert seen["options"]["temperature"] == 0.1 and seen["options"]["num_ctx"] == 8192
    assert (out.text, out.tokens_in, out.tokens_out) == (REPLY, 321, 45)


def test_hosted_uses_json_mode_and_bearer_key() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": REPLY}}],
                                         "usage": {"prompt_tokens": 7, "completion_tokens": 3}})

    p = HostedProvider(Settings(hosted_base_url="https://example.invalid/v1",
                                llm_api_key="test-key", llm_model="m"))
    p._client = httpx.Client(transport=httpx.MockTransport(handler),
                             headers={"Authorization": "Bearer test-key"})
    out = p.complete([{"role": "user", "content": "q"}], ANSWER_SCHEMA, 0.2)
    assert seen["response_format"] == {"type": "json_object"}
    assert seen["auth"] == "Bearer test-key"
    assert out.tokens_in == 7


def test_hosted_refuses_to_start_without_a_key() -> None:
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        HostedProvider(Settings(hosted_base_url="https://x"))


def test_provider_selection_by_config() -> None:
    assert get_provider(Settings(llm_provider="ollama-host")).name == "ollama"
    with pytest.raises(ValueError):
        get_provider(Settings(llm_provider="nope"))
