"""Surface visual-regression tests on REAL designs.

Detects when a surface-code change VISUALLY changes the rendered mesh — the oracle that
lets the fast-build refactor (``surface_atom_cloud``, project_oxdna_relaxation §27) be
proven appearance-preserving.  The panel builds the FINE (all-atom) molecular surface the
exact way ``routes_display_geometry.get_surface`` detail='fine' does, and asserts stable,
meaningful invariants that any envelope change would perturb:

  * symmetric surface↔surface distance (``surface_hausdorff``) ≈ 0 when the mesh should be
    identical (the reusable oracle the Task-2 vectorized-build tests import);
  * enclosed volume + surface area + vertex/face counts pinned within a small band — these
    catch envelope drift (grid coarsening, radius inflation) directly;
  * the coarse-vs-fine deviation as a documented characterization (~2.8 Å mean) so a future
    coarse-surface tweak is caught too.

The invariants are PROVABLY able to go red: ``test_invariants_detect_envelope_perturbation``
perturbs the grid + the CG bead radius and asserts the distance/volume/count checks fire.

Panel: the small 6hb stays in the fast suite (~0.25 s — a per-loop guard); 18hb_routed and
VoltronCore build ~300k-atom models (~7 s each) so they are marked slow+atomistic and defer
to a test-dedicated session.  VoltronCore's design.json lives under workspace/ (not synced
across machines) → its param skips when absent.
"""

from pathlib import Path

import numpy as np
import pytest

from tests.conftest import make_6hb_design, make_18hb_routed_design
from backend.core.models import Design
from backend.api.routes_display_geometry import _flexible_display_override
from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from backend.core.surface import (
    compute_surface,
    smooth_mesh,
    adaptive_grid_spacing,
    cg_surface_mesh,
    make_cg_bead,
    CG_BEAD_RADIUS_NM,
)

_VOLTRONCORE_JSON = Path("workspace/oxdna_jobs/154d3ea291b7/design.json")


# ── Reusable mesh-comparison oracles (imported by the Task-2 vectorized-build tests) ──


def surface_hausdorff(mesh_a, mesh_b) -> dict:
    """Symmetric surface-to-surface vertex distance (nm) between two meshes, both directions,
    via ``scipy.spatial.cKDTree``.  Returns ``{"mean", "p99", "max"}``.

    ~0 when the two meshes describe the SAME surface (identical marching-cubes grid → identical
    vertices), and grows with any envelope change.  This is the core appearance-preservation
    oracle: the fast-build refactor must keep p99 ≤ ~0.1 nm (1 Å) vs the current fine surface.
    Empty on either side ⇒ inf (a build that produced nothing is never "identical")."""
    from scipy.spatial import cKDTree

    A = np.asarray(mesh_a.vertices, dtype=np.float64)
    B = np.asarray(mesh_b.vertices, dtype=np.float64)
    if len(A) == 0 or len(B) == 0:
        return {"mean": float("inf"), "p99": float("inf"), "max": float("inf")}
    d_ab, _ = cKDTree(B).query(A, workers=-1)
    d_ba, _ = cKDTree(A).query(B, workers=-1)
    d = np.concatenate([d_ab, d_ba])
    return {
        "mean": float(d.mean()),
        "p99": float(np.percentile(d, 99)),
        "max": float(d.max()),
    }


def mesh_volume(mesh) -> float:
    """Enclosed volume (nm³) via the divergence theorem — sum of signed tetrahedra from the
    origin.  A closed watertight mesh (marching cubes is closed) gives the true interior
    volume; the scalar drifts as soon as the envelope grows/shrinks."""
    v = np.asarray(mesh.vertices, dtype=np.float64)
    f = mesh.faces
    if len(f) == 0:
        return 0.0
    return float(
        abs(np.einsum("ij,ij->i", v[f[:, 0]], np.cross(v[f[:, 1]], v[f[:, 2]])).sum())
        / 6.0
    )


def mesh_area(mesh) -> float:
    """Total triangle surface area (nm²)."""
    v = np.asarray(mesh.vertices, dtype=np.float64)
    f = mesh.faces
    if len(f) == 0:
        return 0.0
    return float(
        0.5
        * np.linalg.norm(
            np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]]), axis=1
        ).sum()
    )


# ── Surface builders — mirror routes_display_geometry.get_surface EXACTLY ──


def fine_surface(
    design,
    grid_spacing=0.20,
    probe_radius=0.28,
    radius_inflate=1.30,
    smooth=15,
    *,
    measured_positioning=True,
):
    """The FINE (all-atom) design surface, built the way ``get_surface`` detail='fine' builds
    it (fast_bridges + flexible override + adaptive grid + Taubin smooth), so these tests guard
    the actually-rendered mesh."""
    model = build_atomistic_model(
        design,
        nuc_frame_override=_flexible_display_override(design),
        fast_bridges=True,
        measured_positioning=measured_positioning,
    )
    gs = adaptive_grid_spacing(model.atoms, grid_spacing)
    mesh = compute_surface(
        model.atoms,
        grid_spacing=gs,
        probe_radius=probe_radius,
        radius_scale=1.2 * radius_inflate,
    )
    return smooth_mesh(mesh, iterations=smooth)


