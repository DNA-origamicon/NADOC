#!/usr/bin/env python3
"""Build full d(TpT) HF/6-31+G(d) ESP jobs from passed optimizations."""

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

from backend.parameterization.photoproduct_esp import generate_esp_job  # noqa: E402


REMOTE_ROOT = Path("/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-boundary-esp-v1")
ESP_PROTOCOL_PATH = (
    REPOSITORY_ROOT
    / "backend/data/forcefield/photoproduct_qm_protocol_v1.6.0.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(
    *, optimization_campaign_roots: list[Path], output_root: Path
) -> dict[str, object]:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite campaign: {output_root}")
    if not optimization_campaign_roots:
        raise ValueError("at least one optimization campaign is required")
    bundle = output_root / "bundle"
    cases_root = bundle / "cases"
    cases_root.mkdir(parents=True)
    sources: list[dict[str, str]] = []
    records: list[dict[str, object]] = []
    lines: list[str] = []
    seen: set[str] = set()
    for campaign_root in optimization_campaign_roots:
        campaign_root = campaign_root.resolve()
        collection_path = campaign_root / "collection_report.json"
        collection = json.loads(collection_path.read_text())
        if (
            collection.get("schema")
            != "nadoc.photoproduct-alpine-boundary-optimization-collection.v1"
            or collection.get("status") != "passed_import_and_identity_audit"
            or collection.get("passed_product_count") != collection.get("product_count")
            or collection.get("simulation_ready") is not False
            or collection.get("gate_effect") != "none"
        ):
            raise ValueError(
                f"optimization collection is not passed: {collection_path}"
            )
        sources.append(
            {"path": str(collection_path), "sha256": _sha256(collection_path)}
        )
        for product in collection.get("products") or []:
            product_id = str(product["product_id"])
            if product_id in seen:
                raise ValueError(f"duplicate optimized product: {product_id}")
            seen.add(product_id)
            source_job = campaign_root / "bundle/cases" / product_id / "job"
            optimized = source_job / "optimized.xyz"
            parent = source_job / "optimized_model_audit.json"
            source_manifest_path = source_job / "job_manifest.json"
            source_manifest = json.loads(source_manifest_path.read_text())
            audit = json.loads(parent.read_text())
            audit_record = product.get("optimized_model_audit") or {}
            atom_map = source_manifest.get("atom_map")
            if (
                audit.get("status") != "passed_identity_and_chirality"
                or audit.get("product_id") != product_id
                or audit.get("optimized_xyz", {}).get("sha256") != _sha256(optimized)
                or audit_record.get("sha256") != _sha256(parent)
                or source_manifest.get("atom_count") != 63
                or source_manifest.get("charge") != -1
                or not isinstance(atom_map, list)
                or len(atom_map) != 63
                or len(set(atom_map)) != 63
            ):
                raise ValueError(
                    f"{product_id}: optimization identity evidence differs"
                )
            job_dir = cases_root / product_id / "job"
            job = generate_esp_job(
                product_id=product_id,
                model_id=audit["model_id"],
                xyz_path=optimized,
                atom_map=atom_map,
                parent_manifest_path=parent,
                output_dir=job_dir,
                charge=-1,
                multiplicity=1,
                memory_gib=36,
                threads=16,
                protocol_path=ESP_PROTOCOL_PATH,
            )
            if (
                job.get("method") != "hf"
                or job.get("basis") != "6-31+G(d)"
                or job.get("protocol_version") != "1.6.0"
                or job.get("expected_outputs") != ["output.dat", "grid_esp.dat"]
                or job.get("properties") != ["GRID_ESP", "DIPOLE"]
                or job.get("dipole_units") != "atomic_unit_e_bohr"
                or int((job.get("grid") or {}).get("point_count") or 0) < 252
            ):
                raise ValueError(
                    f"{product_id}: ESP job differs from the pinned protocol"
                )
            case = {
                "schema": "nadoc.photoproduct-alpine-boundary-esp-case.v1",
                "status": "generated_not_run",
                "gate_effect": "none",
                "simulation_ready": False,
                "product_id": product_id,
                "model_id": audit["model_id"],
                "atom_count": 63,
                "charge": -1,
                "multiplicity": 1,
                "source_optimization_audit": {
                    "path": str(parent.resolve()),
                    "sha256": _sha256(parent),
                },
                "job_manifest_sha256": _sha256(job_dir / "job_manifest.json"),
                "input_sha256": _sha256(job_dir / "input.dat"),
                "grid_sha256": _sha256(job_dir / "grid.dat"),
                "source_xyz_sha256": _sha256(optimized),
                "protocol_version": job["protocol_version"],
                "method": job["method"],
                "basis": job["basis"],
                "grid_point_count": job["grid"]["point_count"],
                "resources": {
                    "slurm_cpus": 16,
                    "psi4_threads": 16,
                    "slurm_memory_gib": 40,
                    "psi4_memory_gib": 36,
                    "walltime": "04:00:00",
                },
            }
            case_path = job_dir.parent / "case_manifest.json"
            case_path.write_text(json.dumps(case, indent=2) + "\n")
            case_hash = _sha256(case_path)
            index = len(records)
            lines.append(f"{index}\t{product_id}\t{case_hash}")
            records.append(
                {
                    "array_index": index,
                    "product_id": product_id,
                    "case_manifest_sha256": case_hash,
                    "grid_point_count": job["grid"]["point_count"],
                }
            )
    if len(records) != 8:
        raise ValueError(
            f"expected all eight ordered TT-CPD products, found {len(records)}"
        )
    (bundle / "cases.tsv").write_text("\n".join(lines) + "\n")
    for name in ("run_case.sh", "campaign_16.sbatch"):
        shutil.copy2(Path(__file__).with_name(name), bundle / name)
    inventory = [
        f"{_sha256(path)}  {path.relative_to(bundle)}"
        for path in sorted(item for item in bundle.rglob("*") if item.is_file())
        if path.name != "MANIFEST.sha256"
    ]
    (bundle / "MANIFEST.sha256").write_text("\n".join(inventory) + "\n")
    archive = output_root / "alpine-boundary-esp-campaign-v1.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(bundle, arcname="bundle")
    (archive.with_suffix(archive.suffix + ".sha256")).write_text(
        f"{_sha256(archive)}  {archive.name}\n"
    )
    report = {
        "schema": "nadoc.photoproduct-alpine-boundary-esp-campaign.v1",
        "status": "built_not_submitted",
        "gate_effect": "none",
        "simulation_ready": False,
        "product_count": len(records),
        "products": records,
        "source_optimization_collections": sources,
        "remote_root": str(REMOTE_ROOT),
        "archive": {"path": str(archive.resolve()), "sha256": _sha256(archive)},
        "interpretation": (
            "Full-boundary ESP evidence for charge transfer validation only; this does "
            "not release product charges, parameters, or NAMD capability."
        ),
    }
    (output_root / "campaign_manifest.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--optimization-campaign", type=Path, action="append", required=True
    )
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                optimization_campaign_roots=args.optimization_campaign,
                output_root=args.output_root.resolve(),
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
