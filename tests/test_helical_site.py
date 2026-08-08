"""The helical site — the quantity every representation projects from.

A designed nucleotide's geometry is a point on the helix axis, the axis tangent there, and
the outward radial at its helical phase.  The coarse-grained bead is that projected at
``HELIX_RADIUS``; the atomistic stamp is the same site projected at ``_ATOMISTIC_P_RADIUS``
after the correction chain.  Neither is built from the other.

Phase 1 (``memory/project_helical_site.md``) put the site on the VECTORISED path, which is
what the display and every array consumer actually run — the scalar path already had it.

What these tests exist to catch, in order of how expensive the bug would be:

1. A producer that forgets the site, so a consumer silently falls back to re-deriving the
   phase from a bead (which is the whole thing being retired).
2. A transform that moves ``positions`` but leaves ``axis_points`` pointing at the straight
   lattice — a STALE site is worse than an absent one, because it reads as valid.
3. The loop/skip fallback recomputing the site instead of carrying the scalar path's own
   values.  The two paths use ``math.cos`` vs ``np.cos`` and differ at the last ULP, which
   the backbone-bridge solve downstream turns into 0.1-1.3 A (LESSONS H15/H19).
"""

from pathlib import Path

import numpy as np
import pytest

from backend.core.constants import HELIX_RADIUS
from backend.core.deformation import (
    deform_extended_arrays,
    deformed_nucleotide_arrays,
    effective_helix_for_geometry,
)
from backend.core.geometry import (
    _frame_from_helix_axis,
    nucleotide_positions,
    nucleotide_positions_arrays,
    nucleotide_positions_arrays_extended,
    nucleotide_positions_arrays_extended_right,
)
from backend.core.models import Design, LatticeType

PLAIN_HC = Path("Examples/6hb_test.nadoc")
PLAIN_SQ = Path("workspace/2x3x100_Sq_test.nadoc")
SKIPS = Path("workspace/3x6x400_Sq_test.nadoc")      # 18 helices carrying loop_skips
CLUSTERED = Path("workspace/VoltronCore.nadoc")      # 3 cluster transforms + 46 skip helices
BENT = Path("Examples/multi_domain_test3_bend90.nadoc")   # a real bend deformation

SITE_KEYS = ("axis_points", "radial_hats", "azimuths")


def _load(path: Path) -> Design:
    if not path.exists():
        pytest.skip(f"fixture {path} not present on this machine")
    return Design.model_validate_json(path.read_text())


def _identity_residual(arrs: dict) -> float:
    """max |position − (axis_point + HELIX_RADIUS·radial_hat)| over the array."""
    if not len(arrs["positions"]):
        return 0.0
    rhs = arrs["axis_points"] + HELIX_RADIUS * arrs["radial_hats"]
    return float(np.abs(arrs["positions"] - rhs).max())


@pytest.mark.parametrize("fixture", [PLAIN_HC, PLAIN_SQ, SKIPS])
def test_every_array_producer_emits_the_site(fixture):
    design = _load(fixture)
    helix = effective_helix_for_geometry(design.helices[0], design)
    producers = {
        "arrays": nucleotide_positions_arrays(helix),
        "arrays_compact": nucleotide_positions_arrays(helix, compact_skips=True),
        "extended_lo": nucleotide_positions_arrays_extended(helix, helix.bp_start - 6),
        "extended_hi": nucleotide_positions_arrays_extended_right(
            helix, helix.bp_start + helix.length_bp + 5),
        "deformed": deformed_nucleotide_arrays(design.helices[0], design),
    }
    for name, arrs in producers.items():
        for k in SITE_KEYS:
            assert k in arrs, f"{name} lost the site key {k}"
        M = len(arrs["positions"])
        assert arrs["axis_points"].shape == (M, 3), name
        assert arrs["radial_hats"].shape == (M, 3), name
        assert arrs["azimuths"].shape == (M,), name


