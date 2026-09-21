"""Portable, review-only DNA context for all eight ordered TT-CPD isomers.

The CPD core is never mirrored or relaxed here. Other isomers retain their
stereochemically checked starting cores; sugars are rigidly transferred from
the preliminary cis-syn template. These are illustrative conformers, not new
coordinate templates for authoring or simulation.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.spatial.transform import Rotation

from backend.core.photoproduct_chemistry import (
    audit_product_chirality,
    load_chemical_definition,
)
from backend.core.photoproduct_registry import REGISTRY_PATH, photoproduct_registry

CORE_PATH = Path(__file__).resolve().parents[1] / "data/cpd_preview_cores.json"
BACKBONE_BONDS = [
    ("P", "O1P"),
    ("P", "O2P"),
    ("P", "O5'"),
    ("O5'", "C5'"),
    ("C5'", "C4'"),
    ("C4'", "O4'"),
    ("O4'", "C1'"),
    ("C1'", "C2'"),
    ("C2'", "C3'"),
    ("C3'", "C4'"),
    ("C3'", "O3'"),
    ("C1'", "N1"),
]
BACKBONE_NAMES = {name for pair in BACKBONE_BONDS for name in pair} - {"N1"}


def _frame(origin, along, toward):
    x = along - origin
    x /= np.linalg.norm(x)
    y = toward - origin
    y -= x * np.dot(x, y)
    y /= np.linalg.norm(y)
    return np.column_stack([x, y, np.cross(x, y)])


def _turn_sugar(coordinates, endpoint, degrees):
    prefix = f"{endpoint}:"
    origin = coordinates[prefix + "N1"]
    axis = coordinates[prefix + "C1'"] - origin
    rotation = Rotation.from_rotvec(axis / np.linalg.norm(axis) * np.deg2rad(degrees))
    return {
        k: rotation.apply(v - origin) + origin
        if k.startswith(prefix) and k.split(":")[1] in BACKBONE_NAMES
        else v
        for k, v in coordinates.items()
    }


def _declash_sugars(coordinates, bonds):
    """Choose illustrative glycosidic torsions; preserve the core and D-sugars."""
    keys = list(coordinates)
    adjacency = {k: set() for k in keys}
    for a, b in bonds:
        adjacency[a].add(b)
        adjacency[b].add(a)
    pairs = []
    for i, a in enumerate(keys):
        if a.split(":")[1].startswith("H"):
            continue
        excluded = adjacency[a] | {c for b in adjacency[a] for c in adjacency[b]}
        for j in range(i + 1, len(keys)):
            b = keys[j]
            if b in excluded or b.split(":")[1].startswith("H"):
                continue
            if not any(k.split(":")[1] in BACKBONE_NAMES for k in (a, b)):
                continue
            pairs.append((i, j))
    first, second = np.array(pairs).T

    def score(angles):
        moved = _turn_sugar(_turn_sugar(coordinates, 1, angles[0]), 2, angles[1])
        xyz = np.array([moved[k] for k in keys])
        distance = np.linalg.norm(xyz[first] - xyz[second], axis=1)
        # An approximate heavy-atom clearance only, not a force-field energy.
        return np.sum(np.maximum(2.8 - distance, 0) ** 2) + 0.002 * np.sum(
            1 - np.cos(np.deg2rad(angles))
        )

    start = min(
        ([a, b] for a in range(-180, 180, 30) for b in range(-180, 180, 30)), key=score
    )
    result = minimize(score, start, method="L-BFGS-B", bounds=[(-360, 360)] * 2)
    angles = (
        result.x if np.isfinite(result.fun) and result.fun <= score(start) else start
    )
    return _turn_sugar(_turn_sugar(coordinates, 1, angles[0]), 2, angles[1])


def build_isomer_previews():
    registry = photoproduct_registry()
    entries = [p for p in registry["products"] if p["product"] == "TT-CPD"]
    canonical = next(p for p in entries if p["stereochemistry"] == "cis-syn")
    asset = canonical["assets"]["coordinate_template"]
    template_path = REGISTRY_PATH.parent / asset["path"]
    raw = template_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != asset["sha256"]:
        raise ValueError("CPD preview attachment template hash mismatch")
    template = json.loads(raw)
    if template["units"] != "angstrom":
        raise ValueError("CPD preview requires angstrom coordinates")
    reference = {
        k: np.array(v, dtype=float) for k, v in template["coordinates"].items()
    }
    cores = json.loads(CORE_PATH.read_text())["products"]
    models = []
    for entry in entries:
        stereo = entry["stereochemistry"]
        definition = load_chemical_definition("TT-CPD", stereo)
        if stereo == "cis-syn":
            coordinates = {
                k: v.copy()
                for k, v in reference.items()
                if k.split(":")[1] in BACKBONE_NAMES
                or k
                in {
                    n
                    for pair in definition["precursor_local_connectivity"]["bonds"]
                    for n in pair
                }
            }
        else:
            core = {
                k: np.array(v) for k, v in cores[entry["id"]]["coordinates"].items()
            }
            coordinates = {k: v for k, v in core.items() if "CM" not in k}
            for endpoint in (1, 2):
                p = f"{endpoint}:"
                origin = reference[p + "N1"]
                source_frame = _frame(origin, reference[p + "C1'"], reference[p + "C2"])
                target_frame = _frame(core[p + "N1"], core[p + "CM"], core[p + "C2"])
                rotation = target_frame @ source_frame.T
                for name in sorted(BACKBONE_NAMES):
                    coordinates[p + name] = (
                        rotation @ (reference[p + name] - origin) + core[p + "N1"]
                    )
        bonds = {
            tuple(sorted(pair))
            for pair in definition["precursor_local_connectivity"]["bonds"]
            if all(k in coordinates for k in pair)
        }
        bonds.update(
            tuple(sorted((f"{e}:{a}", f"{e}:{b}")))
            for e in (1, 2)
            for a, b in BACKBONE_BONDS
        )
        crosslinks = [
            (b["atom_1"], b["atom_2"]) for b in definition["graph_delta"]["bonds_added"]
        ]
        bonds.update(tuple(sorted(pair)) for pair in crosslinks)
        if stereo != "cis-syn":
            coordinates = _declash_sugars(coordinates, bonds)
        # Same ordered cyclobutane frame for every thumbnail. Proper rotations
        # preserve all stereocenters and do not interchange endpoint identities.
        origin = (coordinates["1:C5"] + coordinates["1:C6"]) / 2
        toward = (coordinates["2:C5"] + coordinates["2:C6"]) / 2
        frame = _frame(origin, coordinates["1:C6"], toward)
        center = (origin + toward) / 2
        coordinates = {k: frame.T @ (v - center) for k, v in coordinates.items()}
        audit = audit_product_chirality(definition, coordinates)
        if not audit["passed"]:
            raise ValueError(f"Incorrect preview stereochemistry: {stereo}")
        source_key = entry["id"] + "-preview-definition"
        checks = [
            {
                "label": "Ordered CPD stereochemistry",
                "state": "pass",
                "value": "All four signed-volume checks match the registered definition",
                "evidence": source_key,
            }
        ]
        geometry = (
            "Preliminary cis-syn-I coordinate template; both sugar–phosphate attachments are included."
            if stereo == "cis-syn"
            else "Estimated conformer: stereochemically checked starting core with transferred D-deoxyribose/phosphate attachments and a coarse torsion clearance adjustment."
        )
        models.append(
            {
                "id": entry["id"],
                "label": entry["label"],
                "stereochemistry": stereo,
                "geometry": geometry
                + " Arrows show local 5′/3′ exit directions, not a fitted DNA strand. Attachment torsions are adjustable; strand fit and clashes are not validated.",
                "qualification": "Preliminary template"
                if stereo == "cis-syn"
                else "In development · estimate",
                "orderedC5": entry["structural_class"]["ordered_c5_configurations"],
                "atoms": [
                    {
                        "id": k,
                        "element": k.split(":")[1][0],
                        "position": v.tolist(),
                        "checks": [],
                        "endpoint": int(k[0]),
                        "region": "backbone"
                        if k.split(":")[1] in BACKBONE_NAMES
                        else "base",
                    }
                    for k, v in sorted(coordinates.items())
                ],
                "bonds": [
                    {
                        "id": "—".join(pair),
                        "atoms": list(pair),
                        "checks": [],
                        "crosslink": tuple(sorted(pair))
                        in {tuple(sorted(p)) for p in crosslinks},
                    }
                    for pair in sorted(bonds)
                ],
                "checks": checks
                + [
                    {
                        "label": "DNA context geometry",
                        "state": "pending",
                        "value": "One illustrative conformer, not a validated strand conformation or force-field model",
                        "evidence": "cpd-preview-method",
                    },
                    {
                        "label": "Core coordinate source",
                        "state": "pending",
                        "value": "Preliminary coordinate template"
                        if stereo == "cis-syn"
                        else "Portable starting cores; original candidate coordinate/map/graph hashes are recorded in the source asset",
                        "evidence": "cpd-preview-attachment-template"
                        if stereo == "cis-syn"
                        else "cpd-preview-cores",
                    },
                    {
                        "label": "Sugar–phosphate source",
                        "state": "pending",
                        "value": "Preliminary cis-syn template; D-sugars retained by proper rigid rotations only",
                        "evidence": "cpd-preview-attachment-template",
                    },
                ],
            }
        )
    return models


def attach_isomer_previews(payload):
    """Update only the illustration catalog; retain evidence timestamps/checks."""
    payload["isomers"] = build_isomer_previews()
    root = Path(__file__).resolve().parents[2]
    files = {"cpd-preview-method": Path(__file__), "cpd-preview-cores": CORE_PATH}
    entries = photoproduct_registry()["products"]
    for entry in entries:
        if entry["product"] == "TT-CPD":
            files[entry["id"] + "-preview-definition"] = (
                REGISTRY_PATH.parent / entry["assets"]["chemical_definition"]["path"]
            )
    canonical = next(e for e in entries if e["stereochemistry"] == "cis-syn")
    files["cpd-preview-attachment-template"] = (
        REGISTRY_PATH.parent / canonical["assets"]["coordinate_template"]["path"]
    )
    for key, path in files.items():
        payload["sources"][key] = {
            "file": str(path.relative_to(root)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    return payload
