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
from backend.core import cluster_resources as cr
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
    (pkg / "demo.log").write_text("log")  # skip: *.log
    (pkg / "output" / "demo_01.dcd").write_text("dcd")  # skip: output/ tree
    rels = {rel for _, rel in ex.stage_plan(pkg)}
    assert rels == {"manifest.json", "demo.psf", "forcefield/par.prm"}


# ── FakeConn + fixtures ───────────────────────────────────────────────────────


class FakeConn:
    """Records ops; returns canned outputs by command substring."""

    def __init__(self, *, user="jojo", connected=True, canned=None, get_contents=None):
        self.user = user
        self._connected = connected
        self.canned: dict[str, RunResult] = canned or {}
        self.get_contents: dict[str, str] = (
            get_contents or {}
        )  # remote substr → downloaded text
        self.runs: list[str] = []
        self.puts: list[tuple[str, str]] = []
        self.put_contents: dict[str, str | None] = {}  # remote → uploaded text
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
    job = new_job(
        "6hb_demo", "mgh_slow_release", name_stem="6hb_demo", package_subdir="pkg"
    )
    job.execution_target = "alpine"
    job.segments = [
        MdSegmentStatus(
            name="6hb_demo_01_p100", stage="relax", percent=100, steps=1000
        ),
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

    out = _run(
        ex.submit_job(job, tmp_path, profile=alpine, resources=resources, conn=conn)
    )

    assert out.slurm_job_id == "987654"
    assert out.status == MdStatus.queued
    assert out.queued_at is not None  # stamped for the queued-wait tooltip
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

    cpu = cr.recommend(alpine, n_atoms=100_000, total_ns=2.0, partition="acpu")
    job = _make_prepared_job(tmp_path)
    conf = _add_gpu_conf(job, tmp_path)
    conn = FakeConn(canned={"sbatch": RunResult(0, "Submitted batch job 5", "")})
    _run(ex.submit_job(job, tmp_path, profile=alpine, resources=cpu, conn=conn))
    remote = next(r for r in conn.put_contents if r.endswith("/" + conf))
    assert "GPUresident" not in (conn.put_contents[remote] or "")
    assert "timestep" in (conn.put_contents[remote] or "")  # rest preserved


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
    out = _run(
        ex.submit_job(job, tmp_path, profile=alpine, resources=resources, conn=conn)
    )
    assert out.slurm_job_id == "111"  # not re-submitted
    assert not conn.runs  # no sbatch issued


def test_submit_job_raises_on_sbatch_failure(tmp_path, alpine, resources):
    job = _make_prepared_job(tmp_path)
    conn = FakeConn(canned={"sbatch": RunResult(1, "", "sbatch: error: bad qos")})
    with pytest.raises(RuntimeError, match="sbatch failed"):
        _run(
            ex.submit_job(job, tmp_path, profile=alpine, resources=resources, conn=conn)
        )


# ── early-stop evaluator staging ───────────────────────────────────────────────


def _staged_basenames(conn):
    return {r.rsplit("/", 1)[-1] for _, r in conn.puts} | set(conn.put_contents)


def _submit(job, tmp_path, alpine, resources):
    conn = FakeConn(canned={"sbatch": RunResult(0, "Submitted batch job 555", "")})
    _run(ex.submit_job(job, tmp_path, profile=alpine, resources=resources, conn=conn))
    return conn


def test_no_early_stop_staging_when_off(tmp_path, alpine, resources):
    job = _make_prepared_job(tmp_path)
    job.early_stop_relax = False  # ON by default since 2026-07-29; opt OUT here
    conn = _submit(job, tmp_path, alpine, resources)
    staged = {r for r in conn.put_contents}
    assert not any("nadoc_cutoff_eval.py" in r for r in staged)


def test_tier_b_stages_only_stdlib_evaluator(tmp_path, alpine, resources):
    job = _make_prepared_job(tmp_path)
    job.early_stop_relax = True  # tier defaults to B
    conn = _submit(job, tmp_path, alpine, resources)
    staged = {r for r in conn.put_contents}
    assert any(r.endswith("/nadoc_cutoff_eval.py") for r in staged)
    assert not any("nadoc_health_eval.py" in r for r in staged)
    assert not any(r.endswith("/md_health.py") for r in staged)


def test_tier_a_stages_health_scripts(tmp_path, alpine, resources):
    job = _make_prepared_job(tmp_path)
    job.early_stop_relax = True
    job.early_stop_tier = "A"
    conn = _submit(job, tmp_path, alpine, resources)
    staged = {r for r in conn.put_contents}
    assert any(r.endswith("/nadoc_cutoff_eval.py") for r in staged)
    assert any(r.endswith("/nadoc_health_eval.py") for r in staged)
    assert any(r.endswith("/md_health.py") for r in staged)
    # the staged md_health is the verbatim backend module (has run_health_check)
    md_health_text = next(
        t for r, t in conn.put_contents.items() if r.endswith("/md_health.py")
    )
    assert "def run_health_check" in md_health_text


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
    conn = FakeConn(
        canned={"module": RunResult(0, "", "namd/3.0.1_cpu\nnamd/3.0.1_gpu\n")}
    )
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
    conn = FakeConn(
        canned={
            "squeue": RunResult(0, "", ""),  # gone from the queue
            "sacct": RunResult(0, "42|COMPLETED", ""),
        }
    )
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
    # A genuinely-completed run brings back the segment's restart set (.coor/.vel/.xsc)
    # — that checkpoint is what resume + downstream chain-seeds restart from.
    conn = FakeConn(
        canned={
            "squeue": RunResult(0, "", ""),
            "sacct": RunResult(0, "42|COMPLETED", ""),
            "find": RunResult(
                0,
                    "7\toutput/6hb_demo_01_p100.coor\n7\toutput/6hb_demo_01_p100.vel\n"
                    "7\toutput/6hb_demo_01_p100.xsc\n7\toutput/6hb_demo_01_p100.dcd\n"
                    "7\t6hb_demo_01_p100.log\n",
                "",
            ),
        }
    )
    out = _run(ex.reconcile_remote_job(job, tmp_path, conn=conn))
    assert out.status == MdStatus.completed
    assert out.fetch_attempts == 0
    # scratch→project mirror happened; the listed files were pulled down locally.
    assert conn.mirrors and conn.mirrors[-1][0] == job.remote_scratch_dir
    assert conn.gets


def test_reconcile_completed_persists_processing_during_final_bookkeeping(
    tmp_path, alpine, resources, monkeypatch
):
    job = _make_prepared_job(tmp_path)
    job.slurm_job_id = "42"
    job.remote_scratch_dir = "/scratch/alpine/jojo/nadoc_jobs/" + job.job_id
    conn = FakeConn(
        canned={
            "squeue": RunResult(0, "", ""),
            "sacct": RunResult(0, "42|COMPLETED", ""),
            "find": RunResult(
                0,
                "7\toutput/6hb_demo_01_p100.coor\n"
                "7\toutput/6hb_demo_01_p100.vel\n"
                "7\toutput/6hb_demo_01_p100.xsc\n",
                "",
            ),
        }
    )

    def assert_processing(saved_job, workspace_dir):
        persisted = MdJob.load(saved_job.job_id, workspace_dir)
        assert persisted.download_status["state"] == "processing"
        assert persisted.download_status["processing_started_at"] > 0

    monkeypatch.setattr(ex, "_finalize_local_bookkeeping", assert_processing)
    out = _run(ex.reconcile_remote_job(job, tmp_path, conn=conn))

    assert out.status == MdStatus.completed
    assert out.download_status["state"] == "verified"
    assert out.download_status["processing_finished_at"] >= out.download_status["processing_started_at"]


def test_reconcile_completed_missing_checkpoint_stays_repollable(
    tmp_path, alpine, resources
):
    """ISSUE-15: SLURM says COMPLETED but the checkpoint restart files failed to
    download → the job must NOT flip to `completed` (that ends polling and strands the
    missing files). It stays re-pollable so the supervisor re-fetches next pass."""
    job = _make_prepared_job(tmp_path)
    job.slurm_job_id = "42"
    job.remote_scratch_dir = "/scratch/x/" + job.job_id
    # Fetch brings back only trajectory/log — NO .coor/.vel/.xsc (the dropped restart).
    conn = FakeConn(
        canned={
            "squeue": RunResult(0, "", ""),
            "sacct": RunResult(0, "42|COMPLETED", ""),
            "find": RunResult(
                0, "output/6hb_demo_01_p100.dcd\n6hb_demo_01_p100.log\n", ""
            ),
        }
    )
    out = _run(ex.reconcile_remote_job(job, tmp_path, conn=conn))
    assert out.status != MdStatus.completed
    assert ex.is_remote_active(out.status)  # still polled → will re-fetch
    assert out.fetch_attempts == 1
    assert "download" in (out.error or "").lower()


def test_reconcile_completed_missing_checkpoint_fails_after_retries(
    tmp_path, alpine, resources
):
    """Once the bounded re-fetch retries exhaust, a completed-but-never-downloaded
    checkpoint surfaces as a genuine failure naming the missing restart files."""
    job = _make_prepared_job(tmp_path)
    job.slurm_job_id = "42"
    job.remote_scratch_dir = "/scratch/x/" + job.job_id
    job.fetch_attempts = ex._MAX_FETCH_ATTEMPTS - 1  # this pass is the last
    conn = FakeConn(
        canned={
            "squeue": RunResult(0, "", ""),
            "sacct": RunResult(0, "42|COMPLETED", ""),
            "find": RunResult(
                0, "output/6hb_demo_01_p100.dcd\n6hb_demo_01_p100.log\n", ""
            ),
        }
    )
    out = _run(ex.reconcile_remote_job(job, tmp_path, conn=conn))
    assert out.status == MdStatus.failed
    assert out.fetch_attempts == ex._MAX_FETCH_ATTEMPTS
    assert out.failure_kind == "fetch_incomplete"
    assert ".coor" in (out.error or "")


def test_reconcile_cancelled_marks_stopped(tmp_path):
    job = _make_prepared_job(tmp_path)
    job.slurm_job_id = "42"
    job.remote_scratch_dir = "/scratch/x/" + job.job_id
    conn = FakeConn(
        canned={
            "squeue": RunResult(0, "", ""),
            "sacct": RunResult(0, "42|CANCELLED", ""),
            "find": RunResult(0, "", ""),
        }
    )
    out = _run(ex.reconcile_remote_job(job, tmp_path, conn=conn))
    assert out.status == MdStatus.stopped
    assert out.user_stopped is True


def test_reconcile_failed_marks_failed(tmp_path):
    job = _make_prepared_job(tmp_path)
    job.slurm_job_id = "42"
    job.remote_scratch_dir = "/scratch/x/" + job.job_id
    # NODE_FAIL is a genuine error (not a walltime TIMEOUT) → no auto-resubmit.
    conn = FakeConn(
        canned={
            "squeue": RunResult(0, "", ""),
            "sacct": RunResult(0, "42|NODE_FAIL", ""),
            "find": RunResult(0, "", ""),
        }
    )
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
    conn = FakeConn(
        canned={
            "squeue": RunResult(0, "", ""),
            "sacct": RunResult(0, "42|FAILED", ""),
            "find": RunResult(0, "", ""),
        }
    )
    out = _run(ex.reconcile_remote_job(job, tmp_path, conn=conn))
    assert out.status == MdStatus.failed
    assert "GPUresident not supported" in (out.error or "")
    assert "FAILED" in (out.error or "")  # keeps the SLURM state too
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
    assert finished == {"s_p10", "s_p10.restart"}  # .restart harmlessly present
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
    conn = FakeConn(
        canned={
            "squeue": RunResult(0, "42|RUNNING", ""),
            "ls -1 output": RunResult(
                0, "output/s_p10.coor\ns_p10.log\ns_p50.log\n", ""
            ),
        }
    )
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
    conn = FakeConn(
        canned={
            "squeue": RunResult(0, "", ""),
            "sacct": RunResult(0, "42|TIMEOUT", ""),
            "find": RunResult(0, "", ""),
        }
    )
    out = _run(ex.reconcile_remote_job(job, tmp_path, conn=conn))
    assert out.status == MdStatus.paused
    assert out.resumable is True
    assert out.failure_kind == "cluster_timeout"
    assert "Resume" in (out.error or "")
    assert out.resubmit_count == 0  # no automatic resubmit
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
    job.resources = cr.recommend(
        alpine, n_atoms=100_000, total_ns=2.0, partition="acpu"
    )
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
        get_contents={
            "6hb_demo_01_p50.restart.xsc": "# NAMD\n144000 100.0 0 0 0 100.0 0 0 0 100.0 50 50 50\n"
        },
    )
    out = _run(ex.resume_job(job, tmp_path, profile=alpine, conn=conn))
    assert out.slurm_job_id == "88"
    assert out.status == MdStatus.queued
    assert out.resubmit_count == 1
    assert out.resumable is False
    # A resume conf was uploaded, continuing from step 144000 for the remainder, and
    # GPUresident stripped (CPU target).
    resume = next(
        v
        for k, v in conn.put_contents.items()
        if k.endswith("6hb_demo_01_p50.resume.conf")
    )
    assert "firsttimestep      144000" in resume
    assert "run                336000" in resume  # 480000 - 144000
    assert "GPUresident" not in resume
    # The uploaded sbatch runs the resume conf for the interrupted segment.
    sbatch = next(
        v for k, v in conn.put_contents.items() if k.endswith(ex._SBATCH_NAME)
    )
    assert "6hb_demo_01_p50.resume.conf" in sbatch


