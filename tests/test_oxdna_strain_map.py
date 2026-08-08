"""Per-nucleotide local-strain map (oxdna_health.strain_map) — the false-colouring
feed for the oxDNA "Strain map" visualization.

Both metrics are pure geometry over a position map, so the design is stubbed out
(``backbone_bond_pairs`` monkeypatched) exactly as the sibling
``test_backbone_strain_field_aggregates_per_bp`` does.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.core import oxdna_health as health
from backend.core.constants import OXDNA_LENGTH_UNIT

R0 = health.FENE_R0_OXDNA2
HR0 = health.HYDR_R0_OXDNA2
U = OXDNA_LENGTH_UNIT


def _measured(res):
    """(helix, bp) of the positions that actually carry a strain VALUE."""
    return {
        (p["helix_id"], p["bp_index"])
        for p in res["positions"]
        if p["strain"] is not None
    }


def _emitted(res):
    """(helix, bp) of every emitted position — the overlay's MOVE list."""
    return {(p["helix_id"], p["bp_index"]) for p in res["positions"]}


def _nt(pos, a1=(1.0, 0.0, 0.0)):
    return {
        "backbone_position": np.asarray(pos, dtype=float),
        "a1": np.asarray(a1, dtype=float),
        "a3": np.array([0.0, 0.0, 1.0]),
    }


@pytest.fixture
def identity_site(monkeypatch):
    """Backbone site == the stored position, so bond lengths are exactly the spacing
    written in the fixture (the reconstruction itself is tested elsewhere).  Both the
    scalar and the batched reconstruction are stubbed — the strain path uses the batched
    one, and an un-stubbed sibling would silently reintroduce the real offset."""
    monkeypatch.setattr(
        health, "oxdna_backbone_site", lambda pos, a1, a3: np.asarray(pos, float)
    )
    monkeypatch.setattr(
        health, "oxdna_backbone_sites", lambda cm, a1, a3: np.asarray(cm, float)
    )


def test_backbone_strain_is_signed_and_worst_bond_wins(identity_site, monkeypatch):
    """Signed (bond/R0 − 1), attributed to both endpoints by LARGEST MAGNITUDE."""
    a, b, c = ("H", 0, "FORWARD"), ("H", 1, "FORWARD"), ("H", 2, "FORWARD")
    monkeypatch.setattr(health, "backbone_bond_pairs", lambda design: [(a, b), (b, c)])
    full_map = {
        a: _nt([0.0, 0, 0]),
        b: _nt([R0 * U, 0, 0]),  # a–b at R0 → 0 strain
        c: _nt([R0 * U + 0.6 * U, 0, 0]),  # b–c = 0.6 units → compressed, in-window
    }
    res = health.strain_map(object(), full_map, metric="backbone")
    by = {(p["helix_id"], p["bp_index"]): p["strain"] for p in res["positions"]}
    assert by[("H", 0)] == pytest.approx(0.0, abs=1e-9)
    assert by[("H", 2)] == pytest.approx(
        0.6 / R0 - 1.0, abs=1e-9
    )  # negative == compressed
    assert by[("H", 1)] == pytest.approx(
        0.6 / R0 - 1.0, abs=1e-9
    )  # worst of its two bonds
    assert res["min_strain"] == pytest.approx(0.6 / R0 - 1.0, abs=1e-9)
    assert res["max_strain"] == pytest.approx(0.0, abs=1e-9)
    assert res["abs_max_strain"] == pytest.approx(1.0 - 0.6 / R0, abs=1e-9)
    assert res["metric"] == "backbone" and res["n_shared"] == 3


def test_backbone_strain_tension_is_positive(identity_site, monkeypatch):
    a, b = ("H", 0, "FORWARD"), ("H", 1, "FORWARD")
    monkeypatch.setattr(health, "backbone_bond_pairs", lambda design: [(a, b)])
    full_map = {a: _nt([0.0, 0, 0]), b: _nt([0.95 * U, 0, 0])}
    res = health.strain_map(object(), full_map, metric="backbone")
    assert all(
        p["strain"] == pytest.approx(0.95 / R0 - 1.0, abs=1e-9)
        for p in res["positions"]
    )


