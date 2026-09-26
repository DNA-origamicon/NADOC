"""Freeze the user-selected ordered isomer-comparison site without changing geometry."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.core.models import Design
from backend.core.atomistic import build_atomistic_model
from backend.core.base_keys import resolve_base_keys


def record(path):
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def main(path, root):
    raw = path.read_bytes()
    design = Design.from_json(raw.decode())
    if len(design.photoproduct_junctions) != 1:
        raise ValueError("Expected one explicitly selected source CPD")
    lesion = design.photoproduct_junctions[0]
    keys = [lesion.base_key_1, lesion.base_key_2]
    if lesion.patch_order == "base-key-2-first":
        keys.reverse()
    model = build_atomistic_model(design)
    resolved, errors = resolve_base_keys(
        design, keys, atomistic_model=model, require_atoms=True
    )
    if errors:
        raise ValueError(errors)
    bykey = {r.key: r for r in resolved}
    endpoints = [bykey[key] for key in keys]
    if any(e.base != "T" or not e.has_cpd_atoms for e in endpoints):
        raise ValueError("Target endpoints must both resolve to thymine with C5/C6")
    root.mkdir(parents=True, exist_ok=False)
    (root / "source.nadoc").write_bytes(raw)
    shutil.copy2(__file__, root / "executed_source.py")
    coords = [
        {name: (10 * np.asarray(x)).tolist() for name, x in e.atom_positions_nm.items()}
        for e in endpoints
    ]
    distances = {}
    for a, b in [("C5", "C5"), ("C6", "C6"), ("C5", "C6"), ("C6", "C5")]:
        distances[f"1:{a}--2:{b}"] = float(
            np.linalg.norm(np.asarray(coords[0][a]) - coords[1][b])
        )
    registry_path = Path("backend/data/forcefield/photoproduct_registry.json")
    registry = json.loads(registry_path.read_text())
    anti = next(p for p in registry["products"] if p["id"] == "tt-cpd-cis-anti-i")
    report = {
        "product_id": "tt-cpd-cis-anti-i",
        "status": "site_identity_frozen_candidate_geometry_pending",
        "simulation_ready": False,
        "source": record(path),
        "snapshot": record(root / "source.nadoc"),
        "source_lesion_id": lesion.id,
        "source_stereochemistry": lesion.stereochemistry,
        "ordered_base_keys": keys,
        "endpoints": [e.to_dict() for e in endpoints],
        "interstrand": endpoints[0].strand_id != endpoints[1].strand_id,
        "source_world_coordinates_angstrom": coords,
        "source_world_distances_angstrom": distances,
        "target_graph_delta": anti["graph_delta"],
        "registry": record(registry_path),
        "scope": "User-selected comparison site only. Source coordinates include live design transforms. No anti coordinate assignment or product topology has been created.",
        "next": "After core/sugar fitting, construct complete anti nucleotides at these exact ordered endpoints; audit backbone and sterics, generate same-frame A/B review artifact before app integration.",
    }
    (root / "site_manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    assert path.read_bytes() == raw
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "ordered_base_keys",
                    "endpoints",
                    "interstrand",
                    "source_world_distances_angstrom",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True)
    args = p.parse_args()
    main(args.source, args.root)
