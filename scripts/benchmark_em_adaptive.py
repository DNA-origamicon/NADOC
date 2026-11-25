"""Current field-adaptive throughput: read-only optical snapshots, not an MD run.

Run in the EM interpreter under validate-safe. Fresh temporary archives are cleaned;
only a compact receipt is retained. Each frame is solved independently.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np

from backend.physics.em_analysis import solve
from backend.physics.em_volume_archive import VolumeArchive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = Path('workspace/Plasmonic_test.nadoc')
    raw_bytes = source.read_bytes()
    design = json.loads(raw_bytes)
    particles = [{'id': p['id'], 'center_nm': [p['pose']['values'][i] for i in (3, 7, 11)],
                  'diameter_nm': p['diameter_nm']} for p in design['nanoparticles']]
    payload = dict(particles=particles, resolution=33, sampling='field_adaptive',
                   solver='multipole', polarization='parallel', shell={'model': 'none'})
    scratch = Path(os.environ.get('NADOC_TEST_SCRATCH_ROOT') or tempfile.gettempdir())
    if not scratch.is_dir() or shutil.disk_usage(scratch).free < 512*1024**2:
        raise RuntimeError('Existing scratch directory with 512 MiB free required.')
    mount = os.environ.get('NADOC_TEST_SCRATCH_MOUNT')
    if mount and (not Path(mount).is_mount() or not scratch.resolve().is_relative_to(Path(mount).resolve())):
        raise RuntimeError('Configured scratch mount unavailable or mismatched.')
    records = {'source_sha256': hashlib.sha256(raw_bytes).hexdigest(),
        'workload': 'Independent optical solves; original poses plus axial offsets of NP2, not MD frames',
        'machine': platform.node(), 'python': sys.version, 'threads': {name: os.environ.get(name)
            for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS')}, 'cases': []}
    cpuinfo = Path('/proc/cpuinfo').read_text()
    records['cpu'] = next((line.split(':', 1)[1].strip() for line in cpuinfo.splitlines()
                           if line.startswith('model name')), platform.processor())
    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(records, indent=2))
    started = time.perf_counter()
    cold = subprocess.run([sys.executable, '-m', 'backend.physics.em_analysis'], input=json.dumps(payload),
                          text=True, capture_output=True, timeout=180, check=True)
    records['cold_worker_seconds'] = time.perf_counter() - started
    cold_result = json.loads(cold.stdout)
    records['cold_solver_seconds'] = cold_result['elapsed_seconds']
    print(json.dumps({key: records[key] for key in ('cold_worker_seconds', 'cold_solver_seconds')}), flush=True)
    # Warm this interpreter's imports separately from measured independent frames.
    started = time.perf_counter()
    import miepy  # noqa: F401
    records['warm_import_seconds'] = time.perf_counter() - started
    save()
    direction = np.array(particles[1]['center_nm']) - particles[0]['center_nm']
    direction /= np.linalg.norm(direction)
    for resolution, shell, offsets in [(25, 'none', [-.25, 0, .25]),
            (33, 'none', [-.5, -.25, 0, .25, .5]), (49, 'none', [-.25, 0, .25]),
            (33, 'manual', [-.25, 0, .25])]:
        case = {'resolution': resolution, 'shell': shell, 'frames': []}
        with tempfile.TemporaryDirectory(prefix='nadoc-em-adaptive-bench-', dir=scratch) as root:
            archive = VolumeArchive(Path(root) / 'frames')
            for index, offset in enumerate(offsets):
                request = json.loads(json.dumps(payload))
                request['resolution'] = resolution
                request['particles'][1]['center_nm'] = (np.array(particles[1]['center_nm']) + offset*direction).tolist()
                if shell == 'manual':
                    request['shell'] = {'model': 'manual', 'thickness_nm': .5, 'refractive_index': 1.7}
                start = time.perf_counter()
                result = solve(request, arrays=True)
                solved = time.perf_counter()
                archive.append(result, frame_index=index)
                written = time.perf_counter()
                row = {'offset_nm': offset, 'solve_seconds': solved-start,
                    'archive_seconds': written-solved, 'total_seconds': written-start,
                    'stage_seconds': result['timing_seconds'], 'samples': len(result['intensity']),
                    'multipole_order': result['multipole_order'], 'gap_nm': result['gap_nm'],
                    'refinement': result['sampling']['field_refinement'],
                    'archive_bytes': archive.manifest['frames'][-1]['bytes']}
                case['frames'].append(row)
                print(json.dumps({'resolution': resolution, 'shell': shell, **row}), flush=True)
            archive.finish()
        assert not Path(root).exists()
        times = [row['total_seconds'] for row in case['frames']]
        case.update(mean_seconds=float(np.mean(times)), min_seconds=min(times), max_seconds=max(times),
                    estimated_100_seconds=float(100*np.mean(times)), scratch_cleanup_verified=True)
        records['cases'].append(case)
        save()
    assert source.read_bytes() == raw_bytes
    records['source_unchanged'] = True
    save()


if __name__ == '__main__':
    main()
