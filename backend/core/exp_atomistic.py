"""All-DNA-atom Exp pilot and atom-derived NAMD Full display transport."""

from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np

from backend.core.exp_regression import FEATURE_NAMES, predict_positions

MODEL_PATH = Path(__file__).resolve().parents[1] / "data/exp/strain_atoms_v1.json"
SCHEMA = "allatom-bundle-strain-v1"
RING_NAMES = {"N9", "C8", "N7", "C5", "C6", "N1", "C2", "N3", "C4"}
DNA_NAMES = {"ADE", "THY", "GUA", "CYT"}


def psf_dna_atoms(stream):
    """Return physical file indices and exact (segment,residue,atom) identities."""
    for line in stream:
        if "!NATOM" not in line:
            continue
        total = int(line.split()[0])
        rows = []
        for i in range(total):
            fields = next(stream).split()
            if fields[3] in DNA_NAMES:
                rows.append((i, (fields[1], int(fields[2]), fields[4]), fields[3]))
        return total, rows
    raise ValueError("PSF has no atom block")


def native_atoms(design, *, include_bonds=False):
    from backend.core.atomistic import build_atomistic_model
    from backend.core.atomistic_to_nadoc import build_chain_map
    from backend.core.namd_topology import build_charmm_psfgen_topology

    heavy = build_atomistic_model(design)
    chain_map = build_chain_map(heavy)
    native = build_charmm_psfgen_topology(design, atomistic_model=heavy)
    segment_map = {s["segid"]: s["chain_id"] for s in native.metadata["segments"]}
    total, rows = psf_dna_atoms(io.StringIO(native.psf_text))
    coords = (
        np.array(
            [
                [float(line[30:38]), float(line[38:46]), float(line[46:54])]
                for line in native.pdb_text.splitlines()
                if line.startswith(("ATOM  ", "HETATM"))
            ]
        )
        / 10
    )
    if len(coords) != total:
        raise ValueError("Native PSF/PDB count mismatch")
    identities = [row[1] for row in rows]
    keys, residue_index, key_index = [], [], {}
    for seg, resid, _ in identities:
        key = tuple(chain_map[(segment_map[seg], resid)])
        if key not in key_index:
            key_index[key] = len(keys)
            keys.append(key)
        residue_index.append(key_index[key])
    result = {
        "positions_nm": coords[[r[0] for r in rows]],
        "identities": identities,
        "names": [a[2] for a in identities],
        "elements": [a[2][0] for a in identities],
        "keys": keys,
        "residue_index": np.asarray(residue_index, dtype=int),
    }

    if include_bonds:
        from backend.core.exp_local import psf_block

        bonds = psf_block(native.psf_text, "!NBOND", 2)
        index_map = np.full(total, -1, dtype=int)
        index_map[[r[0] for r in rows]] = np.arange(len(rows))
        mapped = index_map[bonds]
        result["bonds"] = mapped[(mapped >= 0).all(axis=1)]
        from backend.core.exp_local_constraints import inter_angles

        all_residues = np.full(total, -1, dtype=int)
        all_residues[[r[0] for r in rows]] = result["residue_index"]
        angles, cosine = inter_angles(native.psf_text, all_residues)
        result["angle_indices"] = index_map[angles]
        result["angle_cos"] = cosine
    return result


def full_frame(positions, names, residue_index, keys):
    """Same measured-ring calculation and 12-float/site contract as NAMD Full."""
    from backend.core.md_base_frames import measured_base_frames

    residues = [{} for _ in keys]
    for i, (name, residue) in enumerate(zip(names, residue_index)):
        residues[int(residue)][name] = i
    anchors, c1, rings = [], [], []
    for residue in residues:
        anchors.append(residue.get("P", residue.get("O5'")))
        c1.append(residue.get("C1'"))
        rings.append([i for name, i in residue.items() if name in RING_NAMES])
    if any(i is None for i in anchors + c1) or any(len(r) < 5 for r in rings):
        raise ValueError("Incomplete DNA atoms for a Full display frame")
    anchors = np.array(anchors)
    groups = []
    for size in sorted({len(r) for r in rings}):
        rows = np.array([i for i, r in enumerate(rings) if len(r) == size])
        groups.append((rows, np.array([rings[i] for i in rows])))
    centers, normals = measured_base_frames(
        positions, anchors, groups, positions[anchors], None, None
    )
    inward = positions[c1] - positions[anchors]
    length = np.linalg.norm(inward, axis=1, keepdims=True)
    if np.any(length < 1e-8):
        raise ValueError("Degenerate predicted nucleotide frame")
    frame = np.column_stack([positions[anchors], inward / length, normals, centers])
    if not np.isfinite(frame).all():
        raise ValueError("Non-finite predicted Full frame")
    return frame.reshape(-1).tolist()


def load_adapter(path=MODEL_PATH):
    if not path.exists():
        return None, None
    model = json.loads(path.read_text())
    if model["feature_schema"] != SCHEMA or model["features"] != FEATURE_NAMES:
        raise ValueError("Unsupported atomistic Exp model")
    coefficients = np.asarray(model["coefficients"])
    if coefficients.shape != (6,) or not np.isfinite(coefficients).all():
        raise ValueError("Invalid atomistic Exp weights")

    def predict(design, progress, cancel):
        progress(0.05, "Building all DNA atoms, including hydrogens")
        native = native_atoms(design)
        progress(0.6, "Predicting each DNA atom")
        positions = predict_positions(native["positions_nm"], coefficients)
        progress(0.85, "Deriving the Full display from predicted atoms")
        frame = full_frame(
            positions, native["names"], native["residue_index"], native["keys"]
        )
        label = (
            "0×T all-atom strain pilot; global modes, not local atomistic equilibration"
        )
        if any(c.extra_bases for c in design.crossovers):
            label += "; extra bases are outside training coverage"
        return {
            "positions_nm": positions.tolist(),
            "label": label,
            "atoms": {
                "names": native["names"],
                "elements": native["elements"],
                "residue_index": native["residue_index"].tolist(),
                "keys": native["keys"],
                "includes_hydrogens": True,
            },
            "full": {"keys": native["keys"], "frame": frame},
        }

    return predict, model["model_card"]
