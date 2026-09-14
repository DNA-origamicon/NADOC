#!/usr/bin/env python3
"""Build three screened noncanonical TT-CPD d(TpT) optimizations for Alpine."""

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

from backend.parameterization.photoproduct_qm import generate_psi4_job  # noqa: E402


PRODUCTS = (
    "tt-cpd-cis-syn-ii",
    "tt-cpd-trans-syn-i",
    "tt-cpd-trans-syn-ii",
)
REMOTE_ROOT = Path("/scratch/alpine/jojo6687/nadoc_qm_campaigns/tt-cpd-boundary-opt-v1")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checked_source(record: object, label: str) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{label} is missing")
    path = Path(str(record.get("path") or ""))
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        raise ValueError(f"{label} is missing or hash-mismatched")
    return path.resolve()


def _screened_boundary(
    path: Path, product_id: str
) -> tuple[dict[str, object], Path, Path]:
    payload = json.loads(path.read_text())
    screen = payload.get("quantitative_screening") or {}
    checks = screen.get("checks") or {}
    policy_gate = screen.get("policy_gate")
    exact_boundary = screen.get("policy") == "exact-dtpdt-boundary-and-replicates-v1"
    if (
        payload.get("schema") != "nadoc.photoproduct-dna-boundary-model-candidate.v1"
        or payload.get("status") != "quantitatively_screened_boundary"
        or payload.get("product_id") != product_id
        or payload.get("atom_count") != 63
        or payload.get("formal_charge") != -1
        or payload.get("simulation_ready") is not False
        or payload.get("gate_effect") != "none"
        or screen.get("status") != "passed_qm_input_screen"
        or (
            not exact_boundary
            and policy_gate
            not in {
                "grafted_dna_boundary_model",
                "flexibly_relaxed_dna_boundary_seed",
            }
        )
        or screen.get("authorizes") != "boundary_qm_evidence_generation_only"
        or screen.get("releases_parameters") is not False
        or (
            not exact_boundary
            and (not checks or not all(value is True for value in checks.values()))
        )
    ):
        raise ValueError(
            f"{product_id}: boundary screen is not valid QM input evidence"
        )
    policy = _checked_source(
        screen.get("policy_source"), f"{product_id} boundary policy"
    )
    policy_payload = json.loads(policy.read_text())
    valid_policy = (
        exact_boundary
        and (
            product_id == "tt-cpd-cis-syn"
            and policy_payload.get("schema")
            == "nadoc.photoproduct-parameter-acceptance.v2"
            and policy_payload.get("version") == "2.1.0"
            and (
                (policy_payload.get("automated_qm_input_gates") or {}).get(
                    "dna_boundary_model"
                )
                or {}
            ).get("policy")
            == "exact-dtpdt-boundary-and-replicates-v1"
        )
        or (
            policy_payload.get("schema")
            == "nadoc.photoproduct-grafted-boundary-policy.v1"
            and policy_payload.get("version") == "1.0.0"
            and policy_gate == "grafted_dna_boundary_model"
        )
        or (
            policy_payload.get("schema")
            == "nadoc.photoproduct-flexible-boundary-seed-policy.v1"
            and policy_payload.get("version") in {"1.0.0", "2.0.0"}
            and policy_gate == "flexibly_relaxed_dna_boundary_seed"
        )
    )
    if not valid_policy or (
        not exact_boundary
        and (
            policy_payload.get("gate_id") != policy_gate
            or policy_payload.get("simulation_ready") is not False
            or policy_payload.get("gate_effect") != "none"
        )
    ):
        raise ValueError(f"{product_id}: boundary policy is invalid")
    xyz = _checked_source(
        (payload.get("outputs") or {}).get("xyz"), f"{product_id} XYZ"
    )
    atom_map = _checked_source(
        (payload.get("outputs") or {}).get("atom_map"), f"{product_id} atom map"
    )
    return payload, xyz, atom_map


