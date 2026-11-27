import json
import hashlib
import os
import shutil
import time
from pathlib import Path

from .verify import Verifier
from .extract import extract
from .clean import clean


def verified_documents(settings, documents):
    root = Path(settings.corpus_dir)
    lake = Path(os.environ.get("DATA_LAKE", "/tmp/rahbar-lake"))
    quarantine = lake / "quarantine"
    archive = lake / "archive"
    reports = lake / "reports"

    for folder in (quarantine, archive, reports):
        folder.mkdir(parents=True, exist_ok=True)

    index = root / "_index.json"
    entries = {}

    if index.exists():
        entries = {
            e["file"]: e
            for e in json.loads(index.read_text(encoding="utf-8-sig"))
        }

    from .recency import detect_versions
    entries = detect_versions(entries)
    verifier = Verifier()
    accepted = []
    results = []

    for path, version, superseded in documents:
        try:
            entry = entries.get(path.name, {})
            superseded = entry.get('superseded', superseded)
            raw = path.read_bytes()
            doc = extract(str(path), version, superseded)

            if path.suffix.lower() == ".pdf":
                import pdfplumber
                with pdfplumber.open(str(path)) as pdf:
                    page_count = len(pdf.pages)
            else:
                page_count = 1

            metadata = {
                "source": entry.get("url"),
                "title": entry.get("name"),
                "doc_version": entry.get("doc_version"),
                "page_count": entry.get("page_count", page_count)
            }

            result = verifier.check(path, doc, metadata)
            result['recency']['latest_version'] = entry.get('latest_version', version)

            if entry.get("bytes") and entry["bytes"] != len(raw):
                result["errors"].append("file_size_mismatch")

            if entry.get("sha256"):
                if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                    result["errors"].append("checksum_mismatch")

            result["passed"] = not result["errors"]

            if result["passed"]:
                accepted.append((path, clean(doc)))

                if superseded:
                    shutil.copy2(path, archive / path.name)
            else:
                shutil.copy2(path, quarantine / path.name)

        except Exception as exc:
            result = {
                "source": path.name,
                "passed": False,
                "errors": ["extraction_failed", str(exc)]
            }

            if path.exists():
                shutil.copy2(path, quarantine / path.name)

        results.append(result)
        print(json.dumps({
            "event": "document_verification",
            **result
        }), flush=True)

    report = {
        "documents": len(results),
        "accepted": len(accepted),
        "quarantined": len(results) - len(accepted),
        "results": results
    }

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    output = reports / f"verification-{stamp}.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps({
        "event": "verification_summary",
        "documents": len(results),
        "accepted": len(accepted),
        "quarantined": len(results)-len(accepted),
        "report": str(output)
    }), flush=True)

    return accepted

