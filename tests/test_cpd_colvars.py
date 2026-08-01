"""Colvars emission for the CPD weld — backend/core/cpd_colvars.py.

The load-bearing test here is the **1-based atom numbering**. Colvars indexes atoms from
1 as NAMD does; the serials on a weld pair are 0-based MDAnalysis indices. An off-by-one
does not error — it restrains a different, nearby atom and yields a plausible, wrong free
energy. That is exactly the class of bug this whole project exists to avoid, so it is
pinned against the hand-written reference config that predates the emitter.
"""

from __future__ import annotations

import re

import pytest

from backend.core import cpd_colvars as cc

# The real 2hb_1xT pair, serials as resolve_weld_serials returns them (0-based).
PAIR = {
    "id": "xa:0~xb:0", "label": "xa[k=0]~xb[k=0]",
    "segid_a": "D000", "resid_a": 8, "segid_b": "D001", "resid_b": 15,
    "c5_a": 241, "c6_a": 233, "c5_b": 948, "c6_b": 940,
    "serials_resolved": True,
}


def _numbers(block: str, group: str) -> list[int]:
    """atomNumbers of one group in an emitted block."""
    m = re.search(rf"{group} \{{ atomNumbers \{{ ([\d ]+?) \}}", block)
    assert m, f"{group} not found in:\n{block}"
    return [int(v) for v in m.group(1).split()]


# ── the off-by-one ────────────────────────────────────────────────────────────


def test_atom_numbers_are_one_based():
    """Colvars counts atoms from 1; our serials are 0-based MDAnalysis indices."""
    out = cc.colvar_blocks(PAIR)

    assert _numbers(out, "group1") == [242, 234]      # 241, 233 + 1
    assert _numbers(out, "group2") == [949, 941]      # 948, 940 + 1


def test_reference_config_round_trips_to_its_own_serials():
    """The hand-written CPD_1xT/colvars_cpd_metrics.in uses atomNumbers 1520/1512 and
    2084/2076, which its own comment marks as index+1. Feeding the emitter those indices
    must reproduce those numbers exactly — this is the pin against the file that existed
    before the emitter did."""
    ref = {**PAIR, "c5_a": 1519, "c6_a": 1511, "c5_b": 2083, "c6_b": 2075}

    out = cc.colvar_blocks(ref)

    assert _numbers(out, "group1") == [1520, 1512]
    assert _numbers(out, "group2") == [2084, 2076]


def test_dihedral_atom_order_is_c5a_c6a_c6b_c5b():
    """eta is the twist between the two C5=C6 bonds. Swapping the middle pair measures a
    different angle entirely and the rate model would be reading nonsense."""
    out = cc.colvar_blocks(PAIR)
    dihedral = out.split("dihedral {")[1]

    assert _numbers(dihedral, "group1") == [242]      # C5_a
    assert _numbers(dihedral, "group2") == [234]      # C6_a
    assert _numbers(dihedral, "group3") == [941]      # C6_b  (not C5_b)
    assert _numbers(dihedral, "group4") == [949]      # C5_b


# ── structure ─────────────────────────────────────────────────────────────────


def test_metrics_mode_defines_both_cvs_and_biases_nothing():
    out = cc.emit_colvars([PAIR], mode="metrics")

    assert "name d_mid" in out and "name eta" in out
    assert "harmonic {" not in out
    assert "abf {" not in out


def test_umbrella_mode_restrains_d_mid_and_leaves_eta_passive():
    out = cc.emit_colvars([PAIR], mode="umbrella", center_ang=5.5, force_constant=3.0)

    assert "harmonic {" in out
    assert "colvars       d_mid" in out
    assert "centers       5.5" in out
    assert "forceConstant 3" in out
    # eta is defined but never named by a bias
    bias = out.split("harmonic {")[1]
    assert "eta" not in bias


def test_eabf_mode_uses_extended_lagrangian_plus_abf():
    out = cc.emit_colvars([PAIR], mode="eabf")

    assert "extendedLagrangian on" in out
    assert "abf {" in out
    assert "harmonic {" not in out


def test_umbrella_without_a_centre_is_refused():
    with pytest.raises(ValueError, match="center_ang"):
        cc.emit_colvars([PAIR], mode="umbrella")


def test_unknown_mode_is_refused():
    with pytest.raises(ValueError, match="mode"):
        cc.emit_colvars([PAIR], mode="metadynamics")


def test_no_resolved_pair_is_refused_rather_than_emitting_an_empty_config():
    """A config with no colvars would run happily and record nothing."""
    with pytest.raises(ValueError, match="no weld pair"):
        cc.emit_colvars([{**PAIR, "serials_resolved": False}], mode="metrics")
    with pytest.raises(ValueError, match="no weld pair"):
        cc.emit_colvars([], mode="metrics")


def test_several_pairs_are_suffixed_and_only_the_first_is_biased():
    """Biasing several distances at once couples them into one landscape nobody asked
    for; the rest ride along as observers."""
    second = {**PAIR, "id": "b", "label": "b", "c5_a": 300, "c6_a": 301,
              "c5_b": 400, "c6_b": 401}

    out = cc.emit_colvars([PAIR, second], mode="umbrella", center_ang=6.0)

    assert "name d_mid_1" in out and "name d_mid_2" in out
    assert "name eta_1" in out and "name eta_2" in out
    assert "colvars       d_mid_1" in out
    assert "colvars       d_mid_2" not in out


def test_frequencies_are_configurable_and_land_in_the_output():
    out = cc.emit_colvars([PAIR], mode="metrics", traj_freq=250, restart_freq=5000)

    assert "colvarsTrajFrequency     250" in out
    assert "colvarsRestartFrequency  5000" in out


# ── the window ladder ─────────────────────────────────────────────────────────


def test_ladder_spans_the_requested_range_ascending():
    w = cc.umbrella_windows(3.5, 12.0)

    centers = [x["center_ang"] for x in w]
    assert centers == sorted(centers)
    assert centers[0] == 3.5
    assert centers[-1] <= 12.0
    assert centers[-1] > 11.0, "must actually reach the far end"


def test_ladder_is_dense_and_stiff_where_the_rings_interact():
    """The free energy varies fastest at short range, so those windows are closer
    together and held by a stiffer spring."""
    w = cc.umbrella_windows(3.5, 12.0, spacing_ang=0.5, wide_spacing_ang=1.0,
                            dense_below_ang=7.0)

    near = [x for x in w if x["center_ang"] < 7.0]
    far = [x for x in w if x["center_ang"] >= 7.0]
    near_gaps = [round(b["center_ang"] - a["center_ang"], 3)
                 for a, b in zip(near, near[1:])]
    far_gaps = [round(b["center_ang"] - a["center_ang"], 3)
                for a, b in zip(far, far[1:])]

    assert set(near_gaps) == {0.5}
    assert set(far_gaps) == {1.0}
    assert all(x["force_constant"] > far[0]["force_constant"] for x in near)


def test_ladder_refuses_an_inverted_range():
    with pytest.raises(ValueError):
        cc.umbrella_windows(12.0, 3.5)


def test_ladder_windows_emit_one_config_each():
    windows = cc.umbrella_windows(3.5, 5.0, spacing_ang=0.5)

    configs = [cc.emit_colvars([PAIR], mode="umbrella", **{
        "center_ang": w["center_ang"], "force_constant": w["force_constant"]})
        for w in windows]

    assert len(configs) == len(windows)
    assert all("harmonic {" in c for c in configs)
    # each window restrains a different centre — otherwise the ladder samples one point
    assert len({re.search(r"centers\s+(\S+)", c).group(1) for c in configs}) == len(windows)
