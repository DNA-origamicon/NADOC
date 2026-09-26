import math
from experiments.cpd_anti_additive.optimization_guard import assess, native_rows


def row(i, f=.001, step=.0001, energy=-10):
    return dict(iteration=i,energy=energy,max_force=f,rms_force=f/3,max_step=step)


def test_stall_and_progress_distinguished():
    assert assess([row(i) for i in range(12)]) == 'stalled_large_force_tiny_steps'
    assert assess([row(i,f=.01*.8**i) for i in range(12)]) == 'continue'


def test_near_convergence_small_steps_not_stall():
    assert assess([row(i,f=1e-5) for i in range(12)]) == 'continue'


def test_single_bad_step_can_recover_but_persistent_excursion_stops():
    base=[row(i,f=.00002,step=.001) for i in range(12)]
    bad=[row(i,f=.1,step=.2,energy=-9.9) for i in range(3)]
    assert assess(base+bad[:1]) == 'continue'
    assert assess(base+bad) == 'sustained_excursion'


def test_nonfinite_and_budget_are_not_success():
    assert assess([row(1,energy=math.nan)]) == 'nonfinite'
    assert assess([row(i,f=1e-6) for i in range(60)]) == 'evaluation_budget'


def test_native_parser_deduplicates_summaries_and_ignores_partial():
    line=' 12 -1364.50569940 -1e-8 o 3.09e-6 * 5.73e-7 * 3.01e-4 6.28e-5 ~\n'
    rows=native_rows(line+line+' 13 -1364.50')
    assert len(rows)==1
    assert rows[0]['max_force']==3.09e-6
    assert rows[0]['max_step']==3.01e-4


def test_unapplied_optimizer_options_fail_closed():
    from types import SimpleNamespace
    import pytest
    from experiments.cpd_anti_additive.optimization_guard import EFFECTIVE, verify_options
    assert verify_options(SimpleNamespace(**EFFECTIVE)) == EFFECTIVE
    with pytest.raises(RuntimeError, match='not applied'):
        verify_options(SimpleNamespace(**dict(EFFECTIVE, intrafrag_trust=.5)))
