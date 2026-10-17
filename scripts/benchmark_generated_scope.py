"""Paired in-memory scope overhead and full-authoring equivalence benchmark.

Baseline is the reviewed pre-schema scope implementation. No files, molecular
solvers, display geometry, native builds or document sessions are created.
"""
import json
import statistics
import subprocess
import time
import types

from backend.api import generated_native_scope as current
from backend.api.part_proof_commands import execute
from backend.core.lattice import make_bundle_design
from backend.core.models import Design, SnapshotLogEntry
from backend.core.part_history_proof import AUTHORING_FIELDS


BASELINE = "afe9cb5d"
GROUP = "a53c503e-a4e8-49a0-a5e9-62e7ad4603bc"


def main():
    old = types.ModuleType("baseline_generated_scope")
    source = subprocess.check_output(
        ["git", "show", f"{BASELINE}:backend/api/generated_native_scope.py"], text=True
    )
    exec(compile(source, "baseline_generated_scope", "exec"), old.__dict__)
    cases = []
    for count, history_rows in ((6, 0), (24, 100)):
        raw = make_bundle_design([(r, c) for r in range(count // 2) for c in range(2)], 84)
        mapping = {identifier: old.namespaced(identifier, GROUP)
                   for identifier in old.identifiers(raw.model_dump())}
        design = Design.model_validate(old.map_values(raw.model_dump(), mapping))
        design.feature_log = [SnapshotLogEntry(
            op_kind="nick", label="Recovery is excluded from scope work",
            post_state_gz_b64="not read" * 1000,
        ) for _ in range(history_rows)]
        parameters = {"_proof_version": 1, "helix_id": raw.helices[0].id,
                      "length_bp": 90, "axis_start": {"x": 0, "y": 0, "z": 0},
                      "axis_end": {"x": 0, "y": 0, "z": 30},
                      "_generated_scope": {"group_id": GROUP, "input_ids": []}}
        samples = {"baseline": [], "typed": []}
        for i in range(23):
            outputs = {}
            for label in (("baseline", "typed") if i % 2 else ("typed", "baseline")):
                arguments = {**parameters, "_generated_scope": {
                    **parameters["_generated_scope"], **({"version": 2} if label == "typed" else {})}}
                start = time.perf_counter()
                output = (old if label == "baseline" else current).execute(
                    "helix-update", design, arguments, execute
                )
                samples[label].append((time.perf_counter() - start) * 1000)
                outputs[label] = output
            assert all(getattr(outputs["baseline"], f) == getattr(outputs["typed"], f)
                       for f in AUTHORING_FIELDS)
        medians = {name: statistics.median(values) for name, values in samples.items()}
        increase = medians["typed"] - medians["baseline"]
        cases.append({"helices": count, "history_rows": history_rows,
                      "full_authoring_equal": True, "median_ms": medians,
                      "added_ms": increase,
                      "gate_passed": not (increase > 0.05 and increase > 0.05 * medians["baseline"]),
                      "samples_ms": samples})
    print(json.dumps({"benchmark": "typed-generated-scope", "baseline": BASELINE,
                      "all_gates_passed": all(case["gate_passed"] for case in cases),
                      "scope": "paired warm command medians; excludes capture/HTTP/rendering; first-use imports are not a cold-start comparison",
                      "cases": cases}, indent=2))


if __name__ == "__main__":
    main()
