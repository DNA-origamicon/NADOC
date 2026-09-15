import json
import numpy as np
import pytest
from backend.core.models import Design
from backend.core.namd_electrode_protocol import prepare_electrode_namd
from backend.core.namd_electrode_health import profile_stationarity

SPEC=dict(normal='z',gap_nm=4,width_nm=4,depth_nm=4,working_charge_C_m2=-.0413)

@pytest.mark.parametrize('mode,expected', [(None,'on'),('auto','on'),('off','off')])
def test_electrode_stage_writer_preserves_forces_and_disables_pressure(tmp_path,monkeypatch,mode,expected):
    from backend.core import namd_solvate as s
    monkeypatch.setattr(s,'_gmx_solvate',lambda pdb,*a,**k:([s._Water(1,1,2,1.095,1,2,1,1.095,2)],(4,4,4),pdb))
    relative,stem,segments=prepare_electrode_namd(Design(),tmp_path,two_electrodes=SPEC,
        ion_conc_mM=0,mg_conc_mM=0,fast=False,declash=False,seed_lattice_nm=None,
        **({'gpu_resident_mode':mode} if mode is not None else {}))
    folder=tmp_path/relative
    manifest=json.loads((folder/'manifest.json').read_text())
    assert manifest['protocol']=='electrode_equilibration_namd'
    assert manifest['gpu_resident_mode']==expected
    assert manifest['solvation']['npt_allowed'] is False
    assert manifest['charge_audit']['production_ready']
    assert all(not stage.npt for stage in segments)
    assert all(stage.scale is None for stage in segments)
    assert all('electrode/solvent' in stage.stage for stage in segments)
    for stage in segments:
        text=(folder/f'{stage.name}.conf').read_text()
        assert 'tclForcesScript electrode_forces.tcl' in text
        assert ('GPUresident        on' in text) == (expected=='on')
        assert text.rfind('langevinPiston off')>text.rfind('langevinPiston     on')
    assert 'electrode_slab_forces' in (folder/'electrode_forces.tcl').read_text()

def test_profiles_cannot_skip_on_short_or_drifting_evidence():
    stable=np.ones((60,4,20))
    assert profile_stationarity(stable)['passed']
    assert not profile_stationarity(stable[:10])['passed']
    drifting=stable.copy();drifting[30:,:,0]=100
    assert not profile_stationarity(drifting)['passed']


def test_fixed_cell_dna_settle_retains_shared_restraint_release():
    from backend.core.md_protocols import mgh_slow_release_segments
    _,stages=mgh_slow_release_segments('dna',nvt_only=True,fixed_cell_settle=True)
    assert all(not stage.npt for stage in stages)
    assert stages[0].restraint_ref_file
    assert 'NVT solvent settle' in stages[0].stage
    assert {stage.scale for stage in stages[1:]}=={.5,.1,.01,None}


def test_bulk_reference_rejects_unsettled_volume(tmp_path):
    import pytest
    from backend.core.namd_electrode_reference import assess_reference
    (tmp_path/'output').mkdir()
    (tmp_path/'reference.json').write_text(json.dumps({'water_oxygens':4000}))
    def write(vary=False):
        (tmp_path/'output'/'bulk.xst').write_text('\n'.join(f'{140000+500*i} {50+(i/100 if vary else 0)} 0 0 0 50 0 0 0 50 0 0 0' for i in range(200)))
    write()
    assert assess_reference(tmp_path)['water_number_density_nm3']==pytest.approx(32)
    write(True)
    with pytest.raises(ValueError,match='not stabilized'):assess_reference(tmp_path)


def test_bulk_density_uses_liquid_interior_not_padded_volume():
    import pytest
    from backend.core.namd_electrode_health import bulk_water_density
    xyz=np.array(np.meshgrid(np.arange(.5,10),np.arange(.5,10),np.arange(10.5,20),indexing='ij')).reshape(3,-1).T
    assert bulk_water_density(xyz,list(range(len(xyz))),[],[10,10,30],2,10,20)==pytest.approx(1)
    assert bulk_water_density(xyz,list(range(len(xyz))),[],[10,10,30],2,10,12) is None


def test_production_electrode_directives_override_pressure_and_preserve_peg():
    from backend.core.namd_electrode_protocol import apply_electrode_forces
    from backend.core.md_plan import parse_conf_directives
    text=apply_electrode_forces('langevinPiston on\nwrapWater on\nrun 100\n',peg=True)
    params=parse_conf_directives(text)
    assert params['langevinpiston']=='off'
    assert params['wrapwater']=='off'
    assert params['tclforcesscript']=='electrode_forces.tcl'
    assert 'forcefield/par_all35_ethers.prm' in params['parameters']


def test_electrode_adapter_rejects_missing_settings_and_conflicting_callbacks(tmp_path):
    import pytest
    from backend.core.namd_electrode_protocol import apply_electrode_forces
    with pytest.raises(ValueError, match='requires two-electrode settings'):
        prepare_electrode_namd(Design(),tmp_path,two_electrodes=None)
    with pytest.raises(ValueError, match='another Tcl force script'):
        apply_electrode_forces('tclForcesScript custom.tcl\nrun 10\n')


