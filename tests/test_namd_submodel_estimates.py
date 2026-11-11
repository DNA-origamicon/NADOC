"""Estimator/software contracts only: no dynamics and no authored structures."""
import asyncio
from types import SimpleNamespace

import pytest

from backend.core import md_vram
from backend.api import routes_md, routes_md_plan
from backend.api.simulation_submodel import SubmodelBox
from tests.test_namd_submodel import toy_topology, BOX


def test_profile_uses_preparation_crop_bonded_support_and_shell_cache(monkeypatch):
    from backend.core import namd_topology
    design = SimpleNamespace(without_reference_geometry=lambda: design)
    source = toy_topology()
    calls = []
    monkeypatch.setattr(namd_topology, 'build_charmm_psfgen_topology', lambda *a, **k: calls.append(True) or source)
    monkeypatch.setattr(md_vram, '_profile_cache_key', lambda *a: ('submodel-estimator-test',))
    monkeypatch.setattr(md_vram, '_PROFILE_CACHE', {})
    small = md_vram.estimate_profile_from_design(design, padding_nm=1.2, submodel=BOX)
    assert small['dna_atoms'] == 4  # Includes all bonded support, even at shell=0.
    assert small['atom_components']['solute_atoms'] == 4
    assert small['submodel']['source_solute_atoms'] == 8
    assert small['submodel']['mobile_solute_atoms'] == 1
    assert small['submodel']['shell_solute_atoms'] == 3
    assert small['resource_box_nm'] == small['box_nm']  # Hydrogens already present.
    assert md_vram.estimate_profile_from_design(design, padding_nm=1.2, submodel={**BOX, 'visible': False}) is small
    assert len(calls) == 1
    wide = md_vram.estimate_profile_from_design(design, padding_nm=1.2, submodel={**BOX, 'shell_nm': 20})
    assert wide['dna_atoms'] == 8 and len(calls) == 2
    assert wide['atom_upper_bound'] > small['atom_upper_bound']
    assert source == toy_topology()


@pytest.mark.parametrize('devices', ['0', 'cpu'])
def test_memory_budgets_all_retained_atoms_and_forces_offload(monkeypatch, tmp_path, devices):
    from backend.core import memory_budget
    monkeypatch.setenv('NADOC_MEMORY_BUDGET_DIR', str(tmp_path))
    monkeypatch.setattr(md_vram, 'detect_host_ram_mb', lambda: 64000)
    monkeypatch.setattr(md_vram, 'detect_vram_mb', lambda *a: 24000)
    monkeypatch.setattr(memory_budget, 'available_for_work', lambda **k: 50000*1024**2)
    monkeypatch.setattr(md_vram, 'estimate_profile_from_design', lambda *a, **k: dict(
        dna_atoms=2000, full_water=10000, ion_atoms=0, atom_upper_bound=32000,
        box_nm=(12,12,12), resource_box_nm=(12,12,12),
        submodel=dict(source_solute_atoms=10000, retained_solute_atoms=2000)))
    result = md_vram.preflight_vram_advice(object(), devices=devices, submodel=BOX,
        stage_overrides={'*': {'GPUresident': 'on'}})
    assert result['current_atoms'] == 32000
    assert result['tier'] == 'ok'
    offload = result['execution_modes']['offload']
    assert result['current_host_mb'] >= offload['ram_mib'] + offload['health_ram_mib']
    assert result['current_vram_mb'] == (0 if devices == 'cpu' else offload['gpu_mib'])
    assert result['execution_modes']['resident']['supported'] is False
    from backend.core.namd_resources import preparation_memory_mib
    assert result['preparation_ram_mb'] == preparation_memory_mib(40000)


def test_forecasts_receive_region_and_quote_offload_with_cropped_atom_count(monkeypatch, tmp_path):
    from backend.core import namd_runtime
    from backend.core.disk_guard import namd_run_output_bytes
    design = SimpleNamespace(without_reference_geometry=lambda: design)
    monkeypatch.setattr(routes_md.design_state, 'get_or_404', lambda: design)
    box = SubmodelBox(**BOX)
    body = routes_md.CreateJobRequest(submodel=box, gpu_resident='on', run_dir=str(tmp_path))
    def memory(*a, **kw):
        assert kw['submodel'] == box and kw['gpu_resident_mode'] == 'off'
        return {'tier': 'ok'}
    monkeypatch.setattr(md_vram, 'preflight_vram_advice', memory)
    assert asyncio.run(routes_md.preflight_md_vram(body))['tier'] == 'ok'
    def profile(*a, **kw):
        assert kw['submodel'] == box
        return dict(dna_atoms=1000, full_water=100, ion_atoms=0, atom_upper_bound=1300,
                    submodel={'retained_solute_atoms': 1000}, resource_box_nm=(8,8,8))
    monkeypatch.setattr(md_vram, 'estimate_profile_from_design', profile)
    async def plan(request, **kw):
        assert request.gpu_resident == 'off' and request.n_atoms_hint == 1300
        return {'stages': [dict(role='relaxation', steps=10000, ns=.02, params={'gpuresident':'on','dcdfreq':100})]}
    monkeypatch.setattr(routes_md_plan, 'protocol_plan', plan)
    def compute(atoms, stages, **kw):
        assert atoms == 1300 and stages[0]['gpu_resident'] is False
        assert kw['box_nm'] == (8,8,8)
        return None
    monkeypatch.setattr(namd_runtime, 'local_compute', compute)
    result = asyncio.run(routes_md.estimate_md_disk(body))
    assert result['predicted_bytes'] == namd_run_output_bytes([(10000,100)],1300)
    assert result['submodel']['retained_solute_atoms'] == 1000


def test_prepared_forecast_preserves_actual_region_and_admission(monkeypatch, tmp_path):
    import json
    from backend.core import namd_resources
    receipt = dict(source_atoms=8, retained_source_indices=[0,1,2,3],
                   mobile_source_indices=[1], box=BOX)
    (tmp_path/'manifest.json').write_text(json.dumps(dict(box_ang=[80,90,100], submodel=receipt)))
    monkeypatch.setattr(namd_resources, 'prepared_resource_summary', lambda *a, **k: dict(
        admission=dict(workflow_ram_mib=1705, gpu_mib=1171)))
    result = namd_resources.prepared_forecast_context(tmp_path)
    assert result['box_nm'] == [8,9,10]
    assert result['submodel']['retained_solute_atoms'] == 4
    assert result['submodel']['shell_solute_atoms'] == 3
    assert result['memory']['current_host_mb'] == 1705
    assert result['memory']['current_vram_mb'] == 1171
    assert 'production settings are checked again' in result['memory']['scope']
