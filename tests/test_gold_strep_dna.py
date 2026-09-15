import json
import subprocess
import numpy as np
import pytest
from fastapi.testclient import TestClient
from backend.api import state, doc_context
from backend.api.main import app
from backend.api.crud import _geometry_for_design
from backend.core.models import Design, Nanoparticle
from backend.core.streptavidin import build_streptavidin_coating, require_coating_simulation_support
from backend.core.gold_strep_dna import build_dna
from backend.core.oxdna_job import new_oxdna_job
from backend.core.oxdna_protocol import build_relaxation_stages, render_stage_input
from backend.core.oxdna_runner import prepare_oxdna_job, find_oxdna


def example(mode='adsorption'):
    p=Nanoparticle(diameter_nm=10,coating=build_streptavidin_coating(10,count_override=1,mode=mode))
    r,h,s=build_dna(p,'ACGTACGTACGTACGT')
    p.biotin_dna=[r];p.oxdna_fixed_core=True
    return Design(nanoparticles=[p],helices=[h],strands=[s])


@pytest.mark.slow
@pytest.mark.oxdna
@pytest.mark.parametrize('backend', ['CPU', 'CUDA'])
@pytest.mark.parametrize('mode,particles,protein_beads', [('adsorption',500,484),('biotin_tether',501,485)])
def test_full_build_and_engine(tmp_path,backend,mode,particles,protein_beads):
    d=example(mode); specs=build_relaxation_stages(mc_steps=10,md_relax_steps=100,equil_steps=100,backend=backend,protein=True)
    job=new_oxdna_job(design_name='gold-strep-dna',stages=[s.to_status() for s in specs])
    prepare_oxdna_job(d,_geometry_for_design(d),job,tmp_path,specs)
    jd=job.job_dir(tmp_path)
    assert (jd/'topology.top').read_text().splitlines()[0].split() == [str(particles),'2','16',str(protein_beads),'1']
    manifest=json.loads((jd/'nanoparticles.json').read_text())
    assert manifest['mobile_core'] is False
    assert manifest['particles'][0]['dna'][0]['strand_id']==d.strands[0].id
    for name in ['forces.txt','equil_forces.txt']:
        t=(jd/name).read_text(); assert 'repulsive_sphere_moving' in t
        assert t.count('type = mutual_trap')==2
        assert t.count('type = trap')==3
    binary=find_oxdna()
    if not binary: pytest.skip('No oxDNA executable available')
    if backend=='CUDA':
        from backend.core.oxdna_runner import oxdna_supports_cuda
        import shutil
        if not oxdna_supports_cuda(binary) or not shutil.which('nvidia-smi'):
            pytest.skip('CUDA build and GPU required')
        if subprocess.run(['nvidia-smi','-L'],capture_output=True,timeout=10).returncode:
            pytest.skip('GPU unavailable')
    assert specs[0].backend=='CPU'
    assert all(s.backend==backend for s in specs[1:])
    assert all(s.dt<=.0001 for s in specs if s.sim_type=='MD')
    assert all(s.absolute_forces and s.external_forces for s in specs)
    conf=jd/'conf.dat'
    for spec in specs:
        folder=jd/spec.name;folder.mkdir()
        force=jd/(spec.forces_file or 'forces.txt')
        (folder/'input').write_text(render_stage_input(spec,str(jd/'topology.top'),str(conf),str(force),str(jd/'anm.par')))
        run=subprocess.run([binary,'input'],cwd=folder,capture_output=True,text=True,timeout=60)
        assert run.returncode==0,(run.stdout+run.stderr)[-2500:]
        conf=folder/'last_conf.dat'
        a=np.loadtxt(conf,skiprows=3)
        assert a.shape==(particles,15) and np.isfinite(a).all()
        from backend.core.constants import NM_TO_OXDNA
        assert np.linalg.norm(a[:,:3]/NM_TO_OXDNA,axis=1).min()>5