def test_backbone_strain_skips_nucleotides_absent_from_the_frame(
    identity_site, monkeypatch
):
    """A bond whose partner is missing from the position map contributes nothing, and a
    nucleotide left with no measurable bond gets strain=None (not 0) — while still being
    EMITTED, so it moves with the structure."""
    a, b, ghost = ("H", 0, "FORWARD"), ("H", 1, "FORWARD"), ("H", 9, "FORWARD")
    monkeypatch.setattr(
        health, "backbone_bond_pairs", lambda design: [(a, b), (b, ghost)]
    )
    full_map = {
        a: _nt([0.0, 0, 0]),
        b: _nt([R0 * U, 0, 0]),
        ("H", 5, "FORWARD"): _nt([50.0, 0, 0]),
    }
    res = health.strain_map(object(), full_map, metric="backbone")
    assert _measured(res) == {("H", 0), ("H", 1)}
    assert _emitted(res) == {("H", 0), ("H", 1), ("H", 5)}


def test_backbone_strain_broadcasts_to_loop_copies(identity_site, monkeypatch):
    """4-tuple loop-copy keys share their base bp's strain, so every loop bead colours."""
    a, b = ("H", 0, "FORWARD"), ("H", 1, "FORWARD")
    monkeypatch.setattr(health, "backbone_bond_pairs", lambda design: [(a, b)])
    full_map = {
        ("H", 0, "FORWARD", 0): _nt([0.0, 0, 0]),
        ("H", 1, "FORWARD", 0): _nt([0.95 * U, 0, 0]),
        ("H", 1, "FORWARD", 1): _nt([1.05 * U, 0, 0]),  # loop copy of bp 1
    }
    res = health.strain_map(object(), full_map, metric="backbone")
    assert len(res["positions"]) == 3
    assert {p["copy"] for p in res["positions"]} == {0, 1}
    assert all(
        p["strain"] == pytest.approx(0.95 / R0 - 1.0, abs=1e-9)
        for p in res["positions"]
    )


def test_wc_strain_measures_base_site_separation(identity_site):
    """(|base_F − base_R| / HYDR_R0 − 1), both partners tagged; base site = CM + POS_BASE·a1."""
    d = health.OXDNA_BASE_SITE_NM
    gap = 1.0 * U  # 1.0 oxDNA unit between the two CMs
    full_map = {
        ("H", 0, "FORWARD"): _nt([0.0, 0, 0], a1=(1.0, 0, 0)),
        ("H", 0, "REVERSE"): _nt([gap + 2 * d, 0, 0], a1=(-1.0, 0, 0)),
    }
    # base sites sit at +d and (gap + 2d) − d = gap + d  →  separation exactly `gap`
    res = health.strain_map(object(), full_map, metric="wc")
    assert res["n_shared"] == 2
    assert all(
        p["strain"] == pytest.approx(1.0 / HR0 - 1.0, abs=1e-9)
        for p in res["positions"]
    )
    assert res["metric"] == "wc" and res["r0_units"] == pytest.approx(HR0)


def test_wc_strain_leaves_unpaired_nucleotides_unmeasured_but_emitted(identity_site):
    """ssDNA loops / overhangs / ragged ends have no designed partner, so they carry no WC
    VALUE — but they are still emitted, because `positions` is also the move list."""
    full_map = {
        ("H", 0, "FORWARD"): _nt([0.0, 0, 0], a1=(1.0, 0, 0)),
        ("H", 0, "REVERSE"): _nt([1.0 * U, 0, 0], a1=(-1.0, 0, 0)),
        ("H", 1, "FORWARD"): _nt([5.0, 0, 0], a1=(1.0, 0, 0)),  # unpaired overhang
    }
    res = health.strain_map(object(), full_map, metric="wc")
    assert {
        (p["helix_id"], p["bp_index"], p["direction"])
        for p in res["positions"]
        if p["strain"] is not None
    } == {("H", 0, "FORWARD"), ("H", 0, "REVERSE")}
    assert res["n_positions"] == 3, "the unpaired overhang is still emitted so it moves"


