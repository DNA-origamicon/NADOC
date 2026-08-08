"""Unit tests for the pure engine-selection policy (backend/core/engine_policy)."""

from __future__ import annotations

import pytest

from backend.core.engine_policy import cpu_slowdown_factor, recommend_engine


# ── cpu_slowdown_factor ───────────────────────────────────────────────────────


def test_slowdown_at_anchors():
    assert cpu_slowdown_factor(1328) == pytest.approx(13.0)
    assert cpu_slowdown_factor(14172) == pytest.approx(47.0)


def test_slowdown_clamps_outside_anchors():
    assert cpu_slowdown_factor(1) == pytest.approx(13.0)  # tiny → floor
    assert cpu_slowdown_factor(0) == pytest.approx(13.0)
    assert cpu_slowdown_factor(500_000) == pytest.approx(47.0)  # huge → ceiling


def test_slowdown_monotonic_between_anchors():
    mid = cpu_slowdown_factor((1328 + 14172) // 2)
    assert 13.0 < mid < 47.0
    assert cpu_slowdown_factor(3000) < cpu_slowdown_factor(10000)


# ── recommend_engine ──────────────────────────────────────────────────────────


def test_no_protein_gpu_free_picks_oxdna_cuda():
    r = recommend_engine(
        has_proteins=False, gpu_busy=False, n_nucleotides=1328, free_cores=16
    )
    assert r["engine"] == "oxdna" and r["backend"] == "CUDA"
    assert r["needs_dialog"] is False


def test_no_protein_gpu_busy_picks_lammps_cpu_with_factor():
    r = recommend_engine(
        has_proteins=False,
        gpu_busy=True,
        gpu_hog_name="namd3",
        n_nucleotides=14172,
        free_cores=12,
    )
    assert r["engine"] == "lammps" and r["backend"] == "CPU"
    assert r["needs_dialog"] is True
    assert "47" in r["reason"] and "namd3" in r["reason"]
    assert r["cpu_slowdown_factor"] == pytest.approx(47.0)


def test_proteins_force_oxdna_even_when_gpu_busy():
    r = recommend_engine(
        has_proteins=True,
        gpu_busy=True,
        gpu_hog_name="namd3",
        n_nucleotides=5000,
        free_cores=8,
    )
    assert r["engine"] == "oxdna" and r["backend"] == "CUDA"
    assert r["needs_dialog"] is True  # busy → surface the dialog
    assert "rotein" in r["reason"]


def test_proteins_gpu_free_no_dialog():
    r = recommend_engine(
        has_proteins=True, gpu_busy=False, n_nucleotides=5000, free_cores=8
    )
    assert r["engine"] == "oxdna" and r["needs_dialog"] is False
