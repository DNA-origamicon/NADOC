"""VRAM failure detection + downsize recommendation (the "Fix" popup backend)."""

from __future__ import annotations

import json
from pathlib import Path

from backend.core import md_vram as V


# ── Failure detection ─────────────────────────────────────────────────────────

def test_log_indicates_oom():
    oom = (
        "Info: Finished startup\n"
        "FATAL ERROR: CUDA error cudaMalloc(pp, ...) in file src/CudaUtils.C, "
        "function reallocate_device_T, line 174\n on Pe 8 device 0: out of memory\n"
    )
    assert V.log_indicates_oom(oom)
    assert not V.log_indicates_oom("ENERGY: 0 ...\nMINIMIZER RESTARTING\n")


def test_log_file_indicates_oom(tmp_path: Path):
    p = tmp_path / "min.log"
    p.write_text("startup ...\nFATAL ERROR: ... : out of memory\n")
    assert V.log_file_indicates_oom(p)
    assert not V.log_file_indicates_oom(tmp_path / "missing.log")


def test_classify_failure_log_multikind():
    assert V.classify_failure_log("FATAL: cudaMalloc ... : out of memory") == "vram_oom"
    assert V.classify_failure_log(
        "ERROR: Constraint failure in RATTLE algorithm for atom 459556!") == "instability"
    assert V.classify_failure_log("ERROR: Margin is too small for 1 atoms") == "instability"
    assert V.classify_failure_log(
        "FATAL ERROR: CUDA error cudaStreamSynchronize ... buildTileLists") == "gpu_error"
    assert V.classify_failure_log("MINIMIZER RESTARTING\nEnd of program") == "other"
    # OOM wins even though it is also a "CUDA error" line.
    assert V.classify_failure_log("CUDA error cudaMalloc: out of memory") == "vram_oom"


# ── VRAM model ────────────────────────────────────────────────────────────────

def test_vram_model_monotonic_and_invertible():
    assert V.max_atoms_for_vram(24000) > V.max_atoms_for_vram(12000)
    # ~3 M atoms fit a 12 GB card (the 18hb ran; the 8.86 M VoltronCore did not)
    assert 2_500_000 < V.max_atoms_for_vram(12288) < 3_500_000
    # required VRAM round-trips above the raw estimate (headroom included)
    assert V.required_vram_mb(3_000_000) > V.estimate_vram_mb(3_000_000)


def test_first_device_id():
    assert V._first_device_id("0") == 0
    assert V._first_device_id("1,2") == 1
    assert V._first_device_id("") == 0


# ── Downsize recommendation ───────────────────────────────────────────────────

def _dna_line(n=60, spacing=0.34):
    """A thin DNA filament along x — most of a big box is empty bulk water."""
    return [(i * spacing, 0.0, 0.0) for i in range(n)]


_BOX = (20.0, 20.0, 20.0)
_FULL_WATER = int(20 * 20 * 20 * 33.0)


def _est(shell):
    return V.estimate_total_atoms(
        dna_xyz_nm=_dna_line(), box_nm=_BOX, full_water=_FULL_WATER,
        dna_atoms=60, ion_atoms=0, shell_nm=shell,
    )


def test_estimate_shrinks_with_shell():
    assert _est(2.0) > _est(1.5) > _est(1.0) > _est(0.8)


def _recommend(vram_mb):
    return V.recommend_downsize(
        dna_xyz_nm=_dna_line(), box_nm=_BOX, full_water=_FULL_WATER,
        dna_atoms=60, ion_atoms=0, vram_mb=vram_mb,
    )


def test_recommend_picks_largest_fitting_shell():
    # VRAM that fits the biggest shell → recommend the largest (least restrictive).
    vram = V.required_vram_mb(_est(2.0)) + 500
    r = _recommend(vram)
    assert r["feasible"] and r["recommended_shell_nm"] == 2.0
    assert r["estimated_atoms"] <= r["max_atoms"]


def test_recommend_steps_down_when_largest_does_not_fit():
    # Budget between the 1.5 nm and 2.0 nm estimates → recommend 1.5 nm.
    max_atoms = (_est(1.5) + _est(2.0)) // 2
    vram = int(max_atoms * 3300 / 0.85 / 1e6) + 1
    r = _recommend(vram)
    assert r["feasible"] and r["recommended_shell_nm"] == 1.5


def test_recommend_infeasible_for_tiny_card():
    r = _recommend(8)  # 8 MB — nothing fits
    assert not r["feasible"]
    assert r["tightest_shell_nm"] == min(V.CANDIDATE_SHELLS_NM)
    assert r["required_vram_mb"] > 8


# ── Package profile loader ────────────────────────────────────────────────────

