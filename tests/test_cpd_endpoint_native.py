import pytest

from experiments.cpd_anti_additive.endpoint_native import require_fitting_condition


@pytest.mark.parametrize('field', ['        1E-10', '       1E-10', '\t1.00e-10', ' 1D-10'])
def test_fitting_condition_accepts_numeric_equivalents(field):
    assert require_fitting_condition('Fitting Condition:'+field)==[1e-10]


@pytest.mark.parametrize('text', ['', 'Fitting Condition: 1E-7',
    'Fitting Condition: 1E-10\nFitting Condition: 1E-8', 'Fitting Condition: NaN'])
def test_fitting_condition_rejects_absent_or_changed_value(text):
    with pytest.raises(ValueError,match='missing or changed'):
        require_fitting_condition(text)


def test_endpoint_chunk_reserves_timeout_and_stops_at_allocation():
    from experiments.cpd_anti_additive.corrected_endpoint_optimization import admit,ChunkBoundary
    plan=dict(max_new_gradients=30,task_timeout_seconds=600)
    admit(29,631,plan)
    with pytest.raises(ChunkBoundary,match='allocation'):
        admit(30,900,plan)
    with pytest.raises(ChunkBoundary,match='checkpoint'):
        admit(0,630,plan)
