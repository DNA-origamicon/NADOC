#!/usr/bin/env python3
"""Build low-energy TT-CPD conformer single points for Alpine."""

from __future__ import annotations

import argparse
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

from backend.core.photoproduct_chemistry import audit_product_chirality  # noqa: E402
from backend.parameterization.photoproduct_qm import (  # noqa: E402
    generate_psi4_job,
    parse_xyz,
)


PRODUCTS = (
    "tt-cpd-cis-syn",
    "tt-cpd-cis-syn-ii",
    "tt-cpd-trans-syn-i",
    "tt-cpd-trans-syn-ii",
    "tt-cpd-cis-anti-i",
    "tt-cpd-cis-anti-ii",
    "tt-cpd-trans-anti-i",
    "tt-cpd-trans-anti-ii",
)
FRACTIONS = (0.25, 0.5)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checked(record: object, label: str) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{label} is missing")
    path = Path(str(record.get("path") or ""))
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        raise ValueError(f"{label} is missing or hash-mismatched")
    return path.resolve()


def _align(reference: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    reference_centered = reference - np.mean(reference, axis=0)
    candidate_centered = candidate - np.mean(candidate, axis=0)
    left, _singular, right = np.linalg.svd(candidate_centered.T @ reference_centered)
    rotation = left @ right
    if np.linalg.det(rotation) < 0.0:
        left[:, -1] *= -1.0
        rotation = left @ right
    if np.linalg.det(rotation) < 0.999999:
        raise ValueError("proper-rotation alignment failed")
    return candidate_centered @ rotation + np.mean(reference, axis=0)


def _xyz_text(elements: list[str], xyz: np.ndarray, comment: str) -> str:
    return (
        f"{len(elements)}\n{comment}\n"
        + "\n".join(
            f"{element:<2} {point[0]: .12f} {point[1]: .12f} {point[2]: .12f}"
            for element, point in zip(elements, xyz, strict=True)
        )
        + "\n"
    )


def build(*, repository: Path, evidence_root: Path, output_root: Path) -> dict[str, object]:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite campaign: {output_root}")
    atom_map = json.loads(
        (
            repository
            / "backend/data/forcefield/photoproducts/tt-cpd-cis-syn/"
            "qm_water_probe_plan_v1.json"
        ).read_text()
    )["atom_map"]
    bundle = output_root / "bundle"
    cases_root = bundle / "cases"
    cases_root.mkdir(parents=True)
    records = []
    lines = []
    for case_index, product_id in enumerate(PRODUCTS):
        definition_path = (
            repository
            / "backend/data/forcefield/photoproducts"
            / product_id
            / "chemical_definition.json"
        )
        definition = json.loads(definition_path.read_text())
        model_id = ((definition.get("model_compounds") or {}).get("charge_model") or {}).get(
            "id"
        )
        if definition.get("id") != product_id or not model_id:
            raise ValueError(f"{product_id}: chemical definition is invalid")
        minimum_record = definition.get("minimum_geometry_evidence") or {}
        if product_id == "tt-cpd-cis-syn":
            minimum_path = (
                evidence_root / "qm/frequency-v1.4/provenance/source_geometry.xyz"
            )
            if not minimum_path.is_file():
                raise ValueError("cis-syn QM minimum is missing")
        else:
            minimum_path = _checked(
                minimum_record.get("optimized_xyz")
                or minimum_record.get("source_geometry"),
                f"{product_id} QM minimum",
            )
        minimum_atoms, _ = parse_xyz(minimum_path.read_text())
        minimum_mapping = None
        if product_id == "tt-cpd-cis-syn-ii":
            equivalence_path = _checked(
                minimum_record.get("equivalent_hessian_reference"),
                "cis-syn-II endpoint-exchange equivalence",
            )
            equivalence = json.loads(equivalence_path.read_text())
            source_order = equivalence.get("target_atom_map_in_source_matrix_order")
            if (
                equivalence.get("status")
                != "passed_candidate_reuse_preconditions"
                or sorted(source_order or []) != sorted(atom_map)
            ):
                raise ValueError("cis-syn-II endpoint-exchange mapping is invalid")
            source_by_target = dict(zip(source_order, minimum_atoms, strict=True))
            minimum_atoms = [source_by_target[key] for key in atom_map]
            minimum_mapping = {
                "path": str(equivalence_path),
                "sha256": _sha256(equivalence_path),
                "operation": "reorder source coordinates into canonical target atom order",
            }
        elements = [item[0] for item in minimum_atoms]
        reference = np.asarray([item[1:] for item in minimum_atoms], dtype=float)
        if len(reference) != len(atom_map):
            raise ValueError(f"{product_id}: minimum atom count differs")
        source_root = (
            evidence_root / "fit/all-forms/fixed-geometry-qm-v1" / product_id
            if product_id == "tt-cpd-cis-syn"
            else evidence_root
            / "fit/all-forms/fixed-geometry-qm-v2.1.0"
            / product_id
        )
        case_dir = cases_root / product_id
        jobs = []
        geometries = [("minimum", reference, {"kind": "QM minimum"})]
        for conformer_index in range(1, 5):
            job_manifest_path = (
                source_root
                / f"conformer-{conformer_index:03d}"
                / "job/job_manifest.json"
            )
            job_manifest = json.loads(job_manifest_path.read_text())
            source_path = _checked(
                job_manifest.get("source_xyz"),
                f"{product_id} conformer {conformer_index}",
            )
            source_atoms, _ = parse_xyz(source_path.read_text())
            if [item[0] for item in source_atoms] != elements:
                raise ValueError(f"{product_id}: conformer atom order differs")
            aligned = _align(
                reference, np.asarray([item[1:] for item in source_atoms], dtype=float)
            )
            for fraction in FRACTIONS:
                geometries.append(
                    (
                        f"conformer-{conformer_index:03d}-f{int(100*fraction):03d}",
                        reference + fraction * (aligned - reference),
                        {
                            "kind": "proper-rotation interpolation",
                            "source_conformer": {
                                "path": str(source_path),
                                "sha256": _sha256(source_path),
                            },
                            "fraction": fraction,
                        },
                    )
                )
        for point_id, xyz, provenance in geometries:
            point_dir = case_dir / "points" / point_id
            point_dir.mkdir(parents=True)
            xyz_path = point_dir / "geometry.xyz"
            xyz_path.write_text(
                _xyz_text(
                    elements,
                    xyz,
                    f"{product_id} {point_id}; no reflection; gate-neutral",
                )
            )
            coordinates = {
                key: xyz[index].tolist() for index, key in enumerate(atom_map)
            }
            chirality = audit_product_chirality(definition, coordinates)
            if not chirality["passed"]:
                raise ValueError(f"{product_id} {point_id}: chirality changed")
            manifest = generate_psi4_job(
                product_id=product_id,
                model_id=model_id,
                xyz_path=xyz_path,
                output_dir=point_dir,
                job_kind="conformer_single_point",
                charge=0,
                multiplicity=1,
                atom_map=atom_map,
                memory_gib=10,
                threads=8,
            )
            jobs.append(
                {
                    "point_id": point_id,
                    "relative_job_dir": str(point_dir.relative_to(case_dir)),
                    "job_manifest_sha256": _sha256(point_dir / "job_manifest.json"),
                    "input_sha256": _sha256(point_dir / "input.dat"),
                    "geometry_sha256": _sha256(xyz_path),
                    "geometry_provenance": provenance,
                    "chirality_audit": chirality,
                    "protocol_version": manifest["protocol_version"],
                    "method": manifest["method"],
                    "basis": manifest["basis"],
                }
            )
        case_manifest = {
            "schema": "nadoc.photoproduct-alpine-relative-energy-case.v1",
            "status": "generated_not_run",
            "gate_effect": "none",
            "simulation_ready": False,
            "product_id": product_id,
            "model_id": model_id,
            "job_count": len(jobs),
            "atom_map": atom_map,
            "qm_minimum": {
                "path": str(minimum_path.resolve()),
                "sha256": _sha256(minimum_path),
                "stable_atom_mapping": minimum_mapping,
            },
            "chemical_definition": {
                "path": str(definition_path.resolve()),
                "sha256": _sha256(definition_path),
            },
            "jobs": jobs,
        }
        case_manifest_path = case_dir / "case_manifest.json"
        case_manifest_path.write_text(json.dumps(case_manifest, indent=2) + "\n")
        case_hash = _sha256(case_manifest_path)
        lines.append(f"{case_index}\t{product_id}\t{len(jobs)}\t{case_hash}")
        records.append(
            {"product_id": product_id, "job_count": len(jobs), "case_manifest_sha256": case_hash}
        )
    (bundle / "cases.tsv").write_text("\n".join(lines) + "\n")
    for name in ("run_case.sh", "campaign_64.sbatch"):
        shutil.copy2(Path(__file__).with_name(name), bundle / name)
    inventory = []
    for path in sorted(item for item in bundle.rglob("*") if item.is_file()):
        if path.name != "MANIFEST.sha256":
            inventory.append(f"{_sha256(path)}  {path.relative_to(bundle)}")
    (bundle / "MANIFEST.sha256").write_text("\n".join(inventory) + "\n")
    archive = output_root / "alpine-relative-energy-campaign-v1.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(bundle, arcname="bundle")
    (archive.with_suffix(archive.suffix + ".sha256")).write_text(
        f"{_sha256(archive)}  {archive.name}\n"
    )
    report = {
        "schema": "nadoc.photoproduct-alpine-relative-energy-campaign.v1",
        "status": "built_not_submitted",
        "gate_effect": "none",
        "simulation_ready": False,
        "product_count": len(records),
        "job_count": sum(item["job_count"] for item in records),
        "products": records,
        "fractions": list(FRACTIONS),
        "archive": {"path": str(archive.resolve()), "sha256": _sha256(archive)},
        "interpretation": (
            "Low-energy relative conformer targets only; no fit or force-field release."
        ),
    }
    (output_root / "campaign_manifest.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                repository=args.repository.resolve(),
                evidence_root=args.evidence_root.resolve(),
                output_root=args.output_root.resolve(),
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
