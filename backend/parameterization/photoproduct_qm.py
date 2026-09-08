"""Reproducible, provenance-first Psi4 input generation for photoproducts.

Generating an input is not force-field evidence. The returned manifest says
``generated_not_run`` and cannot change a registry gate.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any, Sequence

from backend.core.photoproduct_chemistry import (
    audit_product_chirality,
    load_chemical_definition,
    signed_tetrahedron_volume,
)
from backend.core.photoproduct_registry import photoproduct_registry

QM_PROTOCOL_PATH = (
    Path(__file__).parents[1] / "data" / "forcefield" / "photoproduct_qm_protocol.json"
)

_KNOWN_JOB_OUTPUTS: dict[str, set[str]] = {
    "geometry_optimization": {"optimized.xyz"},
    "frequency": {"hessian_hartree_per_bohr2.txt"},
    "fixed_geometry_hessian": {
        "gradient_hartree_per_bohr.txt",
        "hessian_hartree_per_bohr2.txt",
    },
    "torsion_scan": {"optimized.xyz"},
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _checked_source(record: object, label: str) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{label} record is missing")
    path = Path(str(record.get("path") or ""))
    if not path.is_file() or _sha256_bytes(path.read_bytes()) != record.get("sha256"):
        raise ValueError(f"{label} is missing or hash-mismatched")
    return path.resolve()


def resolve_frequency_job_reference(
    *, job_dir: Path, job: dict[str, Any], key: str, label: str
) -> Path:
    """Resolve a source through a hash-audited frequency-job provenance copy."""

    record = job.get(key)
    if not isinstance(record, dict):
        raise ValueError(f"frequency job lacks {label}")
    declared = Path(str(record.get("path") or ""))
    if declared.is_file() and _sha256_bytes(declared.read_bytes()) == record.get(
        "sha256"
    ):
        return declared.resolve()
    relocation_path = job_dir / "frequency_job_provenance.json"
    if not relocation_path.is_file():
        raise ValueError(f"{label} is missing or hash-mismatched")
    relocation = json.loads(relocation_path.read_text())
    relocated_record = (relocation.get("references") or {}).get(key)
    copy_record = (
        relocated_record.get("copy") if isinstance(relocated_record, dict) else None
    )
    if (
        relocation.get("schema")
        != "nadoc.photoproduct-frequency-job-provenance-copy.v1"
        or relocation.get("status") != "materialized_byte_identical"
        or relocation.get("gate_effect") != "none"
        or relocation.get("product_id") != job.get("product_id")
        or relocation.get("model_id") != job.get("model_id")
        or (relocation.get("frequency_job_manifest") or {}).get("sha256")
        != _sha256_bytes((job_dir / "job_manifest.json").read_bytes())
        or not isinstance(relocated_record, dict)
        or relocated_record.get("original_path") != record.get("path")
        or relocated_record.get("sha256") != record.get("sha256")
        or not isinstance(copy_record, dict)
        or copy_record.get("sha256") != record.get("sha256")
    ):
        raise ValueError(f"frequency-job provenance copy changed {label} identity")
    relocated = (job_dir / str(copy_record.get("path") or "")).resolve()
    try:
        relocated.relative_to(job_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"relocated {label} escapes the frequency job") from exc
    if not relocated.is_file() or _sha256_bytes(relocated.read_bytes()) != record.get(
        "sha256"
    ):
        raise ValueError(f"relocated {label} is missing or hash-mismatched")
    return relocated


def qm_protocol(path: Path = QM_PROTOCOL_PATH) -> dict[str, Any]:
    protocol = json.loads(path.read_text())
    if protocol.get("schema") != "nadoc.photoproduct-qm-protocol.v1":
        raise ValueError("unsupported photoproduct QM protocol schema")
    return protocol


def parse_xyz(text: str) -> tuple[list[tuple[str, float, float, float]], str]:
    lines = text.splitlines()
    if len(lines) < 2:
        raise ValueError("XYZ requires an atom count and comment line")
    try:
        count = int(lines[0].strip())
    except ValueError as exc:
        raise ValueError("XYZ atom count is not an integer") from exc
    atom_lines = [line for line in lines[2:] if line.strip()]
    if len(atom_lines) != count:
        raise ValueError(f"XYZ declares {count} atoms but contains {len(atom_lines)}")
    atoms: list[tuple[str, float, float, float]] = []
    for line in atom_lines:
        fields = line.split()
        if len(fields) != 4 or not fields[0].isalpha():
            raise ValueError(f"invalid XYZ atom line: {line!r}")
        try:
            xyz = tuple(float(value) for value in fields[1:])
        except ValueError as exc:
            raise ValueError(f"invalid XYZ coordinate: {line!r}") from exc
        atoms.append((fields[0], *xyz))
    return atoms, lines[1]


def render_psi4_input(
    xyz_text: str,
    *,
    job_kind: str,
    charge: int,
    multiplicity: int,
    memory_gib: int = 8,
    threads: int = 8,
    maximum_geometry_iterations: int | None = None,
    protocol_path: Path = QM_PROTOCOL_PATH,
) -> tuple[str, dict[str, Any]]:
    protocol = qm_protocol(protocol_path)
    job = (protocol.get("jobs") or {}).get(job_kind)
    if job_kind not in {
        "geometry_optimization",
        "frequency",
        "fixed_geometry_hessian",
        "electrostatic_properties",
        "conformer_single_point",
    }:
        raise ValueError(
            f"{job_kind!r} requires a specialized generator or is not registered"
        )
    if not isinstance(job, dict):
        raise ValueError(f"QM protocol has no job {job_kind!r}")
    if multiplicity < 1 or memory_gib < 1 or threads < 1:
        raise ValueError("multiplicity, memory_gib, and threads must be positive")
    if maximum_geometry_iterations is not None and (
        job_kind != "geometry_optimization"
        or not 50 < maximum_geometry_iterations <= 500
    ):
        raise ValueError(
            "maximum_geometry_iterations is a geometry-retry override in (50, 500]"
        )
    atoms, comment = parse_xyz(xyz_text)
    basis = protocol["rules"]["charged_model_diffuse_basis"] if charge else job["basis"]
    coordinates = "\n".join(
        f"  {element:<2} {x: .12f} {y: .12f} {z: .12f}" for element, x, y, z in atoms
    )
    settings = {
        "basis": basis,
        "reference": "rhf" if multiplicity == 1 else "uhf",
        "scf_type": job.get("scf_type", "df"),
        "freeze_core": bool(job.get("freeze_core", True)),
    }
    if job.get("mp2_type"):
        settings["mp2_type"] = job["mp2_type"]
    if job_kind == "geometry_optimization":
        settings["g_convergence"] = job["geometry_convergence"]
        optimizer_settings = job.get("optimizer_settings") or {}
        allowed_optimizer_settings = {
            "intrafrag_step_limit",
            "intrafrag_step_limit_max",
        }
        if not isinstance(optimizer_settings, dict) or not set(
            optimizer_settings
        ).issubset(allowed_optimizer_settings):
            raise ValueError(
                "geometry optimizer_settings contain an unsupported Psi4 option"
            )
        for name, value in optimizer_settings.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not (
                0.01 <= float(value) <= 0.5
            ):
                raise ValueError(
                    f"geometry optimizer setting {name} must be in [0.01, 0.5]"
                )
            settings[name] = float(value)
        if maximum_geometry_iterations is not None:
            settings["geom_maxiter"] = maximum_geometry_iterations
        operation = (
            f"energy, wavefunction = optimize('{job['method']}', return_wfn=True)\n"
            "model.save_xyz_file('optimized.xyz', True)"
        )
    elif job_kind == "frequency":
        operation = (
            "import numpy as np\n"
            f"energy, wavefunction = frequency('{job['method']}', return_wfn=True)\n"
            "hessian = np.asarray(wavefunction.hessian())\n"
            "np.savetxt('hessian_hartree_per_bohr2.txt', hessian, fmt='%.16e')"
        )
    elif job_kind == "fixed_geometry_hessian":
        operation = (
            "import numpy as np\n"
            f"energy, wavefunction = hessian('{job['method']}', return_wfn=True)\n"
            "gradient = np.asarray(wavefunction.gradient())\n"
            "hessian = np.asarray(wavefunction.hessian())\n"
            "np.savetxt('gradient_hartree_per_bohr.txt', gradient.reshape(-1), "
            "fmt='%.16e')\n"
            "np.savetxt('hessian_hartree_per_bohr2.txt', hessian, fmt='%.16e')"
        )
    elif job_kind == "electrostatic_properties":
        operation = (
            f"energy, wavefunction = energy('{job['method']}', return_wfn=True)\n"
            "oeprop(wavefunction, 'DIPOLE')\n"
            "dipole = wavefunction.variable('DIPOLE')\n"
            "print_out('NADOC_DIPOLE_AU %.12f %.12f %.12f\\n' % "
            "(dipole[0], dipole[1], dipole[2]))"
        )
    else:
        operation = f"energy, wavefunction = energy('{job['method']}', return_wfn=True)"
    setting_lines = "\n".join(
        f"  {name} {str(value).lower() if isinstance(value, bool) else value}"
        for name, value in settings.items()
    )
    rendered = f"""# NADOC photoproduct QM protocol {protocol["version"]}
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
{setting_lines}
}}

