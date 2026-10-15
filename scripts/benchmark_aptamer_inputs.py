#!/usr/bin/env python3
"""Serial aptamer admission evidence; all models/results stay in memory.

Run under the repository validation guard. Stdout is JSON; no user document,
simulation, geometry lock or artifact is written. This measures software input
work, not physical validity of the deliberately adversarial boundary fixture.
"""

import argparse
import json
import pickle
from statistics import median
from time import perf_counter
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel

from backend.api import part_aptamer_commands as commands, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_verification_worker import VerificationWorker
from backend.core.aptamer import CATALOG, template_content
from backend.core.models import SnapshotLogEntry
from backend.core.part_history_contract import FIELD_ROLES, assess_part_history, create_empty_part
from backend.core.part_input_sources import describe, embed
from backend.core.part_verification_capture import CaptureLimit, capture


def boundary_source():
    """Exactly 1,000 distinct first-model atom records and 150,000 UTF-8 bytes.

    One complete source residue plus arbitrary distinct atom labels exercises
    maximum parser output size. It is not a scientifically meaningful molecule.
    """
    lines = [line for line in template_content("148D").splitlines()
             if line.startswith("ATOM") and line[22:26].strip() == "1"]
    exemplar = lines[0]
    for index in range(commands.MAX_APTAMER_ATOM_RECORDS - len(lines)):
        lines.append(exemplar[:12] + f"X{index:03d}" + exemplar[16:])
    text = "\n".join(lines) + "\nENDMDL\nREMARK "
    return text + "x" * (commands.MAX_APTAMER_SOURCE_BYTES - len(text.encode()))


def authoring_nodes(design):
    """Report structural authoring nodes, excluding source and history payloads."""
    pending = [getattr(design, field) for field, role in FIELD_ROLES.items() if role == "authoring"]
    seen, count = set(), 0
    while pending:
        item = pending.pop()
        count += 1
        if isinstance(item, (BaseModel, dict, list, tuple)):
            if id(item) in seen:
                continue
            seen.add(id(item))
            if isinstance(item, BaseModel):
                pending.extend(item.__dict__.values())
            elif isinstance(item, dict):
                pending.extend(item.keys())
                pending.extend(item.values())
            else:
                pending.extend(item)
    return count


def fixture(text, name, count):
    raw = text.encode()
    source = describe(raw, format="pdb", media_type="chemical/x-pdb")
    design = create_empty_part(name, "HONEYCOMB").copy_with(
        input_sources={source.sha256: embed(source, raw)})
    recovery_bytes, recovery_ms, build_ms = 0, 0.0, 0.0
    for index in range(count):
        params = {"_proof_version": 1, "aptamer_version": 1, "importer_version": 1,
                  "source": source.model_dump(mode="json"), "name": name,
                  "source_label": "benchmark pinned source", "_helix_id": f"apt_bench_{index}",
                  "_strand_id": f"apt_bench_strand_{index}",
                  "history_seed": str(uuid5(NAMESPACE_URL, f"aptamer-benchmark:{index}")),
                  "initialize_metadata": index == 0}
        started = perf_counter()
        pre, pre_size = state.encode_design_snapshot(design)
        recovery_ms += (perf_counter() - started) * 1_000
        started = perf_counter()
        design = execute("aptamer-import", design, params)
        build_ms += (perf_counter() - started) * 1_000
        started = perf_counter()
        post, post_size = state.encode_design_snapshot(design)
        recovery_ms += (perf_counter() - started) * 1_000
        recovery_bytes += len(pre) + len(post)
        design.feature_log.append(SnapshotLogEntry(op_kind="aptamer-import", label="Pinned aptamer", params=params,
            design_snapshot_gz_b64=pre, snapshot_size_bytes=pre_size,
            post_state_gz_b64=post, post_state_size_bytes=post_size))
    return design, {"source_bytes": len(raw), "source_count": len(design.input_sources),
                    "first_model_atom_records": commands._first_model_records(text),
                    "authoring_nodes": authoring_nodes(design),
                    "parsed_atoms": sum(len(site.atoms) for helix in design.helices for site in helix.native_residues),
                    "build_total_ms": build_ms, "recovery_encode_total_ms": recovery_ms,
                    "recovery_encoded_bytes": recovery_bytes,
                    "candidate_json_bytes": len(design.model_dump_json().encode())}


