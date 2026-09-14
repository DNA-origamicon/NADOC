"""Prepare a conservative, hash-linked NAMD smoke sequence for released lesions."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

import numpy as np

from backend.core.cpd_forcefield import (
    packaged_photoproduct_manifest,
    packaged_photoproduct_parameter_directives,
)
from backend.core.dcd_fast import read_frame, read_layout
from backend.core.namd_topology import charmm_atom_name
from backend.core.photoproduct_chemistry import (
    audit_product_chirality,
    load_chemical_definition,
)
from backend.core.photoproduct_psf_audit import parse_psf_atoms
from backend.core.photoproduct_registry import photoproduct_registry


_CONTROL_RE = re.compile(
    r"^\s*(?:outputName|outputEnergies|dcdFreq|dcdFile|xstFreq|xstFile|"
    r"restartfreq|binaryrestart|minimize|run|temperature|langevinTemp|"
    r"rigidBonds|timestep|coordinates|binCoordinates|binVelocities|"
    r"extendedSystem|fixedAtoms|fixedAtomsFile|fixedAtomsCol)\b",
    re.IGNORECASE,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _positive_cycle_count(value: int, name: str) -> int:
    if value < 10 or value % 10:
        raise ValueError(f"{name} must be a positive multiple of 10")
    return value


def _pdb_records(path: Path) -> tuple[list[str], list[int], np.ndarray]:
    lines = path.read_text().splitlines()
    indices = [
        index
        for index, line in enumerate(lines)
        if line.startswith("ATOM  ") or line.startswith("HETATM")
    ]
    coordinates = []
    for index in indices:
        line = lines[index]
        try:
            coordinates.append(
                [float(line[30:38]), float(line[38:46]), float(line[46:54])]
            )
        except ValueError as exc:
            raise ValueError(f"malformed PDB coordinates at line {index + 1}") from exc
    return lines, indices, np.asarray(coordinates, dtype=float)


def _write_local_fixed_mask(
    *,
    pdb_path: Path,
    psf_path: Path,
    lesions: list[dict[str, Any]],
    output_path: Path,
    mobile_radius_angstrom: float,
) -> dict[str, Any]:
    psf_atoms = parse_psf_atoms(psf_path.read_text(errors="replace"))
    lines, pdb_line_indices, coordinates = _pdb_records(pdb_path)
    if len(psf_atoms) != len(pdb_line_indices):
        raise ValueError("PDB and PSF atom counts differ while building CPD local mask")
    endpoint_residues = {
        (endpoint["segid"], str(endpoint["resid"]))
        for lesion in lesions
        for endpoint in lesion.get("endpoints") or []
    }
    if not endpoint_residues:
        raise ValueError("static topology audit contains no ordered lesion endpoints")
    endpoint_indices = [
        index
        for index, atom in enumerate(psf_atoms)
        if (atom.segid, atom.resid) in endpoint_residues
    ]
    if not endpoint_indices:
        raise ValueError("ordered lesion endpoints resolve no PSF atoms")
    neighboring_residues = set(endpoint_residues)
    for segid, resid in endpoint_residues:
        try:
            numeric = int(resid)
        except ValueError:
            continue
        neighboring_residues.update({(segid, str(numeric - 1)), (segid, str(numeric + 1))})
    mobile = {
        index
        for index, atom in enumerate(psf_atoms)
        if (atom.segid, atom.resid) in neighboring_residues
    }
    endpoint_xyz = coordinates[endpoint_indices]
    squared_cutoff = mobile_radius_angstrom**2
    for index, xyz in enumerate(coordinates):
        if float(np.min(np.sum((endpoint_xyz - xyz) ** 2, axis=1))) <= squared_cutoff:
            mobile.add(index)
    for atom_index, line_index in enumerate(pdb_line_indices):
        line = lines[line_index].ljust(66)
        fixed = 0.0 if atom_index in mobile else 1.0
        lines[line_index] = line[:60] + f"{fixed:6.2f}" + line[66:]
    output_path.write_text("\n".join(lines) + "\n")
    return {
        "mobile_atom_count": len(mobile),
        "fixed_atom_count": len(psf_atoms) - len(mobile),
        "mobile_radius_angstrom": mobile_radius_angstrom,
        "endpoint_residues": [list(item) for item in sorted(endpoint_residues)],
    }


def _stage_config(
    base: str,
    *,
    name_stem: str,
    stage: str,
    action: str,
    steps: int,
    restart_from: str | None = None,
    fixed_mask: str | None = None,
    dcd_freq: int = 0,
) -> str:
    kept = [line for line in base.splitlines() if not _CONTROL_RE.match(line)]
    output_stem = f"output/{stage}"
    lines = [*kept, "", f"# NADOC CPD smoke stage: {stage}"]
    if restart_from is None:
        lines.append(f"coordinates        {name_stem}.pdb")
    else:
        lines.extend(
            [
                f"coordinates        {name_stem}.pdb",
                f"binCoordinates     output/{restart_from}.coor",
                f"extendedSystem     output/{restart_from}.xsc",
            ]
        )
    lines.extend(
        [
            f"outputName         {output_stem}",
            "outputEnergies     10",
            "restartfreq        100",
            "binaryrestart      yes",
        ]
    )
    if fixed_mask:
        lines.extend(
            [
                "fixedAtoms         on",
                f"fixedAtomsFile     {fixed_mask}",
                "fixedAtomsCol      B",
            ]
        )
    if action == "minimize":
        lines.extend(
            [
                "rigidBonds         none",
                "timestep           1.0",
                "temperature        0",
                "langevinTemp       0",
            ]
        )
        if steps:
            lines.append(f"minimize           {steps}")
        lines.append("run                0")
    elif action == "dynamics":
        lines.extend(
            [
                "rigidBonds         all",
                "timestep           2.0",
                "temperature        310",
                "langevinTemp       310",
                f"dcdFreq            {dcd_freq}",
                f"dcdFile            {output_stem}.dcd",
                f"xstFreq            {dcd_freq}",
                f"xstFile            {output_stem}.xst",
                f"run                {steps}",
            ]
        )
    else:  # pragma: no cover - private caller fixes this set
        raise ValueError(f"unsupported smoke action: {action}")
    return "\n".join(lines) + "\n"


def prepare_photoproduct_namd_smoke(
    *,
    package_dir: Path,
    output_dir: Path,
    local_minimize_steps: int = 500,
    global_minimize_steps: int = 1000,
    dynamics_steps: int = 1000,
    dcd_freq: int = 10,
    mobile_radius_angstrom: float = 6.0,
) -> dict[str, Any]:
    """Write a four-stage CPD smoke plan without executing or advancing a gate."""

    local_minimize_steps = _positive_cycle_count(local_minimize_steps, "local steps")
    global_minimize_steps = _positive_cycle_count(global_minimize_steps, "global steps")
    dynamics_steps = _positive_cycle_count(dynamics_steps, "dynamics steps")
    if dcd_freq < 1 or dynamics_steps % dcd_freq:
        raise ValueError("DCD frequency must divide the dynamics step count")
    if not math.isfinite(mobile_radius_angstrom) or mobile_radius_angstrom < 3.0:
        raise ValueError("mobile radius must be finite and at least 3 angstrom")
    if output_dir.exists():
        if not output_dir.is_dir() or any(output_dir.iterdir()):
            raise FileExistsError(f"refusing to overwrite CPD smoke plan: {output_dir}")
    try:
        output_relative = output_dir.resolve().relative_to(package_dir.resolve())
    except ValueError:
        raise ValueError("CPD smoke output directory must be inside the package") from None
    packaged = packaged_photoproduct_manifest(package_dir)
    if packaged is None:
        raise ValueError("CPD smoke preparation requires a packaged photoproduct manifest")
    if packaged.get("hmr_4fs_enabled") is not False or float(
        packaged.get("timestep_fs", math.inf)
    ) > 2.0:
        raise ValueError("packaged photoproduct integrator policy is not ordinary-mass <=2 fs")
    manifest_path = package_dir / "manifest.json"
    charge_audit_path = package_dir / "charge_audit.json"
    base_conf_path = package_dir / "namd.conf"
    if not all(path.is_file() for path in (manifest_path, charge_audit_path, base_conf_path)):
        raise FileNotFoundError("package lacks manifest.json, charge_audit.json, or namd.conf")
    package_manifest = json.loads(manifest_path.read_text())
    charge_audit = json.loads(charge_audit_path.read_text())
    name_stem = package_manifest.get("name_stem")
    if not isinstance(name_stem, str) or not name_stem:
        raise ValueError("package manifest has no name_stem")
    psf_path = package_dir / f"{name_stem}.psf"
    pdb_path = package_dir / f"{name_stem}.pdb"
    if not psf_path.is_file() or not pdb_path.is_file():
        raise FileNotFoundError("package is missing its ordinary-mass PSF or PDB")
    static_audit = (
        charge_audit.get("topology_metadata", {}).get(
            "photoproduct_static_topology_audit"
        )
    )
    if (
        not isinstance(static_audit, dict)
        or static_audit.get("schema")
        != "nadoc.photoproduct-static-topology-audit.v1"
        or static_audit.get("passed") is not True
    ):
        raise ValueError("package lacks a passed photoproduct static topology audit")
    base_conf = base_conf_path.read_text()
    required_directives = packaged_photoproduct_parameter_directives(package_dir)
    if any(directive not in base_conf for directive in required_directives):
        raise ValueError("package preflight config omits a frozen lesion parameter stream")

    output_dir.mkdir(parents=True, exist_ok=True)
    fixed_path = output_dir / "local_fixed.pdb"
    mask_report = _write_local_fixed_mask(
        pdb_path=pdb_path,
        psf_path=psf_path,
        lesions=static_audit["lesions"],
        output_path=fixed_path,
        mobile_radius_angstrom=mobile_radius_angstrom,
    )
    static_path = output_dir / "static_topology_audit.json"
    static_path.write_text(json.dumps(static_audit, indent=2) + "\n")
    stages = [
        ("00_load", "minimize", 0, None, None, 0),
        (
            "01_local_min",
            "minimize",
            local_minimize_steps,
            None,
            (output_relative / "local_fixed.pdb").as_posix(),
            0,
        ),
        ("02_global_min", "minimize", global_minimize_steps, "01_local_min", None, 0),
        ("03_dynamics_2fs", "dynamics", dynamics_steps, "02_global_min", None, dcd_freq),
    ]
    stage_records = []
    for stage, action, steps, restart, fixed, frequency in stages:
        conf_path = output_dir / f"{stage}.conf"
        conf_path.write_text(
            _stage_config(
                base_conf,
                name_stem=name_stem,
                stage=stage,
                action=action,
                steps=steps,
                restart_from=restart,
                fixed_mask=fixed,
                dcd_freq=frequency,
            )
        )
        stage_records.append(
            {
                "name": stage,
                "action": action,
                "steps": steps,
                "restart_from": restart,
                "config": str(conf_path.relative_to(package_dir)),
                "sha256": _sha256(conf_path),
                "log": str((output_dir / f"{stage}.log").relative_to(package_dir)),
                "command_template": (
                    f"<namd> +p<threads> +setcpuaffinity "
                    f"{conf_path.relative_to(package_dir)} > "
                    f"{(output_dir / f'{stage}.log').relative_to(package_dir)} 2>&1"
                ),
            }
        )
    manifest = {
        "schema": "nadoc.photoproduct-namd-smoke-plan.v1",
        "status": "prepared_not_run",
        "gate_effect": "none",
        "product_ids": sorted({item["product_id"] for item in static_audit["lesions"]}),
        "package": {
            "manifest_sha256": _sha256(manifest_path),
            "photoproduct_manifest_sha256": _sha256(
                package_dir / "photoproduct_forcefield_manifest.json"
            ),
            "psf_sha256": _sha256(psf_path),
            "pdb_sha256": _sha256(pdb_path),
        },
        "integrator": {"maximum_timestep_fs": 2.0, "hmr": False},
        "local_mobile_mask": {**mask_report, "sha256": _sha256(fixed_path)},
        "static_topology_audit": {
            "path": str(static_path.relative_to(package_dir)),
            "sha256": _sha256(static_path),
        },
        "stages": stage_records,
        "execution_note": (
            "Run stages in order from the package root with the installed NAMD binary; "
            "a separate trajectory/log audit is required before the namd_smoke gate."
        ),
    }
    plan_path = output_dir / "smoke_plan.json"
    plan_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def _namd_log_audit(path: Path) -> dict[str, Any]:
    text = path.read_text(errors="replace")
    lower = text.lower()
    problem_lines = [
        line.strip()
        for line in text.splitlines()
        if any(
            token in line.lower()
            for token in (
                "fatal error",
                "error:",
                "warning:",
                "missing parameter",
                "unable to find",
                "duplicate parameter",
            )
        )
    ]
    energy_lines = [line for line in text.splitlines() if line.lstrip().startswith("ENERGY:")]
    nonfinite_energy = any(
        token.lower() in {"nan", "+nan", "-nan", "inf", "+inf", "-inf"}
        for line in energy_lines
        for token in line.split()
    )
    version_match = re.search(r"\bNAMD\s+([0-9][0-9A-Za-z.+_-]*)", text)
    errors = []
    if "end of program" not in lower:
        errors.append("NAMD log has no successful end-of-program marker")
    if not energy_lines:
        errors.append("NAMD log contains no ENERGY record")
    if nonfinite_energy:
        errors.append("NAMD log contains non-finite energy")
    if problem_lines:
        errors.append("NAMD log contains fatal/error/warning/parameter diagnostics")
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "passed": not errors,
        "energy_record_count": len(energy_lines),
        "diagnostic_lines": problem_lines,
        "errors": errors,
        "engine_version": version_match.group(1) if version_match else None,
    }


def _distance(coordinates: np.ndarray, first: int, second: int) -> float:
    return float(np.linalg.norm(coordinates[first] - coordinates[second]))


def audit_photoproduct_namd_smoke(
    *,
    package_dir: Path,
    smoke_plan_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Audit completed smoke logs/DCD and emit the report consumed by Help export."""

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite NAMD smoke audit: {output_path}")
    plan = json.loads(smoke_plan_path.read_text())
    if (
        plan.get("schema") != "nadoc.photoproduct-namd-smoke-plan.v1"
        or plan.get("status") != "prepared_not_run"
        or plan.get("gate_effect") != "none"
    ):
        raise ValueError("unsupported or non-neutral CPD smoke plan")
    packaged = packaged_photoproduct_manifest(package_dir)
    if packaged is None:
        raise ValueError("smoke audit requires a packaged photoproduct manifest")
    if _sha256(package_dir / "manifest.json") != plan["package"]["manifest_sha256"]:
        raise ValueError("package manifest changed after smoke planning")
    if _sha256(package_dir / "photoproduct_forcefield_manifest.json") != plan[
        "package"
    ]["photoproduct_manifest_sha256"]:
        raise ValueError("packaged photoproduct manifest changed after smoke planning")
    name_stem = json.loads((package_dir / "manifest.json").read_text())["name_stem"]
    psf_path = package_dir / f"{name_stem}.psf"
    if _sha256(psf_path) != plan["package"]["psf_sha256"]:
        raise ValueError("ordinary-mass PSF changed after smoke planning")
    for stage in plan["stages"]:
        config_path = package_dir / stage["config"]
        if not config_path.is_file() or _sha256(config_path) != stage["sha256"]:
            raise ValueError(f"smoke configuration changed or is missing: {stage['name']}")
    static_path = package_dir / plan["static_topology_audit"]["path"]
    if _sha256(static_path) != plan["static_topology_audit"]["sha256"]:
        raise ValueError("static topology audit changed after smoke planning")
    static_audit = json.loads(static_path.read_text())
    lesions = static_audit.get("lesions") or []
    if len(lesions) != 1:
        raise ValueError("help/smoke release audit requires exactly one lesion per package")
    product_id = lesions[0].get("product_id")
    if plan.get("product_ids") != [product_id]:
        raise ValueError("smoke plan and static topology product identities differ")

    log_reports = []
    restart_reports = []
    for stage in plan["stages"]:
        log_path = package_dir / stage["log"]
        if not log_path.is_file():
            raise FileNotFoundError(f"smoke stage log is missing: {log_path}")
        log_reports.append({"stage": stage["name"], **_namd_log_audit(log_path)})
        stage_outputs = {}
        for suffix in ("coor", "xsc"):
            result_path = package_dir / "output" / f"{stage['name']}.{suffix}"
            if not result_path.is_file():
                raise FileNotFoundError(
                    f"smoke stage output is missing: {result_path}"
                )
            stage_outputs[suffix] = {
                "path": str(result_path),
                "sha256": _sha256(result_path),
            }
        restart_reports.append({"stage": stage["name"], "outputs": stage_outputs})
    dynamics_stage = plan["stages"][-1]
    dynamics_conf = (package_dir / dynamics_stage["config"]).read_text()
    if (
        not re.search(r"^\s*timestep\s+2(?:\.0+)?\s*$", dynamics_conf, re.MULTILINE)
        or not re.search(r"^\s*rigidBonds\s+all\s*$", dynamics_conf, re.MULTILINE)
        or "_hmr.psf" in dynamics_conf
    ):
        raise ValueError("dynamics smoke config is not ordinary-mass rigid-bond 2 fs")

    dcd_path = package_dir / "output/03_dynamics_2fs.dcd"
    if not dcd_path.is_file():
        raise FileNotFoundError(f"smoke dynamics DCD is missing: {dcd_path}")
    layout = read_layout(dcd_path)
    psf_atoms = parse_psf_atoms(psf_path.read_text(errors="replace"))
    if layout.n_atoms != len(psf_atoms) or layout.n_frames < 2:
        raise ValueError("smoke DCD atom/frame count is incompatible with the PSF")
    if layout.nsavc <= 0 or layout.delta_ps <= 0:
        raise ValueError("smoke DCD lacks a positive timestep/stride header")
    timestep_fs = layout.delta_ps * 1000.0 / layout.nsavc
    if not math.isclose(timestep_fs, 2.0, rel_tol=1e-4, abs_tol=1e-6):
        raise ValueError(f"smoke DCD records {timestep_fs:g} fs rather than 2 fs")

    registry_entry = next(
        item for item in photoproduct_registry()["products"] if item["id"] == product_id
    )
    definition = load_chemical_definition(
        registry_entry["product"], registry_entry["stereochemistry"]
    )
    endpoint_by_number = {
        int(item["endpoint"]): (item["segid"], str(item["resid"]))
        for item in lesions[0]["endpoints"]
    }
    atom_indices = {
        (atom.segid, atom.resid, atom.name): index
        for index, atom in enumerate(psf_atoms)
    }

    def resolve(reference: str) -> int:
        endpoint_text, atom_name = reference.split(":", 1)
        segid, resid = endpoint_by_number[int(endpoint_text)]
        identity = (segid, resid, charmm_atom_name(atom_name))
        if identity not in atom_indices:
            raise ValueError(f"smoke PSF is missing product atom {reference}")
        return atom_indices[identity]

    crosslinks = [
        (bond["atom_1"], bond["atom_2"])
        for bond in definition["graph_delta"]["bonds_added"]
    ]
    retained = [
        (bond["atom_1"], bond["atom_2"])
        for bond in definition["graph_delta"]["bonds_retained"]
    ]
    glycosidic = [("1:C1'", "1:N1"), ("2:C1'", "2:N1")]
    frame_reports = []
    errors = [error for report in log_reports for error in report["errors"]]
    for frame_index in range(layout.n_frames):
        coordinates, _cell = read_frame(dcd_path, layout, frame_index)
        chirality_coordinates = {}
        for center in definition["product_stereocenters"]:
            for reference in [center["atom"], *center["signed_volume_reference_atoms"]]:
                chirality_coordinates[reference] = coordinates[resolve(reference)].tolist()
        chirality = audit_product_chirality(definition, chirality_coordinates)
        distances = {
            "crosslinks": [
                _distance(coordinates, resolve(first), resolve(second))
                for first, second in crosslinks
            ],
            "retained_ring_bonds": [
                _distance(coordinates, resolve(first), resolve(second))
                for first, second in retained
            ],
            "glycosidic_bonds": [
                _distance(coordinates, resolve(first), resolve(second))
                for first, second in glycosidic
            ],
        }
        frame_errors = []
        if not chirality["passed"]:
            frame_errors.append("product chirality changed")
        if any(not 1.25 <= value <= 1.85 for value in distances["crosslinks"]):
            frame_errors.append("CPD crosslink left the 1.25-1.85 angstrom safety range")
        if any(not 1.25 <= value <= 1.85 for value in distances["retained_ring_bonds"]):
            frame_errors.append("retained C5-C6 bond left the safety range")
        if any(not 1.25 <= value <= 1.75 for value in distances["glycosidic_bonds"]):
            frame_errors.append("glycosidic bond left the 1.25-1.75 angstrom safety range")
        errors.extend(f"frame {frame_index}: {message}" for message in frame_errors)
        frame_reports.append(
            {
                "frame": frame_index,
                "chirality_passed": chirality["passed"],
                "distances_angstrom": distances,
                "errors": frame_errors,
            }
        )

    parameter_records = [
        record for record in packaged["assets"] if record.get("kind") == "parameters"
    ]
    if len(parameter_records) != 1:
        raise ValueError("one-lesion smoke package must contain exactly one parameter stream")
    parameter_path = package_dir / "forcefield" / parameter_records[0]["relative_path"]
    engine_versions = {item["engine_version"] for item in log_reports if item["engine_version"]}
    if len(engine_versions) != 1:
        errors.append("NAMD engine version is absent or inconsistent across stage logs")
    report = {
        "schema": "nadoc.photoproduct-namd-smoke.v1",
        "status": "passed" if not errors else "failed",
        "passed": not errors,
        "gate_effect": "none",
        "product_ids": [product_id],
        "engine": {
            "name": "NAMD",
            "version": next(iter(engine_versions), None),
        },
        "timestep_fs": timestep_fs,
        "hmr": False,
        "psf_sha256": _sha256(psf_path),
        "dcd_sha256": _sha256(dcd_path),
        "parameters_sha256": _sha256(parameter_path),
        "static_topology_audit_sha256": _sha256(static_path),
        "smoke_plan_sha256": _sha256(smoke_plan_path),
        "logs": log_reports,
        "stage_outputs": restart_reports,
        "frames": frame_reports,
        "errors": errors,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
