"""Periodic-cell diagnostics: box-trace settling, collapse detection, envelope sizing.

The reference numbers are the measured ones from the 2hb_1xT runs
(`experiments/exp47_protocol_delta/RESULTS.md`), so a regression here means the check
that was missing when that run collapsed has stopped working.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.core.md_cell_health import (
    box_adequacy,
    COLLAPSE_VOLUME_FRAC,
    DEFAULT_MAX_LINEAR_DRIFT_FRAC,
    box_from_envelope,
    is_collapsing,
    min_image_distance,
    parse_xst,
    settle_report,
    solute_envelope,
    volume_fraction,
    volumes,
)

XST_HEADER = (
    "# NAMD extended system trajectory file\n"
    "#$LABELS step a_x a_y a_z b_x b_y b_z c_x c_y c_z o_x o_y o_z\n"
)


def _xst(steps_and_cells) -> str:
    out = [XST_HEADER.rstrip("\n")]
    for step, a, b, c in steps_and_cells:
        out.append(f"{step} {a} 0 0 0 {b} 0 0 0 {c} 0 0 0")
    return "\n".join(out) + "\n"


# ── parsing ───────────────────────────────────────────────────────────────────
def test_parse_xst_reads_diagonal_and_skips_comments_and_torn_lines():
    text = _xst([(0, 44.147, 66.635, 113.568), (500, 44.0, 66.5, 113.4)])
    text += "1000 44.0 0 0 0 66.5\n"  # torn trailing line, must be dropped
    rows = parse_xst(text)
    assert rows.shape == (2, 4)
    assert rows[0].tolist() == pytest.approx([0, 44.147, 66.635, 113.568])
    assert volumes(rows)[0] == pytest.approx(44.147 * 66.635 * 113.568)


def test_parse_xst_empty_text_is_empty_not_an_error():
    assert parse_xst(XST_HEADER).shape == (0, 4)


# ── settling ──────────────────────────────────────────────────────────────────
def _trace(v_frac_by_ps, timestep_fs=4.0, a0=44.147, b0=66.635, c0=113.568):
    """Build an xst whose volume follows the given (ps, fraction) schedule."""
    rows = []
    for ps, frac in v_frac_by_ps:
        s = frac ** (1.0 / 3.0)
        rows.append((int(ps * 1000 / timestep_fs), a0 * s, b0 * s, c0 * s))
    return parse_xst(_xst(rows))


def test_a_correctly_filled_box_passes():
    # MEASURED: the full-water-box 2hb_1xT ladder trimmed to 0.926 of its volume
    # (2.5 % of cell length) in the first stage and then held.  That must pass.
    rows = _trace(
        [
            (0, 1.0),
            (100, 0.95),
            (200, 0.930),
            (300, 0.926),
            (500, 0.926),
            (800, 0.9265),
            (1000, 0.926),
        ]
    )
    rep = settle_report(rows, timestep_fs=4.0)
    assert rep["ok"] is True
    assert rep["linear_drift_frac"] == pytest.approx(-0.025, abs=2e-3)
    assert rep["drift_frac"] == pytest.approx(-0.074, abs=2e-3)
    assert rep["settled_from_ps"] is not None and rep["settled_from_ps"] <= 300.0


def test_collapsing_box_fails_the_drift_limit():
    # MEASURED: the carved 2hb_1xT cell fell to 0.618 of its volume (14.8 % of length)
    # and was still marching at the end
    rows = _trace([(0, 1.0), (250, 0.87), (500, 0.78), (750, 0.70), (1000, 0.618)])
    rep = settle_report(rows, timestep_fs=4.0)
    assert rep["ok"] is False
    assert rep["linear_drift_frac"] < -0.10
    assert "does not contain the right amount of water" in rep["reason"]


def test_the_gate_is_on_cell_LENGTH_not_volume():
    # 7.4 % by volume is only 2.5 % by length; gating on volume at 3 % would have
    # rejected the correctly filled box that this project actually built.
    rows = _trace([(0, 1.0), (300, 0.926), (1000, 0.926)])
    rep = settle_report(rows, timestep_fs=4.0)
    assert abs(rep["drift_frac"]) > 0.03  # would fail a naive volume gate
    assert abs(rep["linear_drift_frac"]) < 0.03
    assert rep["ok"] is True


def _ramp(v_start, v_end, span_ps=1000.0, n=200):
    """A DENSE, steadily-marching trace — a real .xst has hundreds of samples, and the
    flatness test compares block means, so it needs realistic density to be meaningful."""
    return _trace(
        [
            (span_ps * i / (n - 1), v_start + (v_end - v_start) * i / (n - 1))
            for i in range(n)
        ]
    )


def test_box_still_moving_after_settle_window_fails_even_when_drift_is_small():
    # -1.7 % of cell length is inside the drift limit, so this isolates the FLATNESS
    # criterion: the cell never stops moving, and that alone must fail it.
    rep = settle_report(_ramp(1.0, 0.95), timestep_fs=4.0)
    assert abs(rep["linear_drift_frac"]) < DEFAULT_MAX_LINEAR_DRIFT_FRAC
    assert rep["flat_after_settle"] is False
    assert rep["ok"] is False
    assert "still moving" in rep["reason"]


def test_thermal_volume_noise_does_not_trip_the_flatness_gate():
    """MEASURED false positive: a 2 ns arm with 0.43 % total drift, 100 % of base pairs
    intact and -0.19 % energy drift was scored "not settled" when flatness compared raw
    samples to the final value.  A 33k-atom cell fluctuates ~0.24 % in volume, so a
    1 % raw-sample band trips on a 4-sigma excursion.  Block means fix it."""
    rng = np.random.default_rng(0)
    settled = _ramp(1.0, 0.995)
    settled[:, 1:] *= 1.0 + rng.normal(0, 0.0024 / 3, size=(len(settled), 3))
    rep = settle_report(settled, timestep_fs=4.0)
    assert rep["ok"] is True


def test_short_trace_is_undecided_not_passed():
    rows = _trace([(0, 1.0), (50, 0.999), (100, 0.998)])
    rep = settle_report(rows, timestep_fs=4.0)
    assert rep["ok"] is None  # crucially not True
    assert "needs 300" in rep["reason"]


def test_settle_report_on_too_few_samples():
    assert settle_report(parse_xst(XST_HEADER), timestep_fs=4.0)["ok"] is None


# ── collapse discrimination ───────────────────────────────────────────────────
def test_is_collapsing_separates_the_two_MEASURED_2hb_runs():
    trim = _trace([(0, 1.0), (300, 0.926)])  # full water box — legitimate
    crash = _trace([(0, 1.0), (300, 0.670)])  # carved, at the patch-grid crash
    settled = _trace([(0, 1.0), (300, 0.618)])  # carved, at its equilibrium volume
    assert volume_fraction(trim) == pytest.approx(0.926, abs=1e-3)
    assert not is_collapsing(trim)
    assert is_collapsing(crash)
    assert is_collapsing(settled)


def test_collapse_floor_sits_between_the_measured_trim_and_crash_volumes():
    # the legitimate full-box trim bottoms out at 0.926; the carved run had already
    # lost enough volume to crash by 0.67.  The floor must separate them.
    assert 0.67 < COLLAPSE_VOLUME_FRAC < 0.926


# ── envelope + sizing ─────────────────────────────────────────────────────────
def _rod(length=88.0, radius=10.0, n=200, axis=2):
    """A crude rod of atoms along ``axis``."""
    xyz = np.zeros((n, 3))
    xyz[:, axis] = np.linspace(-length / 2, length / 2, n)
    xyz[:, (axis + 1) % 3] = radius * np.sign(np.arange(n) % 2 - 0.5)
    return xyz


def test_solute_envelope_single_frame_describes_the_build_pose():
    env = solute_envelope([_rod()])
    assert env["n_frames"] == 1
    assert env["extent_ang"]["p95"][2] == pytest.approx(88.0, abs=1e-6)
    # radius from the centroid is ~ half the length (plus the off-axis offset)
    assert env["radius_ang"]["max"] == pytest.approx(np.hypot(44.0, 10.0), abs=1e-6)


def test_solute_envelope_over_an_ensemble_captures_rotation():
    # same rod, rotated onto x in half the frames: per-axis extent grows, radius does not
    frames = [_rod(axis=2), _rod(axis=0), _rod(axis=2), _rod(axis=0)]
    env = solute_envelope(frames)
    assert env["extent_ang"]["max"][0] == pytest.approx(88.0, abs=1e-6)
    assert env["extent_ang"]["max"][2] == pytest.approx(88.0, abs=1e-6)
    assert env["radius_ang"]["max"] == pytest.approx(np.hypot(44.0, 10.0), abs=1e-6)


def test_rotation_mode_is_orientation_proof_and_bbox_mode_is_not():
    env = solute_envelope([_rod()])  # rod along z only
    bbox = box_from_envelope(env, padding_nm=1.2, mode="bbox")
    rot = box_from_envelope(env, padding_nm=1.2, mode="rotation")
    # bbox's thin axis cannot even contain the rod's length — the failure mode: one
    # rotation puts 88 A of solute into an axis sized for its 20 A cross-section
    assert bbox[0] * 10.0 < 88.0 < bbox[2] * 10.0
    # rotation is cubic and fits the rod on every axis with the padding intact
    assert rot[0] == rot[1] == rot[2]
    assert rot[0] * 10.0 >= 88.0 + 2 * 12.0


def test_box_from_envelope_honours_padding_and_percentile():
    env = solute_envelope([_rod()])
    small = box_from_envelope(env, padding_nm=1.2, mode="rotation")
    big = box_from_envelope(env, padding_nm=2.0, mode="rotation")
    assert big[0] - small[0] == pytest.approx(2 * (2.0 - 1.2), abs=1e-9)
    assert box_from_envelope(
        env, 1.2, mode="axis", percentile="p50"
    ) == box_from_envelope(env, 1.2, mode="bbox", percentile="max")  # single frame


def test_box_from_envelope_rejects_unknown_mode_and_percentile():
    env = solute_envelope([_rod()])
    with pytest.raises(ValueError):
        box_from_envelope(env, 1.2, mode="nope")
    with pytest.raises(ValueError):
        box_from_envelope(env, 1.2, percentile="p99")


def test_solute_envelope_rejects_bad_input():
    with pytest.raises(ValueError):
        solute_envelope([])
    with pytest.raises(ValueError):
        solute_envelope([np.zeros((0, 3))])


# ── box adequacy ──────────────────────────────────────────────────────────────
def test_box_adequacy_reproduces_the_2hb_failure():
    """The real numbers: a 2hb build bbox of 20.2 x 42.6 x 88.1 A padded by 12 A gives
    44.1 x 66.6 x 113.6 A — which passes as-built and fails the moment it rotates
    (r_max 47.2 A needs 94.4 A on every axis)."""
    env = {"extent_ang": {"p95": [20.2, 42.6, 88.1]}, "radius_ang": {"p95": 47.2}}
    rep = box_adequacy((4.4147, 6.6635, 11.3568), env, padding_nm=1.2)
    assert rep["fits_as_built"] is True
    assert rep["fits_rotated"] is False
    assert rep["image_gap_rotated_ang"] < 0  # images overlap once it turns
    assert rep["image_clearance_ok"] is False


def test_box_adequacy_passes_a_rotation_proof_box():
    env = {"extent_ang": {"p95": [20.2, 42.6, 88.1]}, "radius_ang": {"p95": 47.2}}
    side = (2 * 47.2 + 2 * 15.0) / 10.0  # r_max + 15 A padding, cubic
    rep = box_adequacy((side, side, side), env, padding_nm=1.5)
    assert rep["fits_as_built"] and rep["fits_rotated"]
    assert rep["image_gap_rotated_ang"] == pytest.approx(30.0, abs=1e-6)
    assert rep["image_clearance_ok"] is True  # 30 A > 2 x 12 A cutoff


def test_box_adequacy_image_gate_is_stricter_than_the_padding_gate():
    """A box can honour its padding and still leave the solute interacting with its
    own image — 8 A of padding is 16 A of image gap, under the 24 A the cutoff needs."""
    env = {"extent_ang": {"p95": [50.0, 50.0, 50.0]}, "radius_ang": {"p95": 25.0}}
    rep = box_adequacy((6.6, 6.6, 6.6), env, padding_nm=0.8)
    assert rep["fits_rotated"] is True
    assert rep["image_clearance_ok"] is False


# ── image clearance ───────────────────────────────────────────────────────────
def test_min_image_distance_matches_the_gap_for_a_centred_blob():
    # a 10 A cube of atoms in a 50 A box: nearest image gap is 50 - 10 = 40 A
    g = np.linspace(-5, 5, 4)
    xyz = np.array(np.meshgrid(g, g, g)).reshape(3, -1).T
    assert min_image_distance(xyz, [50.0, 50.0, 50.0]) == pytest.approx(40.0, abs=1e-6)


def test_min_image_distance_flags_a_solute_wider_than_its_box():
    # 60 A of solute in a 50 A box — images overlap, so the distance collapses
    xyz = np.stack([np.linspace(-30, 30, 61), np.zeros(61), np.zeros(61)], axis=1)
    assert min_image_distance(xyz, [50.0, 50.0, 50.0]) < 1.0
