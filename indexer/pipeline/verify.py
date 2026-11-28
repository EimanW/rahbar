"""Document quality checks before chunking."""

import hashlib
import math
from collections import Counter

from .hashembed import hash_embed


class Verifier:
    def __init__(self):
        self.hashes = {}
        self.vectors = {}

    def check(self, path, doc, metadata):
        text = "\n".join(p.text for p in doc.pages)
        digest = hashlib.sha256(
            " ".join(text.lower().split()).encode()
        ).hexdigest()

        errors = []

        quality = (
            len(text.strip()) >= 40
            and sum(c.isalpha() for c in text) / max(len(text), 1) >= 0.35
            and text.count("\ufffd") / max(len(text), 1) < 0.02
        )

        if not quality:
            errors.append("empty_or_garbled_extraction")

        required = ["source", "title", "doc_version", "page_count"]

        missing = [
            key for key in required
            if not metadata.get(key)
            or metadata.get(key) == "unknown"
        ]

        if missing:
            errors.append("missing_metadata:" + ",".join(missing))

        if metadata.get("page_count"):
            if int(metadata["page_count"]) != len(doc.pages):
                errors.append("page_count_mismatch")

        if path.suffix.lower() == ".pdf":
            if b"%%EOF" not in path.read_bytes()[-2048:]:
                errors.append("truncated_pdf")

        exact_duplicate = self.hashes.get(digest)
        near_duplicate = None
        similarity = 0.0

        vector = hash_embed(text, 768)

        if exact_duplicate:
            errors.append("exact_duplicate")
        else:
            for source, previous in self.vectors.items():
                score = sum(a*b for a,b in zip(vector, previous))
                if score > similarity:
                    similarity = score
                    near_duplicate = source

            if similarity >= 0.95:
                errors.append("near_duplicate")

        if not errors:
            self.hashes[digest] = path.name
            self.vectors[path.name] = vector

        return {
            "source": path.name,
            "quality": quality,
            "completeness": not missing and not any(
                e in errors for e in
                ["page_count_mismatch", "truncated_pdf"]
            ),
            "recency": {
                "version": doc.doc_version,
                "superseded": doc.superseded
            },
            "uniqueness": {
                "hash": digest,
                "exact_duplicate": exact_duplicate,
                "nearest_document": near_duplicate,
                "similarity": similarity
            },
            "passed": not errors,
            "errors": errors
        }
