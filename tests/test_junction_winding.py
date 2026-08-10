"""Are two crossover strands wound through one another? — backend/core/junction_winding.py.

This is the module that produces the VERDICT, so it needs its own tests rather than only
being exercised through ``catenation_report``.

Most cases here use synthetic threaded/separated arcs rather than built designs: the
question "are these two open curves wound?" is pure geometry, and testing it directly
means a failure points at the measure instead of at the seed builder.

Background for anyone changing thresholds: five closure schemes were tried before this
one and each produced a confident wrong answer — a straight chord flipped the verdict
+1 -> 0 -> -1 across three MD stages of a structure that never moved, whole-strand chords
were degenerate at nicks, closure "at infinity" made the two closure loops link each
other, and average crossing number was confounded by arc length. Hence two channels that
fail differently, and an explicit ``ambiguous`` verdict when they disagree.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.core.junction_winding import (
    clamp_sweep,
    combine,
    fibonacci_directions,
    projected_crossing_number,
    signed_crossings,
)


# ── Fixtures: two open arcs, threaded or not ─────────────────────────────────


def _threaded_arcs(separation=1.0, n=26, seed=None):
    """Two open arcs; ``separation`` ~1 threads them, large values pull them apart."""
    t = np.linspace(0.0, 2.0 * np.pi * 0.88, n)  # open, not closed
    a = np.stack([np.cos(t), np.sin(t), 0.06 * t], axis=1)
    b = np.stack([separation + np.cos(t), 0.06 * t, np.sin(t)], axis=1)
    if seed is not None:
        rng = np.random.default_rng(seed)
        a = a + rng.normal(0.0, 0.02, a.shape)
        b = b + rng.normal(0.0, 0.02, b.shape)
    return a, b


def _rotate(points, axis=(0.3, 0.5, 0.81), angle=0.9):
    axis = np.asarray(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    k = np.array(
        [[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]]
    )
    r = np.eye(3) + np.sin(angle) * k + (1 - np.cos(angle)) * (k @ k)
    return points @ r.T


# ── PCS: the closure-free verdict channel ────────────────────────────────────


def test_threaded_arcs_read_wound():
    """THE entwinement test: two arcs threaded through one another must read wound.

    Asserted on f_hi, not n_mode. On a real wound junction the crossing distribution
    straddles 1 and 2 ({0:1, 1:29, 2:34} over 64 views), so the modal value flips with
    orientation while f_hi does not.
    """
    a, b = _threaded_arcs(separation=1.0)
    result = projected_crossing_number(a, b)
    assert result["f_hi"] >= 0.15
    assert abs(result["n_mode"]) >= 1


def test_separated_arcs_read_clean():
    a, b = _threaded_arcs(separation=8.0)
    result = projected_crossing_number(a, b)
    assert result["n_mode"] == 0
    assert result["f_hi"] < 0.05


@pytest.mark.parametrize("angle", [0.3, 0.9, 1.7, 2.4])
def test_verdict_is_rotation_invariant(angle):
    """No closure and no reference frame ⇒ the VERDICT cannot depend on orientation.

    This is the test that caught the original rule. Views are sampled on a fixed
    lab-frame sphere, so rotating the object changes which views you get: the modal
    crossing number moved 2,2,1,1,1,2 on a real wound junction, which under a
    "|n_mode| >= 2" rule would have scored it CLEAN in half of all orientations.
    f_hi stayed in 0.453-0.562 throughout.
    """
    a, b = _threaded_arcs(separation=1.0)
    base = projected_crossing_number(a, b)
    turned = projected_crossing_number(_rotate(a, angle=angle), _rotate(b, angle=angle))
    assert (base["f_hi"] >= 0.15) == (turned["f_hi"] >= 0.15)
    assert base["f_hi"] == pytest.approx(turned["f_hi"], abs=0.12)


def test_thermal_jitter_does_not_change_the_verdict():
    """The failure mode that broke the chord closure: a jiggled frame must read the same."""
    clean = projected_crossing_number(*_threaded_arcs(separation=8.0, seed=1))
    wound = projected_crossing_number(*_threaded_arcs(separation=1.0, seed=1))
    assert clean["f_hi"] < 0.15
    assert wound["f_hi"] >= 0.15


def test_swapping_the_two_arcs_preserves_the_verdict():
    a, b = _threaded_arcs(separation=1.0)
    assert projected_crossing_number(a, b)["f_hi"] == pytest.approx(
        projected_crossing_number(b, a)["f_hi"], abs=0.05
    )


def test_degenerate_input_does_not_raise():
    a, _ = _threaded_arcs()
    assert projected_crossing_number(a[:1], a[:1])["n_mode"] == 0


def test_single_view_crossing_count_is_an_integer():
    a, b = _threaded_arcs(separation=1.0)
    value = signed_crossings(a, b, np.array([0.0, 0.0, 1.0]))
    assert isinstance(value, int)


def test_view_directions_are_unit_and_deterministic():
    first, second = fibonacci_directions(32), fibonacci_directions(32)
    assert first.shape == (32, 3)
    np.testing.assert_allclose(np.linalg.norm(first, axis=1), 1.0, atol=1e-12)
    np.testing.assert_array_equal(first, second)


# ── Fusing the channels ──────────────────────────────────────────────────────


def _clamp(lk, converged=True):
    return {"lk": lk, "converged": converged, "lk_by_k": {5: lk}, "residual": 0.0}


def test_both_channels_wound_is_confirmed():
    v = combine({"n_mode": 2, "f_hi": 0.50, "n_views": 64}, _clamp(1.0))
    assert v["verdict"] == "wound"
    assert v["confidence"] == "confirmed"


def test_both_channels_clean_is_confirmed():
    v = combine({"n_mode": 0, "f_hi": 0.01, "n_views": 64}, _clamp(0.0))
    assert v["verdict"] == "clean"
    assert v["confidence"] == "confirmed"


def test_disagreement_refuses_to_pick_a_side():
    """The whole point of two channels. Silently choosing one is what produced three
    false alarms during development."""
    v = combine({"n_mode": 2, "f_hi": 0.50, "n_views": 64}, _clamp(0.0))
    assert v["verdict"] == "ambiguous"
    assert v["confidence"] == "channels-disagree"


def test_unconverged_clamp_falls_back_to_the_closure_free_channel():
    """A clamp that never settles is untrustworthy, so PCS decides alone — and the
    report says the verdict rests on one channel."""
    v = combine(
        {"n_mode": 2, "f_hi": 0.50, "n_views": 64}, _clamp(0.4, converged=False)
    )
    assert v["verdict"] == "wound"
    assert v["confidence"] == "single-channel"


def test_verdict_wording_never_claims_strands_are_linked():
    """Two OPEN chains are never topologically linked — they can always be separated.
    The report must describe a bounded window, not assert a theorem."""
    for f_hi, lk in ((0.50, 1.0), (0.01, 0.0)):
        meaning = combine({"n_mode": 0, "f_hi": f_hi, "n_views": 64}, _clamp(lk))[
            "meaning"
        ]
        assert "linked" not in meaning.lower()


# ── The duplex clamp, on a real build ────────────────────────────────────────


#: Helical phases of the reciprocal fixture that do / do not link. The calibrated
#: 1xT default is clean at both phases; the wound positive control therefore uses
#: the still-arc-seeded 2xT run at bp 16, while bp 8 remains clean.
_WOUND_BP = 16
_CLEAN_BP = 8


def _reciprocal_pair_inputs(extra_bases, bp):
    """Build the reciprocal-pair fixture and return what clamp_sweep needs."""
    from backend.core.atomistic import build_atomistic_model
    from backend.core import junction_topology as jt

    from tests.test_junction_topology import _reciprocal_design

    design = _reciprocal_design(extra_bases, bp=bp)
    model = build_atomistic_model(design)

    prep = jt._prepare(design, model, None)
    i, j = jt.reciprocal_pairs(prep.connectors)[0]
    positions = np.array([[a.x, a.y, a.z] for a in model.atoms], dtype=float)
    return (
        jt._residue_lookup(model),
        positions,
        jt._connector_dict(prep.connectors[i]),
        jt._connector_dict(prep.connectors[j]),
        jt._BACKBONE_ORDER,
    )


def test_clamp_converges_and_separates_wound_from_clean():
    """The duplex clamp's self-check: a genuine invariant settles on an integer as the
    rung retreats into the duplex. Wound -> ~1, clean -> ~0, both converged."""
    wound = clamp_sweep(*_reciprocal_pair_inputs("TT", bp=_WOUND_BP))
    clean = clamp_sweep(*_reciprocal_pair_inputs("T", bp=_CLEAN_BP))

    assert wound["converged"] and clean["converged"]
    assert abs(wound["lk"]) > 0.5
    assert abs(clean["lk"]) < 0.5

    # convergence is monotone toward the integer, which is what makes it trustworthy
    by_k = wound["lk_by_k"]
    ks = sorted(by_k)
    assert abs(by_k[ks[-1]] - round(by_k[ks[-1]])) < abs(
        by_k[ks[0]] - round(by_k[ks[-1]])
    )


def test_a_wound_junction_survives_the_orientation_that_breaks_n_mode():
    """Regression for the false negative: a real wound junction read n_mode = 1 at some
    orientations. The verdict must still be 'wound' there."""
    v = combine({"n_mode": 1, "f_hi": 0.484, "n_views": 64}, _clamp(0.98))
    assert v["verdict"] == "wound"
    assert v["confidence"] == "confirmed"