def build(*, graft_root: Path, output_root: Path) -> dict[str, object]:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite campaign: {output_root}")
    bundle = output_root / "bundle"
    cases_root = bundle / "cases"
    cases_root.mkdir(parents=True)
    records: list[dict[str, object]] = []
    lines: list[str] = []
    for index, product_id in enumerate(PRODUCTS):
        screen_path = (graft_root / product_id / "screened-chain-b.json").resolve()
        model, xyz_path, atom_map_path = _screened_boundary(screen_path, product_id)
        atom_map = json.loads(atom_map_path.read_text())
        if (
            not isinstance(atom_map, list)
            or len(atom_map) != 63
            or len(set(atom_map)) != 63
        ):
            raise ValueError(f"{product_id}: stable atom map is not a 63-key bijection")
        model_id = str(model.get("model_id") or "")
        if not model_id:
            raise ValueError(f"{product_id}: boundary model id is missing")
        job_dir = cases_root / product_id / "job"
        job = generate_psi4_job(
            product_id=product_id,
            model_id=model_id,
            xyz_path=xyz_path,
            output_dir=job_dir,
            job_kind="geometry_optimization",
            charge=-1,
            multiplicity=1,
            atom_map=atom_map,
            model_manifest_path=screen_path,
            memory_gib=100,
            threads=64,
            maximum_geometry_iterations=300,
        )
        if (
            job.get("method") != "mp2"
            or job.get("basis") != "6-31+G(d)"
            or job.get("protocol_version") != "1.5.0"
            or job.get("expected_outputs") != ["output.dat", "optimized.xyz"]
        ):
            raise ValueError(
                f"{product_id}: generated job does not match pinned protocol"
            )
        job_manifest = job_dir / "job_manifest.json"
        input_path = job_dir / "input.dat"
        case = {
            "schema": "nadoc.photoproduct-alpine-boundary-optimization-case.v1",
            "status": "generated_not_run",
            "gate_effect": "none",
            "simulation_ready": False,
            "product_id": product_id,
            "model_id": model_id,
            "charge": -1,
            "multiplicity": 1,
            "atom_count": 63,
            "stable_atom_map_sha256": _sha256(atom_map_path),
            "screened_boundary": {
                "path": str(screen_path),
                "sha256": _sha256(screen_path),
            },
            "job_manifest_sha256": _sha256(job_manifest),
            "input_sha256": _sha256(input_path),
            "source_xyz_sha256": _sha256(xyz_path),
            "protocol_version": job["protocol_version"],
            "method": job["method"],
            "basis": job["basis"],
            "resources": {
                "slurm_cpus": 64,
                "psi4_threads": 64,
                "slurm_memory_gib": 110,
                "psi4_memory_gib": 100,
                "walltime": "24:00:00",
            },
        }
        case_path = job_dir.parent / "case_manifest.json"
        case_path.write_text(json.dumps(case, indent=2) + "\n")
        case_hash = _sha256(case_path)
        lines.append(f"{index}\t{product_id}\t{case_hash}")
        records.append(
            {
                "array_index": index,
                "product_id": product_id,
                "case_manifest_sha256": case_hash,
            }
        )
    (bundle / "cases.tsv").write_text("\n".join(lines) + "\n")
    for name in ("run_case.sh", "campaign_64.sbatch"):
        shutil.copy2(Path(__file__).with_name(name), bundle / name)
    inventory = [
        f"{_sha256(path)}  {path.relative_to(bundle)}"
        for path in sorted(item for item in bundle.rglob("*") if item.is_file())
        if path.name != "MANIFEST.sha256"
    ]
    (bundle / "MANIFEST.sha256").write_text("\n".join(inventory) + "\n")
    archive = output_root / "alpine-boundary-optimization-campaign-v1.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(bundle, arcname="bundle")
    (archive.with_suffix(archive.suffix + ".sha256")).write_text(
        f"{_sha256(archive)}  {archive.name}\n"
    )
    report = {
        "schema": "nadoc.photoproduct-alpine-boundary-optimization-campaign.v1",
        "status": "built_not_submitted",
        "gate_effect": "none",
        "simulation_ready": False,
        "product_count": len(records),
        "products": records,
        "remote_root": str(REMOTE_ROOT),
        "archive": {"path": str(archive.resolve()), "sha256": _sha256(archive)},
        "interpretation": (
            "Full d(TpT) geometry optimizations are QM evidence only. Frequency, "
            "parameter fitting, and simulation validation remain required."
        ),
    }
    (output_root / "campaign_manifest.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graft-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                graft_root=args.graft_root.resolve(),
                output_root=args.output_root.resolve(),
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
