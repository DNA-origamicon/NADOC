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
        self.snapshots = 0
        self._lock = threading.Lock()

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *exc):
        self.exited = True
        return False

    def snapshot_seed(self):
        with self._lock:
            self.snapshots += 1

    def set_field(self, *, field_oxdna=None, field_dir=None):
        with self._lock:
            self.field_calls.append(
                (field_oxdna, list(field_dir) if field_dir is not None else None)
            )

    def run(self, steps):
        with self._lock:
            self.runs.append(steps)
        time.sleep(0.001)  # pace the loop so the test isn't a tight spin

    def n_runs(self):
        with self._lock:
            return len(self.runs)


def test_live_session_bursts_and_captures():
    eng = _FakeEngine()
    live = LiveSession(
        "t1",
        eng,
        frame_builder=lambda e: [{"runs": e.n_runs()}],
        field_oxdna=0.08,
        field_dir=[0, 1, 0],
        burst_steps=10,
    )
    live.start()
    try:
        _wait(lambda: live.frame()["n_bursts"] >= 2)
        f = live.frame()
        assert f["ready"] is True
        assert f["status"] == "running"
        assert f["n_positions"] == 1
        assert eng.runs[0] == 10  # burst size honoured
        assert eng.field_calls and eng.field_calls[0][0] == 0.08  # field on at start
    finally:
        live.stop()
    assert eng.exited is True
    assert live.frame()["status"] == "stopped"


def test_live_session_set_field_applied_live():
    eng = _FakeEngine()
    live = LiveSession(
        "t2",
        eng,
        frame_builder=lambda e: [],
        field_oxdna=0.05,
        field_dir=[1, 0, 0],
        burst_steps=5,
    )
    live.start()
    try:
        _wait(lambda: live.frame()["n_bursts"] >= 1)
        live.set_field(field_oxdna=0.2, field_dir=[0, 0, 1])
        _wait(lambda: (0.2, [0, 0, 1]) in eng.field_calls)
    finally:
        live.stop()
    assert (0.2, [0, 0, 1]) in eng.field_calls


def test_live_session_reconfigure_swaps_engine_seamlessly():
    """A queued reconfigure snapshots the current pose on the OLD engine, tears it
    down, builds + enters the NEW engine, sets its field, and keeps stepping — the
    worker swaps engine + frame builder mid-loop."""
    eng1 = _FakeEngine()
    eng2 = _FakeEngine()
    live = LiveSession(
        "rc",
        eng1,
        frame_builder=lambda e: [{"id": id(e)}],
        field_oxdna=0.05,
        field_dir=[1, 0, 0],
        burst_steps=5,
    )
    live.start()
    try:
        _wait(lambda: live.frame()["n_bursts"] >= 1)
        assert live.frame()["positions"] == [{"id": id(eng1)}]  # eng1's builder

        live.reconfigure(
            lambda: (eng2, lambda e: [{"id": id(e)}]),
            field_oxdna=0.2,
            field_dir=[0, 0, 1],
        )
        # The swap: old snapshotted + closed, new entered + field set, frames from eng2.
        _wait(lambda: eng2.entered and live.frame()["positions"] == [{"id": id(eng2)}])
        assert eng1.snapshots == 1  # current pose dumped
        assert eng1.exited is True  # old engine torn down
        assert (0.2, [0, 0, 1]) in eng2.field_calls  # field applied to new
        n0 = live.frame()["n_bursts"]
        _wait(lambda: live.frame()["n_bursts"] > n0)  # keeps stepping on eng2
    finally:
        live.stop()
    assert eng2.exited is True


def test_frame_builder_error_does_not_kill_loop():
    """A bad frame read records an error but the burst loop keeps stepping."""
    calls = {"n": 0}

    def _builder(_e):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("bad read")
        return []

    eng = _FakeEngine()
    live = LiveSession(
        "t3",
        eng,
        frame_builder=_builder,
        field_oxdna=0.1,
        field_dir=[0, 1, 0],
        burst_steps=3,
    )
    live.start()
    try:
        _wait(lambda: eng.n_runs() >= 4)  # loop survived the bad read
        assert live.frame()["status"] == "running"
    finally:
        live.stop()


