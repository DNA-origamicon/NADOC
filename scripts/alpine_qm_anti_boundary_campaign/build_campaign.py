#!/usr/bin/env python3
"""Build one screened d(TpT) optimization per anti TT-CPD for Alpine."""

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


PRODUCTS = (
    "tt-cpd-cis-anti-i",
    "tt-cpd-cis-anti-ii",
    "tt-cpd-trans-anti-i",
    "tt-cpd-trans-anti-ii",
)
REMOTE_ROOT = Path(
    "/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-anti-boundary-opt-v1"
)


def build(*, seed_root: Path, output_root: Path) -> dict[str, object]:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite campaign: {output_root}")
    bundle = output_root / "bundle"
    cases_root = bundle / "cases"
    cases_root.mkdir(parents=True)
    records = []
    lines = []
    for index, product_id in enumerate(PRODUCTS):
        screen_path = (
            seed_root / product_id / "chain-b/candidate_manifest.json"
        ).resolve()
        model, xyz_path, atom_map_path = _screened_boundary(screen_path, product_id)
        atom_map = json.loads(atom_map_path.read_text())
        model_id = str(model.get("model_id") or "")
        if len(atom_map) != 63 or len(set(atom_map)) != 63 or not model_id:
            raise ValueError(f"{product_id}: seed identity is invalid")
        job_dir = cases_root / product_id / "job"
        job = generate_psi4_job(
            product_id=product_id,
            model_id=model_id,
            xyz_path=xyz_path,
            output_dir=job_dir,
            job_kind="geometry_optimization",
            charge=-1,
            multiplicity=1,
            atom_map=atom_map,
            model_manifest_path=screen_path,
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
            raise ValueError(f"{product_id}: generated job differs from pinned protocol")
        case = {
            "schema": "nadoc.photoproduct-alpine-boundary-optimization-case.v1",
            "status": "generated_not_run",
            "gate_effect": "none",
            "simulation_ready": False,
            "product_id": product_id,
            "model_id": model_id,
            "charge": -1,
            "multiplicity": 1,
            "atom_count": 63,
            "stable_atom_map_sha256": _sha256(atom_map_path),
            "screened_boundary": {
                "path": str(screen_path),
                "sha256": _sha256(screen_path),
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
        lines.append(f"{index}\t{product_id}\t{case_hash}")
        records.append(
            {
                "array_index": index,
                "product_id": product_id,
                "case_manifest_sha256": case_hash,
            }
        )
    (bundle / "cases.tsv").write_text("\n".join(lines) + "\n")
    for name in ("run_case.sh", "campaign_64.sbatch"):
        shutil.copy2(Path(__file__).with_name(name), bundle / name)
    shutil.copy2(
        REPOSITORY_ROOT / "scripts/alpine_qm_boundary_campaign/run_case.sh",
        bundle / "shared_run_case.sh",
    )
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
        "product_count": len(records),
        "products": records,
        "remote_root": str(REMOTE_ROOT),
        "archive": {"path": str(archive.resolve()), "sha256": _sha256(archive)},
        "interpretation": (
            "Full anti-product d(TpT) optimizations from screened geometry-only "
            "seeds; frequency, fitting, and simulation gates remain closed."
        ),
    }
    (output_root / "campaign_manifest.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                seed_root=args.seed_root.resolve(),
                output_root=args.output_root.resolve(),
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