def vectorized_fine_surface(
    design, grid_spacing=0.20, probe_radius=0.28, radius_inflate=1.30, smooth=15
):
    """The FINE surface built via the vectorised point cloud (``surface_atom_cloud`` +
    ``compute_surface_from_cloud``) — the fast path ``get_surface`` detail='fine' now serves.
    Must match :func:`fine_surface` (the exact Atom-object build) to within the appearance
    tolerance on every design it covers."""
    from backend.core.atomistic import surface_atom_cloud
    from backend.core.surface import (
        compute_surface_from_cloud,
        adaptive_grid_spacing_arr,
    )

    pos, radii, sids, nucs = surface_atom_cloud(design)
    gs = adaptive_grid_spacing_arr(pos, grid_spacing)
    mesh = compute_surface_from_cloud(
        pos,
        radii,
        sids,
        grid_spacing=gs,
        probe_radius=probe_radius,
        radius_scale=1.2 * radius_inflate,
        nuc_ids=nucs,
    )
    return smooth_mesh(mesh, iterations=smooth)


def coarse_surface(
    design,
    grid_spacing=0.20,
    probe_radius=0.28,
    smooth=15,
    bead_radius=CG_BEAD_RADIUS_NM,
):
    """The COARSE (CG-bead) design surface, built the way ``get_surface`` detail='coarse'
    builds it (~2 spheres/nucleotide straight from design geometry)."""
    beads = []
    for g in _geometry_for_design(design):
        for key in ("backbone_position", "base_position"):
            p = g.get(key)
            if p is None:
                continue
            beads.append(
                make_cg_bead(
                    p[0],
                    p[1],
                    p[2],
                    strand_id=g.get("strand_id", ""),
                    helix_id=g.get("helix_id", ""),
                    bp_index=int(g.get("bp_index", 0)),
                    direction=g.get("direction", "FORWARD"),
                )
            )
    return cg_surface_mesh(
        beads,
        grid_spacing=grid_spacing,
        probe_radius=probe_radius,
        smooth=smooth,
        bead_radius=bead_radius,
    )


def _voltroncore() -> Design:
    if not _VOLTRONCORE_JSON.exists():
        pytest.skip(
            "VoltronCore design.json not present (workspace/ is not synced across machines)"
        )
    return Design.model_validate_json(_VOLTRONCORE_JSON.read_text())


# Baselines measured on this machine (uv.lock-pinned scipy/skimage; marching cubes is
# deterministic). These July baselines used the legacy 1ZEW templates, before the
# August promotion of measured templates. Keep that input explicit for the frozen
# envelope oracle; the vectorized/exact and determinism tests exercise native
# measured templates. No baseline or production geometry is changed here.
# Counts/faces get an 8% band, volume +
# area a 5% band — loose enough for library micro-variation, tight enough that a real
# envelope change (grid coarsen → −47% verts, radius inflate → +21% vol) trips them.
# ``cf_mean`` is the coarse-vs-fine characterization (~2.8 Å).
_slow = [pytest.mark.slow, pytest.mark.atomistic]
_PANEL = [
    pytest.param(
        make_6hb_design,
        dict(verts=32777, faces=66466, vol=225.3, area=728.6, cf_mean=0.28),
        id="6hb",
    ),
    pytest.param(
        make_18hb_routed_design,
        dict(verts=871679, faces=1769846, vol=6399.5, area=19718.8, cf_mean=0.28),
        marks=_slow,
        id="18hb_routed",
    ),
    pytest.param(
        _voltroncore,
        dict(verts=498015, faces=1016230, vol=6718.3, area=18077.7, cf_mean=0.29),
        marks=_slow,
        id="VoltronCore",
    ),
]

_COUNT_BAND = 0.08
_SCALAR_BAND = 0.05


@pytest.mark.parametrize("builder,base", _PANEL)
def test_fine_surface_deterministic(builder, base):
    """Building the fine surface twice yields the identical mesh — the identity case that
    calibrates ``surface_hausdorff`` (≈0) and proves the pipeline is reproducible."""
    design = builder()
    m1 = fine_surface(design)
    m2 = fine_surface(design)
    assert len(m1.vertices) == len(m2.vertices)
    h = surface_hausdorff(m1, m2)
    assert h["max"] < 1e-4, f"fine surface not deterministic: {h}"