def test_the_empty_helix_still_carries_the_site_keys():
    """A caller that unconditionally reads the site must not KeyError on a 0-bp helix."""
    design = _load(PLAIN_HC)
    helix = effective_helix_for_geometry(design.helices[0], design)
    arrs = nucleotide_positions_arrays_extended(helix, helix.bp_start)   # empty by design
    for k in SITE_KEYS:
        assert k in arrs
        assert len(arrs[k]) == 0


@pytest.mark.parametrize("fixture", [PLAIN_HC, PLAIN_SQ, SKIPS])
def test_the_bead_is_the_site_projected_exactly(fixture):
    """On straight geometry the identity is EXACT, not approximate.

    It is exact because the producers hand back the radial they already used to place the
    bead rather than recomputing it.  A tolerance here would hide precisely the recompute
    this is meant to forbid.
    """
    design = _load(fixture)
    checked = 0
    for h in design.helices:
        helix = effective_helix_for_geometry(h, design)
        for arrs in (nucleotide_positions_arrays(helix),
                     nucleotide_positions_arrays(helix, compact_skips=True),
                     nucleotide_positions_arrays_extended(helix, helix.bp_start - 4),
                     nucleotide_positions_arrays_extended_right(
                         helix, helix.bp_start + helix.length_bp + 4)):
            if not len(arrs["positions"]):
                continue
            rhs = arrs["axis_points"] + HELIX_RADIUS * arrs["radial_hats"]
            assert np.array_equal(arrs["positions"], rhs)
            checked += len(arrs["positions"])
    assert checked > 200


@pytest.mark.parametrize("fixture", [PLAIN_HC, SKIPS])
def test_the_azimuth_reproduces_the_radial_in_the_helix_frame(fixture):
    """``azimuths`` is not decoration — it must be the angle that generates ``radial_hats``.

    Nothing reads it yet; the engine adapters (Phases 2-4) will, and a silently wrong angle
    would be invisible until then.
    """
    design = _load(fixture)
    for h in design.helices[:4]:
        helix = effective_helix_for_geometry(h, design)
        arrs = nucleotide_positions_arrays(helix)
        if not len(arrs["positions"]):
            continue
        axis_vec = helix.axis_end.to_array() - helix.axis_start.to_array()
        frame = _frame_from_helix_axis(axis_vec / np.linalg.norm(axis_vec))
        expected = (np.cos(arrs["azimuths"])[:, None] * frame[:, 0]
                    + np.sin(arrs["azimuths"])[:, None] * frame[:, 1])
        assert np.abs(expected - arrs["radial_hats"]).max() < 1e-12


def test_the_skip_fallback_carries_the_scalar_paths_own_values():
    """Loop/skip helices route through the scalar path; the site must come WITH them.

    ``nucleotide_positions_arrays`` delegates any helix with ``loop_skips`` to
    ``nucleotide_positions`` and converts the result.  Recomputing the site in the
    converter would put skip-bearing designs a last ULP away from every other design.
    """
    design = _load(SKIPS)
    skip_helices = [h for h in design.helices if h.loop_skips]
    assert skip_helices, "fixture lost its loop/skips"
    checked = 0
    for h in skip_helices[:4]:
        helix = effective_helix_for_geometry(h, design)
        arrs = nucleotide_positions_arrays(helix)
        scalar = nucleotide_positions(helix)
        assert len(scalar) == len(arrs["positions"])
        assert np.array_equal(arrs["radial_hats"],
                              np.array([n.radial_hat for n in scalar]))
        assert np.array_equal(arrs["axis_points"],
                              np.array([n.axis_point for n in scalar]))
        assert np.array_equal(arrs["azimuths"],
                              np.array([n.azimuth_rad for n in scalar]))
        checked += len(scalar)
    assert checked > 100