def test_engine_error_sets_status_error():
    class _Boom(_FakeEngine):
        def run(self, steps):
            raise RuntimeError("boom")

    eng = _Boom()
    live = LiveSession(
        "t4", eng, frame_builder=lambda e: [], field_oxdna=0.1, field_dir=[0, 1, 0]
    )
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
    live = LiveSession(
        "t5",
        _FakeEngine(),
        frame_builder=lambda e: [],
        field_oxdna=0.1,
        field_dir=[0, 1, 0],
        rundir=rd,
    )
    live.start()
    try:
        _wait(lambda: live.frame()["n_bursts"] >= 1)
    finally:
        live.stop()
    assert not rd.exists()


def test_registry_register_get_stop():
    stop_all()
    a = LiveSession(
        "a",
        _FakeEngine(),
        frame_builder=lambda e: [],
        field_oxdna=0.1,
        field_dir=[0, 1, 0],
    )
    register(a)
    a.start()
    assert get_session("a") is a
    assert stop_session("a") is True
    assert get_session("a") is None
    assert stop_session("a") is False  # idempotent / not found


def test_stop_all_enforces_single_session():
    stop_all()
    a = LiveSession(
        "x",
        _FakeEngine(),
        frame_builder=lambda e: [],
        field_oxdna=0.1,
        field_dir=[0, 1, 0],
    )
    register(a)
    a.start()
    assert get_session("x") is a
    assert stop_all() == 1
    assert get_session("x") is None


# ── Real-oxpy: in-memory readout convention (#2) ──────────────────────────────


def test_configuration_map_matches_file_readout_real_oxpy(tmp_path):
    """The in-memory live readout must agree with the file path on a REAL engine —
    locks the oxpy orientation convention (a1 = orientation col 0, a3 = col 2) and
    the pos→nm conversion against print_configuration + read_configuration_full."""
    import numpy as np

    pytest.importorskip("oxpy")
    from backend.api.crud import _geometry_for_design
    from backend.core.oxdna_protocol import build_run_stage, render_stage_input
    from backend.physics.oxdna_interface import write_configuration, write_topology
    from backend.physics.oxdna_live import _OxpyStepper
    from tests.test_headless_oxdna_build import _design_with_overhang_anchor

    d, _dom = _design_with_overhang_anchor()
    rd = tmp_path / "live"
    rd.mkdir()
    write_topology(d, rd / "topology.top")
    geom = _geometry_for_design(d, compact_skips=True)
    write_configuration(d, geom, rd / "conf.dat")
    spec = build_run_stage(name="t", steps=1000, backend="CPU")  # CPU → only needs oxpy
    # Cap the backbone force so raw (unrelaxed) design geometry — whose bonded beads
    # start over-stretched — loads without an init FENE error (the relax stages do this).
    inp_text = (
        render_stage_input(spec, "topology.top", "conf.dat")
        + "\nmax_backbone_force = 5\nmax_backbone_force_far = 10\n"
    )
    (rd / "input").write_text(inp_text)

    with _OxpyStepper(rd) as st:
        st.run(200)
        file_map = st.configuration(d)  # print_configuration + parse
        mem_map = st.configuration_map(d)  # in-memory particles
    assert set(mem_map) == set(file_map)
    # Positions must be compared under MINIMUM IMAGE.  oxpy's in-memory particles and its
    # printed configuration can sit on opposite sides of the periodic box for a nucleotide
    # near an edge — seen as a clean one-box offset (50.615 vs 0.615 nm) once the honeycomb
    # twist becoming commensurate (TD-29) nudged a nucleotide over the boundary.  That is a
    # wrap, not a disagreement; a raw comparison misreports it as a failure.
    from backend.physics.oxdna_interface import box_nm_for_positions

    box = box_nm_for_positions([n["backbone_position"] for n in geom])
    for k in file_map:
        dm = np.asarray(mem_map[k]["backbone_position"], float) - np.asarray(
            file_map[k]["backbone_position"], float
        )
        dm -= box * np.round(dm / box)
        # RELATIVE, not absolute.  file_map round-trips through print_configuration's
        # TEXT output, and a text float carries relative precision — so the agreement
        # floor scales with how far the particle has wandered during the 200 MD steps
        # this test integrates.  Chasing it with a fixed atol does not converge: the same
        # assertion failed at 3.7e-8, then 3.8e-5, then 3.4e-3 nm as the seed geometry
        # changed underneath it.  1e-9 only ever passed because the sampled nucleotides
        # happened to round well.
        #
        # What this test actually locks is the CONVENTION — a1 = orientation column 0,
        # a3 = column 2, and the pos->nm conversion.  Getting any of those wrong displaces
        # a position by NANOMETRES, which 1e-5 relative still catches with ~100x margin
        # even at the largest coordinates seen here.
        scale = np.maximum(
            1.0, np.abs(np.asarray(file_map[k]["backbone_position"], float))
        )
        assert np.all(np.abs(dm) <= 1e-5 * scale), (k, dm)
        assert np.allclose(mem_map[k]["a1"], file_map[k]["a1"], atol=1e-9)
        assert np.allclose(mem_map[k]["a3"], file_map[k]["a3"], atol=1e-9)


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


