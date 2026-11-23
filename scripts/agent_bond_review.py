"""Read-only bond inspection and exact-design review receipts for publication.

A receipt acknowledges an investigated exception. It is neither a physical
validation certificate nor a substitute for replaying the construction process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.core.design_bond_review import review_design_bonds
from backend.core.models import Design

REPORT_SCHEMA = "nadoc-design-bond-report-v1"
REVIEW_SCHEMA = "nadoc-design-bond-review-v1"
_SHA = r"^[0-9a-f]{64}$"


class BondReviewRequired(ValueError):
    """Publication stopped; the attached report remains available for inspection."""

    def __init__(self, message, report):
        super().__init__(f"DESIGN_BOND_REVIEW_REQUIRED: {message}")
        self.report = report


class _Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["visual", "bond-report"]
    path: str = Field(min_length=1, max_length=4096)
    sha256: str = Field(pattern=_SHA)


class _Receipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_name: Literal["nadoc-design-bond-review-v1"] = Field(alias="schema")
    design_sha256: str = Field(pattern=_SHA)
    report_sha256: str = Field(pattern=_SHA)
    reviewer: str = Field(min_length=1, max_length=256)
    reviewed_at: str = Field(min_length=1, max_length=64)
    decision: Literal["reviewed-for-publication"]
    rationale: str = Field(min_length=1, max_length=12000)
    limitations: str = Field(default="", max_length=12000)
    evidence: list[_Evidence] = Field(min_length=2, max_length=16)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def bond_report(design: Design) -> dict:
    """Bind the complete deterministic report to all normalized document fields."""
    report = review_design_bonds(design, include_geometry=True)
    return {"schema": REPORT_SCHEMA,
            "design_sha256": _digest(design.model_dump(mode="json")),
            "report_sha256": _digest(report), "report": report}


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"Review artifact exceeds {limit} bytes: {path}")
    return raw


def _check_receipt(receipt, envelope):
    base = Path.cwd()
    if isinstance(receipt, (str, Path)):
        path = Path(receipt)
        base = path.resolve().parent
        value = json.loads(_read_bounded(path, 65536))
    else:
        value = receipt
        if len(_canonical(value)) > 65536:
            raise ValueError("Review receipt exceeds 65536 bytes")
    review = _Receipt.model_validate(value)
    if not review.reviewer.strip() or not review.rationale.strip():
        raise ValueError("A reviewer and an investigation rationale are required")
    when = datetime.fromisoformat(review.reviewed_at.replace("Z", "+00:00"))
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("Review date must include a timezone")
    for key in ("design_sha256", "report_sha256"):
        if getattr(review, key) != envelope[key]:
            raise ValueError(f"Review {key} does not match the current design/report")
    if not envelope["report"]["geometry"]["complete"] and not review.limitations.strip():
        raise ValueError("Incomplete geometry requires an explicit limitations statement")
    kinds = set()
    for evidence in review.evidence:
        path = Path(evidence.path)
        path = path if path.is_absolute() else base / path
        raw = _read_bounded(path, 2 * 1024 * 1024 if evidence.kind == "bond-report"
                            else 64 * 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != evidence.sha256:
            raise ValueError(f"Review evidence changed: {evidence.path}")
        if evidence.kind == "bond-report" and json.loads(raw) != envelope:
            raise ValueError("Bond-report evidence does not match the complete current report")
        kinds.add(evidence.kind)
    if kinds != {"visual", "bond-report"}:
        raise ValueError("Both visual inspection and current bond-report evidence are required")
    return {"review_status": "reviewed", "reviewer": review.reviewer,
            "reviewed_at": review.reviewed_at, "rationale": review.rationale,
            "limitations": review.limitations, "receipt_sha256": _digest(value)}


def require_bond_review(design: Design, receipt=None) -> dict:
    """Refuse an unreviewed threshold breach; never auto-create a receipt."""
    envelope = bond_report(design)
    if receipt is not None:
        try:
            status = _check_receipt(receipt, envelope)
        except (OSError, ValueError, TypeError, ValidationError) as exc:
            raise BondReviewRequired(f"Invalid review receipt: {exc}", envelope) from exc
    elif envelope["report"]["review_required"]:
        reasons = ", ".join(envelope["report"]["reason_codes"])
        raise BondReviewRequired(
            f"{reasons}. Inspect with python -m scripts.agent_bond_review PATH.nadoc; "
            "record the investigation in an exact-design review receipt before publication.",
            envelope,
        )
    else:
        status = {"review_status": "not_required"}
    return {**envelope, **status}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--output", type=Path, help="Create a JSON report; never changes the design")
    args = parser.parse_args(argv)
    envelope = bond_report(Design.model_validate_json(args.file.read_text()))
    raw = json.dumps(envelope, indent=2, allow_nan=False) + "\n"
    if args.output:
        # Reports are evidence, never an alternative structure publication path.
        with args.output.open("x") as stream:
            stream.write(raw)
    else:
        print(raw, end="")
    return 0  # A flagged design must remain inspectable without accepting it.


if __name__ == "__main__":
    raise SystemExit(main())
