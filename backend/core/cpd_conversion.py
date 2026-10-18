"""Manual MVP conversion, shared by contextual preview and commit.

Compatible 1xT crossovers use six-residue seeds; other pairs retain base-only
placement. Neither path changes force-field qualification.
"""
import json
from pathlib import Path
import uuid

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.base_keys import atom_base_key, resolve_base_keys, parse_base_key
from backend.core.cpd_product import _proper_kabsch
from backend.core.models import PhotoproductJunction
from backend.core.photoproduct_chemistry import audit_product_chirality, load_chemical_definition

METHOD = "manual-base-only-mvp-v1"
CORE_PATH = Path(__file__).resolve().parents[1] / "data/cpd_conversion_cores.json"
BASE_NAMES = frozenset(("N1", "C2", "O2", "N3", "C4", "O4", "C5", "C6", "C7",
                        "C5M", "H3", "H6", "H71", "H72", "H73", "H51", "H52", "H53"))
BASE_ALIASES = {"C5M": "C7", "H71": "H51", "H72": "H52", "H73": "H53"}


def conversion_catalog():
    data = json.loads(CORE_PATH.read_text())
    return {"products": [{"product": "TT-CPD", "id": p["id"],
                          "stereochemistry": p["stereochemistry"],
                          "label": "cis-syn-I" if p["stereochemistry"] == "cis-syn" else p["stereochemistry"]}
                         for p in data["products"]], "qualification": data["qualification"]}


def endpoint_transform(design, parsed):
    key = (("extra_base", parsed.crossover_id, parsed.k) if parsed.family == "xover"
           else ("base", parsed.helix_id, parsed.bp_index, parsed.direction.upper(), parsed.copy))
    return next((t for t in design.nucleotide_transforms if t.target_key() == key), None)


def ordered_conversion_keys(design, base_keys):
    """Standardized 1xT seeds use stable endpoint order, independent of clicks."""
    single = {f"__xb__:{x.id}:0" for x in [*design.crossovers, *design.forced_ligations]
              if x.extra_bases == "T"}
    return sorted(base_keys) if len(base_keys) == 2 and set(base_keys) <= single else list(base_keys)


