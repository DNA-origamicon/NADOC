"""Construct chemically partitioned TT-CPD QM boundary model compounds.

The complete covalent photoproduct is retained in every model.  To isolate one
glycosidic boundary, one endpoint keeps its complete deoxyribose while the
opposite endpoint is capped at N1 with a neutral methyl group.  The open
backbone oxygen on the retained sugar is hydroxyl capped.  This follows the
model-compound hierarchy used by additive CHARMM parameter development; it is
not a force-field release decision.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from backend.core.photoproduct_chemistry import (
    audit_product_chirality,
    load_chemical_definition,
)
from backend.core.photoproduct_registry import photoproduct_registry


class FragmentConstructionError(RuntimeError):
    """A source boundary model cannot yield the requested audited fragment."""


_BASE_ATOMS = {
    "N1",
    "C2",
    "O2",
    "N3",
    "H3",
    "C4",
    "O4",
    "C5",
    "C7",
    "H51",
    "H52",
    "H53",
    "C6",
    "H6",
}

_SUGAR_ATOMS = {
    "O5'",
    "C5'",
    "H5'",
    "H5''",
    "C4'",
    "H4'",
    "O4'",
    "C3'",
    "H3'",
    "O3'",
    "HO3'",
    "C2'",
    "H2'",
    "H2''",
    "C1'",
    "H1'",
    "HO5'",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _resolve_output(
    manifest_path: Path, manifest: dict[str, Any], name: str
) -> Path:
    record = (manifest.get("outputs") or {}).get(name)
    if not isinstance(record, dict):
        raise FragmentConstructionError(f"source boundary has no {name} output")
    declared = Path(str(record.get("path") or ""))
    candidates = (declared, manifest_path.parent / declared.name)
    for candidate in candidates:
        if candidate.is_file() and _sha256(candidate) == record.get("sha256"):
            return candidate.resolve()
    raise FragmentConstructionError(
        f"source boundary {name} is unavailable or hash-mismatched"
    )


def _registry_identity(product_id: str) -> tuple[str, str]:
    matches = [
        item for item in photoproduct_registry()["products"] if item["id"] == product_id
    ]
    if len(matches) != 1:
        raise FragmentConstructionError(
            f"no unique photoproduct registry entry for {product_id}"
        )
    return str(matches[0]["product"]), str(matches[0]["stereochemistry"])


def _model_graph(model: Any, atom_map: list[str]) -> dict[str, Any]:
    if model.GetNumAtoms() != len(atom_map) or len(atom_map) != len(set(atom_map)):
        raise FragmentConstructionError("fragment atom map is not a bijection")
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
        first, second = sorted((bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()))
        bonds.append(
            {
                "indices": [first, second],
                "atoms": [atom_map[first], atom_map[second]],
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


def _xyz_text(model: Any, atom_map: list[str], comment: str) -> str:
    conformer = model.GetConformer()
    lines = [str(len(atom_map)), comment]
    for index, atom in enumerate(model.GetAtoms()):
        point = conformer.GetAtomPosition(index)
        lines.append(
            f"{atom.GetSymbol():<2} {point.x: .12f} {point.y: .12f} {point.z: .12f}"
        )
    return "\n".join(lines) + "\n"


def _source_model(
    source_manifest_path: Path,
) -> tuple[Any, list[str], dict[str, Any], dict[str, Path]]:
    try:
        from rdkit import Chem
    except ImportError as exc:
        raise FragmentConstructionError(
            "RDKit is required; use the nadoc-qm environment"
        ) from exc

    source_manifest_path = source_manifest_path.resolve()
    source = json.loads(source_manifest_path.read_text())
    accepted_statuses = {
        "quantitatively_screened_boundary",
        "human_cap_review_complete",
    }
    if (
        source.get("schema")
        != "nadoc.photoproduct-dna-boundary-model-candidate.v1"
        or source.get("status") not in accepted_statuses
        or source.get("gate_effect") != "none"
        or source.get("atom_count") != 63
        or source.get("formal_charge") != -1
    ):
        raise FragmentConstructionError(
            "a screened 63-atom, charge -1 d(TpT) boundary model is required"
        )
    paths = {
        name: _resolve_output(source_manifest_path, source, name)
        for name in ("xyz", "atom_map", "sdf")
    }
    atom_map = json.loads(paths["atom_map"].read_text())
    if (
        not isinstance(atom_map, list)
        or len(atom_map) != 63
        or len(atom_map) != len(set(atom_map))
    ):
        raise FragmentConstructionError("source stable atom map is invalid")
    supplier = Chem.SDMolSupplier(str(paths["sdf"]), removeHs=False)
    model = supplier[0] if supplier and len(supplier) == 1 else None
    if model is None or model.GetNumAtoms() != len(atom_map):
        raise FragmentConstructionError("RDKit could not load the mapped source SDF")
    Chem.SanitizeMol(model)
    for atom, key in zip(model.GetAtoms(), atom_map, strict=True):
        atom.SetProp("nadoc_stable_key", key)
    return model, atom_map, source, paths


def build_single_endpoint_glycosidic_fragment(
    *,
    source_manifest_path: Path,
    retained_endpoint: int,
    output_dir: Path,
) -> dict[str, Any]:
    """Build a neutral 49-atom TT-CPD/deoxyribose boundary model.

    ``retained_endpoint`` keeps the complete endpoint sugar.  The other C1' is
    converted to the N1 methyl cap, and the retained sugar's phosphate-facing
    oxygen receives the only other newly generated hydrogen.
    """

    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except ImportError as exc:
        raise FragmentConstructionError(
            "RDKit is required; use the nadoc-qm environment"
        ) from exc

    if retained_endpoint not in {1, 2}:
        raise ValueError("retained_endpoint must be 1 or 2")
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite fragment: {output_dir}")

    model, source_map, source, source_paths = _source_model(source_manifest_path)
    product_id = str(source["product_id"])
    other_endpoint = 2 if retained_endpoint == 1 else 1

    def retain(key: str) -> bool:
        endpoint_text, atom_name = key.split(":", 1)
        endpoint = int(endpoint_text)
        if atom_name in _BASE_ATOMS:
            return True
        if endpoint == retained_endpoint and atom_name in _SUGAR_ATOMS:
            return True
        return endpoint == other_endpoint and atom_name in {"C1'", "H1'"}

    editable = Chem.RWMol(model)
    for index in reversed(range(len(source_map))):
        if not retain(source_map[index]):
            editable.RemoveAtom(index)
    fragment = editable.GetMol()
    Chem.SanitizeMol(fragment)

    pre_hydrogen_count = fragment.GetNumAtoms()
    retained_keys: list[str] = []
    for atom in fragment.GetAtoms():
        key = atom.GetProp("nadoc_stable_key")
        if key == f"{other_endpoint}:C1'":
            key = f"{other_endpoint}:CM"
        elif key == f"{other_endpoint}:H1'":
            key = f"{other_endpoint}:HCM1"
        atom.SetProp("nadoc_stable_key", key)
        retained_keys.append(key)

    fragment = Chem.AddHs(fragment, addCoords=True)
    new_key_counts: dict[str, int] = {}
    for atom in fragment.GetAtoms():
        if atom.HasProp("nadoc_stable_key"):
            continue
        if atom.GetSymbol() != "H" or atom.GetDegree() != 1:
            raise FragmentConstructionError("unexpected generated fragment atom")
        neighbor = atom.GetNeighbors()[0]
        neighbor_key = neighbor.GetProp("nadoc_stable_key")
        if neighbor_key == f"{other_endpoint}:CM":
            count = new_key_counts.get(neighbor_key, 1) + 1
            key = f"{other_endpoint}:HCM{count}"
            new_key_counts[neighbor_key] = count
        else:
            expected_oxygen = (
                f"{retained_endpoint}:O3'"
                if retained_endpoint == 1
                else f"{retained_endpoint}:O5'"
            )
            if neighbor_key != expected_oxygen:
                raise FragmentConstructionError(
                    f"unexpected new hydrogen on {neighbor_key}"
                )
            key = (
                f"{retained_endpoint}:HO3'"
                if retained_endpoint == 1
                else f"{retained_endpoint}:HO5'"
            )
        atom.SetProp("nadoc_stable_key", key)

    atom_map = [atom.GetProp("nadoc_stable_key") for atom in fragment.GetAtoms()]
    if (
        pre_hydrogen_count != 46
        or fragment.GetNumAtoms() != 49
        or len(atom_map) != len(set(atom_map))
        or set(atom_map).intersection({"2:P", "2:OP1", "2:OP2"})
    ):
        raise FragmentConstructionError(
            "fragment does not have the expected 46 retained plus 3 cap atoms"
        )

    # Relax only the three generated cap hydrogens.  Every source coordinate,
    # including the complete product core and retained sugar, remains fixed.
    forcefield = AllChem.UFFGetMoleculeForceField(fragment)
    if forcefield is None:
        raise FragmentConstructionError("UFF could not type the cap-hydrogen model")
    for index in range(pre_hydrogen_count):
        forcefield.AddFixedPoint(index)
    forcefield.Initialize()
    uff_status = int(forcefield.Minimize(maxIts=200))
    if uff_status != 0:
        raise FragmentConstructionError("cap-hydrogen-only UFF relaxation did not converge")

    graph = _model_graph(fragment, atom_map)
    if graph["formal_charge"] != 0:
        raise FragmentConstructionError(
            f"glycosidic fragment charge is {graph['formal_charge']}, expected 0"
        )
    product, stereochemistry = _registry_identity(product_id)
    definition = load_chemical_definition(product, stereochemistry)
    edges = {frozenset(item["atoms"]) for item in graph["bonds"]}
    required_edges = {
        *(
            frozenset((bond["atom_1"], bond["atom_2"]))
            for bond in definition["graph_delta"]["bonds_added"]
        ),
        frozenset((f"{retained_endpoint}:C1'", f"{retained_endpoint}:N1")),
        frozenset((f"{other_endpoint}:CM", f"{other_endpoint}:N1")),
    }
    if not required_edges.issubset(edges):
        raise FragmentConstructionError("fragment lost required product or cap bonds")

    coordinates = {}
    conformer = fragment.GetConformer()
    for index, key in enumerate(atom_map):
        point = conformer.GetAtomPosition(index)
        coordinates[key] = (float(point.x), float(point.y), float(point.z))
    chirality = audit_product_chirality(definition, coordinates)
    if not chirality["passed"]:
        raise FragmentConstructionError("fragment changed the reviewed product chirality")

    output_dir.mkdir(parents=True)
    xyz_path = output_dir / "model.xyz"
    sdf_path = output_dir / "model.sdf"
    atom_map_path = output_dir / "atom_map.json"
    graph_path = output_dir / "model_graph.json"
    manifest_path = output_dir / "model_manifest.json"
    model_id = f"{product_id}-endpoint-{retained_endpoint}-glycosidic-fragment-v1"
    xyz_path.write_text(
        _xyz_text(
            fragment,
            atom_map,
            f"{model_id}; complete TT-CPD plus endpoint {retained_endpoint} deoxyribose",
        )
    )
    writer = Chem.SDWriter(str(sdf_path))
    writer.write(fragment)
    writer.close()
    atom_map_path.write_text(json.dumps(atom_map, indent=2) + "\n")
    graph_path.write_text(json.dumps(graph, indent=2) + "\n")

    manifest = {
        "schema": "nadoc.photoproduct-model-compound.v1",
        "status": "constructed_not_optimized",
        "gate_effect": "none",
        "simulation_ready": False,
        "product_id": product_id,
        "model_id": model_id,
        "model_class": "single_endpoint_glycosidic_boundary",
        "retained_endpoint": retained_endpoint,
        "opposite_endpoint_cap": "neutral_N1_methyl",
        "retained_sugar_open_oxygen_cap": (
            "O3'-H" if retained_endpoint == 1 else "O5'-H"
        ),
        "formal_charge": 0,
        "multiplicity": 1,
        "atom_count": len(atom_map),
        "atom_map": atom_map,
        "source_boundary_manifest": _record(source_manifest_path.resolve()),
        "source_outputs": {
            name: _record(path) for name, path in source_paths.items()
        },
        "construction": {
            "deleted": "opposite sugar beyond C1'/H1' and complete phosphate group",
            "renamed": {
                f"{other_endpoint}:C1'": f"{other_endpoint}:CM",
                f"{other_endpoint}:H1'": f"{other_endpoint}:HCM1",
            },
            "generated_atoms": atom_map[pre_hydrogen_count:],
            "cap_relaxation": "UFF; generated hydrogens mobile; all source atoms fixed",
            "reflection": "forbidden and not performed",
        },
        "chirality_audit": chirality,
        "outputs": {
            "xyz": _record(xyz_path),
            "sdf": _record(sdf_path),
            "atom_map": _record(atom_map_path),
            "model_graph": _record(graph_path),
        },
        "release_blockers": [
            "model has not been optimized at the registered QM level",
            "matching frequency and torsion-response evidence is not complete",
            "force-field and NAMD release gates remain closed",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
