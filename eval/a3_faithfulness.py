import json
import re
from pathlib import Path
from datetime import datetime, timezone

def normalize(text):
    return " ".join(text.lower().split())

records = {}

for path in Path("traces").glob("*.jsonl"):
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            r = json.loads(line)
            if r.get("event") == "query_trace":
                records[r["trace_id"]] = r
        except (ValueError, KeyError):
            continue

def get_context(record):
    seen = set()
    while record:
        tid = record.get("trace_id")
        if tid in seen:
            return []
        seen.add(tid)
        if record.get("context"):
            return record["context"]
        record = records.get(record.get("cached_from_trace_id"))
    return []

def evaluate():
    groups = {}

    for tid, record in sorted(records.items()):
        response = record.get("response") or {}
        if not response.get("answered_from_context"):
            continue

        group = record.get("collection") or "unknown"
        rows = groups.setdefault(group, [])
        context = get_context(record)
        answer = response.get("answer", "")

        if "The first one says:" not in answer or not context:
            rows.append({
                "trace_id": tid,
                "supported": None,
                "reason": "Missing context or unsupported answer format"
            })
            continue

        claim = answer.split("The first one says:", 1)[1]
        claim = re.sub(r"\s*\[[^\]]+\]\s*$", "", claim)
        claim = normalize(claim).rstrip(".").rstrip("…").rstrip(".")

        evidence = [
            normalize(p.get("text", ""))
            for p in context
        ]

        supported = bool(claim) and any(
            claim in passage for passage in evidence
        )

        rows.append({
            "trace_id": tid,
            "question": record.get("query"),
            "claim": claim,
            "supported": supported
        })

    result = {}

    for group, rows in groups.items():
        scored = [r for r in rows if r["supported"] is not None]
        supported = sum(r["supported"] for r in scored)

        result[group] = {
            "answered_queries": len(rows),
            "evaluated": len(scored),
            "skipped": len(rows) - len(scored),
            "supported": supported,
            "faithfulness": supported / len(scored) if scored else None,
            "details": rows
        }

    return result

first = evaluate()
second = evaluate()

assert first == second

result = {
    "method": "Deterministic extractive claim support against actual trace context",
    "limitations": "Designed for stub answers; measures textual grounding, not semantic correctness. Abstentions are evaluated separately.",
    "repeatability_identical": first == second,
    "collections": first
}

out = Path("eval/results")
out.mkdir(exist_ok=True)
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
path = out / f"faithfulness-{stamp}.json"
path.write_text(json.dumps(result, indent=2), encoding="utf-8")

print("FAITHFULNESS EVALUATION")
for name, data in first.items():
    print("\nCOLLECTION:", name)
    for key, value in data.items():
        if key != "details":
            print(key, ":", value)

print("\nREPEATABILITY IDENTICAL:", first == second)
print("RESULT SAVED:", path)
