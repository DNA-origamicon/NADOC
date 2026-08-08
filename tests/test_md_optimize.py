"""Advanced-card ⚡ Optimize policy (backend/core/md_optimize.py).

The rule under test is the one that cost a real run 40 minutes before it was found:
a water-shell carve and NAMD's GPU-resident mode are mutually exclusive, so a carve is
a TRADE (fewer atoms, but the slower integrator) that only pays off when it removes
more than ~2.6x the atoms.  See memory/project_water_shell_carve.md.
"""

from __future__ import annotations

import pytest

from backend.core.md_optimize import (
    CARVE_BREAKEVEN,
    DEFAULT_SHELL_NM,
    K_GPU_RESIDENT,
    K_OFFLOAD,
    MIN_SHELL_NM,
    choose_water_shell,
    physical_cores,
    predict_ns_per_day,
)


class TestThroughputModel:
    def test_breakeven_is_the_ratio_of_the_two_measured_constants(self) -> None:
        assert CARVE_BREAKEVEN == pytest.approx(K_GPU_RESIDENT / K_OFFLOAD)
        # ~2.6x — GPU-resident is that much faster per atom than CUDA offload.
        assert 2.0 < CARVE_BREAKEVEN < 3.5

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


class TestChooseWaterShell:
    """shell_atoms maps candidate shell (nm) -> estimated total atoms."""

    def test_concave_design_carves_and_loses_gpu_resident(self) -> None:
        # A bent bundle: the 12 A shell removes 3.5x the atoms — above break-even.
        shell, gpu_res, why = choose_water_shell(
            full_atoms=712_370,
            shell_atoms={1.2: 204_047, 1.0: 180_000, 0.8: 150_000},
            atom_cap=None,
            gpu=True,
        )
        assert shell == DEFAULT_SHELL_NM
        assert gpu_res is False  # the carve DISABLES GPU-resident — the whole point
        # Wording changed with the size-aware model: the full box is no longer ALWAYS the
        # GPU-resident candidate, so the reason compares against "the full box".  The
        # payoff (3.5x) and the threshold it must clear (2.6x, since this system IS above
        # the resident crossover) are both still stated.
        assert "beats the full box" in why
        assert "3.5x" in why and "2.6x" in why

    def test_convex_design_keeps_full_box_and_gpu_resident(self) -> None:
        # A straight bundle already fills its bounding box: only 2.3x — below break-even.
        shell, gpu_res, why = choose_water_shell(
            full_atoms=231_328,
            shell_atoms={1.2: 100_000, 1.0: 90_000, 0.8: 80_000},
            atom_cap=None,
            gpu=True,
        )
        assert shell == 0.0
        assert gpu_res is True
        assert "does not pay" in why

    def test_carve_is_forced_when_the_full_box_will_not_fit(self) -> None:
        """Even a below-break-even carve is taken if the full box blows the memory cap."""
        shell, gpu_res, why = choose_water_shell(
            full_atoms=2_000_000,
            shell_atoms={1.2: 900_000, 1.0: 800_000, 0.8: 700_000},
            atom_cap=1_000_000,
            gpu=True,
        )
        assert shell == DEFAULT_SHELL_NM
        assert gpu_res is False
        assert "does not fit" in why or "exceeds" in why

    def test_shell_is_thinned_only_when_memory_demands_it(self) -> None:
        """The default shell doesn't fit → step down, but no thinner than needed."""
        shell, _gpu_res, _why = choose_water_shell(
            full_atoms=5_000_000,
            shell_atoms={1.2: 1_200_000, 1.0: 950_000, 0.8: 700_000},
            atom_cap=1_000_000,
            gpu=True,
        )
        assert shell == 1.0  # the thickest shell that fits — not 0.8

    def test_never_thins_the_shell_for_speed_alone(self) -> None:
        """Memory is ample; a thinner shell WOULD be faster — it must still be refused.

        This is the regression that matters: an optimiser told to maximise ns/day will
        shave the hydration layer to nothing, because throughput rises monotonically as
        the shell thins.  Shell thickness is physics, not a speed knob.
        """
        shell, _gpu_res, _why = choose_water_shell(
            full_atoms=712_370,
            shell_atoms={1.2: 204_047, 1.0: 150_000, 0.8: 100_000},
            atom_cap=None,
            gpu=True,  # no memory pressure at all
        )
        assert shell == DEFAULT_SHELL_NM  # NOT 0.8, even though 0.8 is 2x faster

    def test_never_goes_below_the_hard_floor(self) -> None:
        shell, _gpu_res, _why = choose_water_shell(
            full_atoms=9_000_000,
            shell_atoms={1.2: 3_000_000, 1.0: 2_500_000, 0.8: 2_000_000},
            atom_cap=1_000,
            gpu=True,  # absurd cap: nothing fits
        )
        assert shell >= MIN_SHELL_NM

    def test_cpu_build_has_no_gpu_resident_even_on_the_full_box(self) -> None:
        _shell, gpu_res, _why = choose_water_shell(
            full_atoms=100_000,
            shell_atoms={1.2: 90_000},
            atom_cap=None,
            gpu=False,
        )
        assert gpu_res is False


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

    def test_a_small_full_box_design_is_recommended_OFFLOAD_not_resident(self) -> None:
        """The regression: a 2hb-scale design fits fine and no carve pays, so the old
        code returned gpu_resident=True — recommending the slower path."""
        from backend.core.md_optimize import choose_water_shell

        shell, gpu_res, why = choose_water_shell(
            full_atoms=32_566,
            shell_atoms={1.2: 30_000},
            atom_cap=None,
            gpu=True,
        )
        assert shell == 0.0  # full box still wins (no carve pays)
        assert gpu_res is False  # ...but on the OFFLOAD path
        assert "slower" in why.lower()

    def test_a_large_full_box_design_still_gets_resident(self) -> None:
        from backend.core.md_optimize import choose_water_shell

        _shell, gpu_res, _why = choose_water_shell(
            full_atoms=3_139_238,
            shell_atoms={1.2: 3_100_000},
            atom_cap=None,
            gpu=True,
        )
        assert gpu_res is True


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
