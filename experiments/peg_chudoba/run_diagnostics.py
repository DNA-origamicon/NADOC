"""Bounded revision: N36 timestep check and independent EOS proposal diagnostics."""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from experiments.peg_chudoba.benchmark_scheduling import DEFAULT, HERE, PYTHON, digest, lease, read, write
from experiments.peg_chudoba.serialize_existing import alive, process
from experiments.peg_chudoba.validate_narrow import (
    SPECIFICATION, continue_gpu, equivalence_assessment, gpu_assessment,
    implementation_assessment, run_batch, scalar_stats,
)
import numpy as np

REVISION = HERE/'DIAGNOSTIC_REVISION.md'


def gpu_work(out):
    refs = {r['n']: r for r in read(HERE/'campaign_comparison.json')['comparisons']
            if r['cutoff'] == 'zero_tail' and r['temperature_K'] == 294}
    report = read(out/'validation.json')
    for n in (36, 135):
        # Both short timestep cohorts precede any extension at this length.
        for round_index, duration in ((1, 20), (2, 80)):
            for dt in (1, 2):
                key = f'n{n}_dt{dt}'
                plans = [read(p) for p in (out/'production').glob(f'gpu_n{n}_dt{dt}_round*/plan.json')]
                latest = max(plans, key=lambda p:p['round']) if plans else None
                sources = ([Path(e['directory']) for e in latest['allocations']] if latest else
                           [Path(p) for p in refs[n]['directories']])
                if latest:
                    for e in latest['allocations']:
                        if digest(Path(e['source'])/'last_conf.dat') != e['source_sha256']:
                            raise RuntimeError('GPU restart source changed')
                    result = gpu_assessment(sources, refs[n])
                    report['gpu'][key] = result
                    write(out/'validation.json', report)
                    if not result['stability_pass'] or (not result['extension_recommended'] and result['equivalence_status'] == 'resolved_outside_band'):
                        raise RuntimeError(f'{key}: stability or resolved equivalence failure; diagnose before extension')
                    if result['passed'] or latest['round'] >= round_index:
                        continue
                sources = continue_gpu(out, n, dt, sources, duration, round_index, 1)
                result = gpu_assessment(sources, refs[n])
                report['gpu'][key] = result
                write(out/'validation.json', report)
                if not result['stability_pass'] or (not result['extension_recommended'] and result['equivalence_status'] == 'resolved_outside_band'):
                    raise RuntimeError(f'{key}: stability or resolved equivalence failure; diagnose before extension')
        a, b = (report['gpu'][f'n{n}_dt{dt}'] for dt in (1, 2))
        comparison = equivalence_assessment(a['rms_rg_nm'], a['conservative_sem_nm'],
                                           b['rms_rg_nm'], b['conservative_sem_nm'],
                                           tolerance=.05*refs[n]['rms_rg_nm']/b['rms_rg_nm'])
        comparison['passed'] = bool(a['passed'] and b['passed'] and comparison['cpu_equivalence'])
        report.setdefault('timestep_equivalence', {})[str(n)] = comparison
        for dt in (1, 2):
            if not report['gpu'][f'n{n}_dt{dt}']['passed']:
                report['gpu'][f'n{n}_dt{dt}']['bounded_stop'] = 'Unresolved at original allocation cap; not a pass'
        report['status'] = 'revised diagnostics; validation incomplete'
        write(out/'validation.json', report)
        if not comparison['passed']:
            return f'N{n} unresolved; larger GPU cohorts withheld'
    return 'GPU checks finished; EOS validation remains incomplete'


