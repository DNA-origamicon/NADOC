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
    assert (
        V.classify_failure_log(
            "ERROR: Constraint failure in RATTLE algorithm for atom 459556!"
        )
        == "instability"
    )
    assert (
        V.classify_failure_log("ERROR: Margin is too small for 1 atoms")
        == "instability"
    )
    assert (
        V.classify_failure_log(
            "FATAL ERROR: CUDA error cudaStreamSynchronize ... buildTileLists"
        )
        == "gpu_error"
    )
    assert V.classify_failure_log("MINIMIZER RESTARTING\nEnd of program") == "other"
    # OOM wins even though it is also a "CUDA error" line.
    assert V.classify_failure_log("CUDA error cudaMalloc: out of memory") == "vram_oom"
    # NPT equilibration outgrowing the patch grid — a self-healing, auto-resumable
    # fatal, distinct from an instability blow-up.
    assert (
        V.classify_failure_log(
            "FATAL ERROR: Periodic cell has become too small for original patch grid!"
        )
        == "cell_shrink"
    )
    # "Margin is too small" (a RATTLE blow-up) must NOT be mistaken for the cell
    # shrink — it stays an instability so it is not auto-resumed into a re-crash.
    assert (
        V.classify_failure_log("ERROR: Margin is too small for 1 atoms")
        == "instability"
    )


def test_classify_host_pinned_oom_not_vram():
    # A cudaHostAlloc failure is a *host* pinned-RAM OOM (bonded-CUDA tuple staging),
    # NOT device VRAM — it must not be routed to the water-shell downsize remedy.
    real = (
        "FATAL ERROR: CUDA error cudaHostAlloc(pp, sizeofT*(*curlen), flag) in file "
        "src/CudaUtils.C, function reallocate_host_T, line 208\n"
        " on Pe 2 (device 0): out of memory\n"
        "  [2:5] namd3 ComputeBondedCUDA::copyTupleDataSN()"
    )
    assert V.classify_failure_log(real) == "host_oom"
    assert V.classify_failure_log("cudaMallocHost failed: out of memory") == "host_oom"
    # A plain device cudaMalloc OOM stays vram_oom (the downsize path).
    assert V.classify_failure_log("CUDA error cudaMalloc: out of memory") == "vram_oom"


# ── Failure → UX description (Relax decision gates) ───────────────────────────


def test_describe_failure_tile_list_bug_offers_newer_binary():
    # The resident tile-list crash is the one a newer NAMD build fixes -> the ONLY
    # kind with retry_other_binary True; it's a decision (offer slower GPU), not a stop.
    log = (
        "TCL: Running for 2400 steps\n"
        "FATAL ERROR: CUDA error cudaStreamSynchronize(stream) in file "
        "src/CudaTileListKernel.cu, function buildTileLists, line 1141\n"
        " on Pe 8 device 0: an illegal memory access was encountered\n"
    )
    d = V.describe_failure(log)
    assert d.kind == V.FAILURE_GPU_ERROR
    assert d.severity == "decision"
    assert d.retry_other_binary is True
    assert d.degrade_target == "offload"
    assert "buildTileLists" in d.technical_reason  # raw cause kept for logs
    assert "buildTileLists" not in d.message  # never in the user message
    assert "GPUresident" not in d.message


def test_describe_failure_host_pinned_not_binary_fixable():
    # A pinned-host OOM is a HOST limit — a newer binary can't fix it, so it must NOT
    # advertise retry_other_binary, but it can still offer the slower GPU mode.
    log = (
        "FATAL ERROR: CUDA error cudaHostAlloc(pp, ...) in file src/CudaUtils.C, "
        "function reallocate_host_T, line 208\n on Pe 2 device 0: out of memory\n"
    )
    d = V.describe_failure(log)
    assert d.kind == V.FAILURE_HOST_OOM
    assert d.severity == "decision"
    assert d.retry_other_binary is False
    assert d.degrade_target == "offload"


def test_describe_failure_vram_oom_is_hard_stop():
    d = V.describe_failure("CUDA error cudaMalloc: out of memory")
    assert d.kind == V.FAILURE_VRAM_OOM
    assert d.severity == "hard_stop"
    assert d.degrade_target is None
    assert d.retry_other_binary is False