def prepare_conversion(design, base_keys, stereochemistry):
    from backend.core.atomistic import build_atomistic_model

    if len(base_keys) != 2 or len(set(base_keys)) != 2:
        raise ValueError("Select exactly two distinct thymines.")
    base_keys = ordered_conversion_keys(design, base_keys)
    used = {k for p in design.photoproduct_junctions for k in (p.base_key_1, p.base_key_2, *p.context_coordinates)}
    if used.intersection(base_keys):
        raise ValueError("A selected thymine already belongs to a CPD.")
    data = json.loads(CORE_PATH.read_text())
    core = next((p for p in data["products"] if p["stereochemistry"] == stereochemistry), None)
    if core is None:
        raise ValueError("This isomer has no admitted MVP authoring core.")
    # I/II definitions address ordered endpoints; 1xT seed order is canonical.
    endpoints, errors = resolve_base_keys(design, base_keys, require_atoms=False)
    if errors or len(endpoints) != 2 or any(e.base != "T" or e.parsed.family not in {"xover", "backbone"} for e in endpoints):
        raise ValueError("Select two ordinary or junction extra thymine bases.")
    for endpoint in endpoints:
        p = endpoint.parsed
        canonical = (f"__xb__:{p.crossover_id}:{p.k}" if p.family == "xover"
                     else f"{p.helix_id}:{p.bp_index}:{p.direction.upper()}" + (f":{p.copy}" if p.copy else ""))
        if endpoint.key != canonical:
            raise ValueError("Select canonical nucleotide identities.")
    model = build_atomistic_model(design)
    endpoints, errors = resolve_base_keys(design, base_keys, atomistic_model=model)
    if errors:
        raise ValueError("Selected thymines have no atomistic coordinates.")
    template = {k: np.array(v) for k, v in core["coordinates"].items()}
    definition = load_chemical_definition("TT-CPD", stereochemistry)
    if not audit_product_chirality(definition, template)["passed"]:
        raise ValueError("MVP core failed the ordered stereochemistry check.")
    names = ["N1", "C2", "N3", "C4", "C5", "C6"]
    source = np.array([template[f"{i}:{n}"] for i in (1, 2) for n in names])
    target = np.array([e.atom_positions_nm[n] for e in endpoints for n in names])
    rotation, translation, _ = _proper_kabsch(source, target)
    placed = {k: rotation @ xyz + translation for k, xyz in template.items()}
    from backend.core.cpd_six_residue import place_six_residue
    six = place_six_residue(design, model, endpoints, definition)
    metadata = {"method": METHOD, "backbone_fixed": True}
    world = {}
    if six is not None:
        world, metadata = six
    else:
        for i, endpoint in enumerate(endpoints, 1):
            world[endpoint.key] = {name: placed[f"{i}:{BASE_ALIASES.get(name, name)}"] for name in BASE_NAMES
                                  if f"{i}:{BASE_ALIASES.get(name, name)}" in placed}
    stored = {}
    for key, positions in world.items():
        pose = endpoint_transform(design, parse_base_key(key))
        if pose:
            r = Rotation.from_quat(pose.rotation).as_matrix()
            pivot, offset = np.array(pose.pivot), np.array(pose.translation)
            positions = {name: (xyz - pivot - offset) @ r + pivot for name, xyz in positions.items()}
        stored[key] = {name: xyz.tolist() for name, xyz in positions.items()}
    crosslinks = []
    for bond in definition["graph_delta"]["bonds_added"]:
        pair = []
        for address in (bond["atom_1"], bond["atom_2"]):
            i, name = address.split(":")
            pair.append(endpoints[int(i) - 1].atom_serials[name])
        crosslinks.append(tuple(pair))
    # One bonded residue on either side of each endpoint gives real strand context.
    by_serial = {a.serial: a for a in model.atoms}
    context = set(base_keys)
    for a, b in model.bonds:
        ka, kb = atom_base_key(by_serial[a]), atom_base_key(by_serial[b])
        if ka in base_keys or kb in base_keys:
            context.update((ka, kb))
    atoms = [a for a in model.atoms if atom_base_key(a) in context and a.element != "H"]
    indices = {a.serial: i for i, a in enumerate(atoms)}
    glyco = [float(np.linalg.norm(world[e.key]["N1"] - world[e.key].get("C1'", e.atom_positions_nm["C1'"]))) for e in endpoints]
    preview = {
        "positions": [world.get(atom_base_key(a), {}).get(a.name, np.array([a.x, a.y, a.z])).tolist() for a in atoms],
        "original_positions": [[a.x, a.y, a.z] for a in atoms],
        "atom_keys": [f"{atom_base_key(a)}:{a.name}" for a in atoms],
        "elements": [a.element for a in atoms],
        "strand_ids": [a.strand_id for a in atoms],
        "selected": [atom_base_key(a) in base_keys and a.name in BASE_NAMES for a in atoms],
        "bonds": [[indices[a], indices[b]] for a, b in [*model.bonds, *crosslinks] if a in indices and b in indices],
        "crosslinks": [[indices[a], indices[b]] for a, b in crosslinks],
        "relationship": "same strand" if endpoints[0].strand_id == endpoints[1].strand_id and endpoints[0].strand_id else "different strands",
        "endpoints": [e.to_dict() for e in endpoints],
        "glycosidic_distances_nm": glyco,
        "placement": metadata,
        "qualification": ("Six-residue starting geometry. Selected nucleotides and adjacent sugars/backbones move; flanking bases stay fixed. Simulation qualification is unchanged." if six is not None else "MVP visual construction. Backbone fixed; attachment strain is not relaxed. Simulation qualification is unchanged."),
    }
    return stored, preview


def convert_thymine_pair(design, base_keys, stereochemistry, *, identity_seed=None):
    base_keys = ordered_conversion_keys(design, base_keys)
    stored, preview = prepare_conversion(design, base_keys, stereochemistry)
    lesion = PhotoproductJunction(id=identity_seed or str(uuid.uuid4()),
        base_key_1=base_keys[0], base_key_2=base_keys[1], stereochemistry=stereochemistry,
        orientation_method=preview["placement"]["method"],
        design_coordinates={k:v for k,v in stored.items() if k in base_keys},
        context_coordinates={k:v for k,v in stored.items() if k not in base_keys},
        bond_relaxation={**preview["placement"],
                         "glycosidic_distances_nm": preview["glycosidic_distances_nm"]})
    return design.copy_with(photoproduct_junctions=[*design.photoproduct_junctions, lesion]), preview
