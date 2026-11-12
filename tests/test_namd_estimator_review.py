import json
from types import SimpleNamespace

import pytest

from backend.core import namd_allocation_model as allocation
from backend.core.namd_resources import (MemoryEstimate, health_expected_mib,
    health_memory_mib, preparation_expected_mib, preparation_memory_mib)
from scripts.validation.namd_estimator_audit import series_summary


@pytest.mark.parametrize('atoms,peak', [
    (313861,258.9), (472630,292.6), (1936696,765.0), (2979096,1072.2),
])
def test_compact_health_forecasts_cover_recorded_full_worker_peaks(atoms,peak):
    assert abs(health_expected_mib(atoms)/peak-1) < .06
    assert 1.2 < health_memory_mib(atoms)/peak < 1.6


@pytest.mark.parametrize('atoms,bonds,peak', [
    (323016,223253,358.74), (472630,15434,406.50),
    (2001261,2444676,1696.71), (3043101,2433727,2335.95),
    (2930633,0,1913.80),
])
def test_preparation_forecast_matches_recorded_sizes_and_restraint_extremes(atoms,bonds,peak):
    assert abs(preparation_expected_mib(atoms,extra_bonds=bonds)/peak-1) < .06
    assert preparation_memory_mib(atoms,extra_bonds=bonds) > peak*1.2
    assert preparation_memory_mib(atoms) >= preparation_memory_mib(atoms,extra_bonds=bonds)


def test_unmeasured_auxiliary_domain_keeps_previous_allowance():
    assert health_expected_mib(4_000_000) is None
    assert health_memory_mib(4_000_000) == 5312
    assert preparation_expected_mib(4_000_000) is None
    assert preparation_memory_mib(4_000_000) > 7400
    assert preparation_expected_mib(1_000_000,extra_bonds=3_000_000) is None
    assert preparation_memory_mib(1_000_000,extra_bonds=3_000_000) > 3000


def test_offload_prediction_uses_patch_count_and_retains_hardware_gating(tmp_path,monkeypatch):
    # Independent 786194-atom margin-30 boundary: 4534 MiB process VRAM,
    # 1620.879 MiB RSS; this case was not used to fit the patch coefficient.
    neighbor=dict(grid=[7,7,7],spatial_tile_pair_capacity_mib=3171.7589164972305)
    workspace=dict(forward_bytes=87808000,backward_bytes=87808000,texture_alignment=512,
        device='NVIDIA GeForce RTX 3080 Ti',device_identity='archived-GPU, 580.178.04')
    monkeypatch.setattr(allocation,'prepared_features',lambda *a,**kw:neighbor)
    monkeypatch.setattr(allocation,'matching_workspace',lambda *a,**kw:workspace)
    e=MemoryEstimate(786194,False,2252,5306,True,patch_layout={},
        components={'host':{'restraints_mib':55592*192/1024**2}})
    opts=dict(coordinates='input.pdb',pairlistdist='24',pmegridspacing='.75',timestep='2')
    out=allocation.prepared_allocation(tmp_path/'test.conf',opts,(200.,)*3,e,threads=32)
    assert out['estimate_kind']=='expected_process_peak'
    assert abs(out['gpu_mib']/4534-1)<.025
    assert abs(out['ram_mib']/1620.879-1)<.02
    assert not out['exceeds_admission']
    workspace['device']='Unqualified GPU'
    out=allocation.prepared_allocation(tmp_path/'test.conf',opts,(200.,)*3,e,threads=32)
    assert out['ram_mib'] is None and out['gpu_mib'] is None


def test_model_schema_mismatch_is_unavailable_instead_of_truncating(tmp_path,monkeypatch):
    monkeypatch.setattr(allocation,'prepared_features',lambda *a,**kw:
        dict(grid=[2,2,2],spatial_tile_pair_capacity_mib=100.))
    monkeypatch.setattr(allocation,'matching_workspace',lambda *a,**kw:
        dict(forward_bytes=0,backward_bytes=0,texture_alignment=512,
             device='NVIDIA GeForce RTX 3080 Ti',device_identity='GPU, 580.178.04'))
    original=allocation.json.loads
    def corrupted(text):
        result=original(text)
        result['modes']['resident']['gpu'].pop()
        return result
    monkeypatch.setattr(allocation,'json',SimpleNamespace(loads=corrupted))
    assert json.loads('{"unrelated": true}') == {'unrelated': True}
    e=MemoryEstimate(100000,True,1000,1000,True,patch_layout={},
        components={'host':{'restraints_mib':0}})
    out=allocation.prepared_allocation(tmp_path/'test.conf',{'coordinates':'a.pdb'},(100.,)*3,e)
    assert 'schema mismatch' in out['unavailable']
    assert out['ram_mib'] is None


def test_time_average_uses_elapsed_time_and_does_not_invent_missing_gpu_samples(tmp_path):
    p=tmp_path/'samples.json'
    p.write_text(json.dumps([
        dict(seconds=0,rss_bytes=100*1024**2,gpu_process_mib=50),
        dict(seconds=1,rss_bytes=200*1024**2),
        dict(seconds=9,rss_bytes=200*1024**2,gpu_process_mib=100),
        dict(seconds=10,rss_bytes=200*1024**2,gpu_process_mib=100),
        dict(seconds=11,rss_bytes=0,gpu_process_mib=0),
    ]))
    r=series_summary(p)
    assert r['ram']['mean_mib']==190
    assert r['gpu']['mean_mib']==55
    assert r['ram']['observed_s']==r['gpu']['observed_s']==10
    assert r['gpu']['maximum_sampling_gap_s']==9
