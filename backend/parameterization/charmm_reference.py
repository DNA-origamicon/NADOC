"""Extract reproducible initial guesses from a pinned CHARMM reference library."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from backend.core.photoproduct_chemistry import load_chemical_definition
from backend.core.photoproduct_registry import photoproduct_registry

REFERENCE_MANIFEST_PATH = (
    Path(__file__).parents[1]
    / "data"
    / "forcefield"
    / "photoproduct_reference_forcefields.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_charmm_residue(topology_path: Path, residue: str) -> dict[str, Any]:
    declared_charge = None
    atoms: list[dict[str, Any]] = []
    active = False
    for raw in topology_path.read_text(errors="replace").splitlines():
        fields = raw.split("!", 1)[0].split()
        if not fields:
            continue
        keyword = fields[0].upper()
        if keyword in {"RESI", "PRES"}:
            if active:
                break
            active = keyword == "RESI" and len(fields) >= 3 and fields[1] == residue
            if active:
                declared_charge = float(fields[2])
            continue
        if active and keyword == "ATOM" and len(fields) >= 4:
            atoms.append(
                {"name": fields[1], "atom_type": fields[2], "charge": float(fields[3])}
            )
    if declared_charge is None or not atoms:
        raise ValueError(f"residue {residue!r} not found in {topology_path}")
    actual = sum(item["charge"] for item in atoms)
    if abs(actual - declared_charge) > 1e-8:
        raise ValueError(
            f"residue {residue} atom charges sum to {actual}, declared {declared_charge}"
        )
    return {"residue": residue, "declared_charge": declared_charge, "atoms": atoms}


def _model_to_1mth_name(key: str) -> str:
    local = key.split(":", 1)[1]
    # Early source-derived model manifests retained CCD hydrogen names.  They are
    # losslessly mapped here so immutable QM evidence remains interpretable; new
    # model builds use the canonical stable names on the right-hand side.
    legacy_ccd_hydrogens = {
        "HN3": "H3",
        "HT": "H3",
        "H5A1": "H51",
        "H5A2": "H52",
        "H5A3": "H53",
        "H71": "H51",
        "H72": "H52",
        "H73": "H53",
    }
    if local in legacy_ccd_hydrogens:
        return legacy_ccd_hydrogens[local]
    if local == "CM":
        return "C1"
    if local.startswith("HCM"):
        suffix = local.removeprefix("HCM")
        if suffix not in {"1", "2", "3"}:
            raise ValueError(f"unsupported methyl-cap hydrogen key: {key}")
        return f"H1{suffix}"
    if local == "C7":
        return "C5M"
    return local


def extract_initial_charge_guess(
    *,
    cgenff_topology: Path,
    model_manifest_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Map pinned CGenFF 1MTH charges onto both halves of a TT-CPD model.

    The result is explicitly an initial guess. No product atom type or charge is
    accepted as final by this operation.
    """

    references = json.loads(REFERENCE_MANIFEST_PATH.read_text())
    expected = references["cgenff_reference_library"]["topology_sha256"]
    actual = _sha256(cgenff_topology)
    if actual != expected:
        raise ValueError(
            f"CGenFF topology hash mismatch: expected {expected}, found {actual}"
        )
    model = json.loads(model_manifest_path.read_text())
    if model.get("schema") != "nadoc.photoproduct-model-compound.v1":
        raise ValueError("unsupported model-compound manifest schema")
    entry = next(
        (
            item
            for item in photoproduct_registry()["products"]
            if item["id"] == model.get("product_id")
        ),
        None,
    )
    if entry is None:
        raise ValueError("model refers to an unregistered photoproduct")
    definition = load_chemical_definition(entry["product"], entry["stereochemistry"])
    recipe = definition["model_compounds"]["charge_model"]
    residue = parse_charmm_residue(cgenff_topology, "1MTH")
    reference_atoms = {item["name"]: item for item in residue["atoms"]}
    guesses = []
    for key in model["atom_map"]:
        source_name = _model_to_1mth_name(key)
        if source_name not in reference_atoms:
            raise ValueError(f"no 1MTH atom maps to model atom {key}")
        source = reference_atoms[source_name]
        guesses.append(
            {
                "model_atom": key,
                "source_residue": "1MTH",
                "source_atom": source_name,
                "source_atom_type": source["atom_type"],
                "initial_charge": source["charge"],
                "final_product_atom_type": None,
                "final_product_charge": None,
            }
        )
    total = sum(item["initial_charge"] for item in guesses)
    cap_totals = {
        str(endpoint): sum(
            item["initial_charge"]
            for item in guesses
            if item["model_atom"].startswith(f"{endpoint}:")
            and (
                item["model_atom"].endswith(":CM")
                or ":HCM" in item["model_atom"]
            )
        )
        for endpoint in (1, 2)
    }
    if abs(total - recipe["charge"]) > 1e-8 or any(
        abs(value) > 1e-8 for value in cap_totals.values()
    ):
        raise ValueError("mapped 1MTH charges violate the reviewed model constraints")
    total = 0.0 if abs(total) < 1e-12 else total
    cap_totals = {
        endpoint: 0.0 if abs(value) < 1e-12 else value
        for endpoint, value in cap_totals.items()
    }
    result = {
        "schema": "nadoc.photoproduct-initial-charge-guess.v1",
        "status": "initial_guess_not_fitted",
        "gate_effect": "none",
        "product_id": model["product_id"],
        "model_id": model["model_id"],
        "model_manifest_sha256": _sha256(model_manifest_path),
        "source": {
            "forcefield": "CGenFF 5.0",
            "residue": "1MTH",
            "topology_path": str(cgenff_topology.resolve()),
            "topology_sha256": actual,
        },
        "initial_total_charge": total,
        "initial_cap_charges": cap_totals,
        "fit_constraints": recipe["charge_constraints"],
        "atoms": guesses,
        "release_rule": "QM water-interaction/dipole fitting and validation are required; source atom types and charges are not product parameters",
    }
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing charge guess: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def build_atom_type_candidate_plan(
    *,
    cgenff_topology: Path,
    model_manifest_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Record chemically closer CGenFF type candidates without selecting final types."""

    references = json.loads(REFERENCE_MANIFEST_PATH.read_text())
    expected = references["cgenff_reference_library"]["topology_sha256"]
    actual = _sha256(cgenff_topology)
    if actual != expected:
        raise ValueError(
            f"CGenFF topology hash mismatch: expected {expected}, found {actual}"
        )
    model = json.loads(model_manifest_path.read_text())
    if model.get("schema") != "nadoc.photoproduct-model-compound.v1":
        raise ValueError("unsupported model-compound manifest schema")
    if model.get("product_id") != "tt-cpd-cis-syn":
        raise ValueError("the reviewed analog map currently covers cis-syn-I TT-CPD only")
    atom_map = model.get("atom_map")
    if not isinstance(atom_map, list) or len(atom_map) != len(set(atom_map)):
        raise ValueError("model manifest requires a unique stable atom map")
    residues = {
        name: parse_charmm_residue(cgenff_topology, name)
        for name in ("1MTH", "BMDU", "BH2U", "CBU")
    }
    by_residue = {
        name: {item["name"]: item for item in residue["atoms"]}
        for name, residue in residues.items()
    }

    def candidate(residue: str, atom: str, rationale: str, *, exact: bool) -> dict[str, Any]:
        source = by_residue[residue][atom]
        return {
            "source_residue": residue,
            "source_atom": atom,
            "source_type": source["atom_type"],
            "source_charge": source["charge"],
            "environment_match": "exact_candidate" if exact else "partial_only",
            "rationale": rationale,
        }

    records = []
    for key in atom_map:
        local = key.split(":", 1)[1]
        candidates: list[dict[str, Any]] = []
        decision = "review_transfer_candidate"
        if local == "CM" or local.startswith("HCM"):
            candidates.append(
                candidate(
                    "1MTH",
                    _model_to_1mth_name(key),
                    "unchanged neutral N1 methyl cap in the fitting model",
                    exact=True,
                )
            )
        elif local in {"N1", "C2", "O2", "N3", "H3", "C4", "O4"}:
            candidates.append(
                candidate(
                    "BMDU",
                    local,
                    "same atom in a C5-C6-saturated 5-methyldihydrouracil ring",
                    exact=True,
                )
            )
        elif local == "C7" or local in {"H51", "H52", "H53"}:
            source = "C5M" if local == "C7" else local
            candidates.append(
                candidate(
                    "BMDU",
                    source,
                    "same C5 methyl substituent in 5-methyldihydrouracil",
                    exact=True,
                )
            )
        elif local == "C5":
            decision = "new_product_type_required"
            candidates.extend(
                [
                    candidate(
                        "BMDU",
                        "C5",
                        "saturated thymine C5, but BMDU has one H and no CPD crosslink",
                        exact=False,
                    ),
                    candidate(
                        "CBU",
                        "C1",
                        "cyclobutane carbon, but CBU is CH2 rather than substituted C5",
                        exact=False,
                    ),
                ]
            )
        elif local == "C6":
            decision = "new_product_type_required"
            candidates.extend(
                [
                    candidate(
                        "BMDU",
                        "C6",
                        "saturated thymine C6, but BMDU is CH2 and lacks a CPD crosslink",
                        exact=False,
                    ),
                    candidate(
                        "CBU",
                        "C1",
                        "cyclobutane carbon, but CBU is CH2 rather than substituted C6",
                        exact=False,
                    ),
                ]
            )
        elif local == "H6":
            decision = "new_product_type_required"
            candidates.extend(
                [
                    candidate(
                        "BMDU",
                        "H5",
                        "aliphatic H on a saturated thymine CH center, but attached at C5",
                        exact=False,
                    ),
                    candidate(
                        "BMDU",
                        "H61",
                        "H on saturated thymine C6, but its source carbon is CH2",
                        exact=False,
                    ),
                ]
            )
        else:
            raise ValueError(f"no reviewed analog rule for stable atom {key}")
        records.append(
            {
                "model_atom": key,
                "decision": decision,
                "candidates": candidates,
                "final_type": None,
                "final_lj_source": None,
            }
        )
    report = {
        "schema": "nadoc.photoproduct-atom-type-candidate-plan.v1",
        "status": "review_required",
        "gate_effect": "none",
        "product_id": model["product_id"],
        "model_id": model["model_id"],
        "source": {
            "forcefield": "CGenFF 5.0 / CHARMM36 February 2026",
            "topology_path": str(cgenff_topology.resolve()),
            "topology_sha256": actual,
            "parameters_sha256": references["cgenff_reference_library"][
                "parameters_sha256"
            ],
            "residues": list(residues),
        },
        "model_manifest": {
            "path": str(model_manifest_path.resolve()),
            "sha256": _sha256(model_manifest_path),
        },
        "atoms": records,
        "unresolved_atoms": [
            item["model_atom"]
            for item in records
            if item["decision"] == "new_product_type_required"
        ],
        "release_rule": (
            "Every final type and Lennard-Jones source must be reviewed, then tested in "
            "the joint charge/bonded fit and held-out validation. Partial analogs cannot "
            "be selected automatically."
        ),
    }
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite atom-type plan: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
