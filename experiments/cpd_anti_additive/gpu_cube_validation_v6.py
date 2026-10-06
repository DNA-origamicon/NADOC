"""One 10 ns final-cube validation, with audited 1 ns restart boundaries."""
import argparse
import os
from pathlib import Path
import sys
import time
import traceback

REPO = Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.gpu_cube_preparation_v6 import admission, load_engine
from experiments.cpd_anti_additive.validation_gate import read, checked, source
from experiments.cpd_anti_additive.sella_pilot import save, now


def require_segment_time(deadline, estimated_seconds):
    if estimated_seconds <= 0 or deadline-time.time() < estimated_seconds*1.25+120:
        raise RuntimeError('Insufficient time for another complete segment; audit retained checkpoints before continuation')


def execute(plan, m):
    folder = m.ROOT/plan['case']/f"replica-{plan['replica']}"/'validation'
    folder.mkdir(exist_ok=False)
    cp = Path(plan['checkpoint_prefix'])
    box,row = m.box_from_xsc(Path(str(cp)+'.xsc'))
    assert row[0] == 530000
    g = m.physical(plan['case'],m.read_binary(Path(str(cp)+'.coor'),m.N),box)
    assert g['passed']
    save(folder/'initial_review.json',g)
    reports = []; started = time.monotonic()
    for segment in range(1,11):
        m.authorize()
        estimate = max([plan['reference_segment_seconds']]+[r['segment_elapsed_seconds'] for r in reports])
        require_segment_time(plan['deadline_epoch'],estimate)
        first = 530000+(segment-1)*500000
        out = folder/f'segment-{segment:02d}'
        tick = time.monotonic()
        result = m.run_stage(plan['case'],out,cp,first,500000,plan['seed']+segment*100,5000,plan['deadline_epoch'],4,True)
        result.update(segment=segment,seed=plan['seed']+segment*100,cores=4,segment_elapsed_seconds=time.monotonic()-tick)
        assert result['native_and_registered_geometry_passed']
        save(out/'assessment.json',result)
        reports.append(result)
        save(folder/'progress.json',dict(at=now(),completed_ns=segment,completed=reports,review_required_before_next_replica=True,simulation_ready=False))
        cp = out/'result.restart'
        # A material slowdown merits a model review instead of automatic continuation.
        if result['performance']['native_seconds_per_ns'] > 1.20*plan['reference_native_seconds_per_ns']:
            save(folder/'boundary_review_required.json',dict(at=now(),segment=segment,reason='Native runtime exceeds matched preparation reference by20%',checkpoint_prefix=str(cp),assessment=source(out/'assessment.json')))
            raise RuntimeError('Performance changed materially; review before another segment')
    native = sum(r['performance']['native_wall_seconds'] for r in reports)
    save(folder/'performance_report.json',dict(at=now(),case=plan['case'],replica=plan['replica'],ns=10,atoms=m.N,cores=4,native_seconds=native,native_ns_per_day=864000/native,service_elapsed_seconds=time.monotonic()-started,nontrajectory_overhead_seconds=time.monotonic()-started-native,next_run_requires_review=True,simulation_ready=False))
    save(folder/'assessment.json',dict(at=now(),case=plan['case'],replica=plan['replica'],ns=10,segments=reports,all_native_and_registered_geometry_passed=True,performance_report=source(folder/'performance_report.json'),physical_structural_and_performance_review_pending=True,simulation_ready=False,minimum_certified=False))


def run(plan_path):
    plan = admission(read(plan_path))
    assert read(checked(plan['startup_admission']))['approved_for_validation']
    assert plan['hard_seconds'] == 15*3600
    execute(plan,load_engine(plan))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--plan',type=Path,required=True)
    args = parser.parse_args()
    try:
        run(args.plan)
    except BaseException:
        args.plan.with_suffix('.failure.txt').write_text(traceback.format_exc())
        raise
