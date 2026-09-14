"""Scheduling decisions must not favor incomplete or unstable timing matrices."""
import pytest

from experiments.peg_chudoba.benchmark_scheduling import select_strategies


def batches(speedup):
    rows = []
    for name in ('pivot_n795', 'npt_p10', 'npt_p1000', 'gpu_n36', 'gpu_n795'):
        for round_index in range(2):
            for concurrency in ((1, 2) if name.startswith('gpu') else (1, 2, 4)):
                rows.append(dict(workload=name, round=round_index, concurrency=concurrency,
                                 makespan_seconds=100 / speedup(concurrency, round_index)))
    return rows


def test_select_aggregate_throughput_and_prefer_near_tie():
    selected = select_strategies(batches(lambda c, r: {1: 1, 2: 1.9, 4: 1.95}[c]))
    assert all(row['concurrency'] == 2 for row in selected.values())


def test_do_not_select_speedup_that_reverses_in_second_round():
    selected = select_strategies(batches(lambda c, r: 1 if c == 1 else (3 if r == 0 else .9)))
    assert all(row['concurrency'] == 1 for row in selected.values())


def test_missing_workload_prevents_selection():
    rows = batches(lambda c, r: c)
    with pytest.raises(ValueError, match='Incomplete'):
        select_strategies(rows[:-1])


def test_uncertainty_must_fit_inside_engineering_band():
    from experiments.peg_chudoba.validate_narrow import agreement
    # Matching means with excessive uncertainty is not an engineering pass.
    assert not agreement(1.,.08,1.)['engineering_agreement']
    assert agreement(1.05,.01,1.)['engineering_agreement']
    assert not agreement(1.09,.02,1.)['engineering_agreement']


def test_periodic_interchain_contact_count(tmp_path):
    import json
    from experiments.peg_chudoba.validate_narrow import contacts
    (tmp_path/'run.json').write_text(json.dumps(dict(n=2,particles=4)))
    xyz = [(0.1,1,1),(4,1,1),(9.9,1,1),(6,1,1)]
    rows = [' '.join(str(v/.8518) for v in p)+'\n' for p in xyz]
    box = 10/.8518
    (tmp_path/'trajectory.dat').write_text(f't = 0\nb = {box} {box} {box}\nE = 0 0 0\n'+''.join(rows))
    assert contacts(tmp_path).tolist() == [.25]


def test_frozen_solution_trace_cannot_pass_sampling():
    import numpy as np
    from experiments.peg_chudoba.validate_narrow import scalar_stats
    result = scalar_stats([np.ones(100) for _ in range(3)])
    assert not result['sampling_pass']
    assert result['minimum_ess'] == 0
    assert result['rhat'] is None


def test_non_owner_cannot_restore_a_live_lease(tmp_path,monkeypatch):
    import json
    import sys
    from experiments.peg_chudoba import scheduling_lease as module
    path = tmp_path/'lease.json'
    original = json.dumps(dict(owner=dict(pid=100,start='1'),status='parked'))
    path.write_text(original)
    monkeypatch.setattr(sys,'argv',['lease','restore','--state',str(path)])
    monkeypatch.setattr(module,'alive',lambda record:True)
    monkeypatch.setattr(module,'process',lambda pid:dict(pid=200,start='2'))
    with pytest.raises(RuntimeError,match='Only the live lease owner'):
        module.main()
    assert path.read_text() == original


def test_cpu12_requires_consistent_scaling_and_matched_endpoints():
    from experiments.peg_chudoba.scale_cpu import select
    rows = [dict(pressure=p,repeat=r,concurrency=c,seconds=300 if c==4 else 105,
                 runs=[dict(final_sha256=str(i)) for i in range(12)])
            for p in (10,1000) for r in (0,1) for c in (4,12)]
    assert select(rows)['concurrency']==12
    rows[-1]['seconds']=140
    assert select(rows)['concurrency']==4
    rows[-1]['runs'][0]['final_sha256']='changed'
    with pytest.raises(ValueError,match='endpoints'):
        select(rows)
    with pytest.raises(ValueError,match='Incomplete'):
        select(rows[:-1])


def test_handover_records_new_owner_before_retiring_old_driver(tmp_path,monkeypatch):
    import json
    import signal
    import sys
    from experiments.peg_chudoba import scheduling_lease as module
    path=tmp_path/'lease.json'
    old=dict(pid=100,start='1',command='python -m experiments.peg_chudoba.run_bounded')
    new=dict(pid=200,start='2',command='python -m experiments.peg_chudoba.scale_cpu')
    path.write_text(json.dumps(dict(owner=old,status='parked',roots=[],new_tasks=[])))
    monkeypatch.setattr(sys,'argv',['lease','handover','--state',str(path),'--previous-owner','100'])
    monkeypatch.setattr(module,'process',lambda pid:new)
    monkeypatch.setattr(module,'alive',lambda record:True)
    monkeypatch.setattr(module,'freeze',lambda record:[record])
    signals=[]
    def send(record,sig):
        assert json.loads(path.read_text())['owner']==new
        signals.append((record['pid'],sig))
    monkeypatch.setattr(module,'send',send)
    module.main()
    assert signals==[(100,signal.SIGTERM),(100,signal.SIGCONT)]
    assert json.loads(path.read_text())['handovers'][0]['previous_owner']==old


@pytest.mark.parametrize('mean,sem,status', [(1.02,.005,'equivalent'), (1.035,.015,'inconclusive'), (1.09,.005,'resolved_outside_band'), (.91,.005,'resolved_outside_band')])
def test_equivalence_distinguishes_uncertainty_from_bias(mean,sem,status):
    from experiments.peg_chudoba.validate_narrow import equivalence_assessment
    result = equivalence_assessment(mean,sem,1.,.005)
    assert result['equivalence_status'] == status
    assert result['cpu_equivalence'] == (status == 'equivalent')


def test_observed_n36_result_is_inconclusive():
    from experiments.peg_chudoba.validate_narrow import equivalence_assessment
    result = equivalence_assessment(1.3875263727834928,.015166548293648182,1.3410284021453198,.008967529051137409)
    assert result['equivalence_status'] == 'inconclusive'
    assert result['difference_interval_nm'][0] > 0
    assert result['difference_interval_nm'][1] > result['tolerance_nm']