{operation}
"""
    metadata = {
        "job_kind": job_kind,
        "method": job["method"],
        "basis": basis,
        "charge": charge,
        "multiplicity": multiplicity,
        "atom_count": len(atoms),
        "memory_gib": memory_gib,
        "threads": threads,
        "maximum_geometry_iterations": maximum_geometry_iterations,
        "optimizer_settings": (
            dict(optimizer_settings) if job_kind == "geometry_optimization" else None
        ),
        "protocol_version": protocol["version"],
        "protocol_sha256": _sha256_bytes(protocol_path.read_bytes()),
    }
    return rendered, metadata


def generate_psi4_job(
    *,
    product_id: str,
    model_id: str,
    xyz_path: Path,
    output_dir: Path,
    job_kind: str,
    charge: int,
    multiplicity: int,
    atom_map: Sequence[str] | None = None,
    model_manifest_path: Path | None = None,
    parent_manifest_path: Path | None = None,
    memory_gib: int = 8,
    threads: int = 8,
    maximum_geometry_iterations: int | None = None,
    protocol_path: Path = QM_PROTOCOL_PATH,
    coupled_conformer_plan_path: Path | None = None,
    conformer_id: str | None = None,
) -> dict[str, Any]:
    xyz_bytes = xyz_path.read_bytes()
    fixed_geometry_context = None
    if job_kind == "fixed_geometry_hessian":
        if coupled_conformer_plan_path is None or not conformer_id:
            raise ValueError(
                "fixed_geometry_hessian requires a reviewed coupled-conformer plan and ID"
            )
        # Local import avoids making ordinary QM generation depend cyclically on the
        # coupled-conformer review module at import time.
        from backend.parameterization.photoproduct_coupled_conformer import (
            validate_reviewed_coupled_conformer_plan,
        )

        reviewed = validate_reviewed_coupled_conformer_plan(coupled_conformer_plan_path)
        matches = [
            item for item in reviewed["conformers"] if item["id"] == conformer_id
        ]
        if len(matches) != 1:
            raise ValueError(f"reviewed plan has no unique conformer {conformer_id!r}")
        selected = matches[0]
        plan = reviewed["plan"]
        if (
            plan.get("product_id") != product_id
            or plan.get("model_id") != model_id
            or selected["geometry"]["sha256"] != _sha256_bytes(xyz_bytes)
            or list(atom_map or []) != reviewed["atom_map"]
        ):
            raise ValueError(
                "fixed-geometry job identity, geometry, or atom map differs from review"
            )
        fixed_geometry_context = {
            "plan_path": coupled_conformer_plan_path,
            "plan": plan,
            "selected": selected,
        }
    elif coupled_conformer_plan_path is not None or conformer_id is not None:
        raise ValueError(
            "coupled-conformer review arguments apply only to fixed_geometry_hessian"
        )
    rendered, metadata = render_psi4_input(
        xyz_bytes.decode(),
        job_kind=job_kind,
        charge=charge,
        multiplicity=multiplicity,
        memory_gib=memory_gib,
        threads=threads,
        maximum_geometry_iterations=maximum_geometry_iterations,
        protocol_path=protocol_path,
    )
    if atom_map is not None and len(atom_map) != metadata["atom_count"]:
        raise ValueError("atom_map length must equal the XYZ atom count")
    model_manifest_record = None
    parent_manifest_record = None
    if model_manifest_path is not None and parent_manifest_path is not None:
        raise ValueError("provide a model manifest or a parent audit, not both")
    if model_manifest_path is not None:
        model_manifest = json.loads(model_manifest_path.read_text())
        model_schema = model_manifest.get("schema")
        if model_schema not in {
            "nadoc.photoproduct-model-compound.v1",
            "nadoc.tt-cpd-stereo-candidate.v1",
            "nadoc.photoproduct-dna-boundary-model-candidate.v1",
        }:
            raise ValueError("unsupported model-compound manifest schema")
        accepted_statuses = {
            "nadoc.photoproduct-model-compound.v1": {"constructed_not_optimized"},
            "nadoc.tt-cpd-stereo-candidate.v1": {"candidate_not_reviewed"},
            "nadoc.photoproduct-dna-boundary-model-candidate.v1": {
                "candidate_pending_cap_review",
                "human_cap_review_complete",
                "quantitatively_screened_boundary",
            },
        }[model_schema]
        observed_status = model_manifest.get("status")
        if (
            model_manifest.get("product_id") != product_id
            or model_manifest.get("model_id") != model_id
            or observed_status not in accepted_statuses
        ):
            raise ValueError(
                "model manifest identity/status does not match requested QM job"
            )
        if model_manifest.get("outputs", {}).get("xyz", {}).get(
            "sha256"
        ) != _sha256_bytes(xyz_bytes):
            raise ValueError("source XYZ does not match the model manifest")
        if model_schema in {
            "nadoc.tt-cpd-stereo-candidate.v1",
            "nadoc.photoproduct-dna-boundary-model-candidate.v1",
        }:
            mapped = model_manifest.get("outputs", {}).get("atom_map", {})
            map_path = Path(str(mapped.get("path") or ""))
            if (
                atom_map is None
                or not map_path.is_file()
                or _sha256_bytes(map_path.read_bytes()) != mapped.get("sha256")
                or json.loads(map_path.read_text()) != list(atom_map)
            ):
                raise ValueError(
                    "stereo-candidate stable atom map is missing or mismatched"
                )
        if observed_status == "human_cap_review_complete":
            review = model_manifest.get("cap_review") or {}
            if (
                review.get("decision") != "APPROVE"
                or review.get("source_geometry_sha256")
                != model_manifest.get("outputs", {}).get("xyz", {}).get("sha256")
                or not review.get("reviewer")
                or not review.get("rationale")
            ):
                raise ValueError(
                    "reviewed boundary model has incomplete cap-review evidence"
                )
        if observed_status == "quantitatively_screened_boundary":
            screen = model_manifest.get("quantitative_screening") or {}
            policy_path = _checked_source(
                screen.get("policy_source"), "boundary quantitative policy"
            )
            policy = json.loads(policy_path.read_text())
            policy_gate = screen.get("policy_gate", "dna_boundary_model")
            if policy_gate not in {
                "dna_boundary_model",
                "grafted_dna_boundary_model",
                "flexibly_relaxed_dna_boundary_seed",
            }:
                raise ValueError("screened boundary uses an unsupported policy gate")
            if policy_gate == "dna_boundary_model":
                expected = (policy.get("automated_qm_input_gates") or {}).get(
                    policy_gate
                ) or {}
                valid_policy = (
                    policy.get("schema")
                    == "nadoc.photoproduct-parameter-acceptance.v2"
                )
            elif policy_gate == "grafted_dna_boundary_model":
                expected = policy.get("gate") or {}
                valid_policy = (
                    policy.get("schema")
                    == "nadoc.photoproduct-grafted-boundary-policy.v1"
                    and policy.get("version") == "1.0.0"
                    and policy.get("gate_id") == policy_gate
                    and policy.get("simulation_ready") is False
                    and policy.get("gate_effect") == "none"
                )
            else:
                expected = {"policy": policy.get("policy")}
                valid_policy = (
                    policy.get("schema")
                    == "nadoc.photoproduct-flexible-boundary-seed-policy.v1"
                    and policy.get("version") in {"1.0.0", "2.0.0"}
                    and policy.get("gate_id") == policy_gate
                    and policy.get("authorizes")
                    == "boundary_qm_evidence_generation_only"
                    and policy.get("simulation_ready") is False
                    and policy.get("gate_effect") == "none"
                )
            if (
                not valid_policy
                or screen.get("schema")
                != "nadoc.photoproduct-dna-boundary-quantitative-screen.v1"
                or screen.get("status") != "passed_qm_input_screen"
                or screen.get("policy") != expected.get("policy")
                or screen.get("authorizes") != "boundary_qm_evidence_generation_only"
                or screen.get("releases_parameters") is not False
            ):
                raise ValueError(
                    "screened boundary model has incomplete policy evidence"
                )
        model_manifest_record = {
            "path": str(model_manifest_path.resolve()),
            "sha256": _sha256_bytes(model_manifest_path.read_bytes()),
            "schema": model_schema,
            "evidence_status": observed_status,
        }
    if parent_manifest_path is not None:
        parent = json.loads(parent_manifest_path.read_text())
        if parent.get("schema") != "nadoc.photoproduct-optimized-model-audit.v1":
            raise ValueError("unsupported parent optimized-model audit schema")
        accepted_parent_statuses = {
            "passed_identity_and_chirality",
            "passed_candidate_identity_and_chirality",
        }
        if (
            parent.get("product_id") != product_id
            or parent.get("model_id") != model_id
            or parent.get("status") not in accepted_parent_statuses
        ):
            raise ValueError("parent audit is not a passed matching model")
        if parent.get("optimized_xyz", {}).get("sha256") != _sha256_bytes(xyz_bytes):
            raise ValueError(
                "source XYZ does not match the parent optimized-model audit"
            )
        parent_manifest_record = {
            "path": str(parent_manifest_path.resolve()),
            "sha256": _sha256_bytes(parent_manifest_path.read_bytes()),
            "evidence_status": parent["status"],
        }
    output_dir.mkdir(parents=True, exist_ok=True)
    input_path = output_dir / "input.dat"
    manifest_path = output_dir / "job_manifest.json"
    input_path.write_text(rendered)
    manifest = {
        "schema": "nadoc.photoproduct-qm-job.v1",
        "status": "generated_not_run",
        "gate_effect": "none",
        "product_id": product_id,
        "model_id": model_id,
        **metadata,
        "source_xyz": {
            "path": str(xyz_path),
            "sha256": _sha256_bytes(xyz_bytes),
        },
        "model_manifest": model_manifest_record,
        "parent_manifest": parent_manifest_record,
        "atom_map": list(atom_map) if atom_map is not None else None,
        "input": {
            "path": str(input_path),
            "sha256": _sha256_bytes(rendered.encode()),
        },
        "expected_outputs": [
            "output.dat",
            *sorted(_KNOWN_JOB_OUTPUTS.get(job_kind, set())),
        ],
        "gradient_units": (
            "hartree/bohr" if job_kind == "fixed_geometry_hessian" else None
        ),
        "hessian_units": (
            "hartree/bohr^2"
            if job_kind in {"frequency", "fixed_geometry_hessian"}
            else None
        ),
    }
    if fixed_geometry_context is not None:
        selected = fixed_geometry_context["selected"]
        manifest["coupled_conformer_plan"] = {
            "path": str(fixed_geometry_context["plan_path"].resolve()),
            "sha256": _sha256_bytes(fixed_geometry_context["plan_path"].read_bytes()),
        }
        manifest["conformer"] = {
            "id": conformer_id,
            "partition": selected["partition"],
            "geometry_sha256": selected["geometry"]["sha256"],
            "review_decision": selected["review_decision"],
        }
        manifest["coordinate_policy"] = {
            "optimization": "forbidden",
            "reflection": "forbidden",
            "atom_reordering": "forbidden",
            "required_outputs": ["gradient", "full_cartesian_hessian"],
        }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


_PSI4_GEOMETRY_LINE = re.compile(
    r"^\s*([A-Z][a-z]?)\s+"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)\s+"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)\s+"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)\s*$"
)


def _last_psi4_geometry(
    text: str, atom_count: int
) -> list[tuple[str, float, float, float]]:
    """Extract the last complete printed Psi4 Cartesian geometry block."""

    lines = text.splitlines()
    candidates: list[list[tuple[str, float, float, float]]] = []
    for index, line in enumerate(lines):
        if "Geometry (in Angstrom)" not in line:
            continue
        atoms: list[tuple[str, float, float, float]] = []
        started = False
        for row in lines[index + 1 :]:
            match = _PSI4_GEOMETRY_LINE.match(row)
            if match:
                started = True
                atoms.append(
                    (
                        match.group(1),
                        float(match.group(2)),
                        float(match.group(3)),
                        float(match.group(4)),
                    )
                )
                if len(atoms) == atom_count:
                    candidates.append(atoms)
                    break
            elif started:
                break
    if not candidates:
        raise ValueError("failed output contains no complete final Cartesian geometry")
    return candidates[-1]


def generate_geometry_retry_job(
    *,
    failed_job_dir: Path,
    output_dir: Path,
    maximum_iterations: int = 100,
) -> dict[str, Any]:
    """Create a hash-linked retry only for a clean optimizer iteration-limit failure."""

    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite geometry retry: {output_dir}")
    job_path = failed_job_dir / "job_manifest.json"
    run_path = failed_job_dir / "run_manifest.json"
    raw_path = failed_job_dir / "output.dat"
    if not all(path.is_file() for path in (job_path, run_path, raw_path)):
        raise ValueError("failed job manifest, run record, and raw output are required")
    job = json.loads(job_path.read_text())
    run = json.loads(run_path.read_text())
    if (
        job.get("schema") != "nadoc.photoproduct-qm-job.v1"
        or job.get("job_kind") != "geometry_optimization"
        or run.get("status") != "failed"
        or run.get("job_manifest_sha256") != _sha256_bytes(job_path.read_bytes())
        or (run.get("outputs") or {}).get("output.dat", {}).get("sha256")
        != _sha256_bytes(raw_path.read_bytes())
        or "OptimizationConvergenceError" not in str(run.get("stdout_tail") or "")
        or "Could not converge geometry optimization"
        not in str(run.get("stdout_tail") or "")
    ):
        raise ValueError(
            "retry is allowed only for a hash-valid geometry optimizer iteration-limit failure"
        )
    source_path = Path(str((job.get("source_xyz") or {}).get("path") or ""))
    if not source_path.is_file() or _sha256_bytes(source_path.read_bytes()) != (
        job.get("source_xyz") or {}
    ).get("sha256"):
        raise ValueError("failed job source geometry is missing or hash-mismatched")
    source_atoms, _comment = parse_xyz(source_path.read_text())
    atoms = _last_psi4_geometry(raw_path.read_text(errors="replace"), len(source_atoms))
    if [item[0] for item in atoms] != [item[0] for item in source_atoms]:
        raise ValueError("last optimizer geometry changed atom order or elements")
    output_dir.mkdir(parents=True)
    restart_path = output_dir / "restart.xyz"
    restart_path.write_text(
        f"{len(atoms)}\nretry from hash-linked failed optimizer geometry\n"
        + "\n".join(
            f"{element:<2} {x: .12f} {y: .12f} {z: .12f}" for element, x, y, z in atoms
        )
        + "\n"
    )
    model_manifest_record = job.get("model_manifest") or {}
    model_manifest_path = Path(str(model_manifest_record.get("path") or ""))
    if model_manifest_record and (
        not model_manifest_path.is_file()
        or _sha256_bytes(model_manifest_path.read_bytes())
        != model_manifest_record.get("sha256")
    ):
        raise ValueError("failed job model manifest is missing or hash-mismatched")
    protocol_version = str(job.get("protocol_version") or "")
    protocol_path = QM_PROTOCOL_PATH.with_name(
        f"photoproduct_qm_protocol_v{protocol_version}.json"
    )
    if not protocol_path.is_file() or _sha256_bytes(
        protocol_path.read_bytes()
    ) != job.get("protocol_sha256"):
        raise ValueError(
            "failed job's immutable QM protocol file is unavailable or changed"
        )
    manifest = generate_psi4_job(
        product_id=job["product_id"],
        model_id=job["model_id"],
        xyz_path=restart_path,
        output_dir=output_dir,
        job_kind="geometry_optimization",
        charge=int(job["charge"]),
        multiplicity=int(job["multiplicity"]),
        atom_map=job.get("atom_map"),
        memory_gib=int(job["memory_gib"]),
        threads=int(job["threads"]),
        maximum_geometry_iterations=maximum_iterations,
        protocol_path=protocol_path,
    )
    manifest["model_manifest"] = model_manifest_record or None
    manifest["retry_parent"] = {
        "job_manifest": {
            "path": str(job_path.resolve()),
            "sha256": _sha256_bytes(job_path.read_bytes()),
        },
        "run_manifest": {
            "path": str(run_path.resolve()),
            "sha256": _sha256_bytes(run_path.read_bytes()),
        },
        "raw_output": {
            "path": str(raw_path.resolve()),
            "sha256": _sha256_bytes(raw_path.read_bytes()),
        },
        "failed_final_energy_hartree": (run.get("parsed") or {}).get(
            "final_energy_hartree"
        ),
    }
    manifest["retry_policy"] = {
        "reason": "optimizer iteration limit only",
        "convergence_criterion_unchanged": True,
        "qm_method_and_basis_unchanged": True,
        "maximum_iterations": maximum_iterations,
        "gate_effect": "none",
    }
    manifest_path = output_dir / "job_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def _coordinates_block(atoms: Sequence[tuple[str, float, float, float]]) -> str:
    return "\n".join(
        f"  {element:<2} {x: .12f} {y: .12f} {z: .12f}" for element, x, y, z in atoms
    )


def _water_geometry(
    atoms: Sequence[tuple[str, float, float, float]],
) -> dict[str, float]:
    if (
        len(atoms) != 3
        or atoms[0][0].upper() != "O"
        or {atoms[1][0].upper(), atoms[2][0].upper()} != {"H"}
    ):
        raise ValueError("water XYZ must contain O, H, H in that order")
    o = atoms[0][1:]
    h1 = atoms[1][1:]
    h2 = atoms[2][1:]
    oh1 = _distance(o, h1)
    oh2 = _distance(o, h2)
    v1 = [a - b for a, b in zip(h1, o, strict=True)]
    v2 = [a - b for a, b in zip(h2, o, strict=True)]
    cosine = sum(a * b for a, b in zip(v1, v2, strict=True)) / (oh1 * oh2)
    angle = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
    if not (abs(oh1 - 0.9572) <= 0.02 and abs(oh2 - 0.9572) <= 0.02):
        raise ValueError("water O-H lengths do not match CHARMM-modified TIP3P")
    if abs(angle - 104.52) > 2.0:
        raise ValueError("water H-O-H angle does not match CHARMM-modified TIP3P")
    return {"oh1_angstrom": oh1, "oh2_angstrom": oh2, "hoh_degrees": angle}


def generate_water_interaction_job(
    *,
    product_id: str,
    model_id: str,
    model_xyz_path: Path,
    water_xyz_path: Path,
    parent_manifest_path: Path,
    atom_map: Sequence[str],
    probe_id: str,
    target_atom: str,
    probe_atom: str,
    output_dir: Path,
    charge: int = 0,
    multiplicity: int = 1,
    memory_gib: int = 8,
    threads: int = 8,
    scf_type_override: str | None = None,
    scf_calibration_role: str | None = None,
    protocol_path: Path = QM_PROTOCOL_PATH,
) -> dict[str, Any]:
    """Generate one fixed-geometry CHARMM water-interaction target calculation.

    Probe orientation and distance must come from a reviewed input; this function does
    not guess hydrogen-bond sites. A series of such jobs defines the interaction curve.
    """

    protocol = qm_protocol(protocol_path)
    job = protocol["jobs"]["water_interaction"]
    primary_scf_type = job.get("scf_type")
    reference_scf_type = job.get("reference_scf_type")
    if primary_scf_type not in {"df", "direct"}:
        raise ValueError("water protocol must declare a resource-safe DF or DIRECT SCF")
    if reference_scf_type not in {"df", "direct"}:
        raise ValueError("water protocol must declare a DF or DIRECT reference SCF")
    if primary_scf_type == reference_scf_type:
        raise ValueError("primary and reference water SCF algorithms must differ")
    if scf_type_override is None:
        if scf_calibration_role is not None:
            raise ValueError("calibration_role requires an explicit SCF override")
        scf_type = primary_scf_type
        calibration_role = "production"
    else:
        expected_by_role = {
            "candidate": primary_scf_type,
            "reference": reference_scf_type,
        }
        if scf_calibration_role not in expected_by_role:
            raise ValueError(
                "SCF override requires calibration_role candidate or reference"
            )
        if scf_type_override != expected_by_role[scf_calibration_role]:
            raise ValueError(
                f"{scf_calibration_role} water job must use "
                f"{expected_by_role[scf_calibration_role]} SCF"
            )
        scf_type = scf_type_override
        calibration_role = scf_calibration_role
    model_bytes = model_xyz_path.read_bytes()
    model_atoms, model_comment = parse_xyz(model_bytes.decode())
    water_bytes = water_xyz_path.read_bytes()
    water_atoms, water_comment = parse_xyz(water_bytes.decode())
    water_geometry = _water_geometry(water_atoms)
    if len(atom_map) != len(model_atoms) or len(atom_map) != len(set(atom_map)):
        raise ValueError("unique atom_map must match the model XYZ")
    if target_atom not in atom_map:
        raise ValueError("water probe target_atom is absent from the stable atom map")
    water_index = {"O": 0, "H1": 1, "H2": 2}.get(probe_atom)
    if water_index is None:
        raise ValueError("probe_atom must be O, H1, or H2")
    target_index = list(atom_map).index(target_atom)
    target_probe_distance = _distance(
        model_atoms[target_index][1:], water_atoms[water_index][1:]
    )
    if not 1.0 <= target_probe_distance <= 8.0:
        raise ValueError(
            "target-probe distance is outside the reviewed 1-8 angstrom range"
        )
    parent = json.loads(parent_manifest_path.read_text())
    accepted_parent_statuses = {
        "passed_identity_and_chirality",
        "passed_candidate_identity_and_chirality",
    }
    if (
        parent.get("schema") != "nadoc.photoproduct-optimized-model-audit.v1"
        or parent.get("product_id") != product_id
        or parent.get("model_id") != model_id
        or parent.get("status") not in accepted_parent_statuses
        or parent.get("optimized_xyz", {}).get("sha256") != _sha256_bytes(model_bytes)
    ):
        raise ValueError("water job parent audit is not a passed matching model")
    if multiplicity < 1 or memory_gib < 1 or threads < 1:
        raise ValueError("multiplicity, memory_gib, and threads must be positive")
    basis = protocol["rules"]["charged_model_diffuse_basis"] if charge else job["basis"]
    model_block = _coordinates_block(model_atoms)
    water_block = _coordinates_block(water_atoms)
    scale = job["neutral_energy_scale"] if charge == 0 else 1.0
    rendered = f"""# NADOC photoproduct water interaction {protocol["version"]}
