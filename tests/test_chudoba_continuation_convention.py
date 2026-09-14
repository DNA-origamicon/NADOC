"""Legacy raw continuation plans must never silently become another Hamiltonian."""
import importlib
import json
import sys
import pytest


@pytest.mark.parametrize('kind',['chain','eos'])
@pytest.mark.parametrize('cutoff',['raw','zero_tail'])
def test_legacy_plan_cutoff_guard(tmp_path,monkeypatch,kind,cutoff):
    module=importlib.import_module(f'experiments.peg_chudoba.run_{kind}_extensions')
    plan={'allocations':[]}
    if kind=='eos':plan['settings']={'n':135,'temperature':294,'pressure_kpa':1,'steps':20000}
    path=tmp_path/'plan.json';original=json.dumps(plan);path.write_text(original)
    monkeypatch.setattr(sys,'argv',['run','--output',str(tmp_path),'--plan-only','--cutoff',cutoff])
    if cutoff=='raw':module.main()
    else:
        with pytest.raises(ValueError):module.main()
    assert path.read_text()==original


def test_reservations_separate_generations_and_hamiltonians(tmp_path):
    from experiments.peg_chudoba.run_chain_extensions import reserved_chain_generations
    for name,cutoff,generation in [('legacy',None,1),('current','zero_tail',1),('next','zero_tail',2)]:
        directory=tmp_path/name;directory.mkdir()
        plan={'allocations':[{'n':76,'temperature':320,'generation':generation,'replica_id':201}]}
        if cutoff:plan['cutoff']=cutoff
        (directory/'plan.json').write_text(json.dumps(plan))
    reserved=reserved_chain_generations(tmp_path)
    assert set(reserved)=={('raw',76,320,1),('zero_tail',76,320,1),('zero_tail',76,320,2)}
    assert reserved['zero_tail',76,320,1]=={str(tmp_path/'current/plan.json')}