def test_empty_map_reports_nothing_measurable(identity_site, monkeypatch):
    monkeypatch.setattr(health, "backbone_bond_pairs", lambda design: [])
    res = health.strain_map(object(), {}, metric="backbone")
    assert res["n_shared"] == 0 and res["positions"] == []
    assert res["min_strain"] is None and res["abs_max_strain"] is None


def test_unknown_metric_rejected():
    with pytest.raises(ValueError, match="unknown metric"):
        health.strain_map(object(), {}, metric="curvature")
    with pytest.raises(ValueError, match="unknown metric"):
        health.strain_field(object(), {}, metric="curvature")


def test_field_override_supplies_values_while_full_map_supplies_geometry(
    identity_site, monkeypatch
):
    """The trajectory map passes ⟨strain⟩ via `field=` and uses `full_map` ONLY for the
    displayed positions — the two must not be re-derived from each other."""
    a, b = ("H", 0, "FORWARD"), ("H", 1, "FORWARD")
    monkeypatch.setattr(health, "backbone_bond_pairs", lambda design: [(a, b)])
    full_map = {a: _nt([0.0, 0, 0]), b: _nt([R0 * U, 0, 0])}  # this frame is relaxed
    res = health.strain_map(
        object(), full_map, metric="backbone", field={a: 0.25, b: -0.5}
    )
    by = {(p["helix_id"], p["bp_index"]): p for p in res["positions"]}
    assert by[("H", 0)]["strain"] == pytest.approx(
        0.25
    )  # from `field`, not the geometry
    assert by[("H", 1)]["strain"] == pytest.approx(-0.5)
    assert by[("H", 1)]["backbone_position"] == pytest.approx(
        [R0 * U, 0, 0]
    )  # from full_map
    assert res["abs_max_strain"] == pytest.approx(0.5)


def test_field_override_omits_nucleotides_it_does_not_cover(identity_site, monkeypatch):
    a, b = ("H", 0, "FORWARD"), ("H", 1, "FORWARD")
    monkeypatch.setattr(health, "backbone_bond_pairs", lambda design: [(a, b)])
    res = health.strain_map(
        object(),
        {a: _nt([0.0, 0, 0]), b: _nt([R0 * U, 0, 0])},
        metric="backbone",
        field={a: 0.1},
    )
    assert _measured(res) == {("H", 0)}
    assert _emitted(res) == {("H", 0), ("H", 1)}


def test_mean_strain_over_frames_is_not_the_strain_of_the_mean_structure(
    identity_site, monkeypatch
):
    """Why the route averages the FIELD, not the STRUCTURE: a bond that breathes ±d has a
    real mean strain, but the averaged positions put it exactly at r0 (strain 0)."""
    a, b = ("H", 0, "FORWARD"), ("H", 1, "FORWARD")
    monkeypatch.setattr(health, "backbone_bond_pairs", lambda design: [(a, b)])
    short = {a: _nt([0.0, 0, 0]), b: _nt([(R0 - 0.2) * U, 0, 0])}
    long_ = {a: _nt([0.0, 0, 0]), b: _nt([(R0 + 0.2) * U, 0, 0])}
    mean_structure = {
        a: _nt([0.0, 0, 0]),
        b: _nt([R0 * U, 0, 0]),
    }  # the average position
    per_frame = [
        health.strain_field(object(), f, metric="backbone")[a] for f in (short, long_)
    ]
    assert np.mean(per_frame) == pytest.approx(0.0, abs=1e-9)  # symmetric here…
    assert np.mean(np.abs(per_frame)) > 0.25  # …but each frame IS strained
    assert health.strain_field(object(), mean_structure, metric="backbone")[
        a
    ] == pytest.approx(0.0)


