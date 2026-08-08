"""Tests for the CanDo FEM job model + runner (Phase-5 Item 1).

Covers the persistence round-trip, the threaded predict_shape lifecycle
(create → run → completed with cached display/RMSF), and status reconcile. The
FEM numerics themselves are validated in tests/test_fem_solver.py; here we assert
the JOB machinery wraps predict_shape correctly and is Physical-layer only.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from backend.core.models import LatticeType


@pytest.fixture(scope="module")
def routed_6hb():
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    cells = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        return design_state.get_or_404().model_copy(deep=True)


def _run_to_completion(design, ws: Path, *, nonlinear: bool):
    from backend.core import cando_runner as cr
    from backend.core.cando_job import CandoJob, CandoStatus, new_cando_job

    job = new_cando_job(
        "6hb", nonlinear=nonlinear, with_rmsf=True, n_steps=5, n_nucleotides=1000
    )
    job.status = CandoStatus.preparing
    job.save(ws)
    cr.prepare_cando_job(design, job, ws)
    job.status = CandoStatus.running
    job.save(ws)
    cr.start_job(job, ws)
    for _ in range(240):  # ≤120 s guard
        if not cr.is_running(job.job_id):
            break
        time.sleep(0.5)
    return CandoJob.load(job.job_id, ws)


def test_job_persistence_roundtrip(tmp_path):
    from backend.core.cando_job import CandoJob, CandoStatus, new_cando_job

    job = new_cando_job(
        "mydesign",
        nonlinear=False,
        n_steps=12,
        with_rmsf=False,
        n_nucleotides=500,
        design_source_path="/ws/mydesign.nadoc",
    )
    job.save(tmp_path)
    loaded = CandoJob.load(job.job_id, tmp_path)
    assert loaded.job_id == job.job_id
    assert loaded.nonlinear is False
    assert loaded.n_steps == 12
    assert loaded.with_rmsf is False
    assert loaded.status == CandoStatus.queued
    assert loaded.stages and loaded.stages[0].name == "linear"
    # list_jobs finds it
    ids = [j.job_id for j in CandoJob.list_jobs(tmp_path)]
    assert job.job_id in ids


def test_new_job_stage_name_tracks_solver(tmp_path):
    from backend.core.cando_job import new_cando_job

    assert new_cando_job("d", nonlinear=True).stages[0].name == "nonlinear"
    assert new_cando_job("d", nonlinear=False).stages[0].name == "linear"


# ── C1/C2 job-request annotations: anchors + E-field (frontend cards drive these) ──


def test_job_roundtrips_anchors_and_field(tmp_path):
    """The anchor list + field spec are job-request annotations that survive save/load
    (so the runner + a re-selected job see exactly what the cards submitted)."""
    from backend.core.cando_job import CandoJob, new_cando_job

    anchors = [
        {"kind": "cluster", "id": "c1"},
        {"kind": "base", "helix_id": "h0", "bp": 5, "direction": "forward"},
    ]
    field = {"field_pN": 0.2, "dir": [0.0, 1.0, 0.0]}
    job = new_cando_job("d", anchors=anchors, field=field)
    job.save(tmp_path)
    loaded = CandoJob.load(job.job_id, tmp_path)
    assert loaded.anchors == anchors
    assert loaded.field == field
    # Default (no field/anchors) is None, not a mutable shared default.
    plain = new_cando_job("d")
    assert plain.anchors is None and plain.field is None


def test_legacy_job_without_anchors_field_migrates_to_none(tmp_path):
    """An old job.json written before C1/C2 (no anchors/field keys) loads cleanly."""
    import json

    from backend.core.cando_job import CandoJob, new_cando_job

    job = new_cando_job("d")
    job.save(tmp_path)
    p = job.job_dir(tmp_path) / "job.json"
    data = json.loads(p.read_text())
    data.pop("anchors", None)
    data.pop("field", None)
    p.write_text(json.dumps(data))
    loaded = CandoJob.load(job.job_id, tmp_path)
    assert loaded.anchors is None and loaded.field is None


def test_create_request_model_carries_anchors_and_field():
    """The create-job request model accepts the two annotations (and defaults them None)."""
    from backend.api.routes_cando import CreateCandoJobRequest

    req = CreateCandoJobRequest(
        anchors=[{"kind": "cluster", "id": "c1"}],
        field={"field_pN": 0.1, "dir": [1, 0, 0]},
    )
    assert req.anchors == [{"kind": "cluster", "id": "c1"}]
    assert req.field == {"field_pN": 0.1, "dir": [1, 0, 0]}
    assert CreateCandoJobRequest().anchors is None
    assert CreateCandoJobRequest().field is None


def test_runner_forwards_anchors_and_field_to_predict_shape(
    routed_6hb, tmp_path, monkeypatch
):
    """The load-bearing wiring: a predict job's anchors + field reach predict_shape(...).
    predict_shape is stubbed to capture its kwargs (no real solve → fast)."""
    import backend.physics.fem_solver as fs
    from backend.core import cando_runner as cr
    from backend.core.cando_job import CandoStatus, new_cando_job

    captured = {}

    def _spy(design, **kw):
        captured.update(kw)
        raise RuntimeError("stop-after-capture")  # end the solve immediately

    monkeypatch.setattr(fs, "predict_shape", _spy)

    anchors = [
        {
            "kind": "base",
            "helix_id": routed_6hb.helices[0].id,
            "bp": 5,
            "direction": "forward",
        }
    ]
    field = {"field_pN": 0.1, "dir": [1.0, 0.0, 0.0]}
    job = new_cando_job(
        "6hb",
        nonlinear=False,
        with_rmsf=False,
        n_steps=5,
        n_nucleotides=1000,
        anchors=anchors,
        field=field,
    )
    job.status = CandoStatus.preparing
    job.save(tmp_path)
    cr.prepare_cando_job(routed_6hb, job, tmp_path)
    cr.start_job(job, tmp_path)
    for _ in range(120):
        if not cr.is_running(job.job_id):
            break
        time.sleep(0.5)
    assert captured.get("anchors") == anchors
    assert captured.get("field") == field


def test_linear_job_completes_and_caches(routed_6hb, tmp_path):
    from backend.core import cando_runner as cr
    from backend.core.cando_job import CandoStatus

    job = _run_to_completion(routed_6hb, tmp_path, nonlinear=False)
    assert job.status == CandoStatus.completed
    assert job.sim_seconds is not None and job.sim_seconds >= 0
    assert job.n_nodes and job.n_nodes > 0
    assert job.rmsf_min_nm is not None and job.rmsf_max_nm is not None
    assert 0.0 <= job.rmsf_min_nm <= job.rmsf_max_nm

    disp = cr.load_display(job.job_dir(tmp_path))
    assert disp and disp["solver"] == "linear"
    # The display covers EVERY nucleotide, not just the duplex-core mesh nodes:
    # two entries (FORWARD/REVERSE) per axis node PLUS the gap-filled ssDNA scaffold
    # ends + loop/skip bases (which ride along their nearest covered bp).  So the
    # position count strictly exceeds 2 * n_nodes whenever the design has ss ends /
    # loops — the fix for the "stranded ssDNA/loop" deform-display bug.
    assert len(disp["positions"]) >= 2 * job.n_nodes
    for p in disp["positions"][:5]:
        assert set(p) >= {"helix_id", "bp_index", "direction", "backbone_position"}
        assert len(p["backbone_position"]) == 3

    rmsf = cr.load_rmsf(job.job_dir(tmp_path))
    assert rmsf and len(rmsf["rmsf"]) == job.n_nodes


def test_progress_and_reconcile(routed_6hb, tmp_path):
    from backend.core import cando_runner as cr
    from backend.core.cando_job import CandoJob, CandoStatus

    job = _run_to_completion(routed_6hb, tmp_path, nonlinear=False)
    prog = cr.job_progress(job, tmp_path)
    assert prog["overall"] == 1.0 and prog["status"] == "completed"

    # A completed job with a cached display reconciles to completed even if its
    # persisted status were flipped back to running by an interrupted run.
    job.status = CandoStatus.running
    job.save(tmp_path)
    reconciled = cr.reconcile_cando_status(
        CandoJob.load(job.job_id, tmp_path), tmp_path
    )
    assert reconciled.status == CandoStatus.completed


def test_stop_marks_stray_running_stopped(tmp_path):
    from backend.core import cando_runner as cr
    from backend.core.cando_job import CandoJob, CandoStatus, new_cando_job

    # No live thread → stop() marks a stray running job stopped.
    job = new_cando_job("d", nonlinear=True)
    job.status = CandoStatus.running
    job.save(tmp_path)
    assert cr.stop_job(job.job_id, tmp_path) is False
    assert CandoJob.load(job.job_id, tmp_path).status == CandoStatus.stopped


def test_snapshot_geometry_reflects_the_jobs_own_topology(
    routed_6hb, tmp_path, monkeypatch
):
    """The /cando/jobs/{id}/snapshot-geometry route serves the geometry of the job's
    OWN design snapshot (the topology at solve time), so the display modes render THIS
    instead of the live editor design.  Pins that the served geometry matches the
    snapshotted design regardless of any later live edits (the core of the fix)."""
    import asyncio

    from backend.api import routes_cando as rc
    from backend.core import cando_runner as cr
    from backend.core.cando_job import CandoStatus, new_cando_job
    from backend.core.design_geometry import _geometry_for_helices

    monkeypatch.setattr(rc, "_WORKSPACE_DIR", tmp_path)

    job = new_cando_job(
        "6hb", nonlinear=False, with_rmsf=False, n_steps=5, n_nucleotides=1000
    )
    job.status = CandoStatus.completed
    job.save(tmp_path)
    cr.prepare_cando_job(routed_6hb, job, tmp_path)  # writes the design.json snapshot

    resp = asyncio.run(rc.get_cando_snapshot_geometry(job.job_id))
    assert resp["ready"] is True
    assert resp["design"]["helices"]  # full snapshot design returned
    assert resp["helix_axes"]
    # Nucleotide list covers exactly the SNAPSHOT topology — every helix bp, not live state.
    expected = len(_geometry_for_helices(routed_6hb, None))
    assert len(resp["nucleotides"]) == expected > 0
    for n in resp["nucleotides"][:5]:
        assert set(n) >= {"helix_id", "bp_index", "direction", "backbone_position"}


def test_snapshot_geometry_missing_snapshot_is_not_ready(tmp_path, monkeypatch):
    """A job whose design.json snapshot is absent reports not-ready rather than 500."""
    import asyncio

    from backend.api import routes_cando as rc
    from backend.core.cando_job import CandoStatus, new_cando_job

    monkeypatch.setattr(rc, "_WORKSPACE_DIR", tmp_path)
    job = new_cando_job("d", nonlinear=False)
    job.status = CandoStatus.completed
    job.save(tmp_path)  # no prepare → no design.json

    resp = asyncio.run(rc.get_cando_snapshot_geometry(job.job_id))
    assert resp["ready"] is False and resp["nucleotides"] == []


# ── Autorefine job kind ──────────────────────────────────────────────────────────


def test_autorefine_job_kind_stage_and_roundtrip(tmp_path):
    """The new 'autorefine' kind persists its result fields + doc_id, and an OLD job.json
    (written before the kind field existed) loads back-compatibly as a 'predict' job."""
    import json

    from backend.core.cando_job import CandoJob, new_cando_job

    job = new_cando_job("d", kind="autorefine", nonlinear=False, doc_id="__default__")
    assert job.kind == "autorefine"
    assert job.stages[0].name == "autorefine"  # not "linear"/"nonlinear"
    job.refine_applied = True
    job.refine_n_marks = 12
    job.refine_period = 40
    job.refine_before_rmsd = 1.7
    job.refine_after_rmsd = 0.4
    job.save(tmp_path)

    loaded = CandoJob.load(job.job_id, tmp_path)
    assert loaded.kind == "autorefine" and loaded.doc_id == "__default__"
    assert loaded.refine_applied is True and loaded.refine_n_marks == 12
    assert loaded.refine_period == 40 and loaded.refine_after_rmsd == 0.4

    # Back-compat: a job.json missing the new fields loads as a plain predict job.
    p = job.job_dir(tmp_path) / "job.json"
    data = json.loads(p.read_text())
    for k in ("kind", "doc_id", "refine_applied", "refine_period"):
        data.pop(k, None)
    p.write_text(json.dumps(data))
    old = CandoJob.load(job.job_id, tmp_path)
    assert (
        old.kind == "predict"
        and old.refine_applied is False
        and old.refine_period is None
    )


def _routed_sq_strut(length: int = 160):
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    cells = [(r, c) for r in range(2) for c in range(3)]  # 2×3 = 6 helices
    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle(cells, length, lattice=LatticeType.SQUARE, name="sq")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        return design_state.get_or_404().model_copy(deep=True)


def _run_autorefine_job(design, ws: Path, *, name: str = "sq"):
    """Set ``design`` as the active (default-doc) design, then run an autorefine job to
    completion synchronously (the runner applies to the active design + feature log)."""
    from backend.api import state as ds
    from backend.core import cando_runner as cr
    from backend.core.cando_job import CandoJob, new_cando_job

    ds.set_design(design.model_copy(deep=True))
    job = new_cando_job(
        name,
        kind="autorefine",
        nonlinear=False,
        with_rmsf=True,
        n_nucleotides=1000,
        doc_id="__default__",
    )
    cr.prepare_cando_job(ds.get_or_404(), job, ws)
    cr._run_autorefine_job(job, ws)  # synchronous (no thread) for a deterministic test
    return CandoJob.load(job.job_id, ws)


def test_autorefine_job_applies_marks_logs_and_caches_all_displays(tmp_path):
    """The autorefine JOB, end to end: refine a square strut's register over-twist, AUTO-APPLY
    the winning skip program to the active design as a reversible feature-log entry, and cache the
    FEM analysis of the refined design so ALL display modes work on the completed job."""
    from backend.api import state as ds
    from backend.core import cando_runner as cr
    from backend.core.cando_job import CandoStatus

    job = _run_autorefine_job(_routed_sq_strut(160), tmp_path)

    assert job.status == CandoStatus.completed
    assert job.kind == "autorefine"
    assert job.refine_applied is True
    assert job.refine_n_marks and job.refine_n_marks > 0
    assert job.refine_after_rmsd < job.refine_before_rmsd  # it straightened the strut
    assert job.feature_log_position is not None

    # The active design received exactly the applied marks + a reversible feature-log entry.
    active = ds.get_or_404()
    assert sum(len(h.loop_skips) for h in active.helices) == job.refine_n_marks
    assert (
        active.feature_log
        and active.feature_log[-1].op_kind == "cando-autorefine-marks"
    )

    # ALL display modes work: the FEM analysis of the REFINED design is cached (display + rmsf +
    # per-bp axis nodes for the cylinder rep), and the job's snapshot is the refined topology.
    disp = cr.load_display(job.job_dir(tmp_path))
    assert disp and disp["positions"] and disp["axis"]
    rmsf = cr.load_rmsf(job.job_dir(tmp_path))
    assert rmsf and len(rmsf["rmsf"]) == job.n_nodes
    snap = cr._load_snapshot_design(job.job_dir(tmp_path))
    assert sum(len(h.loop_skips) for h in snap.helices) == job.refine_n_marks


def test_autorefine_job_no_improvement_leaves_design_but_still_caches(
    routed_6hb, tmp_path
):
    """A straight design with nothing to refine: the job applies NOTHING (design + feature log
    untouched) but STILL caches its FEM analysis, so the completed job's displays work."""
    from backend.api import state as ds
    from backend.core import cando_runner as cr
    from backend.core.cando_job import CandoStatus

    before_marks = sum(len(h.loop_skips) for h in routed_6hb.helices)
    before_log = len(routed_6hb.feature_log or [])
    job = _run_autorefine_job(routed_6hb, tmp_path, name="6hb")

    assert job.status == CandoStatus.completed
    assert job.refine_applied is False
    active = ds.get_or_404()
    assert sum(len(h.loop_skips) for h in active.helices) == before_marks
    assert len(active.feature_log or []) == before_log  # no entry added
    # Displays still work on the completed job.
    assert cr.load_display(job.job_dir(tmp_path))["positions"]
    assert cr.load_rmsf(job.job_dir(tmp_path))["rmsf"]