def test_resume_job_applies_resource_override(tmp_path, alpine):
    """Reviewed/edited resources (e.g. a longer walltime) are used for the resumed run."""
    job = _make_resumable_job(tmp_path, alpine)
    override = dict(job.resources)
    override["walltime"] = "02:00:00"
    conn = FakeConn(
        canned={
            "ls -1 output": RunResult(0, "", ""),
            "sbatch": RunResult(0, "Submitted batch job 55", ""),
        },
        get_contents={"restart.xsc": "not-an-xsc"},
    )
    out = _run(
        ex.resume_job(job, tmp_path, profile=alpine, resources=override, conn=conn)
    )
    assert out.resources["walltime"] == "02:00:00"
    assert out.queued_at is not None  # re-stamped on resume (fresh queue wait)
    sbatch = next(
        v for k, v in conn.put_contents.items() if k.endswith(ex._SBATCH_NAME)
    )
    assert "#SBATCH --time=02:00:00" in sbatch


def test_remote_recommendation_current_seeds_from_job_resources(tmp_path, monkeypatch):
    """Resume review (current=true) shows the job's CURRENT resources, not a fresh
    auto-recommend — so the user reviews the (short) walltime they actually ran."""
    from backend.api import routes_md

    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    job = _make_prepared_job(tmp_path)
    job.resources = {
        "partition": "acpu",
        "kind": "cpu",
        "gpus": 0,
        "cores": 8,
        "mem_gb": 12,
        "walltime": "00:10:00",
        "qos": "normal",
    }
    job.slurm_job_id = "42"  # already submitted (resumable)
    job.save(tmp_path)
    out = routes_md.md_job_remote_recommendation(job.job_id, current=True)
    assert out["prepared"] is True
    assert (
        out["resources"]["walltime"] == "00:10:00"
    )  # current, not a fresh long auto-size
    assert out["resources"]["partition"] == "acpu"
    # acpu -> cpu-* QoS tiers offered (keyed off the seeded partition).
    assert {q["name"] for q in out["available_qos"]} == {"cpu-normal", "cpu-long"}


