"""Build reviewed QM model compounds from hash-verified structural references.

RDKit is imported lazily because model construction runs in the isolated
``nadoc-qm`` environment, while NADOC's web backend must not depend on it.
"""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import shlex
from typing import Any

import numpy as np

from backend.core.photoproduct_chemistry import (
    audit_product_chirality,
    chemical_definition_asset,
    load_chemical_definition,
)
from backend.parameterization.photoproduct_references import sha256_file


PARAMETER_ACCEPTANCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "forcefield"
    / "photoproduct_parameter_acceptance.json"
)
GRAFTED_BOUNDARY_POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "forcefield"
    / "photoproduct_grafted_boundary_policy_v1.json"
)
FLEXIBLE_BOUNDARY_SEED_POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "forcefield"
    / "photoproduct_flexible_boundary_seed_policy_v1.json"
)


class ModelConstructionError(RuntimeError):
    """A requested model cannot be constructed from the reviewed recipe."""


def _source(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": sha256_file(path)}


def materialize_reviewed_dna_boundary_model(
    *,
    candidate_manifest_path: Path,
    visual_decisions_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Bind an explicit visual cap/protonation approval to one boundary model."""

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite reviewed boundary model: {output_path}"
        )
    candidate_manifest_path = candidate_manifest_path.resolve()
    visual_decisions_path = visual_decisions_path.resolve()
    candidate = json.loads(candidate_manifest_path.read_text())
    visual = json.loads(visual_decisions_path.read_text())
    if (
        candidate.get("schema") != "nadoc.photoproduct-dna-boundary-model-candidate.v1"
        or candidate.get("status") != "candidate_pending_cap_review"
        or candidate.get("gate_effect") != "none"
        or candidate.get("product_id") != "tt-cpd-cis-syn"
        or not (candidate.get("chirality_audit") or {}).get("passed")
    ):
        raise ValueError(
            "a passed-identity, cap-review-pending boundary candidate is required"
        )
    if (
        visual.get("schema") != "nadoc.photoproduct-visual-review-decisions.v1"
        or visual.get("simulation_ready") is not False
        or visual.get("gate_effect") != "none"
    ):
        raise ValueError("a gate-neutral visual decision store is required")

    resolved_outputs: dict[str, dict[str, str]] = {}
    for name, record in (candidate.get("outputs") or {}).items():
        path = Path(str(record.get("path") or ""))
        fallback = candidate_manifest_path.parent / path.name
        if not path.is_file() or sha256_file(path) != record.get("sha256"):
            path = fallback
        if not path.is_file() or sha256_file(path) != record.get("sha256"):
            raise ValueError(f"boundary candidate {name} is missing or hash-mismatched")
        resolved_outputs[name] = {
            "path": str(path.resolve()),
            "sha256": str(record["sha256"]),
        }
    if set(resolved_outputs) != {"xyz", "atom_map", "sdf"}:
        raise ValueError("boundary candidate output inventory is incomplete")

    chain = str((candidate.get("source_selection") or {}).get("chain") or "").lower()
    review_id = f"chain-{chain}"
    matches = [
        item
        for item in visual.get("decisions") or []
        if isinstance(item, dict)
        and item.get("stage") == "dna_boundary_model"
        and item.get("product_id") == candidate["product_id"]
        and item.get("conformer_id") == review_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"boundary candidate requires one current decision for {review_id}"
        )
    decision = matches[0]
    if decision.get("decision") != "approve":
        raise ValueError(f"boundary candidate {review_id} is not approved")
    if decision.get("partition") is not None:
        raise ValueError("boundary approval cannot enter a fit partition")
    if decision.get("source_geometry_sha256") != resolved_outputs["xyz"]["sha256"]:
        raise ValueError("boundary visual decision is stale or geometry-mismatched")
    reviewer = str(decision.get("reviewer") or "").strip()
    notes = str(decision.get("notes") or "").strip()
    reviewed_at_raw = str(decision.get("reviewed_at") or "").strip()
    try:
        reviewed_at = datetime.fromisoformat(reviewed_at_raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("boundary visual decision timestamp is invalid") from exc
    if (
        len(reviewer) < 2
        or len(notes) < 12
        or reviewed_at.tzinfo is None
        or reviewed_at.utcoffset() is None
    ):
        raise ValueError("boundary visual decision identity/rationale is incomplete")

    reviewed = deepcopy(candidate)
    reviewed["status"] = "human_cap_review_complete"
    reviewed["outputs"] = resolved_outputs
    reviewed["cap_review"] = {
        "decision": "APPROVE",
        "reviewer": reviewer,
        "reviewed_at": reviewed_at_raw,
        "rationale": notes,
        "review_id": review_id,
        "source_geometry_sha256": resolved_outputs["xyz"]["sha256"],
        "source_visual_decisions": {
            "path": str(visual_decisions_path),
            "sha256": sha256_file(visual_decisions_path),
        },
        "source_candidate_manifest": {
            "path": str(candidate_manifest_path),
            "sha256": sha256_file(candidate_manifest_path),
        },
    }
    reviewed["release_blockers"] = [
        blocker
        for blocker in reviewed.get("release_blockers") or []
        if "cap" not in blocker.lower()
    ]
    reviewed["simulation_ready"] = False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(reviewed, indent=2) + "\n")
    return reviewed


def materialize_quantitatively_screened_dna_boundary_model(
    *,
    candidate_manifest_path: Path,
    replicate_audit_path: Path,
    output_path: Path,
    policy_path: Path = PARAMETER_ACCEPTANCE_PATH,
) -> dict[str, Any]:
    """Authorize boundary-model QM using exact graph and replicate metrics.

    This is a model-input screen only.  It does not assert that the resulting force
    field is acceptable and deliberately leaves every simulation release gate closed.
    """

    try:
        from rdkit import Chem
    except ImportError as exc:
        raise ModelConstructionError(
            "RDKit is required; run this command with the nadoc-qm environment"
        ) from exc
    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite screened boundary model: {output_path}"
        )
    candidate_manifest_path = candidate_manifest_path.resolve()
    replicate_audit_path = replicate_audit_path.resolve()
    policy_path = policy_path.resolve()
    candidate = json.loads(candidate_manifest_path.read_text())
    replicate = json.loads(replicate_audit_path.read_text())
    policy = json.loads(policy_path.read_text())
    gate = (policy.get("automated_qm_input_gates") or {}).get(
        "dna_boundary_model"
    ) or {}
    if (
        candidate.get("schema") != "nadoc.photoproduct-dna-boundary-model-candidate.v1"
        or candidate.get("status") != "candidate_pending_cap_review"
        or candidate.get("gate_effect") != "none"
        or candidate.get("product_id") != "tt-cpd-cis-syn"
        or candidate.get("model_id") != "cis-syn-dtpdT-dinucleoside-monophosphate"
        or candidate.get("formal_charge") != -1
        or candidate.get("atom_count") != 63
        or not (candidate.get("chirality_audit") or {}).get("passed")
    ):
        raise ValueError(
            "a passed-identity cis-syn d(TpT) boundary candidate is required"
        )
    if (
        policy.get("schema") != "nadoc.photoproduct-parameter-acceptance.v2"
        or gate.get("policy") != "exact-dtpdt-boundary-and-replicates-v1"
        or replicate.get("schema")
        != "nadoc.photoproduct-dna-boundary-replicate-audit.v1"
        or replicate.get("product_id") != candidate["product_id"]
        or replicate.get("gate_effect") != "none"
    ):
        raise ValueError("boundary quantitative policy or replicate audit is invalid")

    resolved_outputs: dict[str, dict[str, str]] = {}
    for name, record in (candidate.get("outputs") or {}).items():
        path = Path(str(record.get("path") or ""))
        fallback = candidate_manifest_path.parent / path.name
        if not path.is_file() or sha256_file(path) != record.get("sha256"):
            path = fallback
        if not path.is_file() or sha256_file(path) != record.get("sha256"):
            raise ValueError(f"boundary candidate {name} is missing or hash-mismatched")
        resolved_outputs[name] = {
            "path": str(path.resolve()),
            "sha256": record["sha256"],
        }
    if set(resolved_outputs) != {"xyz", "atom_map", "sdf"}:
        raise ValueError("boundary candidate output inventory is incomplete")
    atom_map = json.loads(Path(resolved_outputs["atom_map"]["path"]).read_text())
    xyz_lines = Path(resolved_outputs["xyz"]["path"]).read_text().splitlines()
    if (
        atom_map != candidate.get("atom_map")
        or len(atom_map) != 63
        or len(atom_map) != len(set(atom_map))
        or int(xyz_lines[0]) != len(atom_map)
        or len(xyz_lines[2:]) != len(atom_map)
    ):
        raise ValueError("boundary stable atom identity is incomplete or mismatched")
    supplier = Chem.SDMolSupplier(resolved_outputs["sdf"]["path"], removeHs=False)
    molecule = supplier[0] if supplier and len(supplier) == 1 else None
    if molecule is None:
        raise ValueError("RDKit could not sanitize the boundary SDF")
    Chem.SanitizeMol(molecule)
    if (
        molecule.GetNumAtoms() != len(atom_map)
        or [atom.GetSymbol() for atom in molecule.GetAtoms()]
        != [line.split()[0] for line in xyz_lines[2:]]
        or sum(atom.GetFormalCharge() for atom in molecule.GetAtoms()) != -1
    ):
        raise ValueError("boundary SDF, XYZ, and declared charge differ")

    expected: dict[tuple[str, str], float] = {}

    def add(first: str, second: str, order: float = 1.0) -> None:
        expected[tuple(sorted((first, second)))] = order

    sugar = (
        ("O5'", "C5'"),
        ("C5'", "C4'"),
        ("C4'", "O4'"),
        ("O4'", "C1'"),
        ("C1'", "C2'"),
        ("C2'", "C3'"),
        ("C3'", "C4'"),
        ("C3'", "O3'"),
        ("C1'", "N1"),
    )
    base = (
        ("N1", "C2", 1.0),
        ("C2", "O2", 2.0),
        ("C2", "N3", 1.0),
        ("N3", "C4", 1.0),
        ("C4", "O4", 2.0),
        ("C4", "C5", 1.0),
        ("C5", "C6", 1.0),
        ("C6", "N1", 1.0),
        ("C5", "C7", 1.0),
    )
    for endpoint in ("1", "2"):
        for first, second in sugar:
            add(f"{endpoint}:{first}", f"{endpoint}:{second}")
        for first, second, order in base:
            add(f"{endpoint}:{first}", f"{endpoint}:{second}", order)
    for first, second in (
        ("1:O3'", "2:P"),
        ("2:P", "2:O5'"),
        ("2:P", "2:OP1"),
        ("2:P", "2:OP2"),
        ("1:C5", "2:C5"),
        ("1:C6", "2:C6"),
    ):
        add(first, second)
    hydrogen_parents = {
        "1:HO5'": "1:O5'",
        "2:HO3'": "2:O3'",
        "1:H5'": "1:C5'",
        "1:H5''": "1:C5'",
        "2:H5'": "2:C5'",
        "2:H5''": "2:C5'",
        "1:H4'": "1:C4'",
        "2:H4'": "2:C4'",
        "1:H3'": "1:C3'",
        "2:H3'": "2:C3'",
        "1:H2'": "1:C2'",
        "1:H2''": "1:C2'",
        "2:H2'": "2:C2'",
        "2:H2''": "2:C2'",
        "1:H1'": "1:C1'",
        "2:H1'": "2:C1'",
        "1:H3": "1:N3",
        "2:H3": "2:N3",
        "1:H51": "1:C7",
        "1:H52": "1:C7",
        "1:H53": "1:C7",
        "2:H51": "2:C7",
        "2:H52": "2:C7",
        "2:H53": "2:C7",
        "1:H6": "1:C6",
        "2:H6": "2:C6",
    }
    for hydrogen, parent in hydrogen_parents.items():
        add(hydrogen, parent)
    actual = {
        tuple(
            sorted((atom_map[bond.GetBeginAtomIdx()], atom_map[bond.GetEndAtomIdx()]))
        ): float(bond.GetBondTypeAsDouble())
        for bond in molecule.GetBonds()
    }
    if actual.keys() != expected.keys() or any(
        abs(actual[pair] - order) > 1.0e-8 for pair, order in expected.items()
    ):
        raise ValueError(
            "boundary SDF does not have the exact declared d(TpT)-CPD graph"
        )
    phosphorus = molecule.GetAtomWithIdx(atom_map.index("2:P"))
    if phosphorus.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED:
        raise ValueError(
            "ordinary phosphate must not acquire a coordinate-defined stereolabel"
        )
    distance_rule = gate["product_crosslink_distance_angstrom"]
    if any(
        not float(distance_rule["minimum"])
        <= float(value)
        <= float(distance_rule["maximum"])
        for value in (candidate.get("crosslink_distances") or {}).values()
    ):
        raise ValueError("boundary product crosslink distance is outside policy")
    candidate_hashes = {
        item.get("sha256") for item in replicate.get("candidate_manifests") or []
    }
    if (
        sha256_file(candidate_manifest_path) not in candidate_hashes
        or len(candidate_hashes) < 2
    ):
        raise ValueError(
            "replicate audit does not include this candidate and an independent copy"
        )
    rmsd_limit = float(gate["replicate_all_heavy_rmsd_angstrom"]["maximum"])
    max_limit = float(gate["replicate_maximum_heavy_displacement_angstrom"]["maximum"])
    comparisons = replicate.get("comparisons") or []
    if not comparisons or any(
        item.get("reflection_used") is not False
        or abs(float(item.get("proper_rotation_determinant")) - 1.0) > 1.0e-6
        or float(item.get("all_heavy_rmsd_angstrom")) > rmsd_limit
        or float(item.get("maximum_heavy_displacement_angstrom")) > max_limit
        for item in comparisons
    ):
        raise ValueError(
            "independent boundary copies fail the proper-rotation replicate policy"
        )

    screened = deepcopy(candidate)
    screened["status"] = "quantitatively_screened_boundary"
    screened["outputs"] = resolved_outputs
    screened["quantitative_screening"] = {
        "schema": "nadoc.photoproduct-dna-boundary-quantitative-screen.v1",
        "status": "passed_qm_input_screen",
        "policy": gate["policy"],
        "policy_source": {"path": str(policy_path), "sha256": sha256_file(policy_path)},
        "source_candidate_manifest": {
            "path": str(candidate_manifest_path),
            "sha256": sha256_file(candidate_manifest_path),
        },
        "source_replicate_audit": {
            "path": str(replicate_audit_path),
            "sha256": sha256_file(replicate_audit_path),
        },
        "authorizes": "boundary_qm_evidence_generation_only",
        "releases_parameters": False,
    }
    screened["release_blockers"] = [
        blocker
        for blocker in screened.get("release_blockers") or []
        if "independent review" not in blocker.lower()
    ]
    screened["simulation_ready"] = False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(screened, indent=2) + "\n")
    return screened


def _ccd_atom_rows(cif_path: Path) -> list[dict[str, str]]:
    """Read the single-row-per-line CCD atom loop used by RCSB ligand CIF files."""

    lines = cif_path.read_text().splitlines()
    headers: list[str] = []
    rows: list[dict[str, str]] = []
    in_atom_loop = False
    for line in lines:
        stripped = line.strip()
        if stripped == "loop_":
            headers = []
            in_atom_loop = False
            continue
        if stripped.startswith("_chem_comp_atom."):
            headers.append(stripped)
            in_atom_loop = True
            continue
        if in_atom_loop and headers and stripped and not stripped.startswith("_"):
            if stripped.startswith("#"):
                break
            values = shlex.split(stripped, posix=True)
            if len(values) != len(headers):
                raise ModelConstructionError(
                    "multiline or malformed CCD atom row is unsupported; "
                    f"expected {len(headers)} fields and found {len(values)}"
                )
            rows.append(dict(zip(headers, values, strict=True)))
    if not rows:
        raise ModelConstructionError(f"no _chem_comp_atom loop found in {cif_path}")
    ordinals = [int(row["_chem_comp_atom.pdbx_ordinal"]) for row in rows]
    if ordinals != list(range(1, len(rows) + 1)):
        raise ModelConstructionError("CCD atom ordinals are not contiguous and ordered")
    return rows


def _mmcif_loop_rows(cif_path: Path, category: str) -> list[dict[str, str]]:
    """Read a simple one-record-per-line mmCIF loop from an RCSB coordinate file."""

    prefix = f"_{category}."
    lines = cif_path.read_text().splitlines()
    headers: list[str] = []
    rows: list[dict[str, str]] = []
    active = False
    for line in lines:
        stripped = line.strip()
        if stripped == "loop_":
            headers = []
            active = False
            continue
        if stripped.startswith(prefix):
            headers.append(stripped)
            active = True
            continue
        if active and headers and stripped and not stripped.startswith("_"):
            if stripped.startswith("#"):
                break
            values = shlex.split(stripped, posix=True)
            if len(values) != len(headers):
                raise ModelConstructionError(
                    f"multiline or malformed {category} row is unsupported; "
                    f"expected {len(headers)} fields and found {len(values)}"
                )
            rows.append(dict(zip(headers, values, strict=True)))
    if not rows:
        raise ModelConstructionError(f"no _{category} loop found in {cif_path}")
    return rows


def _reference_paths(
    definition: dict[str, Any], reference_dir: Path
) -> tuple[Path, Path, list[dict[str, Any]]]:
    records = {asset["id"]: asset for asset in definition["source_assets"]}
    recipe = definition["model_compounds"]["charge_model"]
    sdf_record = records[recipe["source_asset"]]
    cif_record = records[recipe["source_atom_table"]]
    checked: list[dict[str, Any]] = []
    paths: list[Path] = []
    for record in (sdf_record, cif_record):
        path = reference_dir / record["filename"]
        if not path.is_file():
            raise ModelConstructionError(
                f"missing verified reference {path}; run fetch-references first"
            )
        actual = sha256_file(path)
        if actual != record["sha256"]:
            raise ModelConstructionError(
                f"reference digest mismatch for {path}: expected {record['sha256']}, "
                f"found {actual}"
            )
        paths.append(path)
        checked.append(
            {"id": record["id"], "path": str(path.resolve()), "sha256": actual}
        )
    return paths[0], paths[1], checked


def _xyz_text(atom_records: list[dict[str, Any]], comment: str) -> str:
    lines = [str(len(atom_records)), comment]
    lines.extend(
        f"{item['element']:<2} {item['x']: .10f} {item['y']: .10f} {item['z']: .10f}"
        for item in atom_records
    )
    return "\n".join(lines) + "\n"


def _model_graph(model: Any, atom_map: list[str]) -> dict[str, Any]:
    """Serialize an RDKit model graph without making RDKit a runtime dependency.

    Coordinates alone are not sufficient parameter-fitting provenance.  This compact
    JSON record preserves the exact stable-key atom ordering and bond orders perceived
    during reviewed model construction, while remaining readable by fitting engines
    that do not use RDKit.
    """

    if model.GetNumAtoms() != len(atom_map) or len(atom_map) != len(set(atom_map)):
        raise ModelConstructionError(
            "model graph requires unique stable keys for every atom"
        )
    atoms = []
    for index, (atom, key) in enumerate(zip(model.GetAtoms(), atom_map, strict=True)):
        atoms.append(
            {
                "index": index,
                "key": key,
                "element": atom.GetSymbol(),
                "formal_charge": int(atom.GetFormalCharge()),
                "aromatic": bool(atom.GetIsAromatic()),
            }
        )
    bonds = []
    for bond in model.GetBonds():
        first = int(bond.GetBeginAtomIdx())
        second = int(bond.GetEndAtomIdx())
        if first > second:
            first, second = second, first
        bonds.append(
            {
                "atoms": [atom_map[first], atom_map[second]],
                "indices": [first, second],
                "order": float(bond.GetBondTypeAsDouble()),
                "aromatic": bool(bond.GetIsAromatic()),
            }
        )
    bonds.sort(key=lambda item: tuple(item["indices"]))
    return {
        "schema": "nadoc.photoproduct-model-graph.v1",
        "atom_count": len(atoms),
        "bond_count": len(bonds),
        "formal_charge": sum(item["formal_charge"] for item in atoms),
        "atoms": atoms,
        "bonds": bonds,
    }


def build_charge_model(
    *,
    product: str,
    stereochemistry: str,
    reference_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Construct the reviewed N1-methylated two-base charge model.

    This is deliberately implemented only for recipes with two explicit endpoint caps.
    Unknown products fail rather than inferring a truncation scheme.
    """

    try:
        from rdkit import Chem
    except ImportError as exc:
        raise ModelConstructionError(
            "RDKit is required; run this command with `mamba run -n nadoc-qm python`"
        ) from exc

    definition = load_chemical_definition(product, stereochemistry)
    definition_asset = chemical_definition_asset(product, stereochemistry)
    recipe = (definition.get("model_compounds") or {}).get("charge_model")
    if not isinstance(recipe, dict):
        raise ModelConstructionError("no reviewed charge_model recipe is available")
    if recipe.get("construction") != (
        "retain both complete TTD bases and replace each deoxyribose at N1 by a methyl group"
    ):
        raise ModelConstructionError("unsupported charge_model construction recipe")
    caps = recipe.get("endpoint_caps")
    if not isinstance(caps, list) or len(caps) != 2:
        raise ModelConstructionError(
            "charge_model requires exactly two reviewed endpoint caps"
        )

    sdf_path, cif_path, checked_sources = _reference_paths(definition, reference_dir)
    rows = _ccd_atom_rows(cif_path)
    molecule = Chem.MolFromMolFile(str(sdf_path), removeHs=False, sanitize=True)
    if molecule is None:
        raise ModelConstructionError(f"RDKit could not parse {sdf_path}")
    if molecule.GetNumAtoms() != len(rows):
        raise ModelConstructionError(
            "SDF atom count does not match the ordered CCD atom table"
        )

    endpoint_heavy: dict[int, set[str]] = {}
    canonical_keys: dict[str, str] = {}
    for endpoint in definition["ordered_endpoints"]:
        number = int(endpoint["index"])
        aliases = endpoint["ccd_atom_aliases"]
        heavy = {name for name in aliases.values() if not name.startswith("H")}
        endpoint_heavy[number] = heavy
        canonical_keys.update(
            {name: f"{number}:{key}" for key, name in aliases.items()}
        )
    cap_names = {int(cap["endpoint"]): cap["ccd_atom"] for cap in caps}
    hydrogen_aliases = {
        int(item["endpoint"]): item["aliases"]
        for item in recipe.get("endpoint_hydrogen_aliases", [])
    }

    keep_names = set().union(*endpoint_heavy.values(), cap_names.values())
    # Retain every CCD hydrogen directly bonded to a retained base/cap atom.
    for atom in molecule.GetAtoms():
        name = rows[atom.GetIdx()]["_chem_comp_atom.atom_id"]
        if atom.GetSymbol() != "H":
            continue
        neighbor_names = {
            rows[neighbor.GetIdx()]["_chem_comp_atom.atom_id"]
            for neighbor in atom.GetNeighbors()
        }
        if neighbor_names & keep_names:
            keep_names.add(name)

    editable = Chem.RWMol(molecule)
    for index in reversed(range(molecule.GetNumAtoms())):
        if rows[index]["_chem_comp_atom.atom_id"] not in keep_names:
            editable.RemoveAtom(index)
    model = editable.GetMol()
    Chem.SanitizeMol(model)

    # Name retained atoms before adding the missing two H atoms to each methyl cap.
    retained_names = [
        row["_chem_comp_atom.atom_id"]
        for row in rows
        if row["_chem_comp_atom.atom_id"] in keep_names
    ]
    if len(retained_names) != model.GetNumAtoms():
        raise ModelConstructionError("retained atom ordering became ambiguous")
    for atom, name in zip(model.GetAtoms(), retained_names, strict=True):
        atom.SetProp("ccd_atom_id", name)
    model = Chem.AddHs(model, addCoords=True)

    cap_by_name = {cap["ccd_atom"]: cap for cap in caps}
    new_h_counts = {int(cap["endpoint"]): 0 for cap in caps}
    cap_h_counts = {int(cap["endpoint"]): 0 for cap in caps}
    atom_map: list[str] = []
    coordinates: dict[str, list[float]] = {}
    conformer = model.GetConformer()
    records: list[dict[str, Any]] = []
    for atom in model.GetAtoms():
        if atom.HasProp("ccd_atom_id"):
            ccd_name = atom.GetProp("ccd_atom_id")
            key = canonical_keys.get(ccd_name)
            if key is None and ccd_name in cap_by_name:
                key = cap_by_name[ccd_name]["model_atom"]
            if key is None:
                # Hydrogens from CCD are mapped to their endpoint and original stable name.
                neighbor_names = {
                    neighbor.GetProp("ccd_atom_id")
                    for neighbor in atom.GetNeighbors()
                    if neighbor.HasProp("ccd_atom_id")
                }
                cap = next(
                    (
                        cap_by_name[name]
                        for name in neighbor_names
                        if name in cap_by_name
                    ),
                    None,
                )
                if cap is not None:
                    endpoint = int(cap["endpoint"])
                    cap_h_counts[endpoint] += 1
                    key = f"{endpoint}:HCM{cap_h_counts[endpoint]}"
                else:
                    endpoint = next(
                        number
                        for number, heavy in endpoint_heavy.items()
                        if neighbor_names & heavy
                    )
                    stable_name = hydrogen_aliases.get(endpoint, {}).get(
                        ccd_name, ccd_name
                    )
                    key = f"{endpoint}:{stable_name}"
        else:
            neighbors = list(atom.GetNeighbors())
            if atom.GetSymbol() != "H" or len(neighbors) != 1:
                raise ModelConstructionError("RDKit added an unexpected non-cap atom")
            neighbor = neighbors[0]
            if not neighbor.HasProp("ccd_atom_id"):
                raise ModelConstructionError("new hydrogen has no named cap neighbor")
            cap = cap_by_name.get(neighbor.GetProp("ccd_atom_id"))
            if cap is None:
                raise ModelConstructionError(
                    "RDKit added a hydrogen outside a methyl cap"
                )
            endpoint = int(cap["endpoint"])
            new_h_counts[endpoint] += 1
            cap_h_counts[endpoint] += 1
            key = f"{endpoint}:HCM{cap_h_counts[endpoint]}"
        position = conformer.GetAtomPosition(atom.GetIdx())
        item = {
            "key": key,
            "element": atom.GetSymbol(),
            "x": float(position.x),
            "y": float(position.y),
            "z": float(position.z),
        }
        records.append(item)
        atom_map.append(key)
        coordinates[key] = [item["x"], item["y"], item["z"]]
    if set(new_h_counts.values()) != {2}:
        raise ModelConstructionError(
            f"expected two generated H atoms per N-methyl cap, found {new_h_counts}"
        )
    if set(cap_h_counts.values()) != {3}:
        raise ModelConstructionError(
            f"expected three total H atoms per N-methyl cap, found {cap_h_counts}"
        )

    chirality = audit_product_chirality(definition, coordinates)
    if not chirality["passed"]:
        raise ModelConstructionError(
            "source-derived charge model failed chirality audit"
        )
    formal_charge = sum(atom.GetFormalCharge() for atom in model.GetAtoms())
    if formal_charge != recipe["charge"]:
        raise ModelConstructionError(
            f"model formal charge {formal_charge} != reviewed charge {recipe['charge']}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    xyz_path = output_dir / "model.xyz"
    map_path = output_dir / "atom_map.json"
    graph_path = output_dir / "model_graph.json"
    xyz = _xyz_text(records, f"{definition['id']} {recipe['id']} source-derived")
    xyz_path.write_text(xyz)
    map_path.write_text(json.dumps(atom_map, indent=2) + "\n")
    graph = _model_graph(model, atom_map)
    if graph["formal_charge"] != formal_charge:
        raise ModelConstructionError("serialized model graph changed the formal charge")
    graph_path.write_text(json.dumps(graph, indent=2) + "\n")
    manifest = {
        "schema": "nadoc.photoproduct-model-compound.v1",
        "status": "constructed_not_optimized",
        "gate_effect": "none",
        "product_id": definition["id"],
        "model_id": recipe["id"],
        "purpose": recipe["purpose"],
        "construction": recipe["construction"],
        "chemical_definition": definition_asset,
        "charge": formal_charge,
        "multiplicity": recipe["multiplicity"],
        "atom_count": model.GetNumAtoms(),
        "atom_map": atom_map,
        "methyl_cap_generated_hydrogens": new_h_counts,
        "chirality_audit": chirality,
        "source_assets": checked_sources,
        "outputs": {
            "xyz": {
                "path": str(xyz_path.resolve()),
                "sha256": hashlib.sha256(xyz.encode()).hexdigest(),
            },
            "atom_map": {
                "path": str(map_path.resolve()),
                "sha256": sha256_file(map_path),
            },
            "graph": {
                "path": str(graph_path.resolve()),
                "sha256": sha256_file(graph_path),
            },
        },
        "limitations": recipe["limitations"],
    }
    manifest_path = output_dir / "model_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def build_dna_boundary_model_candidate(
    *,
    reference_dir: Path,
    output_dir: Path,
    chain_id: str = "B",
    endpoint_resids: tuple[str, str] = ("15", "16"),
    pdb_model: str = "1",
) -> dict[str, Any]:
    """Build a review-only cis-syn d(TpT) phosphodiester boundary model.

    The cap/protonation choices are explicit and intentionally remain review blockers.
    No generic inference path is provided for another product or source structure.
    """

    try:
        from rdkit import Chem
    except ImportError as exc:
        raise ModelConstructionError(
            "RDKit is required; run this command with `mamba run -n nadoc-qm python`"
        ) from exc
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite boundary candidate: {output_dir}")
    definition = load_chemical_definition("TT-CPD", "cis-syn")
    source_record = next(
        item for item in definition["source_assets"] if item["id"] == "RCSB-1N4E-CIF"
    )
    source_path = reference_dir / source_record["filename"]
    if not source_path.is_file() or sha256_file(source_path) != source_record["sha256"]:
        raise ModelConstructionError("verified RCSB 1N4E mmCIF is missing or changed")
    if len(endpoint_resids) != 2 or endpoint_resids[0] == endpoint_resids[1]:
        raise ModelConstructionError(
            "two distinct ordered source residues are required"
        )
    atom_rows = _mmcif_loop_rows(source_path, "atom_site")
    selected = [
        row
        for row in atom_rows
        if row["_atom_site.auth_asym_id"] == chain_id
        and row["_atom_site.auth_seq_id"] in endpoint_resids
        and row["_atom_site.pdbx_PDB_model_num"] == pdb_model
    ]
    by_source: dict[tuple[str, str], dict[str, str]] = {}
    for row in selected:
        key = (row["_atom_site.auth_seq_id"], row["_atom_site.auth_atom_id"])
        if key in by_source:
            raise ModelConstructionError(f"duplicate 1N4E source atom {key}")
        by_source[key] = row
    residue_heavy = (
        "O5'",
        "C5'",
        "C4'",
        "O4'",
        "C3'",
        "O3'",
        "C2'",
        "C1'",
        "N1",
        "C2",
        "O2",
        "N3",
        "C4",
        "O4",
        "C5",
        "C7",
        "C6",
    )
    stable_heavy = [
        *(f"1:{name}" for name in residue_heavy),
        "2:P",
        "2:OP1",
        "2:OP2",
        *(f"2:{name}" for name in residue_heavy),
    ]
    source_for_stable = {
        **{f"1:{name}": (endpoint_resids[0], name) for name in residue_heavy},
        "2:P": (endpoint_resids[1], "P"),
        "2:OP1": (endpoint_resids[1], "OP1"),
        "2:OP2": (endpoint_resids[1], "OP2"),
        **{f"2:{name}": (endpoint_resids[1], name) for name in residue_heavy},
    }
    missing = [
        key for key, source in source_for_stable.items() if source not in by_source
    ]
    if missing:
        raise ModelConstructionError(
            "1N4E boundary source atoms are missing: " + ", ".join(missing)
        )

    editable = Chem.RWMol()
    index_by_key: dict[str, int] = {}
    elements: dict[str, str] = {}
    for key in stable_heavy:
        row = by_source[source_for_stable[key]]
        element = row["_atom_site.type_symbol"]
        atom = Chem.Atom(element)
        if key == "2:P":
            atom.SetFormalCharge(1)
        elif key in {"2:OP1", "2:OP2"}:
            atom.SetFormalCharge(-1)
        index = editable.AddAtom(atom)
        index_by_key[key] = index
        elements[key] = element

    def add(first: str, second: str, order: Any = Chem.BondType.SINGLE) -> None:
        editable.AddBond(index_by_key[first], index_by_key[second], order)

    sugar_bonds = (
        ("O5'", "C5'"),
        ("C5'", "C4'"),
        ("C4'", "O4'"),
        ("O4'", "C1'"),
        ("C1'", "C2'"),
        ("C2'", "C3'"),
        ("C3'", "C4'"),
        ("C3'", "O3'"),
        ("C1'", "N1"),
    )
    base_bonds = (
        ("N1", "C2", Chem.BondType.SINGLE),
        ("C2", "O2", Chem.BondType.DOUBLE),
        ("C2", "N3", Chem.BondType.SINGLE),
        ("N3", "C4", Chem.BondType.SINGLE),
        ("C4", "O4", Chem.BondType.DOUBLE),
        ("C4", "C5", Chem.BondType.SINGLE),
        ("C5", "C6", Chem.BondType.SINGLE),
        ("C6", "N1", Chem.BondType.SINGLE),
        ("C5", "C7", Chem.BondType.SINGLE),
    )
    for endpoint in (1, 2):
        for first, second in sugar_bonds:
            add(f"{endpoint}:{first}", f"{endpoint}:{second}")
        for first, second, order in base_bonds:
            add(f"{endpoint}:{first}", f"{endpoint}:{second}", order)
    add("1:O3'", "2:P")
    add("2:P", "2:O5'")
    add("2:P", "2:OP1")
    add("2:P", "2:OP2")
    add("1:C5", "2:C5")
    add("1:C6", "2:C6")
    molecule = editable.GetMol()
    conformer = Chem.Conformer(len(stable_heavy))
    for key, index in index_by_key.items():
        row = by_source[source_for_stable[key]]
        conformer.SetAtomPosition(
            index,
            (
                float(row["_atom_site.Cartn_x"]),
                float(row["_atom_site.Cartn_y"]),
                float(row["_atom_site.Cartn_z"]),
            ),
        )
        molecule.GetAtomWithIdx(index).SetProp("stable_atom_key", key)
    molecule.AddConformer(conformer)
    Chem.SanitizeMol(molecule)
    Chem.AssignAtomChiralTagsFromStructure(molecule, confId=0, replaceExistingTags=True)
    # Ordinary DNA phosphodiester is not a phosphorothioate stereocenter.  Use a
    # charge-separated P(+)/2 O(-) Lewis form so the resonance-equivalent
    # non-bridging oxygens remain constitutionally equivalent, and defensively
    # remove any coordinate-perceived phosphorus R/S label.
    phosphate = molecule.GetAtomWithIdx(index_by_key["2:P"])
    phosphate.SetChiralTag(Chem.ChiralType.CHI_UNSPECIFIED)
    if phosphate.HasProp("_CIPCode"):
        phosphate.ClearProp("_CIPCode")
    molecule = Chem.AddHs(molecule, addCoords=True)

    hydrogen_names = {
        "C1'": ["H1'"],
        "C2'": ["H2'", "H2''"],
        "C3'": ["H3'"],
        "C4'": ["H4'"],
        "C5'": ["H5'", "H5''"],
        "N3": ["H3"],
        "C7": ["H51", "H52", "H53"],
        "C6": ["H6"],
    }
    expected_terminal_h = {"1:O5'": ["HO5'"], "2:O3'": ["HO3'"]}
    generated_by_parent: dict[str, list[int]] = {}
    atom_map = list(stable_heavy)
    for atom in list(molecule.GetAtoms())[len(stable_heavy) :]:
        neighbors = list(atom.GetNeighbors())
        if atom.GetSymbol() != "H" or len(neighbors) != 1:
            raise ModelConstructionError("boundary model gained a non-hydrogen atom")
        parent = neighbors[0]
        if not parent.HasProp("stable_atom_key"):
            raise ModelConstructionError("generated H lacks a stable heavy-atom parent")
        generated_by_parent.setdefault(parent.GetProp("stable_atom_key"), []).append(
            atom.GetIdx()
        )
    hydrogen_key_by_index: dict[int, str] = {}
    for parent_key, indices in generated_by_parent.items():
        endpoint, local = parent_key.split(":", 1)
        names = expected_terminal_h.get(parent_key, hydrogen_names.get(local, []))
        if len(indices) != len(names):
            raise ModelConstructionError(
                f"unexpected hydrogen count on {parent_key}: {len(indices)} != {len(names)}"
            )
        for index, name in zip(sorted(indices), names, strict=True):
            key = f"{endpoint}:{name}"
            hydrogen_key_by_index[index] = key
            molecule.GetAtomWithIdx(index).SetProp("stable_atom_key", key)
    atom_map.extend(
        hydrogen_key_by_index[index] for index in sorted(hydrogen_key_by_index)
    )
    if len(atom_map) != molecule.GetNumAtoms() or len(atom_map) != len(set(atom_map)):
        raise ModelConstructionError(
            "boundary model stable atom map is incomplete or duplicate"
        )

    conformer = molecule.GetConformer()
    coordinates = {}
    for atom in molecule.GetAtoms():
        point = conformer.GetAtomPosition(atom.GetIdx())
        coordinates[atom.GetProp("stable_atom_key")] = [
            float(point.x),
            float(point.y),
            float(point.z),
        ]
    chirality = audit_product_chirality(definition, coordinates)
    if not chirality["passed"]:
        raise ModelConstructionError(
            "1N4E boundary candidate failed product chirality audit"
        )
    formal_charge = sum(atom.GetFormalCharge() for atom in molecule.GetAtoms())
    if formal_charge != -1:
        raise ModelConstructionError(f"boundary candidate charge {formal_charge} != -1")
    crosslink_distances = {
        name: float(
            (
                conformer.GetAtomPosition(index_by_key[first])
                - conformer.GetAtomPosition(index_by_key[second])
            ).Length()
        )
        for name, first, second in (
            ("c5_c5_angstrom", "1:C5", "2:C5"),
            ("c6_c6_angstrom", "1:C6", "2:C6"),
        )
    }
    if any(not 1.3 <= value <= 1.7 for value in crosslink_distances.values()):
        raise ModelConstructionError("1N4E source crosslink geometry is implausible")

    output_dir.mkdir(parents=True)
    xyz_path = output_dir / "candidate.xyz"
    map_path = output_dir / "atom_map.json"
    sdf_path = output_dir / "candidate.sdf"
    xyz_records = []
    for atom in molecule.GetAtoms():
        point = conformer.GetAtomPosition(atom.GetIdx())
        xyz_records.append(
            {
                "element": atom.GetSymbol(),
                "x": float(point.x),
                "y": float(point.y),
                "z": float(point.z),
            }
        )
    xyz_path.write_text(
        _xyz_text(xyz_records, "1N4E cis-syn d(TpT) boundary candidate")
    )
    map_path.write_text(json.dumps(atom_map, indent=2) + "\n")
    writer = Chem.SDWriter(str(sdf_path))
    writer.write(molecule)
    writer.close()
    manifest = {
        "schema": "nadoc.photoproduct-dna-boundary-model-candidate.v1",
        "status": "candidate_pending_cap_review",
        "gate_effect": "none",
        "product_id": definition["id"],
        "model_id": "cis-syn-dtpdT-dinucleoside-monophosphate",
        "formal_charge": formal_charge,
        "multiplicity": 1,
        "atom_count": molecule.GetNumAtoms(),
        "atom_map": atom_map,
        "source_selection": {
            "structure": "RCSB 1N4E",
            "chain": chain_id,
            "ordered_auth_resids": list(endpoint_resids),
            "pdb_model": pdb_model,
            "source_path": str(source_path.resolve()),
            "source_sha256": sha256_file(source_path),
        },
        "chemical_definition_sha256": chemical_definition_asset("TT-CPD", "cis-syn")[
            "sha256"
        ],
        "caps_and_protonation": {
            "five_prime": "endpoint 1 O5'-H",
            "three_prime": "endpoint 2 O3'-H",
            "inter_residue_phosphodiester": "one deprotonated nonbridging oxygen; net -1",
            "tautomer": "neutral canonical thymine lactam at both endpoints",
        },
        "serialization_note": (
            "The SDF uses a charge-separated P(+)/OP1(-)/OP2(-) Lewis form to preserve "
            "equivalent nonbridging oxygens and net charge. Phosphorus chirality is "
            "explicitly unset; the SDF drawing is not parameter authority."
        ),
        "chirality_audit": chirality,
        "crosslink_distances": crosslink_distances,
        "outputs": {
            "xyz": {"path": str(xyz_path.resolve()), "sha256": sha256_file(xyz_path)},
            "atom_map": {
                "path": str(map_path.resolve()),
                "sha256": sha256_file(map_path),
            },
            "sdf": {"path": str(sdf_path.resolve()), "sha256": sha256_file(sdf_path)},
        },
        "release_blockers": [
            "independent review of atom map, phosphate resonance choice, and terminal caps",
            "QM optimization and frequency or constrained-mode confirmation",
            "glycosidic, sugar-pucker, phosphate, and lesion-ring torsion target generation",
            "proof that unmodified CHARMM36 boundary terms remain transferable",
        ],
    }
    manifest_path = output_dir / "candidate_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def _proper_rotation_fit(
    source: np.ndarray, target: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float]:
    """Fit source to target with a proper rotation; reflection is never allowed."""

    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 3:
        raise ValueError("proper-rotation fit requires matching Nx3 arrays")
    source_center = np.mean(source, axis=0)
    target_center = np.mean(target, axis=0)
    left, _singular, right_t = np.linalg.svd(
        (source - source_center).T @ (target - target_center)
    )
    correction = np.eye(3)
    correction[-1, -1] = np.sign(np.linalg.det(right_t.T @ left.T))
    rotation = right_t.T @ correction @ left.T
    determinant = float(np.linalg.det(rotation))
    if determinant < 1.0 - 1.0e-8:
        raise ValueError("boundary graft fit did not produce a proper rotation")
    translation = target_center - rotation @ source_center
    fitted = (rotation @ source.T).T + translation
    rmsd = float(np.sqrt(np.mean(np.sum((fitted - target) ** 2, axis=1))))
    return rotation, translation, rmsd


def _resolved_manifest_output(
    manifest_path: Path, manifest: dict[str, Any], name: str
) -> Path:
    record = (manifest.get("outputs") or {}).get(name) or {}
    path = Path(str(record.get("path") or ""))
    fallback = manifest_path.parent / path.name
    if not path.is_file() or sha256_file(path) != record.get("sha256"):
        path = fallback
    if not path.is_file() or sha256_file(path) != record.get("sha256"):
        raise ValueError(f"manifest {name} output is missing or hash-mismatched")
    return path.resolve()


def _xyz_coordinates(path: Path, atom_map: list[str]) -> tuple[list[str], np.ndarray]:
    lines = path.read_text().splitlines()
    if len(lines) < 2 or int(lines[0]) != len(atom_map) or len(lines[2:]) != len(
        atom_map
    ):
        raise ValueError("XYZ and stable atom map differ")
    fields = [line.split() for line in lines[2:]]
    elements = [row[0] for row in fields]
    coordinates = np.asarray(
        [[float(value) for value in row[1:4]] for row in fields], dtype=float
    )
    if not np.all(np.isfinite(coordinates)):
        raise ValueError("XYZ contains non-finite coordinates")
    return elements, coordinates


def _minimum_nonbonded_covalent_ratio(
    molecule: Any, coordinates: np.ndarray, elements: list[str]
) -> float:
    """Return the tightest heavy-atom nonbonded contact outside graph distance two."""

    try:
        from rdkit import Chem
    except ImportError as exc:  # pragma: no cover - caller already imports RDKit
        raise ModelConstructionError("RDKit is required") from exc
    adjacency = {
        atom.GetIdx(): {neighbor.GetIdx() for neighbor in atom.GetNeighbors()}
        for atom in molecule.GetAtoms()
    }
    excluded: set[frozenset[int]] = set()
    for origin in adjacency:
        first = adjacency[origin]
        second = {
            neighbor
            for attached in first
            for neighbor in adjacency[attached]
            if neighbor != origin
        }
        excluded.update(frozenset((origin, other)) for other in first | second)
    table = Chem.GetPeriodicTable()
    minimum = float("inf")
    for first in range(len(elements)):
        if elements[first].upper() == "H":
            continue
        for second in range(first + 1, len(elements)):
            if (
                elements[second].upper() == "H"
                or frozenset((first, second)) in excluded
            ):
                continue
            radius = table.GetRcovalent(elements[first]) + table.GetRcovalent(
                elements[second]
            )
            minimum = min(
                minimum,
                float(np.linalg.norm(coordinates[first] - coordinates[second]) / radius),
            )
    if not math.isfinite(minimum):
        raise ValueError("boundary graft has no auditable nonbonded heavy-atom contacts")
    return minimum


def _covalent_bond_radius_ratio_range(
    molecule: Any, coordinates: np.ndarray, elements: list[str]
) -> tuple[float, float]:
    """Return broad geometry-only covalent-radius ratios for every graph bond."""

    try:
        from rdkit import Chem
    except ImportError as exc:  # pragma: no cover - caller already imports RDKit
        raise ModelConstructionError("RDKit is required") from exc
    table = Chem.GetPeriodicTable()
    ratios = []
    for bond in molecule.GetBonds():
        first, second = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
        radii = table.GetRcovalent(elements[first]) + table.GetRcovalent(
            elements[second]
        )
        ratios.append(
            float(
                np.linalg.norm(coordinates[first] - coordinates[second]) / radii
            )
        )
    if not ratios or not all(math.isfinite(value) for value in ratios):
        raise ValueError("boundary model has no finite auditable covalent bonds")
    return min(ratios), max(ratios)


def build_grafted_dna_boundary_model_candidate(
    *,
    reference_manifest_path: Path,
    mode_source_path: Path,
    chemical_definition_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Graft an audited product minimum onto a d(TpT) sugar/phosphate reference.

    The product base pair moves as one rigid body under a proper rotation.  Sugar and
    phosphate coordinates are copied byte-for-byte in stable-atom order.  This produces
    only a quantitatively screenable QM/NAMD starting candidate, never released assets.
    """

    try:
        from rdkit import Chem
    except ImportError as exc:
        raise ModelConstructionError(
            "RDKit is required; run this command with the nadoc-qm environment"
        ) from exc
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite boundary graft: {output_dir}")
    reference_manifest_path = reference_manifest_path.resolve()
    mode_source_path = mode_source_path.resolve()
    chemical_definition_path = chemical_definition_path.resolve()
    reference = json.loads(reference_manifest_path.read_text())
    mode_source = json.loads(mode_source_path.read_text())
    definition = json.loads(chemical_definition_path.read_text())
    if (
        reference.get("schema")
        != "nadoc.photoproduct-dna-boundary-model-candidate.v1"
        or reference.get("product_id") != "tt-cpd-cis-syn"
        or reference.get("atom_count") != 63
        or reference.get("formal_charge") != -1
        or mode_source.get("schema")
        != "nadoc.photoproduct-conformer-mode-source.v1"
        or mode_source.get("status") != "candidate_mode_source_not_fit_target"
        or definition.get("schema") != "nadoc.photoproduct-chemical-definition.v1"
        or definition.get("product") != "TT-CPD"
        or mode_source.get("product_id") != definition.get("id")
        or not (mode_source.get("chirality_audit") or {}).get("passed")
    ):
        raise ValueError("boundary reference, product minimum, or definition is invalid")

    reference_xyz = _resolved_manifest_output(
        reference_manifest_path, reference, "xyz"
    )
    reference_map_path = _resolved_manifest_output(
        reference_manifest_path, reference, "atom_map"
    )
    reference_sdf = _resolved_manifest_output(
        reference_manifest_path, reference, "sdf"
    )
    reference_map = json.loads(reference_map_path.read_text())
    if reference_map != reference.get("atom_map") or len(reference_map) != len(
        set(reference_map)
    ):
        raise ValueError("boundary reference stable atom map is invalid")
    elements, reference_coordinates = _xyz_coordinates(reference_xyz, reference_map)

    source_record = mode_source.get("source_geometry") or {}
    source_xyz = Path(str(source_record.get("path") or ""))
    if not source_xyz.is_file() or sha256_file(source_xyz) != source_record.get(
        "sha256"
    ):
        raise ValueError("product minimum geometry is missing or hash-mismatched")
    source_map = list(mode_source.get("atom_map") or [])
    source_elements, source_coordinates = _xyz_coordinates(source_xyz, source_map)
    required_base_names = (
        "N1",
        "C2",
        "O2",
        "N3",
        "H3",
        "C4",
        "O4",
        "C5",
        "C7",
        "C6",
        "H51",
        "H52",
        "H53",
        "H6",
    )
    required_source = {
        *(f"{endpoint}:{name}" for endpoint in (1, 2) for name in required_base_names),
        "1:CM",
        "2:CM",
    }
    if len(source_map) != len(set(source_map)) or not required_source <= set(source_map):
        raise ValueError("product minimum lacks the required stable base atoms")
    source_by_key = dict(zip(source_map, source_coordinates, strict=True))
    reference_by_key = dict(zip(reference_map, reference_coordinates, strict=True))
    source_anchors = np.asarray(
        [
            source_by_key[f"{endpoint}:{name}"]
            for endpoint in (1, 2)
            for name in ("CM", "N1")
        ]
    )
    target_anchors = np.asarray(
        [
            reference_by_key[f"{endpoint}:{name}"]
            for endpoint in (1, 2)
            for name in ("C1'", "N1")
        ]
    )
    rotation, translation, anchor_rmsd = _proper_rotation_fit(
        source_anchors, target_anchors
    )
    transformed = {
        key: rotation @ coordinate + translation
        for key, coordinate in source_by_key.items()
    }
    grafted_coordinates = np.array(reference_coordinates, copy=True)
    reference_index = {key: index for index, key in enumerate(reference_map)}
    for endpoint in (1, 2):
        for name in required_base_names:
            key = f"{endpoint}:{name}"
            grafted_coordinates[reference_index[key]] = transformed[key]

    supplier = Chem.SDMolSupplier(str(reference_sdf), removeHs=False)
    reference_molecule = supplier[0] if supplier and len(supplier) == 1 else None
    if reference_molecule is None or reference_molecule.GetNumAtoms() != len(reference_map):
        raise ValueError("RDKit could not load the reference boundary SDF")
    editable = Chem.RWMol(reference_molecule)
    ring = {"1:C5", "1:C6", "2:C5", "2:C6"}
    for bond in list(editable.GetBonds()):
        first = reference_map[bond.GetBeginAtomIdx()]
        second = reference_map[bond.GetEndAtomIdx()]
        if (
            first in ring
            and second in ring
            and first.split(":", 1)[0] != second.split(":", 1)[0]
        ):
            editable.RemoveBond(bond.GetBeginAtomIdx(), bond.GetEndAtomIdx())
    for bond in (definition.get("graph_delta") or {}).get("bonds_added") or []:
        first = bond.get("atom_1")
        second = bond.get("atom_2")
        if first not in ring or second not in ring or bond.get("order") != "single":
            raise ValueError("product definition has an unsupported boundary crosslink")
        editable.AddBond(
            reference_index[first], reference_index[second], Chem.BondType.SINGLE
        )
    molecule = editable.GetMol()
    conformer = molecule.GetConformer()
    for index, coordinate in enumerate(grafted_coordinates):
        conformer.SetAtomPosition(index, tuple(float(value) for value in coordinate))
    Chem.SanitizeMol(molecule)
    Chem.AssignAtomChiralTagsFromStructure(molecule, confId=0, replaceExistingTags=True)
    phosphorus = molecule.GetAtomWithIdx(reference_index["2:P"])
    phosphorus.SetChiralTag(Chem.ChiralType.CHI_UNSPECIFIED)
    if phosphorus.HasProp("_CIPCode"):
        phosphorus.ClearProp("_CIPCode")

    coordinate_dict = {
        key: grafted_coordinates[index].tolist()
        for index, key in enumerate(reference_map)
    }
    chirality = audit_product_chirality(definition, coordinate_dict)
    if not chirality["passed"]:
        raise ModelConstructionError("grafted boundary failed product chirality")
    glycosidic = {
        f"endpoint_{endpoint}_c1_n1_angstrom": float(
            np.linalg.norm(
                coordinate_dict[f"{endpoint}:C1'"]
                - np.asarray(coordinate_dict[f"{endpoint}:N1"])
            )
        )
        for endpoint in (1, 2)
    }
    crosslinks = {
        f"{bond['atom_1']}--{bond['atom_2']}": float(
            np.linalg.norm(
                np.asarray(coordinate_dict[bond["atom_1"]])
                - np.asarray(coordinate_dict[bond["atom_2"]])
            )
        )
        for bond in definition["graph_delta"]["bonds_added"]
    }
    minimum_contact = _minimum_nonbonded_covalent_ratio(
        molecule, grafted_coordinates, elements
    )
    moved_keys = {
        f"{endpoint}:{name}"
        for endpoint in (1, 2)
        for name in required_base_names
    }
    unchanged_boundary = {
        key: reference_coordinates[index].tolist()
        for index, key in enumerate(reference_map)
        if key not in moved_keys
    }

    output_dir.mkdir(parents=True)
    xyz_path = output_dir / "candidate.xyz"
    map_path = output_dir / "atom_map.json"
    sdf_path = output_dir / "candidate.sdf"
    xyz_path.write_text(
        _xyz_text(
            [
                {
                    "element": element,
                    "x": float(coordinate[0]),
                    "y": float(coordinate[1]),
                    "z": float(coordinate[2]),
                }
                for element, coordinate in zip(
                    elements, grafted_coordinates, strict=True
                )
            ],
            f"{definition['id']} rigid product graft onto d(TpT) boundary",
        )
    )
    map_path.write_text(json.dumps(reference_map, indent=2) + "\n")
    writer = Chem.SDWriter(str(sdf_path))
    writer.write(molecule)
    writer.close()
    manifest = {
        "schema": "nadoc.photoproduct-dna-boundary-model-candidate.v1",
        "status": "candidate_pending_quantitative_screen",
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": definition["id"],
        "model_id": f"{definition['id']}-dtpdt-rigid-graft-v1",
        "formal_charge": -1,
        "multiplicity": 1,
        "atom_count": len(reference_map),
        "atom_map": reference_map,
        "source_selection": {
            "structure": reference["source_selection"].get("structure"),
            "chain": reference["source_selection"].get("chain"),
            "ordered_auth_resids": reference["source_selection"].get(
                "ordered_auth_resids"
            ),
            "reference_manifest": _source(reference_manifest_path),
        },
        "construction": {
            "policy": "proper-rotation-product-graft-v1",
            "reflection_used": False,
            "proper_rotation_determinant": float(np.linalg.det(rotation)),
            "anchor_mapping": [
                [f"{endpoint}:CM", f"{endpoint}:C1'"]
                for endpoint in (1, 2)
            ]
            + [[f"{endpoint}:N1", f"{endpoint}:N1"] for endpoint in (1, 2)],
            "anchor_rmsd_angstrom": anchor_rmsd,
            "product_base_geometry_transform": "one rigid proper rotation and translation",
            "sugar_phosphate_coordinates": "copied unchanged from reference",
            "unchanged_boundary_coordinate_sha256": hashlib.sha256(
                json.dumps(unchanged_boundary, sort_keys=True).encode()
            ).hexdigest(),
        },
        "chemical_definition": _source(chemical_definition_path),
        "product_minimum": {
            "mode_source": _source(mode_source_path),
            "source_geometry": {
                "path": str(source_xyz.resolve()),
                "sha256": source_record["sha256"],
            },
        },
        "caps_and_protonation": reference.get("caps_and_protonation"),
        "serialization_note": reference.get("serialization_note"),
        "chirality_audit": chirality,
        "graft_metrics": {
            "glycosidic_bond_lengths_angstrom": glycosidic,
            "product_crosslink_distances_angstrom": crosslinks,
            "minimum_nonbonded_covalent_radius_ratio": minimum_contact,
        },
        "outputs": {
            "xyz": {"path": str(xyz_path.resolve()), "sha256": sha256_file(xyz_path)},
            "atom_map": {
                "path": str(map_path.resolve()),
                "sha256": sha256_file(map_path),
            },
            "sdf": {"path": str(sdf_path.resolve()), "sha256": sha256_file(sdf_path)},
        },
        "release_blockers": [
            "pass the versioned rigid-graft quantitative input screen",
            "QM optimization and harmonic or constrained-mode validation of the full d(TpT) model",
            "validate glycosidic, sugar-pucker, phosphate, and lesion-ring transfer",
            "pass explicit-solvent intrastrand and interstrand DNA-context replicas",
        ],
    }
    manifest_path = output_dir / "candidate_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def _expected_boundary_bond_orders(
    definition: dict[str, Any],
) -> dict[tuple[str, str], float]:
    """Return the exact capped d(TpT)-product graph in stable-key space."""

    expected: dict[tuple[str, str], float] = {}

    def add(first: str, second: str, order: float = 1.0) -> None:
        key = tuple(sorted((first, second)))
        if first == second or key in expected:
            raise ValueError("boundary product graph has a duplicate or self bond")
        expected[key] = order

    sugar = (
        ("O5'", "C5'"), ("C5'", "C4'"), ("C4'", "O4'"),
        ("O4'", "C1'"), ("C1'", "C2'"), ("C2'", "C3'"),
        ("C3'", "C4'"), ("C3'", "O3'"), ("C1'", "N1"),
    )
    base = (
        ("N1", "C2", 1.0), ("C2", "O2", 2.0), ("C2", "N3", 1.0),
        ("N3", "C4", 1.0), ("C4", "O4", 2.0), ("C4", "C5", 1.0),
        ("C5", "C6", 1.0), ("C6", "N1", 1.0), ("C5", "C7", 1.0),
    )
    for endpoint in (1, 2):
        for first, second in sugar:
            add(f"{endpoint}:{first}", f"{endpoint}:{second}")
        for first, second, order in base:
            add(f"{endpoint}:{first}", f"{endpoint}:{second}", order)
    for first, second in (
        ("1:O3'", "2:P"), ("2:P", "2:O5'"),
        ("2:P", "2:OP1"), ("2:P", "2:OP2"),
    ):
        add(first, second)
    crosslinks = (definition.get("graph_delta") or {}).get("bonds_added") or []
    if len(crosslinks) != 2:
        raise ValueError("boundary definition must contain exactly two product crosslinks")
    for bond in crosslinks:
        if bond.get("order") != "single":
            raise ValueError("boundary product crosslink must be single")
        add(str(bond.get("atom_1")), str(bond.get("atom_2")))
    hydrogen_parents = {
        "1:HO5'": "1:O5'", "2:HO3'": "2:O3'",
        "1:H5'": "1:C5'", "1:H5''": "1:C5'",
        "2:H5'": "2:C5'", "2:H5''": "2:C5'",
        "1:H4'": "1:C4'", "2:H4'": "2:C4'",
        "1:H3'": "1:C3'", "2:H3'": "2:C3'",
        "1:H2'": "1:C2'", "1:H2''": "1:C2'",
        "2:H2'": "2:C2'", "2:H2''": "2:C2'",
        "1:H1'": "1:C1'", "2:H1'": "2:C1'",
        "1:H3": "1:N3", "2:H3": "2:N3",
        "1:H51": "1:C7", "1:H52": "1:C7", "1:H53": "1:C7",
        "2:H51": "2:C7", "2:H52": "2:C7", "2:H53": "2:C7",
        "1:H6": "1:C6", "2:H6": "2:C6",
    }
    for hydrogen, parent in hydrogen_parents.items():
        add(hydrogen, parent)
    return expected


def materialize_quantitatively_screened_grafted_dna_boundary_model(
    *,
    candidate_manifest_path: Path,
    replicate_audit_path: Path,
    output_path: Path,
    policy_path: Path = GRAFTED_BOUNDARY_POLICY_PATH,
) -> dict[str, Any]:
    """Validate a product-minimum graft for QM or gate-neutral engine testing."""

    try:
        from rdkit import Chem
    except ImportError as exc:
        raise ModelConstructionError(
            "RDKit is required; run this command with the nadoc-qm environment"
        ) from exc
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite screened graft: {output_path}")
    candidate_manifest_path = candidate_manifest_path.resolve()
    replicate_audit_path = replicate_audit_path.resolve()
    policy_path = policy_path.resolve()
    candidate = json.loads(candidate_manifest_path.read_text())
    replicate = json.loads(replicate_audit_path.read_text())
    policy = json.loads(policy_path.read_text())
    gate = policy.get("gate") or {}
    construction = candidate.get("construction") or {}
    if (
        candidate.get("schema")
        != "nadoc.photoproduct-dna-boundary-model-candidate.v1"
        or candidate.get("status") != "candidate_pending_quantitative_screen"
        or candidate.get("simulation_ready") is not False
        or candidate.get("gate_effect") != "none"
        or candidate.get("atom_count") != 63
        or candidate.get("formal_charge") != -1
        or not (candidate.get("chirality_audit") or {}).get("passed")
        or construction.get("policy") != "proper-rotation-product-graft-v1"
        or construction.get("reflection_used") is not False
        or abs(float(construction.get("proper_rotation_determinant", 0.0)) - 1.0)
        > 1.0e-8
        or policy.get("schema")
        != "nadoc.photoproduct-grafted-boundary-policy.v1"
        or policy.get("version") != "1.0.0"
        or policy.get("gate_id") != "grafted_dna_boundary_model"
        or policy.get("simulation_ready") is not False
        or policy.get("gate_effect") != "none"
        or gate.get("policy")
        != "proper-rotation-product-graft-and-replicates-v1"
    ):
        raise ValueError("grafted boundary candidate or policy is invalid")

    definition_record = candidate.get("chemical_definition") or {}
    definition_path = Path(str(definition_record.get("path") or ""))
    if (
        not definition_path.is_file()
        or sha256_file(definition_path) != definition_record.get("sha256")
    ):
        raise ValueError("grafted boundary chemical definition is hash-mismatched")
    definition = json.loads(definition_path.read_text())
    if (
        definition.get("schema") != "nadoc.photoproduct-chemical-definition.v1"
        or definition.get("id") != candidate.get("product_id")
    ):
        raise ValueError("grafted boundary chemical identity differs")

    xyz_path = _resolved_manifest_output(candidate_manifest_path, candidate, "xyz")
    map_path = _resolved_manifest_output(candidate_manifest_path, candidate, "atom_map")
    sdf_path = _resolved_manifest_output(candidate_manifest_path, candidate, "sdf")
    atom_map = json.loads(map_path.read_text())
    elements, coordinates = _xyz_coordinates(xyz_path, atom_map)
    if atom_map != candidate.get("atom_map") or len(atom_map) != 63:
        raise ValueError("grafted boundary stable atom identity differs")
    supplier = Chem.SDMolSupplier(str(sdf_path), removeHs=False)
    molecule = supplier[0] if supplier and len(supplier) == 1 else None
    if molecule is None or molecule.GetNumAtoms() != len(atom_map):
        raise ValueError("RDKit could not sanitize the grafted boundary SDF")
    Chem.SanitizeMol(molecule)
    if (
        [atom.GetSymbol() for atom in molecule.GetAtoms()] != elements
        or sum(atom.GetFormalCharge() for atom in molecule.GetAtoms()) != -1
    ):
        raise ValueError("grafted boundary SDF, XYZ, or charge differs")
    actual_bonds = {
        tuple(sorted((atom_map[bond.GetBeginAtomIdx()], atom_map[bond.GetEndAtomIdx()]))):
        float(bond.GetBondTypeAsDouble())
        for bond in molecule.GetBonds()
    }
    expected_bonds = _expected_boundary_bond_orders(definition)
    if actual_bonds.keys() != expected_bonds.keys() or any(
        abs(actual_bonds[key] - order) > 1.0e-8
        for key, order in expected_bonds.items()
    ):
        raise ValueError("grafted boundary SDF does not encode the exact product graph")
    phosphorus = molecule.GetAtomWithIdx(atom_map.index("2:P"))
    if phosphorus.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED:
        raise ValueError("ordinary phosphate acquired a coordinate stereolabel")

    reference_record = (candidate.get("source_selection") or {}).get(
        "reference_manifest"
    ) or {}
    reference_path = Path(str(reference_record.get("path") or ""))
    if (
        not reference_path.is_file()
        or sha256_file(reference_path) != reference_record.get("sha256")
    ):
        raise ValueError("grafted boundary reference manifest is hash-mismatched")
    reference = json.loads(reference_path.read_text())
    reference_xyz = _resolved_manifest_output(reference_path, reference, "xyz")
    reference_map_path = _resolved_manifest_output(reference_path, reference, "atom_map")
    reference_map = json.loads(reference_map_path.read_text())
    _reference_elements, reference_coordinates = _xyz_coordinates(
        reference_xyz, reference_map
    )
    if reference_map != atom_map:
        raise ValueError("grafted and reference boundary atom maps differ")
    moved_names = {
        "N1", "C2", "O2", "N3", "H3", "C4", "O4", "C5", "C7", "C6",
        "H51", "H52", "H53", "H6",
    }
    boundary_indices = [
        index
        for index, key in enumerate(atom_map)
        if key.split(":", 1)[1] not in moved_names
    ]
    if not np.array_equal(
        coordinates[boundary_indices], reference_coordinates[boundary_indices]
    ):
        raise ValueError("sugar or phosphate coordinate changed during product graft")

    minimum_record = candidate.get("product_minimum") or {}
    mode_record = minimum_record.get("mode_source") or {}
    mode_path = Path(str(mode_record.get("path") or ""))
    if not mode_path.is_file() or sha256_file(mode_path) != mode_record.get("sha256"):
        raise ValueError("grafted product mode source is hash-mismatched")
    mode_source = json.loads(mode_path.read_text())
    source_geometry_record = minimum_record.get("source_geometry") or {}
    source_geometry_path = Path(str(source_geometry_record.get("path") or ""))
    if (
        not source_geometry_path.is_file()
        or sha256_file(source_geometry_path) != source_geometry_record.get("sha256")
    ):
        raise ValueError("grafted product source geometry is hash-mismatched")
    source_map = list(mode_source.get("atom_map") or [])
    _source_elements, source_coordinates = _xyz_coordinates(
        source_geometry_path, source_map
    )
    source_by_key = dict(zip(source_map, source_coordinates, strict=True))
    grafted_by_key = dict(zip(atom_map, coordinates, strict=True))
    base_keys = [
        f"{endpoint}:{name}"
        for endpoint in (1, 2)
        for name in sorted(moved_names)
    ]
    source_base = np.asarray([source_by_key[key] for key in base_keys])
    grafted_base = np.asarray([grafted_by_key[key] for key in base_keys])
    source_distances = np.linalg.norm(
        source_base[:, None, :] - source_base[None, :, :], axis=2
    )
    grafted_distances = np.linalg.norm(
        grafted_base[:, None, :] - grafted_base[None, :, :], axis=2
    )
    if not np.allclose(source_distances, grafted_distances, atol=1.0e-8):
        raise ValueError("product base geometry was not transferred as one rigid body")

    metrics = candidate.get("graft_metrics") or {}
    glycosidic = metrics.get("glycosidic_bond_lengths_angstrom") or {}
    crosslinks = metrics.get("product_crosslink_distances_angstrom") or {}
    glyco_rule = gate.get("glycosidic_bond_length_angstrom") or {}
    crosslink_rule = gate.get("product_crosslink_distance_angstrom") or {}
    contact_rule = gate.get("minimum_nonbonded_covalent_radius_ratio") or {}
    checks = {
        "proper_rotation": True,
        "anchor_rmsd": float(construction["anchor_rmsd_angstrom"])
        <= float(gate["anchor_rmsd_angstrom"]["maximum"]),
        "glycosidic_bonds": len(glycosidic) == 2
        and all(
            float(glyco_rule["minimum"]) <= float(value) <= float(glyco_rule["maximum"])
            for value in glycosidic.values()
        ),
        "product_crosslinks": len(crosslinks) == 2
        and all(
            float(crosslink_rule["minimum"])
            <= float(value)
            <= float(crosslink_rule["maximum"])
            for value in crosslinks.values()
        ),
        "nonbonded_contact": float(
            metrics.get("minimum_nonbonded_covalent_radius_ratio", 0.0)
        )
        >= float(contact_rule["minimum"]),
        "chirality": True,
        "exact_graph": True,
        "boundary_coordinates_unchanged": True,
        "product_geometry_rigid": True,
    }
    candidate_hashes = {
        item.get("sha256") for item in replicate.get("candidate_manifests") or []
    }
    comparisons = replicate.get("comparisons") or []
    checks["independent_replicates"] = (
        replicate.get("schema")
        == "nadoc.photoproduct-dna-boundary-replicate-audit.v1"
        and replicate.get("product_id") == candidate.get("product_id")
        and replicate.get("gate_effect") == "none"
        and sha256_file(candidate_manifest_path) in candidate_hashes
        and len(candidate_hashes) >= 2
        and bool(comparisons)
        and all(
            item.get("reflection_used") is False
            and abs(float(item.get("proper_rotation_determinant")) - 1.0) <= 1.0e-8
            and float(item.get("all_heavy_rmsd_angstrom"))
            <= float(gate["replicate_all_heavy_rmsd_angstrom"]["maximum"])
            and float(item.get("maximum_heavy_displacement_angstrom"))
            <= float(
                gate["replicate_maximum_heavy_displacement_angstrom"]["maximum"]
            )
            for item in comparisons
        )
    )
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise ValueError(
            "grafted boundary quantitative screen failed: " + ", ".join(failed)
        )

    screened = deepcopy(candidate)
    screened["status"] = "quantitatively_screened_boundary"
    screened["quantitative_screening"] = {
        "schema": "nadoc.photoproduct-dna-boundary-quantitative-screen.v1",
        "status": "passed_qm_input_screen",
        "policy_gate": "grafted_dna_boundary_model",
        "policy": gate["policy"],
        "checks": checks,
        "policy_source": _source(policy_path),
        "source_candidate_manifest": _source(candidate_manifest_path),
        "source_replicate_audit": _source(replicate_audit_path),
        "authorizes": "boundary_qm_evidence_generation_only",
        "releases_parameters": False,
    }
    screened["release_blockers"] = [
        blocker
        for blocker in screened.get("release_blockers") or []
        if "quantitative input screen" not in blocker
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(screened, indent=2) + "\n")
    return screened


def build_flexibly_relaxed_dna_boundary_seed(
    *,
    rigid_graft_manifest_path: Path,
    output_dir: Path,
    policy_path: Path = FLEXIBLE_BOUNDARY_SEED_POLICY_PATH,
    maximum_iterations: int = 4000,
) -> dict[str, Any]:
    """Repair a rigid-graft boundary around a fixed product core for QM input.

    UFF supplies only a deterministic pre-QM geometry repair. It is neither energy nor
    parameter evidence, and the resulting model remains explicitly nonreleasing.
    """

    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except ImportError as exc:
        raise ModelConstructionError(
            "RDKit is required; run this command with the nadoc-qm environment"
        ) from exc
    if output_dir.exists():
        raise FileExistsError(
            f"refusing to overwrite flexible boundary seed: {output_dir}"
        )
    rigid_graft_manifest_path = rigid_graft_manifest_path.resolve()
    policy_path = policy_path.resolve()
    source = json.loads(rigid_graft_manifest_path.read_text())
    policy = json.loads(policy_path.read_text())
    thresholds = policy.get("thresholds") or {}
    if (
        source.get("schema")
        != "nadoc.photoproduct-dna-boundary-model-candidate.v1"
        or source.get("status") != "candidate_pending_quantitative_screen"
        or source.get("atom_count") != 63
        or source.get("formal_charge") != -1
        or source.get("simulation_ready") is not False
        or source.get("gate_effect") != "none"
        or not (source.get("chirality_audit") or {}).get("passed")
        or (source.get("construction") or {}).get("policy")
        != "proper-rotation-product-graft-v1"
        or policy.get("schema")
        != "nadoc.photoproduct-flexible-boundary-seed-policy.v1"
        or policy.get("version") not in {"1.0.0", "2.0.0"}
        or policy.get("gate_id") != "flexibly_relaxed_dna_boundary_seed"
        or policy.get("simulation_ready") is not False
        or policy.get("gate_effect") != "none"
        or maximum_iterations < 100
    ):
        raise ValueError(
            "rigid graft, flexible-seed policy, or iteration limit is invalid"
        )
    atom_map = list(source.get("atom_map") or [])
    if len(atom_map) != 63 or len(set(atom_map)) != 63:
        raise ValueError("rigid graft stable atom map is not a 63-key bijection")
    xyz_path = _resolved_manifest_output(rigid_graft_manifest_path, source, "xyz")
    sdf_path = _resolved_manifest_output(rigid_graft_manifest_path, source, "sdf")
    map_path = _resolved_manifest_output(rigid_graft_manifest_path, source, "atom_map")
    if json.loads(map_path.read_text()) != atom_map:
        raise ValueError("rigid graft atom-map output differs from its manifest")
    elements, initial_coordinates = _xyz_coordinates(xyz_path, atom_map)
    supplier = Chem.SDMolSupplier(str(sdf_path), removeHs=False)
    molecule = supplier[0] if supplier and len(supplier) == 1 else None
    if molecule is None or molecule.GetNumAtoms() != len(atom_map):
        raise ValueError("RDKit could not sanitize the rigid-graft SDF")
    Chem.SanitizeMol(molecule)
    if [atom.GetSymbol() for atom in molecule.GetAtoms()] != elements:
        raise ValueError("rigid-graft SDF and XYZ elements differ")
    definition_record = source.get("chemical_definition") or {}
    definition_path = Path(str(definition_record.get("path") or ""))
    if (
        not definition_path.is_file()
        or sha256_file(definition_path) != definition_record.get("sha256")
    ):
        raise ValueError("rigid-graft chemical definition is hash-mismatched")
    definition = json.loads(definition_path.read_text())
    if definition.get("id") != source.get("product_id"):
        raise ValueError("rigid-graft product identity differs")
    actual_bonds = {
        tuple(
            sorted(
                (
                    atom_map[bond.GetBeginAtomIdx()],
                    atom_map[bond.GetEndAtomIdx()],
                )
            )
        ): float(bond.GetBondTypeAsDouble())
        for bond in molecule.GetBonds()
    }
    expected_bonds = _expected_boundary_bond_orders(definition)
    if actual_bonds != expected_bonds:
        raise ValueError("rigid graft does not contain the exact product graph")

    conformer = molecule.GetConformer()
    sdf_coordinates = np.asarray(
        [list(conformer.GetAtomPosition(index)) for index in range(len(atom_map))],
        dtype=float,
    )
    relaxation_initial_coordinates = (
        sdf_coordinates
        if policy.get("initial_coordinates") == "sdf_serialized"
        else initial_coordinates
    )
    for index, coordinate in enumerate(relaxation_initial_coordinates):
        conformer.SetAtomPosition(index, tuple(float(value) for value in coordinate))
    base_names = {
        "N1",
        "C2",
        "O2",
        "N3",
        "H3",
        "C4",
        "O4",
        "C5",
        "C7",
        "C6",
        "H51",
        "H52",
        "H53",
        "H6",
    }
    fixed_indices = [
        index
        for index, key in enumerate(atom_map)
        if key.split(":", 1)[1] in base_names
    ]
    if len(fixed_indices) != 28 or not AllChem.UFFHasAllMoleculeParams(molecule):
        raise ModelConstructionError("UFF cannot type every atom of the boundary model")
    force_field = AllChem.UFFGetMoleculeForceField(
        molecule, confId=0, ignoreInterfragInteractions=False
    )
    for index in fixed_indices:
        force_field.AddFixedPoint(index)
    force_field.Initialize()
    initial_energy = float(force_field.CalcEnergy())
    convergence_code = int(
        force_field.Minimize(
            maxIts=maximum_iterations,
            energyTol=1.0e-6,
            forceTol=1.0e-4,
        )
    )
    final_energy = float(force_field.CalcEnergy())
    coordinates = np.asarray(
        [list(conformer.GetAtomPosition(index)) for index in range(len(atom_map))],
        dtype=float,
    )
    fixed_displacement = float(
        np.max(
            np.linalg.norm(
                coordinates[fixed_indices]
                - relaxation_initial_coordinates[fixed_indices],
                axis=1,
            )
        )
    )
    source_core_displacement = float(
        np.max(
            np.linalg.norm(
                relaxation_initial_coordinates[fixed_indices]
                - initial_coordinates[fixed_indices],
                axis=1,
            )
        )
    )
    coordinate_dict = {
        key: coordinates[index].tolist() for index, key in enumerate(atom_map)
    }
    chirality = audit_product_chirality(definition, coordinate_dict)
    glycosidic = {
        f"endpoint_{endpoint}_c1_n1_angstrom": float(
            np.linalg.norm(
                coordinates[atom_map.index(f"{endpoint}:C1'")]
                - coordinates[atom_map.index(f"{endpoint}:N1")]
            )
        )
        for endpoint in (1, 2)
    }
    crosslinks = {
        f"{bond['atom_1']}--{bond['atom_2']}": float(
            np.linalg.norm(
                coordinates[atom_map.index(bond["atom_1"])]
                - coordinates[atom_map.index(bond["atom_2"])]
            )
        )
        for bond in definition["graph_delta"]["bonds_added"]
    }
    bond_minimum, bond_maximum = _covalent_bond_radius_ratio_range(
        molecule, coordinates, elements
    )
    nonbonded_minimum = _minimum_nonbonded_covalent_ratio(
        molecule, coordinates, elements
    )
    glyco_rule = thresholds.get("glycosidic_bond_length_angstrom") or {}
    crosslink_rule = thresholds.get("product_crosslink_distance_angstrom") or {}
    bond_rule = thresholds.get("covalent_bond_radius_ratio") or {}
    checks = {
        "uff_all_atoms_typed": True,
        "uff_converged": convergence_code == 0,
        "energy_finite_and_decreased": math.isfinite(initial_energy)
        and math.isfinite(final_energy)
        and final_energy < initial_energy,
        "fixed_product_core": fixed_displacement
        <= float(thresholds["fixed_product_core_maximum_displacement_angstrom"]),
        "source_product_core_perturbation": source_core_displacement
        <= float(
            thresholds.get("source_product_core_maximum_displacement_angstrom", 0.0)
        ),
        "exact_graph": actual_bonds == expected_bonds,
        "chirality": bool(chirality.get("passed")),
        "glycosidic_bonds": all(
            float(glyco_rule["minimum"])
            <= value
            <= float(glyco_rule["maximum"])
            for value in glycosidic.values()
        ),
        "product_crosslinks": all(
            float(crosslink_rule["minimum"])
            <= value
            <= float(crosslink_rule["maximum"])
            for value in crosslinks.values()
        ),
        "covalent_bonds": float(bond_rule["minimum"])
        <= bond_minimum
        <= bond_maximum
        <= float(bond_rule["maximum"]),
        "nonbonded_contacts": nonbonded_minimum
        >= float(thresholds["minimum_nonbonded_covalent_radius_ratio"]),
    }
    if not all(checks.values()):
        failed = ", ".join(
            sorted(name for name, passed in checks.items() if not passed)
        )
        raise ModelConstructionError(f"flexible boundary seed failed: {failed}")

    output_dir.mkdir(parents=True)
    output_xyz = output_dir / "candidate.xyz"
    output_map = output_dir / "atom_map.json"
    output_sdf = output_dir / "candidate.sdf"
    output_xyz.write_text(
        _xyz_text(
            [
                {
                    "element": element,
                    "x": float(xyz[0]),
                    "y": float(xyz[1]),
                    "z": float(xyz[2]),
                }
                for element, xyz in zip(elements, coordinates, strict=True)
            ],
            f"{definition['id']} fixed-product-core flexible d(TpT) QM seed",
        )
    )
    output_map.write_text(json.dumps(atom_map, indent=2) + "\n")
    writer = Chem.SDWriter(str(output_sdf))
    writer.write(molecule)
    writer.close()
    manifest = deepcopy(source)
    manifest["status"] = "quantitatively_screened_boundary"
    policy_id = str(policy["policy"])
    manifest["model_id"] = f"{definition['id']}-dtpdt-flexible-seed-{policy['version']}"
    manifest["construction"] = {
        "policy": policy_id,
        "reflection_used": False,
        "endpoint_exchange_used": False,
        "source_rigid_graft": _source(rigid_graft_manifest_path),
        "fixed_product_atom_count": len(fixed_indices),
        "initial_coordinate_source": policy.get("initial_coordinates", "exact_xyz"),
        "maximum_iterations": maximum_iterations,
        "convergence_code": convergence_code,
        "initial_uff_energy": initial_energy,
        "final_uff_energy": final_energy,
        "uff_role": "pre-QM geometry repair only; not parameter or energy authority",
    }
    manifest["chirality_audit"] = chirality
    manifest["graft_metrics"] = {
        "glycosidic_bond_lengths_angstrom": glycosidic,
        "product_crosslink_distances_angstrom": crosslinks,
        "fixed_product_core_maximum_displacement_angstrom": fixed_displacement,
        "source_product_core_maximum_displacement_angstrom": source_core_displacement,
        "covalent_bond_radius_ratio_minimum": bond_minimum,
        "covalent_bond_radius_ratio_maximum": bond_maximum,
        "minimum_nonbonded_covalent_radius_ratio": nonbonded_minimum,
    }
    manifest["quantitative_screening"] = {
        "schema": "nadoc.photoproduct-dna-boundary-quantitative-screen.v1",
        "status": "passed_qm_input_screen",
        "policy_gate": "flexibly_relaxed_dna_boundary_seed",
        "policy": policy_id,
        "checks": checks,
        "policy_source": _source(policy_path),
        "source_candidate_manifest": _source(rigid_graft_manifest_path),
        "authorizes": policy["authorizes"],
        "releases_parameters": False,
    }
    manifest["outputs"] = {
        "xyz": {
            "path": str(output_xyz.resolve()),
            "sha256": sha256_file(output_xyz),
        },
        "atom_map": {
            "path": str(output_map.resolve()),
            "sha256": sha256_file(output_map),
        },
        "sdf": {
            "path": str(output_sdf.resolve()),
            "sha256": sha256_file(output_sdf),
        },
    }
    manifest["release_blockers"] = [
        "UFF-relaxed boundary is only a QM starting point",
        "matching optimization and frequency evidence are required",
        "all force-field fit and NAMD release gates remain closed",
    ]
    manifest_path = output_dir / "candidate_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def audit_dna_boundary_model_replicates(
    *, manifest_paths: list[Path], output_path: Path
) -> dict[str, Any]:
    """Compare matching boundary candidates without reflecting either structure."""

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite boundary comparison: {output_path}"
        )
    if len(manifest_paths) < 2:
        raise ValueError("at least two boundary candidate manifests are required")
    candidates = []
    product_id = None
    for manifest_path in manifest_paths:
        manifest = json.loads(manifest_path.read_text())
        if (
            manifest.get("schema")
            != "nadoc.photoproduct-dna-boundary-model-candidate.v1"
            or manifest.get("status")
            not in {
                "candidate_pending_cap_review",
                "candidate_pending_quantitative_screen",
            }
            or not (manifest.get("chirality_audit") or {}).get("passed")
        ):
            raise ValueError(
                f"not a passed-identity boundary candidate: {manifest_path}"
            )
        if product_id is None:
            product_id = manifest.get("product_id")
        elif manifest.get("product_id") != product_id:
            raise ValueError("boundary replicate products differ")
        xyz_record = manifest["outputs"]["xyz"]
        map_record = manifest["outputs"]["atom_map"]
        xyz_path = Path(xyz_record["path"])
        map_path = Path(map_record["path"])
        if (
            not xyz_path.is_file()
            or sha256_file(xyz_path) != xyz_record["sha256"]
            or not map_path.is_file()
            or sha256_file(map_path) != map_record["sha256"]
        ):
            raise ValueError(
                f"boundary candidate outputs are hash-mismatched: {manifest_path}"
            )
        lines = xyz_path.read_text().splitlines()
        atom_map = json.loads(map_path.read_text())
        if int(lines[0]) != len(atom_map) or len(lines[2:]) != len(atom_map):
            raise ValueError("boundary candidate XYZ and atom map differ")
        elements = [line.split()[0] for line in lines[2:]]
        coordinates = np.asarray(
            [[float(value) for value in line.split()[1:4]] for line in lines[2:]]
        )
        if len(atom_map) != len(set(atom_map)) or not np.all(np.isfinite(coordinates)):
            raise ValueError("boundary candidate coordinates or identity are invalid")
        candidates.append(
            {
                "manifest_path": manifest_path,
                "manifest": manifest,
                "atom_map": atom_map,
                "elements": elements,
                "coordinates": coordinates,
            }
        )
    reference = candidates[0]
    comparisons = []
    for candidate in candidates[1:]:
        if (
            candidate["atom_map"] != reference["atom_map"]
            or candidate["elements"] != reference["elements"]
        ):
            raise ValueError(
                "boundary candidates do not share one ordered stable atom map"
            )
        heavy_indices = [
            index
            for index, element in enumerate(reference["elements"])
            if element.upper() != "H"
        ]
        ref_heavy = reference["coordinates"][heavy_indices]
        mobile_heavy = candidate["coordinates"][heavy_indices]
        ref_center = np.mean(ref_heavy, axis=0)
        mobile_center = np.mean(mobile_heavy, axis=0)
        covariance = (mobile_heavy - mobile_center).T @ (ref_heavy - ref_center)
        left, _singular, right_t = np.linalg.svd(covariance)
        correction = np.eye(3)
        correction[-1, -1] = np.sign(np.linalg.det(left @ right_t))
        rotation = left @ correction @ right_t
        determinant = float(np.linalg.det(rotation))
        aligned = (candidate["coordinates"] - mobile_center) @ rotation + ref_center
        displacements = np.linalg.norm(aligned - reference["coordinates"], axis=1)
        base_indices = [
            index
            for index in heavy_indices
            if not any(
                token in reference["atom_map"][index] for token in ("'", ":P", ":OP")
            )
        ]
        boundary_indices = [
            index for index in heavy_indices if index not in base_indices
        ]

        def rmsd(indices: list[int]) -> float:
            return float(np.sqrt(np.mean(displacements[indices] ** 2)))

        comparisons.append(
            {
                "reference_source_selection": reference["manifest"]["source_selection"],
                "mobile_source_selection": candidate["manifest"]["source_selection"],
                "alignment_atom_count": len(heavy_indices),
                "proper_rotation_determinant": determinant,
                "reflection_used": False,
                "all_heavy_rmsd_angstrom": rmsd(heavy_indices),
                "base_heavy_rmsd_angstrom": rmsd(base_indices),
                "sugar_phosphate_heavy_rmsd_angstrom": rmsd(boundary_indices),
                "maximum_heavy_displacement_angstrom": float(
                    np.max(displacements[heavy_indices])
                ),
            }
        )
    report = {
        "schema": "nadoc.photoproduct-dna-boundary-replicate-audit.v1",
        "status": "comparison_complete_review_required",
        "gate_effect": "none",
        "product_id": product_id,
        "candidate_manifests": [
            {"path": str(path.resolve()), "sha256": sha256_file(path)}
            for path in manifest_paths
        ],
        "comparisons": comparisons,
        "release_note": (
            "Experimental-copy variability is validation evidence, not a QM target or "
            "automatic acceptance threshold. Cap/protonation review remains required."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
