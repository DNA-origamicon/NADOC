#!/usr/bin/env python3
"""Build the prioritized, restart-safe TT-CPD boundary optimization cycle."""

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

from backend.core.photoproduct_chemistry import (  # noqa: E402
    audit_product_chirality,
    load_chemical_definition,
)
from backend.core.photoproduct_registry import photoproduct_registry  # noqa: E402
from backend.parameterization.photoproduct_qm import (  # noqa: E402
    _last_psi4_geometry,
    generate_psi4_job,
    parse_psi4_output,
    parse_xyz,
)


POLICY_PATH = (
    REPOSITORY_ROOT
    / "backend/data/forcefield/photoproduct_qm_cycle_policy_v2.0.1.json"
)
PROTOCOL_PATH = (
    REPOSITORY_ROOT
    / "backend/data/forcefield/photoproduct_qm_protocol_v1.7.0.json"
)
REMOTE_ROOT = Path(
    "/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-boundary-recovery-v2r1"
)
COMPUTE_CASES = (
    ("tt-cpd-cis-syn", "fresh_screened_seed"),
    ("tt-cpd-cis-syn-ii", "last_preserved_optimizer_geometry"),
    ("tt-cpd-cis-anti-i", "fresh_screened_seed"),
)
RECOVERED_PRODUCT = "tt-cpd-trans-syn-i"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _original_case_paths(evidence_root: Path, product_id: str) -> tuple[Path, Path | None]:
    if product_id == "tt-cpd-cis-syn":
        campaign = evidence_root / "alpine-qm-cis-syn-boundary-optimization-campaign-v1"
    elif product_id in {"tt-cpd-cis-syn-ii", "tt-cpd-trans-syn-i"}:
        campaign = evidence_root / "alpine-qm-boundary-optimization-campaign-v1"
    else:
        campaign = evidence_root / "alpine-qm-anti-boundary-optimization-campaign-v1"
    case = campaign / "bundle/cases" / product_id
    if not case.is_dir():
        raise FileNotFoundError(f"original case is unavailable: {case}")
    outputs = sorted(
        (campaign / "remote-results" / product_id).glob("*/case/job/output.dat")
    )
    return case, outputs[-1] if outputs else None


def _registry_identity(product_id: str) -> tuple[str, str]:
    matches = [
        item for item in photoproduct_registry()["products"] if item["id"] == product_id
    ]
    if len(matches) != 1:
        raise ValueError(f"no unique registry entry for {product_id}")
    return str(matches[0]["product"]), str(matches[0]["stereochemistry"])


def _chirality(product_id: str, xyz_path: Path, atom_map: list[str]) -> dict[str, object]:
    atoms, _ = parse_xyz(xyz_path.read_text())
    if len(atoms) != len(atom_map) or len(atom_map) != len(set(atom_map)):
        raise ValueError(f"{product_id}: stable atom map is not a coordinate bijection")
    product, stereo = _registry_identity(product_id)
    definition = load_chemical_definition(product, stereo)
    coordinates = {key: atom[1:] for key, atom in zip(atom_map, atoms, strict=True)}
    audit = audit_product_chirality(definition, coordinates)
    if not audit["passed"]:
        raise ValueError(f"{product_id}: proposed cycle geometry changed chirality")
    return audit


def _write_xyz(path: Path, atoms: list[tuple[str, float, float, float]], comment: str) -> None:
    path.write_text(
        f"{len(atoms)}\n{comment}\n"
        + "\n".join(
            f"{element:<2} {x: .12f} {y: .12f} {z: .12f}"
            for element, x, y, z in atoms
        )
        + "\n"
    )


