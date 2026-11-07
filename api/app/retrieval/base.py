"""The retriever interface. The rest of the API only ever sees this."""

from __future__ import annotations

from typing import Protocol

from ..schemas import Passage


class Retriever(Protocol):
    name: str

    def embed(self, text: str) -> list[float]:
        """Embed with the pinned model. Used for retrieval and for the semantic cache."""
        ...

    def index_version(self) -> str:
        """Identifies the index; the cache namespaces its entries by it (section 3.3)."""
        ...

    def retrieve(self, question: str, k: int, vector: list[float] | None = None) -> list[Passage]:
        """Return up to k passages, best first. `vector` skips re-embedding the question."""
        ...
