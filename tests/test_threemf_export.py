"""
Tests for backend/core/threemf_export.py — multi-colour 3MF export.

Verifies the 3MF package is a valid zip with parseable model XML, that the
scaffold/staple split produces the right number of coloured parts (each a
re-indexed sub-object referencing a base material), that all original faces
survive the split, and that auto-scaling is shared with the STL path.
"""

import io
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

from backend.core.atomistic import build_atomistic_model
from backend.core.lattice import make_bundle_design
from backend.core.surface import SurfaceMesh, compute_surface, smooth_mesh
from backend.core.threemf_export import (
    auto_scale,
    export_3mf,
    scaffold_staple_colored_groups,
    scaffold_staple_groups,
    _color_staples,
    _staple_adjacency,
)

_CELLS_6HB = [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)]
_CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"


def _design_and_surface():
    design = make_bundle_design(cells=_CELLS_6HB, length_bp=42, plane="XY")
    model = build_atomistic_model(design)
    mesh = compute_surface(model.atoms, grid_spacing=0.30, probe_radius=0.28)
    mesh = smooth_mesh(mesh, iterations=15)
    return design, mesh


def _model_root(data: bytes) -> ET.Element:
    z = zipfile.ZipFile(io.BytesIO(data))
    assert z.testzip() is None, "corrupt zip"
    assert set(z.namelist()) >= {
        "[Content_Types].xml",
        "_rels/.rels",
        "3D/3dmodel.model",
    }
    return ET.fromstring(z.read("3D/3dmodel.model"))


def _ns(tag: str) -> str:
    return f"{{{_CORE_NS}}}{tag}"


def test_3mf_is_valid_zip_with_parseable_model():
    design, mesh = _design_and_surface()
    assert mesh.faces.shape[0] > 0
    fg, names, colors = scaffold_staple_groups(mesh, design)
    root = _model_root(export_3mf(mesh, fg, names, colors, scale=1.0, name="t"))
    assert root.tag == _ns("model")
    assert root.get("unit") == "millimeter"


def test_two_base_materials_and_part_objects():
    design, mesh = _design_and_surface()
    fg, names, colors = scaffold_staple_groups(mesh, design)
    # This design has both a scaffold and staples → both groups populated.
    assert (fg == 0).any() and (fg == 1).any()

    root = _model_root(export_3mf(mesh, fg, names, colors, name="t"))
    bases = root.findall(f".//{_ns('base')}")
    assert [b.get("name") for b in bases] == ["scaffold", "staples"]
    assert bases[0].get("displaycolor") == "#29B6F6FF"

    objects = root.findall(f".//{_ns('object')}")
    # Two coloured parts + one assembly object.
    part_objs = [o for o in objects if o.get("pid") == "1"]
    assert len(part_objs) == 2
    assert {o.get("pindex") for o in part_objs} == {"0", "1"}

    # The assembly references both parts as components, and build points at it.
    comps = root.findall(f".//{_ns('component')}")
    assert len(comps) == 2
    item = root.find(f".//{_ns('item')}")
    assert item is not None


def test_all_faces_survive_the_split():
    """Every original triangle ends up in exactly one part (no loss/dup)."""
    design, mesh = _design_and_surface()
    fg, names, colors = scaffold_staple_groups(mesh, design)
    root = _model_root(export_3mf(mesh, fg, names, colors, name="t"))
    total_tris = sum(
        len(o.findall(f".//{_ns('triangle')}"))
        for o in root.findall(f".//{_ns('object')}")
        if o.get("pid") == "1"
    )
    assert total_tris == mesh.faces.shape[0]


def test_part_faces_reference_only_local_vertices():
    """Each part's triangles index within its own re-indexed vertex list."""
    design, mesh = _design_and_surface()
    fg, names, colors = scaffold_staple_groups(mesh, design)
    root = _model_root(export_3mf(mesh, fg, names, colors, name="t"))
    for o in root.findall(f".//{_ns('object')}"):
        if o.get("pid") != "1":
            continue
        n_verts = len(o.findall(f".//{_ns('vertex')}"))
        for t in o.findall(f".//{_ns('triangle')}"):
            for k in ("v1", "v2", "v3"):
                assert 0 <= int(t.get(k)) < n_verts


def test_auto_scale_matches_stl_path():
    _, mesh = _design_and_surface()
    scale = auto_scale(mesh, target_mm=200.0)
    scaled = mesh.vertices.astype(np.float64) * scale
    extent = scaled.max(axis=0) - scaled.min(axis=0)
    assert abs(float(extent.max()) - 200.0) < 1e-3


def test_single_group_design_emits_one_part():
    """A design with no scaffold yields a single staple part (no empty part)."""
    design, mesh = _design_and_surface()
    fg, names, colors = scaffold_staple_groups(mesh, design)
    # Force everything into the staple group.
    fg = np.ones_like(fg)
    root = _model_root(export_3mf(mesh, fg, names, colors, name="t"))
    part_objs = [o for o in root.findall(f".//{_ns('object')}") if o.get("pid") == "1"]
    assert len(part_objs) == 1
    assert part_objs[0].get("pindex") == "1"
    # Both materials still declared; only the populated part is emitted.
    assert len(root.findall(f".//{_ns('base')}")) == 2
    assert len(root.findall(f".//{_ns('component')}")) == 1


