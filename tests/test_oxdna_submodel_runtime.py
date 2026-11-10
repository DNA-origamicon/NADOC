"""Native export/projection contracts; no authored NADOC structures."""

import numpy as np
import pytest

from backend.physics.oxdna_submodel import crop, expand_frame, remap_pair_forces, DisplayFrame
from backend.core.oxdna_submodel import estimate
from backend.core.oxdna_submodel_runner import Projector


def specimen():
    points=[[i-3,0,0] for i in range(7)]
    top="7 1\n"+"\n".join(f"1 A {i-1 if i else -1} {i+1 if i<6 else -1}" for i in range(7))+"\n"
    rows=[" ".join(map(str,[*p,1,0,0,0,0,1,0,0,0,0,0,0])) for p in points]
    conf="t = 0\nb = 30 30 30\nE = 0 0 0\n"+"\n".join(rows)+"\n"
    box=dict(min_corner=[-.1,-.1,-.1],max_corner=[.1,.1,.1],rotation=[0,0,0,1])
    small,frame,recipe=crop(top,conf,points,box,0)
    return conf,small,frame,recipe


def test_projection_preserves_context_and_source_indices():
    context,_,frame,recipe=specimen()
    rows=frame.splitlines()
    fields=rows[4].split();fields[1]="2";rows[4]=" ".join(fields)
    projected=expand_frame("\n".join(rows)+"\n",context,recipe).splitlines()
    assert len(projected)==10
    assert projected[6].split()[1]=="2"
    assert projected[3:6]==context.splitlines()[3:6]
    assert projected[7:]==context.splitlines()[7:]


def test_partial_frames_are_not_published_and_fixed_motion_is_rejected(tmp_path):
    context,top,frame,recipe=specimen()
    native=tmp_path/"native";stage=tmp_path/"stage";native.mkdir();stage.mkdir()
    (native/"conf.dat").write_text(frame)
    projector=Projector(native,stage,recipe,context)
    lines=frame.splitlines(keepends=True)
    (native/"trajectory.dat").write_text("".join(lines[:-1]))
    projector.sync()
    assert (stage/"trajectory.dat").read_text()==""
    (native/"trajectory.dat").write_text(frame)
    projector.sync()
    assert len((stage/"trajectory.dat").read_text().splitlines())==10
    projector.sync()
    assert len((stage/"trajectory.dat").read_text().splitlines())==10
    corrupt=frame.replace("-1 0 0","-2 0 0",1)
    with pytest.raises(ValueError,match="Fixed shell position"):
        projector.expand(corrupt)


def test_native_orthonormalization_is_not_mistaken_for_fixed_motion(tmp_path):
    context,_,frame,recipe=specimen()
    frame=frame.replace("1 0 0 0 0 1","1.000001 0 0 0 0 1")
    (tmp_path/"conf.dat").write_text(frame)
    p=Projector(tmp_path,tmp_path,recipe,context)
    p.expand(frame.replace("1.000001","1"))
    with pytest.raises(ValueError,match="orientation"):
        p.expand(frame.replace("1.000001 0 0","0 1 0"))


def test_pair_force_remapping_refuses_missing_mobile_partner():
    _,_,_,recipe=specimen()
    text="{\ntype = mutual_trap\nparticle = 3\nref_particle = 4\nstiff = 1\n}\n"
    result=remap_pair_forces(text,recipe)
    assert "particle = 1\n" in result and "ref_particle = 2\n" in result
    with pytest.raises(ValueError,match="partner"):
        remap_pair_forces(text.replace("ref_particle = 4","ref_particle = 6"),recipe)
    with pytest.raises(ValueError,match="pair traps only"):
        remap_pair_forces(text.replace("mutual_trap","trap"),recipe)


def test_estimates_keep_source_context_memory_and_cpu_vram_separate():
    _,_,_,recipe=specimen()
    small=estimate(recipe)
    full=estimate({**recipe,"retained_source_indices":list(range(7))})
    assert small["simulation_vram_bytes"]==0
    assert small["host_ram_budget_bytes"]>small["native_ram_estimate_bytes"]
    assert small["source_nucleotides"]==7 and small["simulated_nucleotides"]==3
    assert small["md_steps_per_second"]>full["md_steps_per_second"]


