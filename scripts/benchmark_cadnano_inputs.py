#!/usr/bin/env python3
"""Serial bounded caDNAno import qualification; every result stays in memory.

Run under the repository validation guard after registering cadnano-import.
Stdout is JSON. No user file, rendering, physical simulation, geometry lock or
artifact is written. Synthetic boundary inputs measure software work only.
"""

import argparse
import json
from pathlib import Path
import pickle
from statistics import median
from time import perf_counter
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel

from backend.api import state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_verification_worker import VerificationWorker
from backend.core import part_cadnano_source as limits
from backend.core.models import Design, SnapshotLogEntry
from backend.core.part_history_contract import FIELD_ROLES, assess_part_history, create_empty_part
from backend.core.part_input_sources import describe, embed
from backend.core.part_verification_capture import CaptureLimit, capture
from backend.core.validator import validate_design


def path_into(helix, kind, positions):
    for index, bp in enumerate(positions):
        previous = (helix["num"], positions[index - 1]) if index else (-1, -1)
        following = (helix["num"], positions[index + 1]) if index + 1 < len(positions) else (-1, -1)
        helix[kind][bp] = [*previous, *following]


def synthetic(*, helices=2, width=21, active=21, fragmented=False, insertion=0):
    data = {"name": "Software boundary input", "vstrands": []}
    for number in range(helices):
        helix = {"num": number, "row": number // 2, "col": number % 2,
            "scaf": [[-1] * 4 for _ in range(width)], "stap": [[-1] * 4 for _ in range(width)],
            "loop": [0] * width, "skip": [0] * width, "stap_colors": []}
        for kind in ("scaf", "stap"):
            chunks = [list(range(bp, bp + 2)) for bp in range(0, active, 2)] if fragmented else [list(range(active))]
            for positions in chunks:
                if (number % 2 == 0) != (kind == "scaf"):
                    positions.reverse()
                path_into(helix, kind, positions)
        helix["loop"][0] = insertion
        data["vstrands"].append(helix)
    return json.dumps(data, separators=(",", ":")).encode()


def authoring_nodes(design):
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


def timed(callback):
    started = perf_counter()
    value = callback()
    return value, (perf_counter() - started) * 1_000


def fixture(name, raw):
    source = describe(raw, format="cadnano-v2", media_type="application/json")
    params = {"_proof_version": 1, "lattice_import_version": 1, "importer_version": 1,
        "source": source.model_dump(mode="json"), "history_seed": str(uuid5(NAMESPACE_URL, "cadnano-benchmark")),
        "identity_policy": "source-content-v1", "name_override": None}
    initial = create_empty_part(name, "HONEYCOMB").copy_with(
        input_sources={source.sha256: embed(source, raw)})
    (_data, counts), preflight_ms = timed(lambda: limits.parse_source(raw, source))
    (pre, pre_size), pre_ms = timed(lambda: state.encode_design_snapshot(initial))
    candidate, build_ms = timed(lambda: execute("cadnano-import", initial, params))
    (post, post_size), post_ms = timed(lambda: state.encode_design_snapshot(candidate))
    candidate = candidate.copy_with(feature_log=[SnapshotLogEntry(op_kind="cadnano-import", label="Pinned caDNAno",
        params=params, design_snapshot_gz_b64=pre, snapshot_size_bytes=pre_size,
        post_state_gz_b64=post, post_state_size_bytes=post_size)])
    _report, validation_ms = timed(lambda: validate_design(candidate))
    return candidate, {"source_bytes": len(raw), "source_base64_characters": len(initial.input_sources[source.sha256].data_b64),
        "preflight_work": counts, "preflight_ms": preflight_ms, "build_ms": build_ms,
        "authoring_nodes": authoring_nodes(candidate), "output_helices": len(candidate.helices),
        "output_strands": len(candidate.strands), "output_domains": sum(len(item.domains) for item in candidate.strands),
        "recovery_encoded_bytes": len(pre) + len(post), "recovery_encode_total_ms": pre_ms + post_ms,
        "candidate_json_bytes": len(candidate.model_dump_json().encode()), "validation_ms": validation_ms,
        "private_prepare_total_ms": build_ms + pre_ms + post_ms + validation_ms}