def test_describe_failure_instability_and_cellshrink_are_auto():
    # Both are handled by NADOC's auto-resume — info note, never a modal.
    assert (
        V.describe_failure("ERROR: Margin is too small for 1 atoms").severity == "auto"
    )
    assert (
        V.describe_failure("FATAL ERROR: Periodic cell has become too small").severity
        == "auto"
    )


def test_describe_failure_unknown_is_generic_decision():
    d = V.describe_failure("MINIMIZER RESTARTING\nEnd of program")
    assert d.kind == V.FAILURE_OTHER
    assert d.severity == "decision"


def test_describe_failure_file(tmp_path: Path):
    p = tmp_path / "seg.log"
    p.write_text("startup\nFATAL ERROR: CUDA error ... buildTileLists ...\n")
    assert V.describe_failure_file(p).kind == V.FAILURE_GPU_ERROR


# ── Pre-flight size gate (Gate A: A1 / A2 / A3) ───────────────────────────────


def test_classify_vram_fit_tiers():
    # full box fits -> no gate
    assert V.classify_vram_fit({"current_atoms": 100, "max_atoms": 200}) == "ok"
    # a comfortable (>=15 A) shell fits -> A1
    assert (
        V.classify_vram_fit(
            {
                "current_atoms": 2_000_000,
                "max_atoms": 1_000_000,
                "feasible": True,
                "recommended_shell_nm": 1.5,
            }
        )
        == "a1"
    )
    # only a tight (<15 A) shell fits -> A2
    assert (
        V.classify_vram_fit(
            {
                "current_atoms": 2_000_000,
                "max_atoms": 1_000_000,
                "feasible": True,
                "recommended_shell_nm": 1.0,
            }
        )
        == "a2"
    )
    # nothing fits -> A3 hard stop
    assert (
        V.classify_vram_fit(
            {"current_atoms": 5_000_000, "max_atoms": 1_000_000, "feasible": False}
        )
        == "a3"
    )


def test_classify_vram_fit_missing_data_never_gates():
    assert V.classify_vram_fit(None) == "ok"
    assert V.classify_vram_fit({}) == "ok"
    assert (
        V.classify_vram_fit({"current_atoms": 9, "max_atoms": 0}) == "ok"
    )  # unknown cap


def test_carve_fill_fraction_tight_vs_big_box():
    # A compact ~4 nm DNA blob; a shell carve fills a TIGHT box but leaves a BIG box
    # mostly vacuum. This is exactly the resident-capable-vs-not distinction.
    dna = [
        (x / 10, y / 10, z / 10)
        for x in range(0, 40, 4)
        for y in range(0, 40, 4)
        for z in range(0, 40, 4)
    ]
    assert V.carve_fill_fraction(dna, (5.0, 5.0, 5.0), 0.0) == 1.0  # no carve = full
    tight = V.carve_fill_fraction(dna, (5.5, 5.5, 5.5), 1.5)  # blob fills the box
    big = V.carve_fill_fraction(dna, (20.0, 20.0, 20.0), 1.5)  # blob lost in vacuum
    assert tight > 0.8  # well-filled → would attempt resident
    assert big < 0.3  # sparse → stays offload
    assert tight > big


def test_preflight_vram_advice_skips_when_gpu_unreadable(monkeypatch):
    monkeypatch.setattr(V, "detect_vram_mb", lambda *a, **k: None)
    out = V.preflight_vram_advice(object(), devices="0")
    assert out == {"skipped": True, "tier": "ok"}


def test_preflight_vram_advice_skips_cpu_without_host(monkeypatch):
    monkeypatch.setattr(V, "detect_host_ram_mb", lambda *a, **k: None)
    out = V.preflight_vram_advice(object(), devices="cpu")
    assert out["skipped"] is True and out["tier"] == "ok"


# ── Error-line extraction (frontend cause surfacing) ──────────────────────────


def test_extract_error_line_namd_fatal():
    log = (
        "Info: Startup phase 0\n"
        "Info: Configuring...\n"
        "FATAL ERROR: GPUresident not supported on regular multicore builds\n"
        "FATAL ERROR: GPUresident not supported on regular multicore builds\n"
    )
    assert V.extract_error_line(log) == (
        "FATAL ERROR: GPUresident not supported on regular multicore builds"
    )


def test_extract_error_line_prefers_fatal_over_generic_error():
    # A generic ERROR appears first, but the NAMD FATAL is the real cause.
    log = "ERROR: something benign earlier\nFATAL ERROR: the real cause\n"
    assert V.extract_error_line(log) == "FATAL ERROR: the real cause"


