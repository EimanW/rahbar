#!/usr/bin/env python3
"""Score a running RAHBAR against a golden set, and gate CI on the result (section 5).

    python eval/run_eval.py --api http://<ingress>                 # your corpus
    python eval/run_eval.py --api ... --golden eval/fixtures/golden.fixture.yaml
    python eval/run_eval.py --api ... --update-baseline            # after a deliberate improvement

Exit code 0 when every gate passes, 1 when any fails. CI relies on that exit code.

Given: talking to the API, reading the golden set, writing results.json, the exit
code. Ours: recall_at_k, citation_validity, summarise and gate below.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent

# The gate from section 5.4. Change these only with a reason written in docs/PIPELINE.md.
# We added a fourth gate, zero stale citations (PIPELINE.md, "A fourth gate").
MAX_RECALL5_DROP = 0.05        # recall@5 may fall at most 5 points below the baseline
MIN_CITATION_VALIDITY = 0.95   # at least 95% of citations must match retrieved passages
REQUIRED_ABSTENTION = 1.0      # every must-abstain question must be declined


def load_golden(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    questions = data.get("questions") or []
    if not questions:
        sys.exit(f"no questions in {path}")
    return questions


def ask(client: httpx.Client, api: str, question: str) -> dict:
    """POST one question and return the AskResponse as a dict (see api/app/schemas.py)."""
    response = client.post(f"{api.rstrip('/')}/api/ask", json={"question": question})
    response.raise_for_status()
    return response.json()


def _norm(text: str) -> str:
    return " ".join(str(text).split()).lower()


def matches(golden: dict, got: dict) -> bool:
    """A retrieved passage matches a golden one when the source is the same file and the
    golden section is a prefix of the retrieved section, compared case- and
    space-insensitively. So golden "5.4" matches a chunk under "5.4 Academic Warning",
    and "2. Academic warning" matches itself, and "acceptable uses" matches a chunk under
    "4. Acceptable Uses" (a leading number on the heading is ignored). A golden entry may instead give a chunk_id,
    which must match exactly. The rule is stated in docs/PIPELINE.md."""
    if golden.get("chunk_id"):
        return golden["chunk_id"] == got.get("chunk_id")
    if _norm(golden.get("source", "")) != _norm(got.get("source", "")):
        return False
    want, have = _norm(golden.get("section", "")), _norm(got.get("section", ""))
    if not want:
        return False
    # a heading may carry a number the golden entry leaves out: "4. acceptable uses"
    unnumbered = re.sub(r"^(?:[ivxlc]+|\d+(?:\.\d+)*)[.)]?\s+", "", have)
    for candidate in (have, unnumbered):
        if candidate == want or candidate.startswith(want + " ") or candidate.startswith(want + "."):
            return True
        if candidate.startswith(want) and not want[-1].isdigit():
            return True
    return False


def recall_at_k(relevant: list[dict], retrieved: list[dict], k: int) -> float | None:
    """Fraction of the relevant (source, section) pairs found in the top k retrieved.
    Return None when the question has no relevant passages (must-abstain questions)."""
    if not relevant:
        return None
    top = retrieved[:k]
    found = sum(1 for g in relevant if any(matches(g, r) for r in top))
    return found / len(relevant)


def citation_validity(response: dict) -> float | None:
    """Fraction of the response's citations that match a passage in response['retrieved'].
    Return None when there are no citations."""
    citations = response.get("citations") or []
    if not citations:
        return None
    retrieved = {(_norm(r["source"]), _norm(r["section"])) for r in response.get("retrieved", [])}
    valid = sum(1 for c in citations if (_norm(c["source"]), _norm(c["section"])) in retrieved)
    return valid / len(citations)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def summarise(rows: list[dict]) -> dict:
    """Overall recall@3, recall@5, citation validity and abstention correctness, plus
    recall@5 broken down by question type. This dict becomes results.json."""
    r3, r5, by_type = [], [], {}
    cited = valid = 0
    abstain_total = abstain_ok = 0
    answerable = false_abstain = 0
    expect_total = expect_hit = 0
    stale_total = stale = 0
    per_question = []
    for row in rows:
        resp = row["response"]
        retrieved = resp.get("retrieved", [])
        rec3 = recall_at_k(row["relevant"], retrieved, 3)
        rec5 = recall_at_k(row["relevant"], retrieved, 5)
        if rec5 is not None:
            r3.append(rec3 or 0.0)
            r5.append(rec5)
            by_type.setdefault(row["type"], []).append(rec5)
        # stale citations (failure mode E): citing a superseded passage when the question
        # did not ask for an older version. recall@k cannot see this: the current chunk can
        # still be in the top 5 while the superseded one ranks first and gets cited.
        old = {(_norm(r["source"]), _norm(r["section"])) for r in retrieved if r.get("superseded")}
        cites = resp.get("citations") or []
        if not row.get("allow_superseded"):
            stale_total += len(cites)
            stale += sum(1 for c in cites if (_norm(c["source"]), _norm(c["section"])) in old)
        cv = citation_validity(resp)
        n = len(resp.get("citations") or [])
        if cv is not None:
            cited += n
            valid += round(cv * n)
        if row["must_abstain"]:
            abstain_total += 1
            abstain_ok += int(resp.get("answered_from_context") is False)
        elif row["relevant"]:
            answerable += 1
            false_abstain += int(resp.get("answered_from_context") is False)
        if row.get("expect") and not row["must_abstain"]:
            expect_total += 1
            expect_hit += int(_norm(row["expect"]) in _norm(resp.get("answer", "")))
        per_question.append({
            "id": row["id"], "type": row["type"], "recall@3": rec3, "recall@5": rec5,
            "citation_validity": cv, "answered_from_context": resp.get("answered_from_context"),
            "must_abstain": row["must_abstain"], "cached": resp.get("cached", False),
            "top_scores": [r.get("score") for r in retrieved[:5]], "seconds": row.get("seconds"),
        })
    return {
        "recall@3": _mean(r3),
        "recall@5": _mean(r5),
        "recall@5_by_type": {t: _mean(v) for t, v in sorted(by_type.items())},
        "citation_validity": round(valid / cited, 4) if cited else None,
        "citations_checked": cited,
        "abstention_correctness": round(abstain_ok / abstain_total, 4) if abstain_total else None,
        "must_abstain_questions": abstain_total,
        "false_abstention_rate": round(false_abstain / answerable, 4) if answerable else None,
        "expect_string_hit_rate": round(expect_hit / expect_total, 4) if expect_total else None,
        "stale_citation_rate": round(stale / stale_total, 4) if stale_total else None,
        "per_question": per_question,
    }


def gate(results: dict, baseline: dict | None) -> list[str]:
    """Return one message per failed gate (section 5.4); an empty list means pass."""
    failures = []
    r5 = results.get("recall@5")
    if baseline and baseline.get("recall@5") is not None and r5 is not None:
        floor = baseline["recall@5"] - MAX_RECALL5_DROP
        if r5 < floor - 1e-9:
            failures.append(f"recall@5 {r5:.3f} is more than {MAX_RECALL5_DROP:.0%} below the "
                            f"baseline {baseline['recall@5']:.3f}")
    abst = results.get("abstention_correctness")
    if abst is not None and abst < REQUIRED_ABSTENTION:
        wrong = [q["id"] for q in results.get("per_question", [])
                 if q["must_abstain"] and q["answered_from_context"] is not False]
        failures.append(f"must-abstain questions answered from context: {', '.join(wrong)}")
    stale = results.get("stale_citation_rate")
    if stale:
        failures.append(f"stale citations: {stale:.1%} of citations name a superseded document "
                        f"the question did not ask for (failure mode E)")
    cv = results.get("citation_validity")
    if cv is not None and cv < MIN_CITATION_VALIDITY:
        failures.append(f"citation validity {cv:.1%} is below {MIN_CITATION_VALIDITY:.0%}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate RAHBAR against a golden set.")
    parser.add_argument("--api", required=True, help="base URL, e.g. http://192.168.49.2")
    parser.add_argument("--host", help="Host header, when your Ingress rule names a host")
    parser.add_argument("--golden", type=Path, default=HERE / "golden.yaml")
    parser.add_argument("--baseline", type=Path, default=HERE / "baseline.json")
    parser.add_argument("--out", type=Path, default=HERE / "results.json")
    parser.add_argument("--update-baseline", action="store_true",
                        help="write these results as the new baseline")
    args = parser.parse_args()

    questions = load_golden(args.golden)
    rows = []
    headers = {"Host": args.host} if args.host else {}
    with httpx.Client(timeout=120.0, headers=headers) as client:
        for q in questions:
            started = time.perf_counter()
            response = ask(client, args.api, q["question"])
            rows.append({
                "id": q["id"], "type": q.get("type", "ordinary"),
                "must_abstain": bool(q.get("must_abstain", False)),
                "relevant": q.get("relevant") or [],
                "expect": q.get("expect"),
                "allow_superseded": bool(q.get("allow_superseded", False)),
                "response": response,
                "seconds": round(time.perf_counter() - started, 2),
            })
            print(f"  {q['id']:<5} {rows[-1]['seconds']:>6.2f}s  {q['question'][:60]}")

    try:
        results = summarise(rows)
        baseline = json.loads(args.baseline.read_text()) if args.baseline.exists() else None
        failures = gate(results, baseline)
    except NotImplementedError as exc:
        print(f"\nnot implemented yet: {exc}")
        return 2

    results["golden"] = str(args.golden)
    results["questions"] = len(rows)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nresults written to {args.out}")
    if args.update_baseline:
        args.baseline.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"baseline updated: {args.baseline}")

    if failures:
        print("\nGATE FAILED")
        for message in failures:
            print(f"  - {message}")
        return 1
    print("\ngate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