def test_bulk_reference_startup_has_unique_output_directives():
    import re
    from backend.core.namd_electrode_reference import reference_conf
    for stage in ['bulk_min','bulk_heat','bulk']:
        text=reference_conf(310,173,stage=stage)
        for key in ['outputEnergies','xstFreq']:
            assert re.findall(rf'(?mi)^\s*{key}\s+(\d+)\s*$',text)==['500']
        # Startup-only controls must precede the single execution command.
        commands=list(re.finditer(r'(?m)^(run|minimize) ',text))
        assert len(commands)==1
        assert 'rigidBonds' not in text[commands[0].start():]
    heat=reference_conf(310,173,stage='bulk_heat')
    assert 'binCoordinates output/bulk_min.coor' in heat
    assert 'temperature 310' in heat
    assert 'rigidBonds all' in heat
    bulk=reference_conf(310,173)
    assert 'binVelocities output/bulk_heat.vel' in bulk
    assert 'langevinPiston on' in bulk


def test_bulk_reference_failure_exposes_namd_cause(tmp_path,monkeypatch):
    import asyncio
    import pytest
    from backend.core.namd_electrode_reference import ensure_reference
    folder=tmp_path/'bulk_reference';folder.mkdir()
    (folder/'bulk.conf').write_text('run 0')
    monkeypatch.setattr('backend.core.namd_electrode_reference.write_reference_configs',lambda folder:None)
    (folder/'bulk_min.log').write_text("ERROR: Multiple definitions of 'outputEnergies'\nFATAL ERROR: ERROR(S) IN THE CONFIGURATION FILE\n")
    async def fail(folder,stem):return 1
    with pytest.raises(ValueError,match="Multiple definitions of 'outputEnergies'"):
        asyncio.run(ensure_reference(tmp_path,{'two_electrodes':{}},fail))


def test_electrode_forces_precede_adaptive_minimization():
    from backend.core.namd_electrode_protocol import apply_electrode_forces
    text=apply_electrode_forces('while {$remaining > 0} {\n    minimize $chunk\n}\n')
    assert text.index('tclForcesScript electrode_forces.tcl')<text.index('while')
    assert 'langevinPiston off' in text


