import json
import pytest
from experiments.cpd_anti_additive.audit_cube_preparation_v6 import unique_step_rows
from experiments.cpd_anti_additive.launch_cube_preparation_v6 import reviewed_predecessors
from experiments.cpd_anti_additive.validation_gate import source


def test_thermodynamic_sampling_does_not_double_count_run_boundaries():
    rows = [dict(TS=0,TEMP=0),dict(TS=500,TEMP=100),dict(TS=500,TEMP=100),dict(TS=1000,TEMP=200)]
    got = unique_step_rows(rows)
    assert [r['TS'] for r in got] == [0,500,1000]
    assert sum(r['TEMP'] for r in got[1:])/2 == 150


def test_successor_fails_closed_without_review_or_with_altered_audit(tmp_path):
    replica = tmp_path/'anti/replica-1'; replica.mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        reviewed_predecessors(tmp_path,'control',1)
    audit = replica/'audit.json'; audit.write_text('{"passed": true}')
    review = replica/'completion_review.json'
    review.write_text(json.dumps(dict(approved_for_next_run=False,audit=source(audit))))
    with pytest.raises(AssertionError):
        reviewed_predecessors(tmp_path,'control',1)
    review.write_text(json.dumps(dict(approved_for_next_run=True,audit=source(audit))))
    assert len(reviewed_predecessors(tmp_path,'control',1)) == 2
    audit.write_text('{"passed": false}')
    with pytest.raises(ValueError):
        reviewed_predecessors(tmp_path,'control',1)
    with pytest.raises((ValueError,FileNotFoundError)):
        reviewed_predecessors(tmp_path,'anti',2)
