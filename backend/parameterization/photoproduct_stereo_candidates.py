"""Build review-only TT-CPD stereoisomer model candidates from verified TTD.

The RCSB TTD component supplies the canonical cis-syn-I graph and absolute
stereochemistry. Taylor (2023) supplies the ordered DNA-level C5 assignments. This
module applies the chemically explicit suprafacial constraint (both new centers on one
precursor double bond invert together), then verifies the resulting C5 CIP labels. The
derived C6 labels and embedded coordinates remain candidates until human review and QM
validation; this command never passes a registry gate.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from copy import deepcopy
from typing import Any

from backend.core.photoproduct_chemistry import (
    load_chemical_definition,
    load_patch_charge_scope,
    signed_tetrahedron_volume,
)
from backend.core.photoproduct_registry import REGISTRY_PATH, photoproduct_registry
from backend.parameterization.photoproduct_models import _ccd_atom_rows, _model_graph

_RING_ATOMS = ("C5", "C6", "C5T", "C6T")
_ENDPOINT_RING_ATOMS = {1: ("C5", "C6"), 2: ("C5T", "C6T")}
_FACE_FLIPS = {
    "cis-syn": (False, False),
    "cis-syn-II": (True, True),
    "trans-syn-I": (True, False),
    "trans-syn-II": (False, True),
    "trans-anti-I": (False, False),
    "cis-anti-I": (True, False),
    "cis-anti-II": (False, True),
    "trans-anti-II": (True, True),
}


def _audit_signed_volume_records(
    *,
    coordinates: dict[str, list[float]],
    records: object,
) -> dict[str, Any]:
    """Recompute all four candidate handedness sentinels from the hashed XYZ."""

    expected_atoms = {"1:C5", "1:C6", "2:C5", "2:C6"}
    if not isinstance(records, list):
        return {"passed": False, "centers": [], "error": "records are not a list"}
    centers: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            return {"passed": False, "centers": centers, "error": "malformed record"}
        atom = record.get("atom")
        references = record.get("reference_atoms")
        expected = record.get("expected_sign")
        if (
            atom not in expected_atoms
            or not isinstance(references, list)
            or len(references) != 3
            or expected not in {"positive", "negative"}
            or any(key not in coordinates for key in [atom, *references])
        ):
            return {
                "passed": False,
                "centers": centers,
                "error": "record identity, references, or expected sign is invalid",
            }
        value = signed_tetrahedron_volume(coordinates, atom, references)
        centers.append(
            {
                "atom": atom,
                "reference_atoms": references,
                "signed_volume": value,
                "expected_sign": expected,
                "passed": value > 0 if expected == "positive" else value < 0,
            }
        )
    observed_atoms = [item["atom"] for item in centers]
    passed = (
        len(centers) == 4
        and len(observed_atoms) == len(set(observed_atoms))
        and set(observed_atoms) == expected_atoms
        and all(item["passed"] for item in centers)
    )
    return {"passed": passed, "centers": centers, "error": None if passed else "failed"}


def tt_cpd_candidate_recipe(stereochemistry: str) -> dict[str, Any]:
    """Return the explicit constitutional/face recipe without requiring RDKit."""

    if stereochemistry not in _FACE_FLIPS:
        raise ValueError(f"unsupported TT-CPD candidate {stereochemistry!r}")
    orientation = "anti" if "anti" in stereochemistry else "syn"
    return {
        "stereochemistry": stereochemistry,
        "orientation": orientation,
        "endpoint_face_flips": list(_FACE_FLIPS[stereochemistry]),
        "crosslinks": (
            [["1:C5", "2:C6"], ["1:C6", "2:C5"]]
            if orientation == "anti"
            else [["1:C5", "2:C5"], ["1:C6", "2:C6"]]
        ),
    }


def _candidate_patch_charge_scope(product_id: str) -> dict[str, Any]:
    """Carry only the reviewed atom boundary into a noncanonical review packet."""

    scope = deepcopy(load_patch_charge_scope("TT-CPD", "cis-syn"))
    source_definition_hash = scope.pop("chemical_definition_sha256")
    source_product_id = scope.pop("product_id")
    scope.update(
        {
            "schema": "nadoc.photoproduct-patch-charge-scope-candidate.v1",
            "status": "boundary_transfer_review_required",
            "gate_effect": "none",
            "product_id": product_id,
            "source_scope": {
                "product_id": source_product_id,
                "chemical_definition_sha256": source_definition_hash,
                "transfer_claim": (
                    "atom-conservation boundary only; no charge or parameter "
                    "transfer is approved"
                ),
            },
        }
    )
    return scope


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atom_index(molecule: Any, name: str) -> int:
    matches = [
        atom.GetIdx()
        for atom in molecule.GetAtoms()
        if atom.HasProp("ccd_atom_id") and atom.GetProp("ccd_atom_id") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"CCD atom {name!r} resolved {len(matches)} times")
    return matches[0]


def _cip_codes(molecule: Any) -> dict[str, str]:
    from rdkit import Chem

    Chem.AssignStereochemistry(molecule, cleanIt=True, force=True)
    result = {}
    for name in _RING_ATOMS:
        atom = molecule.GetAtomWithIdx(_atom_index(molecule, name))
        if not atom.HasProp("_CIPCode"):
            raise ValueError(f"candidate ring center {name} has no CIP assignment")
        result[name] = atom.GetProp("_CIPCode")
    return result


def _invert_tag(atom: Any) -> None:
    from rdkit import Chem

    inverse = {
        Chem.ChiralType.CHI_TETRAHEDRAL_CW: Chem.ChiralType.CHI_TETRAHEDRAL_CCW,
        Chem.ChiralType.CHI_TETRAHEDRAL_CCW: Chem.ChiralType.CHI_TETRAHEDRAL_CW,
    }
    tag = atom.GetChiralTag()
    if tag not in inverse:
        raise ValueError("source ring center lacks an explicit tetrahedral tag")
    atom.SetChiralTag(inverse[tag])


def _candidate_full_molecule(source: Any, stereochemistry: str) -> Any:
    from rdkit import Chem

    recipe = tt_cpd_candidate_recipe(stereochemistry)
    editable = Chem.RWMol(source)
    orientation = recipe["orientation"]
    if orientation == "anti":
        c5 = _atom_index(editable, "C5")
        c6 = _atom_index(editable, "C6")
        c5t = _atom_index(editable, "C5T")
        c6t = _atom_index(editable, "C6T")
        if editable.GetBondBetweenAtoms(c5, c5t) is None or editable.GetBondBetweenAtoms(
            c6, c6t
        ) is None:
            raise ValueError("source TTD does not contain both canonical syn crosslinks")
        editable.RemoveBond(c5, c5t)
        editable.RemoveBond(c6, c6t)
        editable.AddBond(c5, c6t, Chem.BondType.SINGLE)
        editable.AddBond(c6, c5t, Chem.BondType.SINGLE)
    for endpoint, flip in enumerate(recipe["endpoint_face_flips"], start=1):
        if flip:
            for name in _ENDPOINT_RING_ATOMS[endpoint]:
                _invert_tag(editable.GetAtomWithIdx(_atom_index(editable, name)))
    molecule = editable.GetMol()
    Chem.SanitizeMol(molecule)
    return molecule


def _prune_to_n1_methyl_model(molecule: Any, definition: dict[str, Any]) -> Any:
    from rdkit import Chem

    aliases = {
        value
        for endpoint in definition["ordered_endpoints"]
        for value in endpoint["ccd_atom_aliases"].values()
        if not value.startswith("H")
    }
    caps = {
        item["ccd_atom"]
        for item in definition["model_compounds"]["charge_model"]["endpoint_caps"]
    }
    keep = aliases | caps
    for atom in molecule.GetAtoms():
        if atom.GetSymbol() != "H" or not atom.HasProp("ccd_atom_id"):
            continue
        if any(
            neighbor.HasProp("ccd_atom_id")
            and neighbor.GetProp("ccd_atom_id") in keep
            for neighbor in atom.GetNeighbors()
        ):
            keep.add(atom.GetProp("ccd_atom_id"))
    editable = Chem.RWMol(molecule)
    for index in reversed(range(molecule.GetNumAtoms())):
        atom = molecule.GetAtomWithIdx(index)
        name = atom.GetProp("ccd_atom_id") if atom.HasProp("ccd_atom_id") else None
        if name not in keep:
            editable.RemoveAtom(index)
    model = editable.GetMol()
    Chem.SanitizeMol(model)
    model.RemoveAllConformers()
    return Chem.AddHs(model, addCoords=False)


def _stable_atom_map(model: Any, definition: dict[str, Any]) -> list[str]:
    canonical = {
        ccd: f"{endpoint['index']}:{stable}"
        for endpoint in definition["ordered_endpoints"]
        for stable, ccd in endpoint["ccd_atom_aliases"].items()
    }
    recipe = definition["model_compounds"]["charge_model"]
    cap_by_name = {
        item["ccd_atom"]: item for item in recipe["endpoint_caps"]
    }
    endpoint_heavy = {
        int(endpoint["index"]): {
            value
            for value in endpoint["ccd_atom_aliases"].values()
            if not value.startswith("H")
        }
        for endpoint in definition["ordered_endpoints"]
    }
    hydrogen_aliases = {
        int(item["endpoint"]): item["aliases"]
        for item in recipe.get("endpoint_hydrogen_aliases", [])
    }
    cap_h_count = {1: 0, 2: 0}
    keys: list[str] = []
    for atom in model.GetAtoms():
        if atom.HasProp("ccd_atom_id"):
            name = atom.GetProp("ccd_atom_id")
            key = canonical.get(name)
            if key is None and name in cap_by_name:
                key = cap_by_name[name]["model_atom"]
            if key is None:
                neighbor_names = {
                    neighbor.GetProp("ccd_atom_id")
                    for neighbor in atom.GetNeighbors()
                    if neighbor.HasProp("ccd_atom_id")
                }
                cap = next(
                    (cap_by_name[item] for item in neighbor_names if item in cap_by_name),
                    None,
                )
                if cap is not None:
                    endpoint = int(cap["endpoint"])
                    cap_h_count[endpoint] += 1
                    key = f"{endpoint}:HCM{cap_h_count[endpoint]}"
                else:
                    endpoint_matches = [
                        number
                        for number, heavy in endpoint_heavy.items()
                        if neighbor_names & heavy
                    ]
                    if len(endpoint_matches) != 1:
                        raise ValueError(
                            f"hydrogen {name} has ambiguous endpoint neighbors"
                        )
                    endpoint = endpoint_matches[0]
                    alias = hydrogen_aliases.get(endpoint, {}).get(name, name)
                    key = f"{endpoint}:{alias}"
        else:
            neighbors = list(atom.GetNeighbors())
            if atom.GetSymbol() != "H" or len(neighbors) != 1:
                raise ValueError("stereo candidate gained an unexpected atom")
            neighbor = neighbors[0]
            if not neighbor.HasProp("ccd_atom_id"):
                raise ValueError("generated hydrogen has no named neighbor")
            cap = cap_by_name.get(neighbor.GetProp("ccd_atom_id"))
            if cap is None:
                raise ValueError("generated hydrogen is outside a reviewed methyl cap")
            endpoint = int(cap["endpoint"])
            cap_h_count[endpoint] += 1
            key = f"{endpoint}:HCM{cap_h_count[endpoint]}"
        if key is None:
            raise ValueError("candidate atom could not be assigned a stable key")
        keys.append(key)
    if len(keys) != len(set(keys)) or cap_h_count != {1: 3, 2: 3}:
        raise ValueError("candidate stable atom map is duplicate or cap-incomplete")
    return keys


def build_tt_cpd_stereo_candidates(
    *, reference_dir: Path, output_dir: Path
) -> dict[str, Any]:
    """Generate all eight hash-linked, review-only N1-methyl TT-CPD models."""

    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except ImportError as exc:
        raise RuntimeError("RDKit is required in the photoproduct QM environment") from exc
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite stereo candidates: {output_dir}")
    definition = load_chemical_definition("TT-CPD", "cis-syn")
    source_records = {item["filename"]: item for item in definition["source_assets"]}
    sdf_path = reference_dir / "TTD_ideal.sdf"
    cif_path = reference_dir / "TTD.cif"
    for path in (sdf_path, cif_path):
        expected = source_records[path.name]["sha256"]
        if not path.is_file() or _sha256(path) != expected:
            raise ValueError(f"missing or hash-mismatched verified source: {path}")
    rows = _ccd_atom_rows(cif_path)
    source = Chem.MolFromMolFile(str(sdf_path), removeHs=False, sanitize=True)
    if source is None or source.GetNumAtoms() != len(rows):
        raise ValueError("RCSB TTD SDF/CIF atom tables do not align")
    for atom, row in zip(source.GetAtoms(), rows, strict=True):
        atom.SetProp("ccd_atom_id", row["_chem_comp_atom.atom_id"])
    source_cip = _cip_codes(source)
    if source_cip != {"C5": "R", "C6": "R", "C5T": "S", "C6T": "S"}:
        raise ValueError(f"canonical TTD stereochemistry changed: {source_cip}")

    registry_bytes = REGISTRY_PATH.read_bytes()
    entries = [
        item for item in photoproduct_registry()["products"] if item["product"] == "TT-CPD"
    ]
    output_dir.mkdir(parents=True)
    records = []
    for position, entry in enumerate(entries):
        stereochemistry = entry["stereochemistry"]
        full = _candidate_full_molecule(source, stereochemistry)
        full_cip = _cip_codes(full)
        observed_c5 = [full_cip["C5"], full_cip["C5T"]]
        expected_c5 = entry["structural_class"]["ordered_c5_configurations"]
        if observed_c5 != expected_c5:
            raise ValueError(
                f"{stereochemistry}: derived C5 {observed_c5} != reviewed {expected_c5}"
            )
        model = _prune_to_n1_methyl_model(full, definition)
        atom_map = _stable_atom_map(model, definition)
        parameters = AllChem.ETKDGv3()
        parameters.randomSeed = 0x4E41444F + position
        parameters.enforceChirality = True
        parameters.useRandomCoords = True
        if AllChem.EmbedMolecule(model, parameters) < 0:
            raise ValueError(f"{stereochemistry}: RDKit could not embed candidate")
        force_field_status = AllChem.UFFOptimizeMolecule(model, maxIters=1000)
        if force_field_status not in {0, 1}:
            raise ValueError(f"{stereochemistry}: UFF candidate cleanup failed")
        item_dir = output_dir / entry["id"]
        item_dir.mkdir()
        xyz_path = item_dir / "candidate.xyz"
        map_path = item_dir / "atom_map.json"
        sdf_output = item_dir / "candidate.sdf"
        graph_path = item_dir / "model_graph.json"
        conformer = model.GetConformer()
        xyz_lines = [str(model.GetNumAtoms()), f"{entry['id']} review-only candidate"]
        coordinates: dict[str, list[float]] = {}
        for atom, key in zip(model.GetAtoms(), atom_map, strict=True):
            point = conformer.GetAtomPosition(atom.GetIdx())
            coordinates[key] = [float(point.x), float(point.y), float(point.z)]
            xyz_lines.append(
                f"{atom.GetSymbol():<2} {point.x: .12f} {point.y: .12f} {point.z: .12f}"
            )
        signed_volume_references = {
            "1:C5": ["1:C4", "1:C6", "1:C7"],
            "1:C6": ["1:N1", "1:C5", "1:H6"],
            "2:C5": ["2:C4", "2:C6", "2:C7"],
            "2:C6": ["2:N1", "2:C5", "2:H6"],
        }
        signed_volumes = [
            {
                "atom": atom,
                "reference_atoms": references,
                "expected_sign": (
                    "positive"
                    if signed_tetrahedron_volume(coordinates, atom, references) > 0
                    else "negative"
                ),
            }
            for atom, references in signed_volume_references.items()
        ]
        xyz_path.write_text("\n".join(xyz_lines) + "\n")
        map_path.write_text(json.dumps(atom_map, indent=2) + "\n")
        graph_path.write_text(json.dumps(_model_graph(model, atom_map), indent=2) + "\n")
        writer = Chem.SDWriter(str(sdf_output))
        writer.write(model)
        writer.close()
        manifest = {
            "schema": "nadoc.tt-cpd-stereo-candidate.v1",
            "status": "candidate_not_reviewed",
            "gate_effect": "none",
            "product_id": entry["id"],
            "model_id": f"n1-methyl-{entry['id']}",
            "stereochemistry": stereochemistry,
            "orientation": entry["structural_class"]["double_bond_orientation"],
            "ordered_c5_configurations": observed_c5,
            "derived_full_ring_cip": full_cip,
            "model_signed_volume_stereochemistry": signed_volumes,
            "endpoint_face_flips_from_rcsb_ttd": list(_FACE_FLIPS[stereochemistry]),
            "suprafacial_constraint": "C5 and C6 on an endpoint invert together",
            "crosslink_rewiring": (
                ["remove C5-C5T", "remove C6-C6T", "add C5-C6T", "add C6-C5T"]
                if "anti" in stereochemistry
                else []
            ),
            "mirror_operation_used": False,
            "coordinate_generation": {
                "engine": "RDKit ETKDGv3 plus UFF candidate cleanup",
                "random_seed": parameters.randomSeed,
                "uff_converged": force_field_status == 0,
                "authority": "initial geometry only",
            },
            "sources": {
                "ttd_sdf": {"path": str(sdf_path.resolve()), "sha256": _sha256(sdf_path)},
                "ttd_cif": {"path": str(cif_path.resolve()), "sha256": _sha256(cif_path)},
                "registry": {
                    "path": str(REGISTRY_PATH.resolve()),
                    "sha256": hashlib.sha256(registry_bytes).hexdigest(),
                },
                "ordered_c5_assignment": "Taylor 2023 DOI 10.1111/php.13694, Figures S1-S2",
            },
            "outputs": {
                "xyz": {"path": str(xyz_path.resolve()), "sha256": _sha256(xyz_path)},
                "atom_map": {"path": str(map_path.resolve()), "sha256": _sha256(map_path)},
                "sdf": {"path": str(sdf_output.resolve()), "sha256": _sha256(sdf_output)},
                "graph": {"path": str(graph_path.resolve()), "sha256": _sha256(graph_path)},
            },
            "release_blockers": [
                "independent atom-mapped stereochemical review",
                "QM optimization with retained endpoint identity",
                "frequency confirmation of a minimum",
                "product-specific CHARMM parameter fit and validation",
            ],
        }
        manifest_path = item_dir / "candidate_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        records.append(
            {
                "product_id": entry["id"],
                "manifest": str(manifest_path.resolve()),
                "sha256": _sha256(manifest_path),
            }
        )
    series = {
        "schema": "nadoc.tt-cpd-stereo-candidate-series.v1",
        "status": "candidates_not_reviewed",
        "gate_effect": "none",
        "candidate_count": len(records),
        "records": records,
    }
    series_path = output_dir / "candidate_series_manifest.json"
    series_path.write_text(json.dumps(series, indent=2) + "\n")
    return series


def audit_tt_cpd_stereo_candidates(
    *, series_manifest_path: Path, output_path: Path
) -> dict[str, Any]:
    """Audit candidate identity, stereochemistry, graph, charge, and hashes."""

    try:
        from rdkit import Chem
    except ImportError as exc:
        raise RuntimeError("RDKit is required in the photoproduct QM environment") from exc
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite candidate audit: {output_path}")
    series_bytes = series_manifest_path.read_bytes()
    series = json.loads(series_bytes)
    if series.get("schema") != "nadoc.tt-cpd-stereo-candidate-series.v1":
        raise ValueError("unsupported TT-CPD stereo candidate series")
    registry = photoproduct_registry()
    entries = {
        item["id"]: item for item in registry["products"] if item["product"] == "TT-CPD"
    }
    errors: list[str] = []
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in series.get("records") or []:
        product_id = record.get("product_id")
        manifest_path = Path(str(record.get("manifest") or ""))
        if product_id in seen:
            errors.append(f"duplicate candidate {product_id}")
            continue
        seen.add(product_id)
        if (
            product_id not in entries
            or not manifest_path.is_file()
            or _sha256(manifest_path) != record.get("sha256")
        ):
            errors.append(f"{product_id}: missing, unknown, or hash-mismatched manifest")
            continue
        manifest = json.loads(manifest_path.read_text())
        item_errors: list[str] = []
        if (
            manifest.get("schema") != "nadoc.tt-cpd-stereo-candidate.v1"
            or manifest.get("status") != "candidate_not_reviewed"
            or manifest.get("gate_effect") != "none"
            or manifest.get("product_id") != product_id
            or manifest.get("mirror_operation_used") is not False
        ):
            item_errors.append("candidate identity/status/mirror policy is invalid")
        output_records = manifest.get("outputs") or {}
        checked_paths: dict[str, Path] = {}
        for name in ("xyz", "atom_map", "sdf"):
            output_record = output_records.get(name) or {}
            path = Path(str(output_record.get("path") or ""))
            if not path.is_file() or _sha256(path) != output_record.get("sha256"):
                item_errors.append(f"{name} output is missing or hash-mismatched")
            else:
                checked_paths[name] = path
        checked_graph: dict[str, Any] | None = None
        if output_records.get("graph") is not None:
            graph_record = output_records["graph"]
            graph_path = Path(str(graph_record.get("path") or ""))
            if not graph_path.is_file() or _sha256(graph_path) != graph_record.get(
                "sha256"
            ):
                item_errors.append("graph output is missing or hash-mismatched")
            else:
                checked_graph = json.loads(graph_path.read_text())
        graph_audit: dict[str, Any] = {}
        signed_volume_audit: dict[str, Any] = {}
        if set(checked_paths) == {"xyz", "atom_map", "sdf"}:
            atom_map = json.loads(checked_paths["atom_map"].read_text())
            molecule = Chem.MolFromMolFile(
                str(checked_paths["sdf"]), removeHs=False, sanitize=True
            )
            if (
                molecule is None
                or molecule.GetNumAtoms() != 36
                or len(atom_map) != molecule.GetNumAtoms()
                or len(atom_map) != len(set(atom_map))
            ):
                item_errors.append("candidate SDF/atom map is not a unique 36-atom model")
            else:
                by_key = {key: index for index, key in enumerate(atom_map)}
                if checked_graph is not None and checked_graph != _model_graph(
                    molecule, atom_map
                ):
                    item_errors.append(
                        "engine-neutral graph differs from the independently parsed SDF"
                    )

                def bonded(first: str, second: str) -> bool:
                    return molecule.GetBondBetweenAtoms(by_key[first], by_key[second]) is not None

                entry = entries[product_id]
                expected_crosslinks = [
                    tuple(item.split("--")) for item in entry["graph_delta"]["bonds_added"]
                ]
                all_possible = {
                    ("1:C5", "2:C5"),
                    ("1:C6", "2:C6"),
                    ("1:C5", "2:C6"),
                    ("1:C6", "2:C5"),
                }
                present = sorted(
                    [list(pair) for pair in all_possible if bonded(*pair)]
                )
                expected = sorted([list(pair) for pair in expected_crosslinks])
                retained = bonded("1:C5", "1:C6") and bonded("2:C5", "2:C6")
                charge = sum(atom.GetFormalCharge() for atom in molecule.GetAtoms())
                symmetry_ranks = Chem.CanonicalRankAtoms(
                    molecule, breakTies=False, includeChirality=False
                )
                endpoint_pairs = [
                    [key, f"2:{key.split(':', 1)[1]}"]
                    for key in atom_map
                    if key.startswith("1:") and f"2:{key.split(':', 1)[1]}" in by_key
                ]
                endpoint_charge_symmetry = (
                    len(endpoint_pairs) * 2 == len(atom_map)
                    and all(
                        symmetry_ranks[by_key[first]] == symmetry_ranks[by_key[second]]
                        for first, second in endpoint_pairs
                    )
                )
                graph_audit = {
                    "present_crosslinks": present,
                    "expected_crosslinks": expected,
                    "retained_intrabase_c5_c6": retained,
                    "atom_count": molecule.GetNumAtoms(),
                    "formal_charge": charge,
                    "endpoint_exchange_graph_symmetry_ignoring_chirality": endpoint_charge_symmetry,
                    "charge_symmetry_pairs": endpoint_pairs,
                }
                if present != expected or not retained:
                    item_errors.append("candidate crosslink graph is incorrect")
                if charge != 0:
                    item_errors.append("candidate model charge is not zero")
                if not endpoint_charge_symmetry:
                    item_errors.append(
                        "candidate lacks endpoint-exchange graph symmetry for charge fitting"
                    )
                xyz_rows = checked_paths["xyz"].read_text().splitlines()
                try:
                    xyz_count = int(xyz_rows[0].strip())
                    xyz_coordinates = {
                        key: [float(value) for value in row.split()[1:4]]
                        for key, row in zip(atom_map, xyz_rows[2:], strict=True)
                    }
                except (ValueError, IndexError):
                    xyz_count = -1
                    xyz_coordinates = {}
                if xyz_count != len(atom_map) or len(xyz_coordinates) != len(atom_map):
                    item_errors.append("candidate XYZ does not match the stable atom map")
                else:
                    signed_volume_audit = _audit_signed_volume_records(
                        coordinates=xyz_coordinates,
                        records=manifest.get("model_signed_volume_stereochemistry"),
                    )
                    if not signed_volume_audit["passed"]:
                        item_errors.append(
                            "candidate signed-volume stereochemistry is not reproducible"
                        )
        sources = manifest.get("sources") or {}
        source_sdf = Path(str((sources.get("ttd_sdf") or {}).get("path") or ""))
        source_cif = Path(str((sources.get("ttd_cif") or {}).get("path") or ""))
        if (
            not source_sdf.is_file()
            or _sha256(source_sdf) != (sources.get("ttd_sdf") or {}).get("sha256")
            or not source_cif.is_file()
            or _sha256(source_cif) != (sources.get("ttd_cif") or {}).get("sha256")
        ):
            item_errors.append("verified TTD source files are unavailable")
        else:
            rows = _ccd_atom_rows(source_cif)
            source = Chem.MolFromMolFile(str(source_sdf), removeHs=False, sanitize=True)
            if source is None or source.GetNumAtoms() != len(rows):
                item_errors.append("TTD source atom tables no longer align")
            else:
                for atom, row in zip(source.GetAtoms(), rows, strict=True):
                    atom.SetProp("ccd_atom_id", row["_chem_comp_atom.atom_id"])
                recomputed_cip = _cip_codes(
                    _candidate_full_molecule(source, manifest["stereochemistry"])
                )
                expected_c5 = entries[product_id]["structural_class"][
                    "ordered_c5_configurations"
                ]
                if (
                    recomputed_cip != manifest.get("derived_full_ring_cip")
                    or [recomputed_cip["C5"], recomputed_cip["C5T"]] != expected_c5
                ):
                    item_errors.append("full-graph CIP assignment is not reproducible")
        results.append(
            {
                "product_id": product_id,
                "passed": not item_errors,
                "derived_full_ring_cip": manifest.get("derived_full_ring_cip"),
                "graph_audit": graph_audit,
                "signed_volume_audit": signed_volume_audit,
                "manifest_sha256": _sha256(manifest_path),
                "errors": item_errors,
            }
        )
        errors.extend(f"{product_id}: {message}" for message in item_errors)
    if seen != set(entries):
        errors.append(f"candidate IDs do not cover the eight-product registry: {sorted(seen)}")
    ring_assignments = {
        tuple(item.get("derived_full_ring_cip", {}).get(name) for name in _RING_ATOMS)
        for item in results
        if item.get("derived_full_ring_cip")
    }
    if len(ring_assignments) != 8:
        errors.append("the eight candidates do not have eight distinct full-ring assignments")
    report = {
        "schema": "nadoc.tt-cpd-stereo-candidate-audit.v1",
        "status": "passed_candidate" if not errors else "failed",
        "passed": not errors,
        "gate_effect": "none",
        "series_manifest": {
            "path": str(series_manifest_path.resolve()),
            "sha256": hashlib.sha256(series_bytes).hexdigest(),
        },
        "candidate_count": len(results),
        "candidates": results,
        "errors": errors,
        "release_note": (
            "This validates deterministic candidate construction only. Independent "
            "stereochemical review, QM minima, parameters, and context validation remain required."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def build_tt_cpd_chemical_definition_candidate(
    *,
    product_id: str,
    candidate_manifest_path: Path,
    candidate_audit_path: Path,
    independent_audit_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Create a review artifact for one noncanonical ordered TT-CPD definition.

    The artifact deliberately uses a distinct schema and is never loadable as a released
    chemical definition. It makes all derived C6 assignments and evidence hashes visible
    for independent review.
    """

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite definition candidate: {output_path}")
    manifest_bytes = candidate_manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    audit = json.loads(candidate_audit_path.read_text())
    independent_audit = json.loads(independent_audit_path.read_text())
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    audit_record = next(
        (
            item
            for item in audit.get("candidates") or []
            if item.get("product_id") == product_id
        ),
        None,
    )
    if (
        manifest.get("schema") != "nadoc.tt-cpd-stereo-candidate.v1"
        or manifest.get("status") != "candidate_not_reviewed"
        or manifest.get("product_id") != product_id
        or audit.get("schema") != "nadoc.tt-cpd-stereo-candidate-audit.v1"
        or audit.get("status") != "passed_candidate"
        or not isinstance(audit_record, dict)
        or not audit_record.get("passed")
        or audit_record.get("manifest_sha256") != manifest_hash
    ):
        raise ValueError("candidate manifest is not covered by the passed series audit")
    independent_record = next(
        (
            item
            for item in independent_audit.get("records") or []
            if item.get("product_id") == product_id
        ),
        None,
    )
    expected_sdf_hash = ((manifest.get("outputs") or {}).get("sdf") or {}).get(
        "sha256"
    )
    if (
        independent_audit.get("schema")
        != "nadoc.tt-cpd-openbabel-stereo-audit.v1"
        or independent_audit.get("status")
        != "software_crosscheck_passed_human_review_required"
        or independent_audit.get("passed") is not True
        or (independent_audit.get("candidate_audit") or {}).get("sha256")
        != _sha256(candidate_audit_path)
        or not isinstance(independent_record, dict)
        or independent_record.get("sdf_sha256") != expected_sdf_hash
    ):
        raise ValueError(
            "definition candidate requires a passed, hash-linked independent stereo audit"
        )
    registry_entry = next(
        (
            item
            for item in photoproduct_registry()["products"]
            if item["id"] == product_id
        ),
        None,
    )
    if registry_entry is None or registry_entry["stereochemistry"] == "cis-syn":
        raise ValueError("definition-candidate builder requires a registered noncanonical TT-CPD")
    outputs = manifest.get("outputs") or {}
    xyz_path = Path(str((outputs.get("xyz") or {}).get("path") or ""))
    atom_map_path = Path(str((outputs.get("atom_map") or {}).get("path") or ""))
    if (
        not xyz_path.is_file()
        or _sha256(xyz_path) != (outputs.get("xyz") or {}).get("sha256")
        or not atom_map_path.is_file()
        or _sha256(atom_map_path) != (outputs.get("atom_map") or {}).get("sha256")
    ):
        raise ValueError("candidate coordinates or stable atom map are hash-mismatched")
    atom_map = json.loads(atom_map_path.read_text())
    rows = xyz_path.read_text().splitlines()
    if int(rows[0]) != len(atom_map) or len(rows[2:]) != len(atom_map):
        raise ValueError("candidate XYZ and stable atom map differ")
    coordinates = {
        key: [float(value) for value in row.split()[1:4]]
        for key, row in zip(atom_map, rows[2:], strict=True)
    }
    base = load_chemical_definition("TT-CPD", "cis-syn")
    definition = {
        "schema": "nadoc.photoproduct-chemical-definition-candidate.v1",
        "status": "review_required",
        "gate_effect": "none",
        "id": product_id,
        "product": "TT-CPD",
        "stereochemistry": registry_entry["stereochemistry"],
        "state": base["state"],
        "ordered_endpoints": deepcopy(base["ordered_endpoints"]),
        "graph_delta": {
            "atoms_added": [],
            "atoms_removed": [],
            "formal_charge_change": 0,
            "bonds_added": [
                {"atom_1": pair.split("--")[0], "atom_2": pair.split("--")[1], "order": "single"}
                for pair in registry_entry["graph_delta"]["bonds_added"]
            ],
            "bonds_retained": [
                {
                    "atom_1": pair.split("--")[0],
                    "atom_2": pair.split("--")[1],
                    "precursor_order": "double",
                    "product_order": "single",
                }
                for pair in registry_entry["graph_delta"]["bonds_retained"]
            ],
            "backbone_and_glycosidic_connectivity": "preserved",
        },
        "patch_charge_scope": _candidate_patch_charge_scope(product_id),
        "precursor_local_connectivity": deepcopy(base["precursor_local_connectivity"]),
        "product_stereocenters": [
            {
                "atom": record["atom"],
                "ccd_configuration": manifest["derived_full_ring_cip"][
                    "C5T" if record["atom"] == "2:C5" else "C6T" if record["atom"] == "2:C6" else record["atom"].split(":")[1]
                ],
                "signed_volume_reference_atoms": record["reference_atoms"],
                "expected_signed_volume": record["expected_sign"],
                "authority": (
                    "Taylor 2023 ordered assignment"
                    if record["atom"].endswith(":C5")
                    else "suprafacial candidate derivation; independent review required"
                ),
            }
            for record in manifest["model_signed_volume_stereochemistry"]
        ],
        "source_ring_coordinates_angstrom": {
            key: coordinates[key]
            for key in sorted(
                {
                    item
                    for record in manifest["model_signed_volume_stereochemistry"]
                    for item in [record["atom"], *record["reference_atoms"]]
                }
            )
        },
        "model_compounds": deepcopy(base["model_compounds"]),
        "requested_contexts": registry_entry.get("requested_contexts", []),
        "candidate_evidence": {
            "manifest": {
                "path": str(candidate_manifest_path.resolve()),
                "sha256": manifest_hash,
            },
            "series_audit": {
                "path": str(candidate_audit_path.resolve()),
                "sha256": _sha256(candidate_audit_path),
            },
            "independent_stereo_audit": {
                "path": str(independent_audit_path.resolve()),
                "sha256": _sha256(independent_audit_path),
                "engine": independent_audit["engine"],
                "record": independent_record,
            },
            "ordered_c5_source": "Taylor 2023 DOI 10.1111/php.13694, Figures S1-S2",
            "canonical_graph_source": "RCSB TTD; anti rewiring follows Yang 2026 syn/anti regio-connectivity",
        },
        "release_blockers": [
            "independent atom-mapped review of all four absolute configurations",
            "replace candidate coordinates with a passed QM minimum and frequency evidence",
            "review model compounds and DNA boundary contexts",
            "convert to the released schema only through chemical-definition gate review",
        ],
    }
    definition["model_compounds"]["charge_model"]["id"] = f"n1-methyl-{product_id}"
    definition["model_compounds"]["charge_model"]["source_asset"] = (
        "hash-linked stereoisomer candidate pending review"
    )
    definition["model_compounds"]["dna_boundary_model"].update(
        {
            "id": f"{product_id}-dinucleotide-boundary",
            "status": "definition-pending",
            "release_rule": (
                "construct and review a product-specific ordered DNA boundary model; "
                "the cis-syn 1N4E fragment is not a coordinate template for this isomer"
            ),
        }
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(definition, indent=2) + "\n")
    return definition
