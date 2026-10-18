#!/usr/bin/env python3
"""Warm in-memory graft execution/capture at admitted sizes; no simulations."""

import json
from statistics import median
from time import perf_counter
from uuid import UUID

from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import SnapshotLogEntry
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_verification_capture import CaptureLimit, capture


def timed(callback):
    start = perf_counter()
    value = callback()
    return value, (perf_counter() - start) * 1000


def main():
    rows = []
    for count, length in ((1, 8), (128, 8), (100, 500)):
        root = create_empty_part("Graft benchmark", "HONEYCOMB")
        gold = {"_proof_version": 1, "nanoparticle_version": 1,
                "nanoparticle_id": "gold", "diameter_nm": 20.0}
        design = execute("nanoparticle-create", root, gold)
        design.feature_log.append(SnapshotLogEntry(op_kind="nanoparticle-create", label="Gold", params=gold))
        inputs = {"_proof_version": 1, "thiol_version": 1, "history_seed": str(UUID(int=1)),
                  "nanoparticle_id": "gold", "replace_conjugation_ids": [], "conjugation_id": "graft",
                  "scheme": "direct_thiol", "sequence": ("ACGT" * 125)[:length], "count": count,
                  "attach_end": "5p", "spacer_nm": None, "seed": 1}
        builds, captures, proofs, statuses = [], [], [], []
        for _ in range(9):
            result, elapsed = timed(lambda: execute("nanoparticle-conjugate", design, inputs))
            builds.append(elapsed)
            result = result.copy_with(feature_log=[*design.feature_log, SnapshotLogEntry(
                op_kind="nanoparticle-conjugate", label="Graft", params=inputs,
                design_snapshot_gz_b64="poisoned", post_state_gz_b64="poisoned")])
            start = perf_counter()
            try:
                isolated = capture(result)
            except CaptureLimit:
                captures.append((perf_counter() - start) * 1000)
                statuses.append("capture_limit")
                continue
            captures.append((perf_counter() - start) * 1000)
            proof, elapsed = timed(lambda: assess_part_history(isolated, execute=execute, dependencies=dependencies))
            proofs.append(elapsed)
            statuses.append(proof["status"])
        rows.append({"handles": count, "bases": count * length,
            "build_median_ms": median(builds), "build_max_ms": max(builds),
            "capture_median_ms": median(captures), "capture_max_ms": max(captures),
            "proof_median_ms": median(proofs) if proofs else None, "statuses": statuses})
    print(json.dumps({"scope": "warm explicit native graft/capture/replay; excludes HTTP, rendering and scientific validity",
                      "repeats": 9, "capture_limits_unchanged": True, "cases": rows}, indent=2))
    return int(any(status not in {"verified", "capture_limit"} for row in rows for status in row["statuses"]))


if __name__ == "__main__":
    raise SystemExit(main())
