"""Derived display connectivity; solver values and scientific archives stay untouched."""
import numpy as np
from scipy.spatial import Delaunay, QhullError


def with_display_tetrahedra(result):
    """Interpolate adaptive point values without volume weighting or resampling.

    Masked vertices remain in the mesh so interpolation cannot bridge masked regions.
    Reject incomplete connectivity instead of silently dropping a sampled hotspot.
    """
    if result.get('sampling', {}).get('layout') != 'octree':
        return result
    points = np.asarray(result['sample_positions_nm'], dtype=float).reshape(-1, 3)
    if len(points) < 4:
        raise ValueError('Smooth EM interpolation requires four noncoplanar samples')
    for options in (None, 'QJ Qbb Qc Q12'):
        try:
            mesh = Delaunay(points, qhull_options=options)
        except QhullError:
            continue
        cells = mesh.simplices
        vertices = points[cells]
        determinants = np.linalg.det(vertices[:, 1:] - vertices[:, :1])
        cells = cells[np.isfinite(determinants) & (determinants != 0)]
        if len(np.unique(cells)) == len(points):
            return {**result, 'display_tetrahedra': cells.tolist()}
    raise ValueError('Smooth EM interpolation could not retain every adaptive sample')
