#!/usr/bin/env python3
"""Part E2/E4: query coverage. Does the golden set still look like real usage?

For every live query, find the most similar golden question (cosine similarity of
nomic-embed-text embeddings). A live query is "covered" when that best score is at
least --sim. The run fails (exit 1) when the covered share is below --min-share.

    python eval/coverage.py
    python eval/coverage.py --sim 0.77 --min-share 0.85

Why 0.77: on the first run we labelled every (live query, best golden question) pair by
hand. Every pair scoring 0.77 or more asks about the same rule as its golden match; the
first pair that does not (L19, 0.768: max credit hours vs summer course limit) sits just
below. 0.80 missed clear matches such as L15 (fee per credit hour, 0.794).
Why 85%: the paper's example flags a coverage gap when under 85% of queries reach the score.

Writes eval/results/coverage-<timestamp>.json and prints a summary with the
uncovered queries grouped by topic.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
PREFIX = "search_query: "  # same prefix the API uses for nomic-embed-text queries


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def embed(texts: list[str], url: str, model: str) -> list[list[float]]:
    prefix = PREFIX if model.startswith("nomic-embed-text") else ""
    r = httpx.post(f"{url.rstrip('/')}/api/embed",
                   json={"model": model, "input": [prefix + t for t in texts]}, timeout=120)
    r.raise_for_status()
    return r.json()["embeddings"]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--golden", default=str(HERE / "golden.jsonl"))
    p.add_argument("--live", default=str(HERE / "live_queries.jsonl"))
    p.add_argument("--sim", type=float, default=float(os.getenv("COVERAGE_SIM", "0.77")),
                   help="a live query is covered when its best golden match is >= this")
    p.add_argument("--min-share", type=float, default=float(os.getenv("COVERAGE_MIN_SHARE", "0.85")),
                   help="fail when the covered share is below this (paper's example: 85%%)")
    p.add_argument("--ollama", default=os.getenv("OLLAMA_URL", "http://localhost:11434"))
    p.add_argument("--model", default=os.getenv("EMBED_MODEL", "nomic-embed-text"))
    p.add_argument("--out", default=str(HERE / "results"))
    args = p.parse_args()

    golden = read_jsonl(Path(args.golden))
    live = read_jsonl(Path(args.live))
    g_vecs = embed([g["question"] for g in golden], args.ollama, args.model)
    l_vecs = embed([q["query"] for q in live], args.ollama, args.model)

    rows = []
    for q, qv in zip(live, l_vecs):
        scores = [cosine(qv, gv) for gv in g_vecs]
        best = max(range(len(scores)), key=scores.__getitem__)
        rows.append({
            "id": q["id"], "query": q["query"], "topic": q.get("topic", "?"),
            "best_golden_id": golden[best]["id"], "best_golden": golden[best]["question"],
            "score": round(scores[best], 4), "covered": scores[best] >= args.sim,
        })

    covered = sum(r["covered"] for r in rows)
    share = covered / len(rows)
    passed = share >= args.min_share
    gaps: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if not r["covered"]:
            gaps[r["topic"]].append(r)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result = {
        "timestamp": stamp, "model": args.model, "golden_file": args.golden,
        "golden_count": len(golden), "live_count": len(rows),
        "sim_threshold": args.sim, "min_share": args.min_share,
        "covered": covered, "share": round(share, 4), "passed": passed,
        "uncovered_by_topic": {t: [r["id"] for r in rs] for t, rs in gaps.items()},
        "rows": rows,
    }
    path = out / f"coverage-{stamp}.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"golden questions : {len(golden)}")
    print(f"live queries     : {len(rows)}")
    print(f"similarity >=    : {args.sim}")
    print(f"covered          : {covered}/{len(rows)} = {share:.1%}  (need {args.min_share:.0%})")
    print(f"result           : {'PASS' if passed else 'FAIL'}")
    if gaps:
        print("\nuncovered queries by topic:")
        for topic, rs in sorted(gaps.items(), key=lambda kv: -len(kv[1])):
            print(f"  {topic} ({len(rs)})")
            for r in rs:
                print(f"    {r['id']}  {r['score']:.3f}  {r['query']}")
    print(f"\nwritten: {path}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
