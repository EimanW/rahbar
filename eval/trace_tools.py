import argparse
import json
import math
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=["replay", "metrics"])
parser.add_argument("--id")
parser.add_argument("--hours", type=float, default=24)
parser.add_argument("--dir", default="traces")
args = parser.parse_args()

records = {}

for path in Path(args.dir).glob("*.jsonl"):
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            r = json.loads(line)
            if r.get("event") == "query_trace":
                records[r["trace_id"]] = r
        except (ValueError, KeyError):
            continue

if args.mode == "replay":
    r = records.get(args.id)
    if not r:
        raise SystemExit("Trace not found")

    print("TRACE ID:", args.id)
    print("QUERY:", r.get("query"))
    print("COLLECTION:", r.get("collection"))
    print("CACHE:", r.get("cache"))
    print("EXACT CONTEXT:")
    print(json.dumps(r.get("context"), indent=2))
    print("EXACT PROMPTS:")
    print(json.dumps(r.get("prompts"), indent=2))
    print("RESPONSE:")
    print(json.dumps(r.get("response"), indent=2))
    print("GUARDRAILS:")
    print(json.dumps(r.get("guardrail_actions"), indent=2))
    raise SystemExit(0)

cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours)
rows = [
    r for r in records.values()
    if datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")) >= cutoff
]

if not rows:
    raise SystemExit("No traces in selected time window")

def percentile(values, p):
    values = sorted(values)
    return values[max(0, math.ceil(len(values)*p)-1)] if values else None

stages = defaultdict(list)
scores = []
abstentions = 0
known_responses = 0
cache_hits = 0
injections = 0

for r in rows:
    retrieved = r.get("retrieved") or []
    if retrieved and retrieved[0].get("score") is not None:
        scores.append(retrieved[0]["score"])

    response = r.get("response")
    if isinstance(response, dict) and "answered_from_context" in response:
        known_responses += 1
        abstentions += int(not response["answered_from_context"])

    cache_hits += int(r.get("cache") == "hit")

    injections += sum(
        a.get("action") == "drop_injected_chunk"
        for a in r.get("guardrail_actions", [])
        if isinstance(a, dict)
    )

    for stage, value in r.get("latency_ms", {}).items():
        if isinstance(value, (int, float)):
            stages[stage].append(value)

result = {
    "window_hours": args.hours,
    "queries": len(rows),
    "top1_similarity": {
        "p50": percentile(scores, .50),
        "p95": percentile(scores, .95),
        "min": min(scores) if scores else None,
        "max": max(scores) if scores else None,
        "distribution": {
            str(i/10): sum(i/10 <= s < (i+1)/10 for s in scores)
            for i in range(-10, 11)
        }
    },
    "abstention_rate": abstentions/known_responses if known_responses else None,
    "cache_hit_rate": cache_hits/len(rows),
    "injection_flags": injections,
    "stage_p95_ms": {
        stage: percentile(values, .95)
        for stage, values in stages.items()
    }
}

print(json.dumps(result, indent=2))
out = Path("eval/results")
out.mkdir(parents=True, exist_ok=True)
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
(out / f"observability-{stamp}.json").write_text(
    json.dumps(result, indent=2), encoding="utf-8"
)
