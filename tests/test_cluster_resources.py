"""Unit tests for backend/core/cluster_resources.py — pure, offline."""

from __future__ import annotations

import json

import pytest

from backend.core import cluster_config as cc
from backend.core import cluster_resources as cr


@pytest.fixture
def alpine():
    return cc.alpine_profile()


# ── recommend: partition / GPU vs CPU ─────────────────────────────────────────

def test_recommend_defaults_to_gpu_ah200(alpine):
    # Default moved aa100 -> ah200 on 2026-08-06: live `sbatch --test-only` put an
    # aa100 start 13 d out (630 jobs pending) against an immediate ah200 start.
    r = cr.recommend(alpine, n_atoms=178_518, total_ns=10.0)
    assert r["partition"] == "ah200"
    assert r["kind"] == "gpu"
    assert r["gpus"] == 1
    assert r["cores"] == cr._GPU_CORES


def test_recommend_falls_back_to_cpu_when_too_big(alpine):
    # Ceiling is per-partition now — the default ah200 has 141 GB, so the fallback
    # trips well above the old A100-derived number.
    r = cr.recommend(alpine, n_atoms=cr.gpu_atom_ceiling("ah200") + 1, total_ns=5.0)
    assert r["kind"] == "cpu"
    assert r["gpus"] == 0
    assert r["partition"] == "acpu"
    assert any("exceeds the single-GPU ceiling" in n for n in r["notes"])


# ── walltime + QoS clamping ───────────────────────────────────────────────────

def test_short_run_stays_in_normal_qos(alpine):
    # GPU partition (default aa100) → gpu-* QoS names (SLURM rejects plain names there).
    r = cr.recommend(alpine, n_atoms=50_000, total_ns=2.0, measured_ns_per_day=50.0)
    assert r["kind"] == "gpu"
    assert r["qos"] == "gpu-normal"
    assert r["walltime_h"] <= 24


def test_long_run_bumps_to_long_qos(alpine):
    # 300 ns at 20 ns/day = 15 days * 1.5 safety ≈ 540 h → well past 24 h 'normal'.
    r = cr.recommend(alpine, n_atoms=200_000, total_ns=300.0, measured_ns_per_day=20.0)
    assert r["qos"] == "gpu-long"
    assert any("bumped to 'gpu-long'" in n for n in r["notes"])


def test_cpu_fallback_uses_cpu_namespaced_qos_names(alpine):
    # A system past the single-GPU ceiling falls back to acpu -> cpu-* QoS.
    r = cr.recommend(alpine, n_atoms=8_000_000, total_ns=2.0, measured_ns_per_day=50.0)
    assert r["kind"] == "cpu"
    assert r["partition"] == "acpu"
    assert r["qos"] == "cpu-normal"


def test_forced_acpu_partition_derives_cpu_resources(alpine):
    # A small system would auto-pick the GPU aa100; forcing acpu (fast-queue CPU
    # validation) must flip kind/gpus/qos/gres consistently — no GPU leftovers.
    r = cr.recommend(alpine, n_atoms=178_518, total_ns=2.0, partition="acpu")
    assert r["partition"] == "acpu"
    assert r["kind"] == "cpu"
    assert r["gpus"] == 0
    assert r["gres_type"] == ""
    assert r["qos"] in ("cpu-normal", "cpu-long")  # cpu-* QoS, never gpu-*
    assert not r["qos"].startswith("gpu-")
    assert any("manually set to acpu" in n for n in r["notes"])


def test_forced_gpu_partition_keeps_gpu_resources(alpine):
    r = cr.recommend(alpine, n_atoms=100_000, total_ns=5.0, partition="aa100")
    assert r["kind"] == "gpu"
    assert r["gpus"] == 1
    assert r["gres_type"] == "a100-40gb"
    assert r["qos"].startswith("gpu-")


def test_forced_unknown_partition_raises(alpine):
    with pytest.raises(ValueError, match="not in profile"):
        cr.recommend(alpine, n_atoms=100_000, total_ns=5.0, partition="nope")


def test_walltime_clamped_to_long_ceiling(alpine):
    # Absurdly long → clamp to 168 h and warn about resubmit.
    r = cr.recommend(alpine, n_atoms=200_000, total_ns=100_000.0, measured_ns_per_day=10.0)
    assert r["walltime_h"] == 168.0
    assert any("auto-resubmit" in n for n in r["notes"])


def test_walltime_format_is_hhmmss(alpine):
    r = cr.recommend(alpine, n_atoms=50_000, total_ns=2.0, measured_ns_per_day=50.0)
    hh, mm, ss = r["walltime"].split(":")
    assert len(hh) == 2 and len(mm) == 2 and len(ss) == 2
    assert 0 <= int(mm) < 60 and 0 <= int(ss) < 60


def test_measured_throughput_beats_guess(alpine):
    guessed = cr.recommend(alpine, n_atoms=100_000, total_ns=10.0)
    measured = cr.recommend(alpine, n_atoms=100_000, total_ns=10.0, measured_ns_per_day=99.0)
    assert not guessed["measured"]
    assert measured["measured"]
    assert measured["expected_ns_per_day"] == pytest.approx(99.0)
    # A faster measured throughput → a shorter walltime than the size guess.
    assert measured["walltime_h"] < guessed["walltime_h"]


# ── memory + cost + queue ─────────────────────────────────────────────────────

def test_mem_scales_with_atoms_and_has_floor(alpine):
    small = cr.recommend(alpine, n_atoms=1_000, total_ns=1.0, measured_ns_per_day=50.0)
    big = cr.recommend(alpine, n_atoms=500_000, total_ns=1.0, measured_ns_per_day=50.0)
    assert small["mem_gb"] >= 4
    assert big["mem_gb"] > small["mem_gb"]


