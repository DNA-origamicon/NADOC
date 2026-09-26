import json
import math
import pytest
from experiments.cpd_anti_additive import validation_gate as gate


def fixture(tmp_path):
    policy = gate.read(gate.POLICY)
    policy['cases'] = [dict(id='p',kind='profile',role='development',endpoint=2)]
    pp = tmp_path/'policy.json'; pp.write_text(json.dumps(policy))
    native = tmp_path/'native.dat';native.write_text('native evidence')
    review = tmp_path/'review.json'
    data = dict(case_id='p', artifacts=[gate.source(native)], checks=dict(native_audit_passed=True,method_and_atom_map_match=True,stereo_preserved=True,all_seed_families_checked=True,bidirectional_closure_passed=True,no_unresolved_branches=True),metrics=dict(qm_max_gradient_au=1e-6,qm_rms_gradient_au=1e-6,closure_energy_kcal=.01,torsion_constraint_deg=.001))
    review.write_text(json.dumps(data))
    packet = tmp_path/'packet.json'
    def save():
        review.write_text(json.dumps(data));packet.write_text(json.dumps(dict(policy_sha256=gate.digest(pp),references={'2':dict(id='ref',qm_energy=0.,qm_geometry=gate.source(native))},records=[dict(case_id='p',review=gate.source(review))])))
    save()
    return pp,packet,data,save,native


def test_valid_acquisition_does_not_promote(tmp_path):
    pp,p,*_=fixture(tmp_path);r=gate.evaluate(pp,p)
    assert r['passed'] and not r['simulation_ready'] and not r['product_promotion_authorized']


def test_missing_coverage_blocks(tmp_path):
    pp,p,*_=fixture(tmp_path);x=gate.read(p);x['records']=[];p.write_text(json.dumps(x))
    assert not gate.evaluate(pp,p)['passed']


@pytest.mark.parametrize('value',[float('nan'),float('inf'),True,-1])
def test_invalid_gradient_never_passes(tmp_path,value):
    pp,p,data,save,_=fixture(tmp_path);data['metrics']['qm_max_gradient_au']=value;save()
    assert not gate.evaluate(pp,p)['passed']


def test_changed_native_hash_blocks(tmp_path):
    pp,p,_,_,native=fixture(tmp_path);native.write_text('changed')
    assert not gate.evaluate(pp,p)['passed']


def test_budget_completion_not_basin_closure(tmp_path):
    pp,p,data,save,_=fixture(tmp_path);data['checks']['bidirectional_closure_passed']=False;save()
    assert not gate.evaluate(pp,p)['passed']


def test_holdout_not_required_for_fit_but_required_for_candidate(tmp_path):
    pp,p,*_=fixture(tmp_path);policy=gate.read(pp);policy['cases'].append(dict(id='blind',kind='profile',role='holdout',endpoint=2));pp.write_text(json.dumps(policy));packet=gate.read(p);packet['policy_sha256']=gate.digest(pp);p.write_text(json.dumps(packet))
    assert gate.evaluate(pp,p)['passed']
    assert not gate.evaluate(pp,p,'candidate')['passed']


def test_no_lock_blocks_fitting(tmp_path,monkeypatch):
    monkeypatch.setattr(gate,'STATE',tmp_path)
    with pytest.raises(RuntimeError,match='not frozen'):gate.require_fit_ready()


def test_geometry_rotation_invariant_but_reflection_not_allowed():
    import numpy as np
    q=np.array([[0.,0.,0.],[1.,0.,0.],[1.,1.,0.],[1.,1.,1.]])
    rot=np.array([[0.,-1.,0.],[1.,0.,0.],[0.,0.,1.]])
    good=gate.geometry_match(q,q@rot+3,['C']*4,[[0,1,2,3]])
    reflected=gate.geometry_match(q,q*np.array([-1,1,1]),['C']*4,[[0,1,2,3]])
    assert good['basin_rmsd_A']<1e-12
    assert reflected['basin_max_torsion_deg']>20


