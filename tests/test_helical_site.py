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
