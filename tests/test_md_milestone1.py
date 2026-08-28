"""Tests for Milestone 1 MD integration modules.

Tests are restricted to the pure-Python parts that don't need
MDAnalysis, GROMACS, or NAMD installed.  Anything that calls
build_namd_solvated_package() or run_health_check() is left for
integration tests that run against real trajectory data.
"""

from __future__ import annotations

import json
import sys
import time
import types
from pathlib import Path

import pytest

from backend.core import md_ensemble


# ── md_job ─────────────────────────────────────────────────────────────────────


class TestMdJob:
    def test_new_job_roundtrip(self, tmp_path: Path) -> None:
        from backend.core.md_job import MdJob, MdStatus, new_job

        job = new_job(
            design_name="B_tube",
            protocol="mgh_slow_release",
            name_stem="B_tube",
            package_subdir="package/B_tube_namd_solvated",
            threads=16,
            devices="0",
        )
        assert job.status == MdStatus.queued
        assert len(job.job_id) == 12

        job.save(tmp_path)
        loaded = MdJob.load(job.job_id, tmp_path)
        assert loaded.job_id == job.job_id
        assert loaded.design_name == "B_tube"
        assert loaded.protocol == "mgh_slow_release"
        assert loaded.name_stem == "B_tube"
        assert loaded.package_subdir == "package/B_tube_namd_solvated"
        assert loaded.threads == 16
        assert loaded.devices == "0"
        assert loaded.status == MdStatus.queued

    def test_parent_job_id_roundtrip(self, tmp_path: Path) -> None:
        """A derived (refit/retry) job records its origin so the list can nest it."""
        from backend.core.md_job import MdJob, new_job

        parent = new_job("A", "mgh_slow_release", "A", "pkg/A")
        child = new_job(
            "A", "mgh_slow_release", "A", "pkg/A", parent_job_id=parent.job_id
        )
        assert parent.parent_job_id is None
        assert child.parent_job_id == parent.job_id
        child.save(tmp_path)
        assert MdJob.load(child.job_id, tmp_path).parent_job_id == parent.job_id

    def test_list_jobs(self, tmp_path: Path) -> None:
        from backend.core.md_job import new_job, MdJob

        j1 = new_job("A", "mgh_slow_release", "A", "pkg/A_namd_solvated")
        j2 = new_job("B", "mgh_slow_release", "B", "pkg/B_namd_solvated")
        j1.save(tmp_path)
        j2.save(tmp_path)

        jobs = MdJob.list_jobs(tmp_path)
        assert {j.job_id for j in jobs} == {j1.job_id, j2.job_id}

    def test_list_empty_workspace(self, tmp_path: Path) -> None:
        from backend.core.md_job import MdJob

        assert MdJob.list_jobs(tmp_path) == []

    def test_status_roundtrip(self, tmp_path: Path) -> None:
        from backend.core.md_job import MdJob, MdStatus, new_job

        for status in MdStatus:
            job = new_job("D", "mgh_slow_release", "D", "pkg")
            job.status = status
            job.save(tmp_path)
            loaded = MdJob.load(job.job_id, tmp_path)
            assert loaded.status == status

    def test_to_dict_serializable(self, tmp_path: Path) -> None:
        from backend.core.md_job import new_job

        job = new_job("X", "mgh_slow_release", "X", "pkg")
        d = job.to_dict()
        assert json.dumps(d)  # must be JSON-serializable
        assert d["status"] == "queued"

    def test_health_sample_roundtrip(self, tmp_path: Path) -> None:
        from backend.core.md_job import MdJob, MdHealthSample, new_job

        job = new_job("Z", "mgh_slow_release", "Z", "pkg")
        job.health_samples.append(
            MdHealthSample(
                wall_time=time.time(),
                stage="50K NVT k=5.0",
                segment="Z_01_050K_NVT_k5_p10",
                c1_paired_fraction=0.998,
                c1_mean_ang=9.5,
                c1_p90_ang=10.2,
                wc_ref_relative_fraction=0.992,
                wc_mean_hbond_ang=3.1,
                passed=True,
            )
        )
        job.save(tmp_path)
        loaded = MdJob.load(job.job_id, tmp_path)
        s = loaded.health_samples[0]
        assert s.stage == "50K NVT k=5.0"
        assert s.c1_paired_fraction == pytest.approx(0.998)
        assert s.passed is True

    def test_path_helpers(self, tmp_path: Path) -> None:
        from backend.core.md_job import new_job

        job = new_job("P", "mgh_slow_release", "P", "package/P_namd_solvated")
        jd = job.job_dir(tmp_path)
        pd = job.package_dir(tmp_path)
        assert jd == tmp_path / "md_jobs" / job.job_id
        assert pd == jd / "package" / "P_namd_solvated"


# ── namd_metrics ──────────────────────────────────────────────────────────────

_SAMPLE_LOG = """\
ETITLE:       TS           BOND          ANGLE          DIHED         IMPRP          ELECT            VDW       BOUNDARY          MISC        KINETIC          TOTAL           TEMP      TEMPAVG      PRESSURE     GPRESSURE         VOLUME       PRESSAVG      GPRESSAVG
ENERGY:        100    1234.5678    234.5678    123.4567     12.3456 -123456.7890   1234.5678      0.0000      0.0000  12345.6789 -108209.0000    309.8765    310.0012      0.9532      0.9420  1234567.8900      1.0001      0.9980
ENERGY:        200    1200.0000    230.0000    121.0000     12.0000 -123400.0000   1230.0000      0.0000      0.0000  12380.0000 -108226.0000    310.1234    310.0987      1.0100      1.0050  1234500.0000      1.0050      1.0020
Info: Benchmark time: 16 CPUs 0.002345 s/step 0.027123 days/ns 1800.00 MB memory
"""


class TestNamdMetrics:
    def test_parse_basic_energy_fields(self, tmp_path: Path) -> None:
        from backend.core.namd_metrics import parse_namd_log

        log = tmp_path / "test.log"
        log.write_text(_SAMPLE_LOG)
        m = parse_namd_log(log)

        assert m.n_energy_lines == 2
        assert m.temperature_k == pytest.approx(310.1234, rel=1e-4)
        assert m.temperature_avg_k == pytest.approx(310.0987, rel=1e-4)
        assert m.pressure_bar == pytest.approx(1.0100, rel=1e-3)
        assert m.gpressure_bar == pytest.approx(1.0050, rel=1e-3)
        assert m.pressure_avg_bar == pytest.approx(1.0050, rel=1e-3)
        assert m.gpressure_avg_bar == pytest.approx(1.0020, rel=1e-3)
        assert m.volume_ang3 == pytest.approx(1234500.0, rel=1e-4)
        assert m.timestep == 200

    def test_parse_ns_per_day(self, tmp_path: Path) -> None:
        from backend.core.namd_metrics import parse_namd_log

        log = tmp_path / "test.log"
        log.write_text(_SAMPLE_LOG)
        m = parse_namd_log(log)

        expected = 1.0 / 0.027123
        assert m.ns_per_day == pytest.approx(expected, rel=1e-4)

    def test_parse_ns_per_day_namd3_format(self, tmp_path: Path) -> None:
        """NAMD 3 (esp. GPU-resident) prints '<ns> ns/day' instead of '<days> days/ns'.

        Take the LAST Benchmark line and ignore the earlier 'Initial time' lines.
        """
        from backend.core.namd_metrics import parse_namd_log

        log = tmp_path / "n3.log"
        log.write_text(
            "Info: Initial time: 16 CPUs 0.0101308 s/step 34.1137 ns/day 0 MB memory\n"
            "Info: Benchmark time: 16 CPUs 0.0117889 s/step 29.3158 ns/day 0 MB memory\n"
            "Info: Benchmark time: 16 CPUs 0.0102826 s/step 33.6101 ns/day 0 MB memory\n"
        )
        m = parse_namd_log(log)
        assert m.ns_per_day == pytest.approx(33.6101, rel=1e-4)  # last Benchmark line

    def test_missing_log_returns_warning(self, tmp_path: Path) -> None:
        from backend.core.namd_metrics import parse_namd_log

        m = parse_namd_log(tmp_path / "nonexistent.log")
        assert m.n_energy_lines == 0
        assert m.temperature_k is None
        assert len(m.warnings) > 0

    def test_empty_log(self, tmp_path: Path) -> None:
        from backend.core.namd_metrics import parse_namd_log

        log = tmp_path / "empty.log"
        log.write_text("")
        m = parse_namd_log(log)
        assert m.n_energy_lines == 0
        assert m.temperature_k is None

    def test_minimisation_lines_skipped_by_temp_check(self, tmp_path: Path) -> None:
        """Minimisation ENERGY lines have TEMP=0; they should still be parsed."""
        from backend.core.namd_metrics import parse_namd_log

        log_text = (
            "ETITLE:       TS           BOND          ANGLE          DIHED         IMPRP"
            "          ELECT            VDW       BOUNDARY          MISC        KINETIC"
            "          TOTAL           TEMP      TEMPAVG\n"
            "ENERGY:          0      0.0      0.0      0.0      0.0      0.0      0.0"
            "      0.0      0.0      0.0  -50000.0      0.0      0.0\n"
        )
        log = tmp_path / "min.log"
        log.write_text(log_text)
        m = parse_namd_log(log)
        assert m.n_energy_lines == 1
        assert m.temperature_k == pytest.approx(0.0)


class TestLastNamdTimestepFast:
    """Tail-read fast path used on the hot job-list poll. Must agree with the full
    parser's ``timestep`` (last ENERGY frame's TS) without reading the whole log."""

    def test_matches_full_parser(self, tmp_path: Path) -> None:
        from backend.core.namd_metrics import last_namd_timestep_fast, parse_namd_log

        log = tmp_path / "test.log"
        log.write_text(_SAMPLE_LOG)
        assert last_namd_timestep_fast(log) == parse_namd_log(log).timestep == 200

    def test_reads_last_of_many_frames(self, tmp_path: Path) -> None:
        from backend.core.namd_metrics import last_namd_timestep_fast

        # Build a log large enough that the tail window can't contain all frames — the
        # answer must still be the LAST frame, since tail-reading starts from the end.
        lines = ["ETITLE:       TS   BOND\n"]
        for step in range(0, 100_000, 500):
            lines.append(f"ENERGY:  {step}   1200.0\n")
        log = tmp_path / "big.log"
        log.write_text("".join(lines))
        assert last_namd_timestep_fast(log) == 99_500

    def test_missing_and_empty(self, tmp_path: Path) -> None:
        from backend.core.namd_metrics import last_namd_timestep_fast

        assert last_namd_timestep_fast(tmp_path / "nope.log") is None
        empty = tmp_path / "empty.log"
        empty.write_text("")
        assert last_namd_timestep_fast(empty) is None

    def test_no_energy_line_in_tail(self, tmp_path: Path) -> None:
        from backend.core.namd_metrics import last_namd_timestep_fast

        log = tmp_path / "noenergy.log"
        log.write_text("Info: startup\nInfo: reading structure\n")
        assert last_namd_timestep_fast(log) is None


class TestLastXscStep:
    """Tail-read of a ``.xst`` box trace / ``.restart.xsc`` checkpoint — the FINE step
    markers the master bar reads, written every ``xstFreq`` / ``restartfreq`` steps."""

    _XSC = (
        "# NAMD extended system configuration restart file\n"
        "#$LABELS step a_x a_y a_z b_x b_y b_z c_x c_y c_z\n"
        "585000 59.19 0 0 0 81.33 0 0 0 127.52\n"
    )

    def test_restart_xsc_single_row(self, tmp_path: Path) -> None:
        from backend.core.namd_metrics import last_xsc_step

        p = tmp_path / "prod.restart.xsc"
        p.write_text(self._XSC)
        assert last_xsc_step(p) == 585_000

    def test_xst_returns_last_row_beyond_the_tail_window(self, tmp_path: Path) -> None:
        from backend.core.namd_metrics import last_xsc_step

        rows = ["# NAMD extended system trajectory file\n", "#$LABELS step a_x\n"]
        rows += [f"{step} 59.1{step % 10}\n" for step in range(0, 250_000, 2_500)]
        p = tmp_path / "prod.xst"
        p.write_text("".join(rows))
        # Far more rows than the tail window holds — the answer is still the LAST one.
        assert last_xsc_step(p, tail_bytes=256) == 247_500

    def test_header_only_missing_and_empty(self, tmp_path: Path) -> None:
        from backend.core.namd_metrics import last_xsc_step

        assert last_xsc_step(tmp_path / "nope.xst") is None
        empty = tmp_path / "empty.xst"
        empty.write_text("")
        assert last_xsc_step(empty) is None
        header = tmp_path / "header.xst"
        header.write_text("# NAMD extended system trajectory file\n#$LABELS step a_x\n")
        assert last_xsc_step(header) is None


