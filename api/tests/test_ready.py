"""Readiness: 503 naming the failed dependency; liveness never touches dependencies."""

from __future__ import annotations

from types import SimpleNamespace

import fakeredis

from app.routes.health import readiness_report
from app.services.cache import SemanticCache
from tests.test_pipeline import FakeChroma, FakeCollection, ROWS, settings

from app.retrieval.chroma import ChromaRetriever


def state(collection: FakeCollection | None, cache: SemanticCache | None = None,
          model: str = "hash-bow-256") -> SimpleNamespace:
    r = ChromaRetriever(settings(embed_model=model), client=FakeChroma(collection))
    return SimpleNamespace(retriever=r, cache=cache, settings=settings(embed_model=model))


def test_ready_when_everything_is_there() -> None:
    col = FakeCollection(ROWS, {"embed_model": "hash-bow-256", "dimension": 256})
    cache = SemanticCache(fakeredis.FakeRedis(), 0.95, 60)
    checks = readiness_report(state(col, cache))
    assert set(checks.values()) == {"ok"}


def test_not_ready_without_a_collection() -> None:
    checks = readiness_report(state(None))
    assert checks["chroma"].startswith("unavailable")


def test_not_ready_when_the_collection_is_empty() -> None:
    col = FakeCollection([], {"embed_model": "hash-bow-256"})
    assert readiness_report(state(col))["collection"] == "collection is empty"


def test_not_ready_on_an_embedding_model_mismatch() -> None:
    col = FakeCollection(ROWS, {"embed_model": "dummy-768", "dimension": 768})
    checks = readiness_report(state(col, model="nomic-embed-text"))
    assert "dummy-768" in checks["embed_model"] and "nomic-embed-text" in checks["embed_model"]


def test_not_ready_when_redis_is_down() -> None:
    class DeadRedis:
        def ping(self) -> bool:
            raise ConnectionError("no route to redis")

    col = FakeCollection(ROWS, {"embed_model": "hash-bow-256"})
    checks = readiness_report(state(col, SemanticCache(DeadRedis(), 0.95, 60)))
    assert checks["redis"].startswith("unavailable")


def test_readyz_endpoint_returns_503_with_the_reason(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    monkeypatch.setenv("RETRIEVER", "stub")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    from app.main import app

    with TestClient(app) as client:
        assert client.get("/readyz").status_code == 200
        app.state.retriever = state(None).retriever
        r = client.get("/readyz")
        assert r.status_code == 503 and "chroma" in r.json()["failed"]
        assert client.get("/healthz").status_code == 200       # liveness unaffected


def test_ask_returns_503_not_500_when_the_pin_is_broken(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    monkeypatch.setenv("RETRIEVER", "stub")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    from app.main import app

    col = FakeCollection(ROWS, {"embed_model": "dummy-768", "dimension": 768})
    with TestClient(app) as client:
        app.state.retriever = state(col, model="nomic-embed-text").retriever
        app.state.retriever.embedder.model = "hash-bow-256"   # embed offline; pin still differs
        r = client.post("/api/ask", json={"question": "What is the attendance rule?"})
        assert r.status_code == 503 and "mismatch" in r.json()["detail"]