# Model: {model_comment}; water: {water_comment}; probe: {probe_id}; target: {target_atom}-{probe_atom}
memory {memory_gib} GB
set_num_threads({threads})

molecule complex {{
  {charge} {multiplicity}
{model_block}
  --
  0 1
{water_block}
  units angstrom
  no_com
  no_reorient
}}

molecule solute {{
  {charge} {multiplicity}
{model_block}
  units angstrom
  no_com
  no_reorient
}}

molecule water {{
  0 1
{water_block}
  units angstrom
  no_com
  no_reorient
}}

set {{
  basis {basis}
  reference {"rhf" if multiplicity == 1 else "uhf"}
  scf_type {scf_type}
}}

e_complex = energy('{job["method"]}', molecule=complex)
e_solute = energy('{job["method"]}', molecule=solute)
e_water = energy('{job["method"]}', molecule=water)
interaction_hartree = e_complex - e_solute - e_water
interaction_kcal_mol = interaction_hartree * 627.5094740631
scaled_target_kcal_mol = interaction_kcal_mol * {scale:.12f}
print_out('NADOC_WATER_INTERACTION_HARTREE %.14f\\n' % interaction_hartree)
print_out('NADOC_WATER_INTERACTION_KCAL_MOL %.10f\\n' % interaction_kcal_mol)
print_out('NADOC_WATER_TARGET_KCAL_MOL %.10f\\n' % scaled_target_kcal_mol)
"""
    output_dir.mkdir(parents=True, exist_ok=True)
    input_path = output_dir / "input.dat"
    manifest_path = output_dir / "job_manifest.json"
    if input_path.exists() or manifest_path.exists():
        raise FileExistsError(f"refusing to overwrite water job in {output_dir}")
    input_path.write_text(rendered)
    manifest = {
        "schema": "nadoc.photoproduct-qm-job.v1",
        "status": "generated_not_run",
        "gate_effect": "none",
        "product_id": product_id,
        "model_id": model_id,
        "job_kind": "water_interaction",
        "method": job["method"],
        "basis": basis,
        "scf_type": scf_type,
        "scf_calibration_role": calibration_role,
        "charge": charge,
        "multiplicity": multiplicity,
        "atom_count": len(model_atoms) + 3,
        "solute_atom_count": len(model_atoms),
        "memory_gib": memory_gib,
        "threads": threads,
        "protocol_version": protocol["version"],
        "protocol_sha256": _sha256_bytes(protocol_path.read_bytes()),
        "probe_id": probe_id,
        "target_atom": target_atom,
        "probe_atom": probe_atom,
        "target_probe_distance_angstrom": target_probe_distance,
        "water_geometry": water_geometry,
        "energy_scale": scale,
        "distance_offset_angstrom": job["distance_offset_angstrom"],
        "counterpoise_corrected": job["counterpoise_corrected"],
        "source_xyz": {
            "path": str(model_xyz_path),
            "sha256": _sha256_bytes(model_bytes),
        },
        "water_xyz": {
            "path": str(water_xyz_path),
            "sha256": _sha256_bytes(water_bytes),
        },
        "parent_manifest": {
            "path": str(parent_manifest_path.resolve()),
            "sha256": _sha256_bytes(parent_manifest_path.read_bytes()),
        },
        "atom_map": list(atom_map),
        "input": {"path": str(input_path), "sha256": _sha256_bytes(rendered.encode())},
        "expected_outputs": ["output.dat"],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def parse_water_interaction_output(text: str) -> dict[str, float | bool | None]:
    """Parse explicit NADOC markers without treating generic SCF energies as targets."""

    raw_hartree = _last_float(
        r"^\s*NADOC_WATER_INTERACTION_HARTREE\s+(-?\d+\.\d+(?:[Ee][+-]?\d+)?)",
        text,
    )
    raw_kcal = _last_float(
        r"^\s*NADOC_WATER_INTERACTION_KCAL_MOL\s+(-?\d+\.\d+(?:[Ee][+-]?\d+)?)",
        text,
    )
    scaled = _last_float(
        r"^\s*NADOC_WATER_TARGET_KCAL_MOL\s+(-?\d+\.\d+(?:[Ee][+-]?\d+)?)",
        text,
    )
    return {
        "interaction_hartree": raw_hartree,
        "interaction_kcal_mol": raw_kcal,
        "scaled_target_kcal_mol": scaled,
        "complete": all(value is not None for value in (raw_hartree, raw_kcal, scaled)),
    }


def audit_water_scf_calibration(
    job_dirs: Sequence[Path],
    *,
    output_path: Path,
    protocol_path: Path = QM_PROTOCOL_PATH,
) -> dict[str, Any]:
    """Compare identical-geometry DF and DIRECT water energies.

    This audit establishes whether the resource-safe production SCF approximation is
    numerically interchangeable with the declared reference for the sampled sites. It
    remains fitting evidence and never advances a product registry gate by itself.
    """

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite water-SCF calibration audit: {output_path}"
        )
    protocol_bytes = protocol_path.read_bytes()
    protocol = qm_protocol(protocol_path)
    policy = protocol["jobs"]["water_interaction"]
    primary_scf = policy["scf_type"]
    reference_scf = policy["reference_scf_type"]
    calibration = policy["df_calibration"]
    minimum_sites = int(calibration["minimum_sites"])
    tolerance = float(calibration["maximum_absolute_interaction_error_kcal_mol"])
    errors: list[str] = []
    records: dict[tuple[Any, ...], dict[str, dict[str, Any]]] = {}
    common_identity: tuple[Any, ...] | None = None
    expected_protocol_hash = _sha256_bytes(protocol_bytes)
    for job_dir in job_dirs:
        job_path = job_dir / "job_manifest.json"
        run_path = job_dir / "run_manifest.json"
        output_dat = job_dir / "output.dat"
        if not all(path.is_file() for path in (job_path, run_path, output_dat)):
            errors.append(f"{job_dir}: job, run, and output files are required")
            continue
        job = json.loads(job_path.read_text())
        run = json.loads(run_path.read_text())
        if (
            job.get("schema") != "nadoc.photoproduct-qm-job.v1"
            or job.get("job_kind") != "water_interaction"
        ):
            errors.append(f"{job_dir}: not a water-interaction job")
            continue
        role = job.get("scf_calibration_role")
        scf_type = job.get("scf_type")
        expected_scf = {"candidate": primary_scf, "reference": reference_scf}.get(role)
        if expected_scf is None or scf_type != expected_scf:
            errors.append(f"{job_dir}: invalid SCF calibration role/type")
            continue
        if job.get("protocol_sha256") != expected_protocol_hash:
            errors.append(f"{job_dir}: job does not use the audited QM protocol")
        if run.get("status") != "completed_unreviewed" or run.get(
            "job_manifest_sha256"
        ) != _sha256_bytes(job_path.read_bytes()):
            errors.append(f"{job_dir}: QM run is incomplete or hash-mismatched")
        if run.get("outputs", {}).get("output.dat", {}).get("sha256") != _sha256_bytes(
            output_dat.read_bytes()
        ):
            errors.append(f"{job_dir}: raw output digest mismatch")
        parsed = parse_water_interaction_output(
            output_dat.read_text(errors="replace")
            + "\n"
            + str(run.get("stdout_tail") or "")
        )
        if not parsed["complete"]:
            errors.append(f"{job_dir}: interaction-energy markers are incomplete")
            continue
        identity = (
            job.get("product_id"),
            job.get("model_id"),
            job.get("method"),
            job.get("basis"),
            job.get("charge"),
            job.get("multiplicity"),
            job.get("source_xyz", {}).get("sha256"),
        )
        if common_identity is None:
            common_identity = identity
        elif identity != common_identity:
            errors.append(f"{job_dir}: model/method identity differs from earlier jobs")
        pair_key = (
            job.get("probe_id"),
            job.get("target_atom"),
            job.get("probe_atom"),
            job.get("target_probe_distance_angstrom"),
            job.get("water_xyz", {}).get("sha256"),
        )
        by_role = records.setdefault(pair_key, {})
        if role in by_role:
            errors.append(f"{job_dir}: duplicate {role} result for a geometry")
            continue
        by_role[role] = {
            "job_dir": str(job_dir.resolve()),
            "job_manifest_sha256": _sha256_bytes(job_path.read_bytes()),
            "output_sha256": _sha256_bytes(output_dat.read_bytes()),
            "interaction_kcal_mol": parsed["interaction_kcal_mol"],
            "scf_type": scf_type,
        }
    comparisons: list[dict[str, Any]] = []
    for key, by_role in sorted(records.items(), key=lambda item: str(item[0])):
        if set(by_role) != {"candidate", "reference"}:
            errors.append(f"unpaired calibration geometry: {key}")
            continue
        candidate = by_role["candidate"]
        reference = by_role["reference"]
        absolute_error = abs(
            float(candidate["interaction_kcal_mol"])
            - float(reference["interaction_kcal_mol"])
        )
        comparisons.append(
            {
                "probe_id": key[0],
                "target_atom": key[1],
                "probe_atom": key[2],
                "distance_angstrom": key[3],
                "water_xyz_sha256": key[4],
                "candidate": candidate,
                "reference": reference,
                "absolute_error_kcal_mol": absolute_error,
                "within_tolerance": absolute_error <= tolerance,
            }
        )
    distinct_sites = {item["probe_id"] for item in comparisons}
    if len(distinct_sites) < minimum_sites:
        errors.append(
            f"calibration covers {len(distinct_sites)} sites; {minimum_sites} required"
        )
    if any(not item["within_tolerance"] for item in comparisons):
        errors.append("one or more DF/DIRECT interaction errors exceed tolerance")
    report = {
        "schema": "nadoc.photoproduct-water-scf-calibration-audit.v1",
        "status": "passed_candidate" if not errors else "failed",
        "passed": not errors,
        "gate_effect": "none",
        "protocol": {
            "path": str(protocol_path.resolve()),
            "sha256": expected_protocol_hash,
            "version": protocol["version"],
        },
        "candidate_scf_type": primary_scf,
        "reference_scf_type": reference_scf,
        "minimum_distinct_sites": minimum_sites,
        "maximum_absolute_interaction_error_kcal_mol": tolerance,
        "distinct_site_count": len(distinct_sites),
        "comparisons": comparisons,
        "maximum_observed_absolute_error_kcal_mol": (
            max(item["absolute_error_kcal_mol"] for item in comparisons)
            if comparisons
            else None
        ),
        "errors": errors,
        "release_note": (
            "Passing validates the declared SCF approximation for these sampled "
            "interaction targets only; it does not validate charges or pass a product gate."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def audit_water_interaction_series(
    job_dirs: Sequence[Path], *, output_path: Path
) -> dict[str, Any]:
    """Audit a distance series and require that its interaction minimum is bracketed."""

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite water-series audit: {output_path}"
        )
    errors: list[str] = []
    points: list[dict[str, Any]] = []
    identity: tuple[Any, ...] | None = None
    for job_dir in job_dirs:
        job_path = job_dir / "job_manifest.json"
        run_path = job_dir / "run_manifest.json"
        raw_path = job_dir / "output.dat"
        if not all(path.is_file() for path in (job_path, run_path, raw_path)):
            errors.append(f"{job_dir}: job, run, and output files are required")
            continue
        job = json.loads(job_path.read_text())
        run = json.loads(run_path.read_text())
        if (
            job.get("schema") != "nadoc.photoproduct-qm-job.v1"
            or job.get("job_kind") != "water_interaction"
        ):
            errors.append(f"{job_dir}: not a water-interaction job")
            continue
        if run.get("job_manifest_sha256") != _sha256_bytes(job_path.read_bytes()):
            errors.append(f"{job_dir}: run/job digest mismatch")
        if run.get("outputs", {}).get("output.dat", {}).get("sha256") != _sha256_bytes(
            raw_path.read_bytes()
        ):
            errors.append(f"{job_dir}: raw output digest mismatch")
        if run.get("status") != "completed_unreviewed":
            errors.append(f"{job_dir}: QM run did not complete")
        item_identity = (
            job.get("product_id"),
            job.get("model_id"),
            job.get("probe_id"),
            job.get("target_atom"),
            job.get("probe_atom"),
            job.get("protocol_sha256"),
        )
        if identity is None:
            identity = item_identity
        elif item_identity != identity:
            errors.append(f"{job_dir}: series identity differs from earlier points")
        parsed = parse_water_interaction_output(
            raw_path.read_text(errors="replace")
            + "\n"
            + str(run.get("stdout_tail") or "")
        )
        if not parsed["complete"]:
            errors.append(f"{job_dir}: NADOC water-interaction markers are incomplete")
        distance = job.get("target_probe_distance_angstrom")
        if not isinstance(distance, (int, float)) or not math.isfinite(float(distance)):
            errors.append(f"{job_dir}: target-probe distance is missing")
            continue
        points.append(
            {
                "job_dir": str(job_dir.resolve()),
                "job_manifest_sha256": _sha256_bytes(job_path.read_bytes()),
                "output_sha256": _sha256_bytes(raw_path.read_bytes()),
                "distance_angstrom": float(distance),
                **parsed,
            }
        )
    points.sort(key=lambda item: item["distance_angstrom"])
    distances = [point["distance_angstrom"] for point in points]
    if len(points) < 5:
        errors.append("at least five completed distance points are required")
    if len(set(distances)) != len(distances):
        errors.append("water-interaction distances must be unique")
    if distances and max(distances) - min(distances) < 0.8 - 1e-9:
        errors.append("water-interaction distance series spans less than 0.8 angstrom")
    if (
        len(distances) > 1
        and max(second - first for first, second in zip(distances, distances[1:]))
        > 0.25 + 1e-9
    ):
        errors.append("water-interaction distance spacing exceeds 0.25 angstrom")
    energies = [point["interaction_kcal_mol"] for point in points]
    minimum_index = None
    if energies and all(isinstance(value, (int, float)) for value in energies):
        minimum_index = min(range(len(energies)), key=energies.__getitem__)
        if minimum_index in {0, len(energies) - 1}:
            errors.append(
                "water-interaction minimum is not bracketed by the distance series"
            )
    report = {
        "schema": "nadoc.photoproduct-water-interaction-series-audit.v1",
        "status": "complete_candidate" if not errors else "incomplete",
        "passed": not errors,
        "gate_effect": "none",
        "identity": (
            dict(
                zip(
                    (
                        "product_id",
                        "model_id",
                        "probe_id",
                        "target_atom",
                        "probe_atom",
                        "protocol_sha256",
                    ),
                    identity,
                    strict=True,
                )
            )
            if identity is not None
            else {}
        ),
        "points": points,
        "minimum_point_index": minimum_index,
        "errors": errors,
        "release_note": (
            "A complete curve is one charge-fit target only; it does not validate charges "
            "or advance a registry gate."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def _dihedral_degrees(
    first: Sequence[float],
    second: Sequence[float],
    third: Sequence[float],
    fourth: Sequence[float],
) -> float:
    """Return the signed IUPAC-style dihedral in ``[-180, 180]`` degrees."""

    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - normal NADOC env includes numpy
        raise RuntimeError("numpy is required for torsion geometry checks") from exc
    p0, p1, p2, p3 = (
        np.asarray(point, dtype=float) for point in (first, second, third, fourth)
    )
    b0 = -(p1 - p0)
    b1 = p2 - p1
    b2 = p3 - p2
    norm = float(np.linalg.norm(b1))
    if norm <= 1e-12:
        raise ValueError("torsion central bond has zero length")
    b1 /= norm
    v = b0 - np.dot(b0, b1) * b1
    w = b2 - np.dot(b2, b1) * b1
    if float(np.linalg.norm(v)) <= 1e-12 or float(np.linalg.norm(w)) <= 1e-12:
        raise ValueError("torsion is undefined for collinear atoms")
    return math.degrees(
        math.atan2(float(np.dot(np.cross(b1, v), w)), float(np.dot(v, w)))
    )


def _circular_difference_degrees(first: float, second: float) -> float:
    return abs((first - second + 180.0) % 360.0 - 180.0)


def _torsion_central_bond_context(
    *, plan: dict[str, Any], atom_map: list[str], torsion_atoms: list[str]
) -> dict[str, Any]:
    """Prove that a proposed torsion has a real, acyclic, single central bond."""

    graph_record = plan.get("model_graph")
    if not isinstance(graph_record, dict):
        raise ValueError("torsion scan plan requires a hash-pinned model graph")
    graph_path = Path(str(graph_record.get("path") or ""))
    if not graph_path.is_file() or _sha256_bytes(
        graph_path.read_bytes()
    ) != graph_record.get("sha256"):
        raise ValueError("torsion scan model graph is missing or hash-mismatched")
    graph = json.loads(graph_path.read_text())
    atoms = graph.get("atoms") or []
    graph_keys = [item.get("key") for item in atoms]
    if (
        graph.get("schema") != "nadoc.photoproduct-model-graph.v1"
        or graph_keys != atom_map
        or len(graph_keys) != len(set(graph_keys))
    ):
        raise ValueError(
            "torsion scan model graph identity/order differs from atom_map"
        )
    edges: dict[frozenset[str], float] = {}
    adjacency = {key: set() for key in graph_keys}
    for record in graph.get("bonds") or []:
        keys = record.get("atoms") or []
        order = record.get("order")
        if (
            len(keys) != 2
            or keys[0] not in adjacency
            or keys[1] not in adjacency
            or keys[0] == keys[1]
            or not isinstance(order, (int, float))
        ):
            raise ValueError("torsion scan model graph contains a malformed bond")
        edge = frozenset(keys)
        if edge in edges:
            raise ValueError("torsion scan model graph contains a duplicate bond")
        edges[edge] = float(order)
        adjacency[keys[0]].add(keys[1])
        adjacency[keys[1]].add(keys[0])
    central = torsion_atoms[1:3]
    central_edge = frozenset(central)
    if central_edge not in edges:
        raise ValueError("torsion atoms do not identify a bonded central pair")
    order = edges[central_edge]
    if abs(order - 1.0) > 1.0e-8:
        raise ValueError(
            "independent torsion scans require an acyclic single central bond"
        )
    # An edge belongs to a cycle exactly when its endpoints remain connected after it
    # is removed. This graph test avoids inferring scanability from atom names/types.
    seen = {central[0]}
    pending = [central[0]]
    while pending:
        current = pending.pop()
        for neighbor in adjacency[current]:
            if frozenset((current, neighbor)) == central_edge or neighbor in seen:
                continue
            seen.add(neighbor)
            pending.append(neighbor)
    in_cycle = central[1] in seen
    if in_cycle:
        raise ValueError(
            "independent torsion scans are forbidden for cyclic central bonds; use "
            "stereochemistry-preserving coupled conformer/Hessian targets"
        )
    return {
        "central_bond": central,
        "central_bond_order": order,
        "central_bond_in_cycle": False,
        "model_graph": {
            "path": str(graph_path.resolve()),
            "sha256": _sha256_bytes(graph_path.read_bytes()),
        },
    }


def generate_torsion_scan_job(
    *,
    scan_plan_path: Path,
    point_id: str,
    xyz_path: Path,
    output_dir: Path,
    memory_gib: int = 8,
    threads: int = 8,
    protocol_path: Path = QM_PROTOCOL_PATH,
) -> dict[str, Any]:
    """Generate one constrained-relaxation point from an explicit reviewed plan.

    The plan, including every starting geometry and target angle, is external evidence.
    This function never rotates a molecule or guesses which side of a bond should move.
    """

    plan_bytes = scan_plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    if plan.get("schema") != "nadoc.photoproduct-torsion-scan-plan.v2":
        raise ValueError("unsupported torsion scan plan schema")
    for field in ("product_id", "model_id", "reviewed_by", "review_rationale"):
        if not plan.get(field):
            raise ValueError(f"torsion scan plan is missing {field}")
    atom_map = plan.get("atom_map")
    torsion_atoms = plan.get("torsion_atoms")
    if (
        not isinstance(atom_map, list)
        or len(atom_map) != len(set(atom_map))
        or not isinstance(torsion_atoms, list)
        or len(torsion_atoms) != 4
        or len(torsion_atoms) != len(set(torsion_atoms))
        or not set(torsion_atoms).issubset(atom_map)
    ):
        raise ValueError(
            "scan plan requires a unique atom map and four mapped torsion atoms"
        )
    central_bond_context = _torsion_central_bond_context(
        plan=plan, atom_map=atom_map, torsion_atoms=torsion_atoms
    )
    points = plan.get("points") or []
    point = next((item for item in points if item.get("id") == point_id), None)
    if point is None or sum(item.get("id") == point_id for item in points) != 1:
        raise ValueError(f"torsion point {point_id!r} is absent or duplicated")
    target = point.get("target_degrees")
    if not isinstance(target, (int, float)) or not math.isfinite(float(target)):
        raise ValueError("torsion target angle must be finite")
    xyz_bytes = xyz_path.read_bytes()
    if point.get("xyz_sha256") != _sha256_bytes(xyz_bytes):
        raise ValueError("torsion point XYZ digest does not match the reviewed plan")
    atoms, comment = parse_xyz(xyz_bytes.decode())
    if len(atoms) != len(atom_map):
        raise ValueError(
            "torsion point atom count does not match the scan plan atom map"
        )
    indices = [atom_map.index(key) for key in torsion_atoms]
    start_angle = _dihedral_degrees(*(atoms[index][1:] for index in indices))
    tolerance = float(plan.get("starting_angle_tolerance_degrees", 2.0))
    if not 0 < tolerance <= 10:
        raise ValueError("starting angle tolerance must be in (0, 10] degrees")
    if _circular_difference_degrees(start_angle, float(target)) > tolerance:
        raise ValueError(
            f"starting torsion {start_angle:.4f} differs from target {float(target):.4f} "
            f"by more than {tolerance:.4f} degrees"
        )
    charge = plan.get("charge")
    multiplicity = plan.get("multiplicity")
    if (
        not isinstance(charge, int)
        or not isinstance(multiplicity, int)
        or multiplicity < 1
    ):
        raise ValueError("scan plan charge/multiplicity are invalid")
    if memory_gib < 1 or threads < 1:
        raise ValueError("memory_gib and threads must be positive")
    protocol = qm_protocol(protocol_path)
    job = protocol["jobs"]["torsion_scan"]
    basis = protocol["rules"]["charged_model_diffuse_basis"] if charge else job["basis"]
    coordinates = _coordinates_block(atoms)
    one_based = [index + 1 for index in indices]
    rendered = f"""# NADOC photoproduct torsion scan {protocol["version"]}