def publication(candidate, repeats):
    """Existing whole-document load boundary only; no live import route wired."""
    token = set_current_doc("__benchmark_cadnano_inputs__")
    elapsed = []
    try:
        for _ in range(repeats):
            _result, duration = timed(lambda: state.load_design(candidate))
            elapsed.append(duration)
        return {"existing_load_boundary_median_ms": median(elapsed),
                "existing_load_boundary_max_ms": max(elapsed), "live_route_qualification": "pending"}
    finally:
        state.close_session()
        reset_current_doc(token)


def measure(name, raw, repeats):
    design, row = fixture(name, raw)
    captures, proofs, statuses, pickle_bytes = [], [], [], []
    isolated = None
    # Serialized cold reload must not infer or repair any authored output.
    reloaded = Design.from_json(design.to_json())
    from backend.core.part_history_proof import AUTHORING_FIELDS
    reload_equal = design.model_dump(include=AUTHORING_FIELDS) == reloaded.model_dump(include=AUTHORING_FIELDS)
    for _ in range(repeats):
        started = perf_counter()
        try:
            isolated = capture(reloaded)
        except CaptureLimit as exc:
            captures.append((perf_counter() - started) * 1_000)
            statuses.append({"status": "capture_limit", "detail": str(exc)})
            continue
        captures.append((perf_counter() - started) * 1_000)
        pickle_bytes.append(len(pickle.dumps(isolated, protocol=pickle.HIGHEST_PROTOCOL)))
        result, elapsed = timed(lambda: assess_part_history(isolated, execute=execute, dependencies=dependencies))
        proofs.append(elapsed)
        statuses.append({"status": result["status"], "issues": result["issues"]})
    cold = {"status": "capture_limit"}
    if isolated is not None:
        worker = VerificationWorker(isolated)
        try:
            started = perf_counter()
            worker.start()
            result = worker.result() if worker.wait(5) else {"status": "worker_deadline"}
            cold = {"status": result["status"], "issues": result.get("issues", []),
                    "spawn_and_proof_ms": (perf_counter() - started) * 1_000}
        finally:
            worker.close()
    return {"case": name, **row, "reload_authoring_equal": reload_equal,
        "capture_median_ms": median(captures), "capture_max_ms": max(captures),
        "capture_refusals": sum(item["status"] == "capture_limit" for item in statuses),
        "pickle_bytes_max": max(pickle_bytes) if pickle_bytes else None,
        "proof_median_ms": median(proofs) if proofs else None, "proof_max_ms": max(proofs) if proofs else None,
        "statuses": statuses, "cold_worker": cold, **publication(design, repeats)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=9)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 25:
        parser.error("Use 1..25 repeats")
    examples = Path(__file__).resolve().parent.parent / "Examples" / "cadnano"
    sources = [(name, (examples / name).read_bytes()) for name in (
        "Honeycomb_6hb_test1.json", "6hb_cadnano_native_test1.json")]
    tiny = synthetic()
    sources.extend([
        ("source-byte-boundary", tiny + b" " * (limits.MAX_SOURCE_BYTES - len(tiny))),
        ("helix-boundary", synthetic(helices=limits.MAX_HELICES)),
        ("array-width-boundary", synthetic(helices=1, width=limits.MAX_ARRAY_WIDTH)),
        ("strand-fragment-boundary", synthetic(helices=1, width=128, active=128, fragmented=True)),
        ("nucleotide-loop-boundary-software-only", synthetic(helices=1, insertion=(limits.MAX_NUCLEOTIDES - 42) // 2)),
    ])
    rows = [measure(name, raw, args.repeats) for name, raw in sources]
    print(json.dumps({"scope": "Pinned topology import, capture, registered cold proof, recovery, validation and existing load boundary; no rendering or physics",
        "repeats": args.repeats, "live_route_enabled": False, "limits_provisional": True,
        "limits": {key: value for key, value in vars(limits).items() if key.startswith("MAX_")},
        "limits_unchanged": {"capture_nodes": 30_000, "capture_bytes": 2_000_000,
            "capture_cooperative_seconds": 0.025, "worker_input_bytes": 2_000_000,
            "candidate_bytes": 16_000_000, "cumulative_recovery_bytes": 8_000_000}, "cases": rows}, indent=2))
    return int(any(not row["reload_authoring_equal"] or any(
        item["status"] not in {"reproduced_import", "capture_limit"}
        for item in [*row["statuses"], row["cold_worker"]]) for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
