#!/usr/bin/env python3
"""Build idealized-site water curves for all optimized TT-CPD d(TpT) models."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
import tarfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.parameterization.photoproduct_water import (  # noqa: E402
    build_water_probe_series,
)
from scripts.alpine_qm_water_campaign.build_campaign import (  # noqa: E402
    _cross_clash_ratio,
    _sha256,
)


REMOTE_ROOT = Path(
    "/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-boundary-water-v1"
)


def _source(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def build(
    *,
    repository: Path,
    optimization_campaign_roots: list[Path],
    output_root: Path,
) -> dict[str, object]:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite campaign: {output_root}")
    if not optimization_campaign_roots:
        raise ValueError("at least one optimization campaign is required")
    canonical_path = (
        repository / "backend/data/forcefield/photoproducts/tt-cpd-cis-syn/"
        "qm_water_probe_plan_v1.json"
    ).resolve()
    canonical = json.loads(canonical_path.read_text())
    if (
        canonical.get("schema") != "nadoc.photoproduct-water-probe-plan.v1"
        or canonical.get("status") != "reviewed"
        or len(canonical.get("sites") or []) != 6
    ):
        raise ValueError(
            "canonical idealized water-probe plan is not reviewed/complete"
        )

    bundle = output_root / "bundle"
    cases_root = bundle / "cases"
    cases_root.mkdir(parents=True)
    records: list[dict[str, object]] = []
    case_lines: list[str] = []
    sources: list[dict[str, str]] = []
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
        sources.append(_source(collection_path))
        for product in collection.get("products") or []:
            product_id = str(product["product_id"])
            if product_id in seen:
                raise ValueError(f"duplicate optimized product: {product_id}")
            seen.add(product_id)
            source_job = campaign_root / "bundle/cases" / product_id / "job"
            model_xyz = source_job / "optimized.xyz"
            parent = source_job / "optimized_model_audit.json"
            source_job_manifest = source_job / "job_manifest.json"
            job = json.loads(source_job_manifest.read_text())
            audit = json.loads(parent.read_text())
            audit_record = product.get("optimized_model_audit") or {}
            atom_map = job.get("atom_map")
            if (
                audit.get("status") != "passed_identity_and_chirality"
                or audit.get("product_id") != product_id
                or audit.get("optimized_xyz", {}).get("sha256") != _sha256(model_xyz)
                or audit_record.get("sha256") != _sha256(parent)
                or job.get("atom_count") != 63
                or job.get("charge") != -1
                or not isinstance(atom_map, list)
                or len(atom_map) != 63
                or len(set(atom_map)) != 63
            ):
                raise ValueError(
                    f"{product_id}: optimization identity evidence differs"
                )

            case_dir = cases_root / product_id
            case_dir.mkdir(parents=True)
            plan_path = case_dir / "water_probe_plan.json"
            plan = {
                "schema": "nadoc.photoproduct-water-probe-plan.v1",
                "version": "2.0.0-full-dtpdt-transfer",
                "status": "quantitatively_screened",
                "product_id": product_id,
                "model_id": audit["model_id"],
                "charge": -1,
                "multiplicity": 1,
                "reviewed_by": "NADOC exact stable-key protocol transfer",
                "review_rationale": (
                    "The six conventional idealized donor/acceptor identities, local "
                    "covalent axes, plane atoms, and distance grids are transferred by "
                    "exact stable atom key. Coordinates are rebuilt at this product's "
                    "passed full d(TpT) MP2 minimum and independently clash screened."
                ),
                "atom_map": atom_map,
                "sites": copy.deepcopy(canonical["sites"]),
                "probe_variant": "canonical-idealized-full-dtpdt",
                "transfer_provenance": {
                    "source_plan": _source(canonical_path),
                    "optimization_collection": _source(collection_path),
                    "optimized_model_audit": _source(parent),
                    "source_job_manifest": _source(source_job_manifest),
                },
            }
            plan_path.write_text(json.dumps(plan, indent=2) + "\n")
            series_dir = case_dir / "series"
            series = build_water_probe_series(
                plan_path=plan_path,
                model_xyz_path=model_xyz,
                parent_manifest_path=parent,
                output_dir=series_dir,
                memory_gib=6,
                threads=4,
            )
            closest = float("inf")
            for series_job in series["jobs"]:
                job_dir = Path(series_job["job_dir"])
                manifest = json.loads((job_dir / "job_manifest.json").read_text())
                target_index = atom_map.index(manifest["target_atom"])
                closest = min(
                    closest,
                    _cross_clash_ratio(model_xyz, job_dir / "water.xyz", target_index),
                )
            if closest < 0.7:
                raise ValueError(
                    f"{product_id}: idealized probe has severe non-target clash ratio "
                    f"{closest}"
                )
            jobs = sorted(series_dir.glob("*/p*/job_manifest.json"))
            inventory = [
                {
                    "relative_job_dir": str(path.parent.relative_to(case_dir)),
                    "job_manifest_sha256": _sha256(path),
                    "input_sha256": _sha256(path.parent / "input.dat"),
                }
                for path in jobs
            ]
            case_manifest = {
                "schema": "nadoc.photoproduct-alpine-water-case.v1",
                "status": "generated_not_run",
                "gate_effect": "none",
                "simulation_ready": False,
                "product_id": product_id,
                "model_id": audit["model_id"],
                "solute_atom_count": 63,
                "solute_charge": -1,
                "job_count": len(inventory),
                "minimum_non_target_covalent_radius_ratio": closest,
                "source_plan_sha256": _sha256(plan_path),
                "jobs": inventory,
            }
            case_manifest_path = case_dir / "case_manifest.json"
            case_manifest_path.write_text(json.dumps(case_manifest, indent=2) + "\n")
            case_hash = _sha256(case_manifest_path)
            index = len(records)
            case_lines.append(f"{index}\t{product_id}\t{len(inventory)}\t{case_hash}")
            records.append(
                {
                    "array_index": index,
                    "product_id": product_id,
                    "job_count": len(inventory),
                    "minimum_non_target_covalent_radius_ratio": closest,
                    "case_manifest_sha256": case_hash,
                }
            )
    if len(records) != 8:
        raise ValueError(
            f"expected all eight ordered TT-CPD products, found {len(records)}"
        )
    if any(int(item["job_count"]) != 54 for item in records):
        raise ValueError(
            "every product must have six nine-point idealized water curves"
        )
    (bundle / "cases.tsv").write_text("\n".join(case_lines) + "\n")
    shutil.copy2(
        REPOSITORY_ROOT / "scripts/alpine_qm_water_campaign/run_case.sh",
        bundle / "run_case.sh",
    )
    shutil.copy2(Path(__file__).with_name("campaign_64.sbatch"), bundle)
    manifest_lines = [
        f"{_sha256(path)}  {path.relative_to(bundle)}"
        for path in sorted(item for item in bundle.rglob("*") if item.is_file())
        if path.name != "MANIFEST.sha256"
    ]
    (bundle / "MANIFEST.sha256").write_text("\n".join(manifest_lines) + "\n")
    archive = output_root / "alpine-water-campaign-v1.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(bundle, arcname="bundle")
    (archive.with_suffix(archive.suffix + ".sha256")).write_text(
        f"{_sha256(archive)}  {archive.name}\n"
    )
    report = {
        "schema": "nadoc.photoproduct-alpine-water-campaign.v1",
        "status": "built_not_submitted",
        "gate_effect": "none",
        "simulation_ready": False,
        "product_count": len(records),
        "job_count": sum(int(item["job_count"]) for item in records),
        "products": records,
        "probe_variant": "canonical-idealized-full-dtpdt",
        "source_optimization_collections": sources,
        "remote_root": str(REMOTE_ROOT),
        "archive": {"path": str(archive.resolve()), "sha256": _sha256(archive)},
        "interpretation": (
            "Charged full-boundary fixed-geometry water interaction evidence only. "
            "Charge fitting and every simulation release gate remain independent."
        ),
    }
    (output_root / "campaign_manifest.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument(
        "--optimization-campaign", type=Path, action="append", required=True
    )
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                repository=args.repository.resolve(),
                optimization_campaign_roots=args.optimization_campaign,
                output_root=args.output_root.resolve(),
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
