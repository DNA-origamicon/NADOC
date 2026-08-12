"""Read-only current/candidate evidence for molecular placement review.

The candidate is intentionally expressed as transient ``NucleotideTransform`` records on an
in-memory ``Design`` clone. Production placement functions and the active design are never
modified. The initial provider is the already-existing raw geometric (Bezier) placement: it
meaningfully contrasts calibrated 1xT residues and is identical for longer runs, which already
use that baseline.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.atomistic import build_atomistic_model, atomistic_to_json
from backend.core.atomistic_validation import (
    BACKBONE_STRETCH_NM,
    CLASH_NM,
    COVALENT_MAX_NM,
    _bond_class,
    _find_clashes,
)
from backend.core.models import Design, NucleotideTransform
from backend.core.ring_piercing import piercing_report

SCHEMA = "nadoc.molecular-placement-audit.v1"
PROVIDER_ID = "geometric-baseline-v1"
DISPLACEMENT_EPS_NM = 1e-6


def _transform_matrix(transform: NucleotideTransform | None) -> np.ndarray:
    if transform is None:
        return np.eye(4)
    rotation = Rotation.from_quat(transform.rotation).as_matrix()
    pivot = np.asarray(transform.pivot, dtype=float)
    translation = np.asarray(transform.translation, dtype=float)
    out = np.eye(4)
    out[:3, :3] = rotation
    out[:3, 3] = pivot - rotation @ pivot + translation
    return out


def _frame_matrix(center, rotation) -> np.ndarray:
    out = np.eye(4)
    out[:3, :3] = np.asarray(rotation, dtype=float)
    out[:3, 3] = np.asarray(center, dtype=float)
    return out


def geometric_baseline_design(
    design: Design, placement_records: list[dict]
) -> Design:
    """Return a clone whose extra residues display at the raw geometric baseline.

    Existing authored transforms are preserved as world-space deltas and composed after the
    alternative native frame. Longer insert runs are unchanged because their current native
    frame already is the geometric baseline.
    """
    existing = {t.target_key(): t for t in design.nucleotide_transforms}
    replaced_keys = {
        ("extra_base", row["crossover_id"], row["extra_base_k"])
        for row in placement_records
    }
    transforms = [
        t for t in design.nucleotide_transforms if t.target_key() not in replaced_keys
    ]
    for row in placement_records:
        key = ("extra_base", row["crossover_id"], row["extra_base_k"])
        authored = _transform_matrix(existing.get(key))
        current_frame = _frame_matrix(row["center"], row["frame_rotation"])
        target_frame = _frame_matrix(
            row["geometric_center"], row["source_frame_rotation"]
        )
        delta = authored @ target_frame @ np.linalg.inv(current_frame)
        transforms.append(
            NucleotideTransform(
                id=(
                    f"audit-geometric:{row['crossover_id']}:"
                    f"{row['extra_base_k']}"
                ),
                kind="extra_base",
                crossover_id=row["crossover_id"],
                extra_base_k=row["extra_base_k"],
                pivot=[0.0, 0.0, 0.0],
                translation=delta[:3, 3].tolist(),
                rotation=Rotation.from_matrix(delta[:3, :3]).as_quat().tolist(),
            )
        )
    return design.copy_with(nucleotide_transforms=transforms)


def _positions(model) -> np.ndarray:
    return np.asarray([[a.x, a.y, a.z] for a in model.atoms], dtype=float)


def _bond_metrics(model, positions: np.ndarray) -> dict:
    rows = []
    max_len = 0.0
    for i, j in model.bonds:
        length = float(np.linalg.norm(positions[i] - positions[j]))
        max_len = max(max_len, length)
        atom_a, atom_b = model.atoms[i], model.atoms[j]
        cls = _bond_class(atom_a, atom_b)
        limit = (
            BACKBONE_STRETCH_NM
            if cls in {"backbone", "bridge"}
            else COVALENT_MAX_NM
        )
        if length > limit:
            rows.append(
                {
                    "serials": [i, j],
                    "names": [atom_a.name, atom_b.name],
                    "class": cls,
                    "length_nm": round(length, 5),
                    "limit_nm": limit,
                }
            )
    rows.sort(key=lambda row: row["length_nm"], reverse=True)
    return {
        "max_length_nm": round(max_len, 5),
        "n_overstretched": len(rows),
        "overstretched": rows[:200],
    }


def _model_diagnostics(design: Design, model) -> dict:
    pos = _positions(model)
    finite = np.isfinite(pos).all(axis=1)
    clashes = _find_clashes(pos, finite, model.bonds, CLASH_NM, 200)
    return {
        "piercing": piercing_report(design, model=model),
        "bonds": _bond_metrics(model, pos),
        "clash_threshold_nm": CLASH_NM,
        "n_clashes": len(clashes),
        "clashes": clashes,
    }


def _affected_serials(current, candidate, current_diag, candidate_diag) -> tuple[list[int], dict]:
    current_pos = _positions(current)
    candidate_pos = _positions(candidate)
    if current_pos.shape != candidate_pos.shape:
        raise ValueError("audit candidate changed atom identity/count")
    delta = np.linalg.norm(candidate_pos - current_pos, axis=1)
    affected = set(np.where(delta > DISPLACEMENT_EPS_NM)[0].tolist())

    for diag in (current_diag, candidate_diag):
        for hit in diag["piercing"]["pierced"]:
            affected.update(hit["bond_serials"])
            affected.update(hit["ring_serials"])
        for hit in diag["bonds"]["overstretched"]:
            affected.update(hit["serials"])
        for hit in diag["clashes"]:
            affected.update(hit["serials"])
    moved = delta[delta > DISPLACEMENT_EPS_NM]
    displacement = {
        "n_displaced": int(moved.size),
        "max_nm": round(float(moved.max()), 6) if moved.size else 0.0,
        "rms_nm": round(float(math.sqrt(np.mean(moved * moved))), 6)
        if moved.size
        else 0.0,
        "vectors": [
            {
                "serial": int(serial),
                "from": current_pos[serial].round(6).tolist(),
                "to": candidate_pos[serial].round(6).tolist(),
                "distance_nm": round(float(delta[serial]), 6),
            }
            for serial in np.where(delta > DISPLACEMENT_EPS_NM)[0]
        ],
    }
    return sorted(affected), displacement


def _defect_serials(diagnostics: dict) -> list[int]:
    """Exact detector atoms for ring-piercing/clash focus views."""
    serials: set[int] = set()
    for hit in diagnostics["piercing"]["pierced"]:
        serials.update(hit["bond_serials"])
        serials.update(hit["ring_serials"])
    for hit in diagnostics["clashes"]:
        serials.update(hit["serials"])
    return sorted(serials)


def build_molecular_placement_audit(
    design: Design, *, nuc_frame_override=None, measured_positioning: bool = True
) -> dict:
    """Build the isolated current/geometric-baseline comparison bundle."""
    placement_records: list[dict] = []
    current = build_atomistic_model(
        design,
        nuc_frame_override=nuc_frame_override,
        fast_bridges=True,
        measured_positioning=measured_positioning,
        _extra_base_placement_sink=placement_records,
    )
    candidate_design = geometric_baseline_design(design, placement_records)
    candidate = build_atomistic_model(
        candidate_design,
        nuc_frame_override=nuc_frame_override,
        fast_bridges=True,
        measured_positioning=measured_positioning,
    )
    if current.bonds != candidate.bonds:
        raise ValueError("audit candidate changed bond topology")

    current_diag = _model_diagnostics(design, current)
    candidate_diag = _model_diagnostics(candidate_design, candidate)
    affected, displacement = _affected_serials(
        current, candidate, current_diag, candidate_diag
    )
    return {
        "schema": SCHEMA,
        "read_only": True,
        "provider": {
            "id": PROVIDER_ID,
            "label": "Raw geometric baseline",
            "description": (
                "Removes the calibrated one-residue local pose. Longer insert runs "
                "already use this geometric baseline and therefore do not move."
            ),
            "not_authorized_for_production": True,
        },
        "current_design": design.model_dump(mode="json"),
        "candidate_design": candidate_design.model_dump(mode="json"),
        "current": {**atomistic_to_json(current), "diagnostics": current_diag},
        "candidate": {
            **atomistic_to_json(candidate),
            "diagnostics": candidate_diag,
        },
        "affected_atom_serials": affected,
        "defect_atom_serials": {
            "current": _defect_serials(current_diag),
            "candidate": _defect_serials(candidate_diag),
        },
        "displacement": displacement,
    }