def test_api_history_move_remove_and_safety():
    doc_context.set_current_doc(None); state.set_design(Design())
    client=TestClient(app)
    try:
        result=client.post('/api/design/nanoparticles/gold-nanospheres',json={'diameter_nm':10,'coating':{'count_override':1}})
        assert result.status_code==201
        p=state.get_design().nanoparticles[0];url=f'/api/design/nanoparticles/{p.id}'
        assert client.post(url+'/biotin-dna',json={'sequence':'ACGTACGT'}).status_code==200
        d=state.get_design(); assert len(d.strands)==1 and d.nanoparticles[0].oxdna_fixed_core
        before=d.helices[0].axis_start.to_array()
        require_coating_simulation_support(d,'oxDNA')
        with pytest.raises(ValueError): require_coating_simulation_support(d,'NAMD')
        assert client.patch(url,json={'diameter_nm':20}).status_code==409
        pose=np.eye(4);pose[:3,3]=[1,2,3]
        assert client.patch(url,json={'pose':pose.ravel().tolist()}).status_code==200
        assert np.allclose(state.get_design().helices[0].axis_start.to_array(),before+[1,2,3])
        assert client.delete(url+'/biotin-dna').status_code==200
        assert not state.get_design().strands
        assert client.post('/api/design/undo').status_code==200
        assert len(state.get_design().strands)==1
        assert client.delete(url).status_code==200
        assert not state.get_design().strands and not state.get_design().helices
    finally: state.close_session()


@pytest.mark.parametrize('backend', ['CPU','CUDA',None])
def test_job_api_builds_full_fixed_core_model(tmp_path, monkeypatch,backend):
    from backend.api import routes_oxdna
    monkeypatch.setattr(routes_oxdna, '_WORKSPACE_DIR', tmp_path)
    monkeypatch.setattr(routes_oxdna, 'find_oxdna', lambda: '/test/oxDNA')
    monkeypatch.setattr(routes_oxdna, 'oxdna_supports_cuda', lambda _: True)
    monkeypatch.setattr(routes_oxdna, 'oxdna_supports_dnanm', lambda _: True)
    monkeypatch.setattr(routes_oxdna, 'oxdna_supports_rigid_bussi', lambda _: True)
    monkeypatch.setattr(routes_oxdna, 'oxdna_supports_matched_bussi_rng', lambda _: True)
    monkeypatch.setattr(routes_oxdna, 'oxdna_supports_physics_v3', lambda _: True)
    doc_context.set_current_doc(None);state.set_design(example())
    try:
        client=TestClient(app)
        payload={'mc_steps':100,'md_relax_steps':100,'equil_steps':100,'autostart':False}
        if backend is not None:payload['backend']=backend
        result=client.post('/api/oxdna/jobs',json=payload)
        assert result.status_code==200,result.text
        assert result.json()['backend']==(backend or 'CUDA')
        assert list(tmp_path.rglob('nanoparticles.json'))
    finally: state.close_session()


def test_saved_model_validation_and_fingerprint():
    from backend.core.gold_strep_dna import validate_fixed_core_design
    from backend.core.oxdna_staleness import design_build_fingerprint
    from backend.core.streptavidin import coating_simulation_gaps
    d=Design.model_validate_json(example().model_dump_json())
    validate_fixed_core_design(d)
    assert coating_simulation_gaps(d)['oxdna_fixed_core_ready']
    fingerprint=design_build_fingerprint(d)
    broken=d.model_copy(deep=True);broken.nanoparticles[0].oxdna_fixed_core=False
    assert design_build_fingerprint(broken)!=fingerprint
    with pytest.raises(ValueError): validate_fixed_core_design(broken)
    broken=d.model_copy(deep=True);broken.helices=[]
    with pytest.raises(ValueError,match='missing'): validate_fixed_core_design(broken)
    broken=d.model_copy(deep=True);broken.nanoparticles[0].coating.mode='biotin_tether';broken.nanoparticles[0].biotin_dna[0].chain='A'
    with pytest.raises(ValueError,match='occupied'): validate_fixed_core_design(broken)


