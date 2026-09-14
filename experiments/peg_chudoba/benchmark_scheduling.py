"""Matched serial/parallel timing, followed by the frozen 294 K validation.

Prepare without simulations:
  python -m experiments.peg_chudoba.benchmark_scheduling --prepare
Execute the directly user-authorized experiment (not a regression suite):
  .venv/bin/python -u -m experiments.peg_chudoba.benchmark_scheduling --execute
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

from experiments.peg_chudoba.serialize_existing import alive, process, tree

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DEFAULT = ROOT / 'workspace/peg_chudoba/scheduling_294_20260910'
PYTHON = ROOT / '.venv/bin/python'
BINARY = Path.home() / '.local/share/nadoc/engines/oxdna-chudoba/build/bin/oxDNA'
LIBRARY = BINARY.parent.parent / 'src/liboxdna_common.so'


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(source, destination):
    source = Path(source).resolve()
    meta = read(source / 'run.json')
    if meta.get('status') != 'completed' or meta.get('cutoff') != 'zero_tail' or meta['temperature'] != 294:
        raise ValueError(f'Invalid source {source}')
    destination.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for filename in ('run.json', 'input', 'last_conf.dat', 'topology.top'):
        shutil.copy2(source / filename, destination / filename)
        hashes[filename] = digest(destination / filename)
    write(destination / 'provenance.json', dict(original=str(source), hashes=hashes))
    return str(destination.resolve())


def prepare(out):
    planfile = out / 'plan.json'
    if planfile.exists():
        return read(planfile)
    chain = read(HERE / 'campaign_comparison.json')['comparisons']
    specifications = [
        ('pivot_n795', 'pivot', 795, None, 5000, [1, 2, 4]),
        ('npt_p10', 'npt', 135, 10, 200, [1, 2, 4]),
        ('npt_p1000', 'npt', 135, 1000, 200, [1, 2, 4]),
        ('gpu_n36', 'md', 36, None, 500000, [1, 2]),
        ('gpu_n795', 'md', 795, None, 500000, [1, 2]),
    ]
    workloads = []
    for name, sampling, n, pressure, steps, slots in specifications:
        if sampling == 'npt':
            sources = [HERE / f'runs/eos_zero_tail_n135_t294/n135_t294_p{pressure}_s{s}' for s in (401, 402, 403)]
        else:
            row = next(r for r in chain if r['cutoff'] == 'zero_tail' and r['temperature_K'] == 294 and r['n'] == n)
            sources = [Path(p) for p in row['directories']]
        frozen = [snapshot(p, out / 'sources' / name / f'origin{i}') for i, p in enumerate(sources)]
        tasks = [dict(source=frozen[i % 3], seed=94001 + i) for i in range(4)]
        workloads.append(dict(name=name, sampling=sampling, n=n, pressure=pressure,
                              steps=steps, concurrency=slots, tasks=tasks))
    plan = dict(created_unix=time.time(), scope_document=str(HERE / 'NARROW_VALIDATION.md'),
                scope_sha256=digest(HERE / 'NARROW_VALIDATION.md'),
                binary_sha256=digest(BINARY), library_sha256=digest(LIBRARY),
                workloads=workloads, rounds=2,
                note='Timing only; four matched tasks per batch, counterbalanced order; never pool with validation')
    write(planfile, plan)
    return plan


def lease(out, action, pid=None):
    cmd = ['/usr/bin/python3', '-m', 'experiments.peg_chudoba.scheduling_lease', action,
           '--state', str(out / 'lease.json')]
    if pid is not None:
        cmd += ['--pid', str(pid)]
    subprocess.run(cmd, cwd=ROOT, check=True)


def launch(out, command, directory):
    """Run one allocation, retain logs, and require a genuinely finished engine."""
    directory = Path(directory)
    plan = read(out/'plan.json')
    if digest(BINARY) != plan['binary_sha256'] or digest(LIBRARY) != plan['library_sha256']:
        raise RuntimeError('Engine changed during the campaign; refusing a mixed-build allocation')
    if (directory / 'run.json').exists():
        raise RuntimeError(f'Allocation already exists; inspect before retry: {directory}')
    suffix = hashlib.sha256(str(directory).encode()).hexdigest()[:12]
    logpath = out / 'launcher_logs' / (directory.name + '-' + suffix + '.log')
    logpath.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    started = time.monotonic()
    with logpath.open('w') as log:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        lease(out, 'register', child.pid)
        try:
            code = child.wait()
        except BaseException:
            # Stop the process group before the lease restores older campaigns.
            import signal
            os.killpg(child.pid, signal.SIGSTOP)
            raise
    elapsed = time.monotonic() - started
    meta = read(directory / 'run.json')
    if code or meta['status'] != 'completed' or meta['completed_steps'] < meta['steps']:
        raise RuntimeError(f'Failed/incomplete allocation {directory}; see {logpath}')
    return dict(directory=str(directory), wall_seconds=elapsed, engine_seconds=meta['elapsed_seconds'],
                steps=meta['completed_steps'], final_sha256=digest(directory / 'last_conf.dat'),
                input_sha256=digest(directory / 'input'), seed=meta['seed'])


def command_for(workload, task, directory):
    sampling = workload['sampling']
    module = 'run_solution' if sampling == 'npt' else 'run_chain'
    cmd = [str(PYTHON), '-m', f'experiments.peg_chudoba.{module}', '--sampling', sampling,
           '--cutoff', 'zero_tail', '--n', str(workload['n']), '--temperature', '294',
           '--steps', str(workload['steps']), '--seed', str(task['seed']),
           '--initial-run', task['source'], '--output', str(directory), '--trajectory-frames',
           '8' if sampling == 'npt' else '200']
    if sampling == 'npt':
        prior = read(Path(task['source']) / 'run.json')
        cmd += ['--pressure-kpa', str(workload['pressure']), '--observable-records', '200',
                '--volume-delta', str(prior['volume_delta']), '--pivot-prob', str(prior['pivot_prob'])]
    else:
        cmd += ['--dt-fs', '2']
    return cmd


def machine_snapshot():
    gpu = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,temperature.gpu,power.draw',
                          '--format=csv,noheader'], capture_output=True, text=True, check=False)
    cpu = subprocess.run(['ps', '-eo', 'pid,comm,pcpu,ni', '--sort=-pcpu'],
                         capture_output=True, text=True, check=False)
    return dict(unix=time.time(), load_average=os.getloadavg(), gpu=gpu.stdout.strip(),
                cpu_processes=cpu.stdout.splitlines()[:12],
                caveat='ps CPU percentages are lifetime averages; external workloads are not modified')


def select_strategies(batches):
    """Choose stable aggregate throughput, preferring less concurrency within 5%."""
    families = {'pivot': ['pivot_n795'], 'npt': ['npt_p10', 'npt_p1000'], 'md': ['gpu_n36', 'gpu_n795']}
    answer = {}
    for family, names in families.items():
        subset = [b for b in batches if b['workload'] in names]
        if len(subset) != len(names) * 2 * (2 if family == 'md' else 3):
            raise ValueError(f'Incomplete matched timing matrix for {family}')
        base = {(b['workload'], b['round']): b['makespan_seconds'] for b in subset if b['concurrency'] == 1}
        scores = {}
        for slots in sorted({b['concurrency'] for b in subset}):
            speedups = [base[b['workload'], b['round']] / b['makespan_seconds']
                        for b in subset if b['concurrency'] == slots]
            per_round = [math.exp(sum(math.log(base[b['workload'], r] / b['makespan_seconds'])
                         for b in subset if b['concurrency'] == slots and b['round'] == r) / len(names))
                         for r in range(2)]
            scores[slots] = dict(geometric_mean_speedup=math.exp(sum(map(math.log, speedups)) / len(speedups)),
                                 round_speedups=per_round)
        eligible = {s: v for s, v in scores.items() if s == 1 or min(v['round_speedups']) > 1}
        best = max(v['geometric_mean_speedup'] for v in eligible.values())
        chosen = min(s for s, v in eligible.items() if v['geometric_mean_speedup'] >= .95 * best)
        answer[family] = dict(concurrency=chosen, scores=scores)
    return answer


def benchmark(out, plan):
    saved = out / 'benchmarks.json'
    batches = read(saved)['batches'] if saved.exists() else []
    for round_index in range(plan['rounds']):
        workloads = plan['workloads'] if round_index == 0 else list(reversed(plan['workloads']))
        for w in workloads:
            slots_order = w['concurrency'] if round_index == 0 else list(reversed(w['concurrency']))
            for slots in slots_order:
                if any(b['workload'] == w['name'] and b['round'] == round_index and b['concurrency'] == slots for b in batches):
                    continue
                paths = [out / 'timing_runs' / f'{w["name"]}_r{round_index}_c{slots}_task{i}' for i in range(4)]
                before = machine_snapshot()
                started = time.monotonic()
                print(f'Benchmark {w["name"]}, round {round_index+1}, concurrency {slots}', flush=True)
                with ThreadPoolExecutor(max_workers=slots) as pool:
                    futures = [pool.submit(launch, out, command_for(w, task, d), d) for task, d in zip(w['tasks'], paths)]
                    runs = [f.result() for f in futures]
                elapsed = time.monotonic() - started
                after = machine_snapshot()
                # Exclude postprocessing from scheduling makespan.
                for run in runs:
                    d = Path(run['directory'])
                    if w['sampling'] == 'npt':
                        from experiments.peg_chudoba.analyze_npt import analyze
                        result = analyze(d)
                        run['provisional_effective_samples'] = result['effective_volume_samples']
                    else:
                        from experiments.peg_chudoba.analyze_chain import analyze, correlation_time
                        import numpy as np
                        analyze(d)
                        x = np.loadtxt(d / 'rg.csv', delimiter=',', skiprows=1, usecols=1)
                        x = x[len(x)//10:] ** 2
                        run['provisional_effective_samples'] = len(x) / correlation_time(x) if np.var(x) else 0.
                    run['provisional_ess_per_second'] = run['provisional_effective_samples'] / run['wall_seconds']
                row = dict(workload=w['name'], round=round_index, concurrency=slots, makespan_seconds=elapsed,
                           aggregate_steps_per_second=sum(r['steps'] for r in runs) / elapsed,
                           provisional_aggregate_ess_per_second=sum(r['provisional_effective_samples'] for r in runs) / elapsed,
                           runs=runs, before=before, after=after)
                batches.append(row)
                write(saved, dict(status='Timing only; no convergence claim', batches=batches))
    # CPU trajectories should be invariant under scheduling for matched seeds.
    for w in plan['workloads']:
        if w['sampling'] == 'md':
            continue  # CUDA accumulation order need not be bitwise deterministic.
        for task in w['tasks']:
            hashes = {r['final_sha256'] for b in batches if b['workload'] == w['name']
                      for r in b['runs'] if r['seed'] == task['seed']}
            if len(hashes) != 1:
                raise RuntimeError(f'Matched CPU endpoints differ for {w["name"]}; diagnose before selecting a strategy')
    selected = select_strategies(batches)
    write(out / 'selection.json', dict(selected=selected, benchmark_sha256=digest(saved)))
    return selected


def execute(out, plan, benchmark_only=False):
    if digest(BINARY) != plan['binary_sha256'] or digest(LIBRARY) != plan['library_sha256']:
        raise RuntimeError('Engine changed since the frozen plan')
    if digest(HERE / 'NARROW_VALIDATION.md') != plan['scope_sha256']:
        raise RuntimeError('Validation specification changed since plan preparation')
    for w in plan['workloads']:
        for task in w['tasks']:
            source = Path(task['source'])
            for name, expected in read(source / 'provenance.json')['hashes'].items():
                if digest(source / name) != expected:
                    raise RuntimeError(f'Frozen source changed: {source / name}')
    code = out/'execution_sources'/str(time.time_ns())
    code.mkdir(parents=True)
    for name in ('benchmark_scheduling.py','scheduling_lease.py','validate_narrow.py',
                 'report_scheduling.py','run_chain.py','run_solution.py','analyze_chain.py',
                 'analyze_npt.py','sampling_diagnostics.py','rg_statistics.py','run_bounded.py'):
        shutil.copy2(HERE/name,code/name)
    for name in ('NARROW_VALIDATION.md','BOUNDED_VALIDATION.md'):
        shutil.copy2(HERE/name,code/name)
    write(code/'hashes.json',{p.name:digest(p) for p in code.glob('*.py')})
    try:
        lease(out, 'park', os.getpid())
        selected = benchmark(out, plan)
        if (out/'active_selection.json').exists():
            active = read(out/'active_selection.json')['selected']
            evidence = read(Path(active['npt']['cpu12_evidence']))
            if evidence['concurrency'] != active['npt']['concurrency']:
                raise RuntimeError('CPU standard differs from measured decision')
            selected['npt'] = active['npt']
        from experiments.peg_chudoba.report_scheduling import render
        render(out)
        if not benchmark_only:
            from experiments.peg_chudoba.validate_narrow import complete_validation
            complete_validation(out, selected)
    except Exception as error:
        write(out/'last_error.json',dict(unix=time.time(),error=str(error),traceback=traceback.format_exc(),
                                        status='Incomplete; requires assessment before retry'))
        raise
    finally:
        if (out / 'lease.json').exists():
            owner = read(out/'lease.json')['owner']
            if owner['pid'] == os.getpid() and alive(owner):
                lease(out, 'restore')
        from experiments.peg_chudoba.report_scheduling import render
        render(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, default=DEFAULT)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', action='store_true')
    group.add_argument('--execute', action='store_true')
    ap.add_argument('--benchmark-only', action='store_true')
    args = ap.parse_args()
    out = args.output.resolve()
    plan = prepare(out)
    if args.execute:
        execute(out, plan, args.benchmark_only)
    else:
        print(json.dumps(dict(plan=str(out / 'plan.json'), workloads=len(plan['workloads']),
                             batches=sum(len(w['concurrency']) * 2 for w in plan['workloads']),
                             status='Prepared; no simulations started'), indent=2))


if __name__ == '__main__':
    main()
