import argparse
import json
import yaml
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("baseline")
args = parser.parse_args()

baseline = json.loads(
    Path(args.baseline).read_text(encoding="utf-8-sig")
)["first"]["metrics"]

thresholds = {
    "min_recall_at_5": max(
        0, baseline["recall@5"] - 0.02
    ),
    "min_citation_validity": 0.95,
    "min_abstention_correctness":
        baseline["abstention_correctness"],
    "min_faithfulness": 0.80,
    "max_latency_p95_ms":
        baseline["latency_p95_ms"] * 1.20
}

path = Path("eval/gate_real.yaml")

path.write_text(
    yaml.safe_dump(thresholds, sort_keys=False),
    encoding="utf-8"
)

print("FIXED REGRESSION THRESHOLDS")
print(path.read_text())