def test_fixed_context_controls_alignment_even_when_mobile_points_move():
    from backend.physics.oxdna_interface import unwrap_align_to_reference
    keys=[("h",i,"fwd") for i in range(4)]
    positions=[[0,0,0],[1,0,0],[0,1,0],[.5,.5,0]]
    ref={k:dict(backbone_position=np.array(p,dtype=float),a1=np.array([1.,0,0]),a3=np.array([0.,0,1])) for k,p in zip(keys,positions)}
    moved=DisplayFrame({k:{**v,"backbone_position":v["backbone_position"].copy()} for k,v in ref.items()})
    moved[keys[-1]]["backbone_position"]+=np.array([3,3,0])
    moved.submodel_fixed_keys=tuple(keys[:3])
    actual=unwrap_align_to_reference(moved,ref,None,np.array([100.,100,100]),adj={k:[] for k in keys})
    for k in keys[:3]:
        np.testing.assert_allclose(actual[k]["backbone_position"],ref[k]["backbone_position"],atol=1e-12)
    np.testing.assert_allclose(actual[keys[-1]]["backbone_position"],[3.5,3.5,0],atol=1e-12)


def test_production_inherits_frozen_identities_but_explicit_clear_does_not(tmp_path):
    import json
    from backend.api.routes_oxdna import _inherit_submodel_selection
    from backend.api.simulation_submodel import SubmodelSelection, save_selection
    from backend.core.oxdna_submodel import fingerprint
    parent=tmp_path/'parent';parent.mkdir()
    child=tmp_path/'child';child.mkdir()
    cleared=tmp_path/'clear';cleared.mkdir()
    box=dict(shape='box',min_corner=[0,0,0],max_corner=[1,1,1],rotation=[0,0,0,1],shell_nm=3,visible=True)
    selection=SubmodelSelection(box=box)
    stored=save_selection(parent,selection)['box']
    recipe={'selection_fingerprint':fingerprint(stored),'mobile_source_indices':[2,3]}
    (parent/'submodel_plan.json').write_text(json.dumps(recipe))
    (parent/'submodel_topology.top').write_text('native topology sentinel')
    _inherit_submodel_selection(parent,child,None)
    assert json.loads((child/'submodel_plan.json').read_text())==recipe
    assert (child/'submodel_topology.top').read_bytes()==(parent/'submodel_topology.top').read_bytes()
    _inherit_submodel_selection(parent,cleared,SubmodelSelection(box=None))
    assert not (cleared/'submodel_plan.json').exists()
    assert json.loads((cleared/'submodel_selection.json').read_text())=={'box':None}


