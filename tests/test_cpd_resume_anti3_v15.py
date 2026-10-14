from pathlib import Path
from types import SimpleNamespace
import pytest
from experiments.cpd_anti_additive import resume_anti3_v15 as resume

@pytest.mark.parametrize('energy,passes',[(-100.,True),(-90.,False)])
def test_exact_checkpoint_energy_and_remaining_interval(tmp_path,monkeypatch,energy,passes):
    plan={'audit':'audit','output':str(tmp_path/'new'),'seed':116037,'deadline_epoch':123}
    audit={'passed':True,'checkpoint':{'prefix':'/checkpoint.5050000'},'checkpoint_potential':-100.}
    monkeypatch.setattr(resume,'read',lambda p:plan if p=='plan' else audit)
    monkeypatch.setattr(resume,'checked',lambda p:p)
    monkeypatch.setattr(resume,'admission',lambda p:p)
    calls=[]
    def native(out,cfg,*args):
        calls.append((out,cfg));return [{'POTENTIAL':energy}]
    def review(case,out,first,steps,stride,*args):
        assert (case,first,steps,stride)==('anti',5050000,480000,5000)
        return {}
    engine=SimpleNamespace(native=native,config=lambda case,coor,first,seed,cp,*args:f'{case} {first} {seed}\n',review=review,endpoint_reference=lambda *args:{})
    monkeypatch.setattr(resume,'load_engine',lambda p:engine)
    monkeypatch.setattr(resume,'save',lambda *args:None)
    monkeypatch.setattr(resume,'source',lambda p:str(p))
    if passes:
        resume.run('plan')
        assert len(calls)==2 and 'run 480000\n' in calls[1][1]
        assert calls[1][0].name=='segment-10-remainder'
        with pytest.raises(FileExistsError):resume.run('plan')
    else:
        with pytest.raises(AssertionError):resume.run('plan')
        assert len(calls)==1
