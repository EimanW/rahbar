"""Record the inputs and outputs needed to inspect a RAHBAR answer."""

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("rahbar.trace")
_write_lock = threading.Lock()
_INSTRUCTION = re.compile(
    r"ignore (?:all |the )?(?:previous |prior |earlier |your |system )*instructions"
    r"|</?\s*(?:system|instructions?)\b", re.IGNORECASE
)


def new_trace(trace_id, question, settings, provider):
    return {
        "event": "query_trace",
        "trace_id": trace_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query": question,
        "rewritten_query": None,
        "embedding_model": settings.embed_model,
        "embedding_version": settings.embed_model.partition(":")[2] or "default",
        "collection": settings.collection,
        "collection_version": None,
        "retrieved": [],
        "reranked_order": [],
        "filters": {},
        "context": [],
        "prompts": [],
        "model": settings.llm_model if provider != "stub" else provider,
        "provider": provider,
        "parameters": {"temperature": settings.temperature, "num_ctx": settings.num_ctx,
                       "top_k": settings.top_k},
        "response": None,
        "citations": [],
        "guardrail_actions": [],
        "latency_ms": {},
        "cache": "off",
    }


def reject_instructions(passages, relevance_floor, actions):
    context = []
    for passage in passages:
        if _INSTRUCTION.search(passage.text):
            actions.append({"action": "drop_injected_chunk", "chunk_id": passage.chunk_id,
                            "doc_id": passage.doc_id or passage.source, "source": passage.source})
        elif passage.score >= relevance_floor:
            context.append(passage)
    return context


def write_trace(record):
    for key in ("retrieved", "context"):
        for passage in record.get(key, []):
            if not passage.get("doc_id"):
                passage["doc_id"] = passage.get("source")

    line = json.dumps(record, ensure_ascii=True)
    print(line, flush=True)
    target = os.environ.get("TRACE_FILE")
    if target:
        try:
            path = Path(target)
            path.parent.mkdir(parents=True, exist_ok=True)
            with _write_lock, path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
        except OSError:
            log.exception("could not append query trace to volume")