# ── 5′/3′ strand-extension tails + crossover extra bases ─────────────────────────
# Tail keys are ("__ext_<id>", bead_index, direction) — 3-tuples whose bp_index slot is
# an int >= 0, so they PASS every `isinstance(k[1], int)` filter.  See
# memory/project_strand_extensions_sim.md.


def test_backbone_strain_measures_extension_tail_bonds(identity_site, monkeypatch):
    """A tail's bonds are the most FENE-fragile in a design — the backbone map must
    measure them, including the anchor→bead0 bond."""
    anchor = ("H", 4, "FORWARD")
    t0, t1 = ("__ext_9", 0, "FORWARD"), ("__ext_9", 1, "FORWARD")
    monkeypatch.setattr(
        health, "backbone_bond_pairs", lambda design: [(anchor, t0), (t0, t1)]
    )
    full_map = {
        anchor: _nt([0.0, 0, 0]),
        t0: _nt([R0 * U, 0, 0]),  # anchor→bead0 relaxed
        t1: _nt([R0 * U + 0.55 * U, 0, 0]),  # bead0→bead1 badly too SHORT
    }
    res = health.strain_map(object(), full_map, metric="backbone")
    by = {(p["helix_id"], p["bp_index"]): p["strain"] for p in res["positions"]}
    assert set(by) == {("H", 4), ("__ext_9", 0), ("__ext_9", 1)}
    assert by[("__ext_9", 1)] == pytest.approx(0.55 / R0 - 1.0, abs=1e-9)
    assert by[("__ext_9", 0)] == pytest.approx(
        0.55 / R0 - 1.0, abs=1e-9
    )  # worst of its two
    assert by[("H", 4)] == pytest.approx(0.0, abs=1e-9)  # anchor bond is fine


def test_wc_strain_never_pairs_synthetic_particles(identity_site):
    """Tails and extra bases are unpaired ssDNA: they must not form a phantom WC pair
    with each other, even though their keys look like real (helix, bp, direction)."""
    full_map = {
        ("H", 0, "FORWARD"): _nt([0.0, 0, 0], a1=(1.0, 0, 0)),
        ("H", 0, "REVERSE"): _nt([1.0 * U, 0, 0], a1=(-1.0, 0, 0)),
        # a 5′ tail and a 3′ tail that happen to share a bead index + opposite directions
        ("__ext_1", 0, "FORWARD"): _nt([9.0, 0, 0], a1=(1.0, 0, 0)),
        ("__ext_1", 0, "REVERSE"): _nt([9.1, 0, 0], a1=(-1.0, 0, 0)),
    }
    res = health.strain_map(object(), full_map, metric="wc")
    assert _measured(res) == {("H", 0)}, "the two tails must not read as a WC pair"
    assert all(p["ss"] for p in res["positions"] if p["helix_id"] == "__ext_1")


def test_strain_map_does_not_coerce_a_synthetic_bp_index(identity_site, monkeypatch):
    """An extra-base key's bp_index slot holds a crossover id, which may be a STRING —
    int()-coercing it (as an early version did) throws."""
    xb0, xb1 = ("__xb__", "xo-abc", 0), ("__xb__", "xo-abc", 1)
    monkeypatch.setattr(health, "backbone_bond_pairs", lambda design: [(xb0, xb1)])
    full_map = {xb0: _nt([0.0, 0, 0]), xb1: _nt([R0 * U, 0, 0])}
    res = health.strain_map(object(), full_map, metric="backbone")
    assert [p["bp_index"] for p in res["positions"]] == ["xo-abc", "xo-abc"]
    assert [p["direction"] for p in res["positions"]] == [0, 1]