def test_coating_display_preserves_absolute_frame(tmp_path):
    from backend.physics.oxdna_protein import protein_display_transforms
    from backend.core.constants import NM_TO_OXDNA
    d=example();geometry=_geometry_for_design(d)
    specs=build_relaxation_stages(mc_steps=10,md_relax_steps=100,equil_steps=100,backend='CPU',protein=True)
    job=new_oxdna_job(design_name='display',stages=[s.to_status() for s in specs])
    prepare_oxdna_job(d,geometry,job,tmp_path,specs)
    ref=job.job_dir(tmp_path)/'conf.dat'
    lines=ref.read_text().splitlines(); data=np.loadtxt(ref,skiprows=3)
    shift=np.array([.1,.2,.3]);data[:484,:3]+=shift*NM_TO_OXDNA
    moved=tmp_path/'moved.dat'
    with moved.open('w') as f:
        f.write('\n'.join(lines[:3])+'\n');np.savetxt(f,data)
    transforms=protein_display_transforms(moved,ref,d,geometry,align=False)
    matrix=np.array(transforms[f'{d.nanoparticles[0].id}:strep:0']).reshape(4,4)
    assert np.allclose(matrix[:3,:3],np.eye(3),atol=1e-5)
    assert np.allclose(matrix[:3,3],shift,atol=1e-5)


def test_strep_preview_is_read_only():
    doc_context.set_current_doc(None);state.set_design(example())
    try:
        before=state.get_design().model_dump_json()
        p=state.get_design().nanoparticles[0]
        response=TestClient(app).post(f'/api/design/nanoparticles/{p.id}/streptavidin-preview',json={'count_override':1})
        assert response.status_code==200
        assert len(response.json()['coating']['poses'])==1
        assert state.get_design().model_dump_json()==before
    finally: state.close_session()


@pytest.mark.slow
@pytest.mark.oxdna
@pytest.mark.parametrize('diameter,mode', [(5,'adsorption'),(10,'adsorption'),(10,'biotin_tether')])
def test_cuda_fixed_gold_force_response_and_translation(tmp_path,diameter,mode):
    """Exercise gold exclusion, anchors, ANM and DNA torque, including moved scenes."""
    import dataclasses
    import re
    import shutil
    from backend.core.constants import NM_TO_OXDNA
    from backend.core.oxdna_runner import oxdna_supports_cuda, configure_adaptive_memory_input

    binary=find_oxdna()
    if not binary or not oxdna_supports_cuda(binary) or not shutil.which('nvidia-smi'):
        pytest.skip('CUDA oxDNA and GPU required')
    if subprocess.run(['nvidia-smi','-L'],capture_output=True,timeout=10).returncode:
        pytest.skip('GPU unavailable')
    p=Nanoparticle(diameter_nm=diameter,coating=build_streptavidin_coating(diameter,count_override=1,mode=mode))
    record,helix,strand=build_dna(p,'ACGTACGTACGTACGT')
    p.biotin_dna=[record];p.oxdna_fixed_core=True
    design=Design(nanoparticles=[p],helices=[helix],strands=[strand])
    specs=build_relaxation_stages(mc_steps=10,md_relax_steps=100,equil_steps=100,backend='CPU',protein=True)
    job=new_oxdna_job(design_name='force-parity',stages=[s.to_status() for s in specs])
    prepare_oxdna_job(design,_geometry_for_design(design),job,tmp_path,specs)
    jd=job.job_dir(tmp_path);initial=np.loadtxt(jd/'conf.dat',skiprows=3)
    dna=int((jd/'topology.top').read_text().splitlines()[0].split()[3])
    nearest=initial[np.argmin(np.linalg.norm(initial[:,:3],axis=1)),:3].copy()
    radius=np.linalg.norm(nearest)
    initial[:,:3]-=(radius-(diameter/2+.1)*NM_TO_OXDNA)*nearest/radius
    initial[0,0]+=.005*NM_TO_OXDNA
    initial[dna:,:3]+=np.array([.01,0,0])*NM_TO_OXDNA
    initial[dna,:3]+=np.array([.005,.003,0])*NM_TO_OXDNA
    angle=.025
    rotation=np.array([[np.cos(angle),0,np.sin(angle)],[0,1,0],[-np.sin(angle),0,np.cos(angle)]])
    initial[dna,3:6]=rotation@initial[dna,3:6]
    initial[dna,6:9]=rotation@initial[dna,6:9]
    initial[:,9:15]=1e-8
    initial[:dna,12:15]=0
    header='\n'.join((jd/'conf.dat').read_text().splitlines()[:3])+'\n'
    responses={}
    for moved,dt in [(False,1e-5),(False,1e-6),(True,1e-6)]:
        shift=np.array([3,-2,1])*NM_TO_OXDNA if moved else np.zeros(3)
        coordinates=initial.copy();coordinates[:,:3]+=shift
        force_text=(jd/'equil_forces.txt').read_text()
        def translate(match):
            values=np.array([float(v) for v in match[2].split(',')])+shift
            return match[1]+' = '+','.join('%.12g'%v for v in values)
        force_text=re.sub(r'^(center|pos0)\s*=\s*(.*)$',translate,force_text,flags=re.M)
        for backend in ['CPU','CUDA']:
            folder=tmp_path/f'{backend}_{moved}_{dt}';folder.mkdir()
            force=folder/'forces.txt';force.write_text(force_text)
            conf=folder/'conf.dat'
            with conf.open('w') as f:
                f.write(header);np.savetxt(f,coordinates,fmt='%.15g')
            spec=dataclasses.replace(specs[-1],backend=backend,steps=1,dt=dt,thermostat='no',
                                     max_backbone_force=None,max_backbone_force_far=None,
                                     print_conf_interval_override=1,print_energy_every_override=1)
            text=render_stage_input(spec,str(jd/'topology.top'),str(conf),str(force),str(jd/'anm.par'))
            text=re.sub(r'^refresh_vel\s*=.*$','refresh_vel = false',text,flags=re.M)
            (folder/'input').write_text(text)
            configure_adaptive_memory_input(binary,folder/'input')
            run=subprocess.run([binary,'input'],cwd=folder,capture_output=True,text=True,timeout=30)
            assert run.returncode==0,(run.stdout+run.stderr)[-2000:]
            output=np.loadtxt(folder/'last_conf.dat',skiprows=3)
            assert output.shape==coordinates.shape and np.isfinite(output).all()
            responses[moved,dt,backend]=(output[:,9:15]-coordinates[:,9:15])/dt
    def assert_response(reference,other):
        assert np.linalg.norm(other-reference)/np.linalg.norm(reference)<.001
    for dt in [1e-5,1e-6]:
        cpu=responses[False,dt,'CPU'];gpu=responses[False,dt,'CUDA']
        assert_response(cpu[:,:3],gpu[:,:3])
        assert_response(cpu[dna:,:3],gpu[dna:,:3])
        assert_response(cpu[:,3:],gpu[:,3:])
    for backend in ['CPU','CUDA']:
        assert_response(responses[False,1e-6,backend],responses[False,1e-5,backend])
        assert_response(responses[False,1e-6,backend],responses[True,1e-6,backend])