def publication(text, name, count):
    """Actual atomic recording and validation, excluding response rendering."""
    token = set_current_doc("__benchmark_aptamer_inputs__")
    try:
        state.load_design(None)
        elapsed = []
        for _ in range(count):
            started = perf_counter()
            commands.record_import(text, name, "benchmark pinned source")
            elapsed.append((perf_counter() - started) * 1_000)
        return {"publication_record_ms": elapsed, "publication_final_revision": state.revision()}
    finally:
        state.close_session()
        reset_current_doc(token)


def measure(name, text, count, repeats):
    design, row = fixture(text, name, count)
    captures, proofs, statuses, pickle_bytes = [], [], [], []
    isolated = None
    for _ in range(repeats):
        started = perf_counter()
        try:
            isolated = capture(design)
        except CaptureLimit as exc:
            captures.append((perf_counter() - started) * 1_000)
            statuses.append({"status": "capture_limit", "detail": str(exc)})
            continue
        captures.append((perf_counter() - started) * 1_000)
        pickle_bytes.append(len(pickle.dumps(isolated, protocol=pickle.HIGHEST_PROTOCOL)))
        started = perf_counter()
        result = assess_part_history(isolated, execute=execute, dependencies=dependencies)
        proofs.append((perf_counter() - started) * 1_000)
        statuses.append({"status": result["status"], "issues": result["issues"]})
    cold = {"status": "capture_limit"}
    if isolated is not None:
        worker = VerificationWorker(isolated)
        try:
            started = perf_counter()
            worker.start()
            cold = worker.result() if worker.wait(5) else {"status": "worker_deadline"}
            cold = {"status": cold["status"], "issues": cold.get("issues", []),
                    "spawn_and_proof_ms": (perf_counter() - started) * 1_000}
        finally:
            worker.close()
    return {"case": name, "features": count, **row,
            "capture_median_ms": median(captures), "capture_max_ms": max(captures),
            "capture_refusals": sum(item["status"] == "capture_limit" for item in statuses),
            "pickle_bytes_max": max(pickle_bytes) if pickle_bytes else None,
            "proof_median_ms": median(proofs) if proofs else None,
            "proof_max_ms": max(proofs) if proofs else None,
            "statuses": statuses, "cold_worker": cold, **publication(text, name, count)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=9)
    parser.add_argument("--counts", type=int, nargs="+", default=[1, 2, 4])
    args = parser.parse_args()
    if not 1 <= args.repeats <= 25 or any(not 1 <= count <= 8 for count in args.counts):
        parser.error("Use 1..25 repeats and 1..8 features per case")
    sources = [(entry["id"], template_content(entry["id"])) for entry in CATALOG]
    rows = [measure(name, text, count, args.repeats) for name, text in sources for count in args.counts]
    rows.append(measure("boundary-unphysical-1000-records-150KB", boundary_source(), 1, args.repeats))
    print(json.dumps({"scope": "Input derivation, capture, worker, recovery and atomic recording; no rendering or physics",
        "repeats": args.repeats, "provisional_route_enabled": commands.NATIVE_ROUTE_ENABLED,
        "limits_unchanged": {"capture_nodes": 30_000, "capture_bytes": 2_000_000,
            "capture_cooperative_seconds": 0.025, "worker_input_bytes": 2_000_000,
            "candidate_bytes": 16_000_000, "cumulative_recovery_bytes": 8_000_000}, "cases": rows}, indent=2))
    return int(any(item["status"] not in {"reproduced_import", "capture_limit"}
                   for row in rows for item in [*row["statuses"], row["cold_worker"]]))


if __name__ == "__main__":
    raise SystemExit(main())