def test_extract_error_line_slurm_level():
    assert "TIME LIMIT" in V.extract_error_line(
        "slurmstepd: error: *** JOB 42 CANCELLED AT ... DUE TO TIME LIMIT ***"
    )
    assert (
        V.extract_error_line("/etc/profile: line 47: HISTCONTROL: unbound variable")
        == "/etc/profile: line 47: HISTCONTROL: unbound variable"
    )
    assert (
        "oom-kill"
        in V.extract_error_line(
            "slurmstepd: error: Detected 1 oom-kill event(s)"
        ).lower()
    )


def test_extract_error_line_none_when_clean():
    assert V.extract_error_line("Info: Benchmark 12 ns/day\nWallClock: 3.2\n") is None
    assert V.extract_error_line("") is None


def test_extract_error_line_from_file(tmp_path: Path):
    p = tmp_path / "seg.log"
    p.write_text("Info: run\nFATAL ERROR: Margin is too small\n")
    assert V.extract_error_line_from_file(p) == "FATAL ERROR: Margin is too small"
    assert V.extract_error_line_from_file(tmp_path / "missing.log") is None


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
        dna_xyz_nm=_dna_line(),
        box_nm=_BOX,
        full_water=_FULL_WATER,
        dna_atoms=60,
        ion_atoms=0,
        shell_nm=shell,
    )


def test_estimate_shrinks_with_shell():
    assert _est(2.0) > _est(1.5) > _est(1.0) > _est(0.8)