def test_live_reconfigure_unknown_session_404():
    from backend.api import routes_oxdna_live as rl

    body = rl.LiveReconfigureRequest(anchors=[{"kind": "overhang", "id": "o"}])
    with pytest.raises(HTTPException) as ei:
        asyncio.run(rl.reconfigure_oxdna_live("nope", body))
    assert ei.value.status_code == 404


def test_live_reconfigure_field_without_anchor_allowed():
    """Recomposing to a field with no anchor is no longer rejected (the UI warns about
    the COM drift instead).  It must get PAST the anchor gate — this fake session has no
    design, so it stops at the 'does not support reconfigure' 400, NOT an anchor 400."""
    from backend.api import routes_oxdna_live as rl

    stop_all()
    sess = LiveSession(
        "rcf",
        _FakeEngine(),
        frame_builder=lambda e: [],
        field_oxdna=0.0,
        field_dir=[0, 1, 0],
    )
    register(sess)
    sess.start()
    try:
        body = rl.LiveReconfigureRequest(
            field={"field_pN": 4.0, "dir": [0, 1, 0]}, anchors=[]
        )
        with pytest.raises(HTTPException) as ei:
            asyncio.run(rl.reconfigure_oxdna_live("rcf", body))
        assert ei.value.status_code == 400
        assert "reconfigure" in ei.value.detail.lower()  # reached past the anchor gate
        assert "anchor" not in ei.value.detail.lower()
    finally:
        stop_session("rcf")


def test_live_available_probe_shape():
    from backend.api import routes_oxdna_live as rl

    d = asyncio.run(rl.get_oxdna_live_available())
    assert "available" in d and "reason" in d
    assert isinstance(d["available"], bool)


def test_live_start_field_without_anchor_allowed_when_oxpy_present():
    """When oxpy is available, /start no longer rejects a field with no anchor (the UI
    warns about the COM drift instead).  It must get PAST the anchor gate and fail only
    at job lookup (the fake job is not found → 404), like the free-dynamics case.
    Skipped where oxpy isn't built (the availability check fires first there)."""
    from backend.api import routes_oxdna_live as rl

    if not rl.oxpy_live_available()["available"]:
        pytest.skip("oxpy not available on this host")
    body = rl.LiveStartRequest(
        job_id="whatever", field={"field_pN": 4.0, "dir": [0, 1, 0]}, anchors=[]
    )
    with pytest.raises(HTTPException) as ei:
        asyncio.run(rl.start_oxdna_live(body))
    assert ei.value.status_code == 404  # reached _load_job → not an anchor 400


