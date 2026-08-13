"""
Tests for the managed mrDNA/ARBD relaxation job system (mrdna_job / mrdna_runner
/ routes_mrdna).

mrDNA's ``model.simulate()`` needs a real ARBD + GPU, so the runner's execution
body is NOT exercised here (it is the manual-validation item).  What IS pinned:
the job model round-trip, the availability probe shape, the time-based progress
estimate, the reconcile state machine (which recovers a restart-orphaned job from
its cached ``display.json``), and the HTTP routes (create/list/stop/delete +
availability gating) with a mocked-out runner + design.
"""

from __future__ import annotations

import json

import pytest
import numpy as np

from backend.core.mrdna_job import MrdnaJob, MrdnaStatus, new_mrdna_job


# ── Job model ─────────────────────────────────────────────────────────────────


def test_fine_display_expands_loop_copies_and_builds_relaxed_slab_frames():
    from backend.core.geometry import nucleotide_positions
    from backend.core.models import Design, Helix, LoopSkip, Vec3
    from backend.core.mrdna_runner import (
        _add_relaxed_frames,
        _expanded_nucleotide_records,
    )

    helix = Helix(
        id="h0",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=2),
        length_bp=4,
        loop_skips=[LoopSkip(bp_index=1, delta=1)],
    )
    design = Design(helices=[helix])
    override = {
        (n.helix_id, n.bp_index, n.direction.value): n.position + np.array([1, 2, 3])
        for n in nucleotide_positions(helix)
    }
    records = _expanded_nucleotide_records(design, override)
    loop = [p for p in records if p["bp_index"] == 1 and p["direction"] == "FORWARD"]
    assert [p["copy"] for p in loop] == [0, 1]
    assert not np.allclose(loop[0]["backbone_position"], loop[1]["backbone_position"])

    _add_relaxed_frames(records)
    framed = [p for p in records if p["helix_id"] == "h0"]
    assert all({"nx", "ny", "nz", "tx", "ty", "tz"} <= p.keys() for p in framed)
    assert all(np.isclose(np.linalg.norm([p["nx"], p["ny"], p["nz"]]), 1) for p in framed)


def test_fine_display_root_anchors_missing_extruded_overhang():
    from backend.core.models import (
        Design,
        Direction,
        Domain,
        Helix,
        OverhangSpec,
        Strand,
        StrandType,
        Vec3,
    )
    from backend.core.design_geometry import _geometry_for_helices
    from backend.core.mrdna_runner import _add_missing_overhang_records

    helix = Helix(
        id="h_child",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=4),
        bp_start=72,
        length_bp=12,
    )
    strand = Strand(
        id="s",
        strand_type=StrandType.STAPLE,
        domains=[Domain(
            helix_id="h_child", start_bp=179, end_bp=168,
            direction=Direction.REVERSE, overhang_id="oh",
        )],
    )
    design = Design(
        helices=[helix], strands=[strand],
        overhangs=[OverhangSpec(
            id="oh", helix_id="h_child", strand_id="s", sequence="A" * 12,
        )],
    )
    # Root is the following domain's first nucleotide; use a second helix so the
    # missing overhang cannot accidentally borrow an unrelated local child range.
    design = design.model_copy(update={"helices": [helix, Helix(
        id="h_root", axis_start=Vec3(x=2, y=0, z=0),
        axis_end=Vec3(x=2, y=0, z=4), bp_start=168, length_bp=12,
    )], "strands": [strand.model_copy(update={"domains": [
        strand.domains[0], Domain(
            helix_id="h_root", start_bp=168, end_bp=179,
            direction=Direction.FORWARD,
        ),
    ]})]})
    ref = _geometry_for_helices(design, None, junction_balance=True)
    root = next(p for p in ref if p["helix_id"] == "h_root" and p["bp_index"] == 168 and p["direction"] == "FORWARD")
    records = [{**root, "backbone_position": (np.asarray(root["backbone_position"]) + [1, 2, 3]).tolist()}]
    _add_missing_overhang_records(design, records)
    oh = [p for p in records if p["helix_id"] == "h_child" and 168 <= p["bp_index"] <= 179]
    assert len(oh) == 12
    # The overhang-to-root junction remains exactly the design bond length.
    tail = next(p for p in oh if p["bp_index"] == 168)
    relaxed_bond = np.linalg.norm(np.asarray(tail["backbone_position"]) - records[0]["backbone_position"])
    ref_tail = next(p for p in ref if p["helix_id"] == "h_child" and p["bp_index"] == 168 and p["direction"] == "REVERSE")
    design_bond = np.linalg.norm(np.asarray(ref_tail["backbone_position"]) - root["backbone_position"])
    assert relaxed_bond == pytest.approx(design_bond)

    # New Fine topologies contain the rendered parent-range sites themselves;
    # this is not only an archived-job display repair.
    from backend.core.mrdna_bridge import _build_nt_arrays

    *_, nt_key = _build_nt_arrays(design, return_nt_key=True)
    assert all(("h_child", bp, "REVERSE", 0) in nt_key for bp in range(168, 180))