def test_backbone_rejects_bonds_outside_the_fene_window(identity_site, monkeypatch):
    """A production frame CANNOT hold a bond past r0 ± delta (oxDNA aborts at config
    load), so such a measurement is a PBC-unwrap artifact — drop the sample instead of
    poisoning the average with a box-sized "bond"."""
    a, b, c = ("H", 0, "FORWARD"), ("H", 1, "FORWARD"), ("H", 2, "FORWARD")
    monkeypatch.setattr(health, "backbone_bond_pairs", lambda design: [(a, b), (b, c)])
    full_map = {
        a: _nt([0.0, 0, 0]),
        b: _nt([0.9 * R0 * U, 0, 0]),  # a–b inside the window (−10 %)
        c: _nt([0.9 * R0 * U + 60.0 * U, 0, 0]),  # b–c torn across the box → impossible
    }
    f = health.strain_field(object(), full_map, metric="backbone")
    assert c not in f, "the torn bond's far endpoint has no valid measurement"
    assert f[a] == pytest.approx(0.9 - 1.0, abs=1e-9)
    assert f[b] == pytest.approx(0.9 - 1.0, abs=1e-9), (
        "b keeps its GOOD bond, not the torn one"
    )
    limit = health.FENE_DELTA / R0
    assert all(abs(v) <= limit + 1e-12 for v in f.values())


def test_wc_keeps_large_stretches_because_a_melted_pair_is_real(identity_site):
    """The FENE rejection must NOT apply to `wc`: a pair genuinely can drift apart."""
    full_map = {
        ("H", 0, "FORWARD"): _nt([0.0, 0, 0], a1=(1.0, 0, 0)),
        ("H", 0, "REVERSE"): _nt([6.0 * U, 0, 0], a1=(-1.0, 0, 0)),  # fully melted
    }
    f = health.strain_field(object(), full_map, metric="wc")
    assert f[("H", 0, "FORWARD")] > 5.0


def test_strain_values_reports_how_many_bonds_it_rejected(identity_site, monkeypatch):
    a, b, c = ("H", 0, "FORWARD"), ("H", 1, "FORWARD"), ("H", 2, "FORWARD")
    monkeypatch.setattr(health, "backbone_bond_pairs", lambda design: [(a, b), (b, c)])
    base = {a: _nt([0.0, 0, 0]), b: _nt([R0 * U, 0, 0]), c: _nt([90.0 * U, 0, 0])}
    keys = list(base)
    ia, ib = health._strain_index(object(), keys, "backbone")
    _v, attempted, rejected = health._strain_values(
        *health._gather_frame(base, keys), ia, ib, metric="backbone"
    )
    assert (attempted, rejected) == (2, 1)


# ── designed-ssDNA classification + the "move everything, colour some" contract ──────


def test_designed_ssdna_flags_are_topological():
    """A (helix, bp) with nucleotides on BOTH strands is designed duplex; anything else is
    designed ssDNA — an unstapled scaffold loop, an overhang, a tail, an extra base."""
    full_map = {
        ("H", 0, "FORWARD"): {},
        ("H", 0, "REVERSE"): {},  # duplex
        ("H", 1, "FORWARD"): {},  # unstapled scaffold → ssDNA loop
        ("H", 2, "REVERSE"): {},  # overhang on the other strand
        ("__ext_7", 0, "FORWARD"): {},  # 5'/3' tail
        ("__xb__", "xo-1", 0): {},  # crossover extra base
    }
    ss = health.designed_ssdna_flags(full_map)
    assert ss(("H", 0, "FORWARD")) is False
    assert ss(("H", 0, "REVERSE")) is False
    assert ss(("H", 1, "FORWARD")) is True
    assert ss(("H", 2, "REVERSE")) is True
    assert ss(("__ext_7", 0, "FORWARD")) is True
    assert ss(("__xb__", "xo-1", 0)) is True
    # A loop-insertion copy inherits its base column's classification.
    assert ss(("H", 0, "FORWARD", 1)) is False


def test_synthetic_keys_cannot_fake_a_duplex_column():
    """Two tails of the same extension on opposite directions must not read as duplex."""
    ss = health.designed_ssdna_flags(
        {("__ext_1", 0, "FORWARD"): {}, ("__ext_1", 0, "REVERSE"): {}}
    )
    assert ss(("__ext_1", 0, "FORWARD")) is True