class TestLiveSegmentStep:
    """The bar's live step for a RUNNING segment: the FURTHEST of the log's ENERGY
    frames, the box trace and the restart checkpoint.

    Regression: a production conf prints ~400 ENERGY frames for the whole run, so on a
    measured 500 ns / 125M-step run the log said 312,500 (one frame, ~8 min apart) while
    the box trace said 585,000.  Reading the log alone pinned the bar at 0 %.
    """

    def _package(self, tmp_path: Path) -> Path:
        (tmp_path / "output").mkdir()
        return tmp_path

    def test_takes_the_furthest_marker(self, tmp_path: Path) -> None:
        from backend.core.namd_metrics import live_segment_step

        pkg = self._package(tmp_path)
        (pkg / "prod.log").write_text("ETITLE: TS BOND\nENERGY:  312500  1200.0\n")
        (pkg / "output" / "prod.xst").write_text("# trace\n0 59.1\n585000 59.2\n")
        (pkg / "output" / "prod.restart.xsc").write_text("# ckpt\n580000 59.2\n")
        assert live_segment_step(pkg, "prod") == 585_000

    def test_box_trace_alone_is_enough(self, tmp_path: Path) -> None:
        from backend.core.namd_metrics import live_segment_step

        # The first minutes of a production: the log holds only the TS-0 frame, so the
        # box trace is the ONLY evidence the run has moved.
        pkg = self._package(tmp_path)
        (pkg / "prod.log").write_text("ETITLE: TS BOND\nENERGY:  0  1200.0\n")
        (pkg / "output" / "prod.xst").write_text("# trace\n0 59.1\n42500 59.2\n")
        assert live_segment_step(pkg, "prod") == 42_500

    def test_log_alone_still_works(self, tmp_path: Path) -> None:
        from backend.core.namd_metrics import live_segment_step

        # A relaxation segment prints ~30 ENERGY frames and may not have checkpointed yet.
        pkg = self._package(tmp_path)
        (pkg / "prod.log").write_text("ETITLE: TS BOND\nENERGY:  9600  1200.0\n")
        assert live_segment_step(pkg, "prod") == 9_600

    def test_nothing_written_yet(self, tmp_path: Path) -> None:
        from backend.core.namd_metrics import live_segment_step

        assert live_segment_step(self._package(tmp_path), "prod") is None


class TestBenchmarkSPerStep:
    """Step cost from the log's Benchmark lines — the rate behind the bar's
    time-remaining estimate.  Head-read, and available within ~30 s of a run starting."""

    _BENCH = (
        "Info: Startup phase 12 took 0.001638 s\n"
        "Info: Benchmark time: 16 CPUs 0.00156458 s/step 0.00452714 days/ns 0 MB memory\n"
        "Info: Benchmark time: 16 CPUs 0.00160176 s/step 0.00463472 days/ns 0 MB memory\n"
    )

    def test_takes_the_last_most_equilibrated_line(self, tmp_path: Path) -> None:
        from backend.core.namd_metrics import benchmark_s_per_step

        log = tmp_path / "prod.log"
        log.write_text(self._BENCH)
        assert benchmark_s_per_step(log) == pytest.approx(0.00160176)

    def test_agrees_with_the_days_per_ns_on_the_same_line(self, tmp_path: Path) -> None:
        from backend.core.namd_metrics import benchmark_ns_per_day, benchmark_s_per_step

        # 4 fs/step: s/step and days/ns are two views of one measurement, so a mismatch
        # here means one of the two regexes grabbed the wrong column.
        log = tmp_path / "prod.log"
        log.write_text(self._BENCH)
        s_per_step = benchmark_s_per_step(log)
        ns_per_day = benchmark_ns_per_day(log)
        steps_per_ns = 1e6 / 4.0
        assert s_per_step * steps_per_ns * ns_per_day == pytest.approx(
            86_400.0, rel=1e-3
        )

    def test_missing_and_unbenchmarked(self, tmp_path: Path) -> None:
        from backend.core.namd_metrics import benchmark_s_per_step

        assert benchmark_s_per_step(tmp_path / "nope.log") is None
        fresh = tmp_path / "fresh.log"
        fresh.write_text(
            "Info: NAMD 3.0 for Linux-x86_64\nInfo: Startup phase 0 took 9e-05 s\n"
        )
        assert benchmark_s_per_step(fresh) is None


class TestEtaSeconds:
    """Time-remaining estimate (pure): remaining steps x measured step cost."""

    def test_matches_the_live_production_run(self) -> None:
        from backend.core.namd_metrics import eta_seconds

        # 2hb_1xT 500 ns: 124.035M steps left at 1.565 ms/step -> ~2d 6h, which must agree
        # with the run's own 221 ns/day over the 496 ns still to simulate.
        eta = eta_seconds(124_035_000, 0.00156458)
        assert eta == pytest.approx(194_063, rel=1e-3)
        assert eta / 86_400.0 == pytest.approx(496.14 / 221.0, rel=0.02)

    def test_no_rate_no_estimate(self) -> None:
        from backend.core.namd_metrics import eta_seconds

        # An absent estimate is honest; a fabricated one is not.
        assert eta_seconds(1_000_000, None) is None
        assert eta_seconds(1_000_000, 0.0) is None

    def test_finished_run_reads_zero_not_negative(self) -> None:
        from backend.core.namd_metrics import eta_seconds

        assert eta_seconds(0, 0.002) == 0
        assert eta_seconds(-500, 0.002) == 0


class TestOverallFraction:
    """Master-bar progress fraction for a NAMD job (done segments + running within-fraction)."""

    def test_single_segment_running_advances_off_zero(self) -> None:
        from backend.core.namd_metrics import overall_fraction

        # A single-segment production child, 60% through its one segment: must read 0.6,
        # NOT 0 (done/total = 0/1) — the "sits at 0% until done" bug.
        assert overall_fraction(
            0, 1, running_timestep=600, running_steps=1000
        ) == pytest.approx(0.6)

    def test_counts_done_plus_running(self) -> None:
        from backend.core.namd_metrics import overall_fraction

        # 2 of 4 done, running segment half-through → (2 + 0.5) / 4 = 0.625.
        assert overall_fraction(
            2, 4, running_timestep=500, running_steps=1000
        ) == pytest.approx(0.625)

    def test_no_live_step_falls_back_to_done_count(self) -> None:
        from backend.core.namd_metrics import overall_fraction

        assert overall_fraction(1, 4) == pytest.approx(0.25)  # no running info
        assert overall_fraction(
            1, 4, running_timestep=0, running_steps=1000
        ) == pytest.approx(0.25)

    def test_clamps_and_guards(self) -> None:
        from backend.core.namd_metrics import overall_fraction

        assert overall_fraction(0, 0) == 0.0  # no segments
        assert overall_fraction(4, 4) == pytest.approx(1.0)  # all done
        # An overshot timestep (log past the planned steps) can't push past 1.0.
        assert overall_fraction(
            0, 1, running_timestep=1500, running_steps=1000
        ) == pytest.approx(1.0)


# ── md_protocols (pure functions) ─────────────────────────────────────────────


class TestParseBoxFromNamdConf:
    def test_standard_orthogonal_box(self) -> None:
        from backend.core.md_protocols import parse_box_from_namd_conf

        conf = """\
cellBasisVector1   160.313  0.000    0.000
cellBasisVector2   0.000    157.711  0.000
cellBasisVector3   0.000    0.000    1053.629
cellOrigin         80.156   78.856   526.814
"""
        bx, by, bz = parse_box_from_namd_conf(conf)
        assert bx == pytest.approx(160.313)
        assert by == pytest.approx(157.711)
        assert bz == pytest.approx(1053.629)

    def test_raises_on_zero_box(self) -> None:
        from backend.core.md_protocols import parse_box_from_namd_conf

        with pytest.raises(ValueError, match="Could not parse box"):
            parse_box_from_namd_conf("# no cell vectors here\n")


class TestWriteRestraintsPdb:
    def test_dna_heavy_atoms_get_b1(self, tmp_path: Path) -> None:
        from backend.core.md_protocols import write_restraints_pdb

        pdb_in = tmp_path / "input.pdb"
        pdb_in.write_text(
            "ATOM      1  P    DA A   1       0.000   0.000   0.000  1.00  0.00           P\n"
            "ATOM      2  H5'  DA A   1       0.000   0.000   0.000  1.00  0.00           H\n"
            "HETATM    3  OH2  TIP A   2       1.000   1.000   1.000  1.00  0.00           O\n"
            "END\n"
        )
        dst = tmp_path / "restraints.pdb"
        write_restraints_pdb(pdb_in, dst)

        lines = dst.read_text().splitlines()
        # ATOM P heavy → B=1.00
        assert "  1.00" in lines[0][60:66]
        # ATOM H hydrogen → B=0.00
        assert "  0.00" in lines[1][60:66]
        # HETATM solvent → B=0.00
        assert "  0.00" in lines[2][60:66]

    def test_end_line_preserved(self, tmp_path: Path) -> None:
        from backend.core.md_protocols import write_restraints_pdb

        pdb_in = tmp_path / "input.pdb"
        pdb_in.write_text(
            "ATOM      1  P    DA A   1       0.000   0.000   0.000  1.00  0.00           P\n"
            "END\n"
        )
        dst = tmp_path / "restraints.pdb"
        write_restraints_pdb(pdb_in, dst)
        assert "END" in dst.read_text()


