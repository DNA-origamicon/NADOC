"""Advanced-card Optimize policy (backend/core/md_optimize.py)."""

from __future__ import annotations

import pytest

from backend.core.md_optimize import (
    physical_cores,
    predict_ns_per_day,
)


class TestThroughputModel:
    def test_reproduces_the_two_real_benchmarks(self) -> None:
        """The model is anchored on real 2080-Super runs; it must return them."""
        # full solvation + GPU-resident: measured 12.8 ns/day @ 747,262 atoms
        assert predict_ns_per_day(747_262, gpu_resident=True) == pytest.approx(
            12.8, rel=0.02
        )
        # 12 A carve + CUDA offload: measured 18.8 ns/day @ 196,606 atoms
        assert predict_ns_per_day(196_606, gpu_resident=False) == pytest.approx(
            18.8, rel=0.02
        )

    def test_throughput_falls_with_atom_count(self) -> None:
        assert predict_ns_per_day(100_000, gpu_resident=True) > predict_ns_per_day(
            400_000, gpu_resident=True
        )

    def test_gpu_resident_is_faster_per_atom(self) -> None:
        n = 300_000
        assert predict_ns_per_day(n, gpu_resident=True) > predict_ns_per_day(
            n, gpu_resident=False
        )

    def test_cpu_is_far_slower_than_gpu(self) -> None:
        n = 200_000
        assert predict_ns_per_day(
            n, gpu_resident=False, gpu=False
        ) < predict_ns_per_day(n, gpu_resident=False, gpu=True)

    def test_zero_atoms_does_not_divide_by_zero(self) -> None:
        assert predict_ns_per_day(0, gpu_resident=True) == 0.0


def test_physical_cores_is_at_least_one() -> None:
    assert physical_cores() >= 1


class TestResidentIsSizeAware:
    """GPU-resident's advantage is not scale-free — the optimiser must stop promising it.

    The throughput model had a single K per path, so resident always looked 2.6x better
    per atom.  Measured on an RTX 3080 Ti (offload -> resident ms/step): 32.5k
    1.116->1.266 (a LOSS), 111k 1.749->1.544, 770k 32.10->16.16, 3.14M 125.6->39.0.
    """

    def test_resident_is_not_predicted_faster_below_the_crossover(self) -> None:
        from backend.core.md_optimize import predict_ns_per_day

        n = 32_566
        assert predict_ns_per_day(n, gpu_resident=True) < predict_ns_per_day(
            n, gpu_resident=False
        )

    def test_resident_is_predicted_faster_well_above_it(self) -> None:
        from backend.core.md_optimize import predict_ns_per_day

        n = 3_139_238
        assert predict_ns_per_day(n, gpu_resident=True) > predict_ns_per_day(
            n, gpu_resident=False
        )

    def test_gpu_resident_pays_tracks_the_measured_crossover(self) -> None:
        from backend.core.md_optimize import _RESIDENT_MIN_ATOMS, gpu_resident_pays

        assert gpu_resident_pays(_RESIDENT_MIN_ATOMS)
        assert not gpu_resident_pays(_RESIDENT_MIN_ATOMS - 1)
        assert not gpu_resident_pays(32_566)
        assert gpu_resident_pays(3_139_238)

class TestGpuResidentModeOverride:
    """The Advanced-card dropdown: 'auto' uses the size gate, 'on'/'off' override it —
    but neither can defeat a HARD incompatibility (GBIS, sparse carved cell)."""

    def _soft_conf(self, **kw):
        from backend.core import md_protocols as M

        _min, segs = M.mgh_slow_release_segments("S", soft=True)
        soft = next(s for s in segs if s.soft)
        return M._segment_conf(soft, "S", (80.0, 80.0, 200.0), True, fast=False, **kw)

    def test_auto_uses_the_size_gate(self) -> None:
        assert "GPUresident" not in self._soft_conf(n_atoms=32_566, force_resident=None)
        assert "GPUresident        on" in self._soft_conf(
            n_atoms=3_139_238, force_resident=None
        )

    def test_on_forces_resident_on_a_small_system(self) -> None:
        assert "GPUresident        on" in self._soft_conf(
            n_atoms=32_566, force_resident=True
        )

    def test_off_forces_offload_on_a_large_system(self) -> None:
        assert "GPUresident" not in self._soft_conf(
            n_atoms=3_139_238, force_resident=False
        )

    def test_forcing_on_cannot_defeat_a_sparse_carve(self) -> None:
        """Not a speed question — resident aborts at step 0 on the exclusion count."""
        assert "GPUresident" not in self._soft_conf(
            n_atoms=3_139_238, force_resident=True, carved=True, fill_fraction=0.30
        )

    def test_forcing_on_cannot_defeat_gbis(self) -> None:
        assert "GPUresident" not in self._soft_conf(
            n_atoms=3_139_238, force_resident=True, gbis=True
        )
