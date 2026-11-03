"""Reject oversized payloads before coordinate expansion and release reservations."""
from types import SimpleNamespace
import numpy as np
import pytest


def test_atom_batch_rejected_before_extracting(monkeypatch, tmp_path):
    from backend.core import md_trajectory as mt, memory_budget as mb
    from backend.core.md_atom_frames_bin import md_frames_atomistic_bin
    monkeypatch.setenv('NADOC_MEMORY_BUDGET_DIR', str(tmp_path))
    monkeypatch.setattr(mb.psutil, 'virtual_memory', lambda: SimpleNamespace(available=8 * 1024**3))
    monkeypatch.setattr(mt, '_build_playback_ctx', lambda *a, **k: {'heavy_idx': np.arange(300_000)})
    monkeypatch.setattr(mt, 'composite_raw_frame_map', lambda *a: list(range(1000)))
    def forbidden(*a, **k):
        pytest.fail('oversized request started extracting coordinates')
    monkeypatch.setattr(mt, '_extract_md_atoms_frame', forbidden)
    with pytest.raises(mb.MemoryBudgetExceeded, match='smaller frame range'):
        md_frames_atomistic_bin('x.psf', [('x', 'md', 'x.dcd')], 'x.pdb', {}, list(range(1000)))
    assert not list(tmp_path.glob('*.json'))


def test_solvent_budget_includes_graphene_dna_and_packing():
    from backend.core.md_trajectory import _check_solvent_response_budget
    from backend.core.memory_budget import MemoryBudgetExceeded
    topology = {'n_waters_total': 1_000_000, 'n_ions': 20_000, 'graphene_rows': range(1_000_000)}
    # Graphene is present even if optional water/ion/box overlays are off.
    with pytest.raises(MemoryBudgetExceeded):
        _check_solvent_response_budget(topology, {'water': False, 'ions': False}, 3)
    with pytest.raises(MemoryBudgetExceeded):
        _check_solvent_response_budget({}, {'include_dna': True}, 1, 3_000_000)
    _check_solvent_response_budget({'n_waters_total': 1_000_000}, {'max_waters': 1000, 'atomistic': True}, 8)
    with pytest.raises(MemoryBudgetExceeded):
        _check_solvent_response_budget({'n_waters_total': 1_000_000}, {'max_waters': 0, 'atomistic': True}, 8)


def test_worker_memory_rejection_is_actionable_http_413(monkeypatch):
    from backend.api.routes_md import _run_md_analysis
    from backend.core import md_analysis_runner
    from fastapi import HTTPException
    async def reject(*a, **k):
        raise RuntimeError('MemoryBudgetExceeded: Request a smaller frame range.')
    monkeypatch.setattr(md_analysis_runner, 'run_analysis', reject)
    with pytest.raises(HTTPException) as caught:
        import asyncio
        asyncio.run(_run_md_analysis(None, 'job', 'atomistic', 'md_frames_atomistic_bin', ()))
    assert caught.value.status_code == 413
    assert caught.value.detail == 'Request a smaller frame range.'