def _build_compute_case(
    *, evidence_root: Path, cases_root: Path, product_id: str, source_mode: str
) -> dict[str, object]:
    original_case, preserved_output = _original_case_paths(evidence_root, product_id)
    original_job_path = original_case / "job/job_manifest.json"
    original_case_path = original_case / "case_manifest.json"
    original_job = json.loads(original_job_path.read_text())
    if (
        original_job.get("schema") != "nadoc.photoproduct-qm-job.v1"
        or original_job.get("product_id") != product_id
        or original_job.get("job_kind") != "geometry_optimization"
        or original_job.get("atom_count") != 63
        or original_job.get("charge") != -1
    ):
        raise ValueError(f"{product_id}: original job identity is invalid")
    atom_map = original_job.get("atom_map")
    if not isinstance(atom_map, list) or len(atom_map) != 63 or len(set(atom_map)) != 63:
        raise ValueError(f"{product_id}: original stable atom map is invalid")
    case_root = cases_root / product_id
    case_root.mkdir(parents=True)
    if source_mode == "fresh_screened_seed":
        source = Path(str((original_job.get("source_xyz") or {}).get("path") or ""))
        if not source.is_file() or _sha256(source) != original_job["source_xyz"]["sha256"]:
            raise ValueError(f"{product_id}: original screened seed is unavailable")
        local_source = case_root / "start.xyz"
        shutil.copy2(source, local_source)
        selection = {
            "mode": source_mode,
            "source_xyz": _record(source),
            "preserved_output": None,
        }
        model_manifest_path = Path(original_job["model_manifest"]["path"])
    elif source_mode == "last_preserved_optimizer_geometry":
        if preserved_output is None or not preserved_output.is_file():
            raise ValueError(f"{product_id}: preserved optimizer output is unavailable")
        source = Path(str((original_job.get("source_xyz") or {}).get("path") or ""))
        source_atoms, _ = parse_xyz(source.read_text())
        restart_atoms = _last_psi4_geometry(
            preserved_output.read_text(errors="replace"), len(source_atoms)
        )
        if [atom[0] for atom in restart_atoms] != [atom[0] for atom in source_atoms]:
            raise ValueError(f"{product_id}: restart changed atom order or elements")
        local_source = case_root / "restart.xyz"
        _write_xyz(
            local_source,
            restart_atoms,
            "restart from last complete geometry in hash-pinned preserved Psi4 output",
        )
        selection = {
            "mode": source_mode,
            "source_xyz": _record(source),
            "preserved_output": _record(preserved_output),
            "selection_rule": "last complete printed Cartesian geometry",
        }
        model_manifest_path = None
    else:
        raise ValueError(f"unsupported source mode: {source_mode}")
    chirality = _chirality(product_id, local_source, atom_map)
    job_dir = case_root / "job"
    job = generate_psi4_job(
        product_id=product_id,
        model_id=str(original_job["model_id"]),
        xyz_path=local_source,
        output_dir=job_dir,
        job_kind="geometry_optimization",
        charge=-1,
        multiplicity=1,
        atom_map=atom_map,
        model_manifest_path=model_manifest_path,
        memory_gib=100,
        threads=32,
        maximum_geometry_iterations=400,
        protocol_path=PROTOCOL_PATH,
    )
    job["cycle_parent"] = {
        "original_case_manifest": _record(original_case_path),
        "original_job_manifest": _record(original_job_path),
        "original_model_manifest": original_job.get("model_manifest"),
        "geometry_selection": selection,
        "starting_chirality_audit": chirality,
    }
    if model_manifest_path is None:
        job["model_manifest"] = original_job.get("model_manifest")
    job_path = job_dir / "job_manifest.json"
    job_path.write_text(json.dumps(job, indent=2) + "\n")
    case = {
        "schema": "nadoc.photoproduct-alpine-boundary-recovery-case.v1",
        "status": "generated_not_run",
        "gate_effect": "none",
        "simulation_ready": False,
        "product_id": product_id,
        "model_id": job["model_id"],
        "source_mode": source_mode,
        "atom_count": 63,
        "charge": -1,
        "stable_atom_map_sha256": hashlib.sha256(
            json.dumps(atom_map, separators=(",", ":")).encode()
        ).hexdigest(),
        "job_manifest_sha256": _sha256(job_path),
        "input_sha256": _sha256(job_dir / "input.dat"),
        "start_xyz_sha256": _sha256(local_source),
        "protocol_version": job["protocol_version"],
        "optimizer_settings": job["optimizer_settings"],
        "resources": {
            "slurm_cpus": 32,
            "psi4_threads": 32,
            "slurm_memory_gib": 240,
            "psi4_memory_gib": 100,
            "walltime": "72:00:00",
        },
    }
    case_path = case_root / "case_manifest.json"
    case_path.write_text(json.dumps(case, indent=2) + "\n")
    return {"case": case, "case_manifest_sha256": _sha256(case_path)}


