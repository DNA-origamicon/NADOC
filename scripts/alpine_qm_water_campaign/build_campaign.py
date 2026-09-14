#!/usr/bin/env python3
"""Build the all-noncanonical TT-CPD water-probe Alpine campaign.

The six canonical donor/acceptor site definitions are transferred by exact stable
atom key from the reviewed cis-syn-I plan.  Product-specific probe coordinates are
then generated from each product's passed QM minimum.  This script deliberately
does not fit or release charges.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
import tarfile
from pathlib import Path

import numpy as np

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.parameterization.photoproduct_qm import parse_xyz
from backend.parameterization.photoproduct_water import build_water_probe_series


PRODUCTS = (
    "tt-cpd-trans-syn-i",
    "tt-cpd-trans-syn-ii",
    "tt-cpd-cis-anti-i",
    "tt-cpd-cis-anti-ii",
    "tt-cpd-trans-anti-i",
    "tt-cpd-trans-anti-ii",
)

_RADII = {"H": 0.31, "C": 0.76, "N": 0.71, "O": 0.66}


def _alternate_plane_sites(sites: list[dict[str, object]]) -> list[dict[str, object]]:
    result = copy.deepcopy(sites)
    alternate_local = {
        "o2-acceptor": "N3",
        "o4-acceptor": "C5",
        "h3-donor": "C4",
    }
    for site in result:
        endpoint, site_kind = str(site["id"]).split("-", 1)
        endpoint_number = endpoint.removeprefix("endpoint")
        site["id"] = f"{site['id']}-alt-plane"
        site["plane_atom"] = f"{endpoint_number}:{alternate_local[site_kind]}"
    return result


def _azimuth_rotated_sites(
    sites: list[dict[str, object]], *, azimuth_degrees: float
) -> list[dict[str, object]]:
    result = copy.deepcopy(sites)
    suffix = f"azimuth-{int(azimuth_degrees):+04d}"
    for site in result:
        site["id"] = f"{site['id']}-{suffix}"
        site["azimuth_degrees"] = float(azimuth_degrees)
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checked(record: object, label: str) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{label} is missing")
    path = Path(str(record.get("path") or ""))
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        raise ValueError(f"{label} is missing or hash-mismatched")
    return path.resolve()


def _cross_clash_ratio(model_xyz: Path, water_xyz: Path, target_index: int) -> float:
    model_atoms, _ = parse_xyz(model_xyz.read_text())
    water_atoms, _ = parse_xyz(water_xyz.read_text())
    closest = float("inf")
    for model_i, (model_element, mx, my, mz) in enumerate(model_atoms):
        for water_i, (water_element, wx, wy, wz) in enumerate(water_atoms):
            # The intended target/probe contact is not a steric clash.  Excluding all
            # three target-water pairs is conservative for donor and acceptor sites;
            # every other solute-water pair remains screened.
            if model_i == target_index:
                continue
            distance = float(np.linalg.norm([mx - wx, my - wy, mz - wz]))
            ratio = distance / (_RADII[model_element] + _RADII[water_element])
            closest = min(closest, ratio)
    return closest


def build(
    *, repository: Path, output_root: Path, probe_variant: str = "canonical"
) -> dict[str, object]:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite campaign: {output_root}")
    canonical_path = (
        repository
        / "backend/data/forcefield/photoproducts/tt-cpd-cis-syn/"
        "qm_water_probe_plan_v1.json"
    )
    canonical = json.loads(canonical_path.read_text())
    if (
        canonical.get("schema") != "nadoc.photoproduct-water-probe-plan.v1"
        or canonical.get("status") != "reviewed"
        or len(canonical.get("sites") or []) != 6
    ):
        raise ValueError("canonical cis-syn water-probe plan is not reviewed/complete")
    if probe_variant not in {"canonical", "alternate-plane", "azimuth-120"}:
        raise ValueError("unsupported water-probe campaign variant")
    site_template = copy.deepcopy(canonical["sites"])
    if probe_variant == "alternate-plane":
        site_template = _alternate_plane_sites(site_template)
    elif probe_variant == "azimuth-120":
        site_template = _azimuth_rotated_sites(
            site_template, azimuth_degrees=120.0
        )

    # cis-syn-II is the exact ordered-endpoint exchange partner of cis-syn-I in this
    # symmetric neutral model and already has a hash-audited equivalence mapping.  A
    # duplicate water calculation would not add an independent electronic target.

    bundle = output_root / "bundle"
    cases_root = bundle / "cases"
    cases_root.mkdir(parents=True)
    records: list[dict[str, object]] = []
    case_lines = []
    for index, product_id in enumerate(PRODUCTS):
        product_dir = (
            repository / "backend/data/forcefield/photoproducts" / product_id
        )
        definition_path = product_dir / "chemical_definition.json"
        review_path = product_dir / "chemical_definition_review_audit.json"
        definition = json.loads(definition_path.read_text())
        review = json.loads(review_path.read_text())
        model_id = ((definition.get("model_compounds") or {}).get("charge_model") or {}).get(
            "id"
        )
        if (
            definition.get("schema")
            != "nadoc.photoproduct-chemical-definition.v1"
            or definition.get("id") != product_id
            or not model_id
            or review.get("status") != "passed_review_ingestion"
            or review.get("passed") is not True
            or product_id not in (review.get("approved_product_ids") or [])
        ):
            raise ValueError(f"{product_id}: chemical definition review is not passed")
        minimum = definition.get("minimum_geometry_evidence") or {}
        model_xyz = _checked(minimum.get("optimized_xyz"), f"{product_id} QM minimum")
        parent = _checked(
            minimum.get("optimized_model_audit"), f"{product_id} optimized-model audit"
        )

        case_dir = cases_root / product_id
        plan_path = case_dir / "water_probe_plan.json"
        case_dir.mkdir(parents=True)
        plan = {
            **canonical,
            "version": (
                "1.2.0-alternate-plane-validation"
                if probe_variant == "alternate-plane"
                else (
                    "1.3.0-azimuth-120-validation"
                    if probe_variant == "azimuth-120"
                    else "1.1.0-transfer"
                )
            ),
            "status": (
                "quantitatively_screened"
                if probe_variant in {"alternate-plane", "azimuth-120"}
                else canonical["status"]
            ),
            "product_id": product_id,
            "model_id": model_id,
            "reviewed_by": "NADOC exact stable-key protocol transfer",
            "review_rationale": (
                "The six donor/acceptor identities, local covalent axes, plane atoms, "
                "and distance grid are transferred unchanged from the reviewed cis-syn-I "
                "plan because every product has the same ordered stable atom map. Probe "
                "coordinates are rebuilt from this product's hash-pinned passed QM minimum."
            ),
            "sites": copy.deepcopy(site_template),
            "probe_variant": probe_variant,
            "transfer_provenance": {
                "source_plan": {
                    "path": str(canonical_path.resolve()),
                    "sha256": _sha256(canonical_path),
                },
                "chemical_definition": {
                    "path": str(definition_path.resolve()),
                    "sha256": _sha256(definition_path),
                },
                "chemical_definition_review": {
                    "path": str(review_path.resolve()),
                    "sha256": _sha256(review_path),
                },
            },
        }
        plan_path.write_text(json.dumps(plan, indent=2) + "\n")
        series_dir = case_dir / "series"
        series = build_water_probe_series(
            plan_path=plan_path,
            model_xyz_path=model_xyz,
            parent_manifest_path=parent,
            output_dir=series_dir,
            memory_gib=3,
            threads=4,
        )
        closest = float("inf")
        for job in series["jobs"]:
            job_dir = Path(job["job_dir"])
            manifest = json.loads((job_dir / "job_manifest.json").read_text())
            target_index = canonical["atom_map"].index(manifest["target_atom"])
            closest = min(
                closest,
                _cross_clash_ratio(model_xyz, job_dir / "water.xyz", target_index),
            )
        if closest < 0.7:
            raise ValueError(
                f"{product_id}: generated probe has severe non-target clash ratio {closest}"
            )
        # Absolute local paths are provenance for the source tree, but the Alpine runner
        # consumes the self-contained input files.  Record an immutable case inventory.
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
            "model_id": model_id,
            "job_count": len(inventory),
            "minimum_non_target_covalent_radius_ratio": closest,
            "source_plan_sha256": _sha256(plan_path),
            "jobs": inventory,
        }
        case_manifest_path = case_dir / "case_manifest.json"
        case_manifest_path.write_text(json.dumps(case_manifest, indent=2) + "\n")
        case_lines.append(
            f"{index}\t{product_id}\t{len(inventory)}\t{_sha256(case_manifest_path)}"
        )
        records.append(
            {
                "product_id": product_id,
                "job_count": len(inventory),
                "minimum_non_target_covalent_radius_ratio": closest,
                "case_manifest_sha256": _sha256(case_manifest_path),
            }
        )

    (bundle / "cases.tsv").write_text("\n".join(case_lines) + "\n")
    for name in ("run_case.sh", "campaign_64.sbatch"):
        shutil.copy2(Path(__file__).with_name(name), bundle / name)
    manifest_lines = []
    for path in sorted(item for item in bundle.rglob("*") if item.is_file()):
        if path.name == "MANIFEST.sha256":
            continue
        manifest_lines.append(f"{_sha256(path)}  {path.relative_to(bundle)}")
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
        "probe_variant": probe_variant,
        "archive": {"path": str(archive.resolve()), "sha256": _sha256(archive)},
        "interpretation": (
            "Generated fixed-geometry water interaction evidence only. Charge fitting, "
            "held-out evaluation, and all release gates remain independent."
        ),
    }
    (output_root / "campaign_manifest.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--probe-variant",
        choices=("canonical", "alternate-plane", "azimuth-120"),
        default="canonical",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                repository=args.repository.resolve(),
                output_root=args.output_root.resolve(),
                probe_variant=args.probe_variant,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