def test_package_solvation_profile(tmp_path: Path):
    pkg = tmp_path
    (pkg / "charge_audit.json").write_text(json.dumps({"ionization": {
        "n_waters": 1000, "n_na": 10, "n_mg": 2, "n_cl": 14,
        "mg_hexahydrate": True, "box_nm": [10.0, 10.0, 10.0],
        "water_shell_nm": None,
    }}))
    (pkg / "x.pdb").write_text(
        "CRYST1  100 100 100  90 90 90 P 1\n"
        "ATOM      1  P   DA  A   1       1.000   2.000   3.000  1.00  0.00      D\n"
        "ATOM      2  C5' DA  A   1       4.000   5.000   6.000  1.00  0.00      D\n"
        "HETATM    3  OH2 TIP3 W  1       9.000   9.000   9.000  1.00  0.00      W\n"
    )
    prof = V.package_solvation_profile(pkg, "x")
    assert prof["dna_atoms"] == 2                 # stopped at HETATM
    assert prof["full_water"] == 1000
    assert prof["ion_atoms"] == 10 + 14 + 2 * 19  # MGH = 19 atoms each
    assert prof["box_nm"] == (10.0, 10.0, 10.0)
    assert prof["dna_xyz_nm"][0] == (0.1, 0.2, 0.3)  # Å → nm

    assert V.package_solvation_profile(tmp_path / "nope", "x") is None


# ── MdJob persists the new fix-related fields ─────────────────────────────────

def test_mdjob_failure_kind_and_prep_params_roundtrip(tmp_path: Path):
    from backend.core.md_job import MdJob, MdStatus, new_job

    job = new_job("d", "equilibrium_aware_namd", "", "", devices="0")
    job.status = MdStatus.failed
    job.failure_kind = "vram_oom"
    job.prep_params = {"padding_nm": 1.2, "water_shell_nm": 0.0, "salt_mode": "screening"}
    job.save(tmp_path)

    loaded = MdJob.load(job.job_id, tmp_path)
    assert loaded.failure_kind == "vram_oom"
    assert loaded.prep_params["water_shell_nm"] == 0.0


def test_mdjob_load_defaults_missing_fix_fields(tmp_path: Path):
    """Jobs written before the fix feature load with None (no KeyError)."""
    from backend.core.md_job import MdJob

    jd = tmp_path / "md_jobs" / "old123"
    jd.mkdir(parents=True)
    (jd / "job.json").write_text(json.dumps({
        "job_id": "old123", "design_name": "d", "protocol": "p",
        "status": "failed", "created_at": 1.0,
        "package_subdir": "", "name_stem": "",
    }))
    loaded = MdJob.load("old123", tmp_path)
    assert loaded.failure_kind is None
    assert loaded.prep_params is None


# ── Pre-flight auto-sizing (proactive, no GROMACS) ────────────────────────────

def test_estimate_profile_from_design():
    from tests.conftest import make_6hb_design

    prof = V.estimate_profile_from_design(make_6hb_design(42), padding_nm=1.2)
    assert prof["dna_atoms"] > 0
    assert len(prof["box_nm"]) == 3 and all(b > 0 for b in prof["box_nm"])
    assert prof["full_water"] > 0
    assert len(prof["dna_xyz_nm"]) == prof["dna_atoms"]


def test_auto_water_shell_skips_when_full_box_fits(monkeypatch):
    from tests.conftest import make_6hb_design

    monkeypatch.setattr(V, "detect_vram_mb", lambda devices="0": 1_000_000)  # huge card
    out = V.auto_water_shell(make_6hb_design(42))
    assert out["shell_nm"] == 0.0 and out["note"] is None and out["fits"] is True


def test_auto_water_shell_carves_when_too_small(monkeypatch):
    from tests.conftest import make_6hb_design

    monkeypatch.setattr(V, "detect_vram_mb", lambda devices="0": 40)  # tiny card
    out = V.auto_water_shell(make_6hb_design(42))
    assert out["shell_nm"] > 0.0          # a carve (or tightest) was chosen
    assert out["note"]                    # with a human explanation


def test_auto_water_shell_no_vram_reading(monkeypatch):
    from tests.conftest import make_6hb_design

    monkeypatch.setattr(V, "detect_vram_mb", lambda devices="0": None)
    out = V.auto_water_shell(make_6hb_design(42))
    assert out["shell_nm"] == 0.0 and out["note"] is None  # leave user's choice alone


# ── External GPU-contention detection (pre-launch warning) ────────────────────

def _activity(procs, used=4000, total=12288, util=40):
    return {"used_mb": used, "total_mb": total, "free_mb": total - used,
            "util_pct": util, "processes": procs}


def test_gpu_contention_flags_external_heavy_process():
    act = _activity([{"pid": 419257, "name": "namd3", "mem_mb": 2336}])
    out = V.gpu_contention_summary(act)
    assert out["available"] is True and out["busy"] is True
    assert out["processes"][0]["name"] == "namd3"
    assert "namd3" in out["message"] and "2,336 MB" in out["message"]


def test_gpu_contention_ignores_small_and_own_processes():
    act = _activity([
        {"pid": 100, "name": "nxnode.bin", "mem_mb": 287},   # below threshold
        {"pid": 200, "name": "namd3", "mem_mb": 8000},        # our own job
    ])
    out = V.gpu_contention_summary(act, own_pids={200})
    assert out["busy"] is False and out["processes"] == []


def test_gpu_contention_no_nvidia_smi():
    out = V.gpu_contention_summary(None)
    assert out["available"] is False and out["busy"] is False
