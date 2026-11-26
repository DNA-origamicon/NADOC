"""Elliptical coarse-grained loop layout, with fixed attachment nucleotides.

This is an ssDNA layout, not a relaxed or atomistic molecular conformation.
"""
import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.constants import BASE_DISPLACEMENT, SSDNA_CONTOUR_PER_NT_NM
from backend.core.strand_loops import loop_key, strand_entries

SOURCE = 'strand-loop-ellipse-v4-ring-priority'
MIN_OPTIMIZED_LOOP_LENGTH = 6


def ellipse_points(start, end, axis, outward, count, aspect_ratio=3.0, rotation_deg=0.0, outward_offset_nm=None):
    """Arc-length sample a loop with its long axis parallel to the host helix.

    Keep both roots fixed. Add the approved 0.50 nm outward shoulders, then
    refit ellipse scale to the available contour. Insertions below six bases
    retain their earlier layout; the reviewed offset does not fit a one-base loop.
    """
    if outward_offset_nm is None:
        outward_offset_nm = .50 if count >= MIN_OPTIMIZED_LOOP_LENGTH else 0.
    start, end = np.asarray(start, float), np.asarray(end, float)
    axis = np.asarray(axis, float)
    axis /= np.linalg.norm(axis)
    outward = np.asarray(outward, float) - axis * np.dot(outward, axis)
    if np.linalg.norm(outward) < 1e-8:
        outward = np.cross(axis, np.eye(3)[np.argmin(np.abs(axis))])
    outward /= np.linalg.norm(outward)
    angle = np.deg2rad(rotation_deg)
    outward = np.cos(angle) * outward + np.sin(angle) * np.cross(axis, outward)
    theta = np.linspace(0, 2 * np.pi, max(2049, 32 * count))
    t = theta / (2 * np.pi)
    target = (count + 1) * SSDNA_CONTOUR_PER_NT_NM
    chord = np.linalg.norm(end - start)
    if chord >= target:
        raise ValueError('Loop is too short to span its attachment nucleotides')
    shape = (aspect_ratio * np.sin(theta))[:, None] * axis + (1 - np.cos(theta))[:, None] * outward
    shoulder = 1 - np.exp(-(np.sin(np.pi * t) / .18)**2)
    shoulder[[0, -1]] = 0
    baseline = start + t[:, None] * (end - start) + outward_offset_nm * shoulder[:, None] * outward
    if np.linalg.norm(np.diff(baseline, axis=0), axis=1).sum() >= target:
        raise ValueError('Loop offset exceeds its available contour length')
    lo, hi = 0.0, target
    for _ in range(48):
        scale = (lo + hi) / 2
        curve = baseline + scale * shape
        length = np.linalg.norm(np.diff(curve, axis=0), axis=1).sum()
        if length < target:
            lo = scale
        else:
            hi = scale
    curve = baseline + ((lo + hi) / 2) * shape
    distances = np.r_[0, np.cumsum(np.linalg.norm(np.diff(curve, axis=0), axis=1))]
    samples = np.linspace(0, distances[-1], count + 2)
    return np.column_stack([np.interp(samples, distances, curve[:, i]) for i in range(3)])


def loop_base_rotation_angles(points, axis):
    """Flip every inserted base; use quarter turns at the two axial tips.

    Angles are relative to the original v1 frame, about the local 5′→3′
    backbone tangent. Each tip includes inserted bases within one ssDNA contour step of its
    axial extremum. This short turning region includes the flanking bases on
    coarse, small loops; rotating only a single extremal base leaves neighboring
    bases intersecting across the tip. Attachment nucleotides never rotate.
    """
    axial = np.asarray(points, float)[1:-1] @ np.asarray(axis, float)
    angles = np.full(len(axial), 180.0)
    if len(axial):
        tips = ((axial - axial.min() <= SSDNA_CONTOUR_PER_NT_NM + 1e-9) |
                (axial.max() - axial <= SSDNA_CONTOUR_PER_NT_NM + 1e-9))
        angles[tips] = 90.0
    return angles


