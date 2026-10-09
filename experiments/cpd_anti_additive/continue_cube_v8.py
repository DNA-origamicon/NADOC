"""Complete anti1 segments03–10 from its audited2ns full restart state."""
import argparse
import os
from pathlib import Path
import sys
import time
import traceback
REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]));sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.gpu_cube_preparation_v6 import admission,load_engine
from experiments.cpd_anti_additive.gpu_cube_validation_v6 import require_segment_time
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now


def execute(plan,m):
    folder=Path(plan['output']);folder.mkdir(exist_ok=False)
    cp=Path(plan['checkpoint_prefix']);box,row=m.box_from_xsc(Path(str(cp)+'.xsc'));assert row[0]==1530000
    g=m.physical('anti',m.read_binary(Path(str(cp)+'.coor'),m.N),box);assert g['passed'];save(folder/'initial_review.json',g)
    reports=[];started=time.monotonic()
    for segment in range(3,11):
        m.authorize()
        estimate=max([plan['reference_segment_seconds']]+[r['segment_elapsed_seconds'] for r in reports])
        require_segment_time(plan['deadline_epoch'],estimate)
        out=folder/f'segment-{segment:02d}';tick=time.monotonic();seed=plan['seed']+segment*100
        result=m.run_stage('anti',out,cp,530000+(segment-1)*500000,500000,seed,5000,plan['deadline_epoch'],4,True)
        assert result['native_and_registered_geometry_passed']
        result.update(segment=segment,seed=seed,cores=4,segment_elapsed_seconds=time.monotonic()-tick)
        save(out/'assessment.json',result);reports.append(result)
        save(folder/'progress.json',dict(at=now(),continued_ns=len(reports),validation_endpoint_ns=segment,completed=reports,simulation_ready=False))
        cp=out/'result.restart'
        if result['performance']['native_seconds_per_ns']>1.20*plan['reference_native_seconds_per_ns']:
            save(folder/'boundary_review_required.json',dict(at=now(),segment=segment,checkpoint_prefix=str(cp),reason='Native runtime exceeds reference by20%; review before further simulation'))
            raise RuntimeError('Material slowdown; audit retained endpoint')
    native=sum(r['performance']['native_wall_seconds'] for r in reports)
    save(folder/'performance_report.json',dict(at=now(),case='anti',replica=1,continued_ns=8,native_seconds=native,native_ns_per_day=8*86400/native,service_elapsed_seconds=time.monotonic()-started,simulation_ready=False))
    save(folder/'assessment.json',dict(at=now(),case='anti',replica=1,continued_ns=8,validation_endpoint_ns=10,segments=reports,prior_2ns_audit=plan['prior_audit'],performance_report=source(folder/'performance_report.json'),all_native_and_registered_geometry_passed=True,aggregate_10ns_independent_review_required=True,simulation_ready=False,minimum_certified=False))


def run(path):
    plan=admission(read(path));assert plan['hard_seconds']==43200
    assert read(checked(plan['prior_audit']))['passed']
    execute(plan,load_engine(plan))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);args=p.parse_args()
    try:run(args.plan)
    except BaseException:
        args.plan.with_suffix('.failure.txt').write_text(traceback.format_exc());raise
