"""Refresh the reviewed CPD summary without changing archived molecular evidence."""

import argparse
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def attach_progress_summary(payload, *, root=ROOT):
    """Keep the review date separate from the archived atom/bond evidence date."""
    summary = json.loads((root / "docs/cpd_progress_summary.json").read_text())
    result = copy.deepcopy(payload)
    sources = result.setdefault("sources", {})
    for group in ("completed", "remaining", "history"):
        for item in summary[group]:
            evidence = []
            for relative in item.pop("sources"):
                raw = (root / relative).read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                key = "progress-review-" + digest[:16]
                sources[key] = {"file": relative, "sha256": digest}
                evidence.append(key)
            item["evidence"] = evidence
    summary["historicalPreviewIds"] = []
    for model in result.get("isomers", []):
        if "-anti-" not in model["id"]:
            continue
        source = sources.get(model["id"] + "-preview-definition")
        if not source or source["sha256"] != hashlib.sha256((root / source["file"]).read_bytes()).hexdigest():
            summary["historicalPreviewIds"].append(model["id"])
    # Omit superseded run notifications from the menu; archive records remain intact.
    historical = set(summary["historicalModelIds"])
    for model in result.get("models", []):
        if model["id"] in historical:
            model["checks"] = [c for c in model.get("checks", []) if not (
                c["label"] in {"Campaign paused by user", "Interstrand DNA validation"}
                or (c.get("state") == "pending" and c.get("value") == "complete")
            )]
    result["progress"] = summary
    # Repeated refreshes must not accumulate obsolete review hashes.
    used = set()
    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "evidence":
                    used.update([item] if isinstance(item, str) else item or [])
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    collect({k: v for k, v in result.items() if k != "sources"})
    for key in list(sources):
        if key.startswith("progress-review-") and key not in used:
            del sources[key]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=ROOT / "frontend/public/cpd-progress.json")
    args = parser.parse_args()
    payload = attach_progress_summary(json.loads(args.snapshot.read_text()))
    args.snapshot.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Updated reviewed progress in {args.snapshot}; molecular evidence retained")


if __name__ == "__main__":
    main()
