#!/usr/bin/env python3
"""Build the canonical cis-syn-I full d(TpT) optimization for Alpine."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tarfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.parameterization.photoproduct_qm import generate_psi4_job  # noqa: E402
from scripts.alpine_qm_boundary_campaign.build_campaign import (  # noqa: E402
    _screened_boundary,
    _sha256,
)


PRODUCT_ID = "tt-cpd-cis-syn"
REMOTE_ROOT = Path(
    "/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-cis-syn-boundary-opt-v1"
)


def build(*, screened_manifest: Path, output_root: Path) -> dict[str, object]:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite campaign: {output_root}")
    model, xyz_path, atom_map_path = _screened_boundary(
        screened_manifest.resolve(), PRODUCT_ID
    )
    atom_map = json.loads(atom_map_path.read_text())
    model_id = str(model.get("model_id") or "")
    if len(atom_map) != 63 or len(set(atom_map)) != 63 or not model_id:
        raise ValueError("cis-syn-I boundary identity is invalid")
    bundle = output_root / "bundle"
    job_dir = bundle / "cases" / PRODUCT_ID / "job"
    job = generate_psi4_job(
        product_id=PRODUCT_ID,
        model_id=model_id,
        xyz_path=xyz_path,
        output_dir=job_dir,
        job_kind="geometry_optimization",
        charge=-1,
        multiplicity=1,
        atom_map=atom_map,
        model_manifest_path=screened_manifest.resolve(),
        memory_gib=100,
        threads=64,
        maximum_geometry_iterations=300,
    )
    if (
        job.get("method") != "mp2"
        or job.get("basis") != "6-31+G(d)"
        or job.get("protocol_version") != "1.5.0"
        or job.get("expected_outputs") != ["output.dat", "optimized.xyz"]
    ):
        raise ValueError("cis-syn-I optimization differs from the pinned protocol")
    case = {
        "schema": "nadoc.photoproduct-alpine-boundary-optimization-case.v1",
        "status": "generated_not_run",
        "gate_effect": "none",
        "simulation_ready": False,
        "product_id": PRODUCT_ID,
        "model_id": model_id,
        "charge": -1,
        "multiplicity": 1,
        "atom_count": 63,
        "stable_atom_map_sha256": _sha256(atom_map_path),
        "screened_boundary": {
            "path": str(screened_manifest.resolve()),
            "sha256": _sha256(screened_manifest),
        },
        "job_manifest_sha256": _sha256(job_dir / "job_manifest.json"),
        "input_sha256": _sha256(job_dir / "input.dat"),
        "source_xyz_sha256": _sha256(xyz_path),
        "protocol_version": job["protocol_version"],
        "method": job["method"],
        "basis": job["basis"],
        "resources": {
            "slurm_cpus": 64,
            "psi4_threads": 64,
            "slurm_memory_gib": 110,
            "psi4_memory_gib": 100,
            "walltime": "24:00:00",
        },
    }
    case_path = job_dir.parent / "case_manifest.json"
    case_path.write_text(json.dumps(case, indent=2) + "\n")
    case_hash = _sha256(case_path)
    (bundle / "cases.tsv").write_text(f"0\t{PRODUCT_ID}\t{case_hash}\n")
    shutil.copy2(
        REPOSITORY_ROOT / "scripts/alpine_qm_boundary_campaign/run_case.sh",
        bundle / "shared_run_case.sh",
    )
    for name in ("run_case.sh", "campaign_64.sbatch"):
        shutil.copy2(Path(__file__).with_name(name), bundle / name)
    inventory = [
        f"{_sha256(path)}  {path.relative_to(bundle)}"
        for path in sorted(item for item in bundle.rglob("*") if item.is_file())
        if path.name != "MANIFEST.sha256"
    ]
    (bundle / "MANIFEST.sha256").write_text("\n".join(inventory) + "\n")
    archive = output_root / "alpine-boundary-optimization-campaign-v1.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(bundle, arcname="bundle")
    (archive.with_suffix(archive.suffix + ".sha256")).write_text(
        f"{_sha256(archive)}  {archive.name}\n"
    )
    report = {
        "schema": "nadoc.photoproduct-alpine-boundary-optimization-campaign.v1",
        "status": "built_not_submitted",
        "gate_effect": "none",
        "simulation_ready": False,
        "product_count": 1,
        "products": [
            {
                "array_index": 0,
                "product_id": PRODUCT_ID,
                "case_manifest_sha256": case_hash,
            }
        ],
        "remote_root": str(REMOTE_ROOT),
        "archive": {"path": str(archive.resolve()), "sha256": _sha256(archive)},
        "interpretation": (
            "Canonical cis-syn-I full d(TpT) optimization evidence only. Frequency, "
            "parameter fitting, and simulation release gates remain closed."
        ),
    }
    (output_root / "campaign_manifest.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screened-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                screened_manifest=args.screened_manifest,
                output_root=args.output_root.resolve(),
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
