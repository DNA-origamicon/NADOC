"""Render reviewed photoproduct workbooks into gate-neutral CHARMM assets.

This module is intentionally downstream of the workbook completeness audit. It does not
assign atom types, charges, or force constants, and its output is not a release merely
because it is syntactically renderable.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable

from backend.core.namd_topology import charmm_atom_name
from backend.core.photoproduct_chemistry import load_chemical_definition
from backend.core.photoproduct_registry import photoproduct_registry


_VARIANT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atom_ref(reference: str) -> str:
    endpoint, separator, name = reference.partition(":")
    if not separator or endpoint not in {"1", "2"} or not name:
        raise ValueError(f"invalid ordered photoproduct atom reference: {reference!r}")
    mapped = charmm_atom_name(name)
    if len(endpoint + mapped) > 8:
        raise ValueError(f"CHARMM patch atom reference is too long: {reference!r}")
    return endpoint + mapped


def _types(record: dict[str, Any], width: int) -> list[str]:
    values = record.get("types")
    if (
        not isinstance(values, list)
        or len(values) != width
        or not all(isinstance(value, str) and value for value in values)
    ):
        raise ValueError(f"reviewed parameter record lacks {width} CHARMM atom types")
    return values


def _finite(record: dict[str, Any], field: str) -> float:
    value = record.get(field)
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"reviewed parameter record lacks finite {field}")
    return float(value)


def _parameter_lines(workbook: dict[str, Any]) -> list[str]:
    bonded = workbook["bonded_terms"]
    emitted: dict[tuple[Any, ...], tuple[float, ...]] = {}

    def should_emit(
        category: str,
        types: list[str],
        values: tuple[float, ...],
        *,
        reversible: bool,
        suffix: tuple[Any, ...] = (),
    ) -> bool:
        signature = tuple(types)
        if reversible:
            signature = min(signature, tuple(reversed(signature)))
        key = (category, *signature, *suffix)
        previous = emitted.get(key)
        if previous is None:
            emitted[key] = values
            return True
        if previous != values:
            raise ValueError(
                f"conflicting duplicate {category} parameter for {' '.join(types)}"
            )
        return False

    lines = [
        "* NADOC reviewed photoproduct candidate parameters",
        "* Gate-neutral output: requires psfgen, NAMD, solution, and release review.",
        "*",
        "",
        "BONDS",
    ]
    for record in bonded["bonds"]:
        if not record["emit_parameter"]:
            continue
        types = _types(record, 2)
        values = (
            _finite(record, "k_kcal_mol_a2"),
            _finite(record, "r0_angstrom"),
        )
        if not should_emit("bond", types, values, reversible=True):
            continue
        lines.append(f"{' '.join(types):<19} {values[0]:12.6f} {values[1]:11.6f}")
    lines.extend(["", "ANGLES"])
    for record in bonded["angles"]:
        if not record["emit_parameter"]:
            continue
        types = _types(record, 3)
        values = (
            _finite(record, "k_kcal_mol_rad2"),
            _finite(record, "theta0_degrees"),
        )
        ub_k = record.get("urey_bradley_k_kcal_mol_a2")
        ub_r = record.get("urey_bradley_s0_angstrom")
        if (ub_k is None) != (ub_r is None):
            raise ValueError(
                "Urey-Bradley force constant and distance must occur together"
            )
        complete_values = values + (() if ub_k is None else (float(ub_k), float(ub_r)))
        if not should_emit("angle", types, complete_values, reversible=True):
            continue
        line = f"{' '.join(types):<28} {values[0]:12.6f} {values[1]:11.6f}"
        if ub_k is not None:
            line += f" {float(ub_k):12.6f} {float(ub_r):11.6f}"
        lines.append(line)
    lines.extend(["", "DIHEDRALS"])
    for record in bonded["dihedrals"]:
        if not record["emit_parameter"]:
            continue
        types = _types(record, 4)
        for term in record["fourier_terms"]:
            multiplicity = _finite(term, "multiplicity")
            if multiplicity <= 0 or not multiplicity.is_integer():
                raise ValueError(
                    "CHARMM dihedral multiplicity must be a positive integer"
                )
            k_value = _finite(term, "k_kcal_mol")
            delta = _finite(term, "delta_degrees")
            if not should_emit(
                "dihedral",
                types,
                (k_value,),
                reversible=True,
                suffix=(int(multiplicity), delta),
            ):
                continue
            lines.append(
                f"{' '.join(types):<37} {k_value:12.6f} "
                f"{int(multiplicity):3d} {delta:11.6f}"
            )
    lines.extend(["", "IMPROPER"])
    for record in bonded["impropers_added"]:
        if not record["emit_parameter"]:
            continue
        types = _types(record, 4)
        values = (
            _finite(record, "k_kcal_mol_rad2"),
            _finite(record, "psi0_degrees"),
        )
        if not should_emit("improper", types, values, reversible=False):
            continue
        lines.append(f"{' '.join(types):<37} {values[0]:12.6f} 0 {values[1]:11.6f}")

    custom_types = workbook["charmm_patch"]["custom_atom_types"]
    if custom_types:
        lines.extend(
            [
                "",
                "NONBONDED NBXMOD 5 ATOM CDIEL FSHIFT VATOM VDISTANCE VFSWITCH -",
                "     CUTNB 14.0 CTOFNB 12.0 CTONNB 10.0 EPS 1.0 E14FAC 1.0 WMIN 1.5",
            ]
        )
        for record in sorted(custom_types, key=lambda item: item["name"]):
            line = (
                f"{record['name']:<8} 0.0 "
                f"{float(record['epsilon_kcal_mol']):12.6f} "
                f"{float(record['rmin_half_angstrom']):11.6f}"
            )
            if record.get("epsilon_14_kcal_mol") is not None:
                line += (
                    f" 0.0 {float(record['epsilon_14_kcal_mol']):12.6f} "
                    f"{float(record['rmin_half_14_angstrom']):11.6f}"
                )
            lines.append(line)
    lines.extend(["", "END", ""])
    return lines


def _joined_atoms(records: Iterable[dict[str, Any]], key: str) -> list[str]:
    output = []
    for record in records:
        atoms = record.get(key)
        if not isinstance(atoms, list) or len(atoms) != 4:
            raise ValueError("reviewed improper record lacks four ordered atoms")
        output.append(" ".join(_atom_ref(atom) for atom in atoms))
    return output


def _topology_lines(workbook: dict[str, Any], definition: dict[str, Any]) -> list[str]:
    patch = workbook["charmm_patch"]
    patch_name = patch["patch_name"]
    atoms = sorted(workbook["atoms"], key=lambda item: item["atom"])
    charge = sum(float(item["final_charge"]) for item in atoms)
    lines = [
        "* NADOC reviewed photoproduct candidate topology patch",
        "* Gate-neutral output: requires psfgen, NAMD, solution, and release review.",
        "*",
        "36 1",
        "",
    ]
    for record in sorted(patch["custom_atom_types"], key=lambda item: item["name"]):
        lines.append(
            f"MASS -1 {record['name']:<8} {float(record['mass_amu']):11.6f} "
            f"! {record['element']} ; source recorded in audited workbook"
        )
    if patch["custom_atom_types"]:
        lines.append("")
    lines.append(
        f"PRES {patch_name:<8} {charge:10.6f} ! ordered two-residue product patch"
    )
    for record in atoms:
        lines.append(
            f"ATOM {_atom_ref(record['atom']):<8} {record['final_type']:<8} "
            f"{float(record['final_charge']):11.6f}"
        )
    for bond in definition["graph_delta"]["bonds_added"]:
        lines.append(f"BOND {_atom_ref(bond['atom_1'])} {_atom_ref(bond['atom_2'])}")
    added_impropers = _joined_atoms(
        workbook["bonded_terms"]["impropers_added"], "ordered_atoms"
    )
    added_improper_set = set(added_impropers)
    for joined in _joined_atoms(
        workbook["bonded_terms"]["impropers_removed"], "ordered_atoms"
    ):
        # If the reviewed product uses the exact precursor ordering, changing its
        # atom types is sufficient.  psfgen remembers DELETE within the patch and
        # will not restore the identical tuple with a later IMPR statement.
        if joined in added_improper_set:
            continue
        lines.append(f"DELETE IMPR {joined}")
    for joined in added_impropers:
        lines.append(f"IMPR {joined}")
    lines.extend(["", "END", ""])
    return lines


def _audit_spec(workbook: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    translate_path = lambda atoms: [
        atom.split(":", 1)[0] + ":" + charmm_atom_name(atom.split(":", 1)[1])
        for atom in atoms
    ]
    return {
        "schema": "nadoc.photoproduct-topology-audit-spec.v1",
        "product_id": definition["id"],
        "expected_product_atoms": [
            {
                "atom": translate_path([record["atom"]])[0],
                "type": record["final_type"],
                "charge": float(record["final_charge"]),
            }
            for record in sorted(workbook["atoms"], key=lambda item: item["atom"])
        ],
        "crosslinks": [
            translate_path([bond["atom_1"], bond["atom_2"]])
            for bond in definition["graph_delta"]["bonds_added"]
        ],
        "retained_bonds": [
            translate_path([bond["atom_1"], bond["atom_2"]])
            for bond in definition["graph_delta"]["bonds_retained"]
        ],
        "impropers_added": [
            translate_path(record["ordered_atoms"])
            for record in workbook["bonded_terms"]["impropers_added"]
        ],
        "impropers_removed": [
            translate_path(record["ordered_atoms"])
            for record in workbook["bonded_terms"]["impropers_removed"]
        ],
    }


def export_charmm_candidate_assets(
    *,
    workbook_path: Path,
    workbook_audit_path: Path,
    output_dir: Path,
    variant_id: str | None = None,
    parent_candidate_manifest_path: Path | None = None,
    correction_policy_path: Path | None = None,
) -> dict[str, Any]:
    """Render, hash, and manifest a complete reviewed candidate without releasing it."""

    if output_dir.exists():
        if not output_dir.is_dir() or any(output_dir.iterdir()):
            raise FileExistsError(
                f"refusing to overwrite CHARMM candidate directory: {output_dir}"
            )
    workbook = json.loads(workbook_path.read_text())
    audit = json.loads(workbook_audit_path.read_text())
    workbook_hash = _sha256(workbook_path)
    if (
        workbook.get("schema") != "nadoc.photoproduct-parameter-workbook.v1"
        or audit.get("schema") != "nadoc.photoproduct-parameter-workbook-audit.v1"
        or audit.get("status") != "complete_candidate"
        or audit.get("passed") is not True
        or audit.get("product_id") != workbook.get("product_id")
        or audit.get("workbook_sha256") != workbook_hash
    ):
        raise ValueError(
            "CHARMM export requires a passed hash-linked parameter workbook audit"
        )
    registry_entry = next(
        (
            item
            for item in photoproduct_registry()["products"]
            if item["id"] == workbook["product_id"]
        ),
        None,
    )
    if registry_entry is None:
        raise ValueError("parameter workbook product is not registered")
    definition = load_chemical_definition(
        registry_entry["product"], registry_entry["stereochemistry"]
    )
    if definition["id"] != workbook["product_id"]:
        raise ValueError("parameter workbook and chemical definition identities differ")
    resolved_variant_id = variant_id or f"{definition['id']}-{workbook_hash[:12]}"
    if not _VARIANT_ID_RE.fullmatch(resolved_variant_id):
        raise ValueError(
            "candidate variant_id must be 3-80 lowercase letters, digits, dot, "
            "underscore, or hyphen"
        )
    if (parent_candidate_manifest_path is None) != (correction_policy_path is None):
        raise ValueError(
            "a corrected variant requires both a parent candidate manifest and "
            "correction policy"
        )
    parent_source = None
    correction_source = None
    if parent_candidate_manifest_path is not None and correction_policy_path is not None:
        parent = json.loads(parent_candidate_manifest_path.read_text())
        correction = json.loads(correction_policy_path.read_text())
        if (
            parent.get("schema") != "nadoc.photoproduct-charmm-candidate.v1"
            or parent.get("product_id") != definition["id"]
            or parent.get("gate_effect") != "none"
        ):
            raise ValueError("parent candidate manifest has incompatible identity")
        if (
            correction.get("schema")
            != "nadoc.photoproduct-bonded-refit-policy.v1"
            or correction.get("status") != "workflow_policy"
            or correction.get("product_id") != definition["id"]
        ):
            raise ValueError("correction policy has incompatible product identity")
        parent_variant = (parent.get("variant") or {}).get("id")
        if parent_variant == resolved_variant_id:
            raise ValueError("corrected variant must not reuse its parent variant ID")
        parent_source = {
            "path": str(parent_candidate_manifest_path.resolve()),
            "sha256": _sha256(parent_candidate_manifest_path),
            "variant_id": parent_variant,
        }
        correction_source = {
            "path": str(correction_policy_path.resolve()),
            "sha256": _sha256(correction_policy_path),
            "version": correction.get("version"),
            "variant_family": correction.get("variant_family"),
        }

    topology_text = "\n".join(_topology_lines(workbook, definition))
    parameter_text = "\n".join(_parameter_lines(workbook))
    topology_spec = _audit_spec(workbook, definition)
    output_dir.mkdir(parents=True, exist_ok=True)
    topology_path = output_dir / "photoproduct.rtf"
    parameter_path = output_dir / "photoproduct.prm"
    spec_path = output_dir / "topology_audit_spec.json"
    topology_path.write_text(topology_text)
    parameter_path.write_text(parameter_text)
    spec_path.write_text(json.dumps(topology_spec, indent=2) + "\n")
    manifest = {
        "schema": "nadoc.photoproduct-charmm-candidate.v1",
        "status": "candidate_requires_psfgen_namd_solution_and_release_review",
        "gate_effect": "none",
        "product_id": definition["id"],
        "patch_name": workbook["charmm_patch"]["patch_name"],
        "variant": {
            "schema": "nadoc.photoproduct-parameter-variant.v1",
            "id": resolved_variant_id,
            "kind": "corrected_candidate" if parent_source else "parameter_candidate",
            "parent_candidate_manifest": parent_source,
            "correction_policy": correction_source,
            "parameter_workbook_sha256": workbook_hash,
        },
        "sources": {
            "parameter_workbook": {
                "path": str(workbook_path.resolve()),
                "sha256": workbook_hash,
            },
            "parameter_workbook_audit": {
                "path": str(workbook_audit_path.resolve()),
                "sha256": _sha256(workbook_audit_path),
            },
        },
        "assets": {
            "topology": {"path": topology_path.name, "sha256": _sha256(topology_path)},
            "parameters": {
                "path": parameter_path.name,
                "sha256": _sha256(parameter_path),
            },
            "topology_audit_spec": {
                "path": spec_path.name,
                "sha256": _sha256(spec_path),
            },
        },
        "release_blockers": [
            "warning-free real psfgen build and static product/reactant topology audit",
            "warning-free NAMD parameter load, staged minimization, and 2 fs smoke trajectory",
            "solution/context validation and independent release review",
        ],
    }
    manifest_path = output_dir / "candidate_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
