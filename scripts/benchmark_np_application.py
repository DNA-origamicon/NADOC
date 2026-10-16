#!/usr/bin/env python3
"""Memory-only native NP application adapter/kernel comparison; no live routes.

Run serially under the repository validation guard. The comparison shares the
current extracted native kernel, so it measures adapter overhead, not an older
binary or independent scientific implementation. GC and all budgets stay intact.
"""

import argparse
from copy import deepcopy
import gc
import json
import math
import pickle
from statistics import median
from time import perf_counter
from uuid import UUID

from backend.api import part_np_application_commands as commands, state
from backend.api.part_evaluation_worker import EvaluationWorker
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_recovery_budget import RecoveryBudget, retained_recovery_bytes
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design, NanoparticleConnectionVersion, SnapshotLogEntry
from backend.core.nanoparticle_connections import connection_attaches, set_version_applied
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_verification_capture import admit, capture
from scripts.benchmark_runtime_probe import RuntimeProbe, overlap_ms
from tests.conftest import valid_overhang_sites


CREATE = "nanoparticle-connection-version-create"
PATCH = "nanoparticle-connection-version-patch"
DELETE = "nanoparticle-connection-version-delete"
ACTIONS = (("create-applied", CREATE, True), ("reapply", PATCH, True),
           ("unapply", PATCH, False), ("apply-pending", PATCH, True),
           ("delete-applied", DELETE, False))


def seed(value):
    return str(UUID(int=value))


def stats(values):
    values = sorted(values)
    return {"count": len(values), "p50_ms": median(values) if values else None,
            "p95_ms": values[math.ceil(len(values) * .95) - 1] if values else None,
            "max_ms": values[-1] if values else None}


def authoring(design):
    return design.model_dump(mode="json", include=AUTHORING_FIELDS)


def append(design, kind, params, identity, budget):
    before, before_size = state.encode_design_snapshot(design)
    candidate = execute(kind, design, params)
    after, after_size = state.encode_design_snapshot(candidate)
    budget.charge(before, after)
    entry = SnapshotLogEntry(id=identity, op_kind=kind, label=identity,
        timestamp="2026-10-15T00:00:00Z", params=deepcopy(params),
        design_snapshot_gz_b64=before, snapshot_size_bytes=before_size,
        post_state_gz_b64=after, post_state_size_bytes=after_size)
    return candidate.copy_with(feature_log=[*design.feature_log, entry])


def prefix(handles, background, budget):
    design = create_empty_part("NP application adapter benchmark", "HONEYCOMB")
    cells = ([[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3]] if background == "six-cell"
             else [[row, column] for row in range(6) for column in range(6)])
    design = append(design, "bundle-create", {"_proof_version": 1, "history_seed": seed(701),
        "cells": cells, "length_bp": 42, "name": design.metadata.name, "lattice_type": "HONEYCOMB"}, "bundle", budget)
    site = next(item for item in valid_overhang_sites(design) if not item["is_five_prime"])
    design = append(design, "overhang-extrude", {"_proof_version": 1, "history_seed": seed(702),
        **site, "direction": site["direction"].value, "length_bp": 12}, "target", budget)
    design = append(design, "overhang-sequence", {"_proof_version": 1,
        "overhang_id": design.overhangs[0].id, "sequence": "ACGT" * 3, "defer_reassign": True}, "sequence", budget)
    design = append(design, "nanoparticle-create", {"_proof_version": 1, "nanoparticle_version": 1,
        "nanoparticle_id": "gold", "diameter_nm": 10.0}, "gold", budget)
    return append(design, "nanoparticle-conjugate", {"_proof_version": 1, "thiol_version": 1,
        "history_seed": seed(704), "nanoparticle_id": "gold", "conjugation_id": "gold-graft",
        "replace_conjugation_ids": [], "scheme": "direct_thiol", "sequence": "ACGT" * 3,
        "count": handles, "attach_end": "5p", "spacer_nm": None, "seed": 17}, "graft", budget)


