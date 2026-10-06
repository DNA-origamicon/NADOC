import time
import pytest
from experiments.cpd_anti_additive import gpu_cube_preparation_v6 as m


def test_admission_rejects_expired_oversized_or_changed_inputs(tmp_path):
    evidence = tmp_path/'input'; evidence.write_text('frozen')
    plan = dict(authorized=True, hard_seconds=10800, deadline_epoch=time.time()+100, inputs=[m.source(evidence)])
    assert m.admission(plan) is plan
    for change in [dict(authorized=False), dict(hard_seconds=57600), dict(hard_seconds=0), dict(deadline_epoch=0)]:
        with pytest.raises(ValueError):
            m.admission(dict(plan, **change))
    evidence.write_text('changed')
    with pytest.raises(ValueError):
        m.admission(plan)


def test_final_cube_dimensions_and_full_cell_restart():
    root = m.REPO/'.development-artifacts/cpd-anti-gpu-cube-context-v5'
    if not (root/'assembly.json').exists():
        pytest.skip('Local campaign evidence unavailable')
    plan = dict(root=str(root), case='anti', engine=m.source(m.REPO/'experiments/cpd_anti_additive/gpu_cube_diagnostic_v5.py'))
    engine = m.load_engine(plan)
    assert (engine.N, engine.NW, engine.NSOL) == (265477, 87289, 3043)
    assert engine.MASS == pytest.approx(1617952.3015)
    cfg = engine.config('anti', root/'anti/start.coor', cp=root/'checkpoint', npt=True)
    assert 'extendedSystem ' in cfg and 'cellBasisVector' not in cfg
    for value in ['PMEGridSizeX 144', 'PMEGridSizeY 144', 'PMEGridSizeZ 144', 'restartfreq 50000', 'restartsave yes', 'GPUresident on', 'vdwForceSwitching on', 'LangevinPiston on', 'timestep 2']:
        assert value+'\n' in cfg