def append_loop_geometry(design, records):
    """Add only loop residues; all existing positions and poses stay unchanged."""
    if not any(s.loops for s in design.strands):
        return
    by_key = {(n['strand_id'], n['helix_id'], n['bp_index'], n['direction']): n
              for n in records if not n.get('extension_id')}
    for strand in design.strands:
        if not strand.loops:
            continue
        entries = list(strand_entries(design, strand))
        for loop in strand.loops:
            key = loop_key(loop)
            anchor_index = entries.index((*key, 0))
            following = entries[anchor_index + loop.length + 1]
            anchor = by_key.get((strand.id, *key))
            end = by_key.get((strand.id, *following[:3]))
            if anchor is None or end is None:
                continue  # partial helix geometry omits unrelated loops
            axis = anchor['axis_tangent']
            normal = anchor['base_normal']
            points = ellipse_points(anchor['backbone_position'], end['backbone_position'],
                                    axis, -np.asarray(normal), loop.length, loop.aspect_ratio, loop.rotation_deg)
            base_angles = loop_base_rotation_angles(points, axis)
            # Ordinary base remains copy 0. Loop copies explicitly carry traversal
            # order, independent of the legacy reverse duplex-copy convention.
            anchor['loop_order'] = 0
            inserted = []
            for ordinal in range(1, loop.length + 1):
                tangent = points[ordinal + 1] - points[ordinal - 1]
                tangent /= np.linalg.norm(tangent)
                radial = np.asarray(normal) - tangent * np.dot(normal, tangent)
                if np.linalg.norm(radial) < 1e-8:
                    radial = np.cross(tangent, np.eye(3)[np.argmin(np.abs(tangent))])
                radial /= np.linalg.norm(radial)
                # User-selected layout: 180° everywhere, 90° at axial tips.
                radial = Rotation.from_rotvec(
                    tangent * np.deg2rad(base_angles[ordinal - 1])).apply(radial)
                binormal = np.cross(tangent, radial)
                base = points[ordinal] + BASE_DISPLACEMENT * radial
                record = {**anchor, 'copy_k': ordinal, 'loop_order': ordinal,
                          'backbone_position': points[ordinal].tolist(), 'base_position': base.tolist(),
                          'base_normal': radial.tolist(), 'axis_tangent': tangent.tolist(),
                          'slab_position': base.tolist(),
                          'slab_quaternion': Rotation.from_matrix(np.column_stack((binormal, tangent, radial))).as_quat().tolist(),
                          'placement_source': (SOURCE if loop.length < 40 else 'strand-loop-ellipse-v3-bond-optimum') if loop.length >= MIN_OPTIMIZED_LOOP_LENGTH else 'strand-loop-ellipse-v2', 'is_unpaired': True,
                          'is_five_prime': False, 'is_three_prime': False,
                          'nucleobase': (strand.sequence or '').ljust(len(entries), 'N')[anchor_index + ordinal]}
                record.pop('helical_site', None)
                records.append(record)
                inserted.append(record)
            from backend.core.strand_loop_bond_fit import fit_loop_bonds
            if loop.length >= MIN_OPTIMIZED_LOOP_LENGTH:
                sequence = (strand.sequence or '').ljust(len(entries), 'N')
                fit_loop_bonds({**anchor, 'nucleobase': sequence[anchor_index]}, inserted,
                               {**end, 'nucleobase': sequence[anchor_index + loop.length + 1]})
            if MIN_OPTIMIZED_LOOP_LENGTH <= loop.length < 40:
                outward = -np.asarray(normal, dtype=float)
                axis_unit = np.asarray(axis, dtype=float) / np.linalg.norm(axis)
                outward -= axis_unit * np.dot(outward, axis_unit)
                outward /= np.linalg.norm(outward)
                # Approved additional rigid 1 nm translation. Only attachments stretch.
                for record in inserted:
                    for field in ('backbone_position', 'base_position', 'slab_position'):
                        record[field] = (np.asarray(record[field]) + outward).tolist()
    from backend.core.strand_loop_ring_fit import refine_loop_geometry
    refine_loop_geometry(design, records)
