"""Experimental duplex metadynamics -> frozen-bias production, isolated from jobs.

Run with --help. Existing simulation exports only; never authors NADOC geometry.
Training frames are explicitly excluded from all equilibrium estimates.
"""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import signal
import time

import numpy as np

from tools.oxdna_hybrid.bias import BiasSpec, deposit, force_text
from tools.oxdna_hybrid.runtime import Worker, check_runtime, simulation_input
from tools.oxdna_umbrella.native import digest, scratch_root


def campaign(args):
    root, output = Path(args.inputs).resolve(), Path(args.output).resolve()
    library, oxpy = Path(args.library).resolve(strict=True), Path(args.oxpy).resolve(strict=True)
    validation = json.loads(Path(args.force_validation).read_text())
    if not validation.get('passed') or validation.get('library_sha256') != digest(library):
        raise ValueError('Native force/torque validation receipt does not match this engine')
    scratch_root()  # Verify explicitly configured scratch and mount before any bulk write.
    if os.environ.get('NADOC_TEST_SCRATCH_MOUNT'):
        mount = Path(os.environ['NADOC_TEST_SCRATCH_MOUNT']).resolve(strict=True)
        if not output.is_relative_to(mount) or output.parent.stat().st_dev != mount.stat().st_dev:
            raise ValueError('Output must be on the configured scratch mount')
    if output.exists():
        raise ValueError('Output exists; refusing to mix experiments')
    if not 2 <= args.walkers <= 4 or args.walkers % 2:
        raise ValueError('Use two or four walkers, balanced bound/unbound starts')
    if min(args.period, args.equil_steps, args.production_steps, args.cadence) <= 0 or args.train_steps < 0:
        raise ValueError('Invalid step budget')
    if args.train_steps % args.period or args.period % args.cadence:
        raise ValueError('Training period must divide training steps and match output cadence')
    if args.equil_steps % args.cadence or args.production_steps % args.cadence:
        raise ValueError('Equilibration and production steps must match output cadence')
    if args.production_steps < 20*args.cadence or not np.isfinite(args.max_minutes) or args.max_minutes <= 0:
        raise ValueError('Insufficient production samples or invalid deadline')
    if not np.isfinite([args.temperature, args.salt]).all() or args.temperature <= -273.15 or args.salt <= 0:
        raise ValueError('Invalid thermodynamic conditions')
    if list(root.glob('*cpd*')):
        raise ValueError('CPD propagation is not validated in this prototype; refusing to omit interactions')
    from backend.core.oxdna_vmmc import duplex_pairs
    if len(duplex_pairs(root/'topology.top')) != 8:
        raise ValueError('This benchmark protocol is validated only for an 8-bp duplex')
    if shutil.disk_usage(output.parent).free < 1_000_000_000:
        raise ValueError('Need 1 GB free for bounded campaign')
    spec = (BiasSpec(coordinate='com', minimum=0, maximum=7, width=.2,
                     height_kbt=args.hill_height_kbt, bias_factor=args.bias_factor)
            if args.coordinate == 'com' else BiasSpec(coordinate=args.coordinate,
                     height_kbt=args.hill_height_kbt, bias_factor=args.bias_factor,
                     contact_radius=args.contact_radius))
    output.mkdir()
    inputs = output/'inputs'
    inputs.mkdir()
    files = {}
    for name in ('topology.top', 'vmmc_op.txt', 'oxDNA2_sequence_dependent_parameters.txt', 'conf.dat', 'unbound.dat'):
        source = root/name
        shutil.copy2(source, inputs/name)
        files[name] = {'source': str(source), 'sha256': digest(source)}
    for name in ('conf.dat', 'unbound.dat'):
        header = (inputs/name).read_text().splitlines()
        box = np.fromstring(header[1].split('=')[1], sep=' ')
        if len(box) != 3 or not np.allclose(box, box[0]):
            raise ValueError('Prototype requires matching cubic boxes')
        if name == 'conf.dat':
            reference_box = box
        elif not np.allclose(reference_box, box):
            raise ValueError('Starting boxes differ')
        if spec.coordinate == 'com' and np.linalg.norm(box)/2 >= spec.maximum:
            raise ValueError('COM table does not cover the periodic box')
    concentration = 2/(6.02214076e23*(reference_box[0]*.8518)**3*1e-24)
    started = time.monotonic()
    deadline = started + args.max_minutes*60
    manifest = {'protocol': vars(args), 'bias_spec': asdict(spec), 'files': files,
                'box_oxdna': reference_box.tolist(), 'total_strand_concentration_M': concentration,
                'library_sha256': digest(library), 'oxpy_core_sha256': digest(oxpy/'oxpy/core.so'),
                'force_validation': validation,
                'source_sha256': {p.name: digest(p) for p in Path(__file__).parent.glob('*.py')},
                'temperature_energy_units': '(C+273.15)/3000',
                'training_samples_used_for_equilibrium': False,
                'production_starts': 'fresh bound/unbound exports; independent seeds; frozen shared bias',
                'scope': 'Experimental unmodified DNA2 duplex; statistical precision only; not CPD validation'}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    snapshot = output/'driver_source'
    snapshot.mkdir()
    for source in Path(__file__).parent.glob('*.py'):
        shutil.copy2(source, snapshot/source.name)
        if digest(snapshot/source.name) != manifest['source_sha256'][source.name]:
            raise RuntimeError('Driver source changed during campaign initialization')
    workers = []
    events = (output/'events.jsonl').open('w', buffering=1)

    def emit(event, **values):
        record = {'event': event, 'elapsed_seconds': time.monotonic()-started, **values}
        events.write(json.dumps(record)+'\n')
        if event != 'training_epoch':
            print(json.dumps(record), flush=True)

    def stop_signal(signum, frame):
        raise InterruptedError(f'Campaign interrupted by signal {signum}')

    previous = {s: signal.signal(s, stop_signal) for s in (signal.SIGINT, signal.SIGTERM)}

    def close_workers():
        for worker in workers:
            worker.close()
        workers.clear()

    def start_workers(stage, bias):
        for i in range(args.walkers):
            folder = output/stage/f'replica_{i}'
            folder.mkdir(parents=True)
            conf = inputs/('conf.dat' if i % 2 == 0 else 'unbound.dat')
            seed = args.seed + i + (10000 if stage == 'production' else 0)
            text, a, b = simulation_input(inputs, conf, spec, args.backend, seed,
                                           args.temperature, args.salt, args.cadence)
            if stage == 'production' and args.train_steps == 0:
                text = text.replace('external_forces = true', 'external_forces = false')
            (folder/'input.txt').write_text(text)
            (folder/'forces.txt').write_text(force_text(spec, bias, inputs/'vmmc_op.txt', a, b))
            workers.append(Worker(folder, oxpy, library))
        receipts = [check_runtime(w.receive(deadline), library) for w in workers]
        emit('stage_started', stage=stage, runtime=receipts[0])

    def advance(steps, bias, checkpoint=False):
        for worker in workers:
            worker.send({'action': 'run', 'steps': steps, 'bias': bias.tolist(), 'checkpoint': checkpoint})
        return [worker.receive(deadline) for worker in workers]

    def finish_stage():
        for worker in workers:
            worker.send({'action': 'stop'})
        for worker in workers:
            worker.receive(deadline)
            worker.process.wait(timeout=10)
            if worker.process.returncode:
                raise RuntimeError(f'Worker failed on shutdown: {worker.directory}')
            if 'off grid!' in (worker.directory/'native.log').read_text():
                raise RuntimeError('Native bias left grid')
        close_workers()

    try:
        bias = np.zeros_like(spec.grid)
        if args.train_steps:
            start_workers('training', bias)
            hills = (output/'hills.jsonl').open('w', buffering=1)
            try:
                for epoch in range(args.train_steps//args.period):
                    endpoints = advance(args.period, bias, checkpoint=(epoch+1) % 50 == 0)
                    bias = deposit(spec, bias, [v['cv'] for v in endpoints], (args.temperature+273.15)/3000)
                    hills.write(json.dumps({'epoch': epoch, 'endpoints': endpoints})+'\n')
                    np.save(output/'training_bias.npy', bias)
                    emit('training_epoch', epoch=epoch, endpoints=endpoints)
                    if (epoch+1) % 50 == 0:
                        emit('training_checkpoint', epoch=epoch+1,
                             bias_range_kbt=float(np.ptp(bias)/((args.temperature+273.15)/3000)))
            finally:
                hills.close()
            finish_stage()
        np.save(output/'frozen_bias.npy', bias)
        frozen_hash = digest(output/'frozen_bias.npy')
        emit('bias_frozen', sha256=frozen_hash)
        start_workers('production', bias)
        advance(args.equil_steps, bias, checkpoint=True)
        emit('production_equilibrated', discarded_steps=args.equil_steps)
        completed = 0
        while completed < args.production_steps:
            steps = min(250000, args.production_steps-completed)
            endpoints = advance(steps, bias, checkpoint=True)
            completed += steps
            emit('production_checkpoint', completed_steps=completed, endpoints=endpoints)
        finish_stage()
        if digest(output/'frozen_bias.npy') != frozen_hash:
            raise RuntimeError('Frozen bias changed during production')
        result = {'status': 'completed', 'wall_seconds': time.monotonic()-started,
                  'frozen_bias_sha256': frozen_hash,
                  'production_steps_per_replica': completed, 'walkers': args.walkers,
                  'output_sha256': {str(p.relative_to(output)): digest(p)
                                    for stage in ('training', 'production')
                                    for p in (output/stage).glob('replica_*/*.dat')}}
        (output/'execution.json').write_text(json.dumps(result, indent=2)+'\n')
        emit('completed', **result)
    except BaseException as error:
        emit('failed', error=str(error))
        (output/'failure.json').write_text(json.dumps({'error': str(error)}, indent=2))
        raise
    finally:
        close_workers()
        events.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('inputs', 'output', 'library', 'oxpy', 'force-validation'):
        p.add_argument('--'+key, required=True)
    p.add_argument('--coordinate', choices=('com', 'hb_cutoff', 'mixed'), default='mixed')
    p.add_argument('--backend', choices=('CPU', 'CUDA'), default='CUDA')
    for key, default in [('walkers', 4), ('train-steps', 2000000), ('period', 10000),
                         ('equil-steps', 200000), ('production-steps', 5000000), ('cadence', 1000), ('seed', 913701)]:
        p.add_argument('--'+key, type=int, default=default)
    p.add_argument('--temperature', type=float, default=70.)
    p.add_argument('--salt', type=float, default=.3)
    p.add_argument('--max-minutes', type=float, default=20.)
    p.add_argument('--hill-height-kbt', type=float, default=.5)
    p.add_argument('--bias-factor', type=float, default=10.)
    p.add_argument('--contact-radius', type=float, default=.5)
    return p


if __name__ == '__main__':
    campaign(parser().parse_args())