# Plan: {scan_plan_path.name}; point: {point_id}; source: {comment}
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
  scf_type df
  mp2_type df
  freeze_core true
  g_convergence gau_tight
}}

set optking {{
  frozen_dihedral = ("
    {" ".join(str(index) for index in one_based)}
  ")
}}

energy, wavefunction = optimize('{job["method"]}', return_wfn=True)
model.save_xyz_file('optimized.xyz', True)
print_out('NADOC_TORSION_TARGET_DEGREES %.8f\\n' % {float(target):.8f})
print_out('NADOC_TORSION_ENERGY_HARTREE %.14f\\n' % energy)
"""
    output_dir.mkdir(parents=True, exist_ok=True)
    input_path = output_dir / "input.dat"
    manifest_path = output_dir / "job_manifest.json"
    if input_path.exists() or manifest_path.exists():
        raise FileExistsError(f"refusing to overwrite torsion job in {output_dir}")
    input_path.write_text(rendered)
    manifest = {
        "schema": "nadoc.photoproduct-qm-job.v1",
        "status": "generated_not_run",
        "gate_effect": "none",
        "product_id": plan["product_id"],
        "model_id": plan["model_id"],
        "job_kind": "torsion_scan",
        "point_id": point_id,
        "method": job["method"],
        "basis": basis,
        "charge": charge,
        "multiplicity": multiplicity,
        "atom_count": len(atoms),
        "atom_map": atom_map,
        "torsion_atoms": torsion_atoms,
        "torsion_atom_indices_one_based": one_based,
        "central_bond_context": central_bond_context,
        "target_degrees": float(target),
        "starting_degrees": start_angle,
        "starting_angle_tolerance_degrees": tolerance,
        "memory_gib": memory_gib,
        "threads": threads,
        "protocol_version": protocol["version"],
        "protocol_sha256": _sha256_bytes(protocol_path.read_bytes()),
        "scan_plan": {
            "path": str(scan_plan_path.resolve()),
            "sha256": _sha256_bytes(plan_bytes),
        },
        "source_xyz": {
            "path": str(xyz_path.resolve()),
            "sha256": _sha256_bytes(xyz_bytes),
        },
        "input": {
            "path": str(input_path.resolve()),
            "sha256": _sha256_bytes(rendered.encode()),
        },
        "expected_outputs": ["output.dat", "optimized.xyz"],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def _last_float(pattern: str, text: str) -> float | None:
    matches = re.findall(pattern, text, flags=re.MULTILINE)
    return float(matches[-1]) if matches else None


def parse_psi4_output(text: str, job_kind: str) -> dict[str, Any]:
    """Extract a compact, non-authoritative completion record from Psi4 output."""

    success = "Psi4 exiting successfully" in text
    optimization_complete = any(
        marker in text
        for marker in (
            "Optimization is complete",
            "Optimizer: Optimization complete",
            # Psi4 1.11/OptKing prints this section only after satisfying the
            # convergence criteria, then writes optimized.xyz before a clean exit.
            "Final optimized geometry and variables",
        )
    )
    energy = _last_float(
        r"^\s*(?:DF-)?MP2 Total Energy\s*=\s*(-?\d+\.\d+(?:[Ee][+-]?\d+)?)",
        text,
    )
    if energy is None:
        energy = _last_float(r"^\s*Final Energy:\s+(-?\d+\.\d+(?:[Ee][+-]?\d+)?)", text)
    if energy is None:
        energy = _last_float(
            r"^\s*Total Energy\s+=\s+(-?\d+\.\d+(?:[Ee][+-]?\d+)?)", text
        )
    optimization_job = job_kind in {"geometry_optimization", "torsion_scan"}
    passed = success and (not optimization_job or optimization_complete)
    return {
        "psi4_success_exit": success,
        "optimization_complete": optimization_complete if optimization_job else None,
        "final_energy_hartree": energy,
        "passed_execution_checks": passed,
    }


def parse_vibrational_frequencies(text: str) -> list[dict[str, Any]]:
    """Parse Psi4's final projected harmonic frequency rows.

    Psi4 prints negative Hessian eigenvalues as a positive magnitude followed by
    ``i``. Keeping that marker separately avoids treating an imaginary mode as a
    merely low positive frequency.
    """

    frequencies: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = re.match(r"^\s*Freq\s+\[cm\^-1\]\s+(.+?)\s*$", line)
        if not match:
            continue
        for token in match.group(1).split():
            value_match = re.fullmatch(
                r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)(i?)",
                token,
            )
            if not value_match:
                raise ValueError(f"unrecognized Psi4 frequency token: {token!r}")
            magnitude = float(value_match.group(1))
            imaginary = value_match.group(2) == "i"
            frequencies.append(
                {
                    "value_cm_inverse": -abs(magnitude) if imaginary else magnitude,
                    "imaginary": imaginary,
                    "printed_token": token,
                }
            )
    return frequencies


def parse_electrostatic_properties_output(text: str) -> dict[str, Any]:
    matches = re.findall(
        r"^\s*NADOC_DIPOLE_AU\s+"
        r"(-?\d+\.\d+(?:[Ee][+-]?\d+)?)\s+"
        r"(-?\d+\.\d+(?:[Ee][+-]?\d+)?)\s+"
        r"(-?\d+\.\d+(?:[Ee][+-]?\d+)?)\s*$",
        text,
        flags=re.MULTILINE,
    )
    vector = [float(value) for value in matches[-1]] if matches else None
    return {
        "dipole_au": vector,
        "dipole_magnitude_au": (
            math.sqrt(sum(value * value for value in vector)) if vector else None
        ),
        "complete": vector is not None
        and all(math.isfinite(value) for value in vector),
    }


def run_psi4_job(
    *,
    job_dir: Path,
    psi4_executable: Path,
    scratch_dir: Path,
) -> dict[str, Any]:
    """Run one generated job and record immutable inputs and compact output hashes.

    Completion remains unreviewed and has no automatic gate effect. Re-running an
    existing result is rejected so raw evidence cannot be overwritten accidentally.
    """

    manifest_path = job_dir / "job_manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"missing generated job manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != "nadoc.photoproduct-qm-job.v1":
        raise ValueError("unsupported QM job manifest schema")
    model_record = manifest.get("model_manifest") or {}
    if model_record.get(
        "schema"
    ) == "nadoc.photoproduct-dna-boundary-model-candidate.v1" and model_record.get(
        "evidence_status"
    ) not in {"human_cap_review_complete", "quantitatively_screened_boundary"}:
        raise ValueError(
            "DNA-boundary QM execution requires a hash-pinned approved cap/protonation "
            "review or quantitative input screen"
        )
    input_path = job_dir / "input.dat"
    if not input_path.is_file():
        raise ValueError(f"missing generated Psi4 input: {input_path}")
    input_hash = _sha256_bytes(input_path.read_bytes())
    if input_hash != manifest["input"]["sha256"]:
        raise ValueError("Psi4 input digest no longer matches the job manifest")
    output_path = job_dir / "output.dat"
    run_manifest_path = job_dir / "run_manifest.json"
    if output_path.exists() or run_manifest_path.exists():
        raise FileExistsError(f"refusing to overwrite existing QM result in {job_dir}")
    if not psi4_executable.is_file():
        raise ValueError(f"Psi4 executable not found: {psi4_executable}")
    scratch_dir.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["PSI_SCRATCH"] = str(scratch_dir.resolve())
    completed = subprocess.run(
        [str(psi4_executable), str(input_path), str(output_path)],
        cwd=job_dir,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    output_text = (
        output_path.read_text(errors="replace") if output_path.exists() else ""
    )
    parsed = parse_psi4_output(
        output_text + "\n" + completed.stdout, manifest["job_kind"]
    )
    outputs: dict[str, Any] = {}
    # Old, immutable generated manifests may predate a newly recorded artifact.
    # Job-kind defaults make the runner backward-compatible without rewriting
    # provenance-bearing inputs/manifests while still hashing every known result.
    expected_names = (
        set(manifest.get("expected_outputs") or [])
        | _KNOWN_JOB_OUTPUTS.get(str(manifest.get("job_kind")), set())
        | {"output.dat"}
    )
    if any(Path(name).name != name for name in expected_names):
        raise ValueError("QM expected output names must be plain basenames")
    for path in (job_dir / name for name in sorted(expected_names)):
        if path.is_file():
            outputs[path.name] = {
                "path": str(path.resolve()),
                "sha256": _sha256_bytes(path.read_bytes()),
                "bytes": path.stat().st_size,
            }
    run_record = {
        "schema": "nadoc.photoproduct-qm-run.v1",
        "status": "completed_unreviewed"
        if completed.returncode == 0 and parsed["passed_execution_checks"]
        else "failed",
        "gate_effect": "none",
        "job_manifest_sha256": _sha256_bytes(manifest_path.read_bytes()),
        "command": [str(psi4_executable.resolve()), "input.dat", "output.dat"],
        "scratch_dir": str(scratch_dir.resolve()),
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
        "parsed": parsed,
        "outputs": outputs,
    }
    run_manifest_path.write_text(json.dumps(run_record, indent=2) + "\n")
    return run_record


def build_qm_job_series(
    job_dirs: Sequence[Path], *, output_path: Path
) -> dict[str, Any]:
    """Hash-link already generated jobs into a generic resumable series."""

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite QM job series: {output_path}")
    resolved = [path.resolve() for path in job_dirs]
    if not resolved or len(resolved) != len(set(resolved)):
        raise ValueError("QM job series requires unique job directories")
    records = []
    kinds = set()
    for index, job_dir in enumerate(resolved):
        job_path = job_dir / "job_manifest.json"
        if not job_path.is_file():
            raise ValueError(f"QM series job {index} has no manifest: {job_path}")
        job = json.loads(job_path.read_text())
        if job.get("schema") != "nadoc.photoproduct-qm-job.v1":
            raise ValueError(f"QM series job {index} has an unsupported schema")
        kinds.add(job.get("job_kind"))
        records.append(
            {
                "job_dir": str(job_dir),
                "job_manifest_sha256": _sha256_bytes(job_path.read_bytes()),
                "product_id": job.get("product_id"),
                "job_kind": job.get("job_kind"),
            }
        )
    if len(kinds) != 1:
        raise ValueError("generic QM series jobs must have one common job kind")
    manifest = {
        "schema": "nadoc.photoproduct-qm-job-series.v1",
        "status": "generated_not_run",
        "gate_effect": "none",
        "job_kind": next(iter(kinds)),
        "jobs": records,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def run_psi4_series(
    *,
    series_manifest_path: Path,
    psi4_executable: Path,
    scratch_root: Path,
    max_parallel: int = 1,
) -> dict[str, Any]:
    """Run or verify every child of a hash-linked generated QM series."""

    if not 1 <= max_parallel <= 16:
        raise ValueError("max_parallel must be in [1, 16]")
    series_bytes = series_manifest_path.read_bytes()
    series = json.loads(series_bytes)
    if series.get("schema") not in {
        "nadoc.photoproduct-water-probe-series.v1",
        "nadoc.photoproduct-torsion-series.v1",
        "nadoc.photoproduct-qm-job-series.v1",
    }:
        raise ValueError("unsupported QM series manifest schema")
    result_path = series_manifest_path.with_name("series_run_manifest.json")
    if result_path.exists():
        raise FileExistsError(f"refusing to overwrite QM series run: {result_path}")
    child_records: list[tuple[int, Path, dict[str, Any]]] = []
    for index, record in enumerate(series.get("jobs") or []):
        job_dir = Path(str(record.get("job_dir") or ""))
        job_path = job_dir / "job_manifest.json"
        if not job_path.is_file() or _sha256_bytes(job_path.read_bytes()) != record.get(
            "job_manifest_sha256"
        ):
            raise ValueError(f"QM series child {index} is missing or hash-mismatched")
        job = json.loads(job_path.read_text())
        if job.get("job_kind") == "water_interaction" and job.get("scf_type") not in {
            "df",
            "direct",
        }:
            raise ValueError(
                f"QM series child {index} uses an unsafe or unrecorded water SCF "
                "algorithm; regenerate with the current DF/DIRECT protocol"
            )
        child_records.append((index, job_dir, record))
    if not child_records:
        raise ValueError("QM series contains no jobs")
    scratch_root.mkdir(parents=True, exist_ok=True)

    def execute(item: tuple[int, Path, dict[str, Any]]) -> dict[str, Any]:
        index, job_dir, record = item
        run_path = job_dir / "run_manifest.json"
        reused = False
        if run_path.is_file():
            run = json.loads(run_path.read_text())
            if (
                run.get("status") != "completed_unreviewed"
                or run.get("job_manifest_sha256") != record["job_manifest_sha256"]
            ):
                raise ValueError(
                    f"existing QM series child run is not reusable: {job_dir}"
                )
            for name, output in (run.get("outputs") or {}).items():
                path = job_dir / name
                if not path.is_file() or _sha256_bytes(path.read_bytes()) != output.get(
                    "sha256"
                ):
                    raise ValueError(
                        f"existing QM child output is hash-mismatched: {path}"
                    )
            reused = True
        else:
            scratch_dir = scratch_root / f"job-{index:04d}"
            run = run_psi4_job(
                job_dir=job_dir,
                psi4_executable=psi4_executable,
                scratch_dir=scratch_dir,
            )
            if run["status"] == "completed_unreviewed" and scratch_dir.is_dir():
                shutil.rmtree(scratch_dir)
        return {
            "index": index,
            "job_dir": str(job_dir.resolve()),
            "status": run["status"],
            "reused": reused,
            "run_manifest_sha256": _sha256_bytes(run_path.read_bytes()),
            "returncode": run.get("returncode"),
            "scratch_retained": bool((scratch_root / f"job-{index:04d}").exists()),
        }

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    stopped_early = False
    submitted_count = 0
    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        record_iterator = iter(child_records)
        future_by_item: dict[Any, tuple[int, Path, dict[str, Any]]] = {}

        def submit_one() -> bool:
            nonlocal submitted_count
            try:
                item = next(record_iterator)
            except StopIteration:
                return False
            future_by_item[pool.submit(execute, item)] = item
            submitted_count += 1
            return True

        for _ in range(min(max_parallel, len(child_records))):
            submit_one()
        while future_by_item:
            done, _pending = wait(tuple(future_by_item), return_when=FIRST_COMPLETED)
            batch_failed = False
            for future in done:
                item = future_by_item.pop(future)
                index = item[0]
                try:
                    result = future.result()
                    results.append(result)
                    if result["status"] != "completed_unreviewed":
                        errors.append(
                            f"child {index}: QM execution status {result['status']}"
                        )
                        batch_failed = True
                except Exception as exc:  # preserve completed child evidence
                    errors.append(f"child {index}: {type(exc).__name__}: {exc}")
                    batch_failed = True
            if batch_failed:
                stopped_early = True
            if not stopped_early:
                while len(future_by_item) < max_parallel and submit_one():
                    pass
        # No new children are submitted after the first observed failure. Jobs that
        # were already running finish and retain their evidence.
    results.sort(key=lambda item: item["index"])
    incomplete = [item for item in results if item["status"] != "completed_unreviewed"]
    report = {
        "schema": "nadoc.photoproduct-qm-series-run.v1",
        "status": "completed_unreviewed" if not errors and not incomplete else "failed",
        "gate_effect": "none",
        "series_manifest": {
            "path": str(series_manifest_path.resolve()),
            "sha256": _sha256_bytes(series_bytes),
        },
        "psi4_executable": str(psi4_executable.resolve()),
        "scratch_root": str(scratch_root.resolve()),
        "max_parallel": max_parallel,
        "job_count": len(child_records),
        "submitted_count": submitted_count,
        "not_started_count": len(child_records) - submitted_count,
        "stopped_early": stopped_early,
        "completed_count": sum(
            item["status"] == "completed_unreviewed" for item in results
        ),
        "reused_count": sum(bool(item["reused"]) for item in results),
        "children": results,
        "errors": errors,
    }
    result_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def reconcile_psi4_run(job_dir: Path) -> dict[str, Any]:
    """Create a non-destructive corrected parse for an existing raw run record."""

    job_path = job_dir / "job_manifest.json"
    run_path = job_dir / "run_manifest.json"
    output_path = job_dir / "output.dat"
    reconciliation_path = job_dir / "run_reconciliation.json"
    if reconciliation_path.exists():
        raise FileExistsError(
            f"refusing to overwrite existing reconciliation: {reconciliation_path}"
        )
    if not all(path.is_file() for path in (job_path, run_path, output_path)):
        raise ValueError("job manifest, run manifest, and output.dat are required")
    job = json.loads(job_path.read_text())
    original = json.loads(run_path.read_text())
    if original.get("job_manifest_sha256") != _sha256_bytes(job_path.read_bytes()):
        raise ValueError("original run does not match the job manifest")
    output_hash = _sha256_bytes(output_path.read_bytes())
    if original.get("outputs", {}).get("output.dat", {}).get("sha256") != output_hash:
        raise ValueError("raw output hash does not match the original run manifest")
    parsed = parse_psi4_output(
        output_path.read_text(errors="replace")
        + "\n"
        + str(original.get("stdout_tail") or ""),
        job["job_kind"],
    )
    outputs: dict[str, Any] = {}
    expected_names = (
        set(job.get("expected_outputs") or [])
        | _KNOWN_JOB_OUTPUTS.get(str(job.get("job_kind")), set())
        | {"output.dat"}
    )
    if any(Path(name).name != name for name in expected_names):
        raise ValueError("QM expected output names must be plain basenames")
    for candidate in (job_dir / name for name in sorted(expected_names)):
        if candidate.is_file():
            outputs[candidate.name] = {
                "path": str(candidate.resolve()),
                "sha256": _sha256_bytes(candidate.read_bytes()),
                "bytes": candidate.stat().st_size,
            }
    record = {
        "schema": "nadoc.photoproduct-qm-run-reconciliation.v1",
        "status": "completed_unreviewed"
        if original.get("returncode") == 0 and parsed["passed_execution_checks"]
        else "failed",
        "gate_effect": "none",
        "reason": "reparsed immutable raw output and captured stdout with the current parser",
        "original_run_manifest_sha256": _sha256_bytes(run_path.read_bytes()),
        "job_manifest_sha256": original["job_manifest_sha256"],
        "output_sha256": output_hash,
        "parsed": parsed,
        "outputs": outputs,
    }
    reconciliation_path.write_text(json.dumps(record, indent=2) + "\n")
    return record


def _distance(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


def audit_optimized_model(job_dir: Path) -> dict[str, Any]:
    """Audit atom identity, finiteness, connectivity distances, and stereochemistry.

    This verifies that an optimized model is still the requested product. It does not
    establish that the geometry is a minimum; a separate frequency job is required.
    """

    job_path = job_dir / "job_manifest.json"
    run_path = job_dir / "run_manifest.json"
    optimized_path = job_dir / "optimized.xyz"
    if not all(path.is_file() for path in (job_path, run_path, optimized_path)):
        raise ValueError("job, run, and optimized XYZ files are all required")
    job = json.loads(job_path.read_text())
    run = json.loads(run_path.read_text())
    reconciliation_path = job_dir / "run_reconciliation.json"
    effective_run = (
        json.loads(reconciliation_path.read_text())
        if reconciliation_path.is_file()
        else run
    )
    if job.get("job_kind") != "geometry_optimization":
        raise ValueError("optimized-model audit requires a geometry_optimization job")
    if effective_run.get("status") != "completed_unreviewed":
        raise ValueError("cannot audit a QM run that did not complete successfully")
    if effective_run.get("job_manifest_sha256") != _sha256_bytes(job_path.read_bytes()):
        raise ValueError("run record does not match the current job manifest")
    optimized_hash = _sha256_bytes(optimized_path.read_bytes())
    recorded = (
        (effective_run.get("outputs") or {}).get("optimized.xyz", {}).get("sha256")
    )
    if recorded != optimized_hash:
        raise ValueError("optimized XYZ digest does not match the run record")
    atoms, comment = parse_xyz(optimized_path.read_text())
    atom_map = job.get("atom_map")
    if not isinstance(atom_map, list) or len(atom_map) != len(atoms):
        raise ValueError("stable atom map is missing or does not match optimized XYZ")
    if len(atom_map) != len(set(atom_map)):
        raise ValueError("stable atom map contains duplicate keys")
    coordinates = {
        key: [x, y, z] for key, (_element, x, y, z) in zip(atom_map, atoms, strict=True)
    }
    finite = all(math.isfinite(value) for xyz in coordinates.values() for value in xyz)

    registry_entry = next(
        (
            item
            for item in photoproduct_registry()["products"]
            if item["id"] == job.get("product_id")
        ),
        None,
    )
    if registry_entry is None:
        raise ValueError(f"unregistered product id in job: {job.get('product_id')!r}")
    candidate_manifest = None
    model_record = job.get("model_manifest") or {}
    model_evidence_status = model_record.get("evidence_status")
    candidate_model = model_record.get(
        "schema"
    ) == "nadoc.tt-cpd-stereo-candidate.v1" or model_evidence_status in {
        "candidate_not_reviewed",
        "candidate_pending_cap_review",
    }
    if candidate_model:
        definition = None
        model_path = Path(str(model_record.get("path") or ""))
        if (
            model_record.get("schema") != "nadoc.tt-cpd-stereo-candidate.v1"
            or not model_path.is_file()
            or _sha256_bytes(model_path.read_bytes()) != model_record.get("sha256")
        ):
            raise ValueError(
                "product has no chemical definition and no verified stereo-candidate manifest"
            )
        candidate_manifest = json.loads(model_path.read_text())
        if (
            candidate_manifest.get("product_id") != job.get("product_id")
            or candidate_manifest.get("model_id") != job.get("model_id")
            or candidate_manifest.get("status") != "candidate_not_reviewed"
        ):
            raise ValueError("stereo-candidate manifest identity/status mismatch")
    else:
        try:
            definition = load_chemical_definition(
                registry_entry["product"], registry_entry["stereochemistry"]
            )
        except FileNotFoundError:
            definition = None
            raise ValueError(
                "product has no chemical definition and no verified stereo-candidate manifest"
            )
    if not finite:
        chirality = {
            "passed": False,
            "centers": [],
            "reason": "non-finite coordinate",
        }
    elif definition is not None:
        chirality = audit_product_chirality(definition, coordinates)
    else:
        centers = []
        for record in candidate_manifest.get("model_signed_volume_stereochemistry", []):
            value = signed_tetrahedron_volume(
                coordinates, record["atom"], record["reference_atoms"]
            )
            expected = record["expected_sign"]
            centers.append(
                {
                    "atom": record["atom"],
                    "signed_volume": value,
                    "expected_sign": expected,
                    "passed": value > 0 if expected == "positive" else value < 0,
                }
            )
        chirality = {
            "schema": "nadoc.photoproduct-candidate-chirality-audit.v1",
            "product_id": job.get("product_id"),
            "passed": len(centers) == 4 and all(item["passed"] for item in centers),
            "centers": centers,
            "authority": "stereo preservation relative to a review-only candidate",
        }
    bond_distances = []
    if definition is not None:
        graph_records = definition["graph_delta"]
    else:
        graph_records = {
            category: [
                {"atom_1": first, "atom_2": second}
                for first, second in (
                    item.split("--") for item in registry_entry["graph_delta"][category]
                )
            ]
            for category in ("bonds_added", "bonds_retained")
        }
    for category in ("bonds_added", "bonds_retained"):
        for bond in graph_records[category]:
            first, second = bond["atom_1"], bond["atom_2"]
            if first not in coordinates or second not in coordinates:
                raise ValueError(
                    f"optimized model is missing graph atom {first} or {second}"
                )
            bond_distances.append(
                {
                    "category": category,
                    "atom_1": first,
                    "atom_2": second,
                    "distance_angstrom": _distance(
                        coordinates[first], coordinates[second]
                    ),
                }
            )
    report = {
        "schema": "nadoc.photoproduct-optimized-model-audit.v1",
        "status": (
            "passed_identity_and_chirality"
            if finite
            and chirality["passed"]
            and definition is not None
            and not candidate_model
            else (
                "passed_candidate_identity_and_chirality"
                if finite and chirality["passed"]
                else "failed"
            )
        ),
        "gate_effect": "none",
        "product_id": job["product_id"],
        "model_id": job["model_id"],
        "effective_run_record": {
            "path": str(
                (
                    reconciliation_path if reconciliation_path.is_file() else run_path
                ).resolve()
            ),
            "sha256": _sha256_bytes(
                (
                    reconciliation_path if reconciliation_path.is_file() else run_path
                ).read_bytes()
            ),
        },
        "optimized_xyz": {
            "path": str(optimized_path.resolve()),
            "sha256": optimized_hash,
            "comment": comment,
        },
        "atom_count": len(atoms),
        "atom_map_unique": len(atom_map) == len(set(atom_map)),
        "coordinates_finite": finite,
        "final_energy_hartree": (effective_run.get("parsed") or {}).get(
            "final_energy_hartree"
        ),
        "chirality_audit": chirality,
        "chemical_definition_status": (
            (
                "released_definition_candidate_model"
                if candidate_model
                else "released_definition"
            )
            if definition is not None
            else "candidate_only"
        ),
        "product_ring_bond_distances": bond_distances,
        "minimum_confirmation": "not_run; requires a frequency calculation",
    }
    report_path = job_dir / "optimized_model_audit.json"
    if report_path.exists():
        raise FileExistsError(f"refusing to overwrite existing audit: {report_path}")
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def audit_frequency_result(job_dir: Path) -> dict[str, Any]:
    """Confirm that a completed nonlinear-model frequency job has no imaginary modes.

    This is deliberately a QM-evidence audit, not a parameter-release gate. The full
    charge/bonded fit and force-field validation remain independently required.
    """

    job_path = job_dir / "job_manifest.json"
    run_path = job_dir / "run_manifest.json"
    output_path = job_dir / "output.dat"
    if not all(path.is_file() for path in (job_path, run_path, output_path)):
        raise ValueError("job, run, and output files are all required")
    job = json.loads(job_path.read_text())
    run = json.loads(run_path.read_text())
    reconciliation_path = job_dir / "run_reconciliation.json"
    effective_path = reconciliation_path if reconciliation_path.is_file() else run_path
    effective_run = (
        json.loads(reconciliation_path.read_text())
        if reconciliation_path.is_file()
        else run
    )
    if job.get("job_kind") != "frequency":
        raise ValueError("frequency audit requires a frequency job")
    if effective_run.get("status") != "completed_unreviewed":
        raise ValueError(
            "cannot audit a frequency run that did not complete successfully"
        )
    if effective_run.get("job_manifest_sha256") != _sha256_bytes(job_path.read_bytes()):
        raise ValueError("run record does not match the current job manifest")
    output_hash = _sha256_bytes(output_path.read_bytes())
    if (effective_run.get("outputs") or {}).get("output.dat", {}).get(
        "sha256"
    ) != output_hash:
        raise ValueError("frequency output digest does not match the run record")

    parent_record = job.get("parent_manifest")
    if not isinstance(parent_record, dict):
        raise ValueError("frequency job is missing its optimized-model parent audit")
    parent_path = resolve_frequency_job_reference(
        job_dir=job_dir,
        job=job,
        key="parent_manifest",
        label="optimized-model parent audit",
    )
    parent = json.loads(parent_path.read_text())
    accepted_parent_statuses = {
        "passed_identity_and_chirality",
        "passed_candidate_identity_and_chirality",
    }
    if (
        parent.get("schema") != "nadoc.photoproduct-optimized-model-audit.v1"
        or parent.get("status") not in accepted_parent_statuses
        or parent.get("product_id") != job.get("product_id")
        or parent.get("model_id") != job.get("model_id")
    ):
        raise ValueError(
            "frequency parent is not a passed matching optimized-model audit"
        )

    frequencies = parse_vibrational_frequencies(output_path.read_text(errors="replace"))
    expected_mode_count = 3 * int(job["atom_count"]) - 6
    imaginary = [item for item in frequencies if item["imaginary"]]
    complete = len(frequencies) == expected_mode_count
    hessian_name = "hessian_hartree_per_bohr2.txt"
    hessian_required = hessian_name in (job.get("expected_outputs") or [])
    hessian_path = job_dir / hessian_name
    hessian_audit: dict[str, Any] = {
        "required_by_job": hessian_required,
        "status": "not_requested_by_legacy_job",
        "units": job.get("hessian_units"),
    }
    hessian_ok = True
    if hessian_required:
        hessian_ok = False
        hessian_audit["status"] = "missing_or_invalid"
        if hessian_path.is_file():
            hessian_hash = _sha256_bytes(hessian_path.read_bytes())
            recorded_hessian = (
                (effective_run.get("outputs") or {}).get(hessian_name, {}).get("sha256")
            )
            rows: list[list[float]] = []
            try:
                for line in hessian_path.read_text().splitlines():
                    if line.strip():
                        rows.append([float(value) for value in line.split()])
            except ValueError:
                rows = []
            dimension = 3 * int(job["atom_count"])
            square = len(rows) == dimension and all(
                len(row) == dimension for row in rows
            )
            finite_hessian = square and all(
                math.isfinite(value) for row in rows for value in row
            )
            symmetry_error = (
                max(
                    abs(rows[i][j] - rows[j][i])
                    for i in range(dimension)
                    for j in range(i)
                )
                if finite_hessian
                else None
            )
            hessian_ok = (
                hessian_hash == recorded_hessian
                and finite_hessian
                and symmetry_error is not None
                and symmetry_error <= 1e-8
                and job.get("hessian_units") == "hartree/bohr^2"
            )
            hessian_audit = {
                "required_by_job": True,
                "status": "passed" if hessian_ok else "missing_or_invalid",
                "path": str(hessian_path.resolve()),
                "sha256": hessian_hash,
                "recorded_sha256": recorded_hessian,
                "units": job.get("hessian_units"),
                "dimension": dimension if square else None,
                "finite": finite_hessian,
                "maximum_symmetry_error": symmetry_error,
            }
    passed = complete and not imaginary and hessian_ok
    candidate_evidence = (
        parent.get("status") == "passed_candidate_identity_and_chirality"
    )
    report = {
        "schema": "nadoc.photoproduct-frequency-audit.v1",
        "status": (
            "passed_candidate_harmonic_minimum"
            if passed and candidate_evidence
            else "passed_harmonic_minimum"
            if passed
            else "failed"
        ),
        "gate_effect": "none",
        "product_id": job["product_id"],
        "model_id": job["model_id"],
        "assumption": "nonlinear molecular model; expected 3N-6 projected modes",
        "atom_count": job["atom_count"],
        "expected_mode_count": expected_mode_count,
        "parsed_mode_count": len(frequencies),
        "frequency_table_complete": complete,
        "imaginary_mode_count": len(imaginary),
        "lowest_frequency_cm_inverse": min(
            (item["value_cm_inverse"] for item in frequencies), default=None
        ),
        "frequencies": frequencies,
        "cartesian_hessian": hessian_audit,
        "effective_run_record": {
            "path": str(effective_path.resolve()),
            "sha256": _sha256_bytes(effective_path.read_bytes()),
        },
        "output": {"path": str(output_path.resolve()), "sha256": output_hash},
        "parent_optimized_model_audit": {
            **parent_record,
            "effective_path": str(parent_path.resolve()),
            "relocated": parent_path.resolve()
            != Path(str(parent_record.get("path") or "")).resolve(),
        },
        "release_note": (
            "Confirms a harmonic minimum and, for new jobs, a hash-audited Cartesian "
            "Hessian; it does not validate fitted CHARMM parameters or pass the "
            "qm_reference_data gate by itself."
        ),
    }
    report_path = job_dir / "frequency_audit.json"
    if report_path.exists():
        raise FileExistsError(f"refusing to overwrite existing audit: {report_path}")
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def audit_electrostatic_properties(job_dir: Path) -> dict[str, Any]:
    """Hash-audit an HF dipole calculation at a passed product geometry."""

    job_path = job_dir / "job_manifest.json"
    run_path = job_dir / "run_manifest.json"
    output_path = job_dir / "output.dat"
    if not all(path.is_file() for path in (job_path, run_path, output_path)):
        raise ValueError("job, run, and output files are all required")
    job = json.loads(job_path.read_text())
    run = json.loads(run_path.read_text())
    if job.get("job_kind") != "electrostatic_properties":
        raise ValueError("electrostatic audit requires an electrostatic_properties job")
    if run.get("status") != "completed_unreviewed":
        raise ValueError("cannot audit an electrostatic run that did not complete")
    if run.get("job_manifest_sha256") != _sha256_bytes(job_path.read_bytes()):
        raise ValueError("run record does not match the current job manifest")
    output_hash = _sha256_bytes(output_path.read_bytes())
    if (run.get("outputs") or {}).get("output.dat", {}).get("sha256") != output_hash:
        raise ValueError("electrostatic output digest does not match the run record")
    parent_record = job.get("parent_manifest")
    if not isinstance(parent_record, dict):
        raise ValueError("electrostatic job is missing its optimized-model parent")
    parent_path = Path(str(parent_record.get("path") or ""))
    if not parent_path.is_file() or _sha256_bytes(parent_path.read_bytes()) != (
        parent_record.get("sha256")
    ):
        raise ValueError("optimized-model parent audit is missing or hash-mismatched")
    parent = json.loads(parent_path.read_text())
    accepted_parent_statuses = {
        "passed_identity_and_chirality",
        "passed_candidate_identity_and_chirality",
    }
    if (
        parent.get("schema") != "nadoc.photoproduct-optimized-model-audit.v1"
        or parent.get("status") not in accepted_parent_statuses
        or parent.get("product_id") != job.get("product_id")
        or parent.get("model_id") != job.get("model_id")
    ):
        raise ValueError("electrostatic parent is not a passed matching model")
    parsed = parse_electrostatic_properties_output(
        output_path.read_text(errors="replace")
        + "\n"
        + str(run.get("stdout_tail") or "")
    )
    report = {
        "schema": "nadoc.photoproduct-electrostatic-properties-audit.v1",
        "status": "complete_candidate" if parsed["complete"] else "failed",
        "geometry_evidence_status": parent.get("status"),
        "passed": parsed["complete"],
        "gate_effect": "none",
        "product_id": job["product_id"],
        "model_id": job["model_id"],
        "method": job.get("method"),
        "basis": job.get("basis"),
        "dipole_units": "atomic_unit_e_bohr",
        **parsed,
        "job_manifest_sha256": _sha256_bytes(job_path.read_bytes()),
        "output": {"path": str(output_path.resolve()), "sha256": output_hash},
        "parent_optimized_model_audit": parent_record,
        "release_note": (
            "This is one electrostatic fitting target; water interactions, constrained "
            "charge fitting, and independent validation remain required."
        ),
    }
    report_path = job_dir / "electrostatic_properties_audit.json"
    if report_path.exists():
        raise FileExistsError(
            f"refusing to overwrite existing electrostatic audit: {report_path}"
        )
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
