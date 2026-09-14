"""Convergence-driven execution and explicit verdicts for the first 294 K claim.

Timing data never enter validation. Reuse completed independent origins and
finish live reserved EOS allocations before making a new continuation cohort.
No Hamiltonian parameters or acceptance criteria are fitted to observed errors.
"""
from concurrent.futures import ThreadPoolExecutor
import math
from pathlib import Path
import time
import threading

import numpy as np
from scipy.spatial import cKDTree

from experiments.peg_chudoba.analyze_chain import analyze as analyze_chain, correlation_time
from experiments.peg_chudoba.analyze_npt import analyze as analyze_npt
from experiments.peg_chudoba.benchmark_scheduling import HERE, ROOT, PYTHON, digest, launch, lease, read, write
from experiments.peg_chudoba.rg_statistics import summarize_rms
from experiments.peg_chudoba.sampling_diagnostics import split_rhat
from experiments.peg_chudoba.serialize_existing import alive, tree

LENGTHS = (9, 18, 27, 36, 76, 135, 275, 455, 795)
PRESSURES = (1, 10, 20, 50, 100, 200, 1000)
GPU_LENGTHS = (36, 135)
EOS_ROUNDS = 2
EOS_STEPS_PER_ROUND = 20000
GPU_DURATIONS_NS = (20, 80)
SPECIFICATION = HERE / "BOUNDED_VALIDATION.md"


def agreement(estimate, sem, target, digitization=0., tolerance=.10):
    if not all(math.isfinite(v) for v in (estimate, sem, target, digitization)) or target <= 0 or sem < 0:
        raise ValueError('Invalid uncertainty/target')
    return dict(relative_difference=estimate / target - 1,
                relative_sem=sem / estimate if estimate > 0 else None,
                engineering_agreement=abs(estimate-target) + 2*sem <= tolerance*target + digitization,
                precision_pass=estimate > 0 and sem / estimate <= .025)


