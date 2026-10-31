"""Isolated diagnostic for direct, paired fine mrDNA particles.

No production importer uses this module. This is not a decoder for coarse,
interpolated, loop-copy, or ssDNA sites. It measures seed-to-frame motion in the
same particle convention on both sides; callers choose the CG or atomistic
reference point to transport. Inputs and the native design remain unchanged.
"""

from __future__ import annotations

import numpy as np


def _frame(tangent, orientation_x):
    tangent = np.asarray(tangent, dtype=float).copy()
    norm = np.linalg.norm(tangent)
    if norm <= 1e-9:
        raise ValueError("Degenerate fine particle tangent")
    z = tangent / norm
    x = np.asarray(orientation_x, dtype=float) - z * np.dot(z, orientation_x)
    norm = np.linalg.norm(x)
    if norm <= 1e-9:
        raise ValueError("Degenerate fine orientation particle")
    x /= norm
    return np.column_stack((x, np.cross(z, x), z))


def paired_particle_motion(
    manifest,
    seed_positions_nm,
    seed_orientations,
    atom_names,
    final_positions_nm,
    *,
    initial_particle_positions_nm=None,
):
    """Return (seed center, final center, rotation) per paired (helix, bp).

    mrDNA's list reader seeds the DNA contour at the paired input midpoint and
    its O particle along frame x. A raw frame built from that midpoint contour
    must be compared to the same raw convention after motion. NADOC's native
    O5' midpoint and mrDNA's separate oxDNA Rz(90°) backmapper are not inputs.

    The final frame must already be unwrapped and aligned by the caller. NAS
    sites are intentionally omitted; unsupported DNA bindings refuse explicitly.
    """
    source = np.asarray(seed_positions_nm, dtype=float)
    final = np.asarray(final_positions_nm, dtype=float)
    initial = (
        None
        if initial_particle_positions_nm is None
        else np.asarray(initial_particle_positions_nm, dtype=float)
    )
    if initial is not None and (
        initial.shape != final.shape or not np.isfinite(initial).all()
    ):
        raise ValueError("Initial and final particle arrays must be finite and match")
    orientations = np.asarray(seed_orientations, dtype=float)
    if not np.isfinite(source).all() or not np.isfinite(final).all():
        raise ValueError("Nonfinite particle coordinates")
    records = {record.identity.key(): record for record in manifest.records}
    sites = {}
    for record in manifest.records:
        bindings = record.particle_bindings
        if not any(b.particle_kind == "DNA" for b in bindings):
            continue
        if (
            len(bindings) != 1
            or bindings[0].weight != 1
            or record.pair not in records
            or record.render.copy != 0
            or not isinstance(record.render.bp_index, int)
        ):
            raise ValueError("Candidate requires direct paired fine DNA sites")
        mate = records[record.pair]
        binding = bindings[0]
        index = binding.particle_index
        if (
            len(mate.particle_bindings) != 1
            or mate.particle_bindings[0].particle_index != index
        ):
            raise ValueError("Paired nucleotides do not share one DNA particle")
        if (
            index < 0
            or index + 1 >= len(final)
            or len(atom_names) != len(final)
            or atom_names[index] != "DNA"
            or atom_names[index + 1] != "O"
        ):
            raise ValueError(
                "Candidate requires a DNA particle followed by its O particle"
            )
        a, b = record.model_nucleotide_index, mate.model_nucleotide_index
        center = 0.5 * (source[a] + source[b])
        x = orientations[a, :, 0]
        if not np.allclose(x, orientations[b, :, 0], atol=1e-6, rtol=0):
            raise ValueError("Paired input orientation x axes disagree")
        key = (record.render.helix_id, record.render.bp_index)
        if key in sites and sites[key][0] != index:
            raise ValueError("Ambiguous particle identity at paired site")
        sites[key] = (index, center, x)

    result = {}
    for key, (index, center, x) in sites.items():
        bps = sorted(bp for hid, bp in sites if hid == key[0])
        if len(bps) < 2:
            raise ValueError("Candidate requires two paired sites on each helix")
        at = bps.index(key[1])
        lo = sites[(key[0], bps[max(0, at - 1)])]
        hi = sites[(key[0], bps[min(len(bps) - 1, at + 1)])]
        if initial is not None:
            # Measure motion between the actual written/read particle frames.
            # PDB quantization is not physical motion of the native reference.
            indices = [lo[0], hi[0], index, index + 1]
            if np.array_equal(initial[indices], final[indices]):
                result[key] = (center.copy(), center.copy(), np.eye(3))
                continue
            before = _frame(
                initial[hi[0]] - initial[lo[0]], initial[index + 1] - initial[index]
            )
        else:
            before = _frame(hi[1] - lo[1], x)
        after = _frame(final[hi[0]] - final[lo[0]], final[index + 1] - final[index])
        rotation = after @ before.T
        target = final[index].copy()
        if initial is not None:
            target += rotation @ (center - initial[index])
        result[key] = (center.copy(), target, rotation)
    return result


def rigid_atom_transport(reference, motion):
    """Transport an existing model only when every site shares one rigid motion.

    Return None for nonrigid motion so callers must explicitly reconstruct it.
    Re-solving native linker atoms under a uniform pose would invent deformation.
    The numerical comparison is for algebraic roundoff, not a molecular tolerance.
    """
    from copy import deepcopy

    values = list(motion.values())
    if not values:
        raise ValueError("No paired particle motion")
    before, after, rotation = values[0]
    translation = after - rotation @ before
    for p, q, r in values:
        if not (
            np.allclose(r, rotation, atol=1e-11, rtol=0)
            and np.allclose(q - r @ p, translation, atol=1e-11, rtol=0)
        ):
            return None
    if any((a.helix_id, a.bp_index) not in motion for a in reference.atoms):
        raise ValueError("Reference contains an unsupported atom site")
    result = deepcopy(reference)
    if np.array_equal(rotation, np.eye(3)) and np.array_equal(translation, np.zeros(3)):
        return result
    for atom in result.atoms:
        atom.x, atom.y, atom.z = (
            rotation @ np.array([atom.x, atom.y, atom.z]) + translation
        ).tolist()
    return result


def transport_point(motion, point):
    """Transport any reference point using one measured local particle motion."""
    before, after, rotation = motion
    return after + rotation @ (np.asarray(point, dtype=float) - before)