def inputs(design, kind, applied, number):
    owner = design.nanoparticle_conjugations[0]
    handle = owner.surface_strands[0]
    target = next(item for item in design.overhangs if not item.auxiliary_endpoint)
    current = next((item for item in design.nanoparticle_connection_versions if item.id == "candidate"), None)
    values = {"_proof_version": 1, "nanoparticle_connection_version": 1, "nanoparticle_application_version": 1,
        "nanoparticle_id": "gold", "conjugation_id": owner.id, "strand_id": handle.strand_id,
        "overhang_id": target.id, "version_id": "candidate", "handle_overhang_id": handle.overhang_id,
        "history_seed": seed(9200 + number), "prior_duplex_id": current.duplex_id if current else None,
        "conflict_version_ids": []}
    if kind == CREATE:
        values.update(name="Measured candidate", created_at=12.0,
                      connection_type="direct", direct_variant="end-to-root")
    if kind != DELETE:
        values["applied"] = applied
        if applied:
            values.update(duplex_id=f"application-duplex-{number}", duplex_created_at=15.0 + number)
    return values


def kernel_operation(kind, design, values):
    """Existing native lifecycle with the same explicit identities and choices.

    Creation/deletion include their ordinary version-list changes. The same
    set_version_applied kernel does all register/restoration/placement work.
    """
    candidate = design
    if kind == CREATE:
        owner = next(item for item in design.nanoparticle_conjugations if item.id == values["conjugation_id"])
        np_attach, target_attach = connection_attaches(owner, values["direct_variant"])
        version = NanoparticleConnectionVersion(id=values["version_id"], name=values["name"],
            created_at=values["created_at"], nanoparticle_id=values["nanoparticle_id"],
            strand_id=values["strand_id"], overhang_id=values["overhang_id"],
            connection_type=values["connection_type"], direct_variant=values["direct_variant"],
            nanoparticle_attach=np_attach, target_attach=target_attach)
        candidate = candidate.copy_with(nanoparticle_connection_versions=[
            *candidate.nanoparticle_connection_versions, version])
    applying = kind != DELETE and values["applied"]
    candidate = set_version_applied(candidate, values["version_id"], applying,
        duplex_id=values.get("duplex_id"), duplex_created_at=values.get("duplex_created_at"),
        identity_seed=values["history_seed"] if applying else None)
    if kind == DELETE:
        candidate = candidate.copy_with(nanoparticle_connection_versions=[
            item for item in candidate.nanoparticle_connection_versions if item.id != values["version_id"]])
    return candidate


def run_worker(report, name, source, phase, operation=None):
    phase[0] = report["active_phase"] = name
    detail = report[name] = {"cleanup_verified": False}
    worker = None
    started = perf_counter()
    try:
        worker = VerificationWorker(source) if operation is None else EvaluationWorker(source, operation)
        worker.start()
        if not worker.wait(5):
            raise TimeoutError("Worker exceeded the existing five-second measurement allowance")
        result = worker.result()
        detail.update(status=result["status"], issues=result["issues"],
                      checked_commands=result.get("checked_commands"), validation=result.get("validation"))
        if result["status"] != ("verified" if operation is None else "ready"):
            raise RuntimeError(f"{name} returned {result['status']}: {result['issues']}")
        return result
    finally:
        detail["execution_ms"] = (perf_counter() - started) * 1000
        close_started = perf_counter()
        if worker is not None:
            worker.close()
            detail["cleanup_verified"] = not worker.is_alive()
        else:
            detail["cleanup_verified"] = True  # Constructor owns partial-allocation cleanup.
        detail["cleanup_ms"] = (perf_counter() - close_started) * 1000


def summarize(report):
    rows = report.get("samples", [])
    report["timings"] = {}
    for action, _, _ in ACTIONS:
        selected = [row for row in rows if row["action"] == action]
        report["timings"][action] = {mode: stats([row["elapsed_ms"] for row in selected if row["mode"] == mode])
                                      for mode in ("adapter", "kernel")}
        pairs = {}
        for row in selected:
            if row.get("completed"):
                pairs.setdefault(row["iteration"], {})[row["mode"]] = row["elapsed_ms"]
        report["timings"][action]["observed_adapter_minus_kernel"] = stats([
            pair["adapter"] - pair["kernel"] for pair in pairs.values() if len(pair) == 2])
    report["output_parity_pairs"] = sum(row.get("output_parity_verified", False)
                                         for row in rows if row["mode"] == "adapter")


