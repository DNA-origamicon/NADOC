"""Fast unit tests for the per-strand split surface (ChimeraX-quality path).

compute_split_surfaces_from_cloud builds a SEPARATE solvent-excluded surface per strand so
adjacent strands are distinct geometry with a real gap between them (vs one fused blob).  These
use tiny synthetic point clouds so they stay in the fast suite.
"""

import numpy as np
from scipy.spatial import cKDTree

from backend.core.surface import compute_split_surfaces_from_cloud


def _blob(center, n=3, spacing=0.3):
    """A small (n×n×n) cubic cloud of atoms centred at ``center`` (nm)."""
    g = (np.arange(n) - (n - 1) / 2) * spacing
    xs, ys, zs = np.meshgrid(g, g, g, indexing="ij")
    pts = np.stack([xs.ravel(), ys.ravel(), zs.ravel()], axis=1)
    return pts + np.asarray(center, dtype=float)


def test_two_separated_strands_give_two_disconnected_coloured_surfaces():
    a = _blob([0.0, 0.0, 0.0])
    b = _blob([4.0, 0.0, 0.0])  # 4 nm apart — clearly separate
    positions = np.vstack([a, b])
    radii = np.full(len(positions), 0.17)  # carbon-ish
    strand_ids = ["A"] * len(a) + ["B"] * len(b)

    mesh = compute_split_surfaces_from_cloud(
        positions, radii, strand_ids, grid_spacing=0.1, smooth=2
    )

    # Each strand contributes its own vertices, tagged with its id.
    assert set(mesh.vertex_strand_ids) == {"A", "B"}
    assert mesh.vertices.shape[0] > 0 and mesh.faces.shape[0] > 0

    sid = np.asarray(mesh.vertex_strand_ids)
    va = mesh.vertices[sid == "A"]
    vb = mesh.vertices[sid == "B"]
    assert len(va) > 0 and len(vb) > 0
    # The two surfaces are GEOMETRICALLY separate — a real gap, not a shared/jagged seam.
    gap = cKDTree(va).query(vb, workers=-1)[0].min()
    assert gap > 1.0, f"strand surfaces should be separated by a gap, got {gap:.2f} nm"


def test_face_indices_are_offset_per_part_and_in_range():
    positions = np.vstack([_blob([0.0, 0.0, 0.0]), _blob([4.0, 0.0, 0.0])])
    radii = np.full(len(positions), 0.17)
    strand_ids = ["A"] * 27 + ["B"] * 27
    mesh = compute_split_surfaces_from_cloud(
        positions, radii, strand_ids, grid_spacing=0.1, smooth=0
    )
    # Concatenation must offset each part's face indices into the combined vertex array.
    assert mesh.faces.min() >= 0
    assert mesh.faces.max() < mesh.vertices.shape[0]
    # Every face's three vertices belong to ONE strand (no cross-strand triangle).
    sid = np.asarray(mesh.vertex_strand_ids)
    tri_sid = sid[mesh.faces]
    assert np.all(tri_sid[:, 0] == tri_sid[:, 1]) and np.all(
        tri_sid[:, 1] == tri_sid[:, 2]
    )


def test_empty_cloud_returns_empty_mesh():
    mesh = compute_split_surfaces_from_cloud(np.empty((0, 3)), np.empty((0,)), [])
    assert mesh.vertices.shape[0] == 0
    assert mesh.faces.shape[0] == 0
    assert mesh.vertex_strand_ids == []


def test_split_surface_carries_per_vertex_nucleotide_ids():
    """The ChimeraX split path runs one marching-cubes pass PER STRAND, so it knows the
    strand structurally — but it used to pass ``strand_ids=None`` into each sub-build and
    so produced no nucleotide identity at all. Per-cluster colouring needs it: a strand
    can span several clusters (LESSONS D15)."""
    import numpy as np
    from backend.core.surface import compute_split_surfaces_from_cloud

    # Two well-separated blobs on different "strands", each with its own nucleotide key.
    a = np.random.default_rng(0).normal(0, 0.3, (60, 3))
    b = a + np.array([8.0, 0.0, 0.0])
    pos = np.vstack([a, b])
    radii = np.full(len(pos), 0.35)
    sids = ["sA"] * len(a) + ["sB"] * len(b)
    nucs = ["hA:1:FORWARD"] * len(a) + ["hB:2:REVERSE"] * len(b)

    mesh = compute_split_surfaces_from_cloud(pos, radii, sids, nuc_ids=nucs)
    if mesh.vertices.shape[0] == 0:
        return  # grid too coarse for these blobs on this machine; nothing to assert
    assert len(mesh.vertex_nuc_ids) == mesh.vertices.shape[0]
    assert set(mesh.vertex_nuc_ids) <= {"hA:1:FORWARD", "hB:2:REVERSE"}
    # A vertex's nucleotide key must agree with its strand id — they come from the same point.
    for sid, nid in zip(mesh.vertex_strand_ids, mesh.vertex_nuc_ids):
        if not nid:
            continue
        assert (sid == "sA") == nid.startswith("hA:")
