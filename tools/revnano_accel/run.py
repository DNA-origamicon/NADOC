"""Run the pinned REVNANO solver with optional bounded caching and parallel Pass 2."""
import os
for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[name] = '1'
import argparse
import hashlib
import json
from pathlib import Path
import resource
import sys
import subprocess
import tempfile
import time

from engine import install_run_cache, limit_memory, parallel_builder


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input', type=Path)
    p.add_argument('--source', type=Path, default=Path('.development-artifacts/revnano-gerling2018'))
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--mode', choices=['original', 'cached', 'parallel'], default='parallel')
    p.add_argument('--workers', type=int, default=4)
    p.add_argument('--budget-mib', type=int, default=4096)
    p.add_argument('--parent-mib', type=int, default=1024)
    p.add_argument('--worker-mib', type=int, default=512)
    p.add_argument('--cache-mib', type=int, default=32)
    p.add_argument('--limit-staples', type=int, help='Diagnostic prefix only; never a full-design result.')
    p.add_argument('--stage0-only', action='store_true')
    p.add_argument('--seven-route-bonus',type=float,choices=[0,1,3,7],default=0)
    p.add_argument('--ordered-pruning',action='store_true')
    p.add_argument('--mu-min',type=int,choices=[5,6],default=6)
    p.add_argument('--sigma',type=int,choices=range(11),default=4)
    p.add_argument('--beta',type=float,default=.3)
    a = p.parse_args()
    if not 0<a.beta<=1:p.error('beta must be in (0,1]')
    if min(a.workers, a.worker_mib, a.parent_mib, a.budget_mib) <= 0 or a.cache_mib < 0:
        p.error('Memory and worker counts must be positive; cache may be zero.')
    if a.parent_mib > a.budget_mib or a.cache_mib >= min(a.parent_mib, a.worker_mib):
        p.error('Budget is smaller than controller or cache exceeds process allowance.')
    workers = min(a.workers, os.cpu_count() or 1, (a.budget_mib-a.parent_mib)//a.worker_mib)
    if a.mode == 'parallel' and workers < 1:
        p.error('Budget cannot accommodate one worker plus controller.')
    if a.limit_staples is not None and a.limit_staples <= 0:
        p.error('Diagnostic prefix must be positive.')
    a.output.mkdir(parents=True, exist_ok=True)
    if (a.output/'summary.json').exists():
        p.error('Output already has a summary; use a new directory to preserve evidence.')
    source = a.source.resolve()
    sys.path.insert(0, str(source))
    limit_memory(a.parent_mib)
    from REVNANO import revnano, stage0
    from contactmap import iohandler
    if a.seven_route_bonus:
        from REVNANO import stage2
        original_distance = stage2.staple_routing_distance
        def preferred_distance(origami,route):
            return original_distance(origami,route)-a.seven_route_bonus*sum(length/7 for _,length in route if length%7==0)
        stage2.staple_routing_distance = preferred_distance
    pruning_stats = {'enabled': False}
    if a.ordered_pruning:
        from ordered_pruning import install
        pruning_stats, _ = install()
    # Refuse silently unsupported forks. The only change to upstream is the hook.
    upstream_commit = subprocess.check_output(['git', '-C', str(source/'REVNANO'), 'rev-parse', 'HEAD'], text=True).strip()
    contactmap_commit = subprocess.check_output(['git', '-C', str(source/'contactmap'), 'rev-parse', 'HEAD'], text=True).strip()
    if upstream_commit != '36a72c13670004a23bc7aad0db44c2ab36c1b207':
        p.error('This adapter is validated only for the pinned REVNANO commit.')
    if contactmap_commit != '8bd39737d2341f1d47dba8456fc1ce8f9bb86150':
        p.error('This adapter requires the pinned contactmap revision.')
    x = revnano.read_rev_file(a.input.stem, str(a.input.resolve().parent), verbose=True)
    if x is None:
        p.error('REVNANO rejected the input.')
    if a.limit_staples:
        if x['extra_staples']:
            p.error('Diagnostic prefix restriction is not supported for loopout inputs.')
        x['staples53'] = x['staples53'][:a.limit_staples]
        x['num_staples'] = len(x['staples53'])
        x['num_physical_staples'] = len(x['staples53'])
    metrics = []
    cache = install_run_cache(a.cache_mib) if a.mode != 'original' else None
    summary = {'input_sha256': hashlib.sha256(a.input.read_bytes()).hexdigest(), 'mode': a.mode,
               'workers': workers if a.mode == 'parallel' else 0, 'parent_address_limit_mib': a.parent_mib,
               'worker_address_limit_mib': a.worker_mib if a.mode == 'parallel' else 0,
               'address_limit_sum_mib': a.parent_mib + (workers*a.worker_mib if a.mode == 'parallel' else 0),
               'cache_limit_mib_per_process': a.cache_mib, 'diagnostic_prefix': a.limit_staples,
               'scientific_parameters': {'MU_MIN': a.mu_min, 'SIGMA': a.sigma, 'BETA': a.beta, 'MAX_SUBTREES': 10000, 'seven_route_bonus': a.seven_route_bonus},
               'source_commit': upstream_commit, 'contactmap_commit': contactmap_commit,
               'adapter_sha256': {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in ('engine.py', 'run.py', 'ordered_pruning.py')},
               'stage0_source_sha256': hashlib.sha256((source/'REVNANO'/'stage0.py').read_bytes()).hexdigest()}
    import shutil
    snapshot = a.output/'adapter_source'
    snapshot.mkdir(exist_ok=True)
    for name in ('run.py','engine.py','ordered_pruning.py'):
        shutil.copy2(Path(__file__).with_name(name),snapshot/name)
    start = time.perf_counter()
    status = 0
    with tempfile.TemporaryDirectory(prefix='trees-', dir=a.output) as temporary:
        if a.mode == 'parallel':
            if not hasattr(stage0, 'parallel_builder'):
                p.error('Apply tools/revnano_accel/stage0_hook.patch to pinned source first.')
            stage0.parallel_builder = parallel_builder(temporary, source, workers, a.worker_mib, a.cache_mib, metrics)
        try:
            if a.stage0_only:
                stage0.process(x, a.mu_min, a.sigma, a.beta, True)
                result, error = None, None
            else:
                result, error = revnano.reverse_engineer(x, a.mu_min, a.sigma, a.beta, True, verbose=True)
            summary['solver_error'] = error
            summary['stage_results'] = {k: v for k, v in x.items() if k.startswith('stage') and k.endswith('_result')}
            summary['no_tree_ids'] = x['staple_ids_with_no_tree']
            summary['tree_digests'] = {str(i): hashlib.sha256(repr(tree).encode()).hexdigest() for i, tree in x['staple_routing_trees'].items()}
            if result is not None:
                encoded = json.dumps(result, sort_keys=True, separators=(',', ':'))
                (a.output/'contactmap.json').write_text(encoded+'\n')
                summary['contactmap_sha256'] = hashlib.sha256(encoded.encode()).hexdigest()
                # Use native writer to keep the supported contact-map format.
                iohandler.write_origami_contactmap(result, str(a.output), 'contactmap.csv', madeby='REVNANO bounded adapter')
            status = 2 if error else 0
        except KeyboardInterrupt:
            summary['execution_error'] = 'KeyboardInterrupt'
            status = 130
            raise
        except Exception as exc:
            summary['execution_error'] = f'{type(exc).__name__}: {exc}'
            status = 3
            raise
        finally:
            summary['ordered_pruning'] = pruning_stats
            summary['solver_seconds'] = time.perf_counter() - start
            summary['parent_peak_rss_mib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            summary['cache'] = cache
            summary['worker_tasks'] = metrics
            peaks = {}
            for item in metrics:
                peaks[item['pid']] = max(peaks.get(item['pid'], 0), item['peak_rss_mib'])
            summary['sum_process_peak_rss_mib_upper_bound'] = summary['parent_peak_rss_mib'] + sum(peaks.values())
            summary['exit_status'] = status
            (a.output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
            # Store is ephemeral; never pickle a mapping with deleted backing paths.
            diagnostic_keys = ['staples53','staples_placed','extra_staples','staple_ids_with_no_tree','staple_ids_with_zero_route','staple_ids_with_persistent_ambiguous_route','staple_ids_with_overlap_problems']
            (a.output/'fragment_diagnostics.json').write_text(json.dumps({k:x.get(k) for k in diagnostic_keys},indent=2)+'\n')
            x['staple_routing_trees'] = None
    print(json.dumps({k: v for k, v in summary.items() if k not in ('worker_tasks', 'tree_digests')}, indent=2))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