def test_the_site_moves_with_the_beads_under_a_cluster_transform():
    """The stale-site trap: a transform that moves ``positions`` must move the site too.

    A cluster transform is applied by overwriting a fixed list of array keys.  Before the
    site joined that list, a clustered helix came back with moved beads and an
    ``axis_points`` still on the straight lattice — an invalid frame that reads as valid.
    """
    design = _load(CLUSTERED)
    assert design.cluster_transforms, "fixture lost its cluster transforms"
    moved = 0
    for h in design.helices[:12]:
        straight = nucleotide_positions_arrays(effective_helix_for_geometry(h, design))
        deformed = deformed_nucleotide_arrays(h, design)
        if not len(deformed["positions"]):
            continue
        # A rotation is involved, so the identity holds to rounding rather than exactly.
        assert _identity_residual(deformed) < 1e-12
        if np.abs(straight["positions"] - deformed["positions"]).max() > 1e-9:
            assert np.abs(straight["axis_points"]
                          - deformed["axis_points"]).max() > 1e-9, (
                f"{h.id}: beads moved but the site did not — stale site")
            moved += 1
    assert moved > 0, "no helix in this fixture actually moved; test proves nothing"


def test_the_site_survives_the_extended_loop_deformation_path():
    """``deform_extended_arrays`` handles ss-loop nucleotides outside the helix span.

    The bend is BUILT here rather than loaded: the repo's bend fixtures store
    ``curvature_deg_per_bp = 0.0`` (``multi_domain_test3_bend90`` included), so a
    fixture-driven version of this test would deform nothing and assert nothing.
    """
    from backend.core.models import BendParams, DeformationOp

    design = _load(PLAIN_HC)
    helix = effective_helix_for_geometry(design.helices[0], design)
    # The window sits INSIDE the helix and the extension is taken off the HIGH side, so
    # its edge frame is past the bend and genuinely rotated.  A low-side extension anchors
    # at the window's start, where the frame is still identity and nothing moves — correct
    # behaviour, but it would make this test vacuous.
    hi_edge = helix.bp_start + helix.length_bp - 1
    bent = design.model_copy(update={"deformations": [DeformationOp(
        type="bend",
        plane_a_bp=helix.bp_start + 2,
        plane_b_bp=hi_edge,
        affected_helix_ids=[h.id for h in design.helices],
        cluster_ids=[],
        params=BendParams(kind="bend", curvature_deg_per_bp=1.5, direction_deg=30.0),
    )]})

    extra = nucleotide_positions_arrays_extended_right(helix, hi_edge + 5)
    assert len(extra["positions"]), "fixture produced no extended nucleotides"
    out = deform_extended_arrays(extra, design.helices[0], bent, edge_bp=hi_edge)

    for k in SITE_KEYS:
        assert k in out
    assert _identity_residual(out) < 1e-12
    # Self-proving: the nucleotides must actually have moved, and the site with them.
    assert np.abs(extra["positions"] - out["positions"]).max() > 1e-9
    assert np.abs(extra["axis_points"] - out["axis_points"]).max() > 1e-9


# ── Phase 2: mrDNA reads the site instead of re-deriving it ───────────────────

LOOPS = Path("Examples/U6hb.nadoc")   # 36 loop insertions (delta > 0) + a bend


@pytest.mark.parametrize("fixture", [PLAIN_HC, PLAIN_SQ, SKIPS, LOOPS])
def test_the_mrdna_seed_is_the_geometric_layers_site(fixture):
    """Every mrDNA bead sits exactly on the bead the rest of NADOC draws.

    ``_build_nt_arrays`` used to re-implement the helix formula inline, reading
    ``phase_offset`` / ``twist_per_bp_rad`` STRAIGHT OFF the stored helix while every other
    representation goes through ``effective_helix_for_geometry``.  Exact equality here is
    what forbids the fourth copy of that formula from growing back.
    """
    from backend.core.mrdna_bridge import _NM_TO_ANGSTROM, _build_nt_arrays

    design = _load(fixture)
    r, _bp, _stack, _tp, _orient, _seq, nt_key = _build_nt_arrays(design, return_nt_key=True)

    site = {}
    for h in design.helices:
        seen: dict = {}
        for n in nucleotide_positions(effective_helix_for_geometry(h, design)):
            k = seen.get((n.bp_index, n.direction.value), 0)
            seen[(n.bp_index, n.direction.value)] = k + 1
            site[(h.id, n.bp_index, n.direction.value, k)] = n

    checked = 0
    for key, idx in nt_key.items():
        if key[0].startswith("__"):          # synthetic tail beads have no lattice site
            continue
        nuc = site.get(key)
        assert nuc is not None, f"mrDNA emitted {key} with no geometric site"
        assert np.array_equal(np.asarray(r[idx]), nuc.position * _NM_TO_ANGSTROM)
        checked += 1
    assert checked > 100


