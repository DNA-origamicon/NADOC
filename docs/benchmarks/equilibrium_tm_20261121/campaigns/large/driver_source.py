"""Bounded, four-core VMMC melting benchmark on an existing native duplex export.

No molecular authoring: topology and starting configurations are copied unchanged.
Fresh tuning, fixed production weights, opposite starts, fixed step checkpoints.
Run with python -m tools.oxdna_vmmc.benchmark --help.
"""
import argparse
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time
from types import SimpleNamespace

import numpy as np

from backend.core.oxdna_vmmc import (
    VmmcMelting, VMMC_ENGINE_SIGNATURE, duplex_pairs, histogram, render_input, tune_weights,
)
from tools.oxdna_umbrella.native import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-dir', type=Path, required=True)
    parser.add_argument('--unbound-conf', type=Path, required=True)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--minutes', type=float, default=55)
    parser.add_argument('--block-steps', type=int, default=2500000)
    parser.add_argument('--blocks', type=int, default=16)
    parser.add_argument('--target-halfwidth', type=float, default=.7)
    parser.add_argument('--seed', type=int, default=191171)
    parser.add_argument('--frozen-weights', type=Path, help='Optional weights trained on prior data; provenance and amortized preparation must be reported separately.')
    parser.add_argument('--continue-campaign', type=Path, help='Continue all four completed replica checkpoints with unchanged conditions; prior production is retained in analysis.')
    parser.add_argument('--translation', type=float, default=.1)
    parser.add_argument('--rotation', type=float, default=.2)
    parser.add_argument('--maxclust', type=int, default=12)
    parser.add_argument('--equil-steps', type=int, default=200000)
    parser.add_argument('--tuning-rounds', type=int, default=8)
    parser.add_argument('--training-walkers', type=int, choices=[1,4], default=1)
    parser.add_argument('--cadence', type=int, default=10000)
    parser.add_argument('--distance-split', type=float, default=0, help='Native minimum base-site distance bin boundary; zero disables.')
    args = parser.parse_args()
    if args.cadence <= 0 or args.block_steps % args.cadence:
        parser.error('Cadence must divide the production block.')
    if not 0 < args.translation <= 2 or not 0 < args.rotation <= 3.14 or not 1 <= args.maxclust <= 16:
        parser.error('Invalid proposal size or cluster cap.')
    if not 0 < args.minutes <= 60 or args.block_steps < 10000 or args.block_steps % 10000 or args.blocks < 1:
        parser.error('Budget must be 0–60 minutes; blocks must be positive multiples of 10,000 sweeps.')
    if not np.isfinite(args.target_halfwidth) or args.target_halfwidth <= 0:
        parser.error('Precision half-width must be positive and finite.')
    if args.distance_split < 0 or args.distance_split > 4:
        parser.error('Distance split must be in [0,4].')
    if args.distance_split and args.frozen_weights:
        parser.error('External frozen weights not supported for two-coordinate experiments.')
    source = args.job_dir.resolve(strict=True)
    binary = args.binary.resolve(strict=True)
    from backend.core.oxdna_runner import _oxdna_contains_signature
    if not _oxdna_contains_signature(str(binary), VMMC_ENGINE_SIGNATURE):
        raise ValueError('Periodic-image-safe VMMC engine required.')
    job = json.loads((source/'job.json').read_text())
    if list(source.glob('*cpd*')):
        raise ValueError('This benchmark is validated for undamaged duplexes only.')
    n_pairs = len(duplex_pairs(source/'topology.top'))
    for checkpoint in (source/'conf.dat', args.unbound_conf):
        coordinates = np.loadtxt(checkpoint, skiprows=3, ndmin=2)
        if coordinates.shape != (2*n_pairs, 15) or not np.isfinite(coordinates).all():
            raise ValueError('Starting checkpoint does not match the duplex topology.')
    boxes = [np.fromstring(p.read_text().splitlines()[1].split('=')[1], sep=' ')
             for p in (source/'conf.dat', args.unbound_conf)]
    if any(b.shape != (3,) or (b <= 0).any() for b in boxes) or not np.allclose(*boxes, rtol=0, atol=1e-10):
        raise ValueError('Bound and unbound starting boxes must match.')
    root = args.output.resolve()
    if shutil.disk_usage(root.parent).free < 1_000_000_000:
        raise ValueError('Benchmark requires 1 GB free space.')
    mount = os.environ.get('NADOC_TEST_SCRATCH_MOUNT')
    if mount:
        mount = Path(mount).resolve(strict=True)
        if not mount.is_mount() or root.parent.stat().st_dev != mount.stat().st_dev:
            raise ValueError('Required output filesystem is not mounted.')
    root.mkdir(exist_ok=False)
    shutil.copy2(__file__, root/'driver_source.py')
    inputs = {name: source/name for name in (
        'topology.top', 'conf.dat', 'oxDNA2_sequence_dependent_parameters.txt', 'vmmc_op.txt')}
    inputs['unbound.dat'] = args.unbound_conf.resolve(strict=True)
    if args.frozen_weights:
        inputs['provided_weights.txt'] = args.frozen_weights.resolve(strict=True)
    for name, path in inputs.items():
        shutil.copy2(path, root/name)
    n_states = (n_pairs+1)*(2 if args.distance_split else 1)
    if args.distance_split:
        op = root/'vmmc_op.txt'
        op.write_text(op.read_text()+'{\norder_parameter = mindistance\nname = approach\nuse_COM = false\ninterfaces = '+str(args.distance_split)+'\n'+''.join(f'pair{i+1} = {a}, {b}\n' for i,(a,b) in enumerate(duplex_pairs(root/'topology.top')))+'}\n')
    def save_weights(path, weights):
        if args.distance_split:
            from tools.oxdna_tm_research.distance import table
            np.savetxt(path, table(weights,n_pairs),fmt=['%d','%d','%.16g'])
        else:
            np.savetxt(path,np.column_stack((np.arange(n_pairs+1),weights)),fmt=['%d','%.16g'])
    def update_weights(weights,counts):
        if not args.distance_split:
            return tune_weights(weights,counts)
        # Positive HB requires the distance bin containing the HB well.
        # Keep unreachable far/bonded bins neutral; they must have zero counts.
        assert not np.any(counts[n_pairs+2:]), 'Far/bonded bins unexpectedly reachable'
        updated=np.ones_like(weights)
        updated[:n_pairs+2]=tune_weights(weights[:n_pairs+2],counts[:n_pairs+2])
        return updated
    cfg = VmmcMelting(temperature_c=70, start_c=64, end_c=78, step_c=.5,
                      tuning_rounds=args.tuning_rounds, tuning_steps=200000, equil_steps=args.equil_steps,
                      production_steps=args.block_steps, replicas=4)
    salt = job['salt_concentration']
    start = time.monotonic()
    deadline = start + args.minutes*60
    active, lock, cancelled = set(), threading.Lock(), threading.Event()

    def emit(event, **data):
        item = dict(event=event, elapsed_seconds=time.monotonic()-start, **data)
        with (root/'events.jsonl').open('a') as stream:
            stream.write(json.dumps(item)+'\n')
        print(json.dumps(item), flush=True)

    def stop(*_):
        cancelled.set()
        with lock:
            for process in active:
                if process.poll() is None:
                    process.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def collect(futures):
        done, _ = wait(futures, return_when=FIRST_EXCEPTION)
        for future in done:
            if future.exception() is not None:
                stop()
                future.result()
        return [future.result()[1] for future in futures]

    manifest = dict(proposals=dict(translation=args.translation, rotation=args.rotation, maxclust=args.maxclust), training_walkers=args.training_walkers, cadence=args.cadence, distance_split=args.distance_split, source=str(source), binary=str(binary), binary_sha256=digest(binary),
                    library_sha256=digest(binary.parent.parent/'lib/liboxdna_common.so'),
                    driver_sha256=digest(root/'driver_source.py'),
                    inputs={n: dict(source=str(p), sha256=digest(p)) for n, p in inputs.items()},
                    protocol=cfg.model_dump(), salt_M=salt, workers=4,
                    seed=args.seed, block_steps=args.block_steps, max_blocks=args.blocks,
                    wall_budget_seconds=args.minutes*60, target_tm_halfwidth_c=args.target_halfwidth,
                    maximum_precision_looks=args.blocks,
                    starts=['bound', 'unbound', 'bound', 'unbound'],
                    cost_scope='Fresh tuning and equilibration included; existing prepared configurations reused.')
    if args.frozen_weights:
        manifest['protocol']['tuning_rounds'] = 0
        manifest['cost_scope'] = 'Prior-trained frozen weights reused; four new equilibrations and independent production included. Prior training cost is not included in this campaign timer.'
    prior_paths = [[] for _ in range(4)]
    prior_confs = None
    if args.continue_campaign:
        raise ValueError('Continuation disabled for proposal comparison; use independent starts.')
        parent = args.continue_campaign.resolve(strict=True)
        previous = json.loads((parent/'manifest.json').read_text())
        previous_result = json.loads((parent/'result.json').read_text())
        for key in ('temperature_c', 'start_c', 'end_c', 'step_c'):
            if previous['protocol'][key] != manifest['protocol'][key]:
                raise ValueError('Continuation temperatures must match.')
        for key in ('salt_M', 'block_steps', 'library_sha256'):
            if previous[key] != manifest[key]:
                raise ValueError(f'Continuation {key} must match.')
        for name in ('topology.top', 'conf.dat', 'oxDNA2_sequence_dependent_parameters.txt', 'vmmc_op.txt'):
            if digest(root/name) != digest(parent/name):
                raise ValueError(f'Continuation {name} must match.')
        if not args.frozen_weights or not np.allclose(np.loadtxt(root/'provided_weights.txt'), np.loadtxt(parent/'frozen_weights.txt'), rtol=1e-14, atol=0):
            raise ValueError('Continuation requires the identical frozen weights.')
        prior_paths = [[Path(p) for p in row] for row in previous_result.get('production_directories', [])]
        if not prior_paths:
            prior_paths = [[parent/f'replica_{i}_block_{j:02}' for j in range(previous_result['completed_blocks'])] for i in range(4)]
        if len(prior_paths) != 4 or len(set(map(len, prior_paths))) != 1:
            raise ValueError('Need four equally sampled prior replicas.')
        for row in prior_paths:
            for directory in row:
                receipt = json.loads((directory/'complete.json').read_text())
                if receipt['returncode'] != 0 or receipt['requested_steps'] != args.block_steps:
                    raise ValueError('Incomplete prior production block.')
                if digest(directory/'input.txt') != receipt['input_sha256']:
                    raise ValueError('Prior production input changed after completion.')
        old_seeds = {json.loads((p/'complete.json').read_text())['seed'] for row in prior_paths for p in row}
        new_seeds = {args.seed+1000+j*4+i for j in range(args.blocks) for i in range(4)}
        if old_seeds & new_seeds:
            raise ValueError('Choose a new --seed for continuation; production streams must not repeat.')
        prior_confs = [row[-1]/'last_conf.dat' for row in prior_paths]
        manifest['continuation'] = dict(parent=str(parent), prior_steps_per_replica=previous_result['production_steps_per_replica'],
                                        checkpoints=[dict(path=str(p), sha256=digest(p)) for p in prior_confs])
        manifest['protocol']['equil_steps'] = 0
        manifest['maximum_precision_looks'] += previous.get('maximum_precision_looks', previous['max_blocks'])
        manifest['cost_scope'] = 'Incremental continuation time only. Prior equilibration and production retained; no retuning or new equilibration.'
    manifest['actual_op_sha256'] = digest(root/'vmmc_op.txt')
    (root/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')

    def execute(name, conf, weights, steps, seed, production=False):
        if cancelled.is_set() or time.monotonic() >= deadline:
            raise TimeoutError('Campaign wall budget reached.')
        directory = root/name
        directory.mkdir()
        save_weights(directory/'weights.txt',weights)
        # Pinned VMMC writes histogram history on configuration output, not
        # energy output. Match cadences to retain actual time-block estimates.
        spec = SimpleNamespace(seed=seed, steps=steps, salt_concentration=salt,
                               print_energy_every_override=args.cadence,
                               print_conf_interval_override=args.cadence if production else max(steps, 1000000))
        text = render_input(root, directory, spec, cfg, conf)
        text = text.replace('delta_translation = 0.1', f'delta_translation = {args.translation}')
        text = text.replace('delta_rotation = 0.2', f'delta_rotation = {args.rotation}')
        text = text.replace('maxclust = 12', f'maxclust = {args.maxclust}')
        text = text.replace('verlet_skin = 1.0', f'verlet_skin = {max(1., 1.8*args.translation)}')
        text = text.replace('print_traj_hist_file = false', f'print_traj_hist_file = {str(production).lower()}\ntraj_hist_file = traj_hist.dat')
        (directory/'input.txt').write_text(text)
        t0 = time.monotonic()
        with (directory/'native.log').open('w') as log:
            with lock:
                if cancelled.is_set():
                    raise TimeoutError('Campaign cancelled.')
                process = subprocess.Popen([str(binary), 'input.txt'], cwd=directory, stdout=log, stderr=subprocess.STDOUT)
                active.add(process)
            timed_out = False
            try:
                process.wait(timeout=max(.01, deadline-time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            finally:
                with lock:
                    active.discard(process)
        report = dict(returncode=process.returncode, elapsed_seconds=time.monotonic()-t0,
                      requested_steps=steps, seed=seed, timed_out=timed_out,
                      input_sha256=digest(directory/'input.txt'))
        (directory/'execution.json').write_text(json.dumps(report, indent=2)+'\n')
        if timed_out or cancelled.is_set():
            raise TimeoutError('Campaign wall budget reached or cancelled; incomplete block excluded.')
        log = (directory/'native.log').read_text()
        if process.returncode or 'END OF THE SIMULATION' not in log:
            raise RuntimeError(f'Native failure in {name}: {log[-1500:]}')
        actual = int((directory/'last_conf.dat').read_text().splitlines()[0].split('=')[1])
        if actual != steps:
            raise RuntimeError(f'Incomplete stage {name}: {actual}/{steps}')
        if args.distance_split:
            from tools.oxdna_tm_research.distance import histogram as read_hist
        else:
            read_hist = histogram
        data = read_hist(directory/'last_hist.dat', n_pairs, len(cfg.temperatures()))
        (directory/'complete.json').write_text(json.dumps(report)+'\n')
        return data, directory/'last_conf.dat'

    paths = prior_paths
    outcome = 'budget_exhausted'
    try:
        weights = np.ones(n_states)
        conf = root/'conf.dat'
        if args.frozen_weights:
            supplied = np.loadtxt(root/'provided_weights.txt', ndmin=2)
            if supplied.shape != (n_pairs+1, 2) or not np.array_equal(supplied[:, 0], np.arange(n_pairs+1)) or not np.isfinite(supplied).all() or (supplied[:, 1] <= 0).any():
                raise ValueError('Invalid supplied frozen weights.')
            weights = supplied[:, 1]
        else:
            if args.training_walkers == 1:
                for i in range(cfg.tuning_rounds):
                    data, conf = execute(f'tune_{i}', conf, weights, cfg.tuning_steps, args.seed+i)
                    weights = update_weights(weights, data[:, 1])
            else:
                train_confs = [root/('conf.dat' if i%2 == 0 else 'unbound.dat') for i in range(4)]
                with ThreadPoolExecutor(max_workers=4) as pool:
                    for i in range(cfg.tuning_rounds):
                        futures = [pool.submit(execute, f'tune_{i}_walker_{j}', train_confs[j], weights,
                                               cfg.tuning_steps, args.seed+10000+4*i+j) for j in range(4)]
                        train_confs = collect(futures)
                        counts = sum(f.result()[0][:,1] for f in futures)
                        weights = update_weights(weights, counts)
                        emit('training_round', round=i, counts=counts.tolist(), weights=weights.tolist())
        save_weights(root/'frozen_weights.txt', weights)
        emit('tuning_complete', weights=weights.tolist())
        with ThreadPoolExecutor(max_workers=4) as pool:
            if prior_confs is not None:
                confs = prior_confs
            else:
                futures = [pool.submit(execute, f'equil_{i}', root/('conf.dat' if i%2 == 0 else 'unbound.dat'),
                                       weights, cfg.equil_steps, args.seed+100+i) for i in range(4)]
                confs = collect(futures)
            emit('equilibration_complete')
            for block in range(args.blocks):
                futures = [pool.submit(execute, f'replica_{i}_block_{block:02}', confs[i], weights,
                                       args.block_steps, args.seed+1000+block*4+i, True) for i in range(4)]
                confs = collect(futures)
                for i in range(4):
                    paths[i].append(root/f'replica_{i}_block_{block:02}')
                # Import late so the analysis module can be developed while native tuning runs.
                if args.distance_split:
                    from tools.oxdna_tm_research.distance import campaign_report
                else:
                    from backend.core.oxdna_vmmc_precision import campaign_report
                report = campaign_report(paths, cfg.temperatures(), n_pairs, target=args.target_halfwidth,
                                         seed=args.seed, bootstrap=1000, max_looks=manifest['maximum_precision_looks'])
                report.update(elapsed_seconds=time.monotonic()-start, completed_blocks=len(paths[0]),
                              production_steps_per_replica=len(paths[0])*args.block_steps,
                              production_directories=[[str(p) for p in row] for row in paths])
                (root/f'checkpoint_{block+1:02}.json').write_text(json.dumps(report, indent=2)+'\n')
                (root/'result.json').write_text(json.dumps(report, indent=2)+'\n')
                emit('precision_checkpoint', tm_c=report['tm_c'], ci95_c=report['ci95_c'],
                     status=report['status'], reasons=report['reasons'], completed_blocks=block+1)
                if report['status'] == 'target_met':
                    outcome = 'target_met'
                    break
                if block+1 == args.blocks:
                    outcome = 'fixed_step_limit'
                    break
                # Do not start a full block when observed speed predicts it cannot finish.
                duration = max(json.loads((p[-1]/'execution.json').read_text())['elapsed_seconds'] for p in paths)
                if time.monotonic()+duration*1.15 >= deadline:
                    break
            else:
                outcome = 'fixed_step_limit'
    except TimeoutError as error:
        if cancelled.is_set():
            outcome = 'cancelled'
        emit('budget_stop', reason=str(error))
    except BaseException as error:
        outcome = 'failed'
        stop()
        emit('failed', error=str(error))
        raise
    finally:
        stop()
        emit('finished', outcome=outcome, completed_blocks_per_replica=[len(p) for p in paths])


if __name__ == '__main__':
    main()