def test_resume_job_no_checkpoint_reruns_fresh(tmp_path, alpine):
    """Timed out before the first restart write → no usable checkpoint → the segment
    just re-runs fresh (idempotent sbatch), no resume conf uploaded."""
    job = _make_resumable_job(tmp_path, alpine)
    conn = FakeConn(
        canned={
            "ls -1 output": RunResult(0, "", ""),  # nothing finished/started
            "sbatch": RunResult(0, "Submitted batch job 99", ""),
        },
        get_contents={"6hb_demo_01_p50.restart.xsc": "not-an-xsc"},  # no step
    )
    out = _run(ex.resume_job(job, tmp_path, profile=alpine, conn=conn))
    assert out.slurm_job_id == "99"
    assert not any(k.endswith(".resume.conf") for k in conn.put_contents)


def test_reconcile_completed_records_learned_throughput(tmp_path):
    from backend.core import cluster_throughput

    job = _make_prepared_job(tmp_path)
    job.slurm_job_id = "42"
    job.cluster_name = "alpine"
    job.resources = {"partition": "acpu"}
    job.remote_scratch_dir = "/scratch/x/" + job.job_id
    job.remote_project_dir = "/projects/x/" + job.job_id
    out_dir = job.package_dir(tmp_path) / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.jsonl").write_text(
        '{"segment": "6hb_demo_01_p100", "ns_per_day": 12.5}\n'
    )
    # A completed run has its checkpoint restart set present (else it stays re-pollable).
    for ext in ("coor", "vel", "xsc"):
        (out_dir / f"6hb_demo_01_p100.{ext}").write_text("restart")
    conn = FakeConn(
        canned={
            "squeue": RunResult(0, "", ""),
            "sacct": RunResult(0, "42|COMPLETED", ""),
            "find": RunResult(0, "", ""),
        }
    )
    _run(ex.reconcile_remote_job(job, tmp_path, conn=conn))
    learned = cluster_throughput.lookup_throughput(
        tmp_path, cluster="alpine", partition="acpu", n_atoms=100_000
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


def test_poll_remote_jobs_drains_pending_scancel(tmp_path):
    """A Stop issued while disconnected sets pending_scancel; the next CONNECTED poll
    scancels the SLURM job and clears the flag — even though the job is already stopped
    (not "active"), so it doesn't keep running on the cluster."""
    job = _make_prepared_job(tmp_path)
    job.slurm_job_id = "77"
    job.status = MdStatus.stopped
    job.pending_scancel = True
    job.save(tmp_path)
    conn = FakeConn()
    touched = _run(ex.poll_remote_jobs(tmp_path, conn=conn))
    assert job.job_id in touched
    assert any("scancel 77" in c for c in conn.runs)
    assert MdJob.load(job.job_id, tmp_path).pending_scancel is False


def test_cluster_connect_kicks_remote_poll(tmp_path, monkeypatch):
    """A successful connect immediately reconciles remote jobs — so a run that FINISHED
    while the session was down gets its results fetched now (not only on the ~30 s
    supervisor pass) and any deferred scancel is drained."""
    import types
    from backend.api import routes_cluster
    from backend.core import cluster_ssh, cluster_config

    monkeypatch.setattr(routes_cluster, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(
        cluster_config,
        "load_profiles",
        lambda ws: {"alpine": types.SimpleNamespace(host="login.example")},
    )

    class _Mgr:
        async def connect(self, *a, **k):
            return None

        def is_connected(self):
            return True

        def status(self):
            return {"state": "connected"}

    monkeypatch.setattr(cluster_ssh, "get_manager", lambda: _Mgr())

    called = {}

    async def _spy(ws, conn=None):
        called["ws"] = ws
        return []

    monkeypatch.setattr(ex, "poll_remote_jobs", _spy)

    req = routes_cluster.ConnectRequest(cluster_name="alpine", user="u", password="p")
    out = _run(routes_cluster.cluster_connect(req))
    assert out == {"state": "connected"}
    assert called.get("ws") == tmp_path  # the post-connect poll ran


def test_stop_disconnected_defers_scancel(tmp_path, monkeypatch):
    """POST /stop on a remote job while the session is DOWN marks it stopped locally AND
    sets pending_scancel (so the SLURM job is cancelled on reconnect, not orphaned)."""
    from backend.api import routes_md
    from backend.core import cluster_ssh

    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    job = _make_prepared_job(tmp_path)
    job.slurm_job_id = "88"
    job.status = MdStatus.running
    job.save(tmp_path)

    class _DisconnectedMgr:
        def is_connected(self):
            return False

    monkeypatch.setattr(cluster_ssh, "get_manager", lambda: _DisconnectedMgr())

    out = _run(routes_md.stop_md_job(job.job_id))
    assert out["pending_scancel"] is True
    reloaded = MdJob.load(job.job_id, tmp_path)
    assert reloaded.pending_scancel is True
    assert reloaded.user_stopped is True


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


def test_remote_recommendation_lists_partitions_and_honours_forced_partition(
    tmp_path, monkeypatch
):
    """The dropdown needs the partition list, and forcing acpu re-sizes to CPU."""
    from backend.api import routes_md

    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    job = _make_prepared_job(tmp_path)

    out = routes_md.md_job_remote_recommendation(job.job_id)
    names = {p["name"] for p in out["available_partitions"]}
    assert {"aa100", "acpu"} <= names

    # GPU auto-pick → gpu-* QoS tiers offered.  The default ah200 has no gpu-testing
    # (that is aa100/ami100 only), so the dropdown must not offer it.
    assert {q["name"] for q in out["available_qos"]} == {"gpu-normal", "gpu-long"}

    forced = routes_md.md_job_remote_recommendation(job.job_id, partition="acpu")
    assert forced["resources"]["partition"] == "acpu"
    assert forced["resources"]["kind"] == "cpu"
    assert forced["resources"]["gpus"] == 0
    # acpu accepts ONLY cpu-normal/cpu-long (live-confirmed 2026-08-06) — the dropdown
    # must not offer testing/mem/compile, which SLURM rejects on acpu.
    assert {q["name"] for q in forced["available_qos"]} == {"cpu-normal", "cpu-long"}


def test_remote_recommendation_prefills_the_wizard_request(tmp_path, monkeypatch):
    """The wizard's first step now collects the resources, so the review card must open
    on THOSE numbers — and only those: an untouched field still comes from the
    recommendation sized against the package's exact atom count, not from the wizard's
    pre-solvation estimate."""
    from backend.api import routes_md

    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    job = _make_prepared_job(tmp_path)
    auto = routes_md.md_job_remote_recommendation(job.job_id)["resources"]

    job.requested_resources = {"walltime": "48:00:00", "cores": 16}
    job.save(tmp_path)
    out = routes_md.md_job_remote_recommendation(job.job_id)["resources"]
    assert out["walltime"] == "48:00:00"
    assert out["cores"] == 16
    # Everything else still tracks the recommendation.
    assert out["mem_gb"] == auto["mem_gb"]
    assert out["partition"] == auto["partition"]
    assert out["qos"] == auto["qos"]


def test_remote_submit_uses_the_wizard_request(tmp_path, monkeypatch):
    """Same merge on the submit path: what step 1 asked for is what gets requested."""
    from backend.api import routes_md

    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    from backend.core import cluster_config

    job = _make_prepared_job(tmp_path)
    job.requested_resources = {"walltime": "48:00:00"}
    job.save(tmp_path)
    profile = cluster_config.load_profiles(tmp_path)["alpine"]

    body = routes_md.SubmitRemoteRequest()
    assert routes_md._remote_resources(job, profile, body)["walltime"] == "48:00:00"

    # An explicit override from the review card still wins over the stored request.
    body = routes_md.SubmitRemoteRequest(resources={"walltime": "02:00:00", "cores": 4})
    assert routes_md._remote_resources(job, profile, body)["walltime"] == "02:00:00"


def test_wizard_request_ignores_blank_fields(tmp_path, monkeypatch):
    """A blanked control means "keep auto", not "request an empty wall time"."""
    from backend.api import routes_md

    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    job = _make_prepared_job(tmp_path)
    auto = routes_md.md_job_remote_recommendation(job.job_id)["resources"]
    job.requested_resources = {"walltime": "", "cores": None}
    job.save(tmp_path)
    out = routes_md.md_job_remote_recommendation(job.job_id)["resources"]
    assert out["walltime"] == auto["walltime"]
    assert out["cores"] == auto["cores"]


def test_remote_recommendation_unknown_partition_400(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from backend.api import routes_md

    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    job = _make_prepared_job(tmp_path)
    with pytest.raises(HTTPException) as exc:
        routes_md.md_job_remote_recommendation(job.job_id, partition="nope")
    assert exc.value.status_code == 400


# ── Failed remote submit records the error on the job (UI cleanup) ─────────────


def test_record_submit_failure_marks_job_without_losing_prepared_state(
    tmp_path, monkeypatch
):
    """A rejected submit must leave a visible error but keep the job queued (prepared,
    retryable) — so it stops looking like a clean/running job in the UI."""
    from backend.api import routes_md

    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    job = _make_prepared_job(tmp_path)
    job.status = MdStatus.queued
    job.save(tmp_path)

    routes_md._record_submit_failure(job, "sbatch failed (rc=1): bad QoS")

    reloaded = MdJob.load(job.job_id, tmp_path)
    assert reloaded.status == MdStatus.queued  # still prepared / retryable
    assert reloaded.slurm_job_id is None
    assert "Cluster submission failed" in (reloaded.error or "")
    assert "bad QoS" in reloaded.error


# ── module pre-flight (SLURM 30948986 post-mortem) ───────────────────────────


def test_submit_preflights_modules_before_uploading_anything(
    tmp_path, alpine, resources
):
    """SLURM 30948986 died instantly on `namd/3.0.1_gpu` (which does not exist on
    Alpine) AFTER an 814 MB upload and a queue wait. Catch it on the login node."""
    job = _make_prepared_job(tmp_path)
    conn = FakeConn(
        canned={
            "module spider": RunResult(
                1,
                "",
                "Lmod has detected the following error: The following module(s) "
                'are unknown: "namd/3.0.1_gpu"',
            ),
        }
    )
    with pytest.raises(RuntimeError, match="Pre-flight failed"):
        _run(
            ex.submit_job(job, tmp_path, profile=alpine, resources=resources, conn=conn)
        )
    # Nothing was staged — that is the whole point of checking first.
    assert conn.puts == []
    assert conn.mirrors == []
    assert not any("sbatch" in c for c in conn.runs)


def test_submit_preflight_reports_the_module_that_failed(tmp_path, alpine, resources):
    job = _make_prepared_job(tmp_path)
    conn = FakeConn(canned={"module spider": RunResult(1, "", "unknown module")})
    with pytest.raises(RuntimeError) as exc:
        _run(
            ex.submit_job(job, tmp_path, profile=alpine, resources=resources, conn=conn)
        )
    msg = str(exc.value)
    assert "clusters.json" in msg  # tells the user where to fix it
    assert "namd-modules" in msg  # ...and how to find the right name


def test_submit_proceeds_when_modules_load_cleanly(tmp_path, alpine, resources):
    job = _make_prepared_job(tmp_path)
    conn = FakeConn(canned={"sbatch": RunResult(0, "Submitted batch job 4242", "")})
    out = _run(
        ex.submit_job(job, tmp_path, profile=alpine, resources=resources, conn=conn)
    )
    assert out.slurm_job_id == "4242"
    assert any("module spider" in c for c in conn.runs)  # the pre-flight really ran


def test_submit_preflight_catches_a_missing_namd_binary(tmp_path, alpine, resources):
    """A private build is an absolute path, so `test -x` settles whether it is really
    there — the same filesystem answer from the login node or a compute node."""
    from dataclasses import replace as _replace

    prof = _replace(alpine, gpu_namd_bin="/projects/me/gone/namd3")
    job = _make_prepared_job(tmp_path)
    conn = FakeConn(canned={"test -x": RunResult(1, "", "NOT EXECUTABLE")})
    gpu_res = cr.recommend(prof, n_atoms=100_000, total_ns=2.0, partition="ah200")
    with pytest.raises(RuntimeError, match="Pre-flight failed"):
        _run(ex.submit_job(job, tmp_path, profile=prof, resources=gpu_res, conn=conn))
    assert conn.puts == []


def test_submit_preflight_checks_the_private_binary_path(tmp_path, alpine, resources):
    from dataclasses import replace as _replace

    prof = _replace(alpine, gpu_namd_bin="/projects/me/namd3")
    job = _make_prepared_job(tmp_path)
    conn = FakeConn(canned={"sbatch": RunResult(0, "Submitted batch job 77", "")})
    gpu_res = cr.recommend(prof, n_atoms=100_000, total_ns=2.0, partition="ah200")
    _run(ex.submit_job(job, tmp_path, profile=prof, resources=gpu_res, conn=conn))
    assert any("/projects/me/namd3" in c for c in conn.runs)


# ── live metrics retrieved from the node (SLURM 30954752 post-mortem) ─────────


def test_poll_retrieves_node_computed_metrics(tmp_path, alpine):
    """A remote run showed no speed/temp/pressure for its whole duration: the poll
    listed filenames only, and metrics.jsonl is written just once a segment
    completes — which never happens inside a short walltime."""
    job = _make_prepared_job(tmp_path)
    job.slurm_job_id = "1"
    job.remote_scratch_dir = "/scratch/x"
    blob = '{"ns_per_day": 30.8, "temperature_k": 296.7, "step": 200000}'
    conn = FakeConn(canned={"ls -1": RunResult(0, "---NADOC-METRICS---\n" + blob, "")})
    _run(ex.poll_remote_progress(job, conn=conn))
    assert job.live_metrics["ns_per_day"] == 30.8
    assert job.live_metrics["step"] == 200000


def test_live_metrics_ignores_a_missing_or_torn_blob(tmp_path):
    """The collector rewrites atomically, but an early poll sees no file at all —
    that must leave the previous reading alone rather than blanking the panel."""
    j = _make_prepared_job(tmp_path)
    j.live_metrics = {"ns_per_day": 12.0}
    assert ex.apply_live_metrics(j, "") is False
    assert ex.apply_live_metrics(j, "{not json") is False
    assert j.live_metrics == {"ns_per_day": 12.0}


def test_parse_remote_sizes_requires_two_real_byte_counts():
    assert ex.parse_remote_sizes("123\n456\n") == (123, 456)
    assert ex.parse_remote_sizes("") == (None, None)
    assert ex.parse_remote_sizes("123\nnot-a-size\n") == (None, None)


def test_live_metrics_no_change_reports_false(tmp_path):
    j = _make_prepared_job(tmp_path)
    assert ex.apply_live_metrics(j, '{"ns_per_day": 5}') is True
    assert ex.apply_live_metrics(j, '{"ns_per_day": 5}') is False


def test_live_metrics_derives_minimization_rate_from_successive_steps(tmp_path):
    j = _make_prepared_job(tmp_path)
    j.live_metrics = {
        "segment": "demo_00_min", "step": 100, "collected_at": 10.0,
        "retrieved_at": 11.0,
    }
    assert ex.apply_live_metrics(
        j, '{"segment":"demo_00_min","step":140,"collected_at":20.0}'
    ) is True
    assert j.live_metrics["s_per_step"] == 0.25


def test_fetch_outputs_serializes_duplicate_requests(tmp_path, monkeypatch):
    """Auto-fetch and a user click may race, but only one may touch a .part file."""
    job = _make_prepared_job(tmp_path)
    active = 0
    peak = 0

    async def fake_fetch(*args, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return True

    monkeypatch.setattr(ex, "_fetch_outputs_locked", fake_fetch)

    async def race():
        return await asyncio.gather(
            ex.fetch_outputs(job, tmp_path, conn=object()),
            ex.fetch_outputs(job, tmp_path, conn=object()),
        )

    assert asyncio.run(race()) == [True, True]
    assert peak == 1


def test_offline_download_verification_uses_exact_persisted_inventory(tmp_path):
    job = _make_prepared_job(tmp_path)
    pkg = job.package_dir(tmp_path)
    (pkg / "output").mkdir(exist_ok=True)
    (pkg / "output" / "run.dcd").write_bytes(b"dcd")
    (pkg / "run.log").write_bytes(b"log!")
    job.download_status = {
        "state": "interrupted", "total_bytes": 7, "verified_bytes": 0,
        "files_total": 2,
        "inventory": {"output/run.dcd": 3, "run.log": 4},
    }

    assert ex.verify_local_download(job, tmp_path) is True
    assert job.download_status["state"] == "verified"
    assert job.download_status["verified_bytes"] == 7
    assert job.download_status["dcd_bytes"] == 3
    assert job.download_status["verified_offline"] is True


def test_offline_download_verification_rejects_missing_or_wrong_sized_file(tmp_path):
    job = _make_prepared_job(tmp_path)
    pkg = job.package_dir(tmp_path)
    (pkg / "output").mkdir(exist_ok=True)
    (pkg / "output" / "run.dcd").write_bytes(b"short")
    job.download_status = {
        "state": "interrupted", "total_bytes": 10, "verified_bytes": 0,
        "files_total": 1, "inventory": {"output/run.dcd": 10},
    }

    assert ex.verify_local_download(job, tmp_path) is False
    assert job.download_status["state"] == "interrupted"
    assert "expected 10" in job.download_status["local_verification_error"]


def test_offline_download_verification_promotes_complete_partial(tmp_path):
    job = _make_prepared_job(tmp_path)
    pkg = job.package_dir(tmp_path)
    (pkg / "output").mkdir(exist_ok=True)
    part = pkg / "output" / "run.dcd.part"
    part.write_bytes(b"complete")
    job.download_status = {
        "state": "interrupted", "total_bytes": 8, "verified_bytes": 0,
        "files_total": 1, "inventory": {"output/run.dcd": 8},
    }

    assert ex.verify_local_download(job, tmp_path) is True
    assert (pkg / "output" / "run.dcd").read_bytes() == b"complete"
    assert not part.exists()


def test_offline_verifier_never_touches_active_download_partial(tmp_path):
    job = _make_prepared_job(tmp_path)
    pkg = job.package_dir(tmp_path)
    (pkg / "output").mkdir(exist_ok=True)
    part = pkg / "output" / "run.dcd.part"
    part.write_bytes(b"complete")
    job.download_status = {
        "state": "downloading", "total_bytes": 8, "verified_bytes": 0,
        "files_total": 1, "inventory": {"output/run.dcd": 8},
    }

    assert ex.verify_local_download(job, tmp_path) is False
    assert part.read_bytes() == b"complete"
    assert not (pkg / "output" / "run.dcd").exists()


def test_offline_download_verification_supports_legacy_count_and_total(tmp_path):
    job = _make_prepared_job(tmp_path)
    pkg = job.package_dir(tmp_path)
    (pkg / "output").mkdir(exist_ok=True)
    (pkg / "output" / "run.dcd").write_bytes(b"12345")
    (pkg / "run.log").write_bytes(b"678")
    job.download_status = {
        "state": "interrupted", "total_bytes": 8, "verified_bytes": 0,
        "files_total": 2,
    }

    assert ex.verify_local_download(job, tmp_path) is True
    assert job.download_status["state"] == "verified"


def test_submit_stages_the_live_metrics_collector(tmp_path, alpine, resources):
    """Staged unconditionally — it is not tied to the early-stop feature."""
    job = _make_prepared_job(tmp_path)
    conn = FakeConn(canned={"sbatch": RunResult(0, "Submitted batch job 5", "")})
    _run(ex.submit_job(job, tmp_path, profile=alpine, resources=resources, conn=conn))
    remotes = [remote for _, remote in conn.puts]
    assert any(r.endswith("/nadoc_live_metrics.py") for r in remotes), remotes


# ── health for INTERRUPTED segments (health card empty, 2026-08-07) ───────────


def test_partial_segment_with_a_trajectory_is_processed(tmp_path):
    """`_segment_outputs_complete` needs .coor+.vel+.xsc, which NAMD writes only when
    a segment FINISHES. Under short-walltime + resume nothing finishes, so the health
    card stayed empty forever. A partial DCD is enough to compute health."""
    out = tmp_path / "output"
    out.mkdir()
    (out / "seg1.dcd").write_bytes(b"x" * 8192)
    assert ex._segment_has_trajectory(out, "seg1") is True


def test_a_header_only_dcd_does_not_count():
    """A freshly-created DCD has a header and no frames — nothing to measure."""
    import tempfile
    from pathlib import Path as _P

    with tempfile.TemporaryDirectory() as td:
        out = _P(td)
        (out / "tiny.dcd").write_bytes(b"x" * 100)
        assert ex._segment_has_trajectory(out, "tiny") is False
        assert ex._segment_has_trajectory(out, "absent") is False