@pytest.mark.parametrize('damage', ['exclusion', 'external_forces', 'interaction'])
def test_fixed_core_run_refuses_missing_physics(tmp_path,monkeypatch,damage):
    import asyncio
    from backend.core import oxdna_runner as runner
    from backend.core.oxdna_job import OxdnaStatus
    design=example()
    specs=build_relaxation_stages(mc_steps=10,md_relax_steps=100,equil_steps=100,backend='CPU',protein=True)
    spec=specs[-1]
    job=new_oxdna_job(design_name='guard',stages=[spec.to_status()])
    prepare_oxdna_job(design,_geometry_for_design(design),job,tmp_path,[spec])
    spec.backend='CUDA'
    if damage=='exclusion':(job.job_dir(tmp_path)/'equil_forces.txt').write_text('# removed gold exclusion\n')
    elif damage=='external_forces':spec.external_forces=False
    else:spec.interaction='DNA2'
    monkeypatch.setattr(runner,'find_oxdna',lambda: '/test/oxDNA')
    monkeypatch.setattr(runner,'oxdna_supports_dnanm',lambda _: True)
    monkeypatch.setattr(runner,'oxdna_supports_rigid_bussi',lambda _: True)
    monkeypatch.setattr(runner,'oxdna_supports_matched_bussi_rng',lambda _: True)
    monkeypatch.setattr(runner,'oxdna_supports_physics_v3',lambda _: True)
    async def must_not_run(*args,**kwargs):pytest.fail('An incomplete fixed-core model reached the engine')
    monkeypatch.setattr(runner,'_run_oxdna_async',must_not_run)
    asyncio.run(runner.run_job(job,tmp_path,[spec]))
    assert job.status==OxdnaStatus.failed
    assert 'gold exclusion and attachment forces' in job.error


