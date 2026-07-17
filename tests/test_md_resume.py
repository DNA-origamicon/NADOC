"""Tests for mid-segment / interrupted-job resume in the NAMD runner.

Covers the pure-ish helpers (checkpoint-step parsing, resume-conf rewriting,
resume-step decision) plus the reconcile + supervisor selection logic.  None of
these require NAMD, GROMACS, or MDAnalysis — the heavy health-check path is only
reached for *completed* segments, which these tests deliberately avoid.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core import namd_runner as nr
from backend.core.md_job import MdJob, MdSegmentStatus, MdStatus


_XSC = (
    "# NAMD extended system configuration restart file\n"
    "#$LABELS step a_x a_y a_z b_x b_y b_z c_x c_y c_z o_x o_y o_z s_x s_y s_z s_u s_v s_w\n"
    "{step} 138.9 0 0 0 153.5 0 0 0 222.4 70.7 78.2 113.3 0 0 0 0 0 0\n"
)

_BASE_CONF = """\
structure          stem.psf
coordinates        stem.pdb
outputName         output/SEG
dcdFile            output/SEG.dcd
dcdFreq            9600
xstFile            output/SEG.xst
langevinTemp       300
binCoordinates     output/PREV.coor
binVelocities      output/PREV.vel
extendedSystem     output/PREV.xsc
run                960000
"""


# ── _read_xsc_step ──────────────────────────────────────────────────────────────


class TestReadXscStep:
    def test_parses_step(self, tmp_path: Path) -> None:
        p = tmp_path / "s.restart.xsc"
        p.write_text(_XSC.format(step=595200))
        assert nr._read_xsc_step(p) == 595200

    def test_missing_file(self, tmp_path: Path) -> None:
        assert nr._read_xsc_step(tmp_path / "nope.xsc") is None

    def test_only_comments(self, tmp_path: Path) -> None:
        p = tmp_path / "s.xsc"
        p.write_text("# header only\n#$LABELS step\n")
        assert nr._read_xsc_step(p) is None


# ── _resume_step ────────────────────────────────────────────────────────────────


class TestResumeStep:
    def _restart(self, out: Path, step: int) -> None:
        (out / "SEG.restart.xsc").write_text(_XSC.format(step=step))

    def test_fresh_when_no_restart(self, tmp_path: Path) -> None:
        assert nr._resume_step(tmp_path, "SEG", 960000) is None

    def test_resume_from_checkpoint(self, tmp_path: Path) -> None:
        self._restart(tmp_path, 595200)
        assert nr._resume_step(tmp_path, "SEG", 960000) == 595200

    def test_none_when_segment_finished(self, tmp_path: Path) -> None:
        self._restart(tmp_path, 960000)
        (tmp_path / "SEG.coor").write_text("done")  # final output exists
        assert nr._resume_step(tmp_path, "SEG", 960000) is None

    def test_zero_step_is_fresh(self, tmp_path: Path) -> None:
        self._restart(tmp_path, 0)
        assert nr._resume_step(tmp_path, "SEG", 960000) is None

    def test_clamped_to_total(self, tmp_path: Path) -> None:
        self._restart(tmp_path, 9_999_999)
        assert nr._resume_step(tmp_path, "SEG", 960000) == 960000


# ── _write_resume_conf ──────────────────────────────────────────────────────────


class TestWriteResumeConf:
    def _setup(self, tmp_path: Path) -> tuple[Path, Path]:
        pkg = tmp_path
        out = tmp_path / "output"
        out.mkdir()
        (pkg / "SEG.conf").write_text(_BASE_CONF)
        for ext in ("coor", "vel", "xsc"):
            (out / f"SEG.restart.{ext}").write_text(f"checkpoint-{ext}")
        return pkg, out

    def test_rewrites_directives(self, tmp_path: Path) -> None:
        pkg, out = self._setup(tmp_path)
        base = nr._write_resume_conf(pkg, out, "SEG", 595200, 960000)
        assert base == "SEG.resume1"
        text = (pkg / "SEG.resume1.conf").read_text()

        # remaining run is expressed as firsttimestep + run REMAINING steps.
        # NAMD 3.0.2's Tcl `run` rejects the `upto` keyword ("first arg not
        # norepeat"), so we must emit the remaining count, not the absolute total.
        assert "firsttimestep      595200" in text
        assert "run                364800" in text  # 960000 - 595200
        assert "run upto" not in text
        # the original 'run 960000' line is gone
        assert "\nrun                960000" not in text
        # inputs point at the copied checkpoint, output name is unchanged
        assert "binCoordinates     output/SEG.resume1.coor" in text
        assert "binVelocities      output/SEG.resume1.vel" in text
        assert "extendedSystem     output/SEG.resume1.xsc" in text
        assert "outputName         output/SEG" in text
        # continuation trajectory preserves the partial <seg>.dcd
        assert "dcdFile            output/SEG.cont1.dcd" in text
        # original prev-segment inputs were dropped
        assert "output/PREV.coor" not in text

    def test_copies_checkpoint_inputs(self, tmp_path: Path) -> None:
        pkg, out = self._setup(tmp_path)
        nr._write_resume_conf(pkg, out, "SEG", 595200, 960000)
        for ext in ("coor", "vel", "xsc"):
            assert (out / f"SEG.resume1.{ext}").read_text() == f"checkpoint-{ext}"

    def test_second_resume_increments(self, tmp_path: Path) -> None:
        pkg, out = self._setup(tmp_path)
        nr._write_resume_conf(pkg, out, "SEG", 595200, 960000)
        (out / "SEG.cont1.dcd").write_text("frames")  # first continuation exists
        base2 = nr._write_resume_conf(pkg, out, "SEG", 700000, 960000)
        assert base2 == "SEG.resume2"
        assert (
            "dcdFile            output/SEG.cont2.dcd"
            in (pkg / "SEG.resume2.conf").read_text()
        )


# ── reconcile_job_status ────────────────────────────────────────────────────────


def _make_job(tmp_path: Path, *, n_segments: int = 1, idx: int = 0) -> MdJob:
    job = MdJob(
        job_id="testjob0001",
        design_name="d",
        protocol="equilibrium_aware_namd",
        status=MdStatus.running,
        created_at=0.0,
        package_subdir="package/pkg",
        name_stem="stem",
        segments=[
            MdSegmentStatus(name=f"SEG{i}", stage="s", percent=100.0, steps=960000)
            for i in range(n_segments)
        ],
        current_segment_idx=idx,
    )
    (job.package_dir(tmp_path) / "output").mkdir(parents=True, exist_ok=True)
    return job


class TestReconcileMidSegment:
    def test_mid_segment_checkpoint_stays_running(self, tmp_path: Path) -> None:
        job = _make_job(tmp_path)
        out = job.package_dir(tmp_path) / "output"
        (out / "SEG0.restart.xsc").write_text(
            _XSC.format(step=480000)
        )  # no final .coor
        job.save(tmp_path)

        result = nr.reconcile_job_status(job, tmp_path)
        assert result.status == MdStatus.running
        assert result.segments[0].status == "running"
        assert "480000" in (result.error or "")

    def test_no_checkpoint_fails(self, tmp_path: Path) -> None:
        job = _make_job(tmp_path)  # no restart, no coor
        job.save(tmp_path)
        result = nr.reconcile_job_status(job, tmp_path)
        assert result.status == MdStatus.failed

    def test_not_running_is_untouched(self, tmp_path: Path) -> None:
        job = _make_job(tmp_path)
        job.status = MdStatus.stopped  # e.g. user-parked job
        job.save(tmp_path)
        result = nr.reconcile_job_status(job, tmp_path)
        assert result.status == MdStatus.stopped


class TestReconcileAbandonedRemoteQueued:
    """An ARCHIVED remote job stuck at ``queued`` with no remote handle, older than
    the launch-race window, is retired to ``stopped`` — it can never be started from
    the archive and otherwise renders as an active "queued" row forever."""

    def _remote_queued(self, tmp_path: Path, *, exec_target: str = "runpod") -> MdJob:
        job = _make_job(tmp_path)
        job.status = MdStatus.queued
        job.execution_target = exec_target
        job.archived = True
        job.created_at = 0.0  # epoch — far older than _ABANDONED_QUEUED_MIN_AGE_S
        job.save(tmp_path)
        return job

    def test_archived_runpod_queued_retired_to_stopped(self, tmp_path: Path) -> None:
        job = self._remote_queued(tmp_path, exec_target="runpod")
        result = nr.reconcile_job_status(job, tmp_path)
        assert result.status == MdStatus.stopped
        assert result.user_stopped is True
        assert result.error is None
        # persisted, so the panel/list reads the healed state next load
        assert MdJob.load(job.job_id, tmp_path).status == MdStatus.stopped

    def test_archived_alpine_queued_retired_to_stopped(self, tmp_path: Path) -> None:
        job = self._remote_queued(tmp_path, exec_target="alpine")
        result = nr.reconcile_job_status(job, tmp_path)
        assert result.status == MdStatus.stopped

    def test_non_archived_queued_is_protected(self, tmp_path: Path) -> None:
        # panel "prepared, awaiting Start/submit" — must persist, never reaped
        job = self._remote_queued(tmp_path)
        job.archived = False
        job.save(tmp_path)
        result = nr.reconcile_job_status(job, tmp_path)
        assert result.status == MdStatus.queued

    def test_recent_queued_not_reaped_launch_race(self, tmp_path: Path) -> None:
        # an in-flight CLI archive-from-birth launch is briefly archived+queued
        import time as _t

        job = self._remote_queued(tmp_path)
        job.created_at = _t.time()  # just now
        job.save(tmp_path)
        result = nr.reconcile_job_status(job, tmp_path)
        assert result.status == MdStatus.queued

    def test_queued_with_pod_id_not_reaped(self, tmp_path: Path) -> None:
        # a real pod exists (launched) — leave it to the pod-aware reaper
        job = self._remote_queued(tmp_path)
        job.runpod_pod_id = "zwyw0rp0c9amya"
        job.save(tmp_path)
        result = nr.reconcile_job_status(job, tmp_path)
        assert result.status == MdStatus.queued


# ── resume_interrupted_jobs (supervisor selection) ──────────────────────────────


class TestResumeInterruptedJobs:
    def test_resumes_only_eligible(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        launched: list[str] = []
        monkeypatch.setattr(
            nr, "start_job", lambda job, ws: launched.append(job.job_id)
        )

        # eligible: running, not user-stopped, mid-segment checkpoint present
        eligible = _make_job(tmp_path)
        eligible.job_id = "eligible0001"
        (eligible.package_dir(tmp_path) / "output").mkdir(parents=True, exist_ok=True)
        (eligible.package_dir(tmp_path) / "output" / "SEG0.restart.xsc").write_text(
            _XSC.format(step=120000)
        )
        eligible.save(tmp_path)

        # user-stopped running job → skipped
        stopped_by_user = _make_job(tmp_path)
        stopped_by_user.job_id = "userstop0001"
        stopped_by_user.user_stopped = True
        (stopped_by_user.package_dir(tmp_path) / "output").mkdir(
            parents=True, exist_ok=True
        )
        (
            stopped_by_user.package_dir(tmp_path) / "output" / "SEG0.restart.xsc"
        ).write_text(_XSC.format(step=120000))
        stopped_by_user.save(tmp_path)

        # completed job → skipped
        done = _make_job(tmp_path)
        done.job_id = "completed001"
        done.status = MdStatus.completed
        done.save(tmp_path)

        # parked/stopped job → skipped (not auto-resumed)
        parked = _make_job(tmp_path)
        parked.job_id = "parked000001"
        parked.status = MdStatus.stopped
        parked.save(tmp_path)

        resumed = nr.resume_interrupted_jobs(tmp_path)
        assert resumed == ["eligible0001"]
        assert launched == ["eligible0001"]
