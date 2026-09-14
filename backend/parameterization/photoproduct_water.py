"""Deterministic, reviewed CHARMM water-probe geometry series."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from backend.parameterization.photoproduct_qm import (
    generate_water_interaction_job,
    parse_xyz,
)

_OH_ANGSTROM = 0.9572
_HOH_DEGREES = 104.52


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unit(vector: np.ndarray, *, label: str) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    if length <= 1e-8:
        raise ValueError(f"water probe {label} vector is degenerate")
    return vector / length


def _probe_plane_direction(
    target: np.ndarray, axis: np.ndarray, plane_point: np.ndarray
) -> np.ndarray:
    candidate = plane_point - target
    perpendicular = candidate - float(np.dot(candidate, axis)) * axis
    return _unit(perpendicular, label="plane")


def place_tip3p_probe(
    *,
    target: Sequence[float],
    axis_anchor: Sequence[float],
    plane_point: Sequence[float],
    role: str,
    distance_angstrom: float,
    azimuth_degrees: float = 0.0,
) -> tuple[list[tuple[str, float, float, float]], str]:
    """Place CHARMM TIP3P along one explicitly defined interaction direction."""

    if role not in {"acceptor", "donor"}:
        raise ValueError("water probe role must be acceptor or donor")
    if not 1.3 <= float(distance_angstrom) <= 4.0:
        raise ValueError("water probe distance must be in [1.3, 4.0] angstrom")
    target_v = np.asarray(target, dtype=float)
    anchor_v = np.asarray(axis_anchor, dtype=float)
    plane_v = np.asarray(plane_point, dtype=float)
    if not all(np.isfinite(item).all() for item in (target_v, anchor_v, plane_v)):
        raise ValueError("water probe reference coordinates must be finite")
    axis = _unit(target_v - anchor_v, label="axis")
    perpendicular = _probe_plane_direction(target_v, axis, plane_v)
    if not math.isfinite(float(azimuth_degrees)) or not -360.0 <= float(
        azimuth_degrees
    ) <= 360.0:
        raise ValueError("water probe azimuth must be finite and in [-360, 360]")
    azimuth = math.radians(float(azimuth_degrees))
    orthogonal = _unit(np.cross(axis, perpendicular), label="azimuth")
    perpendicular = (
        math.cos(azimuth) * perpendicular + math.sin(azimuth) * orthogonal
    )
    angle = math.radians(_HOH_DEGREES)
    if role == "acceptor":
        # H1 points at the acceptor; the oxygen lies farther along the carbonyl axis.
        h1 = target_v + float(distance_angstrom) * axis
        oxygen = h1 + _OH_ANGSTROM * axis
        oh1 = -axis
        oh2 = math.cos(angle) * oh1 + math.sin(angle) * perpendicular
        h2 = oxygen + _OH_ANGSTROM * oh2
        probe_atom = "H1"
    else:
        # Water oxygen accepts from the donor H; both O-H bonds point away from it.
        oxygen = target_v + float(distance_angstrom) * axis
        half = angle / 2.0
        h1 = oxygen + _OH_ANGSTROM * (
            math.cos(half) * axis + math.sin(half) * perpendicular
        )
        h2 = oxygen + _OH_ANGSTROM * (
            math.cos(half) * axis - math.sin(half) * perpendicular
        )
        probe_atom = "O"
    atoms = [("O", *oxygen), ("H", *h1), ("H", *h2)]
    return [
        (element, float(x), float(y), float(z)) for element, x, y, z in atoms
    ], probe_atom


def build_water_probe_series(
    *,
    plan_path: Path,
    model_xyz_path: Path,
    parent_manifest_path: Path,
    output_dir: Path,
    memory_gib: int = 4,
    threads: int = 4,
) -> dict[str, Any]:
    """Generate jobs from a reviewed or deterministic screened water-probe plan."""

    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite water-probe series: {output_dir}")
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    if plan.get("schema") != "nadoc.photoproduct-water-probe-plan.v1":
        raise ValueError("unsupported water-probe plan schema")
    if plan.get("status") not in {"reviewed", "quantitatively_screened"}:
        raise ValueError(
            "water-probe plan must be reviewed or quantitatively screened"
        )
    for field in (
        "product_id",
        "model_id",
        "reviewed_by",
        "review_rationale",
        "atom_map",
        "sites",
    ):
        if not plan.get(field):
            raise ValueError(f"water-probe plan is missing {field}")
    model_atoms, _comment = parse_xyz(model_xyz_path.read_text())
    atom_map = plan["atom_map"]
    if (
        not isinstance(atom_map, list)
        or len(atom_map) != len(model_atoms)
        or len(atom_map) != len(set(atom_map))
    ):
        raise ValueError("water-probe atom_map must uniquely match the model XYZ")
    coordinates = {
        key: np.asarray((x, y, z), dtype=float)
        for key, (_element, x, y, z) in zip(atom_map, model_atoms, strict=True)
    }
    parent = json.loads(parent_manifest_path.read_text())
    accepted_parent_statuses = {
        "passed_identity_and_chirality",
        "passed_candidate_identity_and_chirality",
    }
    if (
        parent.get("schema") != "nadoc.photoproduct-optimized-model-audit.v1"
        or parent.get("status") not in accepted_parent_statuses
        or parent.get("product_id") != plan["product_id"]
        or parent.get("model_id") != plan["model_id"]
        or parent.get("optimized_xyz", {}).get("sha256") != _sha256(model_xyz_path)
    ):
        raise ValueError("water-probe parent is not a passed matching optimized model")
    site_ids = [site.get("id") for site in plan["sites"]]
    if len(site_ids) != len(set(site_ids)):
        raise ValueError("water-probe site IDs must be unique")
    output_dir.mkdir(parents=True)
    jobs: list[dict[str, Any]] = []
    for site in plan["sites"]:
        site_id = site.get("id")
        role = site.get("role")
        keys = [
            site.get("target_atom"),
            site.get("axis_anchor_atom"),
            site.get("plane_atom"),
        ]
        if (
            not isinstance(site_id, str)
            or not site_id
            or any(key not in coordinates for key in keys)
        ):
            raise ValueError(f"water-probe site {site_id!r} has unresolved atom keys")
        distances = site.get("distances_angstrom")
        if (
            not isinstance(distances, list)
            or len(distances) < 5
            or distances != sorted(set(distances))
            or max(distances) - min(distances) < 0.8 - 1e-9
            or max(second - first for first, second in zip(distances, distances[1:]))
            > 0.25 + 1e-9
        ):
            raise ValueError(
                f"water-probe site {site_id!r} needs >=5 sorted unique points, "
                ">=0.8 angstrom span, and <=0.25 angstrom spacing"
            )
        for index, distance in enumerate(distances):
            atoms, probe_atom = place_tip3p_probe(
                target=coordinates[keys[0]],
                axis_anchor=coordinates[keys[1]],
                plane_point=coordinates[keys[2]],
                role=role,
                distance_angstrom=float(distance),
                azimuth_degrees=float(site.get("azimuth_degrees", 0.0)),
            )
            point_id = f"p{index:02d}-{float(distance):.3f}A"
            point_dir = output_dir / site_id / point_id
            point_dir.mkdir(parents=True)
            water_path = point_dir / "water.xyz"
            water_path.write_text(
                "3\n"
                f"{site_id} {role} target-probe {float(distance):.6f} angstrom\n"
                + "\n".join(
                    f"{element} {x:.12f} {y:.12f} {z:.12f}"
                    for element, x, y, z in atoms
                )
                + "\n"
            )
            manifest = generate_water_interaction_job(
                product_id=plan["product_id"],
                model_id=plan["model_id"],
                model_xyz_path=model_xyz_path,
                water_xyz_path=water_path,
                parent_manifest_path=parent_manifest_path,
                atom_map=atom_map,
                probe_id=site_id,
                target_atom=keys[0],
                probe_atom=probe_atom,
                output_dir=point_dir,
                charge=int(plan.get("charge", 0)),
                multiplicity=int(plan.get("multiplicity", 1)),
                memory_gib=memory_gib,
                threads=threads,
            )
            jobs.append(
                {
                    "site_id": site_id,
                    "point_id": point_id,
                    "distance_angstrom": float(distance),
                    "job_dir": str(point_dir.resolve()),
                    "job_manifest_sha256": hashlib.sha256(
                        json.dumps(manifest, indent=2).encode() + b"\n"
                    ).hexdigest(),
                }
            )
    series = {
        "schema": "nadoc.photoproduct-water-probe-series.v1",
        "status": "generated_not_run",
        "gate_effect": "none",
        "geometry_evidence_status": parent.get("status"),
        "product_id": plan["product_id"],
        "model_id": plan["model_id"],
        "plan": {
            "path": str(plan_path.resolve()),
            "sha256": hashlib.sha256(plan_bytes).hexdigest(),
        },
        "model_xyz": {
            "path": str(model_xyz_path.resolve()),
            "sha256": _sha256(model_xyz_path),
        },
        "parent_manifest": {
            "path": str(parent_manifest_path.resolve()),
            "sha256": _sha256(parent_manifest_path),
        },
        "jobs": jobs,
    }
    (output_dir / "series_manifest.json").write_text(
        json.dumps(series, indent=2) + "\n"
    )
    return series