def test_live_start_no_field_no_anchor_passes_validation():
    """A live session with NO field and NO anchors (free dynamics) is allowed — it
    must get PAST the field/anchor gate and fail only at job lookup (the fake job is
    not found → 404), not be rejected for missing anchors."""
    from backend.api import routes_oxdna_live as rl

    if not rl.oxpy_live_available()["available"]:
        pytest.skip("oxpy not available on this host")
    body = rl.LiveStartRequest(job_id="no_such_job")  # no field, no surface, no anchors
    with pytest.raises(HTTPException) as ei:
        asyncio.run(rl.start_oxdna_live(body))
    assert ei.value.status_code == 404  # reached _load_job → not an anchor 400


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
    info0, be0 = _prepare_live_rundir(
        d,
        seed,
        rd0,
        field=None,
        wall=None,
        anchors=[],
        anchor_stiff=1000.0,
        steps=300,
        backend="CPU",
    )
    assert info0["has_forces"] is False
    assert info0["n_anchored"] == 0
    assert "external_forces = true" not in (rd0 / "input").read_text()
    assert (rd0 / "field_forces.txt").read_text().strip() == ""

    # (b) anchors only (no field) → traps written, external_forces on, no string force.
    rd1 = tmp_path / "anch"
    info1, be1 = _prepare_live_rundir(
        d,
        seed,
        rd1,
        field=None,
        wall=None,
        anchors=[anchor],
        anchor_stiff=1000.0,
        steps=300,
        backend="CPU",
    )
    assert info1["has_forces"] is True
    assert info1["n_anchored"] > 0
    forces = (rd1 / "field_forces.txt").read_text()
    assert "type = trap" in forces
    assert "type = string" not in forces  # no field
    assert "external_forces = true" in (rd1 / "input").read_text()

    # (c) the complete current-card composition reaches one ephemeral run: electric
    # field + hard surface + both anchor cards. This is the Live-button contract.
    rd2 = tmp_path / "all-current-cards"
    surface_anchor = {
        "kind": "domain",
        "strand_id": d.strands[0].id,
        "domain_index": 0,
    }
    info2, _be2 = _prepare_live_rundir(
        d,
        seed,
        rd2,
        field={"force_oxdna": 0.05, "dir": [0, 1, 0]},
        wall={"dir": [0, 1, 0], "offset_nm": 1.0, "stiff": 5.0},
        anchors=[anchor],
        surface_anchors=[surface_anchor],
        anchor_stiff=1000.0,
        steps=300,
        backend="CPU",
    )
    assert info2["has_forces"] is True
    assert info2["n_anchored"] > info1["n_anchored"]
    forces = (rd2 / "field_forces.txt").read_text()
    assert "type = string" in forces
    assert "type = repulsion_plane" in forces
    assert "type = trap" in forces
    assert "type = lowdim_trap" in forces


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
    _info, backend = _prepare_live_rundir(
        d,
        seed,
        rd,
        field=None,
        wall=None,
        anchors=[],
        anchor_stiff=1000.0,
        steps=300,
        backend="CUDA",
    )
    assert backend == "CUDA"
    assert "backend = CUDA" in (rd / "input").read_text()
    assert (rd / "input_cpu").exists()
    assert "backend = CPU" in (rd / "input_cpu").read_text()
    assert "CUDA" not in (rd / "input_cpu").read_text()


def test_live_request_accepts_updated_surface_cards():
    """Live has parity with the continuation cards added to the oxDNA tab."""
    from backend.api.routes_oxdna_live import LiveStartRequest, _resolve_live_elements

    body = LiveStartRequest(
        job_id="selected",
        surface={"dir": [0, 0, 1], "offset_nm": 2, "position_nm": -4, "stiff": 5},
        surface_anchors=[{"kind": "domain", "strandId": "s1", "domainIndex": 0}],
        surface_strands={"enabled": True, "subjectToField": False},
    )
    (
        _field,
        _force,
        _direction,
        wall,
        anchors,
        surface_anchors,
    ) = _resolve_live_elements(body)
    assert anchors == []
    assert surface_anchors == [
        {
            "kind": "domain",
            "id": None,
            "strand_id": "s1",
            "domain_index": 0,
            "helix_id": None,
            "bp": None,
            "direction": None,
            "crossover_id": None,
            "extension_id": None,
            "k": None,
        }
    ]
    assert wall["position_nm"] == -4
    assert body.surface_strands == {"enabled": True, "subjectToField": False}
