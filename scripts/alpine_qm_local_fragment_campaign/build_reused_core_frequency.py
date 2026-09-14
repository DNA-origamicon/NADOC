#!/usr/bin/env python3
"""Build the one missing reused-core frequency job for Alpine D2 reconciliation."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.parameterization.photoproduct_distributed_hessian import (  # noqa: E402
    materialize_frequency_job_provenance,
)
from backend.parameterization.photoproduct_qm import generate_psi4_job  # noqa: E402

PRODUCT_ID = "tt-cpd-cis-syn-ii"
CASE_ID = "frequency-reused-tt-cpd-cis-syn-ii"
REMOTE_ROOT = Path(
    "/scratch/alpine/jojo6687/nadoc_qm_campaigns/"
    "tt-cpd-local-fragment-reused-core-frequency-v1"
)
PROTOCOL = REPOSITORY_ROOT / "backend/data/forcefield/photoproduct_qm_protocol_v1.7.0.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def build(*, geometry_dir: Path, output_root: Path) -> dict[str, object]:
    geometry_dir = geometry_dir.resolve()
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite campaign: {output_root}")
    parent_path = geometry_dir / "optimized_model_audit.json"
    geometry_path = geometry_dir / "optimized.xyz"
    geometry_job_path = geometry_dir / "job_manifest.json"
    parent = json.loads(parent_path.read_text())
    geometry_job = json.loads(geometry_job_path.read_text())
    if (
        parent.get("status") != "passed_candidate_identity_and_chirality"
        or parent.get("product_id") != PRODUCT_ID
        or parent.get("model_id") != "n1-methyl-tt-cpd-cis-syn-ii"
        or parent.get("optimized_xyz", {}).get("sha256") != _sha256(geometry_path)
        or geometry_job.get("product_id") != PRODUCT_ID
        or geometry_job.get("atom_count") != 36
        or geometry_job.get("charge") != 0
        or len(geometry_job.get("atom_map") or []) != 36
    ):
        raise ValueError("cis-syn-II optimized core evidence is invalid")

    bundle = output_root / "bundle"
    job_dir = bundle / "frequency-cases" / CASE_ID / "job"
    job = generate_psi4_job(
        product_id=PRODUCT_ID,
        model_id=parent["model_id"],
        xyz_path=geometry_path,
        output_dir=job_dir,
        job_kind="frequency",
        charge=0,
        multiplicity=1,
        atom_map=geometry_job["atom_map"],
        parent_manifest_path=parent_path,
        memory_gib=48,
        threads=32,
        protocol_path=PROTOCOL,
    )
    if (
        job.get("method") != "mp2"
        or job.get("basis") != "6-31G(d)"
        or job.get("protocol_version") != "1.7.0"
        or set(job.get("expected_outputs") or [])
        != {"output.dat", "hessian_hartree_per_bohr2.txt"}
    ):
        raise ValueError("generated frequency job differs from the current protocol")
    materialize_frequency_job_provenance(job_dir=job_dir)
    case = {
        "schema": "nadoc.photoproduct-alpine-local-fragment-frequency-case.v1",
        "status": "generated_not_run",
        "gate_effect": "none",
        "simulation_ready": False,
        "id": CASE_ID,
        "product_id": PRODUCT_ID,
        "model_id": job["model_id"],
        "atom_count": 36,
        "origin_geometry_job_manifest": _record(geometry_job_path),
        "origin_optimized_model_audit": _record(parent_path),
        "job_manifest_sha256": _sha256(job_dir / "job_manifest.json"),
        "input_sha256": _sha256(job_dir / "input.dat"),
        "provenance_sha256": _sha256(job_dir / "frequency_job_provenance.json"),
        "resources": {
            "slurm_cpus": 32,
            "psi4_threads": 32,
            "slurm_memory_gib": 56,
            "psi4_memory_gib": 48,
            "walltime": "23:30:00",
        },
    }
    case_path = job_dir.parent / "case_manifest.json"
    case_path.write_text(json.dumps(case, indent=2) + "\n")
    case_hash = _sha256(case_path)
    (bundle / "frequency_cases.tsv").write_text(f"0\t{CASE_ID}\t{case_hash}\n")
    for name in ("run_case.sh", "frequency.sbatch"):
        shutil.copy2(Path(__file__).with_name(name), bundle / name)
    inventory = [
        f"{_sha256(path)}  {path.relative_to(bundle)}"
        for path in sorted(item for item in bundle.rglob("*") if item.is_file())
        if path.name != "MANIFEST.sha256"
    ]
    (bundle / "MANIFEST.sha256").write_text("\n".join(inventory) + "\n")
    archive = output_root / "alpine-reused-core-frequency-v1.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(bundle, arcname="bundle")
    (archive.with_suffix(archive.suffix + ".sha256")).write_text(
        f"{_sha256(archive)}  {archive.name}\n"
    )
    report = {
        "schema": "nadoc.photoproduct-alpine-local-fragment-campaign.v1",
        "status": "built_not_submitted",
        "gate_effect": "none",
        "simulation_ready": False,
        "stage_id": "D2-missing-reused-core-frequency",
        "next_stage": "D2-reused-core-frequency-inventory",
        "trigger_file": "missing_reused_core_frequency.json",
        "passed_next_action": "combine this result with the four existing matching core-frequency audits",
        "retained_local_frequencies": [],
        "queued_frequency_count": 1,
        "queued_frequencies": [
            {
                "array_index": 0,
                "id": CASE_ID,
                "case_manifest_sha256": case_hash,
                "atom_count": 36,
            }
        ],
        "remote_root": str(REMOTE_ROOT),
        "maximum_concurrent_array_tasks": 1,
        "archive": _record(archive),
        "interpretation": (
            "This is the only missing frequency among the five reused 36-atom core "
            "minima. It is independent evidence generation and does not open D2 "
            "until D1 and the complete five-core reconciliation pass."
        ),
    }
    (output_root / "campaign_manifest.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build(geometry_dir=args.geometry_dir, output_root=args.output_root),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