def test_fixed_core_cpu_remains_available_without_cuda_build(tmp_path,monkeypatch):
    from backend.api import routes_oxdna
    monkeypatch.setattr(routes_oxdna,'_WORKSPACE_DIR',tmp_path)
    monkeypatch.setattr(routes_oxdna,'find_oxdna',lambda: '/test/cpu-only-oxDNA')
    monkeypatch.setattr(routes_oxdna,'oxdna_supports_dnanm',lambda _: True)
    monkeypatch.setattr(routes_oxdna,'oxdna_supports_rigid_bussi',lambda _: True)
    monkeypatch.setattr(routes_oxdna,'oxdna_supports_matched_bussi_rng',lambda _: True)
    monkeypatch.setattr(routes_oxdna,'oxdna_supports_physics_v3',lambda _: True)
    monkeypatch.setattr(routes_oxdna,'oxdna_supports_cuda',lambda _: False)
    doc_context.set_current_doc(None);state.set_design(example())
    try:
        client=TestClient(app)
        settings={'mc_steps':100,'md_relax_steps':100,'equil_steps':100,'autostart':False}
        unavailable=client.post('/api/oxdna/jobs',json=settings)
        assert unavailable.status_code==400
        assert 'CPU-only' in unavailable.json()['detail']
        cpu=client.post('/api/oxdna/jobs',json=dict(settings,backend='CPU'))
        assert cpu.status_code==200 and cpu.json()['backend']=='CPU'
        assert cpu.json()['status']=='queued'
    finally:state.close_session()


def test_protein_job_rejects_old_thermostat_before_start(tmp_path,monkeypatch):
    import asyncio
    from backend.core import oxdna_runner as runner
    from backend.core.oxdna_job import OxdnaStatus
    design=example()
    specs=build_relaxation_stages(mc_steps=10,md_relax_steps=100,equil_steps=100,backend='CPU',protein=True)
    job=new_oxdna_job(design_name='old-thermostat',stages=[s.to_status() for s in specs])
    prepare_oxdna_job(design,_geometry_for_design(design),job,tmp_path,specs)
    monkeypatch.setattr(runner,'find_oxdna',lambda: '/test/old-oxDNA')
    monkeypatch.setattr(runner,'oxdna_supports_dnanm',lambda _: True)
    monkeypatch.setattr(runner,'oxdna_supports_rigid_bussi',lambda _: False)
    async def must_not_run(*args,**kwargs):pytest.fail('Old thermostat reached the engine')
    monkeypatch.setattr(runner,'_run_oxdna_async',must_not_run)
    asyncio.run(runner.run_job(job,tmp_path,specs))
    assert job.status==OxdnaStatus.failed
    assert 'rotational-degree thermostat fix' in job.error


def test_gpu_protein_job_rejects_unmatched_bussi_before_start(tmp_path,monkeypatch):
    import asyncio
    from backend.core import oxdna_runner as runner
    from backend.core.oxdna_job import OxdnaStatus
    design=example()
    spec=build_relaxation_stages(mc_steps=10,md_relax_steps=100,equil_steps=100,backend='CPU',protein=True)[-1]
    job=new_oxdna_job(design_name='old-cuda-initialization',stages=[spec.to_status()])
    prepare_oxdna_job(design,_geometry_for_design(design),job,tmp_path,[spec])
    spec.backend='CUDA'
    monkeypatch.setattr(runner,'find_oxdna',lambda: '/test/old-oxDNA')
    monkeypatch.setattr(runner,'oxdna_supports_dnanm',lambda _: True)
    monkeypatch.setattr(runner,'oxdna_supports_rigid_bussi',lambda _: True)
    monkeypatch.setattr(runner,'oxdna_supports_matched_bussi_rng',lambda _: False)
    async def must_not_run(*args,**kwargs):pytest.fail('Unvalidated CUDA initialization reached the engine')
    monkeypatch.setattr(runner,'_run_oxdna_async',must_not_run)
    asyncio.run(runner.run_job(job,tmp_path,[spec]))
    assert job.status==OxdnaStatus.failed
    assert 'random-stream initialization' in job.error
