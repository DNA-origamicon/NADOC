"""Periodic image and cell-frame adapters; no molecular placement or force policy."""
from copy import deepcopy

import numpy as np

from backend.core.surface_transforms import RigidTransform, surface_frame, transform_surface


def unwrap_chains(points_nm, chains, box_nm, *, graft_sites_nm=None):
    """Make explicit ordered chains whole in an orthorhombic source cell.

    Keep each first bead in its recorded image, or select its nearest image to
    its registered graft. Never independently center chains. Exactly half-cell
    bonds/graft displacements are ambiguous and rejected. Chain indices must
    partition all supplied points; connectivity is supplied, never inferred.
    """
    points = RigidTransform().points(points_nm)
    if points.ndim != 2:
        raise ValueError("chain points must have shape (N, 3)")
    box = np.asarray(box_nm, float)
    if box.shape != (3,) or not np.isfinite(box).all() or np.any(box <= 0):
        raise ValueError("box_nm must contain three positive finite lengths")
    order = [i for chain in chains for i in chain]
    if any(isinstance(i, bool) or not isinstance(i, (int, np.integer)) for i in order):
        raise ValueError("chain indices must be integers")
    if sorted(order) != list(range(len(points))) or any(not len(c) for c in chains):
        raise ValueError("chains must partition points exactly once")
    grafts = None if graft_sites_nm is None else RigidTransform().points(graft_sites_nm)
    if grafts is not None and grafts.shape != (len(chains), 3):
        raise ValueError("one registered graft site is required per chain")

    def minimum_image(delta):
        fractional = delta / box
        reduced = fractional - np.rint(fractional)
        if np.any(np.isclose(np.abs(reduced), .5, atol=1e-10, rtol=0)):
            raise ValueError("ambiguous half-cell displacement; supply an unwrapped checkpoint")
        return reduced * box

    result = points.copy()
    for c, chain in enumerate(chains):
        if grafts is not None:
            result[chain[0]] = grafts[c] + minimum_image(points[chain[0]] - grafts[c])
        for previous, current in zip(chain, chain[1:]):
            result[current] = result[previous] + minimum_image(points[current] - points[previous])
    return result


def surface_aligned_cell(points_nm, spec, *, padding_nm):
    """Rebox a whole assembly in a surface-aligned orthorhombic cell.

    All supplied points and declared surface/coating fields use one rigid map.
    Returns the forward/inverse map and the physical cell vectors in the source
    frame. This prepares geometry; callers must rotate external vectors too and
    rebuild solvent. It does not rotate an existing solvent cell in place.
    """
    points = RigidTransform().points(points_nm)
    if points.ndim != 2 or not len(points):
        raise ValueError("a nonempty whole assembly is required")
    if not np.isfinite(padding_nm) or padding_nm <= 0:
        raise ValueError("padding_nm must be positive and finite")
    frame = surface_frame(spec)
    rotate = RigidTransform((frame.tangent_u, tuple(frame.tangent_v), frame.normal))
    rotated = rotate.points(points)
    moved_surface = transform_surface(spec, rotate)
    # Include registered features when sizing: a barrier may sit beyond the DNA.
    extent = [rotated, np.asarray(moved_surface['plane_point_nm']).reshape(1, 3)]
    for key in ('pore_center_nm', 'graft_sites_nm', 'peg_positions_nm'):
        if key in moved_surface and np.asarray(moved_surface[key]).size:
            extent.append(np.asarray(moved_surface[key]).reshape(-1, 3))
    extent = np.concatenate(extent)
    lo, hi = extent.min(0), extent.max(0)
    transform = rotate.then(RigidTransform(translation_nm=padding_nm - lo))
    lengths = hi - lo + 2 * padding_nm
    return {
        'points_nm': transform.points(points),
        'surface': transform_surface(spec, transform),
        'box_nm': lengths,
        'source_cell_vectors_nm': np.diag(lengths) @ np.asarray(rotate.rotation),
        'transform': transform,
        'inverse': transform.inverse(),
    }


def translate_coated_surface(spec, displacement_nm):
    """Move a sheet with all its declared attached geometry; update in place.

    Used by graphene's existing clearance policy, which chooses the displacement.
    Explicit local patch coordinates/dimensions remain unchanged.
    """
    original = deepcopy(spec)
    if original.get('plane_point_nm') is None:
        original['plane_point_nm'] = original['pore_center_nm']
    moved = transform_surface(original, RigidTransform(translation_nm=displacement_nm))
    spec.clear()
    spec.update(moved)
    return spec


def unwrap_connected(points_nm, edges, box_nm):
    """Make an explicit connectivity graph whole, retaining each root's image.

    Reject noncontractible periodic cycles instead of stretching a closing bond.
    Disconnected components retain their recorded root images; their relative
    image cannot be inferred without an external reference or graft constraint.
    """
    points = RigidTransform().points(points_nm)
    box = np.asarray(box_nm, float)
    if points.ndim != 2 or box.shape != (3,) or not np.isfinite(box).all() or np.any(box <= 0):
        raise ValueError('invalid points or orthorhombic cell')
    adjacency = [[] for _ in points]
    for a, b in edges:
        if (isinstance(a, bool) or isinstance(b, bool)
                or not isinstance(a, (int, np.integer)) or not isinstance(b, (int, np.integer))
                or not 0 <= a < len(points) or not 0 <= b < len(points) or a == b):
            raise ValueError('invalid connectivity edge')
        adjacency[a].append(b)
        adjacency[b].append(a)
    result = points.copy()
    visited = set()
    for root in range(len(points)):
        if root in visited:
            continue
        visited.add(root)
        pending = [root]
        while pending:
            a = pending.pop()
            for b in adjacency[a]:
                reduced = (points[b] - points[a]) / box
                reduced -= np.rint(reduced)
                if np.any(np.isclose(np.abs(reduced), .5, atol=1e-10, rtol=0)):
                    raise ValueError('ambiguous half-cell bond')
                candidate = result[a] + reduced * box
                if b in visited:
                    if not np.allclose(result[b], candidate, atol=1e-7, rtol=0):
                        raise ValueError('connectivity winds around the periodic cell; cannot make whole')
                else:
                    result[b] = candidate
                    visited.add(b)
                    pending.append(b)
    return result


def register_graphene_plane(spec, dna_points_nm, normal):
    """Honor an explicit plane when its default pore center has not been chosen."""
    spec['dir'] = np.asarray(normal).tolist()
    if (spec.get('surface_axis') is not None or 'pore_center_nm' in spec
            or (spec.get('plane_point_nm') is None and spec.get('position_nm') is None)):
        return
    points = np.asarray(dna_points_nm)
    reference = (points.min(0) + points.max(0)) / 2 if len(points) else np.zeros(3)
    spec['pore_center_nm'] = surface_frame(spec).project(reference).tolist()