def test_wc_map_emits_unpaired_bases_so_they_still_move(identity_site):
    """`positions` is the overlay's MOVE list, not just its colour list: a base left out
    keeps its DESIGN coordinates while the rest deforms.  Unpaired bases therefore appear
    with strain=None rather than being dropped (2260 stranded beads on VoltronCoreScad)."""
    full_map = {
        ("H", 0, "FORWARD"): _nt([0.0, 0, 0], a1=(1.0, 0, 0)),
        ("H", 0, "REVERSE"): _nt([1.0 * U, 0, 0], a1=(-1.0, 0, 0)),
        ("H", 1, "FORWARD"): _nt([5.0, 0, 0], a1=(1.0, 0, 0)),  # unstapled scaffold
        ("__ext_3", 0, "FORWARD"): _nt([9.0, 0, 0], a1=(1.0, 0, 0)),  # 3' tail
    }
    res = health.strain_map(object(), full_map, metric="wc")
    assert res["n_positions"] == 4, "every bead is emitted so every bead moves"
    assert res["n_shared"] == 2, "only the designed pair is MEASURED"
    by = {(p["helix_id"], p["bp_index"]): p for p in res["positions"]}
    assert by[("H", 1)]["strain"] is None and by[("H", 1)]["ss"] is True
    assert by[("__ext_3", 0)]["strain"] is None and by[("__ext_3", 0)]["ss"] is True
    assert by[("H", 0)]["ss"] is False
    # Every emitted bead carries real coordinates — a None strain must not mean a None pose.
    assert all(len(p["backbone_position"]) == 3 for p in res["positions"])


def test_dsdna_stats_block_excludes_ssdna(identity_site, monkeypatch):
    """The companion stats let the display rescale to the duplex without a refetch."""
    keys = [("H", 0, "FORWARD"), ("H", 0, "REVERSE"), ("H", 1, "FORWARD")]
    monkeypatch.setattr(health, "backbone_bond_pairs", lambda design: [])
    full_map = {k: _nt([float(i), 0, 0]) for i, k in enumerate(keys)}
    field = {keys[0]: 0.01, keys[1]: -0.02, keys[2]: 3.0}  # the ssDNA one is wild
    res = health.strain_map(object(), full_map, metric="backbone", field=field)
    assert res["abs_max_strain"] == pytest.approx(3.0)  # overall includes the ssDNA
    assert res["dsdna"]["n"] == 2
    assert res["dsdna"]["abs_max_strain"] == pytest.approx(0.02)  # duplex-only is tight
    assert res["dsdna"]["display_abs_strain"] < 0.1


def test_dsdna_stats_absent_when_nothing_is_duplex(identity_site, monkeypatch):
    monkeypatch.setattr(health, "backbone_bond_pairs", lambda design: [])
    k = ("__ext_1", 0, "FORWARD")
    res = health.strain_map(
        object(), {k: _nt([0.0, 0, 0])}, metric="backbone", field={k: 0.1}
    )
    assert res["dsdna"] is None


def test_fene_violation_fraction_flags_a_torn_frame(identity_site, monkeypatch):
    """The per-frame gate that protects BOTH metrics: a PBC unwrap that snapped two bonded
    components into different periodic images leaves impossible bonds behind."""
    a, b, c = ("H", 0, "FORWARD"), ("H", 1, "FORWARD"), ("H", 2, "FORWARD")
    monkeypatch.setattr(health, "backbone_bond_pairs", lambda design: [(a, b), (b, c)])
    clean = {a: _nt([0.0, 0, 0]), b: _nt([R0 * U, 0, 0]), c: _nt([2 * R0 * U, 0, 0])}
    torn = {a: _nt([0.0, 0, 0]), b: _nt([R0 * U, 0, 0]), c: _nt([90.0 * U, 0, 0])}
    keys = list(clean)
    ia, ib = health._strain_index(object(), keys, "backbone")
    assert (
        health._fene_violation_fraction(*health._gather_frame(clean, keys), ia, ib)
        == 0.0
    )
    assert health._fene_violation_fraction(
        *health._gather_frame(torn, keys), ia, ib
    ) == pytest.approx(0.5)
    # …and the gate's threshold sits above float noise but far below a torn frame.
    assert 0.0 < health._STRAIN_FRAME_REJECT_FRAC < 0.5


