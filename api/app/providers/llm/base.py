"""The LLM provider interface (section 3.5). Swapping providers is one file.

A provider does one thing: send chat messages with a JSON schema for the output and
return the raw text plus token counts. Prompt building, validation, the retry and the
fallback are NOT provider concerns; they live once in services/generation.py, so every
provider gets them for free and a swap cannot forget one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class Completion:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0


class LLMProvider(Protocol):
    name: str

    def complete(self, messages: list[dict[str, str]], schema: dict[str, Any],
                 temperature: float) -> Completion:
        """Return the model's reply to `messages`, constrained to `schema` where the
        provider supports it. Raise on transport errors; never parse here."""
        ...