def test_the_mrdna_seed_uses_the_commensurate_honeycomb_twist():
    """The concrete bug the Phase-2 swap fixed, pinned so it cannot come back.

    Reading the STORED twist gave honeycomb designs the pre-TD-29 34.3 deg/bp instead of the
    commensurate 720/21, so crossover strain ramped along every helix — measured on
    ``18hb`` (400 bp), the seed moved up to 0.99 A, and it grows without bound with length.
    A square design is the control: its stored and grid-derived values already agreed, so
    its seed did not move at all.
    """
    from backend.core.constants import HONEYCOMB_TWIST_PER_BP_RAD
    from backend.core.mrdna_bridge import _NM_TO_ANGSTROM, _build_nt_arrays

    design = _load(LOOPS)
    assert design.lattice_type == LatticeType.HONEYCOMB
    stored = {h.twist_per_bp_rad for h in design.helices}
    assert not any(abs(t - HONEYCOMB_TWIST_PER_BP_RAD) < 1e-12 for t in stored), (
        "fixture no longer carries a stale stored twist — it cannot prove this")

    r, *_rest, nt_key = _build_nt_arrays(design, return_nt_key=True)
    helix = effective_helix_for_geometry(design.helices[0], design)
    assert abs(helix.twist_per_bp_rad - HONEYCOMB_TWIST_PER_BP_RAD) < 1e-12

    # The seed must follow the COMMENSURATE helix, not the stored one.
    seen: dict = {}
    for n in nucleotide_positions(helix):
        k = seen.get((n.bp_index, n.direction.value), 0)
        seen[(n.bp_index, n.direction.value)] = k + 1
        idx = nt_key.get((helix.id, n.bp_index, n.direction.value, k))
        if idx is not None:
            assert np.array_equal(np.asarray(r[idx]), n.position * _NM_TO_ANGSTROM)


# ── Phase 3: the periodic seam solver reads the axis instead of inverting for it ──


def test_the_seam_frame_is_the_forward_nucleotides_own_site():
    """The frame must be the forward strand's own axis point and radial, verbatim."""
    from backend.core import periodic_polymer as pp

    design = _load(CLUSTERED)
    checked = 0
    for h in design.helices[:8]:
        arrs = deformed_nucleotide_arrays(h, design)
        for bp in sorted({int(b) for b in arrs["bp_indices"]})[::11]:
            F = pp._section_frame_from_arrs(arrs, bp)
            if F is None:
                continue
            fi = int(((arrs["bp_indices"] == bp) & (arrs["directions"] == 0)).argmax())
            assert np.allclose(F[:3, 3], arrs["axis_points"][fi], atol=1e-15)
            assert np.allclose(F[:3, 0], arrs["radial_hats"][fi], atol=1e-15)
            checked += 1
    assert checked > 20


