import numpy as np
import pytest
from backend.core.models import Design
from backend.core.nanoparticle import create_gold_nanosphere, build_thiol_conjugation
from backend.physics.oxdna_mobile_gold import append_mobile_gold, configure_mobile_gold_stages
from backend.core.oxdna_protocol import OxdnaStageSpec, render_stage_input
from backend.core.oxdna_staleness import oxdna_design_fingerprint


def design_with_handles(end='5p'):
    p=create_gold_nanosphere(10)
    c,h,s=build_thiol_conjugation(p,scheme='direct_thiol',sequence='ACGTACGT',count=2,attach_end=end)
    return Design(nanoparticles=[p],nanoparticle_conjugations=[c],helices=h,strands=s)

@pytest.mark.parametrize('end,terminals',[('5p',[0,8]),('3p',[7,15])])
def test_export_grafts_and_core(tmp_path,end,terminals):
    from backend.api.crud import _geometry_for_design
    from backend.physics.oxdna_interface import write_topology,write_configuration,assert_topology_matches_design
    design=design_with_handles(end)
    write_topology(design,tmp_path/'topology.top')
    write_configuration(design,_geometry_for_design(design),tmp_path/'conf.dat',oxdna_native_seed=True)
    m=append_mobile_gold(design,tmp_path)
    assert [g['dna'] for g in m['grafts']]==terminals
    assert m['n_cores']==1 and m['cores'][0]['index']==16
    assert_topology_matches_design(tmp_path/'topology.top',design,extra_trailing=1)
    rows=np.loadtxt(tmp_path/'conf.dat',skiprows=3)
    np.testing.assert_allclose(rows[-1,:3],0)
    with pytest.raises(ValueError): append_mobile_gold(design,tmp_path)


def test_stages_gpu_only_and_fingerprint():
    stages=[OxdnaStageSpec('mc','mc','MC',100,'CPU'),OxdnaStageSpec('production','production','MD',100,'CPU')]
    configure_mobile_gold_stages(stages)
    for s in stages:
        text=render_stage_input(s,'top','conf')
        assert 'backend = CUDA' in text and 'interaction_type = DNA2GOLD' in text
        assert 'refresh_vel = false' in text
        s.backend='CPU'
        with pytest.raises(ValueError): render_stage_input(s,'top','conf')
    d=design_with_handles();before=oxdna_design_fingerprint(d)
    d.nanoparticles[0].diameter_nm+=1
    assert oxdna_design_fingerprint(d)!=before


def test_prepared_job_and_trajectory_keep_gold_pose(tmp_path):
    from backend.api.crud import _geometry_for_design
    from backend.core.oxdna_job import new_oxdna_job
    from backend.core.oxdna_runner import prepare_oxdna_job
    from backend.core.oxdna_health import composite_trajectory
    from backend.physics.oxdna_interface import write_configuration,read_configuration_unwrapped
    from backend.physics.oxdna_surface_strands import capture_bead_count
    d=design_with_handles()
    stage=OxdnaStageSpec('prod','production','MD',10,'CUDA')
    job=new_oxdna_job('gold',[stage.to_status()])
    prepare_oxdna_job(d,_geometry_for_design(d),job,tmp_path,[stage])
    jd=job.job_dir(tmp_path)
    assert capture_bead_count(job)==1
    assert stage.interaction=='DNA2GOLD'
    write_configuration(d,_geometry_for_design(d),jd/'ref.dat')
    (jd/'trajectory.dat').write_text((jd/'conf.dat').read_text())
    result=composite_trajectory(d,[('prod','production',jd/'trajectory.dat')],jd/'ref.dat',0,align=False,n_trailing_extra=1,trailing_extra_strand_length=-1)
    assert ['__gold__',0,'CORE'] in result['keys']
    assert np.isfinite(result['frames']).all()
    core_index=result['keys'].index(['__gold__',0,'CORE'])
    np.testing.assert_allclose(result['frames'][-1][core_index*9:core_index*9+3],0,atol=1e-5)
    full=read_configuration_unwrapped(jd/'conf.dat',d,jd/'ref.dat',n_trailing_extra=1,trailing_extra_strand_length=-1)
    assert ('__gold__',0,'CORE') in full


def test_runpod_requires_gpu_and_preserves_model_path(tmp_path):
    from backend.core.runpod_oxdna import stage_inputs,render_build_script,render_chain_script,RunpodOxdnaError
    s=OxdnaStageSpec('prod','production','MD',100,'CUDA')
    configure_mobile_gold_stages([s])
    inputs=stage_inputs(tmp_path,[s],'/workspace/test')
    assert 'gold_file = /workspace/test/mobile_gold.dat' in inputs['prod/input.txt']
    assert 'mobile_gold/patch_engine.py' in render_build_script('90','/adaptive.patch',True)
    assert '-gold-' in render_chain_script('test',[s],'90')
    s.backend='CPU'
    with pytest.raises(RunpodOxdnaError):render_chain_script('test',[s],'90')


def test_production_child_keeps_core_model(tmp_path,monkeypatch):
    import asyncio
    from backend.api import routes_oxdna as routes
    from backend.api.crud import _geometry_for_design
    from backend.core.oxdna_job import new_oxdna_job,OxdnaStatus,OxdnaJob
    from backend.core.oxdna_runner import prepare_oxdna_job,load_stage_specs
    d=design_with_handles();stage=OxdnaStageSpec('relax','md_relax','MD',100,'CUDA')
    parent=new_oxdna_job('gold',[stage.to_status()],n_nucleotides=16)
    prepare_oxdna_job(d,_geometry_for_design(d),parent,tmp_path,[stage])
    parent.status=OxdnaStatus.completed;parent.save(tmp_path)
    monkeypatch.setattr(routes,'_load_job',lambda _:parent)
    monkeypatch.setattr(routes,'_workspace',lambda:tmp_path)
    monkeypatch.setattr(routes,'_assert_job_current',lambda _:None)
    monkeypatch.setattr(routes,'find_oxdna',lambda:'test-binary')
    monkeypatch.setattr(routes,'_latest_relaxed_conf',lambda *a:(parent.job_dir(tmp_path)/'conf.dat','relax'))
    # append_oxdna_run no longer auto-starts (NAMD-parity job creation — the panel's
    # Run button starts it), so read the created child back instead of intercepting
    # start_job's args.
    result=asyncio.run(routes.append_oxdna_run(parent.job_id,routes.RunRequest(steps=1000)))
    child=OxdnaJob.load(result['job_id'],tmp_path)
    specs=load_stage_specs(child.job_dir(tmp_path))
    assert child.status==OxdnaStatus.queued
    assert child.run_config['mobile_gold']==parent.run_config['mobile_gold']
    assert specs[0].interaction=='DNA2GOLD' and specs[0].backend=='CUDA'
    assert (child.job_dir(tmp_path)/'mobile_gold.dat').read_bytes()==(parent.job_dir(tmp_path)/'mobile_gold.dat').read_bytes()