def scalar_stats(traces):
    if len(traces) != 3 or any(len(x) < 36 or not np.isfinite(x).all() for x in traces):
        raise ValueError('Three finite traces of at least 36 samples required')
    means = np.array([x.mean() for x in traces])
    sems = []
    effective = []
    for x in traces:
        tau = correlation_time(x)
        effective.append(len(x)/tau if np.var(x) > 0 else 0.)
        auto = x.std(ddof=1)*np.sqrt(tau/len(x))
        block = np.array([a.mean() for a in np.array_split(x,18)]).std(ddof=1)/np.sqrt(18)
        sems.append(max(auto, block))
    sem = max(np.linalg.norm(sems)/3, means.std(ddof=1)/np.sqrt(3))
    # Explicitly align full retained windows for R-hat when output cadences
    # differ. Full-resolution traces still determine moments and ESS.
    length = min(map(len, traces))
    rhat = split_rhat([x[np.linspace(0,len(x)-1,length,dtype=int)] for x in traces])['maximum']
    return dict(mean=float(means.mean()), sem=float(sem), minimum_ess=float(min(effective)),
                rhat=float(rhat) if np.isfinite(rhat) else None,
                retained_counts=list(map(len,traces)),rhat_aligned_draws=length,
                rhat_alignment='Evenly spaced indices over each full retained window; moments/ESS use unthinned data',
                sampling_pass=bool(rhat < 1.01 and min(effective) >= 100),
                maximum_relative_half_drift=float(max(abs(x[:len(x)//2].mean()-x[len(x)//2:].mean())
                    for x in traces)/abs(means.mean())) if means.mean() else None)


def contacts(directory):
    """Periodic intermolecular contacts below 0.6 nm per bead; no native changes."""
    path = directory/'contacts_validation.json'
    trajectory = directory/'trajectory.dat'
    fingerprint = dict(size=trajectory.stat().st_size, mtime_ns=trajectory.stat().st_mtime_ns,
                       cutoff_nm=.6, definition='Number of intermolecular bead pairs within 0.6 nm / total beads')
    if path.exists() and read(path)['fingerprint'] == fingerprint:
        return np.asarray(read(path)['trace'])
    meta = read(directory/'run.json')
    count = meta['particles']
    values = []
    with trajectory.open() as stream:
        while stream.readline():
            box = np.array([float(v) for v in stream.readline().split('=')[1].split()]) * .8518
            stream.readline()
            xyz = np.array([[float(v) for v in stream.readline().split()[:3]] for _ in range(count)]) * .8518
            if xyz.shape != (count, 3) or not np.isfinite(xyz).all():
                raise ValueError('Invalid trajectory')
            pairs = cKDTree(np.mod(xyz, box), boxsize=box).query_pairs(.6, output_type='ndarray')
            values.append(float(np.count_nonzero(pairs[:,0]//meta['n'] != pairs[:,1]//meta['n'])/count))
    write(path, dict(fingerprint=fingerprint, trace=values))
    return np.asarray(values)


def eos_assessment(directories, target):
    volume, shape, contact = [], [], []
    ids = []
    mass_factor = None
    for d in directories:
        meta = read(d/'run.json')
        if any(meta.get(k) != v for k,v in dict(n=135, chains=108, temperature=294,
                 cutoff='zero_tail', sampling='npt', status='completed').items()):
            raise ValueError(f'Wrong EOS state: {d}')
        ids.append(meta.get('replica_id', meta['seed']))
        analysis = analyze_npt(d)
        density = np.atleast_2d(np.loadtxt(d/'thermo.dat'))[:,1]
        v = meta['particles']/density*.8518**3
        volume.append(v[len(v)//2:])
        s = np.asarray(analysis['saved_rg_trace_nm'])
        shape.append(s[len(s)//2:])
        c = contacts(d)
        contact.append(c[len(c)//2:])
        mass_factor = meta['particles']*44.05/.602214076
    if len(set(ids)) != 3:
        raise ValueError('EOS origins are not independent')
    vs = scalar_stats(volume)
    ss = scalar_stats(shape) if min(map(len,shape)) >= 36 else dict(sampling_pass=False)
    cs = scalar_stats(contact) if min(map(len,contact)) >= 36 else dict(sampling_pass=False)
    # Sparse saved coordinates support a weaker ancillary contact diagnostic;
    # volume and shape retain ESS >=100. No missing contact data clears a pass.
    contact_pass = cs.get('rhat') is not None and cs['rhat'] < 1.01 and cs['minimum_ess'] >= 20
    concentration = mass_factor/vs['mean']
    sem = concentration*vs['sem']/vs['mean']
    comparison = agreement(concentration, sem, target['concentration_g_per_l'],
                           target['concentration_g_per_l']*target['digitization_relative_bound'])
    mixing = bool(vs['sampling_pass'] and ss['sampling_pass'] and contact_pass
                  and vs['maximum_relative_half_drift'] < .05
                  and ss.get('maximum_relative_half_drift', 1) < .05)
    passed = bool(mixing and comparison['precision_pass'] and comparison['engineering_agreement'])
    return dict(directories=list(map(str,directories)), replica_ids=ids, concentration_g_per_l=concentration,
                conservative_sem_g_per_l=sem, volume=vs, shape=ss, contacts=cs,
                sampling_pass=mixing, passed=passed, **comparison)


def finish_reserved(out, concurrency, *, plan_only=False):
    state = read(out/'lease.json')
    selected, jobs, entries = [], [], []
    live = {}
    for root in state['roots'] + state.get('new_tasks',[]):
        members = tree(root) if alive(root) else []
        for member in members:
            if member['name'] != 'oxDNA':
                continue
            directory = Path(member['cwd'])
            meta = read(directory/'run.json')
            if any(meta.get(k) != v for k,v in dict(n=135,temperature=294,sampling='npt',cutoff='zero_tail').items()):
                continue
            wrapper = next(p for p in members if p['pid'] == member['parent'])
            if 'experiments.peg_chudoba.run_solution' not in wrapper['command']:
                raise RuntimeError('Unrecognized native parent during adoption')
            live[directory.resolve()] = wrapper
            if root in state['roots'] and root not in selected:
                selected.append(root)
    used = set()
    for planfile in (HERE/'runs').glob('eos_zero_tail_extensions_n135_t294*/plan.json'):
        plan = read(planfile)
        settings = plan['settings']
        if any(settings.get(k) != v for k,v in dict(n=135,temperature=294,cutoff='zero_tail').items()):
            raise RuntimeError('Reserved EOS plan has a different convention')
        for entry in plan['allocations']:
            destination = planfile.parent/entry['name']
            resolved = destination.resolve()
            if resolved in used:
                raise RuntimeError('Duplicate reserved destination')
            used.add(resolved)
            if resolved in live:
                jobs.append(('live',live[resolved],destination))
                continue
            if (destination/'run.json').exists():
                if read(destination/'run.json')['status'] != 'completed':
                    raise RuntimeError(f'Unowned incomplete reserved allocation: {destination}')
                continue
            source = Path(entry['source'])
            if digest(source/'last_conf.dat') != entry['source_sha256']:
                raise RuntimeError('Reserved source endpoint changed')
            command = [str(PYTHON),'-m','experiments.peg_chudoba.run_solution','--sampling','npt',
                '--initial-run',str(source),'--output',str(destination),
                '--observable-records','10000','--trajectory-frames','200']
            for key,value in dict(settings,seed=entry['seed'],volume_delta=entry['volume_delta'],
                                  pivot_prob=entry['pivot_prob']).items():
                command += ['--'+key.replace('_','-'),str(value)]
            jobs.append(('pending',command,destination))
            entries.append(dict(directory=str(destination),source=str(source),source_sha256=entry['source_sha256'],
                                command=command,replica_id=entry['replica_id']))
    if set(live)-used:
        raise RuntimeError('Live EOS allocation outside reserved plans; inspect before adoption')
    write(out/'adoption.json',dict(roots=selected,pending=entries,
          live=[dict(wrapper=job[1],directory=str(job[2])) for job in jobs if job[0]=='live'],
          note='Existing frozen allocations only; added output records do not change the sampler or Hamiltonian'))
    if plan_only:
        return dict(live=sum(j[0]=='live' for j in jobs),pending=sum(j[0]=='pending' for j in jobs),roots=len(selected))
    def finish(root,action):
        known = {(p['pid'],p['start']): p for p in tree(root)}
        lease(out, action, root['pid'])
        while any(alive(p) for p in known.values()):
            known.update({(p['pid'],p['start']): p for p in tree(root)})
            time.sleep(5)
        return root['pid']
    def execute(job):
        kind,payload,directory = job
        if kind == 'live':
            finish(payload,'resume-task')
            if read(directory/'run.json')['status'] != 'completed':
                raise RuntimeError(f'Adopted engine did not complete: {directory}')
        else:
            launch(out,payload,directory)
    print(f'Finish {len(jobs)} reserved N135/294 K EOS replicas at concurrency {concurrency}', flush=True)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(execute,jobs))
    # The original drivers now find completed entries, produce their summaries,
    # and exit. No second allocation is created by resuming them.
    for root in selected:
        finish(root,'resume')


def latest_eos(out, pressure):
    candidates = {}
    paths = list((HERE/'runs').glob('*/*/run.json')) + list((out/'production').glob('*/*/run.json'))
    for path in paths:
        m = read(path)
        if any(m.get(k) != v for k,v in dict(n=135,chains=108,temperature=294,pressure_kpa=pressure,
                 sampling='npt',cutoff='zero_tail',status='completed').items()):
            continue
        replica = m.get('replica_id',m['seed'])
        if replica not in (401,402,403):
            continue
        score = (m.get('sampling_generation',0),m['steps'])
        if replica not in candidates or score > candidates[replica][0]:
            candidates[replica] = (score,path.parent)
    if set(candidates) != {401,402,403}:
        raise ValueError(f'Incomplete existing EOS cohort at {pressure} kPa')
    return [candidates[r][1] for r in (401,402,403)]


def run_batch(out, jobs, concurrency):
    # A frozen plan prevents accidentally changing/reusing an unfinished cohort.
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = []
        for command,directory in jobs:
            if (directory/'run.json').exists():
                m = read(directory/'run.json')
                if m['status'] != 'completed':
                    raise RuntimeError(f'Inspect unfinished allocation before recovery: {directory}')
                for option,key in (('--steps','steps'),('--seed','seed'),('--n','n'),('--dt-fs','dt_fs')):
                    if option in command and float(command[command.index(option)+1]) != m[key]:
                        raise RuntimeError(f'Existing allocation settings mismatch: {directory}')
                continue
            futures.append(pool.submit(launch,out,command,directory))
        for future in futures:
            future.result()


def continue_eos(out, pressure, sources, steps, round_index, concurrency):
    cohort = out/'production'/f'eos_p{pressure}_round{round_index}'
    jobs, entries = [], []
    for source in sources:
        prior = read(source/'run.json')
        replica = prior.get('replica_id',prior['seed'])
        directory = cohort/f'r{replica}'
        seed = 100000 + round_index*1000 + replica
        command = [str(PYTHON),'-m','experiments.peg_chudoba.run_solution','--sampling','npt',
            '--cutoff','zero_tail','--temperature','294','--n','135','--pressure-kpa',str(pressure),
            '--initial-run',str(source),'--output',str(directory),'--seed',str(seed),'--steps',str(steps),
            '--volume-delta',str(prior['volume_delta']),'--pivot-prob',str(prior['pivot_prob']),
            '--observable-records','10000','--trajectory-frames','200']
        entries.append(dict(source=str(source),source_sha256=digest(source/'last_conf.dat'),
                            replica_id=replica,steps=steps,directory=str(directory),command=command))
        jobs.append((command,directory))
    plan = dict(pressure_kpa=pressure,round=round_index,allocations=entries)
    if (cohort/'plan.json').exists() and read(cohort/'plan.json') != plan:
        raise RuntimeError('EOS continuation plan changed')
    write(cohort/'plan.json',plan)
    run_batch(out,jobs,concurrency)
    return [d for _,d in jobs]


def equivalence_assessment(estimate, sem, reference, reference_sem, tolerance=.05):
    """Classify a two-SEM difference interval against the frozen equivalence band."""
    if not all(math.isfinite(x) for x in (estimate, sem, reference, reference_sem, tolerance)) or min(sem, reference_sem) < 0 or reference <= 0 or tolerance <= 0:
        raise ValueError('Invalid equivalence inputs')
    difference = estimate-reference
    uncertainty = 2*math.hypot(sem, reference_sem)
    limit = tolerance*reference
    lower, upper = difference-uncertainty, difference+uncertainty
    status = ('equivalent' if lower >= -limit and upper <= limit else
              'resolved_outside_band' if lower > limit or upper < -limit else 'inconclusive')
    return dict(equivalence_status=status, difference_nm=difference,
                difference_interval_nm=[lower, upper], tolerance_nm=limit,
                cpu_equivalence=status == 'equivalent')


def gpu_assessment(directories, reference):
    traces = []
    ids = []
    maximum_bond = 0.
    for d in directories:
        analysis = analyze_chain(d)
        maximum_bond = max(maximum_bond,analysis['maximum_bond_nm'])
        m = read(d/'run.json')
        ids.append(m['replica_id'])
        x = np.loadtxt(d/'rg.csv',delimiter=',',skiprows=1,usecols=1)
        traces.append(x[len(x)//10:])
    if len(set(ids)) != 3:
        raise ValueError('GPU origins are not independent')
    stats = summarize_rms(traces)
    comparison = equivalence_assessment(stats['rms_rg_nm'], stats['conservative_sem_nm'],
                                        reference['rms_rg_nm'], reference['conservative_sem_nm'])
    return dict(**stats, **comparison, replica_ids=ids,directories=list(map(str,directories)),
                maximum_bond_nm=maximum_bond,stability_pass=maximum_bond < .6,
                passed=bool(comparison['cpu_equivalence'] and maximum_bond < .6 and not stats['extension_recommended']
                  and stats['conservative_sem_nm']/stats['rms_rg_nm'] <= .025))


def continue_gpu(out,n,dt,sources,duration_ns,round_index,concurrency):
    cohort = out/'production'/f'gpu_n{n}_dt{dt}_round{round_index}'
    jobs,entries = [],[]
    for index,source in enumerate(sources):
        prior = read(source/'run.json')
        replica = prior.get('replica_id',prior['seed'])
        directory = cohort/f'r{replica}'
        command = [str(PYTHON),'-m','experiments.peg_chudoba.run_chain','--sampling','md',
            '--cutoff','zero_tail','--temperature','294','--n',str(n),'--dt-fs',str(dt),
            '--initial-run',str(source),'--output',str(directory),'--seed',str(300000+10000*round_index+100*dt+index),
            '--steps',str(round(duration_ns*1e6/dt)),'--trajectory-frames','10000']
        entries.append(dict(source=str(source),source_sha256=digest(source/'last_conf.dat'),
                            replica_id=replica,directory=str(directory),command=command))
        jobs.append((command,directory))
    plan = dict(n=n,dt_fs=dt,duration_ns=duration_ns,round=round_index,allocations=entries)
    if (cohort/'plan.json').exists() and read(cohort/'plan.json') != plan:
        raise RuntimeError('GPU continuation plan changed')
    write(cohort/'plan.json',plan)
    run_batch(out,jobs,concurrency)
    return [d for _,d in jobs]


def implementation_assessment(out):
    from tools.oxdna_peg.chudoba_reference import chain_energy
    manifest = read(HERE/'verification_zero_tail_manifest.json')
    hashes = {name:digest(Path(name)) == expected for name,expected in manifest['hashes'].items()}
    endpoints = []
    for batch in read(out/'benchmarks.json')['batches']:
        if batch['workload'] != 'gpu_n795' or batch['concurrency'] != 1:
            continue
        for run in batch['runs']:
            path = Path(run['directory'])/'last_conf.dat'
            lines = path.read_text().splitlines()
            box = np.array([float(v) for v in lines[1].split('=')[1].split()])*.8518
            xyz = np.loadtxt(path,skiprows=3,usecols=(0,1,2))*.8518
            bonds = np.diff(xyz,axis=0)
            bonds -= box*np.rint(bonds/box)
            xyz = np.vstack([xyz[0],xyz[0]+np.cumsum(bonds,axis=0)])
            if np.any(np.ptp(xyz,axis=0) >= box/2):
                raise RuntimeError('Reference endpoint needs explicit nonbonded periodic treatment')
            reference = chain_energy(xyz,294,zero_tail=True)/24.943387854/len(xyz)
            observed = float(lines[2].split('=')[1].split()[1])
            error = abs(reference-observed)
            endpoints.append(dict(directory=run['directory'],sha256=digest(path),
                reference_internal_per_bead=reference,observed_internal_per_bead=observed,
                absolute_error=error,passed=error <= 2e-5))
    return dict(verified_manifest_hashes=hashes,n795_gpu_energy=endpoints,
        passed=bool(all(hashes.values()) and len(endpoints)==8 and all(r['passed'] for r in endpoints)),
        scope='Numerical implementation check only; benchmark endpoints are not equilibrium samples')


def complete_validation(out,selected):
    from experiments.peg_chudoba.report_scheduling import render
    reportfile = out/'validation.json'
    report = read(reportfile) if reportfile.exists() else dict(status='incomplete',chains=[],eos={},gpu={},
        claim='294 K bulk PEG, zero-tail reconstruction; literature benchmark validation only',
        specification_sha256=digest(SPECIFICATION),validator_sha256=digest(Path(__file__)),
        exclusions=['physical kinetics','PEG-DNA','surfaces','electric fields','electrolyte dependence'],
        final_journal_main_text_verified=False)
    if report['specification_sha256'] != digest(SPECIFICATION):
        raise RuntimeError('Validation criteria changed; review before resuming')
    report['implementation'] = implementation_assessment(out)
    write(reportfile,report)
    if not report['implementation']['passed']:
        raise RuntimeError('Implementation provenance/endpoint energy check failed; diagnose before production')
    # Resume only frozen allocations; never reinterpret completed children as
    # extra replicas or build a new plan from a partially completed generation.
    for planfile in sorted((out/'production').glob('*/plan.json')):
        frozen = read(planfile)
        jobs = []
        for entry in frozen['allocations']:
            if digest(Path(entry['source'])/'last_conf.dat') != entry['source_sha256']:
                raise RuntimeError('Continuation source changed')
            jobs.append((entry['command'],Path(entry['directory'])))
        run_batch(out,jobs,selected['npt' if 'pressure_kpa' in frozen else 'md']['concurrency'])
    # Existing 294 K pivot cohorts already have independent origins; do not rerun passes.
    rows = read(HERE/'campaign_comparison.json')['comparisons']
    references = {r['n']:r for r in rows if r['cutoff']=='zero_tail' and r['temperature_K']==294}
    report['chains'] = []
    for n in LENGTHS:
        r = references[n]
        verdict = agreement(r['rms_rg_nm'],r['conservative_sem_nm'],r['published_rg_nm'],r['digitization_bound_nm'])
        report['chains'].append(dict(n=n,**verdict,rms_rg_nm=r['rms_rg_nm'],sem_nm=r['conservative_sem_nm'],
            sampling_pass=not r['extension_recommended'],passed=bool(not r['extension_recommended'] and
                verdict['engineering_agreement'] and verdict['precision_pass']),directories=r['directories']))
    write(reportfile,report)
    render(out)
    if not all(r['passed'] for r in report['chains']):
        raise RuntimeError('Existing 294 K chain claim fails frozen criteria; diagnose before broad production')
    finish_reserved(out,selected['npt']['concurrency'])
    targets = read(HERE/'reference/published_targets.json')['osmotic_pressure']
    initial_eos = {pressure:latest_eos(out,pressure) for pressure in PRESSURES}
    report_lock = threading.Lock()
    def process_pressure(pressure):
        target = next(r for r in targets if r['n']==135 and r['temperature_K']==294 and abs(r['pressure_kpa']/pressure-1)<.02)
        sources = initial_eos[pressure]
        previous_round = max([0]+[read(p)['round'] for p in (out/'production').glob(f'eos_p{pressure}_round*/plan.json')])
        for round_index in range(previous_round,EOS_ROUNDS+1):
            result = eos_assessment(sources,target)
            with report_lock:
                report['eos'][str(pressure)] = result
                write(reportfile,report)
                render(out)
            print(f'EOS {pressure} kPa: pass={result["passed"]}; volume ESS={result["volume"]["minimum_ess"]:.1f}',flush=True)
            if result['passed']:
                break
            if result['sampling_pass'] and result['precision_pass'] and not result['engineering_agreement']:
                raise RuntimeError(f'Converged EOS disagreement at {pressure} kPa; diagnosis required, no automatic refitting')
            if round_index == EOS_ROUNDS:
                with report_lock:
                    result['bounded_stop'] = 'Sampling/precision unresolved at the allocation cap; not a pass'
                    write(reportfile,report)
                break
            steps = EOS_STEPS_PER_ROUND
            sources = continue_eos(out,pressure,sources,steps,round_index+1,selected['npt']['concurrency'])
    with ThreadPoolExecutor(max_workers=max(1,selected['npt']['concurrency']//3)) as pool:
        list(pool.map(process_pressure,PRESSURES))
    for n in GPU_LENGTHS:
        for dt in (2,1):
            sources = [Path(p) for p in references[n]['directories']]
            duration = 20
            old_plans = [read(p) for p in (out/'production').glob(f'gpu_n{n}_dt{dt}_round*/plan.json')]
            previous_round = 0
            if old_plans:
                latest = max(old_plans,key=lambda p:p['round'])
                previous_round = latest['round']
                sources = [Path(e['directory']) for e in latest['allocations']]
                result = gpu_assessment(sources,references[n])
                report['gpu'][f'n{n}_dt{dt}'] = result
                write(reportfile,report)
                render(out)
                if not result['stability_pass']:
                    raise RuntimeError(f'GPU bond instability N{n}, dt={dt}; diagnose before continuing')
                if result['passed']:
                    continue
                if previous_round >= len(GPU_DURATIONS_NS):
                    result['bounded_stop'] = 'Sampling/precision unresolved at the allocation cap; not a pass'
                    write(reportfile,report)
                    continue
            for round_index in range(previous_round+1,len(GPU_DURATIONS_NS)+1):
                duration = GPU_DURATIONS_NS[round_index-1]
                sources = continue_gpu(out,n,dt,sources,duration,round_index,selected['md']['concurrency'])
                result = gpu_assessment(sources,references[n])
                report['gpu'][f'n{n}_dt{dt}'] = result
                write(reportfile,report)
                render(out)
                if not result['stability_pass']:
                    raise RuntimeError(f'GPU bond instability N{n}, dt={dt}; diagnose before continuing')
                if result['passed']:
                    break
                if not result['extension_recommended'] and result['conservative_sem_nm']/result['rms_rg_nm'] <= .025 and result['equivalence_status'] == 'resolved_outside_band':
                    raise RuntimeError(f'GPU/CPU disagreement N{n}, dt={dt}; investigate integration before more sampling')
                if round_index == len(GPU_DURATIONS_NS):
                    result['bounded_stop'] = 'Sampling/precision unresolved at the allocation cap; not a pass'
                    write(reportfile,report)
        a,b = report['gpu'][f'n{n}_dt2'],report['gpu'][f'n{n}_dt1']
        difference_bound = abs(a['rms_rg_nm']-b['rms_rg_nm'])+2*math.hypot(a['conservative_sem_nm'],b['conservative_sem_nm'])
        report.setdefault('timestep_equivalence',{})[str(n)] = dict(
            difference_bound_nm=difference_bound, tolerance_nm=.05*references[n]['rms_rg_nm'],
            passed=bool(a['passed'] and b['passed'] and difference_bound <= .05*references[n]['rms_rg_nm']))
        write(reportfile,report)
    if len(report['eos']) != len(PRESSURES) or len(report['gpu']) != 2*len(GPU_LENGTHS) or not all(
        r['passed'] for r in report.get('timestep_equivalence',{}).values()) or not all(
        r['passed'] for r in list(report['eos'].values())+list(report['gpu'].values())):
        report.update(status='bounded campaign finished; validation incomplete',completed_unix=time.time())
        write(reportfile,report)
        render(out)
        print(report['status'],flush=True)
        return
    report.update(status='passed within the stated engineering scope',completed_unix=time.time())
    write(reportfile,report)
    render(out)
    print(report['status'],flush=True)
