import argparse
import json
import yaml
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("result")
parser.add_argument("--config", default="eval/gate.yaml")
args = parser.parse_args()

result = json.loads(
    Path(args.result).read_text(encoding="utf-8-sig")
)
config = yaml.safe_load(
    Path(args.config).read_text(encoding="utf-8-sig")
)

metrics = result["first"]["metrics"]

checks = [
    ("Recall@5", metrics["recall@5"],
     config["min_recall_at_5"], ">="),
    ("Citation validity", metrics["citation_validity"],
     config["min_citation_validity"], ">="),
    ("Abstention correctness", metrics["abstention_correctness"],
     config["min_abstention_correctness"], ">="),
    ("Latency p95", metrics["latency_p95_ms"],
     config["max_latency_p95_ms"], "<=")
]

passed = True
details = []

for name, actual, threshold, op in checks:
    ok = actual is not None and (
        actual >= threshold if op == ">=" else actual <= threshold
    )
    passed = passed and ok
    print(f"{name}: {actual} {op} {threshold}: {'PASS' if ok else 'FAIL'}")
    details.append({
        "metric": name,
        "actual": actual,
        "threshold": threshold,
        "passed": ok
    })

print("REGRESSION GATE:", "PASS" if passed else "FAIL")

out = Path(args.result).with_suffix(".gate.json")
out.write_text(json.dumps({
    "passed": passed,
    "checks": details
}, indent=2), encoding="utf-8")

raise SystemExit(0 if passed else 1)
