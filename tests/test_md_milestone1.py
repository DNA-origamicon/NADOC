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


# ── md_job ─────────────────────────────────────────────────────────────────────

class TestMdJob:
    def test_new_job_roundtrip(self, tmp_path: Path) -> None:
        from backend.core.md_job import MdJob, MdStatus, new_job

        job = new_job(
            design_name    = "B_tube",
            protocol       = "mgh_slow_release",
            name_stem      = "B_tube",
            package_subdir = "package/B_tube_namd_solvated",
            threads        = 16,
            devices        = "0",
        )
        assert job.status == MdStatus.queued
        assert len(job.job_id) == 12

        job.save(tmp_path)
        loaded = MdJob.load(job.job_id, tmp_path)
        assert loaded.job_id         == job.job_id
        assert loaded.design_name    == "B_tube"
        assert loaded.protocol       == "mgh_slow_release"
        assert loaded.name_stem      == "B_tube"
        assert loaded.package_subdir == "package/B_tube_namd_solvated"
        assert loaded.threads        == 16
        assert loaded.devices        == "0"
        assert loaded.status         == MdStatus.queued

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
        assert json.dumps(d)   # must be JSON-serializable
        assert d["status"] == "queued"

    def test_health_sample_roundtrip(self, tmp_path: Path) -> None:
        from backend.core.md_job import MdJob, MdHealthSample, new_job

        job = new_job("Z", "mgh_slow_release", "Z", "pkg")
        job.health_samples.append(MdHealthSample(
            wall_time              = time.time(),
            stage                  = "50K NVT k=5.0",
            segment                = "Z_01_050K_NVT_k5_p10",
            c1_paired_fraction     = 0.998,
            c1_mean_ang            = 9.5,
            c1_p90_ang             = 10.2,
            wc_ref_relative_fraction = 0.992,
            wc_mean_hbond_ang      = 3.1,
            passed                 = True,
        ))
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
        assert m.temperature_k   == pytest.approx(310.1234, rel=1e-4)
        assert m.temperature_avg_k == pytest.approx(310.0987, rel=1e-4)
        assert m.pressure_bar    == pytest.approx(1.0100,   rel=1e-3)
        assert m.gpressure_bar   == pytest.approx(1.0050,   rel=1e-3)
        assert m.pressure_avg_bar == pytest.approx(1.0050,  rel=1e-3)
        assert m.gpressure_avg_bar == pytest.approx(1.0020, rel=1e-3)
        assert m.volume_ang3     == pytest.approx(1234500.0, rel=1e-4)
        assert m.timestep        == 200

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
        assert m.temperature_k  is None
        assert len(m.warnings)  > 0

    def test_empty_log(self, tmp_path: Path) -> None:
        from backend.core.namd_metrics import parse_namd_log

        log = tmp_path / "empty.log"
        log.write_text("")
        m = parse_namd_log(log)
        assert m.n_energy_lines == 0
        assert m.temperature_k  is None

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

    def test_every_stage_has_three_segments(self) -> None:
        from backend.core.md_protocols import mgh_slow_release_segments

        _, segments = mgh_slow_release_segments("X")
        from collections import Counter
        stage_counts = Counter(s.stage for s in segments)
        for stage, count in stage_counts.items():
            assert count == 3, f"Stage {stage!r} has {count} segments, expected 3"

    def test_percentages_are_10_50_100(self) -> None:
        from backend.core.md_protocols import mgh_slow_release_segments

        _, segments = mgh_slow_release_segments("X")
        from collections import Counter
        pct_counts = Counter(int(s.percent) for s in segments)
        assert pct_counts[10]  == pct_counts[50] == pct_counts[100]

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
        npt_segs  = [s for s in segments if s.npt]
        nvt_segs  = [s for s in segments if not s.npt]
        assert len(npt_segs) > 0
        assert len(nvt_segs) == 0
        # Aksimentiev-style default relax runs NPT at 300 K.
        for s in npt_segs:
            assert s.temp == pytest.approx(300.0)

    def test_default_segments_use_long_aksimentiev_enm_stages(self) -> None:
        from backend.core.md_protocols import mgh_slow_release_segments

        _, segments = mgh_slow_release_segments("X")
        stage_totals: dict[str, int] = {}
        for s in segments:
            stage_totals[s.stage] = stage_totals.get(s.stage, 0) + s.steps
        assert set(stage_totals.values()) == {2_400_000}
        assert any(s.extra_bonds_file == "X_k0.5.enm.extra" for s in segments)
        assert all(not s.reinit for s in segments)
        assert all(s.steps % 12 == 0 for s in segments)

    def test_minimize_steps_round_up_to_stepspercycle(self) -> None:
        from backend.core.md_protocols import _round_up_to_cycle

        assert _round_up_to_cycle(4_800) == 4_800
        assert _round_up_to_cycle(10_000) == 10_008

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
        spec = segs[0]
        with_extra = _segment_conf(spec, "S", (100.0, 90.0, 80.0), mgh_extrabonds=True)
        without    = _segment_conf(spec, "S", (100.0, 90.0, 80.0), mgh_extrabonds=False)
        assert "extraBondsFile     mgh_extrabonds.txt" in with_extra
        assert "extraBondsFile     mgh_extrabonds.txt" not in without
        assert "extraBondsFile     S_k0.5.enm.extra" in without

    def test_enm_extrabonds_on_for_restrained_stage(self) -> None:
        from backend.core.md_protocols import _segment_conf, mgh_slow_release_segments

        _, segs = mgh_slow_release_segments("S")
        spec = segs[0]   # first ENM stage — k=0.5
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

        async def _run_in_threadpool(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        fastapi = types.ModuleType("fastapi")
        fastapi.APIRouter = _Router
        fastapi.BackgroundTasks = object
        fastapi.HTTPException = _HTTPException
        fastapi.Request = object
        concurrency = types.ModuleType("fastapi.concurrency")
        concurrency.run_in_threadpool = _run_in_threadpool
        assembly = types.ModuleType("backend.api.assembly")
        assembly._WORKSPACE_DIR = tmp_path

        monkeypatch.setitem(sys.modules, "fastapi", fastapi)
        monkeypatch.setitem(sys.modules, "fastapi.concurrency", concurrency)
        monkeypatch.setitem(sys.modules, "backend.api.assembly", assembly)
        sys.modules.pop("backend.api.routes_md", None)

        import backend.api.routes_md as routes_md

        monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
        return routes_md

    def _ready_job(self, tmp_path: Path):
        from backend.core.md_job import MdHealthSample, MdSegmentStatus, MdStatus, new_job

        job = new_job(
            design_name="D",
            protocol="equilibrium_aware",
            name_stem="D",
            package_subdir="package/D_namd_solvated",
        )
        job.status = MdStatus.completed
        job.segments.append(MdSegmentStatus(
            name="D_16_310K_NPT_k0_qualification_p100",
            stage="310K NPT unrestrained qualification",
            percent=100.0,
            steps=1000,
            status="done",
        ))
        job.health_samples.append(MdHealthSample(
            wall_time=time.time(),
            stage="310K NPT unrestrained qualification",
            segment="D_16_310K_NPT_k0_qualification_p100",
            c1_paired_fraction=0.98,
            wc_ref_relative_fraction=0.77,
            passed=True,
        ))
        job.save(tmp_path)

        package_dir = job.package_dir(tmp_path)
        package_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "name_stem": "D",
            "box_ang": [100.0, 90.0, 80.0],
            "mgh_extrabonds": False,
            "minimization": {"name": "D_00_min_k5"},
            "segments": [{
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
            }],
        }
        text = json.dumps(manifest, indent=2)
        (package_dir / "manifest.json").write_text(text)
        (package_dir / "nadoc_md_run.json").write_text(text)
        output_dir = package_dir / "output"
        output_dir.mkdir()
        for ext in ("coor", "vel", "xsc"):
            (output_dir / f"D_16_310K_NPT_k0_qualification_p100.{ext}").write_text("restart\n")
        return job

    def test_steps_and_ns_use_conservative_one_fs_timestep(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        routes_md = self._routes_md(tmp_path, monkeypatch)

        steps, length_ns = routes_md._production_steps_and_ns(
            routes_md.ProductionRequest(length_ns=0.25)
        )

        assert steps == 250_000
        assert length_ns == pytest.approx(0.25)

    def test_appended_production_uses_conservative_unrestrained_settings(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        routes_md = self._routes_md(tmp_path, monkeypatch)
        job = self._ready_job(tmp_path)

        segments = routes_md._append_production_segments(job, 1000)

        assert [int(s.percent) for s in segments] == [10, 50, 100]
        assert all(s.min_wc_ref_relative == pytest.approx(0.25) for s in segments)
        assert all(s.damping == pytest.approx(1.0) for s in segments)
        assert all("conservative production" in s.stage for s in segments)

        package_dir = job.package_dir(tmp_path)
        conf = (package_dir / f"{segments[0].name}.conf").read_text()
        assert "timestep           1.0" in conf
        assert "rigidBonds         none" in conf
        assert "langevinDamping    1.0" in conf
        assert "PMEGridSpacing     1.0" in conf
        assert "cutoff             12.0" in conf
        assert "switchdist         10.0" in conf
        assert "pairlistdist       14.0" in conf

        manifest = json.loads((package_dir / "manifest.json").read_text())
        assert manifest["production_extension"]["timestep_fs"] == pytest.approx(1.0)
        assert manifest["production_extension"]["settings"] == "conservative_unrestrained"
        assert manifest["production_extension"]["health_gate"] == {
            "min_c1_paired": 0.90,
            "min_wc_ref_relative": 0.25,
        }
        assert manifest["production_extension"]["advisory_gate"] == {
            "wc_ref_relative": 0.75,
        }

    def _seeded_job(self, tmp_path: Path):
        """An oxDNA-seeded job whose package is built but NO relaxation has run
        (no completed segments, no restart files)."""
        from backend.core.md_job import MdStatus, new_job

        job = new_job(
            design_name="S", protocol="equilibrium_aware",
            name_stem="S", package_subdir="package/S_namd_solvated",
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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A seeded job with no relaxation checkpoint can NO LONGER produce directly
        from the seed (the minimize-then-unrestrained shortcut blew up).  It must run
        the restrained relaxation ladder first, so production 400s without a
        checkpoint — exactly like an unseeded job."""
        routes_md = self._routes_md(tmp_path, monkeypatch)
        assert routes_md._seed_production_available(self._seeded_job(tmp_path)) is False

        job = self._seeded_job(tmp_path)
        with pytest.raises(Exception) as exc:
            routes_md._append_production_segments(job, 1000)
        assert getattr(exc.value, "status_code", None) == 400

    def test_display_meta_seeded_job_not_production_ready_without_checkpoint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A NON-seeded job with no relaxation checkpoint must still 400 (no
        produce-from-seed shortcut)."""
        routes_md = self._routes_md(tmp_path, monkeypatch)
        job = self._seeded_job(tmp_path)
        job.seed_oxdna_job_id = None          # remove the seed provenance
        job.save(tmp_path)
        with pytest.raises(Exception) as exc:
            routes_md._append_production_segments(job, 1000)
        assert getattr(exc.value, "status_code", None) == 400


# ── namd_runner (pure helpers only) ──────────────────────────────────────────

class TestOrphanStop:
    """A NAMD run orphaned by a server restart (no in-memory runner thread) must still
    be stoppable from the UI: stop_job finds the detached PID and kills it."""

    def _running_job(self, tmp_path: Path):
        from backend.core.md_job import MdSegmentStatus, MdStatus, new_job
        job = new_job(design_name="S", protocol="equilibrium_aware",
                      name_stem="S", package_subdir="package/S")
        job.segments = [MdSegmentStatus(name="S_01", stage="x", percent=10, steps=100)]
        job.current_segment_idx = 0
        job.status = MdStatus.running
        job.save(tmp_path)
        return job

    def test_stop_orphan_kills_external_pid_and_marks_stopped(self, tmp_path, monkeypatch):
        from backend.core import namd_runner
        from backend.core.md_job import MdJob, MdStatus

        job = self._running_job(tmp_path)
        killed = []
        monkeypatch.setattr(namd_runner, "_external_pid", lambda j: 4242)
        monkeypatch.setattr(namd_runner, "_kill_process_group", lambda pid, **k: killed.append(pid))

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
        monkeypatch.setattr(namd_runner, "_external_pid", lambda j: None)   # /proc scan misses
        monkeypatch.setattr(namd_runner, "_pid_is_namd", lambda pid: True)  # but persisted PID is ours
        monkeypatch.setattr(namd_runner, "_kill_process_group", lambda pid, **k: killed.append(pid))

        assert namd_runner.stop_job(job.job_id, tmp_path) is True
        assert killed == [7777]

    def test_stop_no_orphan_returns_false_without_killing(self, tmp_path, monkeypatch):
        from backend.core import namd_runner

        job = self._running_job(tmp_path)
        killed = []
        monkeypatch.setattr(namd_runner, "_external_pid", lambda j: None)
        monkeypatch.setattr(namd_runner, "_kill_process_group", lambda pid, **k: killed.append(pid))
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

    def test_reconcile_completed_orphaned_segment(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

        monkeypatch.setattr(runner, "run_health_check", lambda *args, **kwargs: HealthCheckResult(
            passed=True,
            c1_paired_fraction=0.98,
            c1_mean_ang=9.7,
            c1_p90_ang=10.8,
            wc_ref_relative_fraction=0.74,
            wc_mean_hbond_ang=5.4,
        ))

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
        from backend.core.md_prep_progress import write_prep_progress, PREP_PROGRESS_FILENAME
        import backend.core.namd_runner as runner

        job = self._preparing_job(tmp_path)
        write_prep_progress(job.job_dir(tmp_path), {"phase": "solvate", "fraction": 0.3})
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
        write_prep_progress(job.job_dir(tmp_path), {"phase": "solvate", "fraction": 0.3})
        out = runner.reconcile_job_status(job, tmp_path)
        assert out.status == MdStatus.preparing  # live heartbeat → untouched
