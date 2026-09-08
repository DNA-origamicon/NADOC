"""Read-only diagnostics for the reproducible photoproduct parameterization toolchain."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
from pathlib import Path
from typing import Any


def _file_source(path: Path) -> dict[str, str] | None:
    if not path.is_file():
        return None
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _command(name: str) -> str | None:
    return shutil.which(name)


def _is_gnome_orca(path: Path) -> bool:
    try:
        header = path.read_bytes()[:4096].lower()
    except OSError:
        return False
    return b"screen reader" in header or b"the orca team" in header


def _quantum_orca() -> dict[str, Any]:
    configured = os.environ.get("NADOC_QM_ORCA")
    candidate = Path(configured) if configured else Path(_command("orca") or "")
    if not str(candidate):
        return {"available": False, "path": None, "reason": "not found"}
    if not candidate.is_file():
        return {"available": False, "path": str(candidate), "reason": "not a file"}
    if _is_gnome_orca(candidate):
        return {
            "available": False,
            "path": str(candidate),
            "reason": "GNOME Orca screen reader, not the ORCA quantum-chemistry executable",
        }
    if not configured:
        return {
            "available": False,
            "path": str(candidate),
            "reason": "unverified; set NADOC_QM_ORCA to an accepted ORCA executable",
        }
    return {"available": True, "path": str(candidate.resolve()), "reason": None}


def _psi4() -> str | None:
    configured = os.environ.get("NADOC_QM_PSI4")
    candidates = [
        Path(configured) if configured else None,
        Path(_command("psi4")) if _command("psi4") else None,
        Path.home() / "miniforge3" / "envs" / "nadoc-qm" / "bin" / "psi4",
    ]
    return next(
        (str(path.resolve()) for path in candidates if path and path.is_file()), None
    )


def _find_fftk() -> str | None:
    candidates = [
        Path("/usr/local/lib/vmd/plugins/noarch/tcl/fftk1.1"),
        Path("/usr/local/lib/vmd/plugins/noarch/tcl/fftk2.0"),
    ]
    return next((str(path) for path in candidates if path.is_dir()), None)


def _openbabel() -> str | None:
    candidates = [
        Path(_command("obabel")) if _command("obabel") else None,
        Path.home() / "miniforge3" / "envs" / "nadoc-stereo-audit" / "bin" / "obabel",
    ]
    return next(
        (str(path.resolve()) for path in candidates if path and path.is_file()), None
    )


def _conda_package(environment: Path, package: str) -> dict[str, Any]:
    records = sorted((environment / "conda-meta").glob(f"{package}-*.json"))
    if not records:
        return {"available": False, "version": None, "environment": str(environment)}
    try:
        record = json.loads(records[-1].read_text())
    except (OSError, ValueError):
        return {"available": False, "version": None, "environment": str(environment)}
    return {
        "available": True,
        "version": record.get("version"),
        "environment": str(environment),
    }


def _environment_package(environment: Path, package: str) -> dict[str, Any]:
    conda = _conda_package(environment, package)
    if conda["available"]:
        return conda
    normalized = package.replace("-", "_").lower()
    candidates = sorted(
        environment.glob(f"lib/python*/site-packages/{normalized}-*.dist-info/METADATA")
    )
    if not candidates:
        return conda
    version = None
    try:
        version = next(
            (
                line.partition(":")[2].strip()
                for line in candidates[-1].read_text(errors="replace").splitlines()
                if line.startswith("Version:")
            ),
            None,
        )
    except OSError:
        pass
    return {
        "available": True,
        "version": version,
        "environment": str(environment),
        "source": "pip-dist-info",
    }


def photoproduct_toolchain_status() -> dict[str, Any]:
    usage = shutil.disk_usage(Path(__file__).anchor)
    archive_path = Path("/media/jojo/Archive")
    archive_mounted = archive_path.is_mount()
    archive_usage = (
        shutil.disk_usage(archive_path)
        if archive_mounted and os.access(archive_path, os.W_OK)
        else None
    )
    psi4 = _psi4()
    qm_environment = Path.home() / "miniforge3" / "envs" / "nadoc-qm"
    psi4_package = _environment_package(qm_environment, "psi4")
    rdkit = _environment_package(qm_environment, "rdkit")
    qcengine = _environment_package(qm_environment, "qcengine")
    qcelemental = _environment_package(qm_environment, "qcelemental")
    numpy = _environment_package(qm_environment, "numpy")
    forcebalance = _environment_package(qm_environment, "forcebalance")
    openmm = _environment_package(qm_environment, "openmm")
    scipy = _environment_package(qm_environment, "scipy")
    orca = _quantum_orca()
    qm_available = bool(psi4) or orca["available"]
    distributed_available = (
        bool(psi4)
        and psi4_package.get("version") == "1.11"
        and qcengine.get("version") == "0.51.0"
        and qcelemental.get("version") == "0.51.0"
        and numpy.get("version") == "2.5.2"
    )
    acceptance_policy = _file_source(
        Path(__file__).resolve().parents[1]
        / "data"
        / "forcefield"
        / "photoproduct_parameter_acceptance.json"
    )
    bonded_refit_policy = _file_source(
        Path(__file__).resolve().parents[1]
        / "data"
        / "forcefield"
        / "photoproduct_bonded_refit_policy.json"
    )
    return {
        "schema": "nadoc.photoproduct-toolchain.v1",
        "simulation": {
            "namd": _command("namd3") or _command("namd2") or _command("namd"),
            "psfgen": _command("psfgen"),
            "vmd": _command("vmd"),
        },
        "quantum": {
            "psi4": {
                "available": bool(psi4),
                "path": psi4,
                "version": psi4_package.get("version"),
                "environment": str(qm_environment),
            },
            "distributed_hessian": {
                "available": distributed_available,
                "qcengine": qcengine,
                "qcelemental": qcelemental,
                "numpy": numpy,
                "required_versions": {
                    "psi4": "1.11",
                    "qcengine": "0.51.0",
                    "qcelemental": "0.51.0",
                    "numpy": "2.5.2",
                },
                "note": (
                    "All workers and the assembler must use the same recorded stack; "
                    "mixed-version results fail closed."
                ),
            },
            "distributed_fixed_geometry_response": {
                "available": distributed_available,
                "job_kind": "fixed_geometry_hessian",
                "requires_reviewed_coupled_conformer": True,
                "requires_human_or_quantitatively_screened_conformer": True,
                "preserves_center_gradient": True,
                "preserves_center_electronic_energy": True,
                "performs_frequency_analysis": False,
                "local_runner": "scripts/run_local_photoproduct_response.py",
                "runpod_offload_supported": True,
                "note": (
                    "Produces gate-neutral force/Hessian evidence at exact screened "
                    "coordinates; it never asserts a stationary point or releases terms."
                ),
            },
            "orca": orca,
            "available": qm_available,
        },
        "fitting": {
            "fftk_path": _find_fftk(),
            "rdkit": rdkit,
            "forcebalance": forcebalance,
            "openmm": openmm,
            "scipy": scipy,
            "bounded_response_fit_available": bool(
                scipy.get("available") and openmm.get("available")
            ),
            "complete_ring_refit": {
                "available": True,
                "policy": bonded_refit_policy,
                "command": "promote-bonded-refit-terms",
                "replaces_covered_terms": True,
                "gate_effect": "none",
            },
            "note": "SciPy supplies bounded least squares, ForceBalance/OpenMM provide a reproducible optimizer harness, and ffTK 1.1 remains an independent inspection aid—not release authority.",
        },
        "stereochemistry_crosscheck": {
            "openbabel": {
                "available": bool(_openbabel()),
                "path": _openbabel(),
                "environment": str(
                    Path.home() / "miniforge3" / "envs" / "nadoc-stereo-audit"
                ),
            },
            "note": "Open Babel is an independent software cross-check; exact graph and signed-volume audits are the machine authority, while visual review remains diagnostic.",
        },
        "definition_review_workflow": {
            "interactive_3d_review": {
                "available": True,
                "review_scope": "visual_identity_and_stereochemistry_only",
                "decision_options": ["approve", "reject", "revise"],
                "writes_to_archive": True,
                "mutates_registry": False,
                "gate_effect": "none",
            },
            "minimum_backed_candidate": {
                "available": True,
                "supports_direct_harmonic_minimum": True,
                "supports_audited_endpoint_exchange_equivalence": True,
                "allows_reflection": False,
                "gate_effect": "none",
                "command": "build-minimum-backed-definition-candidate",
            },
            "completed_review_ingestion": {
                "available": True,
                "requires_all_human_decisions": True,
                "requires_signed_release_or_decision_evidence": True,
                "mutates_registry": False,
                "gate_effect": "none",
                "command": "audit-tt-cpd-definition-review",
            },
            "dna_boundary_quantitative_screen": {
                "available": True,
                "requires_exact_dtpdt_graph": True,
                "requires_independent_1n4e_replicates": True,
                "authorizes_qm": True,
                "authorizes_parameter_release": False,
                "gate_effect": "none",
                "command": "screen-dna-boundary-model",
            },
            "note": (
                "Software revalidates identities, hashes, and chirality. A named human "
                "reviewer confirms atom-mapped identity; parameter acceptance is handled "
                "by separate quantitative gates."
            ),
        },
        "conformer_review_workflow": {
            "mode_source": {
                "available": True,
                "accepts_direct_harmonic_minimum": True,
                "accepts_audited_endpoint_exchange_equivalence": True,
                "contains_parameter_targets": False,
                "allows_reflection": False,
                "gate_effect": "none",
                "command": "build-coupled-conformer-mode-source",
            },
            "candidate_generation": {
                "available": True,
                "requires_stereochemistry_preservation": True,
                "requires_safe_geometry": True,
                "gate_effect": "none",
                "command": "build-coupled-conformer-candidates",
            },
            "multi_product_review_index": {
                "available": True,
                "requires_pristine_unreviewed_plans": True,
                "authorizes_qm": False,
                "gate_effect": "none",
                "command": "build-coupled-conformer-review-index",
            },
            "review_visualization": {
                "available": True,
                "static_pdb_models_only": True,
                "is_trajectory": False,
                "eligible_for_help_viewer": False,
                "authorizes_qm": False,
                "gate_effect": "none",
                "command": "build-coupled-conformer-review-visualization",
            },
            "decision_overlay": {
                "available": True,
                "preserves_pristine_source_plans": True,
                "requires_named_human_identity_review": True,
                "mutates_registry": False,
                "authorizes_qm": False,
                "gate_effect": "none",
                "build_command": "build-coupled-conformer-review-decisions",
                "apply_command": "apply-coupled-conformer-review-decisions",
            },
            "quantitative_qm_input_screen": {
                "available": True,
                "requires_hash_pinned_v2_policy": True,
                "recomputes_identity_chirality_and_geometry": True,
                "deterministic_training_validation_partition": True,
                "mutates_registry": False,
                "authorizes_qm": True,
                "authorizes_parameter_release": False,
                "gate_effect": "none",
                "command": "screen-coupled-conformer-plan",
            },
            "completed_review_audit": {
                "available": True,
                "mutates_registry": False,
                "authorizes_qm": False,
                "gate_effect": "none",
                "command": "audit-coupled-conformer-review",
            },
            "fixed_geometry_qm": {
                "requires_released_chemical_definition": True,
                "requires_human_or_quantitative_input_decision": True,
                "allows_reflection": False,
            },
            "note": (
                "Mode sources and candidate review queues are not fitting authority; "
                "fixed-geometry QM requires either an explicit human decision or the "
                "hash-pinned quantitative input policy. Neither releases parameters."
            ),
        },
        "parameter_acceptance": {
            "policy": acceptance_policy,
            "visual_approval_releases_parameters": False,
            "requires_quantitative_machine_gates": True,
        },
        "resources": {
            "disk_free_gib": round(usage.free / 1024**3, 2),
            "disk_total_gib": round(usage.total / 1024**3, 2),
            "root_disk_low_space": usage.free < 20 * 1024**3,
            "archive_scratch": (
                {
                    "available": True,
                    "path": str(archive_path),
                    "mounted": True,
                    "free_gib": round(archive_usage.free / 1024**3, 2),
                    "total_gib": round(archive_usage.total / 1024**3, 2),
                    "recommended_subdirectory": str(
                        archive_path / "NADOC_archive" / "qm_scratch"
                    ),
                    "note": (
                        "Use a dedicated per-run subtree for disposable Psi4 scratch; "
                        "keep manifests and final outputs outside scratch."
                    ),
                }
                if archive_usage is not None
                else {
                    "available": False,
                    "path": str(archive_path),
                    "mounted": archive_mounted,
                    "reason": "Archive drive is not mounted or is not writable",
                }
            ),
            "warnings": (
                [
                    "Root filesystem has less than 20 GiB free; do not use it for "
                    "large Psi4 integral scratch."
                ]
                if usage.free < 20 * 1024**3
                else []
            ),
        },
        "ready_for_qm_generation": qm_available,
        "install_actions": []
        if qm_available
        else [
            {
                "tool": "Psi4",
                "requires_sudo": False,
                "requires_account": False,
                "command": "mamba create -n nadoc-qm -c conda-forge python=3.12 psi4=1.11",
                "note": (
                    "Use a separate environment and a dedicated per-run scratch directory "
                    "under /media/jojo/Archive/NADOC_archive/qm_scratch."
                ),
            },
            {
                "tool": "ORCA",
                "requires_sudo": False,
                "requires_account": True,
                "command": None,
                "note": "Optional alternative; the user must accept the ORCA license and download it personally.",
            },
        ],
        "gated_downloads": [
            {
                "tool": "ORCA quantum chemistry",
                "required": False,
                "requires_account": True,
                "requires_license_acceptance": True,
                "requires_sudo": False,
                "reason": "optional independent QM cross-check; Psi4 is the primary engine",
            },
            {
                "tool": "CGenFF assignment program / ParamChem",
                "required": False,
                "requires_account": True,
                "requires_license_acceptance": True,
                "requires_sudo": False,
                "reason": "optional initial atom typing only; it cannot validate a lesion",
            },
            {
                "tool": "Gaussian 16",
                "required": False,
                "requires_account": True,
                "requires_license_acceptance": True,
                "requires_sudo": False,
                "reason": "needed only to reproduce the 2026 literature DFT protocol exactly",
            },
        ],
        "sudo_commands_required": [],
    }