def test_cost_uses_gpu_billing(alpine):
    r = cr.recommend(alpine, n_atoms=100_000, total_ns=10.0, measured_ns_per_day=50.0,
                     partition="aa100")
    hours = r["walltime_h"]
    expected = r["cores"] * hours * 1.0 + r["gpus"] * hours * 108.2
    assert r["est_cost_su"] == pytest.approx(round(expected, 1))


def test_estimate_queue_time_known_and_unknown():
    assert cr.estimate_queue_time_min("aa100") == 240
    assert cr.estimate_queue_time_min("who_knows") == 60


# ── manifest / metrics extractors ─────────────────────────────────────────────

def _mini_manifest():
    return {
        "name_stem": "demo",
        "relax_protocol_settings": {"timestep_fs": 2.0},
        "charge_audit": {"final_solvated": {"n_atoms": 178_518}},
        "minimization": {"name": "demo_00_min"},
        "segments": [
            {"name": "demo_01_p100", "steps": 1_000_000},
            {"name": "demo_02_p100", "steps": 500_000},
        ],
    }


def test_n_atoms_from_manifest_prefers_solvated():
    assert cr.n_atoms_from_manifest(_mini_manifest()) == 178_518


def test_n_atoms_from_manifest_falls_back_to_dry():
    m = {"charge_audit": {"dry_dna": {"n_atoms": 20_797}}}
    assert cr.n_atoms_from_manifest(m) == 20_797


def test_total_ns_from_manifest_excludes_minimization():
    # 1.5e6 steps * 2 fs = 3.0 ns.
    assert cr.total_ns_from_manifest(_mini_manifest()) == pytest.approx(3.0)


def test_total_ns_includes_production_extension():
    m = _mini_manifest()
    m["production_extension"] = {"length_ns": 50.0}
    assert cr.total_ns_from_manifest(m) == pytest.approx(53.0)


def test_latest_ns_per_day_reads_last_value(tmp_path):
    p = tmp_path / "metrics.jsonl"
    p.write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {"ns_per_day": 12.0},
                {"ns_per_day": None},
                {"ns_per_day": 16.5},
            ]
        )
    )
    assert cr.latest_ns_per_day(p) == pytest.approx(16.5)


def test_latest_ns_per_day_missing_file(tmp_path):
    assert cr.latest_ns_per_day(tmp_path / "nope.jsonl") is None


# ── 2026 GPU expansion: per-partition speed + billing ─────────────────────────

def test_faster_gpu_gets_a_shorter_walltime(alpine):
    """Walltime is derived from throughput, and throughput was A100-anchored.  An
    H200 job that asks for 2.5x the walltime it needs gets worse queue priority for
    no reason — so the partition's speed factor must reach the walltime."""
    a100 = cr.recommend(alpine, n_atoms=180_000, total_ns=100.0, partition="aa100")
    h200 = cr.recommend(alpine, n_atoms=180_000, total_ns=100.0, partition="ah200")
    assert h200["expected_ns_per_day"] > a100["expected_ns_per_day"]
    assert h200["walltime_h"] < a100["walltime_h"]
    assert h200["partition"] == "ah200" and h200["gres_type"] == "h200"


def test_measured_throughput_still_overrides_the_speed_factor(alpine):
    """A real measured ns/day is ground truth — the guess multiplier must not
    re-scale it."""
    r = cr.recommend(alpine, n_atoms=180_000, total_ns=10.0,
                     measured_ns_per_day=40.0, partition="ah200")
    assert r["expected_ns_per_day"] == pytest.approx(40.0)
    assert r["measured"] is True


def test_new_partitions_use_their_own_su_rate(alpine):
    """Same job, same hours → the H200 must cost more per GPU-hour than the A100."""
    per_hour_a100 = cr.estimate_cost_su(8, 1, 1.0, alpine, alpine.partition("aa100"))
    per_hour_h200 = cr.estimate_cost_su(8, 1, 1.0, alpine, alpine.partition("ah200"))
    assert per_hour_h200 > per_hour_a100
    # Omitting the partition falls back to the profile-wide (A100) rate.
    assert cr.estimate_cost_su(8, 1, 1.0, alpine) == pytest.approx(per_hour_a100)


def test_recommend_costs_against_the_chosen_partition(alpine):
    r = cr.recommend(alpine, n_atoms=180_000, total_ns=10.0,
                     measured_ns_per_day=20.0, partition="ah200")
    expected = cr.estimate_cost_su(
        r["cores"], r["gpus"], r["walltime_h"], alpine, alpine.partition("ah200"),
    )
    assert r["est_cost_su"] == pytest.approx(round(expected, 1))


def test_new_partitions_bump_to_gpu_long_not_gpu_testing(alpine):
    """ah200 has no gpu-testing QoS; a long run must land on gpu-long."""
    r = cr.recommend(alpine, n_atoms=180_000, total_ns=500.0,
                     measured_ns_per_day=5.0, partition="ah200")
    assert r["qos"] == "gpu-long"


def test_gpu_speed_factor_defaults_to_one_for_unknown_partitions():
    assert cr.gpu_speed_factor("aa100") == 1.0
    assert cr.gpu_speed_factor("ah200") > 1.0
    assert cr.gpu_speed_factor("something-new") == 1.0
    assert cr.gpu_speed_factor(None) == 1.0


def test_big_vram_partitions_raise_the_cpu_fallback_ceiling():
    assert cr.gpu_atom_ceiling("ah200") > cr.gpu_atom_ceiling("aa100")
    assert cr.gpu_atom_ceiling("aa100") == cr._GPU_ATOM_CEILING