def test_new_mrdna_job_single_coarse_stage():
    job = new_mrdna_job("mydesign", coarse_steps=50_000, n_nucleotides=1200)
    assert job.status == MrdnaStatus.queued
    assert job.coarse_steps == 50_000
    assert len(job.stages) == 1
    assert job.stages[0].name == "coarse"
    assert job.stages[0].steps == 50_000


def test_mrdna_job_save_load_roundtrip(tmp_path):
    job = new_mrdna_job(
        "d", coarse_steps=1000, n_nucleotides=42, design_source_path="foo/bar.nadoc"
    )
    job.sim_seconds = 12.3
    job.n_beads = 99
    job.save(tmp_path)
    loaded = MrdnaJob.load(job.job_id, tmp_path)
    assert loaded.job_id == job.job_id
    assert loaded.status == MrdnaStatus.queued
    assert loaded.coarse_steps == 1000
    assert loaded.n_beads == 99
    assert loaded.design_source_path == "foo/bar.nadoc"
    assert loaded.stages[0].name == "coarse"


def test_mrdna_job_list_jobs(tmp_path):
    a = new_mrdna_job("a")
    a.save(tmp_path)
    b = new_mrdna_job("b")
    b.save(tmp_path)
    ids = {j.job_id for j in MrdnaJob.list_jobs(tmp_path)}
    assert {a.job_id, b.job_id} <= ids


# ── Availability probe ────────────────────────────────────────────────────────


def test_mrdna_available_shape(monkeypatch):
    import backend.core.mrdna_runner as r
    import backend.core.mrdna_bridge as bridge

    monkeypatch.setattr(bridge, "find_mrdna", lambda: "/x/mrdna")
    monkeypatch.setattr(bridge, "find_arbd", lambda: "/x/arbd")
    out = r.mrdna_available()
    assert out["available"] is True
    assert out["mrdna"] == "/x/mrdna"
    assert out["arbd"] == "/x/arbd"

    monkeypatch.setattr(bridge, "find_arbd", lambda: None)
    assert r.mrdna_available()["available"] is False


# ── Progress ──────────────────────────────────────────────────────────────────


def test_job_progress_states(tmp_path):
    import time
    from backend.core.mrdna_runner import job_progress

    job = new_mrdna_job("d", coarse_steps=100_000, n_nucleotides=1270)

    job.status = MrdnaStatus.queued
    assert job_progress(job, tmp_path)["overall"] == 0.0

    job.status = MrdnaStatus.completed
    assert job_progress(job, tmp_path)["overall"] == 1.0

    job.status = MrdnaStatus.running
    job.stages[0].status = "running"
    job.stages[0].started_at = time.time()
    p = job_progress(job, tmp_path)
    assert 0.0 <= p["overall"] < 1.0
    assert p["eta_seconds"] is not None and p["eta_seconds"] >= 0.0


