"""Unit tests for backend/core/md_executor.py — the remote SLURM executor.

No network: a FakeConn stands in for the asyncssh ClusterConnection, returning
canned ``sbatch``/``squeue``/``sacct`` output and recording every op.  Pure parsers
are tested directly.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from backend.core import cluster_config as cc
from backend.core import md_executor as ex
from backend.core.cluster_ssh import RunResult
from backend.core.md_job import MdJob, MdSegmentStatus, MdStatus, new_job


def _run(coro):
    return asyncio.run(coro)


# ── Pure parsers ──────────────────────────────────────────────────────────────

def test_parse_sbatch_job_id():
    assert ex.parse_sbatch_job_id("Submitted batch job 1234567") == "1234567"
    assert ex.parse_sbatch_job_id("garbage") is None
    assert ex.parse_sbatch_job_id("") is None


def test_parse_state_lines_squeue():
    out = "1234567|RUNNING\n1234568|PENDING\n"
    assert ex.parse_state_lines(out) == {"1234567": "RUNNING", "1234568": "PENDING"}


def test_parse_state_lines_sacct_substeps_and_cancelled():
    # sacct emits sub-step rows and "CANCELLED by <uid>" — base id + first token only.
    out = "1234567|COMPLETED\n1234567.batch|COMPLETED\n1234568|CANCELLED by 55\n"
    parsed = ex.parse_state_lines(out)
    assert parsed["1234567"] == "COMPLETED"
    assert parsed["1234568"] == "CANCELLED"


def test_map_slurm_state_buckets():
    assert ex.map_slurm_state("PENDING") == "pending"
    assert ex.map_slurm_state("R") == "running"
    assert ex.map_slurm_state("COMPLETED") == "completed"
    assert ex.map_slurm_state("CANCELLED") == "cancelled"
    for f in ("FAILED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL"):
        assert ex.map_slurm_state(f) == "failed"
    # Unknown → keep polling.
    assert ex.map_slurm_state("WEIRD") == "running"


def test_bucket_to_md_status():
    assert ex.bucket_to_md_status("pending") == MdStatus.queued
    assert ex.bucket_to_md_status("running") == MdStatus.running
    assert ex.bucket_to_md_status("completed") == MdStatus.completed
    assert ex.bucket_to_md_status("cancelled") == MdStatus.stopped
    assert ex.bucket_to_md_status("failed") == MdStatus.failed


def test_stage_plan_skips_output_and_logs(tmp_path):
    pkg = tmp_path / "pkg"
    (pkg / "forcefield").mkdir(parents=True)
    (pkg / "output").mkdir()
    (pkg / "manifest.json").write_text("{}")
    (pkg / "demo.psf").write_text("psf")
    (pkg / "forcefield" / "par.prm").write_text("prm")
    (pkg / "demo.log").write_text("log")                 # skip: *.log
    (pkg / "output" / "demo_01.dcd").write_text("dcd")   # skip: output/ tree
    rels = {rel for _, rel in ex.stage_plan(pkg)}
    assert rels == {"manifest.json", "demo.psf", "forcefield/par.prm"}


# ── FakeConn + fixtures ───────────────────────────────────────────────────────

class FakeConn:
    """Records ops; returns canned outputs by command substring."""

    def __init__(self, *, user="jojo", connected=True, canned=None, get_contents=None):
        self.user = user
        self._connected = connected
        self.canned: dict[str, RunResult] = canned or {}
        self.get_contents: dict[str, str] = get_contents or {}   # remote substr → downloaded text
        self.runs: list[str] = []
        self.puts: list[tuple[str, str]] = []
        self.put_contents: dict[str, str | None] = {}   # remote → uploaded text
        self.gets: list[tuple[str, str]] = []
        self.mkdirs: list[str] = []
        self.mirrors: list[tuple[str, str]] = []

    def is_connected(self):
        return self._connected

    async def run(self, cmd, timeout=60.0):
        self.runs.append(cmd)
        for key, res in self.canned.items():
            if key in cmd:
                return res
        return RunResult(rc=0, stdout="", stderr="")

    async def mkdir_p(self, d):
        self.mkdirs.append(d)

    async def sftp_put(self, local, remote):
        self.puts.append((local, remote))
        try:
            self.put_contents[remote] = Path(local).read_text()
        except OSError:
            self.put_contents[remote] = None

    async def sftp_get(self, remote, local):
        self.gets.append((remote, local))
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        for key, content in self.get_contents.items():
            if key in remote:
                Path(local).write_text(content)
                return
        Path(local).write_text("fetched")

    async def mirror(self, src, dst):
        self.mirrors.append((src, dst))
        return RunResult(rc=0, stdout="", stderr="")


def _make_prepared_job(workspace: Path) -> MdJob:
    job = new_job("6hb_demo", "mgh_slow_release", name_stem="6hb_demo",
                  package_subdir="pkg")
    job.execution_target = "alpine"
    job.segments = [
        MdSegmentStatus(name="6hb_demo_01_p100", stage="relax", percent=100, steps=1000),
    ]
    job.save(workspace)
    pkg = job.package_dir(workspace)
    pkg.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name_stem": "6hb_demo",
        "declash": False,
        "relax_protocol_settings": {"timestep_fs": 2.0},
        "charge_audit": {"final_solvated": {"n_atoms": 100_000}},
        "minimization": {"name": "6hb_demo_00_min"},
        "segments": [{"name": "6hb_demo_01_p100", "steps": 1_000_000}],
    }
    (pkg / "manifest.json").write_text(json.dumps(manifest))
    (pkg / "6hb_demo.psf").write_text("psf")
    (pkg / "6hb_demo.pdb").write_text("pdb")
    return job


@pytest.fixture
def alpine():
    return cc.alpine_profile()


@pytest.fixture
def resources(alpine):
    from backend.core import cluster_resources as cr
    return cr.recommend(alpine, n_atoms=100_000, total_ns=2.0, measured_ns_per_day=50.0)


# ── submit_job ────────────────────────────────────────────────────────────────

def test_submit_job_stages_and_parses_id(tmp_path, alpine, resources):
    job = _make_prepared_job(tmp_path)
    conn = FakeConn(canned={"sbatch": RunResult(0, "Submitted batch job 987654", "")})

    out = _run(ex.submit_job(job, tmp_path, profile=alpine, resources=resources, conn=conn))

    assert out.slurm_job_id == "987654"
    assert out.status == MdStatus.queued
    assert out.queued_at is not None          # stamped for the queued-wait tooltip
    assert out.execution_target == "alpine"
    assert out.cluster_name == "alpine"
    assert out.remote_project_dir == "/projects/jojo/nadoc_jobs/" + job.job_id
    assert out.remote_scratch_dir == "/scratch/alpine/jojo/nadoc_jobs/" + job.job_id
    # PSF/PDB/manifest staged; the sbatch uploaded into scratch and submitted there.
    staged = {r for _, r in conn.puts}
    assert any(r.endswith("/6hb_demo.psf") for r in staged)
    assert any(r.endswith("/" + ex._SBATCH_NAME) for r in staged)
    assert conn.mirrors and conn.mirrors[0][0] == out.remote_project_dir
    assert any("sbatch" in c for c in conn.runs)
    # Persisted.
    assert MdJob.load(job.job_id, tmp_path).slurm_job_id == "987654"


def _add_gpu_conf(job, workspace, name="6hb_demo_01_p100.conf"):
    """Drop a fast-segment conf carrying ``GPUresident on`` into the package."""
    (job.package_dir(workspace) / name).write_text(
        "timestep           4\nGPUresident        on\nrun                600000\n"
    )
    return name


def test_submit_amends_confs_for_cpu_target(tmp_path, alpine):
    """A CPU/multicore Alpine target must not inherit ``GPUresident on`` — every
    staged .conf is amended, not just the ones that happen to lack it."""
    from backend.core import cluster_resources as cr
    cpu = cr.recommend(alpine, n_atoms=100_000, total_ns=2.0, partition="amilan")
    job = _make_prepared_job(tmp_path)
    conf = _add_gpu_conf(job, tmp_path)
    conn = FakeConn(canned={"sbatch": RunResult(0, "Submitted batch job 5", "")})
    _run(ex.submit_job(job, tmp_path, profile=alpine, resources=cpu, conn=conn))
    remote = next(r for r in conn.put_contents if r.endswith("/" + conf))
    assert "GPUresident" not in (conn.put_contents[remote] or "")
    assert "timestep" in (conn.put_contents[remote] or "")   # rest preserved


def test_submit_keeps_confs_verbatim_for_gpu_target(tmp_path, alpine, resources):
    """A GPU target keeps ``GPUresident on`` (matches the +devices exec line)."""
    job = _make_prepared_job(tmp_path)
    conf = _add_gpu_conf(job, tmp_path)
    conn = FakeConn(canned={"sbatch": RunResult(0, "Submitted batch job 6", "")})
    _run(ex.submit_job(job, tmp_path, profile=alpine, resources=resources, conn=conn))
    remote = next(r for r in conn.put_contents if r.endswith("/" + conf))
    assert "GPUresident" in (conn.put_contents[remote] or "")


def test_submit_job_idempotent(tmp_path, alpine, resources):
    job = _make_prepared_job(tmp_path)
    job.slurm_job_id = "111"
    conn = FakeConn(canned={"sbatch": RunResult(0, "Submitted batch job 999", "")})
    out = _run(ex.submit_job(job, tmp_path, profile=alpine, resources=resources, conn=conn))
    assert out.slurm_job_id == "111"          # not re-submitted
    assert not conn.runs                       # no sbatch issued


def test_submit_job_raises_on_sbatch_failure(tmp_path, alpine, resources):
    job = _make_prepared_job(tmp_path)
    conn = FakeConn(canned={"sbatch": RunResult(1, "", "sbatch: error: bad qos")})
    with pytest.raises(RuntimeError, match="sbatch failed"):
        _run(ex.submit_job(job, tmp_path, profile=alpine, resources=resources, conn=conn))


# ── NAMD module discovery ─────────────────────────────────────────────────────

def test_parse_namd_modules_keeps_only_namd_tokens():
    terse = (
        "/curc/sw/modulefiles/gcc/14.2.0:\n"
        "namd/3.0.1_cpu\n"
        "namd/3.0.1_gpu\n"
        "namd\n"
        "openmpi/5.0.6\n"
        "/curc/sw/other:\n"
    )
    assert ex.parse_namd_modules(terse) == ["namd", "namd/3.0.1_cpu", "namd/3.0.1_gpu"]


def test_parse_namd_modules_empty():
    assert ex.parse_namd_modules("") == []
    assert ex.parse_namd_modules("no modules here\nfoo/1.0\n") == []


def test_list_namd_modules_runs_module_avail(tmp_path):
    conn = FakeConn(canned={"module": RunResult(0, "", "namd/3.0.1_cpu\nnamd/3.0.1_gpu\n")})
    mods = _run(ex.list_namd_modules(conn=conn))
    assert mods == ["namd/3.0.1_cpu", "namd/3.0.1_gpu"]
    assert any("module -t avail namd" in c for c in conn.runs)


# ── poll_status ───────────────────────────────────────────────────────────────

def test_poll_status_squeue_hit(tmp_path):
    job = new_job("d", "p", name_stem="d", package_subdir="pkg")
    job.slurm_job_id = "42"
    conn = FakeConn(canned={"squeue": RunResult(0, "42|RUNNING", "")})
    raw, bucket = _run(ex.poll_status(job, conn=conn))
    assert (raw, bucket) == ("RUNNING", "running")


def test_poll_status_falls_back_to_sacct(tmp_path):
    job = new_job("d", "p", name_stem="d", package_subdir="pkg")
    job.slurm_job_id = "42"
    conn = FakeConn(canned={
        "squeue": RunResult(0, "", ""),                  # gone from the queue
        "sacct": RunResult(0, "42|COMPLETED", ""),
    })
    raw, bucket = _run(ex.poll_status(job, conn=conn))
    assert bucket == "completed"


def test_poll_status_absent_everywhere_is_completed(tmp_path):
    job = new_job("d", "p", name_stem="d", package_subdir="pkg")
    job.slurm_job_id = "42"
    conn = FakeConn()  # both empty
    _, bucket = _run(ex.poll_status(job, conn=conn))
    assert bucket == "completed"


# ── reconcile_remote_job ──────────────────────────────────────────────────────

def test_reconcile_running_updates_state(tmp_path, alpine, resources):
    job = _make_prepared_job(tmp_path)
    job.slurm_job_id = "42"
    job.status = MdStatus.queued
    conn = FakeConn(canned={"squeue": RunResult(0, "42|RUNNING", "")})
    out = _run(ex.reconcile_remote_job(job, tmp_path, conn=conn))
    assert out.status == MdStatus.running
    assert out.slurm_state == "RUNNING"


def test_reconcile_completed_fetches_and_marks_done(tmp_path, alpine, resources):
    job = _make_prepared_job(tmp_path)
    job.slurm_job_id = "42"
    job.remote_scratch_dir = "/scratch/alpine/jojo/nadoc_jobs/" + job.job_id
    job.remote_project_dir = "/projects/jojo/nadoc_jobs/" + job.job_id
    conn = FakeConn(canned={
        "squeue": RunResult(0, "", ""),
        "sacct": RunResult(0, "42|COMPLETED", ""),
        "find": RunResult(0, "output/6hb_demo_01_p100.dcd\n6hb_demo_01_p100.log\n", ""),
    })
    out = _run(ex.reconcile_remote_job(job, tmp_path, conn=conn))
    assert out.status == MdStatus.completed
    # scratch→project mirror happened; the listed files were pulled down locally.
    assert conn.mirrors and conn.mirrors[-1][0] == job.remote_scratch_dir
    assert conn.gets


def test_reconcile_cancelled_marks_stopped(tmp_path):
    job = _make_prepared_job(tmp_path)
    job.slurm_job_id = "42"
    job.remote_scratch_dir = "/scratch/x/" + job.job_id
    conn = FakeConn(canned={
        "squeue": RunResult(0, "", ""),
        "sacct": RunResult(0, "42|CANCELLED", ""),
        "find": RunResult(0, "", ""),
    })
    out = _run(ex.reconcile_remote_job(job, tmp_path, conn=conn))
    assert out.status == MdStatus.stopped
    assert out.user_stopped is True


def test_reconcile_failed_marks_failed(tmp_path):
    job = _make_prepared_job(tmp_path)
    job.slurm_job_id = "42"
    job.remote_scratch_dir = "/scratch/x/" + job.job_id
    # NODE_FAIL is a genuine error (not a walltime TIMEOUT) → no auto-resubmit.
    conn = FakeConn(canned={
        "squeue": RunResult(0, "", ""),
        "sacct": RunResult(0, "42|NODE_FAIL", ""),
        "find": RunResult(0, "", ""),
    })
    out = _run(ex.reconcile_remote_job(job, tmp_path, conn=conn))
    assert out.status == MdStatus.failed
    assert "NODE_FAIL" in (out.error or "")


def test_reconcile_failed_surfaces_namd_cause(tmp_path):
    """A NAMD FATAL in a fetched segment log must reach job.error, not just the
    bare SLURM state — this is the user-facing "why did it fail" surfacing."""
    job = _make_prepared_job(tmp_path)
    job.slurm_job_id = "42"
    job.remote_scratch_dir = "/scratch/x/" + job.job_id
    # Simulate an already-fetched NAMD log carrying the real cause.
    (job.package_dir(tmp_path) / "6hb_demo_01_p50.log").write_text(
        "Info: Startup phase 0\n"
        "FATAL ERROR: GPUresident not supported on regular multicore builds\n"
    )
    conn = FakeConn(canned={
        "squeue": RunResult(0, "", ""),
        "sacct": RunResult(0, "42|FAILED", ""),
        "find": RunResult(0, "", ""),
    })
    out = _run(ex.reconcile_remote_job(job, tmp_path, conn=conn))
    assert out.status == MdStatus.failed
    assert "GPUresident not supported" in (out.error or "")
    assert "FAILED" in (out.error or "")          # keeps the SLURM state too
    assert out.failure_kind == "other"


def test_scan_logs_prefers_namd_log_over_slurm_err(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "seg_p50.log").write_text("Info\nFATAL ERROR: real NAMD cause\n")
    (pkg / "job_42.err").write_text("srun: error: some launcher noise\n")
    excerpt, src, kind = ex._scan_logs_for_error(pkg)
    assert excerpt == "FATAL ERROR: real NAMD cause"
    assert src == "seg_p50.log"


def test_scan_logs_none_when_clean(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "seg.log").write_text("Info: benchmark 10 ns/day\nWallClock 3.0\n")
    assert ex._scan_logs_for_error(pkg) == (None, None, None)


# ── live segment progress (running remote job) ────────────────────────────────

def test_parse_progress_listing():
    finished, started = ex.parse_progress_listing(
        "output/s_p10.coor\noutput/s_p10.restart.coor\ns_p10.log\ns_p50.log\n"
    )
    assert finished == {"s_p10", "s_p10.restart"}   # .restart harmlessly present
    assert started == {"s_p10", "s_p50"}


def test_apply_remote_progress_advances_segments():
    job = new_job("d", "p", name_stem="d", package_subdir="pkg")
    job.segments = [
        MdSegmentStatus(name="s_p10", stage="relax", percent=10, steps=1),
        MdSegmentStatus(name="s_p50", stage="relax", percent=50, steps=1),
        MdSegmentStatus(name="s_p100", stage="relax", percent=100, steps=1),
    ]
    changed = ex.apply_remote_progress(job, {"s_p10"}, {"s_p10", "s_p50"})
    assert changed is True
    assert [s.status for s in job.segments] == ["done", "running", "pending"]
    assert job.current_segment_idx == 1


def test_apply_remote_progress_never_regresses_done():
    job = new_job("d", "p", name_stem="d", package_subdir="pkg")
    job.segments = [MdSegmentStatus(name="s", stage="relax", percent=10, steps=1)]
    job.segments[0].status = "done"
    # A lingering log with no fresh .coor listing must not flip done→running.
    assert ex.apply_remote_progress(job, set(), {"s"}) is False
    assert job.segments[0].status == "done"


def test_reconcile_running_reflects_segment_progress(tmp_path):
    job = _make_prepared_job(tmp_path)
    job.slurm_job_id = "42"
    job.remote_scratch_dir = "/scratch/x/" + job.job_id
    job.status = MdStatus.running
    job.segments = [
        MdSegmentStatus(name="s_p10", stage="relax", percent=10, steps=1),
        MdSegmentStatus(name="s_p50", stage="relax", percent=50, steps=1),
        MdSegmentStatus(name="s_p100", stage="relax", percent=100, steps=1),
    ]
    conn = FakeConn(canned={
        "squeue": RunResult(0, "42|RUNNING", ""),
        "ls -1 output": RunResult(0, "output/s_p10.coor\ns_p10.log\ns_p50.log\n", ""),
    })
    out = _run(ex.reconcile_remote_job(job, tmp_path, conn=conn))
    assert [s.status for s in out.segments] == ["done", "running", "pending"]
    assert out.current_segment_idx == 1
    # Persisted so the panel poll sees it.
    assert MdJob.load(job.job_id, tmp_path).current_segment_idx == 1


# ── TIMEOUT → resumable + user-driven resume ──────────────────────────────────

def test_reconcile_timeout_marks_resumable_not_failed(tmp_path):
    """A walltime TIMEOUT is expected for the short-job strategy — the job goes
    resumable (paused), NOT failed, and does NOT auto-resubmit (Duo needs the user)."""
    job = _make_prepared_job(tmp_path)
    job.slurm_job_id = "42"
    job.remote_scratch_dir = "/scratch/x/" + job.job_id
    conn = FakeConn(canned={
        "squeue": RunResult(0, "", ""),
        "sacct": RunResult(0, "42|TIMEOUT", ""),
        "find": RunResult(0, "", ""),
    })
    out = _run(ex.reconcile_remote_job(job, tmp_path, conn=conn))
    assert out.status == MdStatus.paused
    assert out.resumable is True
    assert out.failure_kind == "cluster_timeout"
    assert "Resume" in (out.error or "")
    assert out.resubmit_count == 0                 # no automatic resubmit
    assert not any("sbatch" in c for c in conn.runs)
    # the finished attempt is recorded for the expand chevron.
    assert out.resume_history[-1]["slurm_job_id"] == "42"
    assert out.resume_history[-1]["state"] == "TIMEOUT"


def _make_resumable_job(tmp_path, alpine):
    from backend.core import cluster_resources as cr
    job = _make_prepared_job(tmp_path)
    job.slurm_job_id = "42"
    job.cluster_name = "alpine"
    job.remote_scratch_dir = "/scratch/alpine/jojo/nadoc_jobs/" + job.job_id
    job.resources = cr.recommend(alpine, n_atoms=100_000, total_ns=2.0, partition="amilan")
    job.resumable = True
    job.status = MdStatus.paused
    job.segments = [
        MdSegmentStatus(name="6hb_demo_01_p50", stage="relax", percent=50, steps=1),
        MdSegmentStatus(name="6hb_demo_02_p100", stage="relax", percent=100, steps=1),
    ]
    pkg = job.package_dir(tmp_path)
    (pkg / "6hb_demo_01_p50.conf").write_text(
        "structure          x.psf\nbinCoordinates     start.coor\n"
        "firsttimestep      0\nGPUresident        on\n"
        "outputName         output/6hb_demo_01_p50\nrun                480000\n"
    )
    manifest = json.loads((pkg / "manifest.json").read_text())
    manifest["segments"] = [
        {"name": "6hb_demo_01_p50", "steps": 480000},
        {"name": "6hb_demo_02_p100", "steps": 480000},
    ]
    (pkg / "manifest.json").write_text(json.dumps(manifest))
    job.save(tmp_path)
    return job


def test_resume_job_mid_segment_from_checkpoint(tmp_path, alpine):
    job = _make_resumable_job(tmp_path, alpine)
    # seg 1 started but not finished (log, no .coor); its restart.xsc has a step.
    conn = FakeConn(
        canned={
            "ls -1 output": RunResult(0, "6hb_demo_01_p50.log\n", ""),
            "sbatch": RunResult(0, "Submitted batch job 88", ""),
        },
        get_contents={"6hb_demo_01_p50.restart.xsc":
                      "# NAMD\n144000 100.0 0 0 0 100.0 0 0 0 100.0 50 50 50\n"},
    )
    out = _run(ex.resume_job(job, tmp_path, profile=alpine, conn=conn))
    assert out.slurm_job_id == "88"
    assert out.status == MdStatus.queued
    assert out.resubmit_count == 1
    assert out.resumable is False
    # A resume conf was uploaded, continuing from step 144000 for the remainder, and
    # GPUresident stripped (CPU target).
    resume = next(v for k, v in conn.put_contents.items()
                  if k.endswith("6hb_demo_01_p50.resume.conf"))
    assert "firsttimestep      144000" in resume
    assert "run                336000" in resume          # 480000 - 144000
    assert "GPUresident" not in resume
    # The uploaded sbatch runs the resume conf for the interrupted segment.
    sbatch = next(v for k, v in conn.put_contents.items() if k.endswith(ex._SBATCH_NAME))
    assert "6hb_demo_01_p50.resume.conf" in sbatch


def test_resume_job_applies_resource_override(tmp_path, alpine):
    """Reviewed/edited resources (e.g. a longer walltime) are used for the resumed run."""
    job = _make_resumable_job(tmp_path, alpine)
    override = dict(job.resources)
    override["walltime"] = "02:00:00"
    conn = FakeConn(
        canned={"ls -1 output": RunResult(0, "", ""),
                "sbatch": RunResult(0, "Submitted batch job 55", "")},
        get_contents={"restart.xsc": "not-an-xsc"},
    )
    out = _run(ex.resume_job(job, tmp_path, profile=alpine, resources=override, conn=conn))
    assert out.resources["walltime"] == "02:00:00"
    assert out.queued_at is not None          # re-stamped on resume (fresh queue wait)
    sbatch = next(v for k, v in conn.put_contents.items() if k.endswith(ex._SBATCH_NAME))
    assert "#SBATCH --time=02:00:00" in sbatch


def test_remote_recommendation_current_seeds_from_job_resources(tmp_path, monkeypatch):
    """Resume review (current=true) shows the job's CURRENT resources, not a fresh
    auto-recommend — so the user reviews the (short) walltime they actually ran."""
    from backend.api import routes_md
    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    job = _make_prepared_job(tmp_path)
    job.resources = {"partition": "amilan", "kind": "cpu", "gpus": 0, "cores": 8,
                     "mem_gb": 12, "walltime": "00:10:00", "qos": "normal"}
    job.slurm_job_id = "42"          # already submitted (resumable)
    job.save(tmp_path)
    out = routes_md.md_job_remote_recommendation(job.job_id, current=True)
    assert out["prepared"] is True
    assert out["resources"]["walltime"] == "00:10:00"   # current, not a fresh long auto-size
    assert out["resources"]["partition"] == "amilan"
    # amilan → plain QoS tiers offered (keyed off the seeded partition).
    assert {q["name"] for q in out["available_qos"]} == {"normal", "long"}


def test_resume_job_no_checkpoint_reruns_fresh(tmp_path, alpine):
    """Timed out before the first restart write → no usable checkpoint → the segment
    just re-runs fresh (idempotent sbatch), no resume conf uploaded."""
    job = _make_resumable_job(tmp_path, alpine)
    conn = FakeConn(
        canned={
            "ls -1 output": RunResult(0, "", ""),        # nothing finished/started
            "sbatch": RunResult(0, "Submitted batch job 99", ""),
        },
        get_contents={"6hb_demo_01_p50.restart.xsc": "not-an-xsc"},   # no step
    )
    out = _run(ex.resume_job(job, tmp_path, profile=alpine, conn=conn))
    assert out.slurm_job_id == "99"
    assert not any(k.endswith(".resume.conf") for k in conn.put_contents)


def test_reconcile_completed_records_learned_throughput(tmp_path):
    from backend.core import cluster_throughput
    job = _make_prepared_job(tmp_path)
    job.slurm_job_id = "42"
    job.cluster_name = "alpine"
    job.resources = {"partition": "amilan"}
    job.remote_scratch_dir = "/scratch/x/" + job.job_id
    job.remote_project_dir = "/projects/x/" + job.job_id
    out_dir = job.package_dir(tmp_path) / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.jsonl").write_text(
        '{"segment": "6hb_demo_01_p100", "ns_per_day": 12.5}\n'
    )
    conn = FakeConn(canned={
        "squeue": RunResult(0, "", ""),
        "sacct": RunResult(0, "42|COMPLETED", ""),
        "find": RunResult(0, "", ""),
    })
    _run(ex.reconcile_remote_job(job, tmp_path, conn=conn))
    learned = cluster_throughput.lookup_throughput(
        tmp_path, cluster="alpine", partition="amilan", n_atoms=100_000
    )
    assert learned == 12.5


# ── cancel_job + poll_remote_jobs ─────────────────────────────────────────────

def test_cancel_job_issues_scancel(tmp_path):
    job = new_job("d", "p", name_stem="d", package_subdir="pkg")
    job.slurm_job_id = "42"
    conn = FakeConn()
    assert _run(ex.cancel_job(job, conn=conn)) is True
    assert any("scancel 42" in c for c in conn.runs)


def test_cancel_job_noop_without_id(tmp_path):
    job = new_job("d", "p", name_stem="d", package_subdir="pkg")
    conn = FakeConn()
    assert _run(ex.cancel_job(job, conn=conn)) is False


def test_poll_remote_jobs_disconnected_is_noop(tmp_path):
    conn = FakeConn(connected=False)
    assert _run(ex.poll_remote_jobs(tmp_path, conn=conn)) == []


def test_poll_remote_jobs_reconciles_active(tmp_path):
    job = _make_prepared_job(tmp_path)
    job.slurm_job_id = "42"
    job.status = MdStatus.queued
    job.save(tmp_path)
    conn = FakeConn(canned={"squeue": RunResult(0, "42|RUNNING", "")})
    touched = _run(ex.poll_remote_jobs(tmp_path, conn=conn))
    assert job.job_id in touched
    assert MdJob.load(job.job_id, tmp_path).status == MdStatus.running


# ── GET /md/jobs/{id}/remote-recommendation (Phase 4 review-card preview) ──────

def test_remote_recommendation_prepared(tmp_path, monkeypatch):
    """A prepared job returns sizing + auto-recommended resources, no submission."""
    from backend.api import routes_md
    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    job = _make_prepared_job(tmp_path)
    out = routes_md.md_job_remote_recommendation(job.job_id)
    assert out["prepared"] is True
    assert out["already_submitted"] is False
    assert out["n_atoms"] == 100_000
    assert out["total_ns"] == pytest.approx(2.0)
    assert out["resources"]["partition"]
    assert out["resources"]["qos"]


def test_remote_recommendation_unprepared_is_not_error(tmp_path, monkeypatch):
    """Still-preparing job → prepared:false with a reason, not a 400."""
    from backend.api import routes_md
    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    job = new_job("np", "mgh_slow_release", name_stem="np", package_subdir="pkg_np")
    job.execution_target = "alpine"
    job.save(tmp_path)
    out = routes_md.md_job_remote_recommendation(job.job_id)
    assert out["prepared"] is False
    assert "reason" in out


def test_remote_recommendation_unknown_profile_404(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from backend.api import routes_md
    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    job = _make_prepared_job(tmp_path)
    with pytest.raises(HTTPException) as exc:
        routes_md.md_job_remote_recommendation(job.job_id, cluster_name="nope")
    assert exc.value.status_code == 404


def test_remote_recommendation_lists_partitions_and_honours_forced_partition(tmp_path, monkeypatch):
    """The dropdown needs the partition list, and forcing amilan re-sizes to CPU."""
    from backend.api import routes_md
    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    job = _make_prepared_job(tmp_path)

    out = routes_md.md_job_remote_recommendation(job.job_id)
    names = {p["name"] for p in out["available_partitions"]}
    assert {"aa100", "amilan"} <= names

    # GPU auto-pick → gpu-* QoS tiers offered.
    assert {q["name"] for q in out["available_qos"]} == {"gpu-normal", "gpu-long", "gpu-testing"}

    forced = routes_md.md_job_remote_recommendation(job.job_id, partition="amilan")
    assert forced["resources"]["partition"] == "amilan"
    assert forced["resources"]["kind"] == "cpu"
    assert forced["resources"]["gpus"] == 0
    # amilan accepts ONLY normal/long (live-confirmed) — the dropdown must not offer
    # testing/mem/compile, which SLURM rejects on amilan.
    assert {q["name"] for q in forced["available_qos"]} == {"normal", "long"}


def test_remote_recommendation_unknown_partition_400(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from backend.api import routes_md
    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    job = _make_prepared_job(tmp_path)
    with pytest.raises(HTTPException) as exc:
        routes_md.md_job_remote_recommendation(job.job_id, partition="nope")
    assert exc.value.status_code == 400


# ── Failed remote submit records the error on the job (UI cleanup) ─────────────

def test_record_submit_failure_marks_job_without_losing_prepared_state(tmp_path, monkeypatch):
    """A rejected submit must leave a visible error but keep the job queued (prepared,
    retryable) — so it stops looking like a clean/running job in the UI."""
    from backend.api import routes_md
    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    job = _make_prepared_job(tmp_path)
    job.status = MdStatus.queued
    job.save(tmp_path)

    routes_md._record_submit_failure(job, "sbatch failed (rc=1): bad QoS")

    reloaded = MdJob.load(job.job_id, tmp_path)
    assert reloaded.status == MdStatus.queued        # still prepared / retryable
    assert reloaded.slurm_job_id is None
    assert "Cluster submission failed" in (reloaded.error or "")
    assert "bad QoS" in reloaded.error
