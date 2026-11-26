"""CPU/GPU trajectory throughput and agreement on identical optical snapshots.

No molecular document is written. Temporary volumes are reopened and removed;
retain only a compact receipt. Run in the EM environment under validate-safe.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import tempfile
import time

import numpy as np

from backend.physics.em_analysis import solve
from backend.physics.em_gpu import device_info
from backend.physics.em_volume_archive import read_frame, write_snapshots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = Path('workspace/Plasmonic_test.nadoc')
    raw = source.read_bytes()
    particles = [{'id': p['id'], 'diameter_nm': p['diameter_nm'],
                  'center_nm': [p['pose']['values'][i] for i in (3, 7, 11)]}
                 for p in json.loads(raw)['nanoparticles']]
    if len(particles) != 2:
        raise ValueError('This benchmark requires the two-particle Plasmonic example.')
    axis = np.subtract(particles[1]['center_nm'], particles[0]['center_nm'])
    axis /= np.linalg.norm(axis)
    scratch = Path(os.environ.get('NADOC_TEST_SCRATCH_ROOT') or tempfile.gettempdir())
    mount = os.environ.get('NADOC_TEST_SCRATCH_MOUNT')
    if not scratch.is_dir() or shutil.disk_usage(scratch).free < 512 * 1024**2:
        raise RuntimeError('Existing scratch directory with 512 MiB free required.')
    if mount and (not Path(mount).is_mount() or not scratch.resolve().is_relative_to(Path(mount).resolve())):
        raise RuntimeError('Configured scratch mount unavailable or mismatched.')
    receipt = {'source_sha256': hashlib.sha256(raw).hexdigest(), 'machine': platform.node(),
               'workload': 'Synthetic optical snapshots, not MD; full independent solves and compressed archives',
               'threads': {key: os.environ.get(key) for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS')},
               'cases': []}
    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(receipt, indent=2))
    start = time.perf_counter()
    receipt['gpu'] = device_info()
    receipt['gpu_initialization_seconds'] = time.perf_counter() - start
    # Both paths import MiePy and warm with the same small frame before timing.
    base = {'particles': particles, 'resolution': 25, 'sampling': 'field_adaptive',
            'solver': 'multipole', 'shell': {'model': 'none'}}
    receipt['first_frame_seconds'] = {}
    for backend in ('cpu', 'gpu'):
        start = time.perf_counter()
        solve({**base, 'compute_backend': backend}, arrays=True)
        receipt['first_frame_seconds'][backend] = time.perf_counter() - start
    save()
    cases = [(33, 'close', 'none'), (33, 'separated', 'none'), (49, 'close', 'none'),
             (33, 'close', 'manual')]
    for resolution, spacing, shell in cases:
        entries = []
        for index, offset in enumerate((-.25, 0., .25)):
            payload = copy.deepcopy(base)
            payload['resolution'] = resolution
            payload['particles'][1]['center_nm'] = (np.array(particles[1]['center_nm']) +
                axis * (offset + (20. if spacing == 'separated' else 0.))).tolist()
            if shell == 'manual':
                payload['shell'] = {'model': 'manual', 'thickness_nm': .5, 'refractive_index': 1.7}
            entries.append(json.dumps({'frame_index': 10 * index, 'time_ps': float(index), 'input': payload}))
        case = {'resolution': resolution, 'spacing': spacing, 'shell': shell, 'backends': {}}
        with tempfile.TemporaryDirectory(prefix='nadoc-em-gpu-bench-', dir=scratch) as root:
            for backend in ('cpu', 'gpu'):
                start = time.perf_counter()
                archive = Path(root) / backend
                write_snapshots(entries, archive, compute_backend=backend)
                elapsed = time.perf_counter() - start
                frames = [read_frame(archive, i) for i in range(len(entries))]
                case['backends'][backend] = {'total_seconds': elapsed, 'seconds_per_frame': elapsed/len(entries),
                    'frames': [{key: f[key] for key in ('elapsed_seconds', 'timing_seconds', 'gap_nm',
                                'peak_intensity', 'multipole_order', 'shape', 'compute_backend')} for f in frames]}
                print(json.dumps({'resolution': resolution, 'spacing': spacing, 'shell': shell,
                                  'backend': backend, 'seconds_per_frame': elapsed/len(entries)}), flush=True)
            errors = []
            for i in range(len(entries)):
                cpu, gpu = (read_frame(Path(root)/backend, i) for backend in ('cpu', 'gpu'))
                assert cpu['frame_index'] == gpu['frame_index'] == 10*i
                assert cpu['multipole_order'] == gpu['multipole_order']
                # Adaptive rankings may break exact ties differently. Compare full
                # volumes only when the selected cells agree, never by ordinal alone.
                same = (cpu['shape'] == gpu['shape'] and
                        np.array_equal(cpu['sample_positions_nm'], gpu['sample_positions_nm']))
                peak_error = abs(cpu['peak_intensity']-gpu['peak_intensity'])/max(1., cpu['peak_intensity'])
                row = {'same_sample_positions': same, 'peak_relative_error': peak_error}
                if same:
                    error = float(np.max(np.abs(cpu['intensity']-gpu['intensity'])/np.maximum(1., cpu['intensity'])))
                    assert error < 1e-8, error
                    np.testing.assert_array_equal(cpu['outside'], gpu['outside'])
                    row['max_normalized_intensity_error'] = error
                assert peak_error < 1e-5, row
                errors.append(row)
            case['agreement'] = errors
        assert not Path(root).exists()
        case['scratch_cleanup_verified'] = True
        case['speedup'] = case['backends']['cpu']['total_seconds']/case['backends']['gpu']['total_seconds']
        receipt['cases'].append(case)
        save()
    assert source.read_bytes() == raw
    receipt['source_unchanged'] = True
    save()


if __name__ == '__main__':
    main()
