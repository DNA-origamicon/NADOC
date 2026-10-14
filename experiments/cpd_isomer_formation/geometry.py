"""Experimental suprafacial CPD approach classifier, not a photochemical rate.

Classifies hypothetical bond additions without moving atoms or constructing a
product. Four-neighbor parity preserves the ordered registry stereochemistry.
The retained-neighbor/approach-face assumption excludes excited-state rotation
and stepwise rearrangement. Thresholds are sensitivity hypotheses, not fitted
anti-isomer photochemical parameters.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
NAMES = ("C4", "C5", "C6", "C7", "H6", "N1")
KEYS = tuple(f"{i}:{name}" for i in (1, 2) for name in NAMES)
INDEX = {key: i for i, key in enumerate(KEYS)}


def catalog():
    root = ROOT / "backend/data/forcefield"
    registry = json.loads((root / "photoproduct_registry.json").read_text())
    products = []
    for item in registry["products"]:
        ref = item["assets"]["chemical_definition"]
        path = root / ref["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != ref["sha256"]:
            raise ValueError(f"Changed chemical definition: {path}")
        definition = json.loads(path.read_text())
        partner = {}
        for bond in definition["graph_delta"]["bonds_added"]:
            a, b = bond["atom_1"], bond["atom_2"]
            partner[a], partner[b] = b, a
        centers = []
        for c in definition["product_stereocenters"]:
            centers.append({
                "center": INDEX[c["atom"]],
                "neighbors": [INDEX[x] for x in c["signed_volume_reference_atoms"]],
                "partner": INDEX[partner[c["atom"]]],
                "expected_sign": -1 if c["expected_signed_volume"] == "negative" else 1,
            })
        products.append({"id": item["id"], "label": item["label"],
                         "family": item["structural_class"]["double_bond_orientation"],
                         "relationship": item["structural_class"]["ring_substituent_relationship"],
                         "centers": centers, "definition": {**ref, "path": str(path)}})
    return products


def local_image(coordinates, box):
    """One coherent periodic image for both bases, with separate local atoms."""
    x = np.asarray(coordinates, dtype=np.float64)
    if x.shape[-2:] != (12, 3):
        raise ValueError("Expected (..., 12 atoms, 3 coordinates)")
    if box is None:
        return x.copy()
    from MDAnalysis.lib.distances import minimize_vectors

    def mic(v):
        return minimize_vectors(v.reshape(-1, 3), box).reshape(v.shape)

    a, b = INDEX["1:C5"], INDEX["2:C5"]
    result = np.empty_like(x)
    anchor_a = x[..., a:a+1, :]
    anchor_b = anchor_a + mic(x[..., b:b+1, :] - anchor_a)
    result[..., :6, :] = anchor_a + mic(x[..., :6, :] - anchor_a)
    result[..., 6:, :] = anchor_b + mic(x[..., 6:, :] - x[..., b:b+1, :])
    return result


def _torsion(p0, p1, p2, p3):
    b0, b1, b2 = p0-p1, p2-p1, p3-p2
    norm = np.linalg.norm(b1, axis=-1, keepdims=True)
    axis = np.divide(b1, norm, out=np.full_like(b1, np.nan), where=norm > 1e-12)
    a = b0 - np.sum(b0*axis, axis=-1, keepdims=True)*axis
    b = b2 - np.sum(b2*axis, axis=-1, keepdims=True)*axis
    result = np.degrees(np.arctan2(np.sum(np.cross(axis, a)*b, axis=-1),
                                  np.sum(a*b, axis=-1)))
    return np.where((np.linalg.norm(a, axis=-1) > 1e-12) &
                    (np.linalg.norm(b, axis=-1) > 1e-12), result, np.nan)


def features(coordinates, products=None):
    """Return descriptors for each ordered product; distances are Angstrom."""
    products = catalog() if products is None else products
    x = np.asarray(coordinates, dtype=np.float64)
    if x.shape[-2:] != (12, 3):
        raise ValueError("Expected (..., 12, 3)")
    shape = x.shape[:-2] + (len(products),)
    signs_match = np.zeros(shape, dtype=bool)
    face_margin = np.empty(shape)
    max_distance = np.empty(shape)
    min_distance = np.empty(shape)
    twist = np.empty(shape)
    for k, product in enumerate(products):
        signs, margins, distances = [], [], []
        for c in product["centers"]:
            neighbors = x[..., c["neighbors"], :]
            incoming = x[..., c["partner"], :] - x[..., c["center"], :]
            vectors = neighbors - x[..., c["partner"], None, :]
            volume = np.sum(vectors[..., 0, :]*np.cross(vectors[..., 1, :], vectors[..., 2, :]), axis=-1)
            normal = np.cross(neighbors[..., 1, :]-neighbors[..., 0, :],
                              neighbors[..., 2, :]-neighbors[..., 0, :])
            denom = np.linalg.norm(normal, axis=-1)*np.linalg.norm(incoming, axis=-1)
            margin = np.divide(np.abs(np.sum(normal*incoming, axis=-1)), denom,
                               out=np.zeros_like(denom), where=denom > 1e-12)
            signs.append(volume*c["expected_sign"] > 1e-8)
            margins.append(margin)
            distances.append(np.linalg.norm(incoming, axis=-1))
        signs_match[..., k] = np.logical_and.reduce(signs)
        face_margin[..., k] = np.minimum.reduce(margins)
        max_distance[..., k] = np.maximum.reduce(distances)
        min_distance[..., k] = np.minimum.reduce(distances)
        a, b = INDEX["1:C5"], INDEX["1:C6"]
        c, d = ((INDEX["2:C6"], INDEX["2:C5"]) if product["family"] == "syn"
                else (INDEX["2:C5"], INDEX["2:C6"]))
        twist[..., k] = _torsion(x[..., a, :], x[..., b, :], x[..., c, :], x[..., d, :])
    return {"signs_match": signs_match, "face_margin": face_margin,
            "max_forming_distance_ang": max_distance, "min_forming_distance_ang": min_distance,
            "mapped_twist_deg": twist}


def eligible(f, distance_ang=4.0, twist_deg=45.0, face_margin=0.25):
    """Boolean compatible approach, never an absolute probability.

    Both proposed C-C bonds must be <= the cutoff, with no proposed distance
    below 2.5 A (grossly overlapping/already bonded reactants are not counted).
    The normal-approach margin avoids nearly coplanar/edge-on face assignments.
    """
    return (f["signs_match"] & (f["face_margin"] >= face_margin)
            & (f["max_forming_distance_ang"] <= distance_ang)
            & (f["min_forming_distance_ang"] >= 2.5)
            & (np.abs(f["mapped_twist_deg"]) <= twist_deg))


def planar_reactant_audit(products=None):
    """Independent coverage check using planar precursors, not product fixtures.

    Four proper-rotation face combinations for each C5=C6 pairing. These ideal
    approaches have 3.4 A forming distances, zero mapped twist, and normal
    incidence. Every connectivity family must recognize all four face products.
    This checks a necessary suprafacial mapping condition, not photophysics.
    """
    products = catalog() if products is None else products
    base = np.array([[-0.7,1.2,0], [0,0,0], [1.4,0,0],
                     [-0.7,-1.2,0], [2.1,-0.8,0], [2.1,1.2,0]], dtype=float)
    cases, family_pass = [], {}
    for family in ("syn", "anti"):
        observed = set()
        for first in (-1, 1):
            for second in (-1, 1):
                a = base * [1, first, first]
                b = base * [1, second, second]
                if family == "anti":
                    b = (b-[0.7,0,0])*[-1,-1,1]+[0.7,0,0]
                b += [0,0,3.4]
                x = np.concatenate([a,b])
                accepted = eligible(features(x, products))
                matched = [p["id"] for p, ok in zip(products, accepted)
                           if ok and p["family"] == family]
                # Cis/trans is the C5 methyl relationship to the cyclobutane
                # plane, independently of R/S assignment or product templates.
                # These planar examples have the ring in the xz plane.
                methyl_sides = [x[INDEX[f"{e}:C7"], 1] - x[INDEX[f"{e}:C5"], 1]
                                for e in (1, 2)]
                relationship = "cis" if np.prod(methyl_sides) > 0 else "trans"
                relationship_passed = len(matched) == 1 and next(
                    p["relationship"] for p in products if p["id"] == matched[0]
                ) == relationship
                observed.update(matched)
                cases.append({"family":family, "face_rotations":[first,second],
                              "matched_products":matched, "unique":len(matched)==1,
                              "methyl_relationship":relationship,
                              "relationship_passed":relationship_passed})
        expected = {p["id"] for p in products if p["family"] == family}
        family_pass[family] = observed == expected and all(
            c["unique"] and c["relationship_passed"] for c in cases if c["family"] == family)
    return {"passed":all(family_pass.values()), "family_pass":family_pass, "cases":cases}
