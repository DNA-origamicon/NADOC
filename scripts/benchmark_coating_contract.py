#!/usr/bin/env python3
"""Memory-only coating recipes and cold replay; run serially after registration.

This is qualification, not a live route or production capture-limit change.
Six fixed fixtures exercise 1/16/64 requested sites in both native modes. No
document session, geometry lock, physical simulation or output file is opened.
"""

import argparse
import json
from importlib import import_module
from pathlib import Path
import pickle
from statistics import median
from time import perf_counter
from uuid import NAMESPACE_URL, uuid5

from backend.api import part_streptavidin_commands as commands
from backend.api.part_evaluation_worker import EvaluationWorker
from backend.api.part_proof_commands import dependencies, execute_long
from backend.api.state import encode_design_snapshot
from backend.core.models import Design, SnapshotLogEntry
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_input_sources import EmbeddedResolver, command_sources, describe, embed, portable_sources
from backend.core.part_verification_capture import CaptureLimit, capture
from backend.core.part_streptavidin_contract import contract_defaults


PROSPECTIVE = {"max_nodes": 100_000, "max_bytes": 4_000_000, "seconds": 0.100}


def timed(callback):
    started = perf_counter()
    result = callback()
    return result, (perf_counter() - started) * 1_000


def source_inputs():
    """Declare both recipe sources; these are the only file reads in fixtures."""
    directory = Path(__file__).resolve().parents[1] / "backend/data/proteins"
    table, sources, sizes = {}, {}, {}
    for name, filename, format_name, media in (
        ("pdb_source", "1STP-assembly1.pdb", "pdb", "chemical/x-pdb"),
        ("coverage_source", "streptavidin_coverage.json", "json", "application/json"),
    ):
        raw = (directory / filename).read_bytes()
        source = describe(raw, format=format_name, media_type=media)
        table[source.sha256] = embed(source, raw)
        sources[name] = source.model_dump(mode="json")
        sizes[name] = {"raw_bytes": len(raw), "sha256": source.sha256,
                       "base64_characters": len(table[source.sha256].data_b64)}
    return table, sources, sizes


def append(design, kind, params, label):
    """Prepare real recovery pairs in memory, separately timing native work."""
    (pre, pre_size), pre_ms = timed(lambda: encode_design_snapshot(design))
    updated, build_ms = timed(lambda: execute_long(kind, design, params))
    (post, post_size), post_ms = timed(lambda: encode_design_snapshot(updated))
    entry = SnapshotLogEntry(id=str(uuid5(NAMESPACE_URL, f"coating-benchmark:{label}")),
        op_kind=kind, label=label, params=params,
        design_snapshot_gz_b64=pre, snapshot_size_bytes=pre_size,
        post_state_gz_b64=post, post_state_size_bytes=post_size)
    updated = updated.copy_with(feature_log=[*design.feature_log, entry])
    return updated, {"build_ms": build_ms, "recovery_encode_ms": pre_ms + post_ms,
        "new_recovery_encoded_bytes": len(pre) + len(post)}


def measure_capture(design, repeats, **limits):
    samples, errors, payloads, isolated = [], [], [], None
    for _ in range(repeats):
        candidate = None
        started = perf_counter()
        try:
            candidate = capture(design, **limits)
        except CaptureLimit as error:
            errors.append(str(error))
        samples.append((perf_counter() - started) * 1_000)
        if candidate is not None:
            isolated = candidate
            payloads.append(len(pickle.dumps(candidate, protocol=pickle.HIGHEST_PROTOCOL)))
    return isolated, {"median_ms": median(samples), "max_ms": max(samples),
        "samples_ms": samples, "refusals": errors,
        "pickle_bytes_max": max(payloads) if payloads else None,
        "fits_existing_2MB_worker": max(payloads) <= 2_000_000 if payloads else None}


def proof(design):
    return assess_part_history(design, execute=execute_long, dependencies=dependencies)


def cold_proof(isolated):
    if isolated is None:
        return {"status": "capture_limit"}
    # Explicit evaluator uses the registered long executor. Its existing
    # bounded pickle/result envelopes and child numerical-thread policy remain.
    operation = {"request": {"operation": "verify"},
                 "header": {"identity": str(uuid5(NAMESPACE_URL, "coating-cold-proof")),
                            "timestamp": "2026-10-15T00:00:00+00:00"}}
    worker = EvaluationWorker(isolated, operation)
    started = perf_counter()
    try:
        worker.start()
        result = worker.result() if worker.wait(30) else {"status": "worker_deadline", "issues": []}
        return {"status": result["status"], "issues": result.get("issues", []),
                "spawn_and_proof_ms": (perf_counter() - started) * 1_000}
    finally:
        worker.close()


