"""Finite DNA PDB source/transport boundaries through ordinary HTTP and cold proof.

Synthetic boundary records qualify conversion work, not molecular realism.
Temporary fixture sources are removed before measurement; no user model is used.
"""

import argparse
import json
from pathlib import Path
import tempfile
from time import perf_counter
import traceback

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import crud, routes_design_interchange as routes, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_verification_worker import VerificationWorker
from backend.core import part_dna_pdb_source as limits
from backend.core.models import Design
from backend.core.part_history_contract import assess_part_history
from backend.core.part_input_sources import InputSource
from backend.core.part_verification_capture import capture
from scripts.benchmark_cadnano_route import stats
from tests.test_pdb_to_design import _write_synthetic_duplex_pdb


def synthetic(length=4):
    with tempfile.TemporaryDirectory(prefix="__e2e__dna-pdb-source-") as root:
        path = Path(root) / "__e2e__source.pdb"
        _write_synthetic_duplex_pdb(str(path), length)
        return path.read_bytes()


def cases():
    raw = synthetic()
    first = raw.decode().splitlines()[0]
    atoms = sum(line.startswith((b"ATOM  ", b"HETATM")) for line in raw.splitlines())
    def record(serial, residue, *, chain="Z", name="DA", atom="C1'"):
        return (f"ATOM  {serial:5d} {atom:<4} {name:>3} {chain}{residue:4d}" + first[26:30]
                + f"{1000.:8.3f}{1000.:8.3f}{1000.:8.3f}" + first[54:] + "\n").encode()
    padded = raw
    while len(padded) < limits.MAX_SOURCE_BYTES:
        remaining = limits.MAX_SOURCE_BYTES - len(padded)
        padded += ((b"REMARK " + b"x" * 249 + b"\n")[:remaining] if remaining >= 7 else b" " * remaining)
    return [("small", raw), ("larger-48-bp", synthetic(48)), ("source-byte-boundary", padded),
        ("atom-boundary", raw + b"".join(record(atoms + i + 1, i + 1, name="HOH", atom="O")
                                         for i in range(limits.MAX_ATOMS - atoms))),
        ("residue-boundary", raw + b"".join(record(atoms + i + 1, i + 1)
                                            for i in range(limits.MAX_RESIDUES - 8))),
        ("chain-boundary", raw + b"".join(record(atoms + i + 1, 1, chain=chain)
                                          for i, chain in enumerate("CDEFGH"))),
        ("record-boundary", raw + b"REMARK\n" * (limits.MAX_RECORDS - len(raw.splitlines()))),
        ("bond-boundary", raw + (b"CONECT    1" + b"    2" * 8 + b"\n") * (limits.MAX_BONDS // 8))]


def measure(api, name, raw, repeats):
    imports, geometry, captures = [], [], []
    for _ in range(repeats):
        start = perf_counter()
        response = api.post("/api/design/import/pdb", json={"content": raw.decode()})
        imported = perf_counter()
        assert response.status_code == 200, response.text
        assert response.json()["import_history"]["status"] == "reproduced_import", response.text
        display = api.get("/api/design/geometry")
        end = perf_counter()
        assert display.status_code == 200, display.text
        imports.append((imported - start) * 1000)
        geometry.append((end - imported) * 1000)
        design = Design.from_json(state.get_or_404().to_json())
        for row in design.feature_log:
            row.design_snapshot_gz_b64 = row.post_state_gz_b64 = "poisoned output"
        start = perf_counter()
        isolated = capture(design)
        captures.append((perf_counter() - start) * 1000)
        result = assess_part_history(isolated, execute=execute, dependencies=dependencies)
        assert result["status"] == "reproduced_import", result
    worker = VerificationWorker(isolated)
    try:
        start = perf_counter()
        worker.start()
        assert worker.wait(5), "Existing cold-worker allowance exceeded"
        result = worker.result()
        assert result["status"] == "reproduced_import", result
        cold_ms = (perf_counter() - start) * 1000
    finally:
        worker.close()
        assert not worker.is_alive()
    descriptor = InputSource.model_validate(design.feature_log[0].params["source"])
    return {"case": name, "source_bytes": len(raw), "work": limits.parse_source(raw, descriptor)[1],
        "import_http": stats(imports), "geometry_http": stats(geometry),
        "combined_http": stats([a + b for a, b in zip(imports, geometry, strict=True)]),
        "capture": stats(captures), "cold_worker_ms": cold_ms, "status": result["status"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, choices=range(1, 26), default=5)
    args = parser.parse_args()
    doc = "__e2e__dna-pdb-input-benchmark"
    initial_sessions = set(state._sessions)
    token = set_current_doc(doc)
    api = FastAPI()
    api.include_router(routes.router, prefix="/api")
    api.include_router(crud.router, prefix="/api")
    rows, failure = [], None
    try:
        with TestClient(api) as client:
            for name, raw in cases():
                rows.append(measure(client, name, raw, args.repeats))
    except Exception as error:
        failure = {"type": type(error).__name__, "detail": str(error), "traceback": traceback.format_exc(limit=5)}
    finally:
        state.drop_doc(doc)
        reset_current_doc(token)
    cleanup = set(state._sessions) == initial_sessions
    print(json.dumps({"repeats": args.repeats, "completed": failure is None and cleanup,
        "failure": failure, "cleanup_verified": cleanup, "cases": rows}, indent=2))
    return int(failure is not None or not cleanup)


if __name__ == "__main__":
    raise SystemExit(main())
