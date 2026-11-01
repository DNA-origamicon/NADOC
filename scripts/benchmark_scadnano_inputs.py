"""Bounded scadnano import qualification; no user files or physics are written."""

import argparse
import json
import pickle
from statistics import median
from time import perf_counter

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import crud, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_verification_worker import VerificationWorker
from backend.core import part_scadnano_source as limits
from backend.core.models import Design
from backend.core.part_history_contract import assess_part_history
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_input_sources import InputSource
from backend.core.part_verification_capture import capture
from scripts.benchmark_cadnano_inputs import authoring_nodes, timed


def synthetic(helices=2, length=16, fragments=1):
    data = {"version": "0.19.0", "grid": "square", "name": "__e2e__scadnano-boundary",
        "helices": [{"grid_position": [index % 4, index // 4], "max_offset": length}
                    for index in range(helices)], "strands": []}
    for helix in range(helices):
        for forward in (True, False):
            for offset in range(0, length, length // fragments):
                data["strands"].append({"is_scaffold": forward,
                    "domains": [{"helix": helix, "forward": forward, "start": offset,
                                 "end": offset + length // fragments}]})
    return json.dumps(data, separators=(",", ":")).encode()


def measure(api, name, raw, repeats):
    imports, captures, proofs = [], [], []
    for _ in range(repeats):
        response, duration = timed(lambda: api.post("/api/design/import/scadnano", json={"content": raw.decode()}))
        assert response.status_code == 200, response.text
        assert response.json()["import_history"]["status"] == "reproduced_import", response.text
        imports.append(duration)
        design = state.get_or_404()
        reloaded = Design.from_json(design.to_json())
        assert reloaded.model_dump(include=AUTHORING_FIELDS) == design.model_dump(include=AUTHORING_FIELDS)
        for row in reloaded.feature_log:
            row.design_snapshot_gz_b64 = row.post_state_gz_b64 = "poisoned output is not an input"
        isolated, duration = timed(lambda: capture(reloaded))
        captures.append(duration)
        proof, duration = timed(lambda: assess_part_history(isolated, execute=execute, dependencies=dependencies))
        assert proof["status"] == "reproduced_import", proof
        proofs.append(duration)
    worker = VerificationWorker(isolated)
    try:
        started = perf_counter()
        worker.start()
        assert worker.wait(5), "Existing cold-worker deadline exceeded"
        result = worker.result()
        assert result["status"] == "reproduced_import", result
        worker_ms = (perf_counter() - started) * 1000
    finally:
        worker.close()
    descriptor = InputSource.model_validate(design.feature_log[0].params["source"])
    _, counts = limits.parse_source(raw, descriptor)
    return {"case": name, "source_bytes": len(raw), "work": counts,
        "authoring_nodes": authoring_nodes(design), "candidate_bytes": len(design.model_dump_json().encode()),
        "worker_input_bytes": len(pickle.dumps(isolated, protocol=pickle.HIGHEST_PROTOCOL)),
        "recovery_bytes": sum(len(row.design_snapshot_gz_b64) + len(row.post_state_gz_b64) for row in design.feature_log),
        "import_http_median_ms": median(imports), "import_http_max_ms": max(imports),
        "capture_median_ms": median(captures), "capture_max_ms": max(captures),
        "proof_median_ms": median(proofs), "cold_worker_ms": worker_ms, "status": result["status"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 25:
        parser.error("Use 1..25 repeats")
    tiny = synthetic()
    cases = [("small", tiny), ("source-byte-boundary", tiny + b" " * (limits.MAX_SOURCE_BYTES - len(tiny))),
        ("helix-boundary", synthetic(32)), ("helix-span-boundary", synthetic(1, 2048)),
        ("nucleotide-and-span-boundary", synthetic(16, 512)),
        ("strand-boundary", synthetic(32, 128, 2))]
    app = FastAPI()
    app.include_router(crud.router, prefix="/api")
    token = set_current_doc("__e2e__scadnano-input-benchmark")
    rows, failure = [], None
    try:
        with TestClient(app) as api:
            for name, raw in cases:
                try:
                    rows.append(measure(api, name, raw, args.repeats))
                except Exception as error:
                    failure = {"case": name, "type": type(error).__name__, "detail": str(error)}
                    break
    finally:
        state.close_session()
        reset_current_doc(token)
    print(json.dumps({"scope": "Ordinary source import, capture, recovery, cold replay and reload; no physical simulation",
        "repeats": args.repeats, "cases": rows, "completed": failure is None, "failure": failure}, indent=2))
    return int(failure is not None)


if __name__ == "__main__":
    raise SystemExit(main())