def _recommend(vram_mb):
    return V.recommend_downsize(
        dna_xyz_nm=_dna_line(),
        box_nm=_BOX,
        full_water=_FULL_WATER,
        dna_atoms=60,
        ion_atoms=0,
        vram_mb=vram_mb,
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
    (pkg / "charge_audit.json").write_text(
        json.dumps(
            {
                "ionization": {
                    "n_waters": 1000,
                    "n_na": 10,
                    "n_mg": 2,
                    "n_cl": 14,
                    "mg_hexahydrate": True,
                    "box_nm": [10.0, 10.0, 10.0],
                    "water_shell_nm": None,
                }
            }
        )
    )
    (pkg / "x.pdb").write_text(
        "CRYST1  100 100 100  90 90 90 P 1\n"
        "ATOM      1  P   DA  A   1       1.000   2.000   3.000  1.00  0.00      D\n"
        "ATOM      2  C5' DA  A   1       4.000   5.000   6.000  1.00  0.00      D\n"
        "HETATM    3  OH2 TIP3 W  1       9.000   9.000   9.000  1.00  0.00      W\n"
    )
    prof = V.package_solvation_profile(pkg, "x")
    assert prof["dna_atoms"] == 2  # stopped at HETATM
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
    job.prep_params = {
        "padding_nm": 1.2,
        "water_shell_nm": 0.0,
        "salt_mode": "screening",
    }
    job.save(tmp_path)

    loaded = MdJob.load(job.job_id, tmp_path)
    assert loaded.failure_kind == "vram_oom"
    assert loaded.prep_params["water_shell_nm"] == 0.0


def test_mdjob_load_defaults_missing_fix_fields(tmp_path: Path):
    """Jobs written before the fix feature load with None (no KeyError)."""
    from backend.core.md_job import MdJob

    jd = tmp_path / "md_jobs" / "old123"
    jd.mkdir(parents=True)
    (jd / "job.json").write_text(
        json.dumps(
            {
                "job_id": "old123",
                "design_name": "d",
                "protocol": "p",
                "status": "failed",
                "created_at": 1.0,
                "package_subdir": "",
                "name_stem": "",
            }
        )
    )
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
    assert out["shell_nm"] > 0.0  # a carve (or tightest) was chosen
    assert out["note"]  # with a human explanation


def test_auto_water_shell_no_vram_reading(monkeypatch):
    from tests.conftest import make_6hb_design

    monkeypatch.setattr(V, "detect_vram_mb", lambda devices="0": None)
    out = V.auto_water_shell(make_6hb_design(42))
    assert out["shell_nm"] == 0.0 and out["note"] is None  # leave user's choice alone


def test_auto_water_shell_cpu_sizes_to_host_ram_not_vram(monkeypatch):
    """Compute=CPU ('cpu') ignores VRAM entirely and sizes the carve to host RAM."""
    from tests.conftest import make_6hb_design

    # A GPU reading, if consulted, would be huge (no carve).  A tiny host RAM must
    # still force a carve → proves the CPU path uses host RAM, not VRAM.
    monkeypatch.setattr(V, "detect_vram_mb", lambda devices="0": 1_000_000)
    monkeypatch.setattr(V, "detect_host_ram_mb", lambda: 500)  # tiny host
    out = V.auto_water_shell(make_6hb_design(42), devices="cpu")
    assert out["vram_mb"] is None  # VRAM never consulted
    assert out["shell_nm"] > 0.0 and out["note"]  # carved to fit host RAM
    assert "host RAM" in out["note"]


def test_auto_water_shell_cpu_no_host_reading(monkeypatch):
    from tests.conftest import make_6hb_design

    monkeypatch.setattr(V, "detect_host_ram_mb", lambda: None)
    out = V.auto_water_shell(make_6hb_design(42), devices="cpu")
    assert out["shell_nm"] == 0.0 and out["note"] is None  # can't size → full box


def test_detect_host_ram_mb_reads_or_degrades():
    # On Linux this reads /proc/meminfo; anywhere else it returns None gracefully.
    mb = V.detect_host_ram_mb()
    assert mb is None or (isinstance(mb, int) and mb > 0)


def test_max_atoms_for_host_ram_monotonic():
    assert V.max_atoms_for_host_ram(2000) < V.max_atoms_for_host_ram(64000)
    assert V.max_atoms_for_host_ram(0) == 0


def test_recommend_downsize_honours_max_atoms_override():
    import numpy as np

    xyz = np.random.RandomState(0).rand(200, 3) * 8.0  # ~8 nm cube of DNA points
    common = dict(
        dna_xyz_nm=xyz,
        box_nm=(12.0, 12.0, 12.0),
        full_water=400_000,
        dna_atoms=6_000,
        ion_atoms=200,
        vram_mb=12288,
    )
    loose = V.recommend_downsize(**common)  # GPU budget only
    tight = V.recommend_downsize(**common, max_atoms=50_000)  # host-tightened
    assert tight["max_atoms"] == 50_000
    assert loose["max_atoms"] == V.max_atoms_for_vram(12288)
    # A tighter atom budget can never recommend a *larger* (less restrictive) shell.
    ls = loose.get("recommended_shell_nm") or loose.get("tightest_shell_nm")
    ts = tight.get("recommended_shell_nm") or tight.get("tightest_shell_nm")
    assert ts <= ls


def test_auto_water_shell_carves_when_host_ram_tight(monkeypatch):
    from tests.conftest import make_6hb_design

    # Huge GPU, but only a sliver of host RAM available → host is the binding cap.
    monkeypatch.setattr(V, "detect_vram_mb", lambda devices="0": 1_000_000)
    monkeypatch.setattr(V, "detect_host_ram_mb", lambda: 30)  # ~30 MB free
    out = V.auto_water_shell(make_6hb_design(42))
    assert out["shell_nm"] > 0.0
    assert out["note"] and "host RAM" in out["note"]  # names the real constraint


# ── External GPU-contention detection (pre-launch warning) ────────────────────


def _activity(procs, used=4000, total=12288, util=40):
    return {
        "used_mb": used,
        "total_mb": total,
        "free_mb": total - used,
        "util_pct": util,
        "processes": procs,
    }


def test_gpu_contention_flags_external_heavy_process():
    act = _activity([{"pid": 419257, "name": "namd3", "mem_mb": 2336}])
    out = V.gpu_contention_summary(act)
    assert out["available"] is True and out["busy"] is True
    assert out["processes"][0]["name"] == "namd3"
    assert "namd3" in out["message"] and "2,336 MB" in out["message"]


def test_gpu_contention_ignores_small_and_own_processes():
    act = _activity(
        [
            {"pid": 100, "name": "nxnode.bin", "mem_mb": 287},  # below threshold
            {"pid": 200, "name": "namd3", "mem_mb": 8000},  # our own job
        ]
    )
    out = V.gpu_contention_summary(act, own_pids={200})
    assert out["busy"] is False and out["processes"] == []


def test_gpu_contention_no_nvidia_smi():
    out = V.gpu_contention_summary(None)
    assert out["available"] is False and out["busy"] is False