def test_fine_job_progress_uses_actual_dcd_frames(tmp_path):
    import struct
    import time

    from backend.core.mrdna_runner import job_progress

    job = new_mrdna_job(
        "d", coarse_steps=100_000, fine_steps=200_000, output_period=10_000
    )
    job.status = MrdnaStatus.running
    job.stages[0].status = "running"
    job.stages[0].started_at = time.time()
    out = job.job_dir(tmp_path) / "output"
    out.mkdir(parents=True)

    def dcd(index, frames):
        (out / f"mrdna_relax-{index}.dcd").write_bytes(
            struct.pack("<i4si", 84, b"CORD", frames)
        )

    dcd(0, 11)  # coarse complete: 100k / 10k + initial frame
    dcd(1, 2)   # twist-fine halfway: 1 interval of 2
    p = job_progress(job, tmp_path)
    assert p["stage_name"] == "fine (twist)"
    assert p["stage_fraction"] == 0.5
    assert p["overall"] == pytest.approx(0.4)  # (100k + 100k) / 500k

    dcd(1, 3)
    dcd(2, 3)
    p = job_progress(job, tmp_path)
    assert p["stage_name"] == "fine (frozen twist)"
    assert p["overall"] == 0.99  # completion remains reserved for extraction


def test_start_job_publishes_preparing_before_worker_runs(tmp_path, monkeypatch):
    import threading

    import backend.core.mrdna_runner as runner

    entered = threading.Event()
    release = threading.Event()

    def blocked_worker(job, workspace):
        entered.set()
        release.wait(2)

    monkeypatch.setattr(runner, "_run_job", blocked_worker)
    job = new_mrdna_job("fine", fine_steps=200_000)
    job.save(tmp_path)
    runner.start_job(job, tmp_path)
    assert entered.wait(1)
    assert MrdnaJob.load(job.job_id, tmp_path).status == MrdnaStatus.preparing
    release.set()
    runner._RUNNING[job.job_id].thread.join(2)
    runner._RUNNING.pop(job.job_id, None)


# ── Reconcile (restart recovery) ──────────────────────────────────────────────


def test_reconcile_running_with_cached_display_completes(tmp_path):
    from backend.core.mrdna_runner import reconcile_mrdna_status

    job = new_mrdna_job("d")
    job.status = MrdnaStatus.running
    job.stages[0].status = "running"
    job.save(tmp_path)
    (job.job_dir(tmp_path) / "display.json").write_text(json.dumps({"positions": [1]}))

    out = reconcile_mrdna_status(job, tmp_path)
    assert out.status == MrdnaStatus.completed
    assert out.stages[0].status == "done"


def test_reconcile_running_no_output_and_no_process_stops(tmp_path, monkeypatch):
    import backend.core.mrdna_runner as r

    monkeypatch.setattr(r, "_external_arbd_pid", lambda job, ws: None)

    job = new_mrdna_job("d")
    job.status = MrdnaStatus.running
    job.stages[0].status = "running"
    job.save(tmp_path)

    out = r.reconcile_mrdna_status(job, tmp_path)
    assert out.status == MrdnaStatus.stopped


def test_reconcile_noop_for_terminal_jobs(tmp_path):
    from backend.core.mrdna_runner import reconcile_mrdna_status

    job = new_mrdna_job("d")
    job.status = MrdnaStatus.completed
    job.save(tmp_path)
    assert reconcile_mrdna_status(job, tmp_path).status == MrdnaStatus.completed


# ── HTTP routes ───────────────────────────────────────────────────────────────


