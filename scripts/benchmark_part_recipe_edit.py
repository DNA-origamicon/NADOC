"""Paired late-edit benchmark: independent full replay vs one verified prefix.

In-memory synthetic part recipes only. Measures source verification plus candidate
rebuild, excluding capture/network/rendering/publication. Uses the same native
algorithms on both sides and compares all authoring fields. No timing gate changes.
"""

import json
import statistics
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.api.part_proof_commands import execute, dependencies
from backend.api.part_recipe_edit import regenerate
from backend.api.part_recipe_prefix import ReplayPrefix
from backend.core.models import SnapshotLogEntry, ClusterOpLogEntry
from backend.core.part_history_contract import create_empty_part, assess_part_history
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_verification_capture import capture


def fixture(helices, poses):
    root = create_empty_part("Bundle", "SQUARE")
    params = {
        "cells": [[r, 0] for r in range(helices)],
        "length_bp": 84,
        "lattice_type": "SQUARE",
        "history_seed": "a5fd915a-0b66-49ed-a986-a60a15b340a7",
        "_proof_version": 1,
    }
    design = execute("bundle-create", root, params)
    cid = design.cluster_transforms[0].id
    log = [SnapshotLogEntry(op_kind="bundle-create", label="Bundle", params=params)]
    for i in range(poses):
        values = {
            "cluster_id": cid,
            "translation": [float(i), 0, 0],
            "rotation": [0, 0, 0, 1],
            "pivot": [0, 0, 0],
        }
        design = execute("cluster_op", design, {**values, "_proof_version": 1})
        log.append(ClusterOpLogEntry(**values, proof_version=1))
    return design.copy_with(feature_log=log)


def run(source, captured, *, prefix_enabled):
    start = time.perf_counter()
    prefix = (
        ReplayPrefix(source, len(source.feature_log) - 1) if prefix_enabled else None
    )
    executor = (
        (lambda kind, d, p: prefix.execute(execute, kind, d, p)) if prefix else execute
    )
    proof = assess_part_history(captured, execute=executor, dependencies=dependencies)
    assert proof["status"] == "verified", proof
    log = list(source.feature_log)
    log[-1] = log[-1].model_copy(update={"translation": [0, 10, 0]})
    candidate = regenerate(source, log, lambda: None, prefix=prefix)
    elapsed = (time.perf_counter() - start) * 1000
    return elapsed, candidate


def main():
    cases = []
    for helices, poses in [(1, 25), (24, 100)]:
        source = fixture(helices, poses)
        captured = capture(source)
        samples = {"baseline": [], "candidate": []}
        for i in range(17):
            outputs = {}
            for label in (
                ("baseline", "candidate") if i % 2 == 0 else ("candidate", "baseline")
            ):
                elapsed, output = run(
                    source, captured, prefix_enabled=label == "candidate"
                )
                samples[label].append(elapsed)
                outputs[label] = output
            assert all(
                getattr(outputs["baseline"], f) == getattr(outputs["candidate"], f)
                for f in AUTHORING_FIELDS
            )
        medians = {label: statistics.median(times) for label, times in samples.items()}
        increase = medians["candidate"] - medians["baseline"]
        cases.append(
            {
                "helices": helices,
                "poses": poses,
                "samples_ms": samples,
                "median_ms": medians,
                "gate_passed": not (
                    increase > 0.05 and increase > 0.05 * medians["baseline"]
                ),
            }
        )
    print(
        json.dumps(
            {
                "benchmark": "verified-prefix-vs-full-replay",
                "all_gates_passed": all(c["gate_passed"] for c in cases),
                "cases": cases,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
