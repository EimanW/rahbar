"""Identify superseded versions of the same logical document."""

def detect_versions(entries):
    groups = {}

    for entry in entries.values():
        logical_id = entry.get("logical_id")

        if not logical_id:
            continue

        groups.setdefault(logical_id, []).append(entry)

    for logical_id, versions in groups.items():
        latest = max(
            versions,
            key=lambda e: str(e.get("doc_version") or "")
        )

        for entry in versions:
            entry["superseded"] = entry is not latest
            entry["latest_version"] = latest["doc_version"]

    return entries
