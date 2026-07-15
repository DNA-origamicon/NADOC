"""Reorient an oxDNA-seeded atomistic model to shrink its solvation box.

WHY. ``build_namd_seed`` reconstructs a NAMD starting structure from an oxDNA relaxation
(``build_atomistic_model_from_cg_spline``) and recenters it, but does NOT reorient it. An
oxDNA-relaxed bundle sits at an arbitrary tilt in the coordinate frame, so its
AXIS-ALIGNED bounding box — which is what the solvation step pads and fills — is far larger
than the structure's true extent. Measured on 24hb_1xT: a tilted seed boxed to 49.5x28.9x19.9
nm (~3.4M atoms) vs 52.3x19.9x17.6 aligned (~2.3M) — a 1.49x solvent saving for the SAME
structure, purely from removing the tilt. This is legitimate packing efficiency, not
under-provisioning: the structure's real equilibrium envelope (including the wider,
extra-base-frayed bundle) is preserved — only the box orientation changes.

Aligns the longest principal axis to +z (the bundle-along-z convention, minimising the xy
cross-section the solvent box fills) via a proper rotation (det +1, never a reflection).
Recenters on the origin too. Physical-layer only: orientation is irrelevant to a boxed MD
run, so this never affects the science — only the atom count.
"""

from __future__ import annotations

import numpy as np


def reorient_to_principal_axes(model) -> None:
    """Rotate ``model``'s atoms in place so the longest principal axis is +z, centred.

    Pure geometric repacking of an MD seed — see module docstring. No-op on an empty model.
    """
    if not model.atoms:
        return
    P = np.asarray([[a.x, a.y, a.z] for a in model.atoms], dtype=float)
    P = P - P.mean(axis=0)

    # Principal axes, largest variance first (vt rows are sorted by singular value desc).
    _, _, vt = np.linalg.svd(P, full_matrices=False)
    # Map principal axes -> (x, y, z) with the LONGEST (vt[0]) onto z.
    R = np.vstack([vt[2], vt[1], vt[0]])          # rows: new x, y, z basis vectors
    if np.linalg.det(R) < 0:                        # keep it a rotation, not a reflection
        R[0] = -R[0]
    Pr = P @ R.T

    for a, (x, y, z) in zip(model.atoms, Pr):
        a.x, a.y, a.z = float(x), float(y), float(z)


def separate_coincident_atoms(model, *, min_sep: float = 0.03, nudge_to: float = 0.10) -> int:
    """Nudge apart heavy-atom pairs closer than ``min_sep`` nm (cg-spline backmap artifact).

    ``build_atomistic_model_from_cg_spline`` occasionally reconstructs two backbone atoms
    from different helices onto ~the same point (measured: one C5'-C5' pair at 0.046 A on
    24hb_2xT). A truly coincident heavy pair is an infinite VDW term the degeneracy gate
    (rightly) refuses before minimisation can help, so clear it here: push each such pair
    apart along its separation axis (a deterministic axis if exactly coincident) to
    ``nudge_to`` nm. Distances in nm (model units). Returns the number of pairs nudged.
    """
    import numpy as np
    from scipy.spatial import cKDTree

    heavy = [(i, a) for i, a in enumerate(model.atoms) if a.element != "H"]
    if not heavy:
        return 0
    idx = [i for i, _ in heavy]
    P = np.asarray([[model.atoms[i].x, model.atoms[i].y, model.atoms[i].z] for i in idx])
    pairs = cKDTree(P).query_pairs(r=min_sep, output_type="ndarray")
    n = 0
    for a, b in pairs:
        ia, ib = idx[a], idx[b]
        pa = np.array([model.atoms[ia].x, model.atoms[ia].y, model.atoms[ia].z])
        pb = np.array([model.atoms[ib].x, model.atoms[ib].y, model.atoms[ib].z])
        d = pb - pa
        dist = float(np.linalg.norm(d))
        u = d / dist if dist > 1e-6 else np.array([1.0, 0.0, 0.0])
        shift = (nudge_to - dist) * 0.5 * u
        model.atoms[ia].x, model.atoms[ia].y, model.atoms[ia].z = (pa - shift).tolist()
        model.atoms[ib].x, model.atoms[ib].y, model.atoms[ib].z = (pb + shift).tolist()
        n += 1
    return n


def oxdna_extra_base_override(design, relaxed_conf, design_ref):
    """`xb_pos_override` (keyed ``(crossover_id, k)``, NANOMETRES) from an oxDNA relax.

    Reads the relaxed conf, PBC-unwraps + Kabsch-aligns it to the design reference (so the
    extra-base coords land in the design's own frame), and returns the aligned extra-base
    backbone positions. Units are nm — the SAME units build_atomistic_model works in, so the
    override goes in verbatim (NO nm->A scaling; an earlier x10 exploded the box).
    """
    import numpy as np
    from pathlib import Path
    from backend.physics.oxdna_interface import (
        OXDNA_LENGTH_UNIT, _XB_SENTINEL, _build_unwrap_adjacency,
        read_configuration_full, unwrap_align_to_reference)
    box = None
    for line in Path(relaxed_conf).read_text().splitlines():
        if line.startswith("b ="):
            box = np.array([float(x) for x in line.split()[2:5]]) * OXDNA_LENGTH_UNIT
            break
    if box is None:
        raise ValueError(f"no box header in {relaxed_conf}")
    relax = read_configuration_full(relaxed_conf, design, include_extra_bases=True, copies=True)
    ref = read_configuration_full(design_ref, design, include_extra_bases=True, copies=True)
    adj = _build_unwrap_adjacency(relax, design)
    aligned = unwrap_align_to_reference(relax, ref, design, box, align=True, rotate=True, adj=adj)
    return {(k[1], k[2]): np.asarray(v["backbone_position"])
            for k, v in aligned.items() if k[0] == _XB_SENTINEL}


def build_ideal_duplex_seeded_model(design, relaxed_conf, design_ref):
    """Atomistic model: IDEAL B-DNA duplex + crossover extra bases at their oxDNA-relaxed
    (declashed) positions. Unlike the cg-spline full backmap, the duplex is the standard
    clean build (~1560 clashes, not 12k), so it does not blow up NPT / distort base rings —
    only the extra bases are moved off their clashing geometric-guess positions. The soft
    declash ladder then heals the mild residual extra-base stretches, and production runs
    4 fs. Reorients + clears any backmap coincidences.
    """
    from backend.core.atomistic import build_atomistic_model
    ov = oxdna_extra_base_override(design, relaxed_conf, design_ref)
    m = build_atomistic_model(design, xb_pos_override=ov or None)
    reorient_to_principal_axes(m)
    separate_coincident_atoms(m)
    return m