def test_wc_display_bound_ignores_the_melted_mode():
    """Every real origami frays at its ends.  Scaling on both modes would put the whole
    intact duplex on the midpoint colour; scale on the bonded mode instead."""
    intact = [0.02] * 850  # bonded duplex, ~2 %
    frayed = [6.0] * 150  # 15 % melted/frayed, +600 %
    bound = health._display_strain_bound(np.array(intact + frayed), "wc")
    assert bound < health.WC_UNPAIRED_STRAIN, (
        "must not be dragged past the H-bond cutoff"
    )
    assert bound == pytest.approx(0.02, abs=0.01), "scales to the intact duplex"
    # Fully melted structure → nothing bonded → fall back rather than divide by nothing.
    assert health._display_strain_bound(np.array(frayed), "wc") == pytest.approx(6.0)


def test_wc_unpaired_threshold_matches_the_hbond_cutoff():
    """The bonded/unpaired cut is BP_FORMED_CUTOFF_NM expressed in WC-strain units — it
    must track that constant, not be a second hand-tuned number."""
    sep_nm = (1.0 + health.WC_UNPAIRED_STRAIN) * OXDNA_LENGTH_UNIT * HR0
    assert sep_nm == pytest.approx(health.BP_FORMED_CUTOFF_NM, abs=1e-12)


def test_display_bound_is_robust_and_metric_aware():
    """The auto-range half-width must survive a melted-pair tail.  WC uses a LOWER
    percentile than backbone because a broken pair is unbounded while a FENE bond is not."""
    bulk = [0.02] * 90  # intact duplex …
    tail = [3.0] * 10  # … plus 10 % melted pairs at +300 %
    vals = np.array(bulk + tail)
    wc = health._display_strain_bound(vals, "wc")
    bb = health._display_strain_bound(vals, "backbone")
    assert wc < 1.0, "wc bound must not be dragged into the melted tail"
    assert bb > wc, "backbone keeps a high percentile — its tail is FENE-bounded"
    assert health._display_strain_bound(np.array([]), "wc") == 0.0
    # A tight, tail-free field (what a healthy backbone looks like) barely clips at all.
    tight = np.linspace(-0.08, 0.08, 200)
    assert health._display_strain_bound(tight, "backbone") == pytest.approx(
        0.08, abs=0.01
    )


def test_strain_map_reports_a_display_bound_below_the_max_when_outliers_exist(
    identity_site, monkeypatch
):
    keys = [("H", i, "FORWARD") for i in range(21)]
    monkeypatch.setattr(health, "backbone_bond_pairs", lambda design: [])
    full_map = {k: _nt([float(i), 0, 0]) for i, k in enumerate(keys)}
    field = {k: 0.01 for k in keys}
    field[keys[-1]] = 5.0  # one melted outlier
    res = health.strain_map(object(), full_map, metric="wc", field=field)
    assert res["abs_max_strain"] == pytest.approx(5.0)
    assert res["display_abs_strain"] < 1.0


def test_even_indices_spans_the_range_and_never_over_samples():
    assert health._even_indices(10, 3) == [0, 4, 9]  # endpoints included, evenly spread
    assert health._even_indices(5, 99) == [0, 1, 2, 3, 4]  # keep >= n → all frames
    assert health._even_indices(7, 1) == [6]  # a single sample = the LAST frame
    assert health._even_indices(0, 5) == []
    for n, keep in ((100, 60), (61, 60), (3, 2)):
        idx = health._even_indices(n, keep)
        assert len(idx) <= min(n, keep) and idx == sorted(set(idx))
        assert all(0 <= i < n for i in idx)
