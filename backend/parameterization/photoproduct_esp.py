"""Deterministic, hash-audited electrostatic-potential targets for charge fitting."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from backend.parameterization.photoproduct_qm import (
    QM_PROTOCOL_PATH,
    parse_xyz,
    qm_protocol,
)

_BONDI_RADII_ANGSTROM = {"H": 1.20, "C": 1.70, "N": 1.55, "O": 1.52}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_esp_grid(
    atoms: Sequence[tuple[str, float, float, float]],
    *,
    radius_scales: Sequence[float],
    directions_per_atom: int,
) -> list[list[float]]:
    """Build multi-shell Fibonacci points and remove points buried by another atom."""

    if directions_per_atom < 12 or not radius_scales:
        raise ValueError("ESP grid requires at least 12 directions and one radius scale")
    elements = [item[0].upper() for item in atoms]
    unsupported = sorted(set(elements) - set(_BONDI_RADII_ANGSTROM))
    if unsupported:
        raise ValueError("ESP Bondi radii are unavailable for: " + ", ".join(unsupported))
    coordinates = np.asarray([item[1:] for item in atoms], dtype=float)
    golden_angle = math.pi * (3.0 - math.sqrt(5.0))
    points: dict[tuple[float, float, float], list[float]] = {}
    for scale in radius_scales:
        if scale <= 1.0:
            raise ValueError("ESP surface radius scales must be greater than 1")
        scaled_radii = np.asarray(
            [scale * _BONDI_RADII_ANGSTROM[element] for element in elements]
        )
        for atom_index, center in enumerate(coordinates):
            radius = scaled_radii[atom_index]
            for direction_index in range(directions_per_atom):
                z = 1.0 - 2.0 * (direction_index + 0.5) / directions_per_atom
                radial = math.sqrt(max(0.0, 1.0 - z * z))
                azimuth = golden_angle * direction_index
                direction = np.asarray(
                    [radial * math.cos(azimuth), radial * math.sin(azimuth), z]
                )
                point = center + radius * direction
                distances = np.linalg.norm(coordinates - point, axis=1)
                buried = any(
                    index != atom_index and distances[index] < scaled_radii[index] - 1e-9
                    for index in range(len(atoms))
                )
                if not buried:
                    key = tuple(round(float(value), 8) for value in point)
                    points[key] = [float(value) for value in point]
    if len(points) < len(atoms) * 4:
        raise ValueError("ESP surface filtering left too few points")
    return [points[key] for key in sorted(points)]


def generate_esp_job(
    *,
    product_id: str,
    model_id: str,
    xyz_path: Path,
    atom_map: Sequence[str],
    parent_manifest_path: Path,
    output_dir: Path,
    charge: int = 0,
    multiplicity: int = 1,
    memory_gib: int = 4,
    threads: int = 4,
    protocol_path: Path = QM_PROTOCOL_PATH,
) -> dict[str, Any]:
    """Generate a Psi4 GRID_ESP job from a passed optimized geometry."""

    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite ESP job: {output_dir}")
    protocol = qm_protocol(protocol_path)
    settings = protocol["jobs"]["electrostatic_potential"]
    xyz_bytes = xyz_path.read_bytes()
    atoms, comment = parse_xyz(xyz_bytes.decode())
    if len(atom_map) != len(atoms) or len(atom_map) != len(set(atom_map)):
        raise ValueError("unique stable atom map must match the ESP model")
    parent = json.loads(parent_manifest_path.read_text())
    accepted_parent_statuses = {
        "passed_identity_and_chirality",
        "passed_candidate_identity_and_chirality",
    }
    if (
        parent.get("schema") != "nadoc.photoproduct-optimized-model-audit.v1"
        or parent.get("status") not in accepted_parent_statuses
        or parent.get("product_id") != product_id
        or parent.get("model_id") != model_id
        or parent.get("optimized_xyz", {}).get("sha256") != hashlib.sha256(xyz_bytes).hexdigest()
    ):
        raise ValueError("ESP parent is not a passed matching optimized-model audit")
    grid = build_esp_grid(
        atoms,
        radius_scales=settings["surface_radius_scales"],
        directions_per_atom=settings["directions_per_atom_per_surface"],
    )
    output_dir.mkdir(parents=True)
    grid_path = output_dir / "grid.dat"
    grid_path.write_text(
        "\n".join(" ".join(f"{value:.10f}" for value in point) for point in grid) + "\n"
    )
    coordinates = "\n".join(
        f"  {element:<2} {x: .12f} {y: .12f} {z: .12f}"
        for element, x, y, z in atoms
    )
    basis = (
        protocol["rules"]["charged_model_diffuse_basis"]
        if charge
        else settings["basis"]
    )
    properties = list(settings.get("properties") or ["GRID_ESP"])
    unsupported_properties = sorted(set(properties) - {"GRID_ESP", "DIPOLE"})
    if "GRID_ESP" not in properties or unsupported_properties:
        raise ValueError(
            "ESP protocol properties must contain GRID_ESP and may additionally "
            f"contain DIPOLE; unsupported={unsupported_properties}"
        )
    oeprop_arguments = ", ".join(repr(item) for item in properties)
    dipole_operation = ""
    if "DIPOLE" in properties:
        dipole_operation = (
            "\ndipole = wavefunction.variable('DIPOLE')\n"
            "print_out('NADOC_DIPOLE_AU %.12f %.12f %.12f\\n' % "
            "(dipole[0], dipole[1], dipole[2]))"
        )
    rendered = f'''# NADOC photoproduct ESP protocol {protocol["version"]}
# Source XYZ comment: {comment}
memory {memory_gib} GB
set_num_threads({threads})

molecule model {{
  {charge} {multiplicity}
{coordinates}
  units angstrom
  no_com
  no_reorient
}}

set {{
  basis {basis}
  reference {"rhf" if multiplicity == 1 else "uhf"}
  scf_type {settings["scf_type"]}
}}

energy, wavefunction = energy('{settings["method"]}', return_wfn=True)
oeprop(wavefunction, {oeprop_arguments}){dipole_operation}
'''
    input_path = output_dir / "input.dat"
    input_path.write_text(rendered)
    manifest = {
        "schema": "nadoc.photoproduct-qm-job.v1",
        "status": "generated_not_run",
        "gate_effect": "none",
        "product_id": product_id,
        "model_id": model_id,
        "job_kind": "electrostatic_potential",
        "method": settings["method"],
        "basis": basis,
        "charge": charge,
        "multiplicity": multiplicity,
        "atom_count": len(atoms),
        "atom_map": list(atom_map),
        "memory_gib": memory_gib,
        "threads": threads,
        "protocol_version": protocol["version"],
        "protocol_sha256": _sha256(protocol_path),
        "source_xyz": {"path": str(xyz_path.resolve()), "sha256": _sha256(xyz_path)},
        "parent_manifest": {
            "path": str(parent_manifest_path.resolve()),
            "sha256": _sha256(parent_manifest_path),
            "evidence_status": parent["status"],
        },
        "grid": {
            "path": str(grid_path.resolve()),
            "sha256": _sha256(grid_path),
            "point_count": len(grid),
            "coordinate_units": settings["grid_units"],
            "radius_scales": settings["surface_radius_scales"],
            "directions_per_atom_per_surface": settings[
                "directions_per_atom_per_surface"
            ],
            "buried_point_rule": "remove if inside any other atom at the same scaled Bondi radius",
        },
        "input": {"path": str(input_path.resolve()), "sha256": _sha256(input_path)},
        "expected_outputs": ["output.dat", "grid_esp.dat"],
        "potential_units": settings["potential_units"],
        "properties": properties,
        "dipole_units": (
            settings.get("dipole_units") if "DIPOLE" in properties else None
        ),
    }
    (output_dir / "job_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def audit_esp_job(job_dir: Path) -> dict[str, Any]:
    """Verify raw GRID_ESP values and their complete provenance chain."""

    job_path = job_dir / "job_manifest.json"
    run_path = job_dir / "run_manifest.json"
    values_path = job_dir / "grid_esp.dat"
    grid_path = job_dir / "grid.dat"
    output_path = job_dir / "output.dat"
    if not all(
        path.is_file()
        for path in (job_path, run_path, values_path, grid_path, output_path)
    ):
        raise ValueError("ESP job, run, grid, and potential files are required")
    job = json.loads(job_path.read_text())
    run = json.loads(run_path.read_text())
    if (
        job.get("job_kind") != "electrostatic_potential"
        or run.get("status") != "completed_unreviewed"
        or run.get("job_manifest_sha256") != _sha256(job_path)
        or job.get("grid", {}).get("sha256") != _sha256(grid_path)
        or run.get("outputs", {}).get("grid_esp.dat", {}).get("sha256")
        != _sha256(values_path)
        or run.get("outputs", {}).get("output.dat", {}).get("sha256")
        != _sha256(output_path)
    ):
        raise ValueError("ESP execution or evidence hashes do not match")
    grid = np.loadtxt(grid_path, ndmin=2)
    values = np.loadtxt(values_path, ndmin=1)
    if values.ndim > 1:
        values = values[:, -1]
    point_count = int(job["grid"]["point_count"])
    properties = list(job.get("properties") or ["GRID_ESP"])
    dipole_required = "DIPOLE" in properties
    dipole_matches = re.findall(
        r"^\s*NADOC_DIPOLE_AU\s+"
        r"(-?\d+\.\d+(?:[Ee][+-]?\d+)?)\s+"
        r"(-?\d+\.\d+(?:[Ee][+-]?\d+)?)\s+"
        r"(-?\d+\.\d+(?:[Ee][+-]?\d+)?)\s*$",
        output_path.read_text(errors="replace"),
        flags=re.MULTILINE,
    )
    dipole = [float(value) for value in dipole_matches[-1]] if dipole_matches else None
    dipole_valid = dipole is not None and all(math.isfinite(value) for value in dipole)
    passed = (
        grid.shape == (point_count, 3)
        and values.shape == (point_count,)
        and bool(np.all(np.isfinite(values)))
        and (not dipole_required or dipole_valid)
    )
    report = {
        "schema": "nadoc.photoproduct-esp-audit.v1",
        "status": "complete_candidate" if passed else "failed",
        "passed": passed,
        "gate_effect": "none",
        "product_id": job["product_id"],
        "model_id": job["model_id"],
        "point_count": point_count,
        "potential_units": job["potential_units"],
        "properties": properties,
        "dipole": {
            "required": dipole_required,
            "vector": dipole,
            "units": job.get("dipole_units"),
            "magnitude": (
                math.sqrt(sum(value * value for value in dipole)) if dipole_valid else None
            ),
        },
        "minimum_potential": float(np.min(values)) if values.size else None,
        "maximum_potential": float(np.max(values)) if values.size else None,
        "grid": {"path": str(grid_path.resolve()), "sha256": _sha256(grid_path)},
        "potentials": {
            "path": str(values_path.resolve()),
            "sha256": _sha256(values_path),
        },
        "job_manifest": {"path": str(job_path.resolve()), "sha256": _sha256(job_path)},
        "release_note": "ESP is one charge-fit target and does not advance a gate by itself.",
    }
    report_path = job_dir / "esp_audit.json"
    if report_path.exists():
        raise FileExistsError(f"refusing to overwrite ESP audit: {report_path}")
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