def test_the_seam_solver_survives_a_base_pair_split_across_two_clusters():
    """The bug Phase 3 fixed, on the fixture that exhibits it.

    Cluster transforms are applied per DOMAIN, so a base pair whose two strands belong to
    different domain-level clusters has one bead moved and the other left behind.  The old
    chord-based solve fed those two beads into one 2x2 as though they shared a frame — on
    VoltronCore the reverse bead sits 7.5-7.9 nm from the forward bead's axis instead of
    ~1 nm, and the recovered axis was garbage (35 of 5549 sampled cross-sections, up to
    1.94 nm out).  Reading the forward nucleotide's own site is immune by construction.
    """
    from backend.core import periodic_polymer as pp

    design = _load(CLUSTERED)
    split_found = 0
    for h in design.helices:
        arrs = deformed_nucleotide_arrays(h, design)
        for bp in sorted({int(b) for b in arrs["bp_indices"]}):
            fwd = (arrs["bp_indices"] == bp) & (arrs["directions"] == 0)
            rev = (arrs["bp_indices"] == bp) & (arrs["directions"] == 1)
            if not fwd.any() or not rev.any():
                continue
            fi, ri = int(fwd.argmax()), int(rev.argmax())
            if np.allclose(arrs["axis_points"][fi], arrs["axis_points"][ri], atol=1e-9):
                continue                      # both strands in one frame — not the case
            split_found += 1
            F = pp._section_frame_from_arrs(arrs, bp)
            assert F is not None
            # The frame is the FORWARD strand's, and its bead is exactly HELIX_RADIUS out.
            assert np.allclose(F[:3, 3], arrs["axis_points"][fi], atol=1e-15)
            offset = arrs["positions"][fi] - F[:3, 3]
            assert abs(float(np.linalg.norm(offset)) - HELIX_RADIUS) < 1e-12
            if split_found >= 5:
                return
    pytest.fail("no split base pair found — this fixture cannot prove the fix")


# ── Phase 5: the measured producer ───────────────────────────────────────────


@pytest.mark.parametrize("fixture", [PLAIN_HC, PLAIN_SQ, SKIPS])
def test_measuring_a_site_off_the_bead_reproduces_the_analytic_one(fixture):
    """The two producers must agree to the last bit or two on lattice geometry.

    This is what lets the stamp treat them as one thing: a nucleotide carrying an analytic
    site and one that was moved and gets a measured site go through identical arithmetic
    afterwards.

    NOT exact, and the reason is worth knowing: the measured producer subtracts the axial
    component before normalising, and for a lattice bead that component is tiny but not
    exactly zero, so it perturbs the last ULP.  It is small enough that a full atomistic
    build comes out byte-identical either way (measured: 0.000e+00 nm over three designs).
    """
    from backend.core.geometry import site_from_bead

    design = _load(fixture)
    checked = 0
    for h in design.helices[:6]:
        for n in nucleotide_positions(effective_helix_for_geometry(h, design)):
            hat, axial = site_from_bead(n.position, n.axis_point, n.axis_tangent)
            assert hat is not None
            assert np.abs(hat - n.radial_hat).max() < 1e-15
            assert abs(axial) < 1e-9        # a lattice bead lies in its own axis plane
            checked += 1
    assert checked > 100


def test_the_scalar_and_array_site_producers_agree():
    """Twins, like ``_strand_beads``: a caller must use one consistently, and they must not
    have drifted apart in what they compute."""
    from backend.core.geometry import site_from_bead, site_from_beads_arrays

    design = _load(PLAIN_HC)
    nucs = [n for h in design.helices[:3]
            for n in nucleotide_positions(effective_helix_for_geometry(h, design))]
    pos = np.array([n.position for n in nucs])
    axp = np.array([n.axis_point for n in nucs])
    axt = np.array([n.axis_tangent for n in nucs])
    hats, axial, ok = site_from_beads_arrays(pos, axp, axt)
    assert ok.all()
    for i, n in enumerate(nucs):
        h_s, a_s = site_from_bead(n.position, n.axis_point, n.axis_tangent)
        assert np.abs(hats[i] - h_s).max() < 1e-15
        assert abs(axial[i] - a_s) < 1e-15


def test_a_bead_on_the_axis_has_no_site():
    """Degenerate case: no radial direction exists, and the caller must be told so rather
    than handed a normalised zero."""
    from backend.core.geometry import site_from_bead, site_from_beads_arrays

    axis_pt = np.array([1.0, 2.0, 3.0])
    tangent = np.array([0.0, 0.0, 1.0])
    hat, axial = site_from_bead(axis_pt + 0.5 * tangent, axis_pt, tangent)
    assert hat is None
    assert axial == pytest.approx(0.5)

    hats, ax, ok = site_from_beads_arrays(
        np.array([axis_pt + 0.5 * tangent]), np.array([axis_pt]), np.array([tangent]))
    assert not ok[0]
    assert np.array_equal(hats[0], np.zeros(3))