# ── Staple map-colouring ─────────────────────────────────────────────────────

def test_staple_adjacency_from_mesh_edges():
    """Touching staple regions become adjacency pairs; non-touching do not."""
    # Vertices 0,1 → staple 0; 2,3 → staple 1; 4,5 → staple 2.
    vert_code = np.array([0, 0, 1, 1, 2, 2], dtype=np.int64)
    # One triangle joins all three staples; its edges border 0-1, 1-2, 0-2.
    faces = np.array([[0, 2, 4]], dtype=np.int64)
    pairs = _staple_adjacency(faces, vert_code)
    assert pairs.tolist() == [[0, 1], [0, 2], [1, 2]]


def test_staple_adjacency_ignores_scaffold_and_self():
    vert_code = np.array([0, 0, -1, 1, -2], dtype=np.int64)  # -1 scaffold, -2 unassigned
    # Edges: 0-0 (self, skip), 0-scaffold (skip), staple0-staple1 only via [1,3,*].
    faces = np.array([[0, 1, 3], [0, 2, 4]], dtype=np.int64)
    pairs = _staple_adjacency(faces, vert_code)
    assert pairs.tolist() == [[0, 1]]


def test_color_staples_proper_on_3colorable():
    # Triangle (3-clique) is 3-colourable → 0 conflicts, all different.
    pairs = np.array([[0, 1], [1, 2], [0, 2]], dtype=np.int64)
    color, conflicts = _color_staples(3, pairs, k=3)
    assert conflicts == 0
    assert len(set(color)) == 3

    # A path 0-1-2-3 is 2-colourable, trivially 0 conflicts with 3 colours.
    path = np.array([[0, 1], [1, 2], [2, 3]], dtype=np.int64)
    _, c2 = _color_staples(4, path, k=3)
    assert c2 == 0


def test_color_staples_reports_unavoidable_conflicts_on_k4():
    # K4 cannot be 3-coloured → at least one same-colour edge remains.
    pairs = np.array([[0, 1], [0, 2], [0, 3], [1, 2], [1, 3], [2, 3]], dtype=np.int64)
    _, conflicts = _color_staples(4, pairs, k=3)
    assert conflicts >= 1


def test_color_staples_balances_isolated_nodes():
    # No edges → greedy spreads colours across the three sets.
    color, conflicts = _color_staples(9, np.zeros((0, 2), dtype=np.int64), k=3)
    assert conflicts == 0
    counts = [color.count(c) for c in range(3)]
    assert counts == [3, 3, 3]


def test_colored_groups_four_groups_on_real_design():
    design, mesh = _design_and_surface()
    fg, names, colors, stats = scaffold_staple_colored_groups(mesh, design, n_staple_colors=3)
    assert names == ["scaffold", "staples A", "staples B", "staples C"]
    assert colors == ["#29B6F6", "#FF6B6B", "#6BCB77", "#FFD93D"]
    assert fg.shape[0] == mesh.faces.shape[0]
    assert int(fg.max()) <= 3 and int(fg.min()) >= 0
    assert stats["n_staples"] > 0
    assert sum(stats["counts"]) == stats["n_staples"]
    # The 3MF carries one part per populated group + an assembly object.
    root = _model_root(export_3mf(mesh, fg, names, colors, name="t"))
    part_objs = [o for o in root.findall(f".//{_ns('object')}") if o.get("pid") == "1"]
    assert 1 <= len(part_objs) <= 4
    assert {int(o.get("pindex")) for o in part_objs} <= {0, 1, 2, 3}
    assert len(root.findall(f".//{_ns('base')}")) == 4


def test_colored_groups_clamps_staple_colors():
    design, mesh = _design_and_surface()
    fg1, names1, colors1, _ = scaffold_staple_colored_groups(mesh, design, n_staple_colors=1)
    assert names1 == ["scaffold", "staples A"]
    assert int(fg1.max()) <= 1
    # Out-of-range clamps to the 3-colour palette, not beyond.
    _, names9, colors9, _ = scaffold_staple_colored_groups(mesh, design, n_staple_colors=9)
    assert len(colors9) == 4


def test_empty_mesh_exports_valid_3mf():
    empty = SurfaceMesh(
        vertices=np.empty((0, 3), dtype=np.float32),
        faces=np.empty((0, 3), dtype=np.int32),
        vertex_strand_ids=[],
    )
    design = make_bundle_design(cells=_CELLS_6HB, length_bp=42, plane="XY")
    fg, names, colors = scaffold_staple_groups(empty, design)
    assert fg.shape[0] == 0
    root = _model_root(export_3mf(empty, fg, names, colors, name="t"))
    # No parts, no components, but a valid (empty) assembly + build remain.
    assert root.findall(f".//{_ns('triangle')}") == []
    assert root.find(f".//{_ns('item')}") is not None