def measure_stage(design, row, repeats):
    reloaded, reload_ms = timed(lambda: Design.model_validate_json(design.model_dump_json()))
    reload_equal = (design.model_dump(include=AUTHORING_FIELDS)
                    == reloaded.model_dump(include=AUTHORING_FIELDS))
    _discard, ordinary = measure_capture(reloaded, repeats)
    isolated, experimental = measure_capture(reloaded, repeats, **PROSPECTIVE)
    direct, proof_ms = timed(lambda: proof(reloaded))
    coating = reloaded.nanoparticles[0].coating
    return {**row, "requested_sites": coating.target_count if coating else 0,
        "actual_sites": len(coating.poses) if coating else 0,
        "protein_atoms": len(coating.protein.atoms) if coating else 0,
        "reload_authoring_equal": reload_equal, "reload_ms": reload_ms,
        "history_rows": len(reloaded.feature_log),
        "candidate_json_bytes": len(reloaded.model_dump_json().encode()),
        "cumulative_recovery_encoded_bytes": sum(len(entry.design_snapshot_gz_b64)
            + len(entry.post_state_gz_b64 or "") for entry in reloaded.feature_log),
        "default_capture": ordinary, "experimental_capture": experimental,
        "same_process_proof_ms": proof_ms,
        "same_process_proof": {"status": direct["status"], "issues": direct["issues"]},
        "cold_worker": cold_proof(isolated)}


def measure_case(mode, count, table, sources, repeats):
    name = f"{mode}:{count}"
    design = create_empty_part(name, "HONEYCOMB").copy_with(input_sources=dict(table))
    design, _gold = append(design, "nanoparticle-create", {"_proof_version": 1,
        "nanoparticle_version": 1, "nanoparticle_id": "gold", "diameter_nm": 20.0}, name + ":gold")
    base = {"_proof_version": 1, "coating_version": 1, "nanoparticle_id": "gold"}
    params = {**base, **contract_defaults(), "action": "set", **sources, "mode": mode,
        "footprint_nm2": 40.0, "spacer_nm": 0.3 if mode == "adsorption" else 4.0,
        "seed": 1, "coverage_reference": "gold_2007", "count_override": count}
    _admission, admission_ms = timed(lambda: commands.validate_inputs(
        "nanoparticle-patch", design, params, resolver=EmbeddedResolver(design.input_sources)))
    declared = {source.sha256 for source in command_sources("nanoparticle-patch", params)}
    expected = {source["sha256"] for source in sources.values()}
    stages = []
    for stage, request in (
        ("set", params), ("resize", {**params, "diameter_nm": 22.0}),
        ("move", {**base, "action": "move", "gizmo_move": {"pivot": [0.0, 0.0, 0.0],
            "translation": [1.0, -2.0, 3.0], "rotation": [0.0, 0.0, 0.0, 1.0]}}),
        ("remove", {**base, "action": "remove"}),
    ):
        design, row = append(design, "nanoparticle-patch", request, name + ":" + stage)
        row["stage"] = stage
        stages.append(measure_stage(design, row, repeats))
    portable = portable_sources(design)
    return {"mode": mode, "requested_count": count, "cheap_admission_ms": admission_ms,
        "two_source_declaration_complete": declared == expected,
        "retained_portable_source_closure_complete": set(portable) == expected,
        "stages": stages}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 30:
        parser.error("Use 1..30 capture repeats")
    table, sources, source_sizes = source_inputs()
    for module in ("scipy.linalg", "scipy.optimize", "scipy.spatial.transform",
                   "scipy.spatial.distance", "scipy.interpolate"):
        import_module(module)
    from threadpoolctl import threadpool_limits

    # The benchmark process adopts exactly the existing worker's one-thread
    # policy for its own native oracle. No application setting is changed.
    with threadpool_limits(limits=1):
        cases = [measure_case(mode, count, table, sources, args.repeats)
                 for mode in ("adsorption", "biotin_tether") for count in (1, 16, 64)]
    print(json.dumps({"scope": "Pure registered coating construction, lifecycle and cold proof; no live UI/lock qualification",
        "production_limits_unchanged": True,
        "experimental_profile_not_production": PROSPECTIVE,
        "existing_worker_input_bytes": 2_000_000, "sources": source_sizes, "cases": cases}, indent=2))
    return int(any(not case["two_source_declaration_complete"]
        or not case["retained_portable_source_closure_complete"]
        or any(not row["reload_authoring_equal"]
            or row["same_process_proof"]["status"] != "reproduced_import"
            or row["cold_worker"]["status"] != "reproduced_import" for row in case["stages"])
        for case in cases))


if __name__ == "__main__":
    raise SystemExit(main())
