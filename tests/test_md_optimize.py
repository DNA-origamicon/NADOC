"""Advanced-card Optimize policy (backend/core/md_optimize.py)."""

from __future__ import annotations

import pytest

from backend.core.md_optimize import (
    physical_cores,
    predict_ns_per_day,
)


class TestThroughputModel:
    def test_uses_current_hardware_scoped_evidence(self, monkeypatch):
        from backend.core import namd_timing
        calls=[]
        def rate(n,**kwargs):
            calls.append((n,kwargs))
            return 10.0
        monkeypatch.setattr(namd_timing,'local_step_ms',rate)
        assert predict_ns_per_day(500000,gpu_resident=True,devices='1',threads=16)==pytest.approx(34.56)
        assert calls==[(500000,dict(resident=True,devices='1',threads=16))]

    def test_unknown_evidence_or_cpu_never_uses_an_obsolete_engine(self,monkeypatch):
        from backend.core import namd_timing
        monkeypatch.setattr(namd_timing,'local_step_ms',lambda *args,**kwargs:None)
        assert predict_ns_per_day(500000,gpu_resident=True) is None
        assert predict_ns_per_day(500000,gpu_resident=False,gpu=False) is None
        assert predict_ns_per_day(0,gpu_resident=True)==0.0


def test_physical_cores_is_at_least_one() -> None:
    assert physical_cores() >= 1


class TestResidentIsSizeAware:
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