def eos_work(out):
    root = out/'diagnostics_revision'/ 'eos'
    entries = []
    for pressure in (1, 100, 1000):
        source_plan = read(out/'production'/f'eos_p{pressure}_round2'/'plan.json')
        for variant, vscale, pscale in (('baseline', 1, 1), ('volume_x4', 4, 1), ('pivot_x4', 1, 4)):
            for e in source_plan['allocations']:
                source = Path(e['directory'])
                prior = read(source/'run.json')
                if prior['status'] != 'completed':
                    raise RuntimeError('EOS diagnostic origin is unfinished')
                replica = prior['replica_id']
                directory = root/f'p{pressure}_{variant}'/f'r{replica}'
                command = [str(PYTHON), '-m', 'experiments.peg_chudoba.run_solution',
                           '--sampling','npt','--cutoff','zero_tail','--temperature','294',
                           '--n','135','--chains','108','--pressure-kpa',str(pressure),
                           '--initial-run',str(source),'--output',str(directory),
                           '--seed',str(700000+pressure*10+replica),'--steps','2000',
                           '--volume-delta',str(prior['volume_delta']*vscale),
                           '--pivot-prob',str(prior['pivot_prob']*pscale),
                           '--observable-records','2000','--trajectory-frames','80']
                entries.append(dict(pressure=pressure,variant=variant,replica_id=replica,
                                    source=str(source),source_sha256=digest(source/'last_conf.dat'),
                                    directory=str(directory),command=command))
    plan = dict(allocations=entries, total_sweeps=54000, concurrency=12,
                purpose='Proposal diagnostic only; no production validation or automatic promotion')
    if (root/'plan.json').exists() and read(root/'plan.json') != plan:
        raise RuntimeError('EOS diagnostic plan changed')
    write(root/'plan.json',plan)
    run_batch(out,[(e['command'],Path(e['directory'])) for e in entries],12)
    rows=[]
    for pressure in (1,100,1000):
        for variant in ('baseline','volume_x4','pivot_x4'):
            cohort=[e for e in entries if e['pressure']==pressure and e['variant']==variant]
            volumes, shapes, seconds = [], [], []
            for e in cohort:
                d=Path(e['directory']); m=read(d/'run.json')
                density=np.atleast_2d(np.loadtxt(d/'thermo.dat'))[:,1]
                volume=m['particles']/density*.8518**3
                shape=np.atleast_2d(np.loadtxt(d/'shape.dat'))[:,1]
                volumes.append(volume[len(volume)//2:]); shapes.append(shape[len(shape)//2:])
                seconds.append(m['elapsed_seconds'])
            v,s=scalar_stats(volumes),scalar_stats(shapes)
            rows.append(dict(pressure=pressure,variant=variant,volume=v,shape=s,
                             minimum_volume_ess_per_worker_hour=v['minimum_ess']/(max(seconds)/3600),
                             minimum_shape_ess_per_worker_hour=s['minimum_ess']/(max(seconds)/3600)))
    write(root/'assessment.json',dict(rows=rows,status='Exploratory efficiency estimates; confirm mixing before selecting production settings'))
    return '27 EOS diagnostic allocations completed; review ESS/hour and drift'


def main():
    out=DEFAULT
    status=out/'diagnostics_revision'/'driver.json'
    if status.exists() and alive(read(status)['owner']):
        raise RuntimeError('Diagnostic driver already alive')
    if read(out/'lease.json')['status'] != 'restored':
        raise RuntimeError('Existing lease not restored')
    if read(out/'validation.json')['specification_sha256'] != digest(SPECIFICATION):
        raise RuntimeError('Frozen validation specification changed')
    check=implementation_assessment(out)
    if not check['passed']:
        raise RuntimeError('Implementation provenance check failed')
    record=dict(owner=process(os.getpid()),status='running',started_unix=time.time(),
                revision_sha256=digest(REVISION),implementation=check)
    snapshot=out/'diagnostics_revision'/'execution_sources'/str(time.time_ns())
    snapshot.mkdir(parents=True)
    for source in (Path(__file__), HERE/'validate_narrow.py', HERE/'run_solution.py', HERE/'run_chain.py', REVISION):
        (snapshot/source.name).write_bytes(source.read_bytes())
    record['execution_sources']=str(snapshot)
    write(status,record)
    lease(out,'park',os.getpid())
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures={name:pool.submit(fn,out)
                     for name,fn in (('gpu',gpu_work),('eos',eos_work))}
            for name,future in futures.items():
                try:
                    record[name]=future.result()
                except Exception as error:
                    record[name]=dict(error=str(error))
                write(status,record)
        record.update(status='finished; review diagnostics, validation incomplete',finished_unix=time.time())
    finally:
        lease(out,'restore')
        write(status,record)


if __name__ == '__main__':
    main()
