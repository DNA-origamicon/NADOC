"""Conservative atomistic working set for fixed-centre loop rotations.

This selects from the native atomistic model; it neither places atoms nor changes
connectivity. Every potential contact and detector-visible bond/ring pair is
retained, as are two-hop bond exclusions and both attachment residues.
"""
from types import SimpleNamespace
import numpy as np
from backend.core.strand_loop_fit_scope import RotorPiercingIndex
from backend.core.ring_piercing import SEARCH_NM


def neighborhood(model, records, ri, required, moving, radii):
    xyz = np.array([[a.x, a.y, a.z] for a in model.atoms])
    movers = np.flatnonzero(moving)
    if not len(movers):
        return model, ri, moving, radii
    beads = np.array([records[ri[i]]['backbone_position'] for i in movers])
    radius = np.linalg.norm(xyz[movers] - beads, axis=1)
    lo = (beads - radius[:, None]).min(axis=0)
    hi = (beads + radius[:, None]).max(axis=0)
    # A rotated atom remains in its bead-centred sphere. Ring centres lie in
    # the convex hull of their atoms. Include the fixed endpoints of incident
    # bonds too: long stretched attachments must not escape the envelope.
    bonds = np.asarray(model.bonds, dtype=int).reshape(-1, 2)
    incident = bonds[moving[bonds].any(axis=1)].ravel()
    if len(incident):
        lo = np.minimum(lo, xyz[incident].min(axis=0))
        hi = np.maximum(hi, xyz[incident].max(axis=0))
    margin = max(SEARCH_NM, 2 * float(radii.max()) - .04) + 1e-12
    lo -= margin
    hi += margin
    within = lambda points: ((points >= lo) & (points <= hi)).all(axis=1)
    keep = within(xyz) | np.isin(ri, list(required))
    # Midpoint-based detector broad phase: a distant endpoint can still belong
    # to a bond which intersects a moving ring.
    keep[bonds[within(xyz[bonds].mean(axis=1))].ravel()] = True
    index = RotorPiercingIndex(model)
    for ids, atoms in index.ring_groups:
        selected = within(xyz[atoms].mean(axis=1))
        keep[atoms[selected].ravel()] = True
    # Preserve exclusion paths even when their intermediate atom lies outside.
    for _ in range(2):
        keep[bonds[keep[bonds].any(axis=1)].ravel()] = True
    selected = np.flatnonzero(keep)
    remap = np.full(len(xyz), -1, dtype=int)
    remap[selected] = np.arange(len(selected))
    kept_bonds = bonds[keep[bonds].all(axis=1)]
    return (SimpleNamespace(atoms=[model.atoms[i] for i in selected],
                            bonds=remap[kept_bonds].tolist()),
            ri[selected], moving[selected], radii[selected])