def candidate_fixture(tmp_path):
    pp,p,data,save,native=fixture(tmp_path)
    data['checks'].update(all_heavy_torsions_checked=True,same_reference_identity=True,mm_multistart_complete=True)
    data['metrics'].update(mm_max_gradient_au=1e-8,mm_rms_gradient_au=1e-8,basin_rmsd_A=.1,basin_max_torsion_deg=5.,bond_error_A=.01,angle_error_deg=1.,mm_energy=2.,qm_energy=2.,mm_reference_energy=0.,qm_reference_energy=0.)
    data['reference_id']='ref'
    bundle=tmp_path/'bundle.json';bundle.write_text(json.dumps(dict(artifacts=[gate.source(native)])))
    lock=tmp_path/'lock.json';lock.write_text('{}')
    receipt=tmp_path/'receipt.json';receipt.write_text(json.dumps(dict(policy_sha256=gate.digest(pp),parameters=gate.source(bundle),dataset_lock=gate.source(lock))))
    data['candidate_sha256']=gate.digest(bundle)
    def candidate_save():
        save();packet=gate.read(p);acquisition=tmp_path/'acquisition.json';acquisition.write_text(json.dumps(packet));lock.write_text(json.dumps(dict(policy=gate.source(pp),packet=gate.source(acquisition))));receipt.write_text(json.dumps(dict(policy_sha256=gate.digest(pp),parameters=gate.source(bundle),dataset_lock=gate.source(lock))));packet['references']['2']['mm_energy']=0.;packet.update(candidate=dict(parameters=gate.source(bundle),freeze_receipt=gate.source(receipt),training_case_ids=['p'],fit_round=1,frozen_before_holdout=True,holdout_used_for_fit=False));p.write_text(json.dumps(packet))
    candidate_save()
    return pp,p,data,candidate_save


def test_candidate_metrics_can_pass_without_authorizing_product(tmp_path):
    pp,p,*_=candidate_fixture(tmp_path);r=gate.evaluate(pp,p,'candidate')
    assert r['passed'] and not r['simulation_ready']


def test_zero_energy_error_cannot_hide_basin_mismatch(tmp_path):
    pp,p,data,save=candidate_fixture(tmp_path);data['metrics']['basin_max_torsion_deg']=93.;save()
    assert not gate.evaluate(pp,p,'candidate')['passed']


def test_independent_energy_rezeroing_rejected(tmp_path):
    pp,p,data,save=candidate_fixture(tmp_path);data['metrics']['mm_reference_energy']=5.;data['metrics']['mm_energy']=7.;save()
    assert not gate.evaluate(pp,p,'candidate')['passed']


def test_energy_rmse_checked_even_below_per_case_max(tmp_path):
    pp,p,data,save=candidate_fixture(tmp_path);data['metrics']['mm_energy']=3.5;save()
    assert not gate.evaluate(pp,p,'candidate')['passed']


def test_unknown_or_duplicate_cases_block(tmp_path):
    pp,p,*_=fixture(tmp_path);x=gate.read(p);x['records']*=2;p.write_text(json.dumps(x))
    assert not gate.evaluate(pp,p)['passed']


def test_launcher_blocks_fit_before_creating_service(tmp_path,monkeypatch):
    from experiments.cpd_anti_additive import launch as launcher
    launch = launcher.launch
    monkeypatch.setattr(launcher,'REPO',tmp_path)
    monkeypatch.setattr(gate,'STATE',tmp_path/'state')
    service=tmp_path/'service'
    with pytest.raises(RuntimeError,match='not frozen'):
        launch(service,'must-not-launch',['python','refine_joint.py'],60)
    assert not service.exists()


def test_user_pause_blocks_acquisition_before_service_creation(tmp_path,monkeypatch):
    from experiments.cpd_anti_additive import launch as launcher
    monkeypatch.setattr(launcher,'REPO',tmp_path)
    pause=tmp_path/'.development-artifacts/cpd-anti-validation-v1/campaign_pause.json'
    pause.parent.mkdir(parents=True);pause.write_text('{"paused": true}')
    with pytest.raises(RuntimeError,match='paused by user'):
        launcher.launch(tmp_path/'service','no-launch',['python','geometric_pilot.py'],60)
    assert not (tmp_path/'service').exists()
