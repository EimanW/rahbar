import json
import math
import time
import statistics
import datetime
import random
from pathlib import Path
import httpx

random.seed(42)
HERE = Path(__file__).resolve().parent
API = "http://127.0.0.1:18080/api/ask"

questions = [
    json.loads(line)
    for line in (HERE / "golden.jsonl").read_text(
        encoding="utf-8-sig"
    ).splitlines() if line.strip()
]

def mean(values):
    return statistics.mean(values) if values else None

def evaluate(noise=False):
    rows = []
    with httpx.Client(timeout=60) as client:
        for q in questions:
            question = q["question"]
            if noise:
                question = question.replace("the ", "teh ").replace("student", "studnet")
                if question == q["question"]:
                    question += " pls"

            start = time.perf_counter()
            response = client.post(API, json={"question": question})
            response.raise_for_status()
            r = response.json()
            latency = (time.perf_counter() - start) * 1000

            gold = {
                (g["source"], g["page"])
                for g in q.get("ground_truth", [])
            }

            retrieved = r.get("retrieved", [])
            seen = set()
            hits = []

            for item in retrieved[:5]:
                key = (item.get("source"), item.get("page"))
                hits.append(int(key in gold and key not in seen))
                seen.add(key)

            citations = r.get("citations", [])
            valid = [
                int(any(
                    c.get("source") == t.get("source")
                    and c.get("page") == t.get("page")
                    for t in retrieved
                ))
                for c in citations
            ]

            row = {
                "id": q["id"],
                "trace_id": r.get("request_id"),
                "question": question,
                "answer": r.get("answer"),
                "retrieved": retrieved,
                "citations": citations,
                "latency_ms": latency,
                "cached": r.get("cached"),
                "citation_validity": mean(valid),
                "must_abstain": q.get("must_abstain", False),
                "answered": r.get("answered_from_context"),
                "expected_text_hit": (
                    int(q["expect"].lower() in r.get("answer", "").lower())
                    if q.get("expect") else None
                )
            }

            if gold:
                row["recall@3"] = sum(hits[:3]) / len(gold)
                row["recall@5"] = sum(hits) / len(gold)
                row["mrr"] = next(
                    (1/(i+1) for i,h in enumerate(hits) if h), 0
                )
                row["ndcg@5"] = sum(
                    h/math.log2(i+2) for i,h in enumerate(hits)
                ) / sum(
                    1/math.log2(i+2) for i in range(min(5,len(gold)))
                )

            rows.append(row)
            print(q["id"], r.get("request_id"), flush=True)

    metrics = {}
    for key in [
        "recall@3", "recall@5", "mrr", "ndcg@5",
        "citation_validity", "expected_text_hit"
    ]:
        metrics[key] = mean([
            r[key] for r in rows if r.get(key) is not None
        ])

    metrics["abstention_correctness"] = mean([
        int(not r["answered"]) for r in rows if r["must_abstain"]
    ])

    times = sorted(r["latency_ms"] for r in rows)
    metrics["latency_p50_ms"] = statistics.median(times)
    metrics["latency_p95_ms"] = times[math.ceil(len(times)*0.95)-1]

    return {"metrics": metrics, "rows": rows}

def difference(a, b):
    return {
        k: b[k]-v for k,v in a.items()
        if v is not None and b.get(k) is not None
    }

print("RUN 1: BASELINE")
first = evaluate()

print("RUN 2: REPEATABILITY")
second = evaluate()

print("RUN 3: NOISE TEST")
noise = evaluate(True)

result = {
    "seed": 42,
    "questions": len(questions),
    "first": first,
    "second": second,
    "noise": noise,
    "repeat_delta": difference(first["metrics"], second["metrics"]),
    "noise_delta": difference(first["metrics"], noise["metrics"]),
    "limitations": "Expected text hit is not faithfulness. Cache affects repeat latency."
}

out = HERE / "results"
out.mkdir(exist_ok=True)
stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
path = out / f"a3-{stamp}.json"
path.write_text(json.dumps(result, indent=2), encoding="utf-8")

print("\nBASELINE METRICS")
print(json.dumps(first["metrics"], indent=2))
print("\nREPEATABILITY DIFFERENCE")
print(json.dumps(result["repeat_delta"], indent=2))
print("\nNOISE DIFFERENCE")
print(json.dumps(result["noise_delta"], indent=2))
print("\nRESULT SAVED:", path)
