"""Read-only A/B evidence for molecular placement review.

For 2xT, both panels show the promoted v7 production default; there is no pending
placement proposal. For 1xT, the historical production/geometric comparison remains.
The active design is never modified by this diagnostic route.
"""

from __future__ import annotations

import copy
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
PROVIDER_ID = "crossover-insert-default-v2"
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
    """Return a clone carrying the historical read-only 1xT geometric baseline.

    Existing authored transforms are preserved as world-space deltas and composed after the
    alternative native frame. Two-base production/legacy comparison is built directly by
    :func:`build_molecular_placement_audit`; runs longer than one are unchanged here.
    """
    # After v6 promotion, 2xT is production geometry and is compared by building
    # legacy/current atom feeds directly (see build_molecular_placement_audit). This
    # transform-only provider remains solely for the historical 1xT geometric A/B.
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
        target_frame = (
            _frame_matrix(row["geometric_center"], row["source_frame_rotation"])
            if row["count"] == 1
            else current_frame
        )
        delta = authored @ target_frame @ np.linalg.inv(current_frame)
        transforms.append(NucleotideTransform(
            id=f"audit-geometric:{row['crossover_id']}:{row['extra_base_k']}",
            kind="extra_base",
            crossover_id=row["crossover_id"],
            extra_base_k=row["extra_base_k"],
            pivot=[0.0, 0.0, 0.0],
            translation=delta[:3, 3].tolist(),
            rotation=Rotation.from_matrix(delta[:3, :3]).as_quat().tolist(),
        ))
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
    raw_clashes = _find_clashes(pos, finite, model.bonds, CLASH_NM, 200)
    # Bridge atoms belonging to one crossover form a single covalent insert chain.
    # Some adjacent bridge bonds are implicit rather than present in model.bonds, so the
    # generic detector otherwise mislabels canonical 0.0707-nm C3'-P/O3'-O5'/P-C5'
    # contacts as nonbonded clashes. They are designed connectivity, not sterics.
    clashes = [
        hit for hit in raw_clashes
        if not (
            model.atoms[hit["serials"][0]].crossover_id is not None
            and model.atoms[hit["serials"][0]].crossover_id
            == model.atoms[hit["serials"][1]].crossover_id
        )
    ]
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


def _midpoint_constraint_planes(placement_records: list[dict]) -> list[dict]:
    """One audit annotation per reciprocal crossover pair, never a constraint.

    A reciprocal junction is represented by two adjacent crossover records. The shared
    plane passes through the midpoint between those two crossover centers and is normal
    to their mean helical axis. Unpaired records intentionally produce no plane.
    """
    by_crossover: dict[str, dict] = {}
    for row in placement_records:
        crossover_id = row["crossover_id"]
        if crossover_id in by_crossover:
            continue
        by_crossover[crossover_id] = {
            "crossover_id": crossover_id,
            "origin": np.asarray(row["midpoint_plane_origin"]).round(6).tolist(),
            "normal": np.asarray(row["midpoint_plane_normal"]).round(6).tolist(),
            "radius_nm": round(float(row["midpoint_plane_radius_nm"]), 6),
            "half_a": row["half_a"],
            "half_b": row["half_b"],
        }

    groups: dict[tuple[str, str], list[dict]] = {}
    for row in by_crossover.values():
        helix_pair = tuple(sorted((row["half_a"]["helix_id"], row["half_b"]["helix_id"])))
        row["midpoint_bp"] = 0.5 * (
            float(row["half_a"]["bp_index"]) + float(row["half_b"]["bp_index"])
        )
        groups.setdefault(helix_pair, []).append(row)

    planes: list[dict] = []
    for helix_pair, rows in groups.items():
        rows.sort(key=lambda row: row["midpoint_bp"])
        i = 0
        while i + 1 < len(rows):
            first, second = rows[i], rows[i + 1]
            # Reciprocal Holliday-junction crossovers occupy adjacent bp levels.
            # Do not invent a plane across unrelated junctions on the same helix pair.
            if abs(second["midpoint_bp"] - first["midpoint_bp"]) > 1.01:
                i += 1
                continue
            normal = np.asarray(first["normal"]) + np.asarray(second["normal"])
            if np.linalg.norm(normal) < 1e-9:
                normal = np.asarray(first["normal"])
            normal = normal / np.linalg.norm(normal)
            planes.append({
                "crossover_ids": [first["crossover_id"], second["crossover_id"]],
                "helix_ids": list(helix_pair),
                "bp_indices": [first["midpoint_bp"], second["midpoint_bp"]],
                "origin": (0.5 * (np.asarray(first["origin"]) + np.asarray(second["origin"]))).round(6).tolist(),
                "normal": normal.round(6).tolist(),
                "radius_nm": round(max(first["radius_nm"], second["radius_nm"]), 6),
            })
            i += 2
    return planes


