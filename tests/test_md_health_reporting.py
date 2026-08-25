"""Why a NAMD Health tile is blank — the reporting path, not the physics.

These pin the audit of the Health card (2026-07-31).  The card showed Temp / Pressure /
Speed while Base pairs / WC health / Broken bp / Shell charge spun forever, because:

  * an ADOPTED NAMD run (one that outlived a dev-server ``--reload``) was waited on by a
    bare poll loop that ran neither the health probe nor the disk guard;
  * three of the four ``MdHealthSample`` construction sites silently dropped
    ``broken_bp_count`` / ``charge_within_shell_e`` after computing them;
  * a bare ``except Exception: pass`` erased the reason the per-frame diagnostics
    produced nothing, so "never measured" was indistinguishable from "failed";
  * an all-null JSONL record permanently blocked recomputation of a segment.

Everything here is fast: no MDAnalysis, no NAMD.  The probe/guard tests drive the real
async code with fakes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.core import namd_runner
from backend.core.disk_guard import DISK_ABORT_RC
from backend.core.md_health import HealthCheckResult, _latest_segment_dcd
from backend.core.md_job import MdHealthSample, new_job


def _result(**over) -> HealthCheckResult:
    """A passing check that measured everything, unless overridden."""
    base = dict(
        passed=True,
        blocking=False,
        reason="",
        c1_paired_fraction=0.95,
        c1_mean_ang=9.1,
        c1_p90_ang=10.0,
        wc_ref_relative_fraction=0.88,
        wc_mean_hbond_ang=3.0,
        broken_bp_count=7,
        charge_within_shell_e=-12.5,
        per_frame_ran=True,
    )
    base.update(over)
    return HealthCheckResult(**base)


# ── The field-drop bug: one constructor, used everywhere ──────────────────────


class TestSampleConstruction:
    def test_from_result_carries_the_per_frame_diagnostics(self) -> None:
        s = MdHealthSample.from_result(
            _result(), "310K NPT production", "seg1", blocking=False
        )
        assert s.broken_bp_count == 7
        assert s.charge_within_shell_e == pytest.approx(-12.5)
        assert s.diagnostics == "ok"  # provenance: the loop actually ran

    def test_blocking_is_explicit_not_copied(self) -> None:
        """An in-flight probe is advisory by construction.

        ``HealthCheckResult`` defaults ``blocking`` True on its error early-returns, so a
        constructor that copied it would flip persisted data for every advisory sample.
        """
        hard = _result(passed=False, blocking=True, reason="C1' paired 80.0% < 90.0%")
        assert (
            MdHealthSample.from_result(hard, "s", "g", blocking=False).blocking is False
        )
        assert (
            MdHealthSample.from_result(hard, "s", "g", blocking=True).blocking is True
        )

    def test_diagnostics_records_a_failure_verbatim(self) -> None:
        s = MdHealthSample.from_result(
            _result(
                broken_bp_count=None,
                charge_within_shell_e=None,
                per_frame_ran=False,
                diagnostics_error="frame 812: truncated DCD",
            ),
            "s",
            "g",
            blocking=False,
        )
        assert s.diagnostics == "frame 812: truncated DCD"

    def test_a_probe_that_skipped_the_loop_leaves_diagnostics_unset(self) -> None:
        """``per_frame=False`` measured nothing, so the UI must say "not recorded",
        not "measured as none" and certainly not spin."""
        s = MdHealthSample.from_result(
            _result(
                broken_bp_count=None, charge_within_shell_e=None, per_frame_ran=False
            ),
            "s",
            "g",
            blocking=False,
        )
        assert s.diagnostics is None

    def test_error_result_still_reports_a_reason(self) -> None:
        s = MdHealthSample.from_result(
            HealthCheckResult(passed=False, error="DCD not found or empty: x.dcd"),
            "s",
            "g",
            blocking=False,
        )
        assert "DCD not found" in s.reason

    def test_roundtrips_through_disk(self, tmp_path: Path) -> None:
        from backend.core.md_job import MdJob

        job = new_job("Z", "mgh_slow_release", "Z", "pkg")
        job.health_samples.append(
            MdHealthSample.from_result(
                _result(), "310K NPT production", "seg1", blocking=False
            )
        )
        job.health_probe = {
            "enabled": True,
            "interval_s": 300.0,
            "last_at": 1.0,
            "last_error": None,
            "reason": None,
        }
        job.save(tmp_path)
        loaded = MdJob.load(job.job_id, tmp_path)
        s = loaded.health_samples[0]
        assert (s.broken_bp_count, s.diagnostics) == (7, "ok")
        assert loaded.health_probe["interval_s"] == 300.0

    def test_an_old_sample_without_diagnostics_still_loads(
        self, tmp_path: Path
    ) -> None:
        """Samples on disk predate the field; they must reload as diagnostics=None —
        that is exactly the signal the card uses to render "—" instead of a spinner."""
        from backend.core.md_job import MdJob

        job = new_job("Z", "mgh_slow_release", "Z", "pkg")
        job.save(tmp_path)
        raw = json.loads((tmp_path / "md_jobs" / job.job_id / "job.json").read_text())
        raw["health_samples"] = [
            {
                "wall_time": 1.0,
                "stage": "s",
                "segment": "g",
                "c1_paired_fraction": 0.9,
                "passed": True,
            }
        ]
        (tmp_path / "md_jobs" / job.job_id / "job.json").write_text(json.dumps(raw))
        s = MdJob.load(job.job_id, tmp_path).health_samples[0]
        assert s.diagnostics is None
        assert s.broken_bp_count is None


# ── The idempotence guard that pinned a segment to nothing ────────────────────


class TestJsonlHasSegment:
    def _write(self, path: Path, records: list[dict]) -> None:
        path.write_text("".join(json.dumps(r) + "\n" for r in records))

    def test_matches_the_named_segment_only(self, tmp_path: Path) -> None:
        p = tmp_path / "metrics.jsonl"
        self._write(p, [{"segment": "prod_p10", "temperature_k": 300.0}])
        assert namd_runner._jsonl_has_segment(p, "prod_p10") is True
        assert namd_runner._jsonl_has_segment(p, "prod_p1") is False

    def test_an_all_null_record_does_not_count_as_recorded(
        self, tmp_path: Path
    ) -> None:
        """Written from a truncated log, this used to pin the segment to blank metrics
        forever — nothing recomputed it even after the log had grown."""
        p = tmp_path / "metrics.jsonl"
        self._write(
            p,
            [
                {
                    "segment": "seg1",
                    "temperature_k": None,
                    "pressure_bar": None,
                    "ns_per_day": None,
                    "volume_ang3": None,
                }
            ],
        )
        assert namd_runner._jsonl_has_segment(p, "seg1") is False

    def test_a_real_failure_does_count_so_it_is_not_retried_forever(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "health.jsonl"
        self._write(
            p,
            [
                {
                    "segment": "seg1",
                    "c1_paired_fraction": None,
                    "error": "PSF or PDB not found",
                }
            ],
        )
        assert namd_runner._jsonl_has_segment(p, "seg1") is True

    def test_a_torn_final_line_is_ignored(self, tmp_path: Path) -> None:
        p = tmp_path / "health.jsonl"
        p.write_text(
            json.dumps({"segment": "seg1", "c1_paired_fraction": 0.9})
            + "\n"
            + '{"segment": "seg2", "c1_pai'
        )
        assert namd_runner._jsonl_has_segment(p, "seg1") is True
        assert namd_runner._jsonl_has_segment(p, "seg2") is False

    def test_missing_file(self, tmp_path: Path) -> None:
        assert namd_runner._jsonl_has_segment(tmp_path / "nope.jsonl", "seg1") is False


# ── The trajectory a resumed segment actually writes to ───────────────────────


class TestLatestSegmentDcd:
    def test_plain_segment(self, tmp_path: Path) -> None:
        (tmp_path / "seg.dcd").write_bytes(b"x")
        assert _latest_segment_dcd(tmp_path, "seg").name == "seg.dcd"

    def test_prefers_the_newest_continuation(self, tmp_path: Path) -> None:
        """A resumed segment writes seg.cont1.dcd, cont2… — a probe hard-coded to
        seg.dcd kept sampling the frozen pre-crash trajectory for the rest of the run."""
        (tmp_path / "seg.dcd").write_bytes(b"x")
        for i, name in enumerate(("seg.cont1.dcd", "seg.cont2.dcd"), start=1):
            p = tmp_path / name
            p.write_bytes(b"x")
            import os

            os.utime(p, (1000 + i, 1000 + i))
        assert _latest_segment_dcd(tmp_path, "seg").name == "seg.cont2.dcd"

    def test_falls_back_when_nothing_exists(self, tmp_path: Path) -> None:
        assert _latest_segment_dcd(tmp_path, "seg").name == "seg.dcd"


# ── The probe's own bookkeeping ───────────────────────────────────────────────


def _job_for_probe(tmp_path: Path):
    job = new_job("D", "equilibrium_aware_namd", "D", "pkg")
    job.save(tmp_path)
    return job


class TestHealthProbeBookkeeping:
    def test_note_records_and_persists(self, tmp_path: Path) -> None:
        from backend.core.md_job import MdJob

        job = _job_for_probe(tmp_path)
        namd_runner._note_health_probe(job, tmp_path, enabled=True, interval_s=300.0)
        assert MdJob.load(job.job_id, tmp_path).health_probe["enabled"] is True

    def test_adopted_is_a_durable_fact_not_a_transient_reason(
        self, tmp_path: Path
    ) -> None:
        """It must survive the tick factory's counter reset, and must NOT sit in
        `reason` — an adopted run samples normally, so it is not why a metric is absent."""
        job = _job_for_probe(tmp_path)
        namd_runner._note_health_probe(job, tmp_path, adopted=True)
        assert job.health_probe["adopted"] is True
        assert job.health_probe["reason"] is None
        namd_runner._note_health_probe(job, tmp_path, reason=None, last_at=None)
        assert job.health_probe["adopted"] is True

    def test_never_raises(self, tmp_path: Path) -> None:
        """Bookkeeping about monitoring must not be able to break the run."""
        broken = SimpleNamespace(
            job_id="x",
            health_probe=None,
            save=lambda _d: (_ for _ in ()).throw(OSError("disk gone")),
        )
        namd_runner._note_health_probe(broken, tmp_path, enabled=True)  # must not raise


class TestInflightTick:
    """The probe that fills Base pairs / WC health / Broken bp / Shell charge."""

    def _spec(self):
        return SimpleNamespace(
            name="seg1",
            stage="310K NPT production",
            min_c1_paired=0.90,
            min_wc_ref_relative=0.85,
        )

    def _wire(self, tmp_path: Path, monkeypatch, result):
        # Fire on the first call instead of waiting out the real first-probe delay;
        # the delay itself is pinned separately below.
        monkeypatch.setattr(namd_runner, "_INFLIGHT_HEALTH_FIRST_S", 0.0)
        job = _job_for_probe(tmp_path)
        pkg = tmp_path / "pkg"
        out = pkg / "output"
        out.mkdir(parents=True)
        (out / "seg1.dcd").write_bytes(b"trajectory")
        calls = {}

        def _fake_check(*a, **kw):
            calls.update(kw)
            return result

        monkeypatch.setattr(namd_runner, "run_health_check", _fake_check)
        tick = namd_runner._make_inflight_health_tick(
            job, self._spec(), pkg, out, tmp_path
        )
        return job, tick, calls

    def test_appends_a_complete_sample(self, tmp_path: Path, monkeypatch) -> None:
        job, tick, calls = self._wire(tmp_path, monkeypatch, _result())
        asyncio.run(tick())
        assert len(job.health_samples) == 1
        s = job.health_samples[0]
        # The whole point: these two used to be dropped on this path.
        assert (s.broken_bp_count, s.charge_within_shell_e) == (7, pytest.approx(-12.5))
        assert s.blocking is False  # advisory by construction
        assert job.health_probe["last_at"] is not None

    def test_skips_the_per_frame_walk(self, tmp_path: Path, monkeypatch) -> None:
        """The series is discarded on this path and the probe runs inline in the disk
        guard's poll loop, so walking the whole trajectory is a blind spot, not a cost."""
        _job, tick, calls = self._wire(tmp_path, monkeypatch, _result())
        asyncio.run(tick())
        assert calls["per_frame"] is False
        assert calls["safe_back"] == namd_runner._INFLIGHT_HEALTH_SAFE_BACK

    def test_too_few_frames_is_not_reported_as_a_failure(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        job, tick, _ = self._wire(
            tmp_path,
            monkeypatch,
            HealthCheckResult(
                passed=False, not_ready=True, error="DCD has no frames yet"
            ),
        )
        asyncio.run(tick())
        assert job.health_samples == []
        assert job.health_probe["last_error"] is None  # normal, not an error
        assert "waiting" in job.health_probe["reason"]

    def test_a_real_error_is_published_not_swallowed(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        job, tick, _ = self._wire(
            tmp_path,
            monkeypatch,
            HealthCheckResult(passed=False, error="PSF or PDB not found in pkg"),
        )
        asyncio.run(tick())
        assert job.health_samples == []
        assert "PSF or PDB not found" in job.health_probe["last_error"]

    def test_first_probe_fires_early_then_settles_to_the_interval(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Waiting a whole interval left the card blank for five minutes at the start of
        every segment, even when everything was working.  After the first sample the
        probe must go back to the full interval rather than sampling continuously."""
        monkeypatch.setattr(namd_runner, "_INFLIGHT_HEALTH_INTERVAL_S", 300.0)
        job, tick, _ = self._wire(tmp_path, monkeypatch, _result())  # FIRST_S → 0
        asyncio.run(tick())
        assert len(job.health_samples) == 1  # fired promptly
        asyncio.run(tick())
        assert len(job.health_samples) == 1, "must wait a full interval after the first"

    def test_every_tick_stamps_last_tick_at_even_without_a_sample(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """ "The probe is alive" and "a sample arrived" are different facts, and the card
        needs both: a probe legitimately waiting for its first trajectory frames must not
        be mistaken for one that has died."""
        job, tick, _ = self._wire(
            tmp_path,
            monkeypatch,
            HealthCheckResult(
                passed=False, not_ready=True, error="DCD has no frames yet"
            ),
        )
        asyncio.run(tick())
        assert job.health_probe["last_tick_at"] is not None  # it ran
        assert job.health_probe["last_at"] is None  # but produced nothing

    def test_started_at_is_the_probe_clock_not_the_job_clock(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A RESUMED run is hours old while its probe is seconds old.  Anchoring
        staleness on the job's age made every resume paint failed tiles instantly."""
        monkeypatch.setattr(namd_runner, "_INFLIGHT_HEALTH_INTERVAL_S", 300.0)
        job = _job_for_probe(tmp_path)
        job.created_at = 1.0  # ancient, as a resumed job is
        out = tmp_path / "pkg" / "output"
        out.mkdir(parents=True)
        namd_runner._make_inflight_health_tick(
            job, self._spec(), tmp_path / "pkg", out, tmp_path
        )
        assert job.health_probe["started_at"] > job.created_at

    def test_a_new_segment_resets_the_counters(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Otherwise a stale last_at from the previous segment answers for this one."""
        monkeypatch.setattr(namd_runner, "_INFLIGHT_HEALTH_INTERVAL_S", 300.0)
        job = _job_for_probe(tmp_path)
        job.health_probe = {
            "enabled": True,
            "interval_s": 300.0,
            "started_at": 1.0,
            "last_tick_at": 2.0,
            "last_at": 3.0,
            "last_error": "an old failure",
            "reason": "an old reason",
        }
        out = tmp_path / "pkg" / "output"
        out.mkdir(parents=True)
        namd_runner._make_inflight_health_tick(
            job, self._spec(), tmp_path / "pkg", out, tmp_path
        )
        assert job.health_probe["last_at"] is None
        assert job.health_probe["last_tick_at"] is None
        assert job.health_probe["last_error"] is None
        assert job.health_probe["reason"] is None

    def test_the_probe_is_published_before_it_first_runs(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """So the card can tell "a sample is coming" from "nothing will ever sample
        this" during the window before the first tick."""
        monkeypatch.setattr(namd_runner, "_INFLIGHT_HEALTH_INTERVAL_S", 300.0)
        job = _job_for_probe(tmp_path)
        out = tmp_path / "pkg" / "output"
        out.mkdir(parents=True)
        namd_runner._make_inflight_health_tick(
            job, self._spec(), tmp_path / "pkg", out, tmp_path
        )
        assert job.health_probe["enabled"] is True
        assert job.health_probe["interval_s"] == 300.0
        assert job.health_probe["last_at"] is None

    def test_disabled_sampling_is_published_as_such(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(namd_runner, "_INFLIGHT_HEALTH_INTERVAL_S", 0.0)
        job = _job_for_probe(tmp_path)
        pkg = tmp_path / "pkg"
        out = pkg / "output"
        out.mkdir(parents=True)
        tick = namd_runner._make_inflight_health_tick(
            job, self._spec(), pkg, out, tmp_path
        )
        assert tick is None
        assert job.health_probe["enabled"] is False
        assert "disabled" in job.health_probe["reason"]


# ── An adopted orphan is a first-class run ────────────────────────────────────


class TestAdoptedRunIsGuarded:
    """A NAMD process that outlived its orchestrator used to be waited on by a bare
    ``asyncio.sleep`` loop: no disk guard, no health probe, no ``job.save``.  A routine
    backend edit (the dev server runs ``--reload``) silently downgraded the rest of the
    run — which is how the reported bug happened."""

    def test_ticks_while_the_adopted_process_lives(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        alive = [True, True, False]
        monkeypatch.setattr(
            namd_runner,
            "_segment_process_running",
            lambda _n: alive.pop(0) if alive else False,
        )
        ticks = []
        rc = asyncio.run(
            namd_runner._wait_for_segment_process(
                "seg1", poll=0.0, guard_dir=tmp_path, on_tick=lambda: ticks.append(1)
            )
        )
        assert rc == 0
        assert ticks, "an adopted segment must still be sampled"

    def test_disk_guard_aborts_an_adopted_run(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(namd_runner, "_segment_process_running", lambda _n: True)
        monkeypatch.setattr("backend.core.disk_guard.free_bytes", lambda _d: 0)
        killed = []
        monkeypatch.setattr(namd_runner, "_segment_pid", lambda _n: 4242)
        monkeypatch.setattr(
            namd_runner, "_kill_process_group", lambda pid: killed.append(pid)
        )
        rc = asyncio.run(
            namd_runner._wait_for_segment_process("seg1", poll=0.0, guard_dir=tmp_path)
        )
        assert rc == DISK_ABORT_RC
        assert killed == [4242], "filling the disk is worse than killing the orphan"

    def test_a_raising_probe_cannot_kill_the_run_it_watches(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        alive = [True, False]
        monkeypatch.setattr(
            namd_runner,
            "_segment_process_running",
            lambda _n: alive.pop(0) if alive else False,
        )

        def _boom():
            raise RuntimeError("probe exploded")

        rc = asyncio.run(
            namd_runner._wait_for_segment_process(
                "seg1", poll=0.0, guard_dir=tmp_path, on_tick=_boom
            )
        )
        assert rc == 0

    def test_without_a_guard_dir_it_is_the_old_plain_wait(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        alive = [True, False]
        monkeypatch.setattr(
            namd_runner,
            "_segment_process_running",
            lambda _n: alive.pop(0) if alive else False,
        )
        assert asyncio.run(namd_runner._wait_for_segment_process("seg1", poll=0.0)) == 0


# ── The per-frame diagnostics loop ────────────────────────────────────────────


class _FakeTraj:
    """A trajectory of ``n`` frames where indexing frame ``bad`` raises, as a torn
    mid-write DCD tail does while NAMD is still appending to it."""

    def __init__(self, n: int, bad: int | None = None) -> None:
        self.n, self.bad, self.visited = n, bad, []

    def __len__(self) -> int:
        return self.n

    def __getitem__(self, i: int):
        if i == self.bad:
            raise OSError(f"truncated frame {i}")
        self.visited.append(i)
        return SimpleNamespace(dimensions=None)


class _FakeUniverse:
    def __init__(self, n: int, bad: int | None = None) -> None:
        self.trajectory = _FakeTraj(n, bad)
        self.atoms = SimpleNamespace(positions=None, charges=[1.0])


@pytest.fixture
def stub_health(monkeypatch, tmp_path):
    """Drive run_health_check's per-frame loop without MDAnalysis or a real trajectory."""
    import sys

    from backend.core import md_health as H

    pkg = tmp_path / "pkg"
    (pkg / "output").mkdir(parents=True)
    for name in ("D.psf", "D.pdb"):
        (pkg / name).write_text("x")
    (pkg / "output" / "seg1.dcd").write_bytes(b"x")

    def _install(n_frames: int, bad: int | None = None):
        uni = _FakeUniverse(n_frames, bad)
        monkeypatch.setitem(
            sys.modules, "MDAnalysis", SimpleNamespace(Universe=lambda *a, **k: uni)
        )
        monkeypatch.setattr(H, "_unpaired_exclusion_set", lambda *a, **k: set())
        monkeypatch.setattr(H, "build_c1_pairs", lambda *a, **k: [(0, 1)])
        monkeypatch.setattr(H, "build_wc_pairs", lambda *a, **k: [(0, 1)])
        monkeypatch.setattr(
            H,
            "c1_metrics_from_dcd",
            lambda *a, **k: {
                "paired_fraction": 0.95,
                "mean_c1_ang": 9.0,
                "p90_c1_ang": 10.0,
                "max_c1_ang": 11.0,
                "n_pairs": 1,
                "frame": n_frames - 1,
            },
        )
        monkeypatch.setattr(
            H,
            "wc_window_metrics_from_dcd",
            lambda *a, **k: {
                "absolute_paired_fraction": 0.9,
                "ref_relative_paired_fraction": 0.9,
                "mean_hbond_proxy_ang": 3.0,
                "p90_max_hbond_proxy_ang": 3.5,
                "n_pairs": 1,
                "window_frames": min(10, max(1, n_frames - int(k.get("safe_back", 0)))),
            },
        )
        monkeypatch.setattr(
            H, "_shell_selections", lambda _u: (_np_arange(1), _np_arange(1))
        )
        monkeypatch.setattr(
            H, "wc_hbond_atoms", lambda _u: (_np_arange(1), _np_arange(1))
        )
        monkeypatch.setattr(H, "count_intact_base_pairs", lambda *a, **k: 10)
        monkeypatch.setattr(H, "count_broken_base_pairs", lambda *a, **k: 2)
        monkeypatch.setattr(H, "charge_within_shell", lambda *a, **k: (-5.0, 3))
        monkeypatch.setattr(
            H, "wc_frame_metrics", lambda *a, **k: {"ref_relative_paired_fraction": 0.9}
        )
        return uni

    return pkg, _install


def _np_arange(n):
    import numpy as np

    return np.arange(n)


class TestPerFrameDiagnostics:
    def test_default_walks_every_frame(self, stub_health) -> None:
        from backend.core.md_health import run_health_check

        pkg, install = stub_health
        uni = install(6)
        r = run_health_check(pkg, "seg1", "D")
        assert len(r.wc_per_frame) == 6
        assert r.per_frame_ran is True
        assert r.diagnostics_error is None
        # Frame 0 is a real trajectory frame. It used to be the reference PDB, because
        # the Universe was built as a ChainReader over (pdb, dcd) — which shifted
        # wc_per_frame (read by the early-stop accelerator) by one.
        assert uni.trajectory.visited[0] == 0

    def test_safe_back_excludes_the_mid_write_tail(self, stub_health) -> None:
        from backend.core.md_health import run_health_check

        pkg, install = stub_health
        uni = install(6)
        run_health_check(pkg, "seg1", "D", safe_back=2)
        assert uni.trajectory.visited == [0, 1, 2, 3]  # last two skipped

    def test_per_frame_false_reads_a_single_frame(self, stub_health) -> None:
        """The in-flight probe runs inline in the disk guard's poll loop, so an
        O(n_frames) walk there is a blind spot in disk-abort detection, not just cost."""
        from backend.core.md_health import run_health_check

        pkg, install = stub_health
        uni = install(5000)
        r = run_health_check(pkg, "seg1", "D", safe_back=2, per_frame=False)
        assert len(uni.trajectory.visited) == 1
        assert uni.trajectory.visited == [4997]  # the newest SAFE frame
        assert r.broken_bp_count == 2  # still reported
        assert r.charge_within_shell_e == pytest.approx(-5.0)

    def test_a_torn_frame_drops_one_frame_not_the_whole_series(
        self, stub_health
    ) -> None:
        """A bare `except Exception: pass` around the whole loop used to wipe all three
        series — and with them the two Health tiles — leaving no trace of why."""
        from backend.core.md_health import run_health_check

        pkg, install = stub_health
        install(6, bad=3)
        r = run_health_check(pkg, "seg1", "D")
        assert len(r.wc_per_frame) == 5  # 6 frames, 1 torn
        assert r.broken_bp_count == 2  # survived
        assert "truncated frame 3" in r.diagnostics_error  # and it is on the record
        assert r.passed is True, "diagnostics must never change the verdict"

    def test_the_verdict_is_unaffected_by_a_diagnostics_failure(
        self, stub_health
    ) -> None:
        from backend.core.md_health import run_health_check

        pkg, install = stub_health
        install(4, bad=0)
        r = run_health_check(pkg, "seg1", "D")
        assert r.c1_paired_fraction == pytest.approx(0.95)
        assert r.reason == ""  # not polluted by diagnostics


class TestTierAContract:
    def test_per_frame_defaults_to_true(self) -> None:
        """remote_health_eval runs a staged copy of md_health on the Alpine compute node
        and exits "no WC" on an empty wc_per_frame. Flipping this default would make
        every Tier-A stage HOLD instead of early-stopping."""
        import inspect

        from backend.core.md_health import run_health_check

        assert (
            inspect.signature(run_health_check).parameters["per_frame"].default is True
        )


class TestEarlyStopShortSeries:
    def test_wc_plateaued_tolerates_a_short_chunk(self) -> None:
        """Dropping the leading reference frame shortens wc_per_frame by one, which only
        matters for a chunk with barely enough frames to judge — a 10 % chunk can be
        that short. Pin the boundary so the accelerator's behaviour is explicit."""
        from backend.core.md_cutoff import wc_plateaued

        assert wc_plateaued([]) is False
        flat = [0.90] * 12
        assert wc_plateaued(flat) is True
        assert wc_plateaued(flat[1:]) is True, (
            "one fewer leading frame must not flip it"
        )
        rising = [0.50, 0.60, 0.70, 0.80, 0.90, 0.95]
        assert wc_plateaued(rising) is False
