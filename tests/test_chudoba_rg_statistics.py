import numpy as np
from experiments.peg_chudoba.rg_statistics import summarize_rms


def test_rms_observable_and_units():
    rng=np.random.default_rng(882)
    traces=[rng.uniform(.5,2.5,6000) for _ in range(3)]
    result=summarize_rms(traces)
    expected=np.sqrt(np.mean([np.mean(x*x) for x in traces]))
    assert abs(result['rms_rg_nm']-expected)<1e-12
    assert result['rms_rg_nm']>np.mean(traces)+.05
    scaled=summarize_rms([x*3 for x in traces])
    assert np.isclose(scaled['rms_rg_nm'],3*result['rms_rg_nm'])
    assert np.isclose(scaled['conservative_sem_nm'],3*result['conservative_sem_nm'])
    assert np.isclose(scaled['minimum_seed_effective_samples'],result['minimum_seed_effective_samples'])


def test_separated_replicas_increase_uncertainty_and_fail_convergence():
    rng=np.random.default_rng(41)
    result=summarize_rms([rng.normal(mu,.01,2000) for mu in (1,2,3)])
    assert result['conservative_sem_nm']>.4
    assert result['extension_recommended']
    assert result['rank_folded_split_rhat']>1.01
