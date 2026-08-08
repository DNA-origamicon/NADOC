"""Phase-1a: per-frame velocity/force DCD capture for the ML-propagator dataset.

The learned atomistic propagator (backend/ml/propagator) needs velocities and
forces per frame, not positions alone.  These tests pin the contract that the
NAMD config emitters write ``velDCD``/``forceDCD`` directives *iff* the capture
flag is set, and are byte-clean (no vel/force output) by default so every
ordinary MD job is unchanged.
"""

from backend.core import md_protocols as mp
from backend.core import namd_solvate as ns
from backend.core.namd_helpers import _render_namd_conf, vel_force_dcd_block


def test_block_empty_when_capture_off():
    assert vel_force_dcd_block("output/x", 5, capture=False) == ""


def test_block_emits_aligned_vel_force_when_on():
    block = vel_force_dcd_block("output/x", 7, capture=True)
    assert "velDCDfile         output/x.veldcd" in block
    assert "forceDCDfile       output/x.forcedcd" in block
    # velDCD + forceDCD sampled at the SAME cadence as the caller's dcdFreq → the
    # three DCDs stay frame-aligned 1:1.
    assert "velDCDfreq         7" in block
    assert "forceDCDfreq       7" in block


def test_gbis_conf_default_has_no_vel_force():
    conf = _render_namd_conf("demo")
    assert "veldcd" not in conf.lower()
    assert "forcedcd" not in conf.lower()


def test_gbis_conf_capture_writes_vel_force():
    conf = _render_namd_conf("demo", capture_vel_force=True)
    assert "output/demo.veldcd" in conf
    assert "output/demo.forcedcd" in conf


def test_solvated_fast_conf_default_has_no_vel_force():
    conf = ns._render_solvated_fast_namd_conf("demo", (6.0, 6.0, 6.0), 1000)
    assert "veldcd" not in conf.lower()
    assert "forcedcd" not in conf.lower()


def test_solvated_fast_conf_capture_writes_vel_force():
    conf = ns._render_solvated_fast_namd_conf(
        "demo", (6.0, 6.0, 6.0), 1000, capture_vel_force=True
    )
    assert "output/demo_fast.veldcd" in conf
    assert "output/demo_fast.forcedcd" in conf


def _prod_spec(dcd_freq: int = 5) -> mp.SegmentSpec:
    return mp.SegmentSpec(
        name="prod1",
        stage="production",
        percent=100,
        steps=10_000,
        temp=300.0,
        damping=1.0,
        scale=1.0,
        npt=True,
        previous="eq",
        reinit=False,
        dcd_freq=dcd_freq,
    )


def test_segment_conf_default_has_no_vel_force():
    conf = mp._segment_conf(_prod_spec(), "sys", (60.0, 60.0, 60.0), False)
    assert "veldcd" not in conf.lower()
    assert "forcedcd" not in conf.lower()


def test_segment_conf_capture_writes_frame_aligned_vel_force():
    conf = mp._segment_conf(
        _prod_spec(dcd_freq=5), "sys", (60.0, 60.0, 60.0), False, capture_vel_force=True
    )
    assert "output/prod1.veldcd" in conf
    assert "output/prod1.forcedcd" in conf
    # cadence matches the segment's position dcdFreq
    assert "velDCDfreq         5" in conf
    assert "forceDCDfreq       5" in conf


def test_propagator_reference_protocol_registered():
    assert mp.PROPAGATOR_REFERENCE_PROTOCOL in mp.SUPPORTED_PROTOCOLS
    assert callable(mp.prepare_propagator_reference)
