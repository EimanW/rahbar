"""Inspect recorded prompts or summarize query traces over a sliding time window."""

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path


def query_traces(path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("event") == "query_trace":
                yield row


def summarize(rows):
    scores = {"below_0.5": 0, "0.5_to_0.75": 0, "0.75_and_above": 0}
    latencies = {}
    hits = misses = abstentions = injections = answered = 0
    for row in rows:
        if row["retrieved"]:
            score = max(chunk["score"] for chunk in row["retrieved"])
            band = "below_0.5" if score < 0.5 else "0.5_to_0.75" if score < 0.75 else "0.75_and_above"
            scores[band] += 1
        for stage, elapsed in row["latency_ms"].items():
            latencies.setdefault(stage, []).append(elapsed)
        hits += row["cache"] == "hit"
        misses += row["cache"] == "miss"
        if row["response"] is not None:
            answered += 1
            abstentions += not row["response"]["answered_from_context"]
        injections += sum(item["action"] == "drop_injected_chunk"
                          for item in row["guardrail_actions"])
    return {
        "queries": len(rows),
        "top_similarity_distribution": scores,
        "abstention_rate": abstentions / answered if answered else None,
        "cache_hit_rate": hits / (hits + misses) if hits + misses else None,
        "injected_chunks_flagged": injections,
        "p95_latency_ms": {
            stage: sorted(samples)[math.ceil(.95 * len(samples)) - 1]
            for stage, samples in latencies.items()
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=Path("traces/queries.jsonl"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("show").add_argument("trace_id")
    commands.add_parser("summary").add_argument("--hours", type=float, default=24)
    args = parser.parse_args()
    rows = list(query_traces(args.file))
    if args.command == "summary":
        since = datetime.now(timezone.utc) - timedelta(hours=args.hours)
        report = summarize([row for row in rows
                            if datetime.fromisoformat(row["timestamp"]) >= since])
    else:
        by_id = {row["trace_id"]: row for row in rows}
        if args.trace_id not in by_id:
            parser.error(f"unknown trace: {args.trace_id}")
        report = by_id[args.trace_id]
        if report.get("cached_from_trace_id"):
            origin_id = report["cached_from_trace_id"]
            report = {**report, "cached_origin": by_id.get(origin_id)}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
