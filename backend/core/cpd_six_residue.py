"""Context-fitted six-residue authoring seeds for two single-T crossovers."""

import json
from pathlib import Path
import numpy as np
from backend.core.base_keys import atom_base_key
from backend.core.cpd_product import _proper_kabsch
from backend.core.photoproduct_chemistry import audit_product_chirality

METHOD = "manual-six-residue-mvp-v1"
SEEDS = Path(__file__).resolve().parents[1] / "data/cpd_six_residue_seeds.json"
ALIASES = {"O1P": "OP1", "O2P": "OP2", "C5M": "C7"}


def place_six_residue(design, model, endpoints, definition):
    """Return None outside 1xT scope; reject incompatible contexts explicitly.

    Fit to unchanged flanking glycosidic nitrogens. The fit is rigid: it cannot
    change seed stereochemistry. Boundary checks prevent silently stretching a
    seed into a substantially different crossover geometry.
    """
    crossovers = {x.id: x for x in [*design.crossovers, *design.forced_ligations]}
    if not all(
        e.parsed.family == "xover"
        and crossovers[e.parsed.crossover_id].extra_bases == "T"
        for e in endpoints
    ):
        return None
    if endpoints[0].parsed.crossover_id == endpoints[1].parsed.crossover_id:
        return None
    by_serial = {a.serial: a for a in model.atoms}
    residues = {}
    for a in model.atoms:
        residues.setdefault(atom_base_key(a), {})[a.name] = np.array([a.x, a.y, a.z])
    roles = {}
    for i, endpoint in enumerate(endpoints, 1):
        roles[f"endpoint-{i}"] = endpoint.key
        for a, b in model.bonds:
            a, b = by_serial[a], by_serial[b]
            if atom_base_key(b) == endpoint.key:
                a, b = b, a
            if atom_base_key(a) != endpoint.key or atom_base_key(b) == endpoint.key:
                continue
            if a.name == "P" and b.name == "O3'":
                roles[f"flank-{i}-5prime"] = atom_base_key(b)
            if a.name == "O3'" and b.name == "P":
                roles[f"flank-{i}-3prime"] = atom_base_key(b)
    if len(roles) != 6 or len(set(roles.values())) != 6:
        raise ValueError(
            "Six-residue CPD placement requires two internal 1×T crossovers with four distinct flanking residues."
        )
    occupied = {
        k
        for p in design.photoproduct_junctions
        for k in [p.base_key_1, p.base_key_2, *p.context_coordinates]
    }
    if occupied.intersection(roles.values()):
        raise ValueError("The six-residue CPD neighborhood overlaps an existing CPD.")
    seed = next(
        p
        for p in json.loads(SEEDS.read_text())["products"]
        if p["stereochemistry"] == definition["stereochemistry"]
    )
    source = {}
    mobile = {}
    for a in seed["atoms"]:
        name = ALIASES.get(a["name"], a["name"])
        source.setdefault(a["role"], {})[name] = np.array(a["position_nm"])
        if a["mobile"]:
            mobile.setdefault(a["role"], {})[name] = np.array(a["position_nm"])
    anchors = [r for r in roles if r.startswith("flank")]

    def nitrogen(atoms):
        return atoms["N9"] if "N9" in atoms else atoms["N1"]

    r, t, rmsd = _proper_kabsch(
        np.array([nitrogen(source[k]) for k in anchors]),
        np.array([nitrogen(residues[roles[k]]) for k in anchors]),
    )
    if rmsd > 0.03:
        raise ValueError(
            "This crossover context differs from the six-residue starting geometry (flanking-base fit exceeds 0.3 Å). Local relaxation is required."
        )
    world = {}
    for role, atoms in mobile.items():
        key = roles[role]
        world[key] = {
            n: r @ xyz + t
            for n, xyz in atoms.items()
            if n in residues[key] or (role.startswith("endpoint") and n == "H6")
        }
    coordinates = {
        f"{i}:{n}": v
        for i, e in enumerate(endpoints, 1)
        for n, v in world[e.key].items()
    }
    if not audit_product_chirality(definition, coordinates)["passed"]:
        raise ValueError("Six-residue seed failed its stereochemistry audit.")
    lengths = []
    for a, b in model.bonds:
        a, b = by_serial[a], by_serial[b]
        ka, kb = atom_base_key(a), atom_base_key(b)
        if (
            ka == kb
            or {a.name, b.name} != {"P", "O3'"}
            or not ({ka, kb} & set(roles.values()))
        ):
            continue
        pa = world.get(ka, {}).get(a.name, np.array([a.x, a.y, a.z]))
        pb = world.get(kb, {}).get(b.name, np.array([b.x, b.y, b.z]))
        lengths.append(float(np.linalg.norm(pa - pb)))
    if any(d < 0.13 or d > 0.19 for d in lengths):
        raise ValueError(
            "Six-residue CPD placement cannot preserve the backbone attachments in this context. Local relaxation is required."
        )
    for key in roles.values():
        atoms = {**residues[key], **world[key]}
        glyco = np.linalg.norm(atoms["C1'"] - nitrogen(atoms))
        if not 0.13 < glyco < 0.18:
            raise ValueError(
                "Six-residue placement cannot preserve a sugar–base attachment in this context."
            )
    # Screen the fitted result against the actual surrounding atoms, including
    # residues outside the six-residue neighborhood shown in the popup.
    from scipy.spatial.distance import cdist

    heavy = [a for a in model.atoms if a.element != "H"]
    xyz = np.array(
        [
            world.get(atom_base_key(a), {}).get(a.name, np.array([a.x, a.y, a.z]))
            for a in heavy
        ]
    )
    moving = [
        i for i, a in enumerate(heavy) if a.name in world.get(atom_base_key(a), {})
    ]
    adjacency = {a.serial: set() for a in model.atoms}
    for a, b in model.bonds:
        adjacency[a].add(b)
        adjacency[b].add(a)
    for bond in definition["graph_delta"]["bonds_added"]:
        pair = []
        for address in [bond["atom_1"], bond["atom_2"]]:
            e, n = address.split(":")
            pair.append(endpoints[int(e) - 1].atom_serials[n])
        a, b = pair
        adjacency[a].add(b)
        adjacency[b].add(a)
    distances = cdist(xyz[moving], xyz)
    for row, i in enumerate(moving):
        serial = heavy[i].serial
        excluded = (
            {serial}
            | adjacency[serial]
            | {v for n in adjacency[serial] for v in adjacency[n]}
        )
        if any(
            heavy[j].serial not in excluded for j in np.where(distances[row] < 0.2)[0]
        ):
            raise ValueError(
                "Six-residue CPD starting geometry clashes with this context. Local relaxation is required."
            )
    return world, {
        "method": METHOD,
        "backbone_fixed": False,
        "flanking_bases_fixed": True,
        "anchor_rmsd_nm": float(rmsd),
        "attachment_distances_nm": lengths,
        "seed_sha256": seed["source_sha256"],
        "context_keys": [roles[k] for k in anchors],
    }
