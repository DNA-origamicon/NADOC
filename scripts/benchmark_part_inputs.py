#!/usr/bin/env python3
"""Measure pinned-source capture/proof costs on small, repeated PDB imports.

Fixtures and results stay in memory; stdout is a compact reproducible JSON report.
This measures explicit checks, not rendering, solver speed, or import UI latency.
"""

import json
from statistics import median
from time import perf_counter

from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import SnapshotLogEntry
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_input_sources import describe, embed
from backend.core.part_verification_capture import CaptureLimit, capture

# Three canonical PDB atom records; each import uses independent authored IDs
# but the same immutable source. No external file, library or simulation output.
PDB = ("ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N\n"
       "ATOM      2  CA  GLY A   1       1.450   0.000   0.000  1.00 20.00           C\n"
       "ATOM      3  C   GLY A   1       2.450   1.000   0.000  1.00 20.00           C\nEND\n").encode()


def source(count):
    descriptor = describe(PDB, format="pdb", media_type="chemical/x-pdb")
    design = create_empty_part("Input benchmark", "HONEYCOMB").copy_with(
        input_sources={descriptor.sha256: embed(descriptor, PDB)})
    for index in range(count):
        params = {"_proof_version": 1, "protein_version": 1, "importer_version": 1,
                  "source": descriptor.model_dump(), "asset_id": f"asset-{index}",
                  "name": f"Protein {index}", "source_filename": "benchmark.pdb", "exclude_dna": True}
        design = execute("protein-import", design, params)
        design.feature_log.append(SnapshotLogEntry(op_kind="protein-import", label="Import", params=params,
            design_snapshot_gz_b64="poisoned recovery", post_state_gz_b64="poisoned output"))
    return design


def main():
    rows = []
    for count in (1, 32, 128):
        design = source(count)
        captures, proofs, statuses = [], [], []
        for _ in range(9):
            start = perf_counter()
            try:
                isolated = capture(design)
            except CaptureLimit:
                captures.append((perf_counter() - start) * 1_000)
                statuses.append("capture_limit")
                continue
            captures.append((perf_counter() - start) * 1_000)
            start = perf_counter()
            result = assess_part_history(isolated, execute=execute, dependencies=dependencies)
            proofs.append((perf_counter() - start) * 1_000)
            statuses.append(result["status"])
        rows.append({"features": count, "atoms": len(design.protein_assets) * 3,
                     "deduplicated_source_bytes": len(PDB), "source_count": len(design.input_sources),
                     "capture_median_ms": median(captures), "capture_max_ms": max(captures),
                     "proof_median_ms": median(proofs) if proofs else None,
                     "statuses": statuses})
    print(json.dumps({"scope": "warm in-memory explicit capture and input replay; no physical outputs",
                      "repeats": 9, "capture_limits_unchanged": {"nodes": 30_000, "bytes": 2_000_000,
                      "cooperative_seconds": 0.025}, "cases": rows}, indent=2))
    return int(any(status not in {"reproduced_import", "capture_limit"}
                   for row in rows for status in row["statuses"]))


if __name__ == "__main__":
    raise SystemExit(main())