def _recover_completed(evidence_root: Path) -> dict[str, object]:
    case, output = _original_case_paths(evidence_root, RECOVERED_PRODUCT)
    if output is None:
        raise ValueError("trans-syn-I preserved output is unavailable")
    job_path = case / "job/job_manifest.json"
    job = json.loads(job_path.read_text())
    result_job = output.parent
    optimized = result_job / "optimized.xyz"
    completion = result_job.parent.parent / "case_completion.json"
    parsed = parse_psi4_output(output.read_text(errors="replace"), "geometry_optimization")
    if not parsed["passed_execution_checks"] or not optimized.is_file():
        raise ValueError("trans-syn-I does not contain a clean completed optimization")
    if (completion_payload := json.loads(completion.read_text())).get("returncode") != 0:
        raise ValueError("trans-syn-I completion record has a nonzero return code")
    atom_map = job.get("atom_map")
    if not isinstance(atom_map, list):
        raise ValueError("trans-syn-I stable atom map is unavailable")
    chirality = _chirality(RECOVERED_PRODUCT, optimized, atom_map)
    return {
        "schema": "nadoc.photoproduct-qm-completed-optimization-recovery.v1",
        "status": "recovered_completed_unreviewed",
        "gate_effect": "none",
        "simulation_ready": False,
        "product_id": RECOVERED_PRODUCT,
        "job_manifest": _record(job_path),
        "case_completion": _record(completion),
        "output": _record(output),
        "optimized_xyz": _record(optimized),
        "parsed": parsed,
        "chirality_audit": chirality,
        "interpretation": "The original runner used an incomplete success-marker list. The raw Psi4 1.11 output and optimized.xyz establish execution completion; parameter release remains gated.",
    }


def build(*, evidence_root: Path, output_root: Path) -> dict[str, object]:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite campaign: {output_root}")
    policy = json.loads(POLICY_PATH.read_text())
    protocol = json.loads(PROTOCOL_PATH.read_text())
    if (
        policy.get("version") != "2.0.1"
        or policy.get("simulation_ready") is not False
        or protocol.get("version") != "1.7.0"
    ):
        raise ValueError("recovery cycle policy or optimizer protocol is invalid")
    cases_root = output_root / "bundle/cases"
    cases_root.mkdir(parents=True)
    products: list[dict[str, object]] = []
    case_lines: list[str] = []
    for index, (product_id, source_mode) in enumerate(COMPUTE_CASES):
        built = _build_compute_case(
            evidence_root=evidence_root,
            cases_root=cases_root,
            product_id=product_id,
            source_mode=source_mode,
        )
        case_lines.append(f"{index}\t{product_id}\t{built['case_manifest_sha256']}")
        products.append(
            {
                "array_index": index,
                "product_id": product_id,
                "action": source_mode,
                "case_manifest_sha256": built["case_manifest_sha256"],
            }
        )
    bundle = output_root / "bundle"
    (bundle / "cases.tsv").write_text("\n".join(case_lines) + "\n")
    for name in ("run_case.sh", "campaign_32.sbatch", "extract_checkpoint.py"):
        shutil.copy2(Path(__file__).with_name(name), bundle / name)
    recovered = _recover_completed(evidence_root)
    recovered_path = output_root / "recovered-trans-syn-i.json"
    recovered_path.write_text(json.dumps(recovered, indent=2) + "\n")
    inventory = [
        f"{_sha256(path)}  {path.relative_to(bundle)}"
        for path in sorted(item for item in bundle.rglob("*") if item.is_file())
        if path.name != "MANIFEST.sha256"
    ]
    (bundle / "MANIFEST.sha256").write_text("\n".join(inventory) + "\n")
    archive = output_root / "alpine-boundary-recovery-campaign-v2r1.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(bundle, arcname="bundle")
    (archive.with_suffix(archive.suffix + ".sha256")).write_text(
        f"{_sha256(archive)}  {archive.name}\n"
    )
    report = {
        "schema": "nadoc.photoproduct-alpine-boundary-recovery-campaign.v1",
        "status": "built_not_submitted",
        "gate_effect": "none",
        "simulation_ready": False,
        "policy": _record(POLICY_PATH),
        "protocol": _record(PROTOCOL_PATH),
        "compute_product_count": len(products),
        "recovered_product_count": 1,
        "products": products,
        "recovered_evidence": _record(recovered_path),
        "remote_root": str(REMOTE_ROOT),
        "archive": _record(archive),
        "interpretation": "This prioritized cycle generates minimum evidence only; no force-field or NAMD gate is released.",
    }
    (output_root / "campaign_manifest.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                evidence_root=args.evidence_root.resolve(),
                output_root=args.output_root.resolve(),
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