def test_profile_evidence_accumulates_within_rung_but_not_across_rungs(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from backend.core import namd_electrode_health as health
    names=['rung1_p10','rung1_p25','rung2_p10']
    manifest={'segments':[{'name':n} for n in names], 'files':{'topology':'system.psf'},
        'two_electrodes':{'n_atoms':20,'normal_axis':1,'normal_bounds_A':[0,10],'cell_nm':[1,1,1]},
        'electrode_validation':{'bulk_reference_result':{'water_number_density_nm3':33}}}
    (tmp_path/'manifest.json').write_text(json.dumps(manifest));(tmp_path/'system.psf').write_text('');(tmp_path/'output').mkdir()
    monkeypatch.setattr(health,'parse_psf_atoms',lambda _: [SimpleNamespace(atomtype='OT',resname='TIP3',atomname='OH2',mass=16,segid='W')]*20)
    monkeypatch.setattr(health,'segment_evidence',lambda *a:({i:(np.tile([[1,5,1],[2,6,2]],(10,1)),{}) for i in range(10)},'',[]))
    monkeypatch.setattr(health,'bulk_water_density',lambda *a:33.)
    result=health.electrode_skip_check(tmp_path,'rung1_p25')
    assert result['passed'] and result['frames']==20
    assert result['evidence_segments']==names[:2]
    result=health.electrode_skip_check(tmp_path,'rung2_p10')
    assert not result['passed'] and result['frames']==10

    # Dense 2 ps output still measures the same 600 ps stationarity window.
    for row in manifest['segments']:row.update(timestep_fs=4,steps=300000)
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    xyz=np.tile([[1,5,1],[2,6,2]],(10,1))
    monkeypatch.setattr(health,'segment_evidence',lambda *a:({(i+1)*500:(xyz,{}) for i in range(600)},'',[]))
    result=health.electrode_skip_check(tmp_path,'rung1_p25')
    assert result['passed'] and result['frames']==300
    assert result['requested_window_ns']==.6
    assert abs(result['observed_window_span_ns']-.598)<1e-10


def test_reference_resume_requires_final_output_and_normal_exit(tmp_path):
    from backend.core.namd_electrode_reference import reference_stage_complete, reference_process
    (tmp_path/'output').mkdir()
    for ext in ['coor','vel']:(tmp_path/'output'/f'bulk_min.{ext}').write_bytes(b'coordinates')
    (tmp_path/'output/bulk_min.xsc').write_text('4800 1 0 0\n')
    (tmp_path/'bulk_min.log').write_text('FATAL ERROR: stopped\n')
    assert not reference_stage_complete(tmp_path,'bulk_min')
    (tmp_path/'bulk_min.log').write_text('WallClock: 10\n')
    assert reference_stage_complete(tmp_path,'bulk_min')
    (tmp_path/'output/bulk_min.xsc').write_text('200 1 0 0\n')
    assert not reference_stage_complete(tmp_path,'bulk_min')
    proc=tmp_path/'proc';proc.mkdir()
    for pid,folder in [('11',tmp_path/'other'),('12',tmp_path)]:
        entry=proc/pid;entry.mkdir();(entry/'cmdline').write_bytes(b'/bin/namd3\0+p2\0bulk.conf\0');(entry/'cwd').symlink_to(folder)
    assert reference_process(tmp_path,'bulk',proc)==12


def test_reference_rejects_wrong_salt_cache(tmp_path):
    import asyncio
    import pytest
    from backend.core.namd_electrode_reference import ensure_reference
    folder=tmp_path/'bulk_reference';folder.mkdir()
    (folder/'result.json').write_text(json.dumps({'passed':True,'salt_mM':150,'mg_mM':0,'temperature_K':300}))
    with pytest.raises(ValueError,match='does not match'):
        asyncio.run(ensure_reference(tmp_path,{'two_electrodes':{'salt_mM':300,'mg_mM':0,'temperature_K':300}},None))


def test_solvent_production_requires_completed_passing_electrode_checkpoint(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from backend.api import routes_md
    from backend.core.md_job import MdStatus
    from backend.core.md_protocols import SegmentSpec
    output=tmp_path/'output';output.mkdir()
    (tmp_path/'manifest.json').write_text(json.dumps({'two_electrodes':{'dna_atoms':0}}))
    spec=SegmentSpec(name='solvent_p10',stage='NVT solvent',percent=10,steps=10,temp=300,damping=5,scale=.5,npt=False,previous='min')
    monkeypatch.setattr(routes_md,'segments_from_manifest',lambda _: ('min',[spec]))
    job=SimpleNamespace(run_kind='relax',status=MdStatus.running,package_dir=lambda _:tmp_path,
        segments=[SimpleNamespace(name=spec.name,status='done')],health_samples=[])
    for ext in ['coor','vel','xsc']:(output/f'{spec.name}.{ext}').write_text('restart')
    assert 'Complete electrode' in routes_md._production_ready_checkpoint(job)[2]
    job.status=MdStatus.completed
    assert 'no passing' in routes_md._production_ready_checkpoint(job)[2]
    report=output/f'{spec.name}.electrode-health.json'
    report.write_text(json.dumps({'passed':False}))
    assert routes_md._production_ready_checkpoint(job)[0] is None
    report.write_text(json.dumps({'passed':True}))
    assert routes_md._production_ready_checkpoint(job)==(0,spec,'','')


def test_electrode_failure_names_the_failed_measurement():
    from backend.core.namd_electrode_health import validation_failure
    message=validation_failure({'passed':False,'profile_drift':[.01,.05,.23,0],
        'tolerance':.1,'confined':True,'bulk_reference_validated':True,'peg_stable':True})
    assert message=='Cl profile drift 0.230 exceeds 0.100'
    assert validation_failure({'passed':True})==''
    assert 'Insufficient' in validation_failure({'passed':False,'reason':'Insufficient finite profile samples'})


def test_profile_window_can_forget_initial_transient_but_not_recent_drift():
    samples=np.ones((120,4,20))
    samples[:60,:,0]=100
    result=profile_stationarity(samples)
    assert result['passed'] and result['frames']==60
    assert result['total_frames']==120 and result['discarded_initial_frames']==60
    samples[-30:,:,0]=100
    assert not profile_stationarity(samples)['passed']


def test_sparse_stationary_profiles_are_not_rejected_for_binwise_sampling_noise():
    rng=np.random.default_rng(123)
    controls=rng.multinomial(10,np.ones(20)/20,size=(1000,60,2))
    results=[profile_stationarity(h) for h in controls]
    # A fixed seeded ensemble, not a fragile single lucky realization. The former
    # TV gate accepted only 4/1000 stationary two-species controls at this size.
    assert sum(r['passed'] for r in results)>=850
    assert all(r['profile_statistic']=='maximum_cumulative_fraction_difference' for r in results)
    assert np.mean([r['total_variation_drift'] for r in results])>.1
    shifted=controls.copy()
    shifted[:,30:]=0
    shifted[:,30:,:,0]=10
    assert not any(profile_stationarity(h)['passed'] for h in shifted)
    too_sparse=np.ones((60,1,1))
    report=profile_stationarity(too_sparse)
    assert not report['passed'] and not report['sampling_sufficient']


def test_cumulative_profile_boundary_is_inclusive():
    samples=np.tile([[[5.,5.]]],(60,1,1))
    samples[30:]=[[[4.,6.]]]
    assert profile_stationarity(samples)['passed']
    samples[30:]=[[[3.,7.]]]
    assert not profile_stationarity(samples)['passed']