def test_a_moved_nucleotide_gets_a_measured_site_not_the_lattice_one():
    """The override contract: move the bead and the atoms follow it.

    This is the same corruption as ``test_the_stamp_ignores_the_bead_and_reads_the_phase``,
    with the opposite expectation — there the phase was carried and the bead ignored, here
    the phase is invalidated (as every override path does) and the bead is authoritative.
    Both must hold, or an override silently applies only its axial component.
    """
    import dataclasses as dc

    import backend.core.geometry as geo
    from backend.core.atomistic import build_atomistic_model

    design = _load(PLAIN_SQ)
    before = build_atomistic_model(design, fast_bridges=True)

    orig = geo.nucleotide_positions

    def moved(helix, compact_skips=False):
        out = []
        for n in orig(helix, compact_skips=compact_skips):
            out.append(dc.replace(
                n, position=n.axis_point + 1.4 * n.radial_hat,
                radial_hat=None, axis_point=None, azimuth_rad=None))
        return out

    geo.nucleotide_positions = moved
    try:
        after = build_atomistic_model(design, fast_bridges=True)
    finally:
        geo.nucleotide_positions = orig

    # The radius change is absorbed (the stamp re-places at its own radius), but the frame
    # must still be built — and identical, because a pure radial move does not rotate it.
    assert len(before.atoms) == len(after.atoms)
    worst = max(abs(a.x - b.x) + abs(a.y - b.y) + abs(a.z - b.z)
                for a, b in zip(before.atoms, after.atoms))
    assert worst < 1e-9, "the measured producer did not reproduce the analytic frame"


# ── Phase 6: the rigid-frame calibration reads sites, not a conf round trip ───


def test_the_rigid_frame_calibration_is_orthonormal_and_complete():
    """Four buckets, each a proper rotation. The function's own ``assert m_res < 1e-6``
    is the drift tripwire; this pins the shape of what it returns."""
    from backend.core.atomistic import _rigid_frame_calibration

    calib = _rigid_frame_calibration()
    assert set(calib) == {("FORWARD", True), ("FORWARD", False),
                          ("REVERSE", True), ("REVERSE", False)}
    for bucket, (Q, c) in calib.items():
        Q = np.asarray(Q, dtype=float)
        assert np.abs(Q @ Q.T - np.eye(3)).max() < 1e-12, bucket
        assert float(np.linalg.det(Q)) == pytest.approx(1.0, abs=1e-12), bucket
        assert np.asarray(c, dtype=float).shape == (3,)


def test_the_rigid_frame_calibration_does_not_touch_the_display_serialiser():
    """FIREWALL: a cached constant must not depend on the DISPLAY path.

    It used to write an oxDNA .dat through ``_geometry_for_design`` and read it back, so a
    display-side default — measured re-placement, the junction-balance roll — could have
    moved it, and the text format quantised every frame to 8.5e-7 nm (measured round-trip
    perturbation: 4.3e-7 nm in position, 5.0e-7 in a1) with that noise landing in the fit's
    own residual.  Breaking the serialiser must now be invisible to it.
    """
    import backend.core.design_geometry as dg
    from backend.core.atomistic import _rigid_frame_calibration

    _rigid_frame_calibration.cache_clear()
    orig = dg._geometry_for_design

    def explode(*a, **k):                      # noqa: ANN002, ANN003
        raise AssertionError("the calibration reached the display serialiser")

    dg._geometry_for_design = explode
    try:
        calib = _rigid_frame_calibration()
    finally:
        dg._geometry_for_design = orig
        _rigid_frame_calibration.cache_clear()
    assert len(calib) == 4