def test_running_selection_allows_visibility_but_not_region_change(tmp_path,monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from fastapi import HTTPException
    from backend.api import routes_oxdna as routes
    from backend.api.simulation_submodel import SubmodelSelection, save_selection
    job=SimpleNamespace(status='running',job_dir=lambda ws:tmp_path)
    monkeypatch.setattr(routes,'_load_job',lambda _:job)
    monkeypatch.setattr(routes,'_workspace',lambda:tmp_path)
    box=dict(min_corner=[0,0,0],max_corner=[1,1,1],rotation=[0,0,0,1])
    save_selection(tmp_path,SubmodelSelection(box=box))
    result=asyncio.run(routes.put_oxdna_submodel('job',SubmodelSelection(box={**box,'visible':False})))
    assert result['box']['visible'] is False
    with pytest.raises(HTTPException,match='Stop the job'):
        asyncio.run(routes.put_oxdna_submodel('job',SubmodelSelection(box={**box,'shell_nm':0})))


def test_partial_job_cannot_silently_switch_to_full_model(tmp_path):
    from types import SimpleNamespace
    from backend.core.oxdna_submodel import preflight
    native=tmp_path/'stage/submodel';native.mkdir(parents=True)
    (native/'extraction.json').write_text('{}')
    job=SimpleNamespace(job_dir=lambda _:tmp_path,stage_dir=lambda ws,name:tmp_path/name,
                        stages=[SimpleNamespace(name='stage',status='stopped')])
    with pytest.raises(ValueError,match='remove its submodel'):
        preflight(job,tmp_path,[])


def test_preflight_freezes_identities_and_cpu_protocol_and_checks_source(tmp_path,monkeypatch):
    import hashlib
    from types import SimpleNamespace
    from backend.core import oxdna_submodel as managed
    from backend.core.oxdna_protocol import OxdnaStageSpec
    from backend.api.simulation_submodel import SubmodelSelection, save_selection
    conf,top,frame,recipe=specimen()
    box=dict(min_corner=[-.1,-.1,-.1],max_corner=[.1,.1,.1],rotation=[0,0,0,1])
    stored=save_selection(tmp_path,SubmodelSelection(box=box))['box']
    # Opaque sentinels: plan is mocked; this test does not author a Design.
    for name in ('topology.top','design.json'):(tmp_path/name).write_text('source sentinel')
    digest=hashlib.sha256(b'source sentinel').hexdigest()
    recipe.update(selection_fingerprint=managed.fingerprint(stored),source_topology_sha256=digest,source_design_sha256=digest)
    monkeypatch.setattr(managed,'installation',lambda:{})
    calls=[]
    def plan(*args):
        calls.append(args)
        return top,frame,recipe
    monkeypatch.setattr(managed,'plan',plan)
    job=SimpleNamespace(job_dir=lambda _:tmp_path,stage_dir=lambda ws,name:tmp_path/name,
        stages=[SimpleNamespace(name='stage',status='queued')],current_stage_idx=0,execution_target='local')
    spec=OxdnaStageSpec(name='stage',kind='production',sim_type='MD',steps=1000,backend='CUDA',min_bp_retained=.8)
    effective=managed.preflight(job,tmp_path,[spec])[0]
    assert effective.backend=='CPU' and effective.thermostat=='brownian'
    assert effective.min_bp_retained==.8 and effective.dt==spec.dt
    assert job.submodel['simulated_nucleotides']==3
    save_selection(tmp_path,SubmodelSelection(box={**stored,'visible':False}))
    managed.preflight(job,tmp_path,[spec])
    assert len(calls)==1
    (tmp_path/'topology.top').write_text('changed source')
    with pytest.raises(ValueError,match='source changed'):
        managed.preflight(job,tmp_path,[spec])


def test_eta_counts_work_instead_of_initial_energy_row_and_resumed_budget():
    from backend.core.oxdna_submodel import attempt_fraction
    from backend.core.oxdna_protocol import OxdnaStageSpec
    spec=OxdnaStageSpec(name="production",kind="production",sim_type="MD",steps=200000,backend="CPU")
    assert attempt_fraction(spec,0,1)==0
    assert attempt_fraction(spec,0,2)==.01
    assert attempt_fraction(spec,2000,2)==pytest.approx(2000/198000)
    assert attempt_fraction(spec,2000,100)==1


def test_stage_input_uses_conditional_dna2_for_md_mc_and_analysis(tmp_path):
    from backend.core.oxdna_protocol import OxdnaStageSpec
    from backend.core.oxdna_submodel_runner import stage_input
    for sim_type in ('MD','MC'):
        spec=OxdnaStageSpec(name='stage',kind=sim_type.lower(),sim_type=sim_type,steps=100,backend='CPU')
        text=stage_input(spec,tmp_path,{'plugins':'/plugins'},tmp_path/'sequence.txt')
        assert 'interaction_type = SubmodelDNA2\n' in text
        assert text.count('plugin_search_path = ')==1
        assert f'submodel_mobile_file = {tmp_path / "mobile.txt"}\n' in text
        assert 'max_backbone_force =' not in text


def test_failure_diagnostic_reports_recorded_submodel_binary(tmp_path,monkeypatch):
    import asyncio,json
    from types import SimpleNamespace
    from backend.api import routes_oxdna as routes
    stage=SimpleNamespace(name='1_production',kind='production',status='failed')
    job=SimpleNamespace(job_id='job',submodel={'backend':'CPU'},backend='CPU',status='failed',
                        error='native failure',stages=[stage],current_stage_idx=0,stage_dir=lambda ws,name:tmp_path)
    (tmp_path/'submodel').mkdir()
    (tmp_path/'submodel/execution.json').write_text(json.dumps({'binary':'/recorded/submodel-adapter'}))
    monkeypatch.setattr(routes,'_load_job',lambda _:job)
    monkeypatch.setattr(routes,'_workspace',lambda:tmp_path)
    monkeypatch.setattr(routes,'find_oxdna',lambda:'/standard/oxDNA')
    result=asyncio.run(routes.get_oxdna_error_log('job'))
    assert result['diagnostics']['oxdna_bin']=='/recorded/submodel-adapter'
    assert result['diagnostics']['cuda_capable'] is False
