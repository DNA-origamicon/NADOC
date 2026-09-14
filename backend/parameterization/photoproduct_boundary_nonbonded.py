"""Build a CHARMM36-preserving nonbonded specification for d(TpT)-CPD fits."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from backend.core.photoproduct_chemistry import load_patch_charge_scope
from backend.parameterization.charmm_reference import (
    REFERENCE_MANIFEST_PATH,
    parse_charmm_residue,
)


POLICY_PATH = (
    Path(__file__).parents[1]
    / "data"
    / "forcefield"
    / "photoproduct_boundary_nonbonded_policy.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _parse_patch(topology_path: Path, patch: str) -> dict[str, Any]:
    active = False
    declared_charge = None
    atoms: dict[str, dict[str, Any]] = {}
    deleted: set[str] = set()
    for raw in topology_path.read_text(errors="replace").splitlines():
        fields = raw.split("!", 1)[0].split()
        if not fields:
            continue
        keyword = fields[0].upper()
        if keyword in {"RESI", "PRES"}:
            if active:
                break
            active = keyword == "PRES" and len(fields) >= 3 and fields[1] == patch
            if active:
                declared_charge = float(fields[2])
            continue
        if active and keyword == "ATOM" and len(fields) >= 4:
            atoms[fields[1]] = {
                "name": fields[1],
                "atom_type": fields[2],
                "charge": float(fields[3]),
            }
        elif (
            active
            and keyword == "DELETE"
            and len(fields) >= 3
            and fields[1].upper() == "ATOM"
        ):
            deleted.add(fields[2])
    if declared_charge is None:
        raise ValueError(f"patch {patch!r} not found in {topology_path}")
    return {
        "name": patch,
        "declared_charge": declared_charge,
        "atoms": atoms,
        "deleted_atoms": sorted(deleted),
    }


def _effective_terminal_thymine(
    topology_path: Path, *, five_prime: bool
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    residue = parse_charmm_residue(topology_path, "THY")
    atoms = {item["name"]: dict(item) for item in residue["atoms"]}
    patches = [
        _parse_patch(topology_path, "DEOX"),
        _parse_patch(topology_path, "5TER" if five_prime else "3TER"),
    ]
    for patch in patches:
        for name in patch["deleted_atoms"]:
            atoms.pop(name, None)
        atoms.update({name: dict(record) for name, record in patch["atoms"].items()})
    return atoms, patches


def _stable_name(endpoint: int, charmm_name: str) -> str:
    aliases = {
        "O1P": "OP1",
        "O2P": "OP2",
        "C5M": "C7",
        "H5T": "HO5'",
        "H3T": "HO3'",
    }
    return f"{endpoint}:{aliases.get(charmm_name, charmm_name)}"


def build_boundary_nonbonded_specification(
    *,
    model_manifest_path: Path,
    nucleic_topology_path: Path,
    cgenff_topology_path: Path,
    cgenff_parameters_path: Path,
    output_path: Path,
    policy_path: Path = POLICY_PATH,
) -> dict[str, Any]:
    """Freeze native boundary values and expose exactly the product patch variables."""

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite boundary nonbonded spec: {output_path}"
        )
    model = json.loads(model_manifest_path.read_text())
    policy = json.loads(policy_path.read_text())
    references = json.loads(REFERENCE_MANIFEST_PATH.read_text())
    if (
        model.get("schema") != "nadoc.photoproduct-model-compound.v1"
        or model.get("status") != "optimized_full_boundary_fit_input"
        or model.get("atom_count") != 63
        or model.get("charge") != -1
        or policy.get("schema") != "nadoc.photoproduct-boundary-nonbonded-policy.v1"
        or policy.get("status") != "workflow_policy"
    ):
        raise ValueError("boundary model or nonbonded policy is incompatible")
    model_map_record = (model.get("outputs") or {}).get("atom_map") or {}
    model_graph_record = (model.get("outputs") or {}).get("graph") or {}
    model_map_path = Path(str(model_map_record.get("path") or ""))
    model_graph_path = Path(str(model_graph_record.get("path") or ""))
    if (
        not model_map_path.is_file()
        or _sha256(model_map_path) != model_map_record.get("sha256")
        or json.loads(model_map_path.read_text()) != model.get("atom_map")
        or not model_graph_path.is_file()
        or _sha256(model_graph_path) != model_graph_record.get("sha256")
    ):
        raise ValueError("boundary model atom map or graph is missing/hash-mismatched")
    graph = json.loads(model_graph_path.read_text())
    if (
        graph.get("schema") != "nadoc.photoproduct-model-graph.v1"
        or graph.get("formal_charge") != -1
        or [item.get("key") for item in graph.get("atoms") or []]
        != model.get("atom_map")
    ):
        raise ValueError("boundary model graph identity or charge is inconsistent")
    if (
        _sha256(nucleic_topology_path)
        != references["base_forcefield"]["topology"]["sha256"]
        or _sha256(cgenff_topology_path)
        != references["cgenff_reference_library"]["topology_sha256"]
        or _sha256(cgenff_parameters_path)
        != references["cgenff_reference_library"]["parameters_sha256"]
    ):
        raise ValueError("CHARMM36/CGenFF references differ from the pinned release")

    scope = load_patch_charge_scope(model["product"], model["stereochemistry"])
    variable_atoms = list(scope["atoms_with_charges_replaced"])
    atom_map = list(model["atom_map"])
    if (
        len(variable_atoms) != 28
        or len(set(variable_atoms)) != 28
        or not set(variable_atoms).issubset(atom_map)
        or scope.get("expected_pair_charge") != 0
    ):
        raise ValueError(
            "registry patch charge scope is not the conserved 28-atom pair"
        )

    endpoint_atoms = {
        endpoint: _effective_terminal_thymine(
            nucleic_topology_path, five_prime=endpoint == 1
        )
        for endpoint in (1, 2)
    }
    native_by_stable: dict[str, dict[str, Any]] = {}
    patch_records = []
    for endpoint, (atoms, patches) in endpoint_atoms.items():
        for name, record in atoms.items():
            native_by_stable[_stable_name(endpoint, name)] = record
        patch_records.extend(
            {
                "endpoint": endpoint,
                "patch": patch["name"],
                "declared_charge": patch["declared_charge"],
            }
            for patch in patches
        )
    missing_native = sorted(set(atom_map) - set(native_by_stable))
    unexpected_native = sorted(set(native_by_stable) - set(atom_map))
    if missing_native or unexpected_native:
        raise ValueError(
            "effective CHARMM terminal model and stable atom map differ: "
            f"missing={missing_native}, unexpected={unexpected_native}"
        )

    local_types = policy["type_hypothesis"]["product_local_types"]
    variable_records = []
    fixed_records = []
    for key in atom_map:
        native = native_by_stable[key]
        if key in variable_atoms:
            local = key.split(":", 1)[1]
            if local not in local_types:
                raise ValueError(f"nonbonded policy has no product type for {key}")
            variable_records.append(
                {
                    "atom": key,
                    "initial_charge_e": native["charge"],
                    "candidate_type": local_types[local],
                    "native_type": native["atom_type"],
                }
            )
        else:
            fixed_records.append(
                {
                    "atom": key,
                    "charge_e": native["charge"],
                    "atom_type": native["atom_type"],
                }
            )
    variable_initial_total = sum(item["initial_charge_e"] for item in variable_records)
    fixed_total = sum(item["charge_e"] for item in fixed_records)
    if abs(variable_initial_total) > 1e-8 or abs(fixed_total + 1.0) > 1e-8:
        raise ValueError(
            "effective native charge partition does not conserve d(TpT) charge"
        )
    variable_initial_total = (
        0.0 if abs(variable_initial_total) < 1e-12 else variable_initial_total
    )
    fixed_total = -1.0 if abs(fixed_total + 1.0) < 1e-12 else fixed_total
    constraints = policy["charge_scope"]
    if (
        constraints.get("endpoint_exchange_symmetry") is not False
        or abs(float(constraints.get("variable_total_charge_e")) - 0.0) > 1e-12
        or any(
            not set(group).issubset(variable_atoms)
            for group in constraints["equal_charge_groups"]
        )
    ):
        raise ValueError(
            "boundary charge constraints are not the ordered-product policy"
        )

    report = {
        "schema": "nadoc.photoproduct-boundary-nonbonded-specification.v1",
        "status": "fit_specification_complete_not_fitted",
        "gate_effect": "none",
        "simulation_ready": False,
        "product_id": model["product_id"],
        "model_id": model["model_id"],
        "product": model["product"],
        "stereochemistry": model["stereochemistry"],
        "atom_map": atom_map,
        "candidate_hypothesis_id": policy["type_hypothesis"]["id"],
        "variable_atoms": variable_records,
        "fixed_atoms": fixed_records,
        "charge_audit": {
            "variable_atom_count": len(variable_records),
            "fixed_atom_count": len(fixed_records),
            "initial_variable_charge_e": variable_initial_total,
            "fixed_charge_e": fixed_total,
            "total_model_charge_e": variable_initial_total + fixed_total,
            "endpoint_exchange_symmetry_enforced": False,
            "equal_charge_groups": constraints["equal_charge_groups"],
        },
        "effective_patches": patch_records,
        "evidence_partition": policy["evidence_partition"],
        "acceptance": policy["acceptance"],
        "sources": {
            "model_manifest": _source(model_manifest_path),
            "patch_charge_scope": scope["source"],
            "policy": _source(policy_path),
            "reference_manifest": _source(REFERENCE_MANIFEST_PATH),
            "nucleic_topology": _source(nucleic_topology_path),
            "cgenff_topology": _source(cgenff_topology_path),
            "cgenff_parameters": _source(cgenff_parameters_path),
        },
        "next_required_step": (
            "fit only variable_atoms against full-boundary ESP and training water targets; "
            "select by held-out ESP/water metrics and preserve fixed_atoms exactly"
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
