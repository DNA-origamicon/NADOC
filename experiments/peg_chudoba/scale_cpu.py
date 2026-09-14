"""Matched 12-vs-4 CPU benchmark, then adopt bounded production if scaling passes."""
from concurrent.futures import ThreadPoolExecutor
import math
import os
from pathlib import Path
import shutil
import subprocess
import time

from experiments.peg_chudoba.benchmark_scheduling import (
    DEFAULT, HERE, ROOT, command_for, digest, launch, lease, machine_snapshot, read, write)
from experiments.peg_chudoba.serialize_existing import alive, process


def select(rows):
    ratios = []
    for pressure in (10,1000):
        for repeat in (0,1):
            pair = {r['concurrency']:r for r in rows if r['pressure']==pressure and r['repeat']==repeat}
            if set(pair) != {4,12}:
                raise ValueError('Incomplete scaling matrix')
            for index in range(12):
                if pair[4]['runs'][index]['final_sha256'] != pair[12]['runs'][index]['final_sha256']:
                    raise ValueError('Matched CPU endpoints differ')
            ratios.append(pair[4]['seconds']/pair[12]['seconds'])
    gain = math.prod(ratios)**(1/len(ratios))
    # Predeclared: >=80% of ideal 3x four-worker throughput in each matched pair.
    return dict(concurrency=12 if min(ratios)>=2.4 else 4,
                speedups_vs_four=ratios,geometric_mean_speedup=gain,
                required_speedup_each=2.4,linear_ideal=3)


def main():
    out=DEFAULT
    directory=out/'cpu12'
    directory.mkdir(exist_ok=True)
    if (directory/'plan.json').exists():
        raise RuntimeError('Scaling campaign already prepared; inspect before restarting')
    old=read(out/'lease.json')['owner']
    if not alive(old):
        raise RuntimeError('Expected bounded owner is no longer alive')
    if list((out/'production').glob('*/plan.json')):
        raise RuntimeError('Production passed reserved phase; handover requires additional recovery review')
    original=read(out/'plan.json')
    workloads=[]
    for pressure in (10,1000):
        w=next(w for w in original['workloads'] if w['name']==f'npt_p{pressure}')
        for task in w['tasks']:
            for name,expected in read(Path(task['source'])/'provenance.json')['hashes'].items():
                if digest(Path(task['source'])/name)!=expected:
                    raise RuntimeError('Frozen timing source changed')
        workloads.append(dict(w,tasks=[dict(source=w['tasks'][i%3]['source'],seed=95001+i) for i in range(12)]))
    write(directory/'plan.json',dict(workloads=workloads,rounds=2,task_count=12,
          first_concurrency=12,comparison_concurrency=4,steps=200,
          minimum_speedup_each=2.4,scope='Timing only; same 12 tasks at each concurrency',
          created_unix=time.time(),original_plan_sha256=digest(out/'plan.json')))
    code=directory/'sources';code.mkdir()
    for name in ('scale_cpu.py','validate_narrow.py','scheduling_lease.py','benchmark_scheduling.py'):
        shutil.copy2(HERE/name,code/name)
    write(code/'hashes.json',{p.name:digest(p) for p in code.glob('*.py')})
    subprocess.run(['/usr/bin/python3','-m','experiments.peg_chudoba.scheduling_lease','handover',
                    '--state',str(out/'lease.json'),'--previous-owner',str(old['pid'])],cwd=ROOT,check=True)
    state=dict(owner=process(os.getpid()),status='12-worker scaling benchmark',started_unix=time.time())
    write(out/'bounded_driver.json',state)
    rows=[]
    try:
        for repeat in range(2):
            for w in (workloads if repeat==0 else list(reversed(workloads))):
                for slots in ([12,4] if repeat==0 else [4,12]):
                    print(f"CPU benchmark P={w['pressure']} kPa, repeat={repeat+1}, workers={slots}",flush=True)
                    before=machine_snapshot();start=time.monotonic()
                    paths=[directory/f"p{w['pressure']}_r{repeat}_c{slots}_task{i}" for i in range(12)]
                    with ThreadPoolExecutor(max_workers=slots) as pool:
                        futures=[pool.submit(launch,out,command_for(w,t,d),d) for t,d in zip(w['tasks'],paths)]
                        runs=[f.result() for f in futures]
                    rows.append(dict(pressure=w['pressure'],repeat=repeat,concurrency=slots,
                                     seconds=time.monotonic()-start,runs=runs,before=before,after=machine_snapshot()))
                    write(directory/'results.json',dict(batches=rows))
        decision=select(rows)
        write(directory/'selection.json',decision)
        selected=read(out/'selection.json')['selected']
        selected['npt']=dict(selected['npt'],concurrency=decision['concurrency'],cpu12_evidence=str(directory/'selection.json'))
        write(out/'active_selection.json',dict(selected=selected,reason='User-authorized 12-worker scaling check',
                                             scope='NPT CPU concurrency only; GPU stays serial'))
        state.update(status='running bounded validation',selection=decision)
        write(out/'bounded_driver.json',state)
        print(f'Selection: {decision}',flush=True)
        from experiments.peg_chudoba.validate_narrow import complete_validation
        report=read(out/'validation.json')
        report.setdefault('scheduling_revisions',[]).append(dict(unix=time.time(),decision=decision,
            validator_sha256=digest(HERE/'validate_narrow.py'),note='Same scientific criteria and allocation caps; pressure cohorts may overlap'))
        write(out/'validation.json',report)
        complete_validation(out,selected)
        state.update(status=read(out/'validation.json')['status'],finished_unix=time.time())
    except Exception as error:
        state.update(status='stopped; validation incomplete',error=str(error),finished_unix=time.time())
        raise
    finally:
        write(out/'bounded_driver.json',state)
        lease(out,'restore')


if __name__=='__main__':
    main()