def build_molecular_placement_audit(
    design: Design, *, nuc_frame_override=None, measured_positioning: bool = True
) -> dict:
    """Build the isolated production-reference/candidate comparison bundle."""
    placement_records: list[dict] = []
    current = build_atomistic_model(
        design,
        nuc_frame_override=nuc_frame_override,
        fast_bridges=True,
        measured_positioning=measured_positioning,
        _extra_base_placement_sink=placement_records,
    )
    has_two_base = any(row["count"] == 2 for row in placement_records)
    candidate_design = design
    clearance_candidate = None
    if has_two_base:
        # v7 is the implemented production default. Keep both panels on the exact
        # production coordinates so the auditor never advertises a stale proposal.
        candidate = copy.deepcopy(current)
    else:
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
    planes = _midpoint_constraint_planes(placement_records)
    symmetric_authored_2xt = sorted({
        crossover_id
        for plane in planes
        for crossover_id in plane["crossover_ids"]
    })
    target_2xt = sorted({
        row["crossover_id"] for row in placement_records if row["count"] == 2
    })
    provider = {
        "id": PROVIDER_ID,
        "label": "Chemically oriented crossover inserts",
        "description": (
            "Compares 1xT with its raw geometric baseline and proposes an "
            "opposite-face, chemical-traversal-oriented Bezier arrangement for 2xT. "
            "Runs longer than two remain unchanged."
        ),
        "not_authorized_for_production": True,
    }
    if target_2xt:
        provider.update({
            "id": "reciprocal-phosphate-clearance-production-v7",
            "label": "Production v7 reciprocal phosphate clearance",
            "description": (
                "Production v7 applies equal/opposite sine-tapered clearance to "
                "colliding reciprocal phosphate linkers. The direction-local 2xT "
                "residue poses remain unchanged."
            ),
            "target_crossover_ids": target_2xt,
            "not_authorized_for_production": False,
            "promoted_to_production": True,
            "panel_labels": {"current": "Production v7", "candidate": "Production v7"},
            "panel_notes": {
                "current": "Active production geometry",
                "candidate": "No pending placement proposal",
            },
            "panel_representations": {
                "current": "ballstick",
                "candidate": "ballstick",
            },
        })
    def target_clashes(side: str) -> int:
        targets = set(target_2xt)
        if not targets:
            return 0
        atoms = (current if side == "current" else candidate).atoms
        diagnostics = current_diag if side == "current" else candidate_diag
        count = 0
        for hit in diagnostics["clashes"]:
            memberships = [atoms[i].crossover_id in targets for i in hit["serials"]]
            if any(memberships):
                count += 1
        return count
    def target_piercings(side: str) -> int:
        diagnostics = current_diag if side == "current" else candidate_diag
        targets = set(target_2xt)
        return sum(
            bool(set(hit.get("crossover_ids", ())) & targets)
            for hit in diagnostics["piercing"]["pierced"]
        )
    def target_overstretched(side: str) -> int:
        model = current if side == "current" else candidate
        diagnostics = current_diag if side == "current" else candidate_diag
        targets = set(target_2xt)
        return sum(
            any(model.atoms[i].crossover_id in targets for i in hit["serials"])
            for hit in diagnostics["bonds"]["overstretched"]
        )
    def plane_violations(side: str) -> list[dict]:
        model = current if side == "current" else candidate
        rows: list[dict] = []
        for plane in planes:
            origin = np.asarray(plane["origin"], dtype=float)
            normal = np.asarray(plane["normal"], dtype=float)
            for crossover_id in plane["crossover_ids"]:
                current_serials = [
                    a.serial for a in current.atoms if a.crossover_id == crossover_id
                ]
                if not current_serials:
                    continue
                current_signed = [
                    float(np.dot(_positions(current)[i] - origin, normal))
                    for i in current_serials
                ]
                expected_sign = 1.0 if float(np.mean(current_signed)) >= 0.0 else -1.0
                for atom in model.atoms:
                    if atom.crossover_id != crossover_id:
                        continue
                    position = np.array([atom.x, atom.y, atom.z], dtype=float)
                    signed = float(np.dot(position - origin, normal))
                    if expected_sign * signed < 0.0:
                        rows.append({
                            "serial": atom.serial,
                            "crossover_id": crossover_id,
                            "extra_base_k": atom.extra_base_k,
                            "atom_name": atom.name,
                            "signed_distance_nm": round(signed, 6),
                            "expected_side": "positive" if expected_sign > 0 else "negative",
                        })
        return rows
    current_plane_violations = plane_violations("current")
    candidate_plane_violations = plane_violations("candidate")
    def junction_bonds(side: str) -> dict:
        model = current if side == "current" else candidate
        positions = _positions(model)
        targets = set(symmetric_authored_2xt)
        rows = []
        by_strand: dict[str, list[float]] = {}
        for i, j in model.bonds:
            a, b = model.atoms[i], model.atoms[j]
            a_target = a.crossover_id in targets
            b_target = b.crossover_id in targets
            if a_target == b_target:
                continue
            length = float(np.linalg.norm(positions[i] - positions[j]))
            strand_id = a.strand_id or b.strand_id or "unknown"
            by_strand.setdefault(strand_id, []).append(length)
            rows.append({
                "serials": [i, j], "strand_id": strand_id,
                "length_nm": round(length, 6),
            })
        means = [float(np.mean(values)) for values in by_strand.values() if values]
        return {
            "bonds": rows,
            "max_length_nm": round(max((r["length_nm"] for r in rows), default=0.0), 6),
            "strand_mean_nm": {
                strand: round(float(np.mean(values)), 6)
                for strand, values in by_strand.items()
            },
            "strand_mean_imbalance_nm": round(max(means) - min(means), 6) if means else 0.0,
        }
    return {
        "schema": SCHEMA,
        "read_only": True,
        "provider": provider,
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
        "midpoint_constraint_planes": planes,
        "midpoint_plane_violations": {
            "current": current_plane_violations,
            "candidate": candidate_plane_violations,
        },
        "proposal_validation": {
            "target_external_clashes": {
                "current": target_clashes("current"),
                "candidate": target_clashes("candidate"),
            },
            "target_ring_piercings": {
                "current": target_piercings("current"),
                "candidate": target_piercings("candidate"),
            },
            "target_overstretched_bonds": {
                "current": target_overstretched("current"),
                "candidate": target_overstretched("candidate"),
            },
            "constraint": "target residue centers retain their current signed plane side",
            "junction_bonds": {
                "current": junction_bonds("current"),
                "candidate": junction_bonds("candidate"),
            },
            "clearance_candidate": clearance_candidate,
        } if symmetric_authored_2xt else None,
        "displacement": displacement,
    }