def test_mrdna_available_route(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.core.mrdna_bridge as bridge

    monkeypatch.setattr(bridge, "find_mrdna", lambda: None)
    monkeypatch.setattr(bridge, "find_arbd", lambda: None)
    r = TestClient(app).get("/api/mrdna/available")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert "mrdna" in body and "arbd" in body


def test_mrdna_create_rejects_when_unavailable(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_mrdna as routes_mrdna

    monkeypatch.setattr(
        routes_mrdna,
        "mrdna_available",
        lambda: {"available": False, "mrdna": None, "arbd": None},
    )
    r = TestClient(app).post("/api/mrdna/jobs", json={"coarse_steps": 1000})
    assert r.status_code == 400
    assert "not installed" in r.json()["detail"]


def test_mrdna_create_and_lifecycle(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_mrdna as routes_mrdna
    from backend.api import state as design_state
    from tests.conftest import make_6hb_design

    monkeypatch.setattr(routes_mrdna, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(
        routes_mrdna,
        "mrdna_available",
        lambda: {"available": True, "mrdna": "/x", "arbd": "/y"},
    )
    monkeypatch.setattr(routes_mrdna, "start_job", lambda job, ws: None)
    design_state.set_design_silent(make_6hb_design())

    client = TestClient(app)
    r = client.post("/api/mrdna/jobs", json={"coarse_steps": 5000, "autostart": True})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "queued"
    assert job["coarse_steps"] == 5000
    assert job["n_nucleotides"] > 0
    jid = job["job_id"]

    lst = client.get("/api/mrdna/jobs").json()
    assert any(j["job_id"] == jid for j in lst)

    assert client.get(f"/api/mrdna/jobs/{jid}").json()["job_id"] == jid
    assert "overall" in client.get(f"/api/mrdna/jobs/{jid}/progress").json()

    # Not-running stop is a no-op-ok; delete removes the folder.
    assert client.post(f"/api/mrdna/jobs/{jid}/stop").json()["ok"] is True
    assert client.delete(f"/api/mrdna/jobs/{jid}").json()["ok"] is True
    assert not (tmp_path / "mrdna_jobs" / jid).exists()


def test_mrdna_display_and_beads_serve_cached(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_mrdna as routes_mrdna

    monkeypatch.setattr(routes_mrdna, "_WORKSPACE_DIR", tmp_path)
    job = new_mrdna_job("d")
    job.status = MrdnaStatus.completed
    job.stages[0].status = "done"
    job.save(tmp_path)
    jd = job.job_dir(tmp_path)
    from backend.core.mrdna_manifest import MrdnaNucleotideManifest

    MrdnaNucleotideManifest(
        design_fingerprint="test", records=[]
    ).write(jd)
    (jd / "display.json").write_text(
        json.dumps(
            {
                "positions": [
                    {
                        "helix_id": "h",
                        "bp_index": 0,
                        "direction": "FORWARD",
                        "backbone_position": [1, 2, 3],
                    },
                ]
            }
        )
    )
    (jd / "beads.json").write_text(
        json.dumps({"beads": [[0, 0, 0], [1, 1, 1]], "edges": [[0, 1]]})
    )

    client = TestClient(app)
    disp = client.get(f"/api/mrdna/jobs/{job.job_id}/display").json()
    assert disp["ready"] is True and disp["n_positions"] == 1
    beads = client.get(f"/api/mrdna/jobs/{job.job_id}/beads").json()
    assert beads["ready"] is True and beads["n_beads"] == 2
    assert beads["edges"] == [[0, 1]]  # CG bond connectivity for the sticks view


def test_load_beads_with_edges_passthrough(tmp_path):
    import backend.core.mrdna_runner as r

    job = new_mrdna_job("d")
    job.save(tmp_path)
    jd = job.job_dir(tmp_path)
    (jd / "beads.json").write_text(
        json.dumps({"beads": [[0, 0, 0]], "edges": [[0, 0]]})
    )
    assert r.load_beads_with_edges(jd)["edges"] == [[0, 0]]


def test_load_beads_with_edges_backfills_from_psf(tmp_path, monkeypatch):
    """A job cached before the edges feature (beads.json has no 'edges') gets its CG
    connectivity backfilled from the coarse PSF on read, and re-cached."""
    import backend.core.mrdna_runner as r

    job = new_mrdna_job("d")
    job.save(tmp_path)
    jd = job.job_dir(tmp_path)
    (jd / "beads.json").write_text(
        json.dumps({"beads": [[0, 0, 0], [1, 1, 1]]})
    )  # no edges
    (jd / "mrdna_relax.psf").write_text("dummy")  # exists → backfill attempts
    monkeypatch.setattr(r, "_psf_dna_edges", lambda psf: [[0, 1]])
    out = r.load_beads_with_edges(jd)
    assert out["edges"] == [[0, 1]]
    assert json.loads((jd / "beads.json").read_text())["edges"] == [[0, 1]]  # persisted


def test_load_display_passthrough_current_version(tmp_path):
    import backend.core.mrdna_runner as r
    from backend.core.mrdna_manifest import MrdnaNucleotideManifest

    job = new_mrdna_job("d")
    job.save(tmp_path)
    jd = job.job_dir(tmp_path)
    MrdnaNucleotideManifest(design_fingerprint="test", records=[]).write(jd)
    (jd / "display.json").write_text(
        json.dumps({"version": r._DISPLAY_VERSION, "positions": [{"a": 1}]})
    )
    assert r.load_display(jd)["positions"] == [{"a": 1}]  # served as-is, not recomputed


def test_load_display_rejects_legacy_cache_without_manifest(tmp_path, monkeypatch):
    """Pre-manifest jobs are unsupported and require a rerun."""
    import backend.core.mrdna_runner as r

    job = new_mrdna_job("d")
    job.save(tmp_path)
    jd = job.job_dir(tmp_path)
    (jd / "display.json").write_text(
        json.dumps({"positions": [{"old": 1}]})
    )  # no version
    (jd / "design.json").write_text('{"dummy": 1}')
    (jd / "mrdna_relax.psf").write_text("x")
    (jd / "output").mkdir()
    (jd / "output" / "mrdna_relax.dcd").write_text("x")
    monkeypatch.setattr(r, "_load_snapshot_design", lambda d: object())
    fresh = [
        {
            "helix_id": "h",
            "bp_index": 0,
            "direction": "FORWARD",
            "backbone_position": [9, 9, 9],
        }
    ]
    monkeypatch.setattr(r, "_display_positions", lambda design, jd_: (fresh, 1))
    with pytest.raises(RuntimeError, match="rerun the job"):
        r.load_display(jd)


def test_mrdna_display_rejects_unsupported_legacy_job(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_mrdna as routes_mrdna

    monkeypatch.setattr(routes_mrdna, "_WORKSPACE_DIR", tmp_path)
    job = new_mrdna_job("d")
    job.save(tmp_path)
    response = TestClient(app).get(f"/api/mrdna/jobs/{job.job_id}/display")
    assert response.status_code == 409
    assert "rerun the job" in response.json()["detail"]


# ── Fine stage + curvature ────────────────────────────────────────────────────


def test_new_mrdna_job_fine_adds_second_stage():
    coarse = new_mrdna_job("d", coarse_steps=1000, fine_steps=0)
    assert [s.name for s in coarse.stages] == ["coarse"]
    fine = new_mrdna_job("d", coarse_steps=1000, fine_steps=5000)
    assert [s.name for s in fine.stages] == ["coarse", "fine"]
    assert fine.fine_steps == 5000


def test_mrdna_job_fine_steps_roundtrip(tmp_path):
    job = new_mrdna_job("d", fine_steps=200000)
    job.save(tmp_path)
    assert MrdnaJob.load(job.job_id, tmp_path).fine_steps == 200000


# ── display collapse detector (tight-bundle fine-stage fallback) ──────────────
#   The fine-stage bead→helix assignment can dump one helix's beads onto a close
#   neighbour, collapsing its spline into a ring (the reported 2hb artifact).
#   _override_has_collapsed_helix flags that so _display_positions falls back to the
#   coarse stage — but it must NOT mistake a genuinely BENT (curved-design) helix for
#   a collapse, or it would drop the fine reconstruction the curvature readout needs.


def _one_helix_design():
    from backend.core.lattice import make_bundle_design

    return make_bundle_design([(0, 0)], 42, name="1hb")  # length_bp 42 → ~14.3 nm


def _override_line(helix, n, span_nm):
    """n FORWARD nucleotides spread over span_nm along +Z (a straight/compressed rod)."""
    import numpy as np

    bp0 = helix.bp_start
    return {
        (helix.id, bp0 + i, "FORWARD"): np.array([0.0, 0.0, span_nm * i / (n - 1)])
        for i in range(n)
    }


def test_collapse_detector_flags_blob_but_not_full_or_bent():
    import math
    import numpy as np
    from backend.core.mrdna_runner import _override_has_collapsed_helix

    d = _one_helix_design()
    h = d.helices[0]
    full = h.length_bp * 0.34  # ~14.3 nm expected contour

    # (a) full-length straight rod → not collapsed
    assert not _override_has_collapsed_helix(d, _override_line(h, h.length_bp, full))
    # (b) collapsed into a 2 nm blob → collapsed
    assert _override_has_collapsed_helix(d, _override_line(h, h.length_bp, 2.0))
    # (c) a bent arc spanning its full contour (a curved design) → NOT collapsed:
    #     even a half-circle keeps a bounding diagonal well above the 0.45 threshold.
    R = full / math.pi  # semicircle of this contour length
    arc = {
        (h.id, h.bp_start + i, "FORWARD"): np.array(
            [
                R * math.sin(math.pi * i / (h.length_bp - 1)),
                R * (1 - math.cos(math.pi * i / (h.length_bp - 1))),
                0.0,
            ]
        )
        for i in range(h.length_bp)
    }
    assert not _override_has_collapsed_helix(d, arc)


def test_stretched_bond_detector_and_badness():
    """_count_stretched_backbone_bonds flags consecutive backbone steps > 1.3 nm
    (the partial-mis-assignment JUMP failure mode); _reconstruction_badness folds
    that together with the collapse penalty so the cleaner CG stage can be chosen."""
    import numpy as np
    from backend.core.mrdna_runner import (
        _count_stretched_backbone_bonds,
        _reconstruction_badness,
    )

    d = _one_helix_design()
    h = d.helices[0]
    # A clean helical backbone (0.67 nm steps) → no stretched bonds.
    clean = {
        (h.id, h.bp_start + i, "FORWARD"): np.array([0.0, 0.0, 0.67 * i])
        for i in range(20)
    }
    assert _count_stretched_backbone_bonds(clean) == 0
    # Inject a 2 nm jump between two consecutive bp → one stretched bond.
    jumpy = dict(clean)
    jumpy[(h.id, h.bp_start + 10, "FORWARD")] = np.array([0.0, 0.0, 0.67 * 9 + 2.0])
    assert _count_stretched_backbone_bonds(jumpy) >= 1
    # Badness: clean < jumpy, and a collapse dwarfs any bond count.
    assert _reconstruction_badness(d, clean) < _reconstruction_badness(d, jumpy)
    blob = _override_line_blob(h)
    assert _reconstruction_badness(d, blob) >= 1000  # collapse penalty dominates


def test_periodic_unwrap_restores_bonded_chain_and_reference_image():
    import numpy as np

    from backend.core.mrdna_bridge import unwrap_periodic_positions

    wrapped = np.array([[0.0, 0.0, 4.9], [0.0, 0.0, -4.9], [0.0, 0.0, -4.6]])
    bonds = np.array([[0, 1], [1, 2]])
    reference = np.array([[0.0, 0.0, 14.9], [0.0, 0.0, 15.1], [0.0, 0.0, 15.4]])

    out = unwrap_periodic_positions(
        wrapped, bonds, np.array([10.0, 10.0, 10.0]), reference=reference
    )

    assert np.allclose(np.diff(out[:, 2]), [0.2, 0.3])
    assert np.allclose(out, reference)


def test_mrdna_box_has_large_clearance_for_long_design():
    from backend.core.mrdna_runner import _mrdna_box_dimensions
    from tests.conftest import make_6hb_design

    d = make_6hb_design(length_bp=1200)
    dims = _mrdna_box_dimensions(d)

    max_abs_ang = max(
        abs(float(v)) * 10.0
        for h in d.helices
        for p in (h.axis_start, h.axis_end)
        for v in (p.x, p.y, p.z)
    )
    assert min(dims) >= 5000.0
    assert max(dims) >= 2.0 * (max_abs_ang + 5000.0)


def _override_line_blob(helix):
    import numpy as np

    return {
        (helix.id, helix.bp_start + i, "FORWARD"): np.array(
            [0.0, 0.0, 2.0 * i / (helix.length_bp - 1)]
        )
        for i in range(helix.length_bp)
    }


def test_analytic_curvature_from_marks():
    from backend.core.mrdna_curvature import analytic_curvature
    from tests.conftest import make_6hb_curved_design

    d = make_6hb_curved_design()
    a = analytic_curvature(d)
    assert a["has_marks"] is True
    assert a["n_loops"] == 18 and a["n_skips"] == 18
    assert 25.0 < a["radius_nm"] < 50.0  # ~36 nm Dietz prediction
    assert a["kappa_deg_per_nm"] > 1.0


def test_analytic_curvature_no_marks_is_straight():
    from backend.core.mrdna_curvature import analytic_curvature
    from tests.conftest import make_6hb_design

    d = make_6hb_design(length_bp=192)
    a = analytic_curvature(d)
    assert a["has_marks"] is False
    assert a["kappa_deg_per_nm"] == 0.0


def test_measured_curvature_straight_and_bent():
    import math
    from backend.core.mrdna_curvature import measured_curvature

    # a straight line of bp midpoints → ~infinite radius, ~0 curvature
    straight = [
        {
            "helix_id": "h",
            "bp_index": i,
            "direction": "FORWARD",
            "backbone_position": [i * 0.34, 0.0, 0.0],
        }
        for i in range(60)
    ]
    assert measured_curvature(straight)["kappa_deg_per_nm"] < 0.05
    # a clean arc of radius 30 nm → measured radius ≈ 30
    R = 30.0
    arc = [
        {
            "helix_id": "h",
            "bp_index": i,
            "direction": "FORWARD",
            "backbone_position": [
                R * math.sin(i * 0.03),
                R * (1 - math.cos(i * 0.03)),
                0.0,
            ],
        }
        for i in range(60)
    ]
    r = measured_curvature(arc)["radius_nm"]
    assert 25.0 < r < 35.0


def test_curvature_endpoint(monkeypatch, tmp_path):
    import json as _json
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_mrdna as routes_mrdna

    monkeypatch.setattr(routes_mrdna, "_WORKSPACE_DIR", tmp_path)
    job = new_mrdna_job("d", fine_steps=200000)
    job.status = MrdnaStatus.completed
    job.save(tmp_path)
    from backend.core.mrdna_manifest import MrdnaNucleotideManifest

    MrdnaNucleotideManifest(design_fingerprint="test", records=[]).write(
        job.job_dir(tmp_path)
    )
    (job.job_dir(tmp_path) / "curvature.json").write_text(
        _json.dumps(
            {
                "analytic": {
                    "has_marks": True,
                    "radius_nm": 36.0,
                    "kappa_deg_per_nm": 1.58,
                    "bend_deg": 88.0,
                },
                "measured": {
                    "radius_nm": 45.0,
                    "kappa_deg_per_nm": 1.27,
                    "bend_deg": 70.0,
                },
                "ratio": 0.8,
            }
        )
    )
    r = TestClient(app).get(f"/api/mrdna/jobs/{job.job_id}/curvature").json()
    assert r["ready"] is True and r["fine"] is True
    assert r["analytic"]["radius_nm"] == 36.0 and r["ratio"] == 0.8
