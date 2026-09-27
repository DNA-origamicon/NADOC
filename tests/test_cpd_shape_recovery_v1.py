"""Memory repair cannot silently authorize a restart or extend the original clock."""
import json
import pytest
from experiments.cpd_anti_additive import shape_fit_isolated_recovery_v1 as repair
from experiments.cpd_anti_additive.validation_gate import source


def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(repair,'PREP',tmp_path)
    plan={'original_absolute_fit_deadline_epoch':200.}
    (tmp_path/'recovery_plan.json').write_text(json.dumps(plan))
    auth=dict(authorized=True,action='recover_interrupted_round_two',user_instruction='Resume the interrupted round with this repair.',
        recovery_plan_sha256=source(tmp_path/'recovery_plan.json')['sha256'])
    return plan,auth


@pytest.mark.parametrize('auth',[{}, {'authorized':True}, {'authorized':False,'action':'recover_interrupted_round_two'}])
def test_no_implicit_recovery_authorization(tmp_path,monkeypatch,auth):
    plan,_=setup(tmp_path,monkeypatch)
    with pytest.raises(RuntimeError,match='Explicit recovery authorization'):repair.require_recovery_authorization(auth,plan,100.)


def test_approval_must_pin_plan_and_retain_original_deadline(tmp_path,monkeypatch):
    plan,auth=setup(tmp_path,monkeypatch)
    repair.require_recovery_authorization(auth,plan,199.)
    with pytest.raises(RuntimeError,match='deadline has passed'):repair.require_recovery_authorization(auth,plan,200.)
    auth['recovery_plan_sha256']='different'
    with pytest.raises(RuntimeError,match='identify this plan'):repair.require_recovery_authorization(auth,plan,100.)