class TestMghSlowReleaseSegments:
    def test_returns_min_name_and_segments(self) -> None:
        from backend.core.md_protocols import mgh_slow_release_segments

        min_name, segments = mgh_slow_release_segments("B_tube")
        assert min_name.startswith("B_tube_")
        assert len(segments) > 0

    def test_every_stage_is_chunked_identically(self) -> None:
        """The invariant is that all stages share ONE chunk schedule — not that it has
        three entries.  The split is configurable (``chunk_pcts``) and the schedule
        itself is covered by tests/test_ladder_chunking.py; pinning 10/50/100 here made
        an arbitrary scheduling choice look like a requirement."""
        from collections import Counter

        from backend.core.md_protocols import mgh_slow_release_segments

        # The Note-4 settle stage that opens the ladder is a single un-chunked
        # segment (nothing is relaxing yet — the solute is pinned), so it is not part
        # of this invariant.
        _, segments = mgh_slow_release_segments("X")
        ladder = [s for s in segments if s.restraint_ref_file is None]
        stage_counts = Counter(s.stage for s in ladder)
        assert len(set(stage_counts.values())) == 1, stage_counts
        per_stage: dict[str, list[float]] = {}
        for seg in ladder:
            per_stage.setdefault(seg.stage, []).append(seg.percent)
        schedules = {tuple(v) for v in per_stage.values()}
        assert len(schedules) == 1, f"stages disagree on their chunk split: {schedules}"

    def test_every_stage_ends_at_one_hundred_percent(self) -> None:
        """A stage that stops short of p100 has silently shortened the ladder."""
        from backend.core.md_protocols import mgh_slow_release_segments

        _, segments = mgh_slow_release_segments("X")
        per_stage: dict[str, list[float]] = {}
        for seg in segments:
            per_stage.setdefault(seg.stage, []).append(seg.percent)
        for stage, pcts in per_stage.items():
            assert pcts == sorted(pcts), f"{stage}: chunks out of order: {pcts}"
            assert pcts[-1] == 100.0, f"{stage}: last chunk is p{pcts[-1]}, not p100"

    def test_segment_names_embed_stem(self) -> None:
        from backend.core.md_protocols import mgh_slow_release_segments

        _, segments = mgh_slow_release_segments("my_design")
        assert all(s.name.startswith("my_design_") for s in segments)

    def test_previous_chain_is_continuous(self) -> None:
        """Each segment's previous must be either the min_name or a prior segment name."""
        from backend.core.md_protocols import mgh_slow_release_segments

        min_name, segments = mgh_slow_release_segments("D")
        known = {min_name}
        for s in segments:
            assert s.previous in known, (
                f"Segment {s.name!r} references unknown previous {s.previous!r}"
            )
            known.add(s.name)

    def test_npt_segments_have_npt_true(self) -> None:
        from backend.core.md_protocols import mgh_slow_release_segments

        _, segments = mgh_slow_release_segments("X")
        npt_segs = [s for s in segments if s.npt]
        nvt_segs = [s for s in segments if not s.npt]
        assert len(npt_segs) > 0
        assert len(nvt_segs) == 0
        # Aksimentiev-style default relax runs NPT at 300 K.
        for s in npt_segs:
            assert s.temp == pytest.approx(300.0)

    def test_default_segments_use_long_aksimentiev_enm_stages(self) -> None:
        from backend.core.md_protocols import (
            AKSIMENTIEV_STEPS_PER_CYCLE,
            mgh_slow_release_segments,
        )

        _, segments = mgh_slow_release_segments("X")
        ladder = [s for s in segments if s.restraint_ref_file is None]
        stage_totals: dict[str, int] = {}
        for s in ladder:
            stage_totals[s.stage] = stage_totals.get(s.stage, 0) + s.steps
        assert set(stage_totals.values()) == {2_400_000}
        assert any(s.extra_bonds_file == "X_k0.5.enm.extra" for s in segments)
        assert all(not s.reinit for s in segments)
        # NAMD FATALs when a run count is not a multiple of stepspercycle.  This used
        # to assert % 12, which every ladder segment satisfied only by coincidence —
        # the real cycle is AKSIMENTIEV_STEPS_PER_CYCLE (20), and _common_header emits it.
        assert all(s.steps % AKSIMENTIEV_STEPS_PER_CYCLE == 0 for s in segments)

    def test_minimize_steps_round_up_to_stepspercycle(self) -> None:
        from backend.core.md_protocols import _round_up_to_cycle

        # stepspercycle is 20 (AKSIMENTIEV_STEPS_PER_CYCLE, must match _common_header).
        assert _round_up_to_cycle(4_800) == 4_800  # already aligned → unchanged
        assert _round_up_to_cycle(10_000) == 10_000  # already aligned → unchanged
        assert _round_up_to_cycle(10_001) == 10_020  # rounds UP to the next multiple

    def test_positive_steps(self) -> None:
        from backend.core.md_protocols import mgh_slow_release_segments

        _, segments = mgh_slow_release_segments("X")
        for s in segments:
            assert s.steps > 0, f"Segment {s.name!r} has steps={s.steps}"


class TestSegmentConf:
    """_segment_conf generates valid NAMD conf text."""

    def test_conf_contains_name_stem(self) -> None:
        from backend.core.md_protocols import _segment_conf, mgh_slow_release_segments

        _, segs = mgh_slow_release_segments("my_stem")
        spec = segs[0]
        conf = _segment_conf(spec, "my_stem", (100.0, 90.0, 80.0), mgh_extrabonds=False)
        assert "my_stem.psf" in conf
        assert "my_stem.pdb" in conf

    def test_npt_conf_has_barostat(self) -> None:
        from backend.core.md_protocols import _segment_conf, mgh_slow_release_segments

        _, segs = mgh_slow_release_segments("S")
        npt_spec = next(s for s in segs if s.npt)
        conf = _segment_conf(npt_spec, "S", (100.0, 90.0, 80.0), mgh_extrabonds=False)
        assert "langevinPiston     on" in conf
        assert "langevinPistonTarget" in conf

    def test_default_relax_has_no_nvt_segments(self) -> None:
        from backend.core.md_protocols import _segment_conf, mgh_slow_release_segments

        _, segs = mgh_slow_release_segments("S")
        assert all(s.npt for s in segs)
        conf = _segment_conf(segs[0], "S", (100.0, 90.0, 80.0), mgh_extrabonds=False)
        assert "langevinPiston     on" in conf

    def test_mgh_extrabonds_included_when_requested(self) -> None:
        from backend.core.md_protocols import _segment_conf, mgh_slow_release_segments

        _, segs = mgh_slow_release_segments("S")
        spec = next(s for s in segs if s.extra_bonds_file)
        with_extra = _segment_conf(spec, "S", (100.0, 90.0, 80.0), mgh_extrabonds=True)
        without = _segment_conf(spec, "S", (100.0, 90.0, 80.0), mgh_extrabonds=False)
        assert "extraBondsFile     mgh_extrabonds.txt" in with_extra
        assert "extraBondsFile     mgh_extrabonds.txt" not in without
        assert "extraBondsFile     S_k0.5.enm.extra" in without

    def test_enm_extrabonds_on_for_restrained_stage(self) -> None:
        from backend.core.md_protocols import _segment_conf, mgh_slow_release_segments

        _, segs = mgh_slow_release_segments("S")
        spec = next(s for s in segs if s.extra_bonds_file)  # first ENM stage — k=0.5
        assert spec.scale is not None
        conf = _segment_conf(spec, "S", (100.0, 90.0, 80.0), mgh_extrabonds=False)
        assert "extraBondsFile     S_k0.5.enm.extra" in conf
        assert "constraints        off" in conf

    def test_box_written_correctly(self) -> None:
        from backend.core.md_protocols import _segment_conf, mgh_slow_release_segments

        _, segs = mgh_slow_release_segments("S")
        spec = segs[0]
        box = (160.313, 157.711, 1053.629)
        conf = _segment_conf(spec, "S", box, mgh_extrabonds=False)
        assert "160.313" in conf
        assert "157.711" in conf
        assert "1053.629" in conf


class TestMghExtraBonds:
    def test_uses_literature_mg_o_restraint_strength(self) -> None:
        from backend.core.namd_solvate import _mgh_extrabonds

        text = _mgh_extrabonds(
            base_serial=100,
            n_waters=2,
            n_na=3,
            n_mg=0,
            n_mgh=1,
        )
        lines = text.strip().splitlines()

        assert len(lines) == 6
        assert all(" 1.0000 1.9400" in line for line in lines)


# ── production append protocol ────────────────────────────────────────────────