@pytest.mark.parametrize("builder,base", _PANEL)
def test_fine_surface_invariants(builder, base):
    """Vertex/face counts + enclosed volume + surface area stay within a small band of the
    pinned baseline — an envelope change (grid, radius, frame math) moves them well beyond it."""
    design = builder()
    m = fine_surface(design, measured_positioning=False)
    assert abs(len(m.vertices) / base["verts"] - 1.0) < _COUNT_BAND, (
        f"vertex count {len(m.vertices)} vs baseline {base['verts']}"
    )
    assert abs(len(m.faces) / base["faces"] - 1.0) < _COUNT_BAND, (
        f"face count {len(m.faces)} vs baseline {base['faces']}"
    )
    assert abs(mesh_volume(m) / base["vol"] - 1.0) < _SCALAR_BAND, (
        f"volume {mesh_volume(m):.1f} vs baseline {base['vol']}"
    )
    assert abs(mesh_area(m) / base["area"] - 1.0) < _SCALAR_BAND, (
        f"area {mesh_area(m):.1f} vs baseline {base['area']}"
    )


@pytest.mark.parametrize("builder,base", _PANEL)
def test_coarse_vs_fine_deviation(builder, base):
    """Characterize how far the fast COARSE (CG-bead) surface sits from the FINE (all-atom)
    surface — ~2.8 Å mean, < the display grid spacing.  Pins the coarse approximation so a
    future coarse-surface tweak (bead radius, base offset) is caught."""
    design = builder()
    h = surface_hausdorff(coarse_surface(design), fine_surface(design))
    assert 0.15 < h["mean"] < 0.45, (
        f"coarse-vs-fine mean {h['mean']:.3f} nm off characterization"
    )
    assert h["p99"] < 1.2, f"coarse-vs-fine p99 {h['p99']:.3f} nm"
    assert h["max"] < 2.0, f"coarse-vs-fine max {h['max']:.3f} nm"


@pytest.mark.parametrize("builder,base", _PANEL)
def test_vectorized_fine_surface_matches_exact_build(builder, base):
    """The vectorised point-cloud fine surface (the fast path now shipped) reproduces the exact
    Atom-object build's mesh to within the appearance tolerance (≤1 Å p99) — the Task-2 gate.
    On the covered designs it is byte-identical (0 Å); the tolerance guards against future
    drift in the frame/stamp/bridge vectorisation."""
    design = builder()
    exact = fine_surface(design)
    fast = vectorized_fine_surface(design)
    h = surface_hausdorff(exact, fast)
    assert h["p99"] < 0.1, f"vectorized vs exact p99 {h['p99']:.4f} nm (>1 Å)"
    assert h["mean"] < 0.03, f"vectorized vs exact mean {h['mean']:.4f} nm"


def test_vectorized_fine_surface_matches_exact_on_deformed():
    """The deformation/cluster fold (4-marker) in the vectorised build must reproduce the exact
    build on a BENT design — exercises the ``_fold_design_geometry_into_frames`` path (the panel's
    VoltronCore covers clusters; this covers a bend deformation)."""
    from backend.core.models import DeformationOp, BendParams

    design = make_6hb_design(length_bp=84)
    design = design.model_copy(
        update={
            "deformations": [
                DeformationOp(
                    type="bend",
                    plane_a_bp=20,
                    plane_b_bp=64,
                    affected_helix_ids=[h.id for h in design.helices],
                    params=BendParams(curvature_deg_per_bp=1.5),
                )
            ]
        }
    )
    h = surface_hausdorff(fine_surface(design), vectorized_fine_surface(design))
    assert h["p99"] < 0.1, f"deformed vectorized vs exact p99 {h['p99']:.4f} nm"


def test_invariants_detect_envelope_perturbation():
    """PROOF the visual-regression oracle can go RED.  A coarser grid and a fatter CG bead
    radius both visibly change the envelope; here we confirm ``surface_hausdorff`` leaves the
    identity band and the vertex-count / volume invariants would fire.  Guards against a
    silently inert test that could pass through a real regression."""
    design = make_6hb_design()

    # (1) Grid perturbation on the FINE surface: a coarser marching-cubes grid changes the
    # vertex count far beyond the invariant band and drives the distance well past identity.
    base = fine_surface(design)
    coarser = fine_surface(design, grid_spacing=0.25)
    h = surface_hausdorff(base, coarser)
    assert h["mean"] > 0.02, (
        "grid perturbation did not move surface_hausdorff off identity"
    )
    assert abs(len(coarser.vertices) / len(base.vertices) - 1.0) > _COUNT_BAND, (
        "grid perturbation did not trip the vertex-count invariant"
    )

    # (2) CG bead-radius perturbation on the COARSE surface: a fatter bead inflates the
    # envelope → volume grows beyond the scalar band.
    cg_base = coarse_surface(design)
    cg_fat = coarse_surface(design, bead_radius=CG_BEAD_RADIUS_NM + 0.15)
    assert mesh_volume(cg_fat) / mesh_volume(cg_base) - 1.0 > _SCALAR_BAND, (
        "CG bead-radius perturbation did not trip the volume invariant"
    )
    assert surface_hausdorff(cg_base, cg_fat)["mean"] > 0.05