def measure(report, handles, background, repeats, probe, phase):
    phase[0] = report["active_phase"] = "native_fixture"
    budget = RecoveryBudget()
    source = prefix(handles, background, budget)
    report.update(handles=handles, background=background, samples=[],
        helices=len(source.helices), strands=len(source.strands),
        domains=sum(len(item.domains) for item in source.strands),
        helix_bases=sum(item.length_bp for item in source.helices),
        domain_bases=sum(abs(domain.end_bp - domain.start_bp) + 1 for strand in source.strands for domain in strand.domains),
        loop_descriptors=sum(len(item.loop_skips) for item in source.helices))
    phase[0] = report["active_phase"] = "native_source_admission"
    commands._work_admission(source)
    admit(source)
    report["source_work_and_node_byte_admitted"] = True
    applied = source
    for number, (action, kind, applying) in enumerate(ACTIONS[:-1], 1):
        phase[0] = report["active_phase"] = "proof_recipe_" + action
        applied = append(applied, kind, inputs(applied, kind, applying, number), action, budget)
    report["applied_recipe_rows"] = len(applied.feature_log)
    report["applied_recovery_bytes"] = retained_recovery_bytes(applied.feature_log, max_rows=2000)

    # Proof must include an actual relocated output. Recovery is deliberately
    # poisoned; none of these strings can substitute for native feature inputs.
    poisoned = applied.model_copy(update={"feature_log": [entry.model_copy(update={
        "design_snapshot_gz_b64": "not a recovery source", "post_state_gz_b64": "not a recovery source"})
        for entry in applied.feature_log]})
    phase[0] = report["active_phase"] = "cold_capture"
    start = perf_counter()
    try:
        captured = capture(poisoned, preserve_entry_types=True)
    finally:
        report["cold_capture_ms"] = (perf_counter() - start) * 1000
    report["cold_input_pickle_bytes"] = len(pickle.dumps(captured, protocol=pickle.HIGHEST_PROTOCOL))
    run_worker(report, "cold_verification", captured, phase)

    phase[0] = report["active_phase"] = "same_process_full_verification"
    start = perf_counter()
    try:
        proof = assess_part_history(captured, execute=execute, dependencies=dependencies)
        report["same_process_full_verification"] = proof
        if proof["status"] != "verified":
            raise RuntimeError(f"Same-process native proof failed: {proof}")
    finally:
        report["same_process_full_verification_ms"] = (perf_counter() - start) * 1000

    for iteration in range(repeats):
        native, kernel = source, source
        for number, (action, kind, applying) in enumerate(ACTIONS, 1):
            values = inputs(native, kind, applying, number)
            originals = {"adapter": native.model_dump_json(), "kernel": kernel.model_dump_json()}
            current = {"adapter": native, "kernel": kernel}
            output, pair = {}, {}
            for mode in (("adapter", "kernel") if iteration % 2 == 0 else ("kernel", "adapter")):
                phase[0] = report["active_phase"] = f"{action}:{mode}"
                sample = {"iteration": iteration, "action": action, "mode": mode}
                report["samples"].append(sample)
                pair[mode] = sample
                start = perf_counter()
                try:
                    builder = commands.build if mode == "adapter" else kernel_operation
                    output[mode] = builder(kind, current[mode], values)
                    sample["completed"] = True
                finally:
                    end = perf_counter()
                    events = probe.intervals(start, end)
                    sample.update(elapsed_ms=(end - start) * 1000, gc_overlap_ms=overlap_ms(events, start, end),
                                  gc_events=len(events), gc_generations=sorted({item["generation"] for item in events}))
            # Exact comparison and source immutability checks are independent
            # of timings. No geometry is reconstructed from snapshots here.
            if any(current[mode].model_dump_json() != originals[mode] for mode in current):
                raise AssertionError("Native lifecycle mutated an input design")
            if authoring(output["adapter"]) != authoring(output["kernel"]):
                raise AssertionError(f"Adapter/kernel output differs for {action}")
            pair["adapter"]["output_parity_verified"] = True
            native, kernel = output["adapter"], output["kernel"]
        if native.nanoparticle_connection_versions or native.duplexes:
            raise AssertionError("Owned lifecycle failed to delete the applied version")

    # Full proof, upstream edit, recovery encoding and validation are measured
    # separately from leaf overhead. This produces a private candidate only.
    gold_index = next(index for index, row in enumerate(applied.feature_log) if row.id == "gold")
    operation = {"header": {"source_revision": 0, "source_design_id": applied.id},
                 "request": {"operation": "edit", "index": gold_index, "params": {"diameter_nm": 14.0}}}
    result = run_worker(report, "full_edit_evaluation", captured, phase, operation)
    candidate = Design.model_validate(result["candidate"])
    before = applied.nanoparticle_conjugations[0].surface_strands[0]
    after = candidate.nanoparticle_conjugations[0].surface_strands[0]
    if (candidate.nanoparticles[0].diameter_nm != 14.0
            or after.backbone_attachment_local_nm == before.backbone_attachment_local_nm
            or candidate.duplexes[0].id != applied.duplexes[0].id):
        raise AssertionError("Full edit did not regenerate the owned attachment with stable child identity")
    report["full_edit_evaluation"]["geometry_edit_verified"] = True
    report["full_edit_evaluation"]["recovery_bytes"] = retained_recovery_bytes(candidate.feature_log, max_rows=2000)
    phase[0] = report["active_phase"] = "complete"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 30:
        parser.error("repeats must be between 1 and 30")
    cases, phase, failure = [], ["initial"], None
    probe = RuntimeProbe(phase=lambda: phase[0], max_events=4096)
    try:
        with probe:
            for background in ("six-cell", "36-cell-42bp"):
                for handles in (1, 16):
                    report = {"case": f"{background}-{handles}-handles", "completed": False}
                    cases.append(report)
                    started = perf_counter()
                    try:
                        measure(report, handles, background, args.repeats, probe, phase)
                        report["completed"] = True
                    except Exception as error:
                        report["failure"] = {"phase": report.get("active_phase"),
                            "exception": type(error).__name__, "detail": str(error)}
                    finally:
                        report["case_elapsed_ms"] = (perf_counter() - started) * 1000
                        summarize(report)
    except Exception as error:
        failure = {"exception": type(error).__name__, "detail": str(error)}
    cleanup = (probe._callback not in gc.callbacks and all(
        row[name]["cleanup_verified"] for row in cases
        for name in ("cold_verification", "full_edit_evaluation") if name in row))
    completed = failure is None and len(cases) == 4 and all(item["completed"] for item in cases)
    print(json.dumps({"scope": "Pure bounded NP owned application lifecycle; current shared native kernel comparison",
        "notes": ["No HTTP publication, user document, simulation, solver change or global budget change.",
            "Both arms use the current extracted kernel with identical explicit IDs, timestamps and history seeds.",
            "Cold input-only proof with poisoned recovery succeeds before timed cycles; no fixture shrinking or retries.",
            "Alternating paired order reduces fixed ordering bias; full output parity and input immutability are checked outside timing.",
            "Full verification and private edit evaluation include their existing unchanged admission and recovery budgets.",
            "GC remains natural; overlap is correlation only and is never subtracted from elapsed latency.",
            "Main-process GC observations exclude worker-process collections; no peak-memory qualification is claimed."],
        "repeats": args.repeats, "completed": completed, "correctness_verified": completed and cleanup,
        "latency_qualified": False, "exit_status_basis": "Correctness and cleanup only; no latency acceptance threshold",
        "cleanup_verified": cleanup, "failure": failure, "failed_cases": [item["case"] for item in cases if not item["completed"]],
        "diagnostics": {"event_limit": probe.max_events, "gc_events": len(probe.events),
                        "dropped_gc_events": probe.dropped_events}, "cases": cases}, indent=2))
    return int(not completed or not cleanup)


if __name__ == "__main__":
    raise SystemExit(main())
