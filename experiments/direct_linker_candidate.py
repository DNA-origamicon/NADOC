"""Isolated, unapproved preservation of a relocated overhang's native linker.

No application path imports this module. A caller must supply the exact unbound
reference and the driven overhang explicitly. Only the diagnostic model receives
atom changes; neither design is modified and no candidate coordinates are saved
to topology. Production display/export/simulation cannot select this policy.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np

RING = ("C1'", "C2'", "C3'", "C4'", "O4'", "C5'")


def positions(atoms):
    return np.asarray([[a.x, a.y, a.z] for a in atoms], dtype=float)


def root_residues(design, overhang_id):
    """Return the actual strand-ordered O3′ and P residues, plus the moving side."""
    hits = [(s, i, d) for s in design.strands for i, d in enumerate(s.domains)
            if d.overhang_id == overhang_id]
    if len(hits) != 1:
        raise ValueError("Candidate requires one unambiguous overhang domain")
    strand, index, domain = hits[0]
    if len(strand.domains) == 1:
        return None
    if index == 0:
        left, right, moving = domain, strand.domains[1], 0
    elif index == len(strand.domains) - 1:
        left, right, moving = strand.domains[index - 1], domain, 1
    else:
        raise ValueError("Candidate supports terminal overhangs only")
    return ((strand.id, left.helix_id, left.end_bp, left.direction.value),
            (strand.id, right.helix_id, right.start_bp, right.direction.value), moving)


def residue(atoms, key):
    hits = [a for a in atoms if (a.strand_id, a.helix_id, a.bp_index, a.direction) == key]
    result = {a.name: a for a in hits}
    if len(result) != len(hits) or any(a.copy_k not in (None, 0) for a in hits):
        raise ValueError("Candidate does not support repeated/loop-copy root atoms")
    if not set(RING) <= result.keys():
        raise ValueError("Candidate requires a complete native sugar residue")
    return result


def _frame(atoms, anchor, first, second):
    origin, p, q = positions([atoms[name] for name in (anchor, first, second)])
    x, y = p - origin, q - origin
    x /= np.linalg.norm(x)
    y -= np.dot(y, x) * x
    y /= np.linalg.norm(y)
    frame = np.column_stack((x, y, np.cross(x, y)))
    if not np.isfinite(frame).all():
        raise ValueError("Candidate encountered a degenerate residue frame")
    return origin, frame


def residue_motion(before, after, *, phosphate):
    """Exact rigid transport anchored at the unmodified adjacent sugar atom.

    The native forward/reverse sugar templates differ in shape. They stay
    untouched. Anchoring at C3/C5 preserves C3–O3/C5–O5 length exactly, and the
    first axis preserves its angle to C4. Other adjacent angles must be measured
    in the A/B evidence; this does not claim the whole residue moved rigidly.
    """
    names = ("C5'", "C4'", "O4'") if phosphate else ("C3'", "C4'", "C2'")
    origin, basis = _frame(before, *names)
    target, axes = _frame(after, *names)
    rotation = axes @ basis.T
    return rotation, origin, target


def transport_linkers(atoms, design, reference_atoms, reference, overhang_ids):
    """Move only O3′ and the bonded P/OP1/OP2/O5′ group for each driven root."""
    changed = set()
    for oid in overhang_ids:
        old, new = root_residues(reference, oid), root_residues(design, oid)
        if old is None or new is None:
            if old != new:
                raise ValueError("Candidate lost or gained a covalent root")
            continue
        if old[2] != new[2]:
            raise ValueError("Candidate changed the overhang's terminal side")
        for side, names in enumerate((("O3'",), ("P", "OP1", "OP2", "O5'"))):
            before, after = residue(reference_atoms, old[side]), residue(atoms, new[side])
            rotation, origin, target = residue_motion(before, after, phosphate=side == 1)
            for name in names:
                a, b = before[name], after[name]
                if b.serial in changed:
                    raise ValueError("Overlapping candidate linker groups are unsupported")
                b.x, b.y, b.z = rotation @ (positions([a])[0] - origin) + target
                changed.add(b.serial)
    return changed


def candidate_model(design, reference, driven_ids, *, fast_bridges):
    """Build an isolated model; insert transport immediately before native poses.

    The temporary hook is local to this single-threaded diagnostic and restored
    on success or failure. The native builder still owns all remaining passes.
    Simulation overrides and arbitrary builder options are deliberately absent.
    """
    from backend.core.atomistic import build_atomistic_model
    from backend.core import deformation

    reference_model = build_atomistic_model(reference, fast_bridges=fast_bridges,
                                           apply_design_geometry=False)
    native_apply = deformation.apply_deformations_to_atoms

    def apply(atoms, current):
        transport_linkers(atoms, current, reference_model.atoms, reference, driven_ids)
        return native_apply(atoms, current)

    with patch.object(deformation, "apply_deformations_to_atoms", apply):
        return build_atomistic_model(design, fast_bridges=fast_bridges)


def root_endpoints(design, model, overhang_id):
    roots = root_residues(design, overhang_id)
    if roots is None:
        return None
    src, dst = residue(model.atoms, roots[0]), residue(model.atoms, roots[1])
    pair = (src["O3'"], dst["P"])
    i, j = (a.serial for a in pair)
    if (i, j) not in model.bonds and (j, i) not in model.bonds:
        raise ValueError("Candidate root endpoints are not covalently bonded")
    xyz = positions(pair)
    return {"serials": [i, j], "fixed": xyz[1 - roots[2]], "moving": xyz[roots[2]],
            "length_nm": float(np.linalg.norm(xyz[0] - xyz[1]))}


def fit_candidate(design, reference, driver_id, driven_ids, root_ids):
    """Existing rigid fitter, reading only isolated candidate atom models."""
    from backend.core.atomistic import build_atomistic_model
    from backend.core.direct_root_placement import fit_root_transform
    from backend.core.overhang_root_constraints import rotate_overhang_about

    moving, fixed, lengths = [], [], []
    for fast in (True, False):
        before = build_atomistic_model(reference, fast_bridges=fast)
        after = candidate_model(design, reference, driven_ids, fast_bridges=fast)
        for oid in root_ids:
            expected = root_endpoints(reference, before, oid)
            if expected is None:
                continue
            actual = root_endpoints(design, after, oid)
            moving.append(actual["moving"])
            fixed.append(actual["fixed"])
            lengths.append(expected["length_nm"])
    rotation, pivot, translation = fit_root_transform(moving, fixed, lengths)
    placed = design if np.array_equal(rotation, np.eye(3)) and not np.any(translation) else (
        rotate_overhang_about(design, driver_id, rotation, pivot,
                              translation=translation, materialize=False))
    for fast in (True, False):
        before = build_atomistic_model(reference, fast_bridges=fast)
        after = candidate_model(placed, reference, driven_ids, fast_bridges=fast)
        for oid in root_ids:
            expected = root_endpoints(reference, before, oid)
            if expected is not None and abs(root_endpoints(placed, after, oid)["length_nm"]
                                           - expected["length_nm"]) > 1e-8:
                raise ValueError("Candidate fit did not preserve the native root length")
    return placed
