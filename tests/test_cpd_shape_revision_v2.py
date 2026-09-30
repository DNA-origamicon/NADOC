"""A closed candidate cannot erase exposure or reset the final fit allowance."""
import json
import pytest
from experiments.cpd_anti_additive import shape_fit_protocol_v2 as revision
from experiments.cpd_anti_additive import preliminary_protocol as old
from experiments.cpd_anti_additive.validation_gate import source


def write(path,value):
    path.write_text(json.dumps(value))


def setup(tmp_path,monkeypatch):
    parent=tmp_path/'parent';state=tmp_path/'revision';parent.mkdir();state.mkdir()
    pause=tmp_path/'pause.json';write(pause,{'paused':False});monkeypatch.setattr(old,'PAUSE',pause)
    write(parent/'activation.json',dict(user_authorized_resume=True,policy=source(old.POLICY)))
    write(parent/'conformational_candidate_lock.json',{'further_fitting_blocked':True})
    rounds=[dict(round=1,output=str(parent/'fit'),policy=source(old.POLICY))]
    write(parent/'conformational_rounds.json',rounds);write(state/'conformational_rounds.json',rounds)
    write(parent/'closeout.json',dict(all_four_QM_constrained_stationarity_passed=True,fit_rounds_used=1,exposed_case_ids=['old','observed-validation']))
    write(state/'activation.json',dict(user_authorized_resume=True,policy=source(old.POLICY)))
    receipt=tmp_path/'receipt.json'
    write(receipt,dict(stage='conformational',ready=True,revision='shape-v2.2',case_ids=['old','observed-validation'],
        max_campaign_rounds=2,original_candidate_lock=source(parent/'conformational_candidate_lock.json'),artifacts=[source(parent/'closeout.json')]))
    old.lock_inputs('conformational',receipt,state)
    write(parent/'conformational_successor.json',dict(state=str(state),input_lock=source(state/'conformational_input_lock.json')))
    output=tmp_path/'fit2'
    write(state/'lineage.json',dict(parent_state=str(parent),successor_claim=source(parent/'conformational_successor.json'),
        parent_candidate_lock=source(parent/'conformational_candidate_lock.json'),parent_rounds=source(parent/'conformational_rounds.json'),
        parent_closeout=source(parent/'closeout.json'),parent_activation=source(parent/'activation.json'),output=str(output)))
    write(state/'conformational_second_round_review.json',dict(prior_result=source(parent/'closeout.json'),authorized=True,rationale='Recorded shape regression'))
    write(state/'registration.json',dict(files=[source(state/n) for n in ('lineage.json','activation.json','conformational_input_lock.json','conformational_second_round_review.json')]))
    return parent,state,output,pause,receipt


def test_only_remaining_round_and_original_lock_preserved(tmp_path,monkeypatch):
    parent,state,out,_,_=setup(tmp_path,monkeypatch)
    before=source(parent/'conformational_candidate_lock.json')
    assert revision.begin_round(out,state)[2]==2
    with pytest.raises(RuntimeError,match='exhausted'):revision.begin_round(out,state)
    assert source(parent/'conformational_candidate_lock.json')==before
    assert len(json.loads((parent/'conformational_rounds.json').read_text()))==1


@pytest.mark.parametrize('replacement',[[],[{'round':1,'output':'different'}],[{}, {}, {}]])
def test_reset_or_expanded_ledger_rejected(tmp_path,monkeypatch,replacement):
    _,state,_,_,_=setup(tmp_path,monkeypatch)
    write(state/'conformational_rounds.json',replacement)
    with pytest.raises(RuntimeError,match='reset or expanded'):revision.require_fit_ready(state=state)


def test_pause_changed_exposure_and_wrong_output_fail_closed(tmp_path,monkeypatch):
    _,state,out,pause,receipt=setup(tmp_path,monkeypatch)
    with pytest.raises(RuntimeError,match='Unregistered fit output'):revision.begin_round(out/'other',state)
    write(pause,{'paused':True})
    with pytest.raises(RuntimeError,match='paused'):revision.require_fit_ready(state=state)
    write(pause,{'paused':False});data=json.loads(receipt.read_text());data['case_ids']=['old'];write(receipt,data)
    with pytest.raises(ValueError,match='Changed evidence'):revision.require_fit_ready(state=state)


def test_alternate_successor_rejected(tmp_path,monkeypatch):
    parent,state,_,_,_=setup(tmp_path,monkeypatch)
    write(parent/'conformational_successor.json',dict(state=str(state/'alternate')))
    with pytest.raises(RuntimeError,match='Successor claim changed'):revision.require_fit_ready(state=state)
