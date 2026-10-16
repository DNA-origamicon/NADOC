#!/usr/bin/env python3
"""Warm bounded thiol movement admission/build/capture; no simulations."""

import json
from statistics import median
from time import perf_counter
from uuid import UUID

from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_thiol_patch_commands import native_route_eligible
from backend.core.models import SnapshotLogEntry
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_verification_capture import CaptureLimit, capture


def timed(callback):
    start = perf_counter()
    result = callback()
    return result, (perf_counter() - start) * 1_000


def main():
    cases = []
    for count, length in ((1, 8), (128, 8), (100, 500)):
        design = create_empty_part("Thiol motion benchmark", "HONEYCOMB")
        gold = {"_proof_version": 1, "nanoparticle_version": 1,
                "nanoparticle_id": "gold", "diameter_nm": 20.0}
        graft = {"_proof_version": 1, "thiol_version": 1, "history_seed": str(UUID(int=1)),
                 "nanoparticle_id": "gold", "replace_conjugation_ids": [], "conjugation_id": "graft",
                 "scheme": "direct_thiol", "sequence": ("ACGT" * 125)[:length], "count": count,
                 "attach_end": "5p", "spacer_nm": None, "seed": 1}
        for kind, params in (("nanoparticle-create", gold), ("nanoparticle-conjugate", graft)):
            updated = execute(kind, design, params)
            design = updated.copy_with(feature_log=[*design.feature_log, SnapshotLogEntry(
                op_kind=kind, label=kind, params=params, design_snapshot_gz_b64="poisoned",
                post_state_gz_b64="poisoned")])
        patch = {"_proof_version": 1, "nanoparticle_version": 1, "thiol_version": 1,
                 "nanoparticle_id": "gold", "conjugation_ids": ["graft"], "diameter_nm": 22.0,
                 "gizmo_move": {"translation": [2., -1., 3.], "rotation": [0., 0., 0., 1.],
                                "pivot": [0., 0., 0.]}}
        timings = {key: [] for key in ("eligibility", "build", "capture", "proof")}
        statuses = []
        for _ in range(9):
            admitted, elapsed = timed(lambda: native_route_eligible(design, "gold"))
            assert admitted
            timings["eligibility"].append(elapsed)
            candidate, elapsed = timed(lambda: execute("nanoparticle-patch", design, patch))
            timings["build"].append(elapsed)
            candidate = candidate.copy_with(feature_log=[*design.feature_log, SnapshotLogEntry(
                op_kind="nanoparticle-patch", label="Move and resize", params=patch,
                design_snapshot_gz_b64="poisoned", post_state_gz_b64="poisoned")])
            start = perf_counter()
            try:
                isolated = capture(candidate)
            except CaptureLimit:
                timings["capture"].append((perf_counter() - start) * 1_000)
                statuses.append("capture_limit")
                continue
            timings["capture"].append((perf_counter() - start) * 1_000)
            result, elapsed = timed(lambda: assess_part_history(isolated, execute=execute,
                                                               dependencies=dependencies))
            timings["proof"].append(elapsed)
            statuses.append(result["status"])
        cases.append({"handles": count, "bases": count * length, "statuses": statuses,
                      "timings_ms": {key: {"median": median(values), "max": max(values)}
                                     for key, values in timings.items() if values}})
    print(json.dumps({"scope": "Warm explicit admission/build/capture/full recipe replay; excludes HTTP/rendering/chemical validity",
                      "repeats": 9, "capture_limits_unchanged": True, "cases": cases}, indent=2))
    # A cooperative capture refusal is a measured unavailable proof, never a
    # successful verification. Keep it visible in evidence without confusing it
    # with a builder mismatch or an unsupported command.
    return int(any(status not in {"verified", "capture_limit"}
                   for case in cases for status in case["statuses"]))


if __name__ == "__main__":
    raise SystemExit(main())