class TestProductionAppend:
    def _routes_md(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        class _Router:
            def __init__(self, *args, **kwargs):
                pass

            def __getattr__(self, name):
                def _decorator(*args, **kwargs):
                    def _wrap(fn):
                        return fn

                    return _wrap

                return _decorator

        class _HTTPException(Exception):
            def __init__(self, status_code: int, detail: str):
                super().__init__(detail)
                self.status_code = status_code
                self.detail = detail

        class _Response:
            """Stand-in for fastapi.Response — the binary solvent route returns one.
            Records what it was handed so a caller can assert on it; these tests
            never invoke that route, they just need the import to resolve."""

            def __init__(self, content=b"", media_type=None, **kwargs):
                self.body = content
                self.media_type = media_type

        async def _run_in_threadpool(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        fastapi = types.ModuleType("fastapi")
        fastapi.APIRouter = _Router
        fastapi.BackgroundTasks = object
        fastapi.HTTPException = _HTTPException
        fastapi.Request = object
        fastapi.Response = _Response
        concurrency = types.ModuleType("fastapi.concurrency")
        concurrency.run_in_threadpool = _run_in_threadpool
        assembly = types.ModuleType("backend.api.assembly")
        assembly._WORKSPACE_DIR = tmp_path

        # Re-import routes_md under the stubbed fastapi so we get a lightweight
        # module bound to the fakes above.  CRITICAL: this must NOT leak the
        # stub-bound module (or any transitively re-imported module) into
        # sys.modules — under `--dist loadfile` the next test file on this xdist
        # worker imports `backend.api.main` fresh, and a leaked stub `routes_md`
        # makes its `md_router` a fake `_Router` → `include_router` fails with
        # "'function' object is not iterable" (see project_test_parallelization.md).
        # monkeypatch.setitem can't manage this: the fresh `import` re-inserts the
        # module by a raw sys.modules write it never recorded, so teardown wouldn't
        # restore the real one.  Snapshot sys.modules and revert it EXACTLY in a
        # finally — independent of monkeypatch's undo ordering.  The returned local
        # `routes_md` still references the stub module, which is all the test needs.
        _modules_before = dict(sys.modules)
        try:
            sys.modules["fastapi"] = fastapi
            sys.modules["fastapi.concurrency"] = concurrency
            sys.modules["backend.api.assembly"] = assembly
            sys.modules.pop("backend.api.routes_md", None)
            import backend.api.routes_md as routes_md
        finally:
            for _name in list(sys.modules):
                if _name not in _modules_before:
                    del sys.modules[_name]
            sys.modules.update(_modules_before)
            # Restoring sys.modules is NOT enough: `import backend.api.routes_md`
            # also rebinds the submodule ATTRIBUTE on the parent package object
            # (`backend.api.routes_md` → the stub), and `from backend.api import
            # routes_md` reads that attribute, not sys.modules — so the victim
            # file would still patch/serve the stub. Re-point every drifted parent
            # attribute back at the real module.
            for _name, _mod in _modules_before.items():
                _parent, _, _child = _name.rpartition(".")
                _pkg = sys.modules.get(_parent)
                if _pkg is not None and getattr(_pkg, _child, _mod) is not _mod:
                    setattr(_pkg, _child, _mod)

        monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
        return routes_md

    def _ready_job(self, tmp_path: Path):
        from backend.core.md_job import (
            MdHealthSample,
            MdSegmentStatus,
            MdStatus,
            new_job,
        )

        job = new_job(
            design_name="D",
            protocol="equilibrium_aware",
            name_stem="D",
            package_subdir="package/D_namd_solvated",
        )
        job.status = MdStatus.completed
        job.segments.append(
            MdSegmentStatus(
                name="D_16_310K_NPT_k0_qualification_p100",
                stage="310K NPT unrestrained qualification",
                percent=100.0,
                steps=1000,
                status="done",
            )
        )
        job.health_samples.append(
            MdHealthSample(
                wall_time=time.time(),
                stage="310K NPT unrestrained qualification",
                segment="D_16_310K_NPT_k0_qualification_p100",
                c1_paired_fraction=0.98,
                wc_ref_relative_fraction=0.77,
                passed=True,
            )
        )
        job.save(tmp_path)

        package_dir = job.package_dir(tmp_path)
        package_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "name_stem": "D",
            "box_ang": [100.0, 90.0, 80.0],
            "mgh_extrabonds": False,
            # A fast relaxation ladder ran (4 fs rigid validated) — this is what
            # makes production HMR/4fs-eligible.
            "fast_relaxation": {"enabled": True},
            "declash": False,
            "minimization": {"name": "D_00_min_k5"},
            "segments": [
                {
                    "name": "D_16_310K_NPT_k0_qualification_p100",
                    "stage": "310K NPT unrestrained qualification",
                    "percent": 100.0,
                    "steps": 1000,
                    "temp": 310.0,
                    "damping": 1.0,
                    "scale": None,
                    "npt": True,
                    "previous": "D_16_310K_NPT_k0_qualification_p50",
                    "reinit": False,
                    "dcd_freq": 100,
                    "min_c1_paired": 0.90,
                    "min_wc_ref_relative": 0.75,
                }
            ],
        }
        text = json.dumps(manifest, indent=2)
        (package_dir / "manifest.json").write_text(text)
        (package_dir / "nadoc_md_run.json").write_text(text)
        # Fast production (HMR + 4 fs) reuses a pre-built HMR PSF when present.
        # Provide both so _append_production_segments takes the fast path without
        # having to parse a real PSF here.
        (package_dir / "D.psf").write_text("* stub\n")
        (package_dir / "D_hmr.psf").write_text("* stub\n")
        output_dir = package_dir / "output"
        output_dir.mkdir()
        for ext in ("coor", "vel", "xsc"):
            (output_dir / f"D_16_310K_NPT_k0_qualification_p100.{ext}").write_text(
                "restart\n"
            )
        return job

    def test_steps_and_ns_use_conservative_one_fs_timestep(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        routes_md = self._routes_md(tmp_path, monkeypatch)

        # Conservative fallback: 1 fs → steps == fs.
        steps, length_ns = routes_md._production_steps_and_ns(
            routes_md.ProductionRequest(length_ns=0.25), 1.0
        )
        assert steps == 250_000
        assert length_ns == pytest.approx(0.25)

        # Fast path: same simulated ns reached in 1/4 the steps at 4 fs.
        steps4, ns4 = routes_md._production_steps_and_ns(
            routes_md.ProductionRequest(length_ns=0.25), 4.0
        )
        assert steps4 == 62_500
        assert ns4 == pytest.approx(0.25)

    def test_appended_production_uses_fast_hmr_settings_by_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        routes_md = self._routes_md(tmp_path, monkeypatch)
        job = self._ready_job(tmp_path)

        plan = routes_md._production_fast_plan(
            job, routes_md.ProductionRequest(length_ns=1.0)
        )
        assert plan["fast"] is True
        assert plan["timestep_fs"] == pytest.approx(4.0)
        assert plan["total_steps"] == 250_000  # 1 ns at 4 fs

        segments = routes_md._append_production_segments(job, plan)

        assert [int(s.percent) for s in segments] == [10, 50, 100]
        assert all(s.min_wc_ref_relative == pytest.approx(0.25) for s in segments)
        # CHANGED 2026-08-03: production couples WEAKLY (1 ps^-1), the ladder strongly
        # (5). Inheriting the ladder's equilibration value overdamped the dynamics, so
        # every time-dependent observable was scaled by something unrelated to the system
        # — and the group's production runs these would be compared with use ~1.
        # See md_protocols.PRODUCTION_LANGEVIN_DAMPING / PRODUCTION_RECIPE_VERSION.
        from backend.core.md_protocols import PRODUCTION_LANGEVIN_DAMPING

        assert all(
            s.damping == pytest.approx(PRODUCTION_LANGEVIN_DAMPING) for s in segments
        )
        assert all(s.temp == pytest.approx(300.0) for s in segments)
        assert all("fast production" in s.stage for s in segments)

        package_dir = job.package_dir(tmp_path)
        conf = (package_dir / f"{segments[0].name}.conf").read_text()
        assert "structure          D_hmr.psf" in conf
        assert "timestep           4" in conf
        assert "rigidBonds         all" in conf
        assert "GPUresident        on" in conf
        # PME every 4 fs at a 4 fs step (fullElect 1) — matches the Aksimentiev
        # reference and stays under the r-RESPA ~4 fs resonance limit.  This is why
        # the tutorial's literal `fullElectFrequency 2` is NOT copied: at their 2 fs it
        # means PME every 4 fs, which is what we already do; at our 4 fs it would mean
        # every 8 fs.
        assert "fullElectFrequency 1" in conf
        # Aksimentiev tutorial electrostatics, adopted 2026-07-29 after a head-to-head
        # measurement: +39 % throughput, structurally indistinguishable (bp intact
        # 1.000 both, same T and energy drift).  See exp47_protocol_delta.
        assert "PMEGridSpacing     1.5" in conf
        assert "switchdist         8.0" in conf
        assert "cutoff             10.0" in conf
        assert "pairlistdist       12.0" in conf
        # Thermostat/barostat aligned to the Aksimentiev reference.
        assert "langevinTemp       300" in conf
        # 1 ps^-1, NOT the ladder's 5: that is an equilibration coupling, and carrying it
        # into production overdamps every time-dependent observable. The group's own
        # production runs use ~1. See PRODUCTION_LANGEVIN_DAMPING.
        assert "langevinDamping    1" in conf
        assert "langevinPistonPeriod  200.0" in conf
        assert "langevinPistonDecay   100.0" in conf

        manifest = json.loads((package_dir / "manifest.json").read_text())
        assert manifest["production_extension"]["timestep_fs"] == pytest.approx(4.0)
        assert (
            manifest["production_extension"]["settings"] == "fast_hmr_gpuresident_4fs"
        )
        assert manifest["production_extension"]["fast_production"]["enabled"] is True
        assert manifest["production_extension"]["health_gate"] == {
            "min_c1_paired": 0.90,
            "min_wc_ref_relative": 0.25,
        }

    def test_fast_plan_eligibility_gate(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Eligibility keys off fast_relaxation.enabled + declash — NOT the presence
        of a soft segment.  A normal fast ladder always has one soft strain-relief
        segment, and that must NOT knock production back to the slow 1 fs path."""
        routes_md = self._routes_md(tmp_path, monkeypatch)
        job = self._ready_job(tmp_path)
        package_dir = job.package_dir(tmp_path)
        mpath = package_dir / "manifest.json"

        def _plan_with(**manifest_overrides):
            m = json.loads(mpath.read_text())
            m.update(manifest_overrides)
            mpath.write_text(json.dumps(m, indent=2))
            return routes_md._production_fast_plan(
                job, routes_md.ProductionRequest(length_ns=1.0)
            )

        # Fast ladder + a lone soft strain-relief segment → still FAST (the bug).
        plan = _plan_with(
            fast_relaxation={"enabled": True},
            declash=False,
            segments=[{"name": "x_soft", "soft": True}],
        )
        assert plan["fast"] is True

        # Declash design → conservative even though the ladder ran fast.
        assert (
            _plan_with(fast_relaxation={"enabled": True}, declash=True)["fast"] is False
        )

        # Relaxation never ran fast (old job) → conservative.
        assert (
            _plan_with(fast_relaxation={"enabled": False}, declash=False)["fast"]
            is False
        )

    def test_declash_job_falls_back_to_conservative_production(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        routes_md = self._routes_md(tmp_path, monkeypatch)
        job = self._ready_job(tmp_path)
        # A soft/declash relaxation cannot run HMR + rigid bonds → conservative.
        package_dir = job.package_dir(tmp_path)
        manifest = json.loads((package_dir / "manifest.json").read_text())
        manifest["declash"] = True
        (package_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

        plan = routes_md._production_fast_plan(
            job, routes_md.ProductionRequest(length_ns=0.001)
        )
        assert plan["fast"] is False
        assert plan["timestep_fs"] == pytest.approx(1.0)

        segments = routes_md._append_production_segments(job, plan)
        conf = (package_dir / f"{segments[0].name}.conf").read_text()
        assert "structure          D.psf" in conf
        assert "timestep           1\n" in conf
        assert "rigidBonds         none" in conf
        # GPUresident is no longer asserted absent: it follows the SIZE gate, not the
        # timestep (exp52, 2026-08-05 — accepted, engaged and 2.06x faster at 1 fs with
        # flexible bonds). What this test is really about is the conservative INTEGRATOR
        # a declash job falls back to, which the three assertions above cover.
        assert all("conservative production" in s.stage for s in segments)
        manifest = json.loads((package_dir / "manifest.json").read_text())
        assert (
            manifest["production_extension"]["settings"] == "conservative_unrestrained"
        )

    def _seeded_job(self, tmp_path: Path):
        """An oxDNA-seeded job whose package is built but NO relaxation has run
        (no completed segments, no restart files)."""
        from backend.core.md_job import MdStatus, new_job

        job = new_job(
            design_name="S",
            protocol="equilibrium_aware",
            name_stem="S",
            package_subdir="package/S_namd_solvated",
            seed_oxdna_job_id="oxjob123",
        )
        job.status = MdStatus.queued
        job.save(tmp_path)
        package_dir = job.package_dir(tmp_path)
        package_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "name_stem": "S",
            "box_ang": [100.0, 90.0, 80.0],
            "mgh_extrabonds": False,
            "minimization": {"name": "S_00_min_k5", "steps": 4800},
            "segments": [],
        }
        text = json.dumps(manifest, indent=2)
        (package_dir / "manifest.json").write_text(text)
        (package_dir / "nadoc_md_run.json").write_text(text)
        (package_dir / "output").mkdir()
        return job

    def test_seeded_job_must_relax_before_production(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A seeded job with no relaxation checkpoint can NO LONGER produce directly
        from the seed (the minimize-then-unrestrained shortcut blew up).  It must run
        the restrained relaxation ladder first, so production 400s without a
        checkpoint — exactly like an unseeded job."""
        routes_md = self._routes_md(tmp_path, monkeypatch)
        assert routes_md._seed_production_available(self._seeded_job(tmp_path)) is False

        job = self._seeded_job(tmp_path)
        with pytest.raises(Exception) as exc:
            routes_md._append_production_segments(
                job,
                {
                    "total_steps": 1000,
                    "length_ns": 0.001,
                    "timestep_fs": 1.0,
                    "fast": False,
                },
            )
        assert getattr(exc.value, "status_code", None) == 400

    def test_display_meta_seeded_job_not_production_ready_without_checkpoint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The /display meta must NOT mark a seeded job production-ready before it has
        a relaxation checkpoint — it has to run the ladder first (no from-seed skip)."""
        import asyncio

        routes_md = self._routes_md(tmp_path, monkeypatch)
        job = self._seeded_job(tmp_path)
        meta = asyncio.run(routes_md.get_md_job_display(job.job_id))
        assert meta["production_ready"] is False
        assert meta["production_from_seed"] is False

    def test_unseeded_job_without_checkpoint_still_blocks_production(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A NON-seeded job with no relaxation checkpoint must still 400 (no
        produce-from-seed shortcut)."""
        routes_md = self._routes_md(tmp_path, monkeypatch)
        job = self._seeded_job(tmp_path)
        job.seed_oxdna_job_id = None  # remove the seed provenance
        job.save(tmp_path)
        with pytest.raises(Exception) as exc:
            routes_md._append_production_segments(
                job,
                {
                    "total_steps": 1000,
                    "length_ns": 0.001,
                    "timestep_fs": 1.0,
                    "fast": False,
                },
            )
        assert getattr(exc.value, "status_code", None) == 400

    # ── production-run child jobs (mirror oxDNA: relaxation stays, productions nest) ──

    def _spawn(
        self, routes_md, tmp_path, monkeypatch, parent, *, autostart=False, seed=None
    ):
        """Call the production-run endpoint with staleness + NAMD launch stubbed out."""
        import asyncio

        # build_replica_package hardlinks the parent PSF *and* PDB into the child pkg;
        # the _ready_job fixture only writes the PSF, so add the PDB it copies.
        (parent.package_dir(tmp_path) / "D.pdb").write_text("* stub\n")
        monkeypatch.setattr(routes_md, "_assert_md_job_current", lambda job: None)
        started: list = []
        monkeypatch.setattr(
            routes_md, "start_job", lambda job, ws: started.append(job.job_id)
        )
        result = asyncio.run(
            routes_md.spawn_md_production(
                parent.job_id,
                routes_md.ProductionRunRequest(
                    length_ns=1.0, autostart=autostart, seed=seed
                ),
            )
        )
        return result, started

    def test_production_spawns_child_leaving_relaxation_intact(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Production creates a CHILD job under the relaxation; the relaxation job is
        NOT mutated (its segments/manifest are untouched), so it stays visible and
        selectable — the whole point of the child-job model."""
        from backend.core.md_job import MdJob, MdStatus

        routes_md = self._routes_md(tmp_path, monkeypatch)
        parent = self._ready_job(tmp_path)
        parent_seg_names = [s.name for s in parent.segments]

        result, _ = self._spawn(routes_md, tmp_path, monkeypatch, parent)
        child = MdJob.load(result["job"]["job_id"], tmp_path)

        assert child.parent_job_id == parent.job_id
        assert child.run_kind == "production"
        # The seed is DRAWN, not fixed — assert the contract (a recorded, in-range NAMD
        # seed), never a literal value.
        assert 1 <= child.ensemble_seed <= md_ensemble.NAMD_SEED_MAX
        assert child.namd_seed == child.ensemble_seed
        assert child.ensemble_index == 0
        assert child.execution_target == "local"
        assert child.status == MdStatus.queued  # autostart False
        # Child package is a fresh production-only package (reseed + one production seg).
        pkg = child.package_dir(tmp_path)
        assert (pkg / "demo_00_reseed.conf").exists() or list(
            pkg.glob("*_00_reseed.conf")
        )
        assert len(child.segments) == 1
        # The parent relaxation is byte-for-byte unchanged.
        reloaded = MdJob.load(parent.job_id, tmp_path)
        assert reloaded.status == MdStatus.completed
        assert [s.name for s in reloaded.segments] == parent_seg_names
        assert reloaded.run_kind is None

    def test_production_child_of_an_archived_parent_stays_on_the_archive_drive(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A relaxation is archived because its folder is too big for the system disk —
        and PRODUCTION is the part that writes the big trajectory.

        The child used to default to archived=False, so job_dir() resolved back to
        workspace/md_jobs/<id> and it would dump gigabytes of DCD onto the exact disk
        the parent had been moved off. For a 1.9M-atom run on a 20 GB system disk that
        is a full disk overnight, not a tidiness issue.
        """
        from backend.core import job_archive
        from backend.core.md_job import MdJob

        routes_md = self._routes_md(tmp_path, monkeypatch)
        parent = self._ready_job(tmp_path)

        # Archive the parent by hand (an "external drive" under tmp_path).
        drive = tmp_path / "external_drive" / "nadoc_jobs"
        archived_dir = drive / parent.job_id
        archived_dir.mkdir(parents=True)
        for f in parent.job_dir(tmp_path).rglob("*"):
            if f.is_file():
                dst = archived_dir / f.relative_to(parent.job_dir(tmp_path))
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(f.read_bytes())
        parent.archived = True
        parent.archive_path = str(archived_dir)
        parent.save(tmp_path)
        # An archived job is discoverable ONLY through the index — MdJob.load() consults
        # it to find the folder. Without this entry the route would silently load the
        # stale workspace job.json (still archived=False) and the test would pass for
        # entirely the wrong reason.
        idx = job_archive.read_index(tmp_path, "md_jobs")
        idx[parent.job_id] = parent.archive_path
        job_archive._write_index(tmp_path, "md_jobs", idx)

        result, _ = self._spawn(routes_md, tmp_path, monkeypatch, parent)
        child = MdJob.load(result["job"]["job_id"], tmp_path)

        assert child.archived is True
        # Sibling of the parent, on the same drive — one archive root per family.
        assert child.job_dir(tmp_path) == drive / child.job_id
        assert child.job_dir(tmp_path).is_relative_to(drive)
        # And decisively: nothing was written to the system-disk workspace.
        assert not (tmp_path / "md_jobs" / child.job_id).exists()

    def test_production_child_of_an_unarchived_parent_stays_in_the_workspace(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The inverse pin: archiving is INHERITED, never invented."""
        from backend.core.md_job import MdJob

        routes_md = self._routes_md(tmp_path, monkeypatch)
        parent = self._ready_job(tmp_path)
        result, _ = self._spawn(routes_md, tmp_path, monkeypatch, parent)
        child = MdJob.load(result["job"]["job_id"], tmp_path)

        assert child.archived is False
        assert child.archive_path is None
        assert child.job_dir(tmp_path) == tmp_path / "md_jobs" / child.job_id

    def test_repeated_productions_get_distinct_seeds(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Each production child of the same parent draws its own RANDOM velocity seed, so
        a fan-out samples independent trajectories — and so two designs being compared do
        not silently share one velocity realisation, which a fixed base seed guaranteed."""
        from backend.core.md_job import MdJob

        routes_md = self._routes_md(tmp_path, monkeypatch)
        parent = self._ready_job(tmp_path)

        r0, _ = self._spawn(routes_md, tmp_path, monkeypatch, parent)
        r1, _ = self._spawn(routes_md, tmp_path, monkeypatch, parent)
        r2, _ = self._spawn(routes_md, tmp_path, monkeypatch, parent)

        seeds = [
            MdJob.load(r["job"]["job_id"], tmp_path).ensemble_seed for r in (r0, r1, r2)
        ]
        assert len(set(seeds)) == 3, f"siblings collided onto one trajectory: {seeds}"
        assert all(1 <= s <= md_ensemble.NAMD_SEED_MAX for s in seeds)
        # Not the old deterministic ladder — three consecutive integers from a fixed base
        # would mean the randomisation regressed.
        assert sorted(seeds) != [54321, 54322, 54323]
        idxs = [
            MdJob.load(r["job"]["job_id"], tmp_path).ensemble_index
            for r in (r0, r1, r2)
        ]
        assert idxs == [0, 1, 2]

    def test_production_inherits_the_parents_anchors_and_field(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """THE bug: the anchors card was read only by the relax launch, and the replica
        builder never forwarded anchors/field — so an anchored relaxation produced an
        unanchored production child, and an E-field job's child ran field-free."""
        from backend.core.md_job import MdJob

        routes_md = self._routes_md(tmp_path, monkeypatch)
        parent = self._ready_job(tmp_path)
        pkg = parent.package_dir(tmp_path)
        (pkg / "restraints_anchors.pdb").write_text(
            "ATOM      1  C1' DT  A   1       0.000   0.000   0.000  1.00  1.00\n"
        )
        manifest = json.loads((pkg / "manifest.json").read_text())
        manifest["files"] = {"anchors": "restraints_anchors.pdb"}
        manifest["anchors"] = {"requested": [{"kind": "base"}]}
        manifest["field"] = {"field_pN": 5.0, "dir": [0.0, 0.0, 1.0]}
        (pkg / "manifest.json").write_text(json.dumps(manifest))

        result, _ = self._spawn(routes_md, tmp_path, monkeypatch, parent)
        child = MdJob.load(result["job"]["job_id"], tmp_path)
        child_pkg = child.package_dir(tmp_path)
        conf = next(child_pkg.glob("D_01_production_*.conf")).read_text()
        assert "fixedAtoms         on" in conf
        assert "eFieldOn" in conf
        assert (child_pkg / "restraints_anchors.pdb").exists()
        cm = json.loads((child_pkg / "manifest.json").read_text())
        assert cm["anchors"]["n_atoms_anchored"] == 1
        assert cm["field"]["field_pN"] == 5.0

    def test_production_request_can_turn_an_inherited_anchor_off(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`anchors: []` is meaningful — it is how an anchored parent spawns a free
        control run.  It must not be confused with `anchors: None` (inherit)."""
        import asyncio

        from backend.core.md_job import MdJob

        routes_md = self._routes_md(tmp_path, monkeypatch)
        parent = self._ready_job(tmp_path)
        pkg = parent.package_dir(tmp_path)
        (pkg / "restraints_anchors.pdb").write_text(
            "ATOM      1  C1' DT  A   1       0.000   0.000   0.000  1.00  1.00\n"
        )
        manifest = json.loads((pkg / "manifest.json").read_text())
        manifest["files"] = {"anchors": "restraints_anchors.pdb"}
        (pkg / "manifest.json").write_text(json.dumps(manifest))
        (pkg / "D.pdb").write_text("* stub\n")
        monkeypatch.setattr(routes_md, "_assert_md_job_current", lambda job: None)
        monkeypatch.setattr(routes_md, "start_job", lambda job, ws: None)

        result = asyncio.run(
            routes_md.spawn_md_production(
                parent.job_id,
                routes_md.ProductionRunRequest(
                    length_ns=1.0, autostart=False, anchors=[]
                ),
            )
        )
        child = MdJob.load(result["job"]["job_id"], tmp_path)
        conf = next(
            child.package_dir(tmp_path).glob("D_01_production_*.conf")
        ).read_text()
        assert "fixedAtoms" not in conf
        assert "constraints        off" in conf

    def test_production_seed_can_be_pinned_to_reproduce_a_run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Randomised by default, reproducible on request: an explicit seed is honoured
        verbatim and recorded, so a published trajectory can be re-run."""
        from backend.core.md_job import MdJob

        routes_md = self._routes_md(tmp_path, monkeypatch)
        parent = self._ready_job(tmp_path)

        result, _ = self._spawn(routes_md, tmp_path, monkeypatch, parent, seed=99991)
        child = MdJob.load(result["job"]["job_id"], tmp_path)
        assert child.ensemble_seed == 99991
        conf = (
            child.package_dir(tmp_path) / f"{child.name_stem}_00_reseed.conf"
        ).read_text()
        assert "seed               99991" in conf

    def test_production_autostart_launches_local(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from backend.core.md_job import MdJob, MdStatus

        routes_md = self._routes_md(tmp_path, monkeypatch)
        parent = self._ready_job(tmp_path)
        result, started = self._spawn(
            routes_md, tmp_path, monkeypatch, parent, autostart=True
        )
        child = MdJob.load(result["job"]["job_id"], tmp_path)
        assert child.status == MdStatus.running
        assert started == [child.job_id]

    # ── revert an old-style appended production back to a clean relaxation ──────────

    def _append_fake_production(self, tmp_path, job, names):
        """Bolt production segments + confs + output onto a relaxation job (mimics the
        legacy same-job append), including a stopped/partial run's files."""
        import json
        from backend.core.md_job import MdSegmentStatus, MdStatus

        pkg = job.package_dir(tmp_path)
        for n in names:
            job.segments.append(
                MdSegmentStatus(
                    name=n,
                    stage="1 ns production run",
                    percent=100.0,
                    steps=1000,
                    status="pending",
                )
            )
            (pkg / f"{n}.conf").write_text("conf")
            (pkg / f"{n}.log").write_text("log")
            (pkg / "output" / f"{n}.dcd").write_text("dcd")
            (pkg / "output" / f"{n}.restart.coor").write_text("coor")
        job.status = MdStatus.stopped
        job.user_stopped = True
        job.current_segment_idx = 1
        job.save(tmp_path)
        manifest = json.loads((pkg / "manifest.json").read_text())
        manifest["segments"].extend(
            {"name": n, "stage": "1 ns production run", "percent": 100.0, "steps": 1000}
            for n in names
        )
        manifest["production_extension"] = {
            "length_ns": 1.0,
            "last_new_segment": names[-1],
        }
        (pkg / "manifest.json").write_text(json.dumps(manifest, indent=2))
        return pkg

    def test_revert_appended_production_restores_clean_relaxation(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import json
        from backend.core.md_job import MdJob, MdStatus, revert_appended_production

        self._routes_md(tmp_path, monkeypatch)
        job = self._ready_job(tmp_path)
        relax_only = [s.name for s in job.segments]
        # "_p10" and "_p100" together prove the dot-prefixed glob doesn't over-match.
        prod = ["D_17_production_1ns_k0_p10", "D_17_production_1ns_k0_p100"]
        pkg = self._append_fake_production(tmp_path, job, prod)

        report = revert_appended_production(job, tmp_path)
        assert report["reverted"] is True
        assert set(report["removed_segments"]) == set(prod)

        j = MdJob.load(job.job_id, tmp_path)
        assert [s.name for s in j.segments] == relax_only  # production peeled off
        assert j.status == MdStatus.completed and j.user_stopped is False
        assert j.current_segment_idx == len(relax_only)

        m = json.loads((pkg / "manifest.json").read_text())
        assert "production_extension" not in m
        assert all("production" not in s["name"] for s in m["segments"])

        # Production artifacts MOVED (not deleted) to the backup folder.
        for n in prod:
            assert not (pkg / f"{n}.conf").exists()
            assert not (pkg / "output" / f"{n}.dcd").exists()
        backup = job.job_dir(tmp_path) / "_superseded_production"
        assert len(list(backup.rglob("*.dcd"))) == 2
        assert len(list(backup.rglob("*.conf"))) == 2
        # The relaxation checkpoint's own output is UNTOUCHED (a future child seeds from it).
        assert (pkg / "output" / "D_16_310K_NPT_k0_qualification_p100.coor").exists()

    def test_revert_is_idempotent_and_guards_non_legacy_jobs(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from backend.core.md_job import MdJob, revert_appended_production

        self._routes_md(tmp_path, monkeypatch)
        job = self._ready_job(tmp_path)
        # No production appended → nothing to do.
        assert revert_appended_production(job, tmp_path)["reverted"] is False

        # After one revert of an appended job, a second call is a no-op.
        self._append_fake_production(tmp_path, job, ["D_17_production_1ns_k0_p10"])
        assert revert_appended_production(job, tmp_path)["reverted"] is True
        assert (
            revert_appended_production(MdJob.load(job.job_id, tmp_path), tmp_path)[
                "reverted"
            ]
            is False
        )

        # A real production CHILD must never be reverted (that would nuke a legit run).
        child = self._ready_job(tmp_path)
        child.run_kind = "production"
        child.parent_job_id = "some_parent"
        child.save(tmp_path)
        self._append_fake_production(tmp_path, child, ["C_01_production_1ns_k0_p100"])
        assert revert_appended_production(child, tmp_path)["reverted"] is False

    def test_production_alpine_target_queues_without_local_start(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An Alpine-targeted production child is created 'queued' (for the submit-review
        card) and is NEVER started locally — even with autostart=True — regardless of
        where the parent relaxation ran."""
        import asyncio
        from backend.core.md_job import MdJob, MdStatus

        routes_md = self._routes_md(tmp_path, monkeypatch)
        monkeypatch.setattr(routes_md, "_assert_md_job_current", lambda job: None)
        started: list = []
        monkeypatch.setattr(
            routes_md, "start_job", lambda job, ws: started.append(job.job_id)
        )
        parent = self._ready_job(tmp_path)  # a LOCAL relaxation
        (parent.package_dir(tmp_path) / "D.pdb").write_text("* stub\n")

        result = asyncio.run(
            routes_md.spawn_md_production(
                parent.job_id,
                routes_md.ProductionRunRequest(
                    length_ns=1.0, autostart=True, execution_target="alpine"
                ),
            )
        )
        child = MdJob.load(result["job"]["job_id"], tmp_path)
        assert child.execution_target == "alpine"
        assert child.cluster_name == "alpine"
        assert child.status == MdStatus.queued
        assert started == []  # never launched locally

    def test_production_refused_while_parent_is_running(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No new production child may be spawned while the parent job is actively
        running on the GPU (a completed status by segment state isn't enough)."""
        import asyncio

        routes_md = self._routes_md(tmp_path, monkeypatch)
        monkeypatch.setattr(routes_md, "_assert_md_job_current", lambda job: None)
        monkeypatch.setattr(routes_md, "is_running", lambda jid: True)
        parent = self._ready_job(tmp_path)
        with pytest.raises(Exception) as exc:
            asyncio.run(
                routes_md.spawn_md_production(
                    parent.job_id, routes_md.ProductionRunRequest(length_ns=1.0)
                )
            )
        assert getattr(exc.value, "status_code", None) == 400


# ── namd_runner (pure helpers only) ──────────────────────────────────────────


class TestOrphanStop:
    """A NAMD run orphaned by a server restart (no in-memory runner thread) must still
    be stoppable from the UI: stop_job finds the detached PID and kills it."""

    def _running_job(self, tmp_path: Path):
        from backend.core.md_job import MdSegmentStatus, MdStatus, new_job

        job = new_job(
            design_name="S",
            protocol="equilibrium_aware",
            name_stem="S",
            package_subdir="package/S",
        )
        job.segments = [MdSegmentStatus(name="S_01", stage="x", percent=10, steps=100)]
        job.current_segment_idx = 0
        job.status = MdStatus.running
        job.save(tmp_path)
        return job

    def test_stop_orphan_kills_external_pid_and_marks_stopped(
        self, tmp_path, monkeypatch
    ):
        from backend.core import namd_runner
        from backend.core.md_job import MdJob, MdStatus

        job = self._running_job(tmp_path)
        killed = []
        monkeypatch.setattr(namd_runner, "_external_pid", lambda j: 4242)
        monkeypatch.setattr(
            namd_runner, "_kill_process_group", lambda pid, **k: killed.append(pid)
        )

        assert namd_runner.stop_job(job.job_id, tmp_path) is True
        assert killed == [4242]
        reloaded = MdJob.load(job.job_id, tmp_path)
        assert reloaded.status == MdStatus.stopped
        assert reloaded.namd_pid is None

    def test_stop_orphan_falls_back_to_persisted_pid(self, tmp_path, monkeypatch):
        from backend.core import namd_runner

        job = self._running_job(tmp_path)
        job.namd_pid = 7777
        job.save(tmp_path)
        killed = []
        monkeypatch.setattr(
            namd_runner, "_external_pid", lambda j: None
        )  # /proc scan misses
        monkeypatch.setattr(
            namd_runner, "_pid_is_namd", lambda pid: True
        )  # but persisted PID is ours
        monkeypatch.setattr(
            namd_runner, "_kill_process_group", lambda pid, **k: killed.append(pid)
        )

        assert namd_runner.stop_job(job.job_id, tmp_path) is True
        assert killed == [7777]

    def test_stop_adopted_orphan_kills_via_proc_scan(self, tmp_path, monkeypatch):
        """Regression: after a dev-server reload the new worker *adopts* the surviving
        NAMD (run_job sits in _wait_for_segment_process) so _RUNNING has a live handle
        but _ACTIVE_PIDS is EMPTY.  Stop must still kill the process (found via the
        /proc scan), not just cancel the wait and leave NAMD burning the GPU."""
        import threading

        from backend.core import namd_runner

        job = self._running_job(tmp_path)
        killed: list[int] = []
        cancelled: list[str] = []

        # A live runner thread with NO _ACTIVE_PIDS entry (adopted, not spawned).
        alive = threading.Event()
        thread = threading.Thread(target=alive.wait, daemon=True)
        thread.start()

        class _FakeLoop:
            def call_soon_threadsafe(self, fn):
                cancelled.append("cancel")

        class _FakeTask:
            def cancel(self):  # pragma: no cover - invoked via fake loop
                cancelled.append("task")

        handle = namd_runner._RunningHandle(
            thread=thread, loop=_FakeLoop(), task=_FakeTask()
        )
        monkeypatch.setitem(namd_runner._RUNNING, job.job_id, handle)
        namd_runner._ACTIVE_PIDS.pop(job.job_id, None)  # nothing spawned by this worker
        monkeypatch.setattr(namd_runner, "_external_pid", lambda j: 5151)
        monkeypatch.setattr(
            namd_runner, "_kill_process_group", lambda pid, **k: killed.append(pid)
        )

        try:
            assert namd_runner.stop_job(job.job_id, tmp_path) is True
            assert killed == [5151]  # the orphan was actually signalled
            assert cancelled == ["cancel"]  # and the runner task cancelled
        finally:
            alive.set()
            thread.join(timeout=2)
            namd_runner._RUNNING.pop(job.job_id, None)

    def test_stop_clears_error_and_reverts_running_segment(self, tmp_path, monkeypatch):
        """A clean user-stop must leave no error behind and no segment stuck
        "running": otherwise the sidebar shows "Unknown error" + a perpetual
        spinner on a terminal job."""
        from backend.core import namd_runner
        from backend.core.md_job import MdJob, MdStatus

        job = self._running_job(tmp_path)
        job.error = "transient interrupted/resuming message"
        job.segments[0].status = "running"
        job.save(tmp_path)

        # Orphan path (no live runner handle) — stop_job writes the stopped state.
        monkeypatch.setattr(namd_runner, "_external_pid", lambda j: 4242)
        monkeypatch.setattr(namd_runner, "_kill_process_group", lambda pid, **k: None)

        assert namd_runner.stop_job(job.job_id, tmp_path) is True
        reloaded = MdJob.load(job.job_id, tmp_path)
        assert reloaded.status == MdStatus.stopped
        assert reloaded.user_stopped is True
        assert reloaded.error is None
        assert reloaded.segments[0].status == "pending"

    def test_apply_user_stop_only_reverts_running_segments(self, tmp_path):
        """apply_user_stop leaves done/failed segments alone — only the in-flight
        (running) one is rewound to pending."""
        from backend.core import namd_runner
        from backend.core.md_job import MdSegmentStatus, MdStatus

        job = self._running_job(tmp_path)
        job.segments = [
            MdSegmentStatus(name="S_01", stage="x", percent=100, steps=100),
            MdSegmentStatus(name="S_02", stage="x", percent=50, steps=100),
        ]
        job.segments[0].status = "done"
        job.segments[1].status = "running"
        job.error = "boom"

        namd_runner.apply_user_stop(job)

        assert job.status == MdStatus.stopped
        assert job.user_stopped is True
        assert job.error is None
        assert job.segments[0].status == "done"  # completed work preserved
        assert job.segments[1].status == "pending"  # in-flight rewound

    def test_stop_no_orphan_returns_false_without_killing(self, tmp_path, monkeypatch):
        from backend.core import namd_runner

        job = self._running_job(tmp_path)
        killed = []
        monkeypatch.setattr(namd_runner, "_external_pid", lambda j: None)
        monkeypatch.setattr(
            namd_runner, "_kill_process_group", lambda pid, **k: killed.append(pid)
        )
        # no persisted PID, no /proc match → nothing to kill
        assert namd_runner.stop_job(job.job_id, tmp_path) is False
        assert killed == []


class TestFindNamd:
    def test_finds_installed_binary(self) -> None:
        """Smoke test: find_namd() should succeed on this machine."""
        import os
        from backend.core.namd_runner import find_namd

        try:
            path = find_namd()
            assert os.path.isfile(path) or bool(path)
        except RuntimeError:
            pytest.skip("NAMD3 not installed on this machine")

    def test_is_running_false_for_unknown(self) -> None:
        from backend.core.namd_runner import is_running

        assert is_running("no_such_job_id") is False

    def test_reconcile_completed_orphaned_segment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from backend.core.md_health import HealthCheckResult
        from backend.core.md_job import MdSegmentStatus, MdStatus, new_job
        import backend.core.namd_runner as runner

        job = new_job("D", "equilibrium_aware", "D", "package/D_namd_solvated")
        job.status = MdStatus.running
        job.current_segment_idx = 0
        job.segments = [
            MdSegmentStatus(
                name="D_01_production_p50",
                stage="310K NPT conservative production 0.5 ns unrestrained",
                percent=50.0,
                steps=200000,
                status="running",
            ),
            MdSegmentStatus(
                name="D_01_production_p100",
                stage="310K NPT conservative production 0.5 ns unrestrained",
                percent=100.0,
                steps=250000,
                status="pending",
            ),
        ]
        job.save(tmp_path)

        package_dir = job.package_dir(tmp_path)
        output_dir = package_dir / "output"
        output_dir.mkdir(parents=True)
        manifest = {
            "name_stem": "D",
            "minimization": {"name": "D_00_min"},
            "segments": [
                {
                    "name": "D_01_production_p50",
                    "stage": "310K NPT conservative production 0.5 ns unrestrained",
                    "percent": 50.0,
                    "steps": 200000,
                    "temp": 310.0,
                    "damping": 1.0,
                    "scale": None,
                    "npt": True,
                    "previous": "D_00_min",
                    "reinit": False,
                    "dcd_freq": 4000,
                    "min_c1_paired": 0.90,
                    "min_wc_ref_relative": 0.25,
                },
                {
                    "name": "D_01_production_p100",
                    "stage": "310K NPT conservative production 0.5 ns unrestrained",
                    "percent": 100.0,
                    "steps": 250000,
                    "temp": 310.0,
                    "damping": 1.0,
                    "scale": None,
                    "npt": True,
                    "previous": "D_01_production_p50",
                    "reinit": False,
                    "dcd_freq": 5000,
                    "min_c1_paired": 0.90,
                    "min_wc_ref_relative": 0.25,
                },
            ],
        }
        (package_dir / "manifest.json").write_text(json.dumps(manifest))
        (package_dir / "D_01_production_p50.log").write_text(
            "ETITLE: TS TEMP TEMPAVG PRESSURE GPRESSURE VOLUME PRESSAVG GPRESSAVG\n"
            "ENERGY: 200000 307.6 307.9 -231.9 -1.9 2199809.7 46.3 47.6\n"
            "WRITING VELOCITIES TO OUTPUT FILE AT STEP 200000\n"
            "[Partition 0][Node 0] End of program\n"
        )
        for ext in ("coor", "vel", "xsc"):
            (output_dir / f"D_01_production_p50.{ext}").write_text("restart\n")
        (output_dir / "D_01_production_p50.dcd").write_text("fake dcd\n")

        monkeypatch.setattr(
            runner,
            "run_health_check",
            lambda *args, **kwargs: HealthCheckResult(
                passed=True,
                c1_paired_fraction=0.98,
                c1_mean_ang=9.7,
                c1_p90_ang=10.8,
                wc_ref_relative_fraction=0.74,
                wc_mean_hbond_ang=5.4,
            ),
        )

        reconciled = runner.reconcile_job_status(job, tmp_path)

        # A completed segment with pending work left behind now stays `running` so
        # the startup/supervisor auto-resume relaunches the next segment, instead
        # of parking at `stopped` and waiting for a manual click.
        assert reconciled.status == MdStatus.running
        assert reconciled.current_segment_idx == 1
        assert reconciled.segments[0].status == "done"
        assert "resuming from" in (reconciled.error or "")
        assert "D_01_production_p50" in (output_dir / "metrics.jsonl").read_text()
        assert "D_01_production_p50" in (output_dir / "health.jsonl").read_text()


class TestReconcilePreparing:
    """A 'preparing' job whose background prep task died must self-heal to failed."""

    def _preparing_job(self, tmp_path):
        from backend.core.md_job import MdStatus, new_job

        job = new_job("P", "equilibrium_aware", "", "")
        job.status = MdStatus.preparing
        job.save(tmp_path)
        return job

    def test_stale_sidecar_marks_failed(self, tmp_path, monkeypatch):
        import time as _time
        from backend.core.md_job import MdStatus
        from backend.core.md_prep_progress import (
            write_prep_progress,
            PREP_PROGRESS_FILENAME,
        )
        import backend.core.namd_runner as runner

        job = self._preparing_job(tmp_path)
        write_prep_progress(
            job.job_dir(tmp_path), {"phase": "solvate", "fraction": 0.3}
        )
        # Backdate the sidecar well past the stale threshold (task is gone).
        sidecar = job.job_dir(tmp_path) / PREP_PROGRESS_FILENAME
        old = _time.time() - (runner._PREP_STALE_S + 60)
        import os

        os.utime(sidecar, (old, old))

        out = runner.reconcile_job_status(job, tmp_path)
        assert out.status == MdStatus.failed
        assert "interrupted" in (out.error or "").lower()

    def test_missing_sidecar_marks_failed(self, tmp_path):
        from backend.core.md_job import MdStatus
        import backend.core.namd_runner as runner

        job = self._preparing_job(tmp_path)  # no sidecar written at all
        out = runner.reconcile_job_status(job, tmp_path)
        assert out.status == MdStatus.failed

    def test_fresh_sidecar_left_preparing(self, tmp_path):
        from backend.core.md_job import MdStatus
        from backend.core.md_prep_progress import write_prep_progress
        import backend.core.namd_runner as runner

        job = self._preparing_job(tmp_path)
        write_prep_progress(
            job.job_dir(tmp_path), {"phase": "solvate", "fraction": 0.3}
        )
        out = runner.reconcile_job_status(job, tmp_path)
        assert out.status == MdStatus.preparing  # live heartbeat → untouched

    def test_completed_package_heals_false_interruption_verdict(self, tmp_path):
        from backend.core.md_job import MdStatus, new_job
        import backend.core.namd_runner as runner

        job = new_job("P", "equilibrium_aware", "P", "package/P_namd_solvated")
        job.status = MdStatus.queued
        job.error = "Preparation was interrupted — its background task is no longer running"
        job.failure_kind = "other"
        package = job.package_dir(tmp_path)
        package.mkdir(parents=True)
        (package / "manifest.json").write_text("{}")
        job.save(tmp_path)

        out = runner.reconcile_job_status(job, tmp_path)

        assert out.status == MdStatus.queued
        assert out.error is None
        assert out.failure_kind is None

    def test_stale_runpod_preparation_is_not_exempt_from_reconciliation(
        self, tmp_path, monkeypatch
    ):
        """RunPod packaging is still a local background task before submission."""
        import os
        import time as _time
        from backend.core.md_job import MdStatus
        from backend.core.md_prep_progress import PREP_PROGRESS_FILENAME, write_prep_progress
        import backend.core.namd_runner as runner

        job = self._preparing_job(tmp_path)
        job.execution_target = "runpod"
        job.save(tmp_path)
        write_prep_progress(job.job_dir(tmp_path), {"phase": "topology", "fraction": 0.112})
        sidecar = job.job_dir(tmp_path) / PREP_PROGRESS_FILENAME
        old = _time.time() - runner._PREP_STALE_S - 1
        os.utime(sidecar, (old, old))

        out = runner.reconcile_job_status(job, tmp_path)

        assert out.status == MdStatus.failed
        assert "interrupted" in (out.error or "").lower()


class TestMdChain:
    """P2 chain executor wired end-to-end through the real NAMD spawn/status adapter
    (NAMD launch stubbed): create -> a real stage-0 production child; halt-on-failure ->
    resume-from-failed.  The stage-to-stage seeding logic itself is proven headless in
    ``tests/test_md_chain_executor.py`` (the engine-agnostic CHAIN oracle).  Reuses
    ``TestProductionAppend``'s ``_routes_md`` / ``_ready_job`` helpers (stateless)."""

    _tp = TestProductionAppend()

    def _create_chain(self, routes_md, tmp_path, monkeypatch, parent, *, n=2):
        import asyncio

        (parent.package_dir(tmp_path) / "D.pdb").write_text("* stub\n")
        monkeypatch.setattr(routes_md, "_assert_md_job_current", lambda job: None)
        started: list = []
        monkeypatch.setattr(
            routes_md, "start_job", lambda job, ws: started.append(job.job_id)
        )
        body = routes_md.CreateChainRequest(
            root_job_id=parent.job_id,
            root_engine="namd",
            stages=[
                routes_md.ChainStageRequest(engine="namd", length_ns=1.0)
                for _ in range(n)
            ],
        )
        result = asyncio.run(routes_md.create_md_chain(body))
        return result["chain"], started

    def test_create_chain_spawns_real_stage0_child(self, tmp_path, monkeypatch):
        from backend.core.md_job import MdJob

        routes_md = self._tp._routes_md(tmp_path, monkeypatch)
        parent = self._tp._ready_job(tmp_path)
        chain, started = self._create_chain(routes_md, tmp_path, monkeypatch, parent)

        assert chain["status"] == "running"
        assert chain["stages"][0]["status"] == "running"
        assert chain["stages"][1]["status"] == "pending"
        s0_job = chain["stages"][0]["job_id"]
        assert s0_job
        child0 = MdJob.load(s0_job, tmp_path)
        assert child0.parent_job_id == parent.job_id  # stage 0 seeds from the root
        assert child0.run_kind == "production"
        assert started == [s0_job]  # local child autostarted

    def test_create_requires_completed_root(self, tmp_path, monkeypatch):
        import asyncio

        from backend.core.md_job import MdStatus

        routes_md = self._tp._routes_md(tmp_path, monkeypatch)
        parent = self._tp._ready_job(tmp_path)
        parent.status = MdStatus.failed  # a failed root reconciles to != completed
        parent.save(tmp_path)
        body = routes_md.CreateChainRequest(
            root_job_id=parent.job_id,
            stages=[routes_md.ChainStageRequest(engine="namd", length_ns=1.0)],
        )
        with pytest.raises(Exception) as exc:
            asyncio.run(routes_md.create_md_chain(body))
        assert getattr(exc.value, "status_code", None) == 400

    def test_chain_halts_on_stage_failure_then_resumes_from_failed(
        self, tmp_path, monkeypatch
    ):
        import asyncio

        from backend.core.md_job import MdJob, MdStatus

        routes_md = self._tp._routes_md(tmp_path, monkeypatch)
        parent = self._tp._ready_job(tmp_path)
        chain, _ = self._create_chain(routes_md, tmp_path, monkeypatch, parent)
        chain_id = chain["chain_id"]
        s0_job = chain["stages"][0]["job_id"]

        # Stage-0 child fails -> the supervisor pass HALTS the chain (no downstream spawn).
        child0 = MdJob.load(s0_job, tmp_path)
        child0.status = MdStatus.failed
        child0.save(tmp_path)
        asyncio.run(routes_md.advance_chains(tmp_path))
        halted = asyncio.run(routes_md.get_md_chain(chain_id))["chain"]
        assert halted["status"] == "failed"
        assert halted["stages"][0]["status"] == "failed"
        assert halted["stages"][1]["status"] == "pending"

        # Resume re-runs ONLY the failed stage: a NEW stage-0 child spawns; stage 1 stays
        # pending (retry-only-failed, not a full restart).
        resumed = asyncio.run(routes_md.resume_md_chain(chain_id))["chain"]
        assert resumed["status"] == "running"
        assert resumed["stages"][0]["status"] == "running"
        new_s0 = resumed["stages"][0]["job_id"]
        assert new_s0 and new_s0 != s0_job
        assert resumed["stages"][1]["status"] == "pending"

    def test_resume_rejects_a_non_failed_chain(self, tmp_path, monkeypatch):
        import asyncio

        routes_md = self._tp._routes_md(tmp_path, monkeypatch)
        parent = self._tp._ready_job(tmp_path)
        chain, _ = self._create_chain(routes_md, tmp_path, monkeypatch, parent)
        with pytest.raises(Exception) as exc:
            asyncio.run(routes_md.resume_md_chain(chain["chain_id"]))
        assert getattr(exc.value, "status_code", None) == 400

    def test_transient_spawn_failure_retries_then_halts(self, tmp_path, monkeypatch):
        """A spawn that keeps failing (e.g. the seed checkpoint hasn't downloaded yet)
        does NOT dead-end the chain on the first hiccup: the stage stays pending and
        retries for a bounded number of supervisor ticks, halting only past the cap —
        so a transient issue self-heals but a permanent one still eventually fails."""
        import asyncio

        routes_md = self._tp._routes_md(tmp_path, monkeypatch)
        parent = self._tp._ready_job(tmp_path)

        async def _boom(ctx):
            raise RuntimeError("seed checkpoint not on disk yet")

        monkeypatch.setattr(routes_md, "_chain_spawn", _boom)
        monkeypatch.setattr(routes_md, "_assert_md_job_current", lambda job: None)
        body = routes_md.CreateChainRequest(
            root_job_id=parent.job_id,
            root_engine="namd",
            stages=[routes_md.ChainStageRequest(engine="namd", length_ns=1.0)],
        )
        result = asyncio.run(routes_md.create_md_chain(body))  # attempt 1
        chain_id = result["chain"]["chain_id"]

        # After the first failed attempt the chain is NOT terminal — stage stays pending.
        assert result["chain"]["status"] != "failed"
        assert result["chain"]["stages"][0]["status"] == "pending"
        assert result["chain"]["stages"][0]["spawn_attempts"] == 1

        # Two more supervisor ticks reach the cap (3) → the chain halts, resumable.
        asyncio.run(routes_md.advance_chains(tmp_path))  # attempt 2 (still pending)
        mid = asyncio.run(routes_md.get_md_chain(chain_id))["chain"]
        assert mid["status"] != "failed" and mid["stages"][0]["spawn_attempts"] == 2

        asyncio.run(routes_md.advance_chains(tmp_path))  # attempt 3 → halt
        halted = asyncio.run(routes_md.get_md_chain(chain_id))["chain"]
        assert halted["status"] == "failed"
        assert halted["stages"][0]["status"] == "failed"
        assert halted["stages"][0]["spawn_attempts"] == 3

        # A manual resume grants a fresh retry budget (attempts reset to 0 pre-retry).
        resumed = asyncio.run(routes_md.resume_md_chain(chain_id))[
            "chain"
        ]  # attempt 1 again
        assert resumed["stages"][0]["spawn_attempts"] == 1
        assert resumed["status"] != "failed"


class TestMdCrossEngineChain:
    """P3 oracle — cross-engine coordinate handoff through the chain executor.

    Bright line (Track P = CHAIN): a stage runs SEEDED from the previous engine's relaxed
    frame — an oxDNA/mrDNA root hands its coordinates to a NAMD stage 0 via the
    create-time seed converter (``build_namd_seed`` — parity with launching a seeded NAMD
    job by hand), NOT the same-engine ``.coor/.xsc`` checkpoint restart.  A same-engine hop
    keeps the checkpoint path.  On a stage failure the chain HALTS and resumes from the
    failed stage.  The engine callbacks are stubbed (no real solvation / NAMD); the
    branching + seeding LOGIC is what's pinned."""

    _tp = TestProductionAppend()

    def _ctx(
        self,
        routes_md,
        *,
        root_engine,
        stage_engine,
        parent_job_id,
        forces=None,
        protocol="production",
    ):
        """A real ``SpawnContext`` for stage 0 of a one-stage chain (via the P1 builder).

        ``protocol`` defaults to ``"production"`` to mirror ``ChainStageRequest``'s real
        default (the cross-engine create path must tolerate it)."""
        from backend.core import md_chain_executor as chain
        from backend.core.md_pipeline import MdPipeline, PipelineStage

        pipe = MdPipeline(
            root_job_id="root",
            root_engine=root_engine,
            stages=[
                PipelineStage(engine=stage_engine, protocol=protocol, **(forces or {}))
            ],
        )
        run = chain.init_chain_run(pipe, chain_id="c", root_checkpoint="cp")
        run.root_job_id = parent_job_id  # the resolved predecessor for stage 0
        return chain.next_spawn(run)

    def test_chain_spawn_cross_engine_uses_the_seed_create_path(
        self, tmp_path, monkeypatch
    ):
        """oxDNA->NAMD stage: reconstruct via ``create_md_job(oxdna_job_id=root)`` (the
        converter), carrying the stage's field/anchors — NOT ``spawn_md_production``."""
        import asyncio

        routes_md = self._tp._routes_md(tmp_path, monkeypatch)
        calls: dict = {}

        async def _fake_create(body):
            calls["create"] = body
            return {"job_id": "namd-child"}

        async def _fake_prod(parent_id, body):
            calls["prod"] = (parent_id, body)
            return {"job": {"job_id": "prod-child"}}

        monkeypatch.setattr(routes_md, "create_md_job", _fake_create)
        monkeypatch.setattr(routes_md, "spawn_md_production", _fake_prod)

        ctx = self._ctx(
            routes_md,
            root_engine="oxdna",
            stage_engine="namd",
            parent_job_id="ox-root",
            forces={
                "field": {"field_pN": 5.0, "dir": [1, 0, 0]},
                "anchors": [{"scope": "base", "helix": 0, "bp": 0}],
            },
        )
        job_id = asyncio.run(routes_md._chain_spawn(ctx))

        assert job_id == "namd-child"
        assert "prod" not in calls  # checkpoint path NOT taken
        body = calls["create"]
        assert body.oxdna_job_id == "ox-root"  # the create-time seed hop kwarg
        assert body.mrdna_job_id is None
        assert body.field == {"field_pN": 5.0, "dir": [1, 0, 0]}
        assert body.anchors == [{"scope": "base", "helix": 0, "bp": 0}]
        assert body.execution_target == "local" and body.autostart is True

    def test_cross_engine_create_uses_a_valid_relaxation_protocol(
        self, tmp_path, monkeypatch
    ):
        """A pipeline stage's protocol defaults to "production", but the cross-engine hop
        goes through the RELAXATION-creation endpoint (``create_md_job`` rejects any protocol
        outside ``SUPPORTED_PROTOCOLS``).  The spawn must map "production" onto a valid
        relaxation preset, else every default oxDNA/mrDNA→NAMD stage 400s and the chain
        fails.  RED against forwarding ``plan.protocol`` verbatim."""
        import asyncio

        from backend.core.md_protocols import SUPPORTED_PROTOCOLS

        routes_md = self._tp._routes_md(tmp_path, monkeypatch)
        calls: dict = {}

        async def _fake_create(body):
            calls["create"] = body
            return {"job_id": "namd-child"}

        monkeypatch.setattr(routes_md, "create_md_job", _fake_create)
        # protocol="production" is ChainStageRequest's default — the failure case.
        ctx = self._ctx(
            routes_md,
            root_engine="oxdna",
            stage_engine="namd",
            parent_job_id="ox-root",
            protocol="production",
        )
        asyncio.run(routes_md._chain_spawn(ctx))
        assert calls["create"].protocol in SUPPORTED_PROTOCOLS

    def test_cross_engine_create_keeps_an_explicit_relaxation_protocol(
        self, tmp_path, monkeypatch
    ):
        """If a stage names a valid relaxation protocol, it's forwarded unchanged."""
        import asyncio

        routes_md = self._tp._routes_md(tmp_path, monkeypatch)
        calls: dict = {}

        async def _fake_create(body):
            calls["create"] = body
            return {"job_id": "namd-child"}

        monkeypatch.setattr(routes_md, "create_md_job", _fake_create)
        ctx = self._ctx(
            routes_md,
            root_engine="oxdna",
            stage_engine="namd",
            parent_job_id="ox-root",
            protocol="mgh_slow_release",
        )
        asyncio.run(routes_md._chain_spawn(ctx))
        assert calls["create"].protocol == "mgh_slow_release"

    def test_chain_spawn_mrdna_root_seeds_via_mrdna_job_id(self, tmp_path, monkeypatch):
        import asyncio

        routes_md = self._tp._routes_md(tmp_path, monkeypatch)
        calls: dict = {}

        async def _fake_create(body):
            calls["create"] = body
            return {"job_id": "namd-child"}

        monkeypatch.setattr(routes_md, "create_md_job", _fake_create)
        ctx = self._ctx(
            routes_md,
            root_engine="mrdna",
            stage_engine="namd",
            parent_job_id="mrdna-root",
        )
        asyncio.run(routes_md._chain_spawn(ctx))
        assert calls["create"].mrdna_job_id == "mrdna-root"
        assert calls["create"].oxdna_job_id is None

    def test_chain_spawn_same_engine_uses_the_checkpoint_path(
        self, tmp_path, monkeypatch
    ):
        """NAMD->NAMD stage: restart the predecessor checkpoint via ``spawn_md_production``,
        never the reconstruct path (a byte-for-byte no-regression of the P2 behaviour)."""
        import asyncio

        routes_md = self._tp._routes_md(tmp_path, monkeypatch)
        calls: dict = {}

        async def _fake_create(body):
            calls["create"] = body
            return {"job_id": "should-not-happen"}

        async def _fake_prod(parent_id, body):
            calls["prod"] = (parent_id, body)
            return {"job": {"job_id": "prod-child"}}

        monkeypatch.setattr(routes_md, "create_md_job", _fake_create)
        monkeypatch.setattr(routes_md, "spawn_md_production", _fake_prod)

        ctx = self._ctx(
            routes_md,
            root_engine="namd",
            stage_engine="namd",
            parent_job_id="namd-parent",
        )
        job_id = asyncio.run(routes_md._chain_spawn(ctx))
        assert job_id == "prod-child"
        assert "create" not in calls
        assert calls["prod"][0] == "namd-parent"

    def test_cross_engine_chain_seeds_stage0_from_root_then_chains_and_resumes(
        self, tmp_path, monkeypatch
    ):
        """End-to-end CHAIN through the real ``advance_chains`` -> ``_chain_spawn`` ->
        ``cross_engine_seed`` path (spawns stubbed): an oxDNA root seeds a NAMD stage 0 via
        the reconstruct path; a completed stage 0 chains a same-engine NAMD stage 1 via the
        checkpoint path; a failed stage 0 HALTS and resume re-runs it."""
        import asyncio

        import backend.core.oxdna_runner as oxr

        routes_md = self._tp._routes_md(tmp_path, monkeypatch)
        # Root oxDNA frame available (the launch-card precheck) — no real oxDNA job needed.
        monkeypatch.setattr(oxr, "assert_namd_seed_available", lambda job_id, ws: None)

        status: dict = {}
        created: list = []
        produced: list = []
        _n = {"i": 0}

        async def _fake_create(body):
            _n["i"] += 1
            jid = f"s0-{_n['i']}"
            created.append((jid, body.oxdna_job_id))
            status[jid] = "running"
            return {"job_id": jid}

        async def _fake_prod(parent_id, body):
            produced.append(parent_id)
            status["s1"] = "running"
            return {"job": {"job_id": "s1"}}

        monkeypatch.setattr(routes_md, "create_md_job", _fake_create)
        monkeypatch.setattr(routes_md, "spawn_md_production", _fake_prod)
        monkeypatch.setattr(
            routes_md, "_chain_job_status", lambda jid: status.get(jid, "running")
        )

        body = routes_md.CreateChainRequest(
            root_job_id="ox-root",
            root_engine="oxdna",
            stages=[
                routes_md.ChainStageRequest(engine="namd", length_ns=1.0),
                routes_md.ChainStageRequest(engine="namd", length_ns=1.0),
            ],
        )
        chain = asyncio.run(routes_md.create_md_chain(body))["chain"]
        chain_id = chain["chain_id"]

        # Stage 0 spawned through the cross-engine reconstruct path (seeded from the root).
        assert chain["stages"][0]["status"] == "running"
        assert created and created[0] == ("s0-1", "ox-root")
        assert produced == []  # stage 1 not yet
        s0 = chain["stages"][0]["job_id"]
        assert s0 == "s0-1"

        # Stage 0 completes -> stage 1 (NAMD->NAMD) chains via the checkpoint path off s0.
        status["s0-1"] = "completed"
        asyncio.run(routes_md.advance_chains(tmp_path))
        mid = asyncio.run(routes_md.get_md_chain(chain_id))["chain"]
        assert mid["stages"][0]["status"] == "done"
        assert mid["stages"][1]["status"] == "running"
        assert produced == ["s0-1"]  # seeded from the realised stage 0

        # Stage 1 completes -> the whole chain is completed.
        status["s1"] = "completed"
        asyncio.run(routes_md.advance_chains(tmp_path))
        done = asyncio.run(routes_md.get_md_chain(chain_id))["chain"]
        assert done["status"] == "completed"

    def test_cross_engine_chain_halts_on_stage0_failure_then_resumes(
        self, tmp_path, monkeypatch
    ):
        import asyncio

        import backend.core.oxdna_runner as oxr

        routes_md = self._tp._routes_md(tmp_path, monkeypatch)
        monkeypatch.setattr(oxr, "assert_namd_seed_available", lambda job_id, ws: None)

        status: dict = {}
        created: list = []
        _n = {"i": 0}

        async def _fake_create(body):
            _n["i"] += 1
            jid = f"s0-{_n['i']}"
            created.append(jid)
            status[jid] = "running"
            return {"job_id": jid}

        monkeypatch.setattr(routes_md, "create_md_job", _fake_create)
        monkeypatch.setattr(
            routes_md, "_chain_job_status", lambda jid: status.get(jid, "running")
        )

        body = routes_md.CreateChainRequest(
            root_job_id="ox-root",
            root_engine="oxdna",
            stages=[
                routes_md.ChainStageRequest(engine="namd", length_ns=1.0),
                routes_md.ChainStageRequest(engine="namd", length_ns=1.0),
            ],
        )
        chain = asyncio.run(routes_md.create_md_chain(body))["chain"]
        chain_id = chain["chain_id"]
        assert created == ["s0-1"]

        # Stage 0 fails -> the chain HALTS (no downstream spawn).
        status["s0-1"] = "failed"
        asyncio.run(routes_md.advance_chains(tmp_path))
        halted = asyncio.run(routes_md.get_md_chain(chain_id))["chain"]
        assert halted["status"] == "failed"
        assert halted["stages"][0]["status"] == "failed"
        assert halted["stages"][1]["status"] == "pending"

        # Resume re-runs ONLY stage 0 (a fresh reconstruct), stage 1 still pending.
        resumed = asyncio.run(routes_md.resume_md_chain(chain_id))["chain"]
        assert resumed["status"] == "running"
        assert resumed["stages"][0]["status"] == "running"
        assert created == ["s0-1", "s0-2"]  # cross-engine reconstruct re-ran
        assert resumed["stages"][1]["status"] == "pending"
