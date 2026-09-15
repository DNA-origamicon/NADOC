"""Deterministic unrelaxed fcc geometry in nm, shared by gold material models."""

import math
import numpy as np

from backend.core.surface_transforms import RigidTransform


def _positive(value, name):
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return float(value)


def slab(facet, repeats, layers, lattice_nm):
    """Orthorhombic, lateral-periodic (100)/(111) slab; no duplicate edge sites."""
    if facet not in ("100", "111"):
        raise ValueError("Supported unreconstructed facets are 100 and 111")
    if not isinstance(repeats, (list, tuple)) or len(repeats) != 2 or any(type(n) is not int or not 1 <= n <= 200 for n in repeats):
        raise ValueError("Slab repeats must be two integers in 1..200")
    if type(layers) is not int or not 2 <= layers <= 100:
        raise ValueError("Slab requires 2..100 complete layers")
    a = _positive(lattice_nm, "lattice_nm")
    s = a / math.sqrt(2)
    dy = s if facet == "100" else math.sqrt(3) * s
    spacing = a/2 if facet == "100" else a/math.sqrt(3)
    basis = [(0., 0.)] if facet == "100" else [(0., 0.), (s/2, dy/2)]
    if repeats[0]*repeats[1]*layers*len(basis) > 250000:
        raise ValueError("Gold geometry exceeds the 250,000-atom preparation limit")
    shift = (s/2, s/2) if facet == "100" else (s/2, dy/6)
    lx, ly = repeats[0]*s, repeats[1]*dy
    xyz = [(round((i*s+x+k*shift[0]) % lx, 12),
            round((j*dy+y+k*shift[1]) % ly, 12), k*spacing)
           for k in range(layers) for i in range(repeats[0])
           for j in range(repeats[1]) for x, y in basis]
    # Roundoff near a periodic edge must not produce sites at both 0 and L.
    p = np.array(xyz)
    p[:, :2] %= [lx, ly]
    for axis, length in enumerate((lx, ly)):
        p[np.isclose(p[:, axis], length, rtol=0, atol=1e-10), axis] = 0
    return p, {"kind": "slab", "facet": facet, "repeats": list(repeats),
               "layers": layers, "lattice_nm": a, "lateral_nm": [lx, ly],
               "thickness_nm": (layers-1)*spacing, "layer_spacing_nm": spacing}


def nanoparticle(radius_nm, lattice_nm):
    """Spherical cut centered on an fcc lattice site; not a Wulff relaxation."""
    radius = _positive(radius_nm, "radius_nm")
    a = _positive(lattice_nm, "lattice_nm")
    if not a <= radius <= 10:
        raise ValueError("Nanoparticle radius must be at least one lattice cell and at most 10 nm")
    n = math.ceil(2*radius/a)
    if (2*n+1)**3 > 2_000_000:
        raise ValueError("Nanoparticle candidate lattice exceeds preparation limit")
    q = np.arange(-n, n+1)
    ijk = np.array(np.meshgrid(q, q, q, indexing="ij")).reshape(3, -1).T
    p = ijk[(ijk.sum(axis=1) % 2) == 0] * (a/2)
    p = p[np.linalg.norm(p, axis=1) <= radius + 1e-12]
    if len(p) > 250000:
        raise ValueError("Gold geometry exceeds the 250,000-atom preparation limit")
    return p, {"kind": "nanoparticle", "shape": "fcc_spherical_cut", "radius_nm": radius,
               "lattice_nm": a, "center_convention": "fcc lattice site"}


def transformed_geometry(positions_nm, cell_vectors_nm, transform: RigidTransform):
    """Transform atoms and cell together; translation affects the origin only."""
    cell = np.asarray(cell_vectors_nm, dtype=float)
    if cell.shape != (3, 3) or not np.isfinite(cell).all() or np.linalg.det(cell) <= 0:
        raise ValueError("Expected finite right-handed cell vectors")
    return {"positions_nm": transform.points(positions_nm).tolist(),
            "cell_vectors_nm": [transform.direction(v).tolist() for v in cell],
            "cell_origin_nm": list(transform.translation_nm)}
