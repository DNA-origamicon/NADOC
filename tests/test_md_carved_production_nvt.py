"""A carved cell must stay at constant volume in EVERY stage, production included.

The relax ladder has always honoured this (``mgh_slow_release_segments(nvt_only=...)``),
but ``build_production_conf`` and ``build_reseed_conf`` hardcoded ``langevinPiston on``.
That gap is how the 2hb_1xT 200 ns run came to sit in a cell that had collapsed 38 % by
volume with the DNA touching its own periodic image
(``experiments/exp47_protocol_delta/RESULTS.md``).
"""

from __future__ import annotations

import json

import pytest

from backend.core.md_protocols import (
    SegmentSpec,
    build_production_conf,
    build_reseed_conf,
    package_npt_allowed,
)

BOX = (44.147, 66.635, 113.568)


def _prod_spec(steps: int = 500_000) -> SegmentSpec:
    return SegmentSpec(
        name="S_01_production_2ns_k0",
        stage="2 ns production",
        percent=100.0,
        steps=steps,
        temp=300.0,
        damping=5.0,
        scale=None,
        npt=True,
        previous="S_00_reseed",
        reinit=False,
    )


def _conf(npt: bool) -> str:
    return build_production_conf(
        _prod_spec(),
        "S",
        BOX,
        True,
        fast=True,
        timestep_fs=4.0,
        structure_psf="S_hmr.psf",
        npt=npt,
    )


def test_production_barostat_follows_the_npt_flag():
    on, off = _conf(True), _conf(False)
    assert "langevinPiston     on" in on
    assert "langevinPiston     off" in off
    assert "langevinPiston     on" not in off


def test_carved_production_gets_no_margin_but_full_box_does():
    assert "\nmargin " in _conf(True)
    assert "\nmargin " not in _conf(False)


def test_reseed_barostat_follows_the_npt_flag():
    on = build_reseed_conf("S_00_reseed", "S", BOX, True, seed=7, npt=True)
    off = build_reseed_conf("S_00_reseed", "S", BOX, True, seed=7, npt=False)
    assert "langevinPiston     on" in on and "langevinPiston     off" in off


def test_default_is_npt_so_existing_callers_are_unchanged():
    assert "langevinPiston     on" in build_production_conf(
        _prod_spec(),
        "S",
        BOX,
        True,
        fast=True,
        timestep_fs=4.0,
        structure_psf="S_hmr.psf",
    )


# ── the manifest is the record production reads back ──────────────────────────
def _pkg(tmp_path, solvation):
    d = tmp_path / "pkg"
    d.mkdir(parents=True)
    m = {"nadoc_md_run_manifest_version": 1, "name_stem": "S"}
    if solvation is not None:
        m["solvation"] = solvation
    (d / "manifest.json").write_text(json.dumps(m))
    return d


def test_package_npt_allowed_reads_the_solvation_record(tmp_path):
    carved = _pkg(
        tmp_path / "a",
        {
            "carved": True,
            "npt_allowed": False,
            "water_shell_nm": 1.2,
            "padding_nm": 1.2,
        },
    )
    full = _pkg(
        tmp_path / "b",
        {
            "carved": False,
            "npt_allowed": True,
            "water_shell_nm": 0.0,
            "padding_nm": 1.2,
        },
    )
    assert package_npt_allowed(carved) is False
    assert package_npt_allowed(full) is True


def test_package_npt_allowed_falls_back_to_carved_flag(tmp_path):
    old = _pkg(tmp_path / "c", {"carved": True})  # no npt_allowed key
    assert package_npt_allowed(old) is False


@pytest.mark.parametrize("missing", ["no_solvation_key", "no_manifest", "corrupt"])
def test_package_npt_allowed_defaults_to_true_for_legacy_packages(tmp_path, missing):
    """Packages built before ``solvation`` was recorded keep their historical
    behaviour — this must never silently change an existing job's ensemble."""
    d = tmp_path / missing
    if missing == "no_solvation_key":
        d = _pkg(d, None)
    elif missing == "corrupt":
        d.mkdir(parents=True)
        (d / "manifest.json").write_text("{not json")
    else:
        d.mkdir(parents=True)
    assert package_npt_allowed(d) is True


# ── the box trace has to be fine enough to judge ──────────────────────────────
def test_xst_sampling_is_capped_so_a_long_run_still_resolves_300_ps():
    """Production used to set ``xstFreq`` from ``outputEnergies``: on the 200 ns run that
    was 125,000 steps = one cell sample per 500 ps, so a 38 % collapse produced ~400
    samples across the whole run and nothing could see it happen."""
    long_run = build_production_conf(
        _prod_spec(steps=50_000_000),
        "S",
        BOX,
        True,
        fast=True,
        timestep_fs=4.0,
        structure_psf="S_hmr.psf",
    )
    xst = int(
        next(l.split()[1] for l in long_run.splitlines() if l.startswith("xstFreq"))
    )
    assert xst * 4.0 / 1000.0 <= 10.0  # <= 10 ps between cell samples
    assert 300.0 / (xst * 4.0 / 1000.0) >= 30  # >= 30 samples inside the settle window
