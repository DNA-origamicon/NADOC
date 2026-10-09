import pytest
from experiments.cpd_anti_additive.resume_cube_v7 import partial_rows


def test_interrupted_log_uses_checkpoint_energy_not_uncheckpointed_tail(tmp_path):
    p=tmp_path/'run.log';p.write_text('ETITLE: TS POTENTIAL VOLUME\nENERGY: 1000 -12 20\nENERGY: 2000 -14 20\nENERGY: 3000 -99 20\n')
    assert partial_rows(p,1000,2000)[2000]['POTENTIAL']==-14
    assert 3000 not in partial_rows(p,1000,2000)


def test_missing_or_nonfinite_checkpoint_energy_fails_closed(tmp_path):
    p=tmp_path/'run.log'
    for body in ['ENERGY: 1000 -12 20\nENERGY: 3000 -14 20\n','ENERGY: 1000 nan 20\nENERGY: 2000 -14 20\n']:
        p.write_text('ETITLE: TS POTENTIAL VOLUME\n'+body)
        with pytest.raises(AssertionError):partial_rows(p,1000,2000)
