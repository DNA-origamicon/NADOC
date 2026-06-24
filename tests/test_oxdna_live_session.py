"""GPU-free tests for the ephemeral oxDNA LIVE field session (worker + routes).

The worker (:class:`backend.core.oxdna_live_runner.LiveSession`) drives an injected
engine + frame builder, so the burst / pending-field / latest-frame / teardown
logic is exercised here with an in-process fake — no oxpy, no GPU.  The route-level
checks cover the not-found + availability-probe paths.  The real oxpy path is
covered by ``test_headless_oxdna_build.test_run_live_field_real_oxpy_steers`` (the
LiveOxdnaSession the worker wraps) and verified live in-app.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from fastapi import HTTPException

from backend.core.oxdna_live_runner import (
    LiveSession,
    get_session,
    register,
    stop_all,
    stop_session,
)


def _wait(pred, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.005)
    raise AssertionError("condition not met within timeout")


class _FakeEngine:
    """A LiveOxdnaSession-like context manager: records set_field / run calls."""

    def __init__(self):
        self.entered = False
        self.exited = False
        self.field_calls: list[tuple] = []
        self.runs: list[int] = []
        self._lock = threading.Lock()

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *exc):
        self.exited = True
        return False

    def set_field(self, *, field_oxdna=None, field_dir=None):
        with self._lock:
            self.field_calls.append(
                (field_oxdna, list(field_dir) if field_dir is not None else None))

    def run(self, steps):
        with self._lock:
            self.runs.append(steps)
        time.sleep(0.001)   # pace the loop so the test isn't a tight spin

    def n_runs(self):
        with self._lock:
            return len(self.runs)


def test_live_session_bursts_and_captures():
    eng = _FakeEngine()
    live = LiveSession("t1", eng, frame_builder=lambda e: [{"runs": e.n_runs()}],
                       field_oxdna=0.08, field_dir=[0, 1, 0], burst_steps=10)
    live.start()
    try:
        _wait(lambda: live.frame()["n_bursts"] >= 2)
        f = live.frame()
        assert f["ready"] is True
        assert f["status"] == "running"
        assert f["n_positions"] == 1
        assert eng.runs[0] == 10                      # burst size honoured
        assert eng.field_calls and eng.field_calls[0][0] == 0.08   # field on at start
    finally:
        live.stop()
    assert eng.exited is True
    assert live.frame()["status"] == "stopped"


def test_live_session_set_field_applied_live():
    eng = _FakeEngine()
    live = LiveSession("t2", eng, frame_builder=lambda e: [],
                       field_oxdna=0.05, field_dir=[1, 0, 0], burst_steps=5)
    live.start()
    try:
        _wait(lambda: live.frame()["n_bursts"] >= 1)
        live.set_field(field_oxdna=0.2, field_dir=[0, 0, 1])
        _wait(lambda: (0.2, [0, 0, 1]) in eng.field_calls)
    finally:
        live.stop()
    assert (0.2, [0, 0, 1]) in eng.field_calls


def test_frame_builder_error_does_not_kill_loop():
    """A bad frame read records an error but the burst loop keeps stepping."""
    calls = {"n": 0}

    def _builder(_e):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("bad read")
        return []

    eng = _FakeEngine()
    live = LiveSession("t3", eng, frame_builder=_builder,
                       field_oxdna=0.1, field_dir=[0, 1, 0], burst_steps=3)
    live.start()
    try:
        _wait(lambda: eng.n_runs() >= 4)              # loop survived the bad read
        assert live.frame()["status"] == "running"
    finally:
        live.stop()


def test_engine_error_sets_status_error():
    class _Boom(_FakeEngine):
        def run(self, steps):
            raise RuntimeError("boom")

    eng = _Boom()
    live = LiveSession("t4", eng, frame_builder=lambda e: [],
                       field_oxdna=0.1, field_dir=[0, 1, 0])
    live.start()
    try:
        _wait(lambda: live.frame()["status"] == "error")
        f = live.frame()
        assert "boom" in (f["error"] or "")
    finally:
        live.stop()


def test_stop_removes_rundir(tmp_path):
    rd = tmp_path / "live_rundir"
    rd.mkdir()
    (rd / "topology.top").write_text("x")
    live = LiveSession("t5", _FakeEngine(), frame_builder=lambda e: [],
                       field_oxdna=0.1, field_dir=[0, 1, 0], rundir=rd)
    live.start()
    try:
        _wait(lambda: live.frame()["n_bursts"] >= 1)
    finally:
        live.stop()
    assert not rd.exists()


def test_registry_register_get_stop():
    stop_all()
    a = LiveSession("a", _FakeEngine(), frame_builder=lambda e: [],
                    field_oxdna=0.1, field_dir=[0, 1, 0])
    register(a)
    a.start()
    assert get_session("a") is a
    assert stop_session("a") is True
    assert get_session("a") is None
    assert stop_session("a") is False               # idempotent / not found


def test_stop_all_enforces_single_session():
    stop_all()
    a = LiveSession("x", _FakeEngine(), frame_builder=lambda e: [],
                    field_oxdna=0.1, field_dir=[0, 1, 0])
    register(a)
    a.start()
    assert get_session("x") is a
    assert stop_all() == 1
    assert get_session("x") is None


# ── Route-level (no oxpy needed for these branches) ───────────────────────────

def test_live_frame_unknown_session_404():
    from backend.api import routes_oxdna_live as rl
    with pytest.raises(HTTPException) as ei:
        asyncio.run(rl.get_oxdna_live_frame("nope"))
    assert ei.value.status_code == 404


def test_live_field_unknown_session_404():
    from backend.api import routes_oxdna_live as rl
    body = rl.LiveFieldRequest(field_pN=4.0, dir=[0, 1, 0])
    with pytest.raises(HTTPException) as ei:
        asyncio.run(rl.update_oxdna_live_field("nope", body))
    assert ei.value.status_code == 404


def test_live_stop_unknown_session_ok():
    from backend.api import routes_oxdna_live as rl
    r = asyncio.run(rl.stop_oxdna_live("nope"))
    assert r["ok"] is True and r["stopped"] is False


def test_live_available_probe_shape():
    from backend.api import routes_oxdna_live as rl
    d = asyncio.run(rl.get_oxdna_live_available())
    assert "available" in d and "reason" in d
    assert isinstance(d["available"], bool)


def test_live_start_field_requires_anchor_when_oxpy_present():
    """When oxpy is available, /start rejects a field with no anchor (the COM-drift
    gotcha) before touching any job.  Skipped where oxpy isn't built (the
    availability check fires first there, a different 400)."""
    from backend.api import routes_oxdna_live as rl
    if not rl.oxpy_live_available()["available"]:
        pytest.skip("oxpy not available on this host")
    body = rl.LiveStartRequest(
        job_id="whatever", field={"field_pN": 4.0, "dir": [0, 1, 0]}, anchors=[])
    with pytest.raises(HTTPException) as ei:
        asyncio.run(rl.start_oxdna_live(body))
    assert ei.value.status_code == 400
    assert "anchor" in ei.value.detail.lower()


def test_live_start_no_field_no_anchor_passes_validation():
    """A live session with NO field and NO anchors (free dynamics) is allowed — it
    must get PAST the field/anchor gate and fail only at job lookup (the fake job is
    not found → 404), not be rejected for missing anchors."""
    from backend.api import routes_oxdna_live as rl
    if not rl.oxpy_live_available()["available"]:
        pytest.skip("oxpy not available on this host")
    body = rl.LiveStartRequest(job_id="no_such_job")   # no field, no surface, no anchors
    with pytest.raises(HTTPException) as ei:
        asyncio.run(rl.start_oxdna_live(body))
    assert ei.value.status_code == 404   # reached _load_job → not an anchor 400


def test_prepare_live_rundir_composes_elements(tmp_path):
    """_prepare_live_rundir stages a rundir whose forces file composes the enabled
    elements: a no-element run writes an empty forces file (external_forces off in
    the input), while anchors-only writes traps (external_forces on).  Binary-free:
    the seed conf is written straight from design geometry."""
    from backend.api.crud import _geometry_for_design
    from backend.api.routes_oxdna_live import _prepare_live_rundir
    from backend.physics.oxdna_interface import write_configuration
    from tests.test_headless_oxdna_build import _design_with_overhang_anchor

    d, _dom = _design_with_overhang_anchor()
    anchor = {"kind": "overhang", "id": "ov_anchor"}
    seed = tmp_path / "seed.dat"
    write_configuration(d, _geometry_for_design(d, compact_skips=True), seed)

    # (a) nothing enabled → free dynamics: empty forces, external_forces NOT set.
    rd0 = tmp_path / "free"
    info0, be0 = _prepare_live_rundir(d, seed, rd0, field=None, wall=None, anchors=[],
                                      anchor_stiff=1000.0, steps=300, backend="CPU")
    assert info0["has_forces"] is False
    assert info0["n_anchored"] == 0
    assert "external_forces = true" not in (rd0 / "input").read_text()
    assert (rd0 / "field_forces.txt").read_text().strip() == ""

    # (b) anchors only (no field) → traps written, external_forces on, no string force.
    rd1 = tmp_path / "anch"
    info1, be1 = _prepare_live_rundir(d, seed, rd1, field=None, wall=None,
                                      anchors=[anchor], anchor_stiff=1000.0, steps=300,
                                      backend="CPU")
    assert info1["has_forces"] is True
    assert info1["n_anchored"] > 0
    forces = (rd1 / "field_forces.txt").read_text()
    assert "type = trap" in forces
    assert "type = string" not in forces            # no field
    assert "external_forces = true" in (rd1 / "input").read_text()


def test_prepare_live_rundir_stages_cuda_with_cpu_fallback(tmp_path):
    """A CUDA-backed live rundir stages a CUDA primary ``input`` AND a CPU
    ``input_cpu`` for the GPU-OOM fallback path."""
    from backend.api.crud import _geometry_for_design
    from backend.api.routes_oxdna_live import _prepare_live_rundir
    from backend.physics.oxdna_interface import write_configuration
    from tests.test_headless_oxdna_build import _design_with_overhang_anchor

    d, _dom = _design_with_overhang_anchor()
    seed = tmp_path / "seed.dat"
    write_configuration(d, _geometry_for_design(d, compact_skips=True), seed)

    rd = tmp_path / "cuda"
    _info, backend = _prepare_live_rundir(d, seed, rd, field=None, wall=None,
                                          anchors=[], anchor_stiff=1000.0, steps=300,
                                          backend="CUDA")
    assert backend == "CUDA"
    assert "backend = CUDA" in (rd / "input").read_text()
    assert (rd / "input_cpu").exists()
    assert "backend = CPU" in (rd / "input_cpu").read_text()
    assert "CUDA" not in (rd / "input_cpu").read_text()
