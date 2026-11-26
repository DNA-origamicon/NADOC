"""Bounded storage and thread benchmark; optical inputs only, no NADOC authoring.

Run in the isolated EM interpreter under just validate-safe. Temporary volumes
are removed even on failure; only the requested JSON measurement is retained.
The 300-frame storage test cycles two solved snapshots, NOT a trajectory solve.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import platform
import shutil
import tempfile
import time

import numpy as np

from backend.physics.em_analysis import solve, gold_permittivity
from backend.physics.em_field_evaluator import exterior_electric_field
from backend.physics.em_volume_archive import VolumeArchive, read_frame


def main():
    import miepy
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    scratch = os.environ.get('NADOC_TEST_SCRATCH_ROOT') or tempfile.gettempdir()
    if not Path(scratch).is_dir() or shutil.disk_usage(scratch).free < 512 * 1024**2:
        raise RuntimeError('An existing scratch root with 512 MiB free is required.')
    records = {'cpu': platform.processor(), 'storage': [], 'threads': [],
               'storage_workload': '300 entries cycling two solved optical snapshots per grid, not MD'}
    for resolution in (33, 49):
        results = [solve({'particles': [
            {'id': 'a', 'center_nm': [0, 0, 0], 'diameter_nm': 20},
            {'id': 'b', 'center_nm': [25 + offset, 0, 0], 'diameter_nm': 20}],
            'resolution': resolution, 'polarization': 'parallel'}, arrays=True) for offset in (0, .25)]
        json_bytes = sum(len(json.dumps({**r, 'intensity': np.round(r['intensity'], 6).tolist(),
            'outside': r['outside'].tolist()}, separators=(',', ':')).encode()) for r in results) * 150
        with tempfile.TemporaryDirectory(prefix='nadoc-em-storage-', dir=scratch) as temporary:
            start = time.perf_counter()
            archive = VolumeArchive(Path(temporary) / 'volumes')
            for i in range(300):
                archive.append(results[i % 2], frame_index=i * 10, time_ps=i * .5)
            archive.finish()
            write_seconds = time.perf_counter() - start
            size = sum(p.stat().st_size for p in archive.path.iterdir())
            start = time.perf_counter()
            for i in (299, 150, 0):
                loaded = read_frame(archive.path, i)
                assert loaded['intensity'].tobytes() == results[i % 2]['intensity'].tobytes()
                np.testing.assert_array_equal(loaded['outside'].ravel(), results[i % 2]['outside'])
            row = dict(resolution=resolution, frames=300, archive_bytes=size, json_bytes=json_bytes,
                reduction=json_bytes / size, write_seconds=write_seconds,
                mean_random_read_seconds=(time.perf_counter() - start) / 3)
            records['storage'].append(row)
            print(json.dumps(row), flush=True)
    cluster = miepy.sphere_cluster(position=[[-12.5, 0, 0], [12.5, 0, 0]], radius=[10, 10],
        material=miepy.constant_material(eps=gold_permittivity()),
        source=miepy.sources.plane_wave([1, 0]), wavelength=520, lmax=10,
        medium=miepy.constant_material(index=1.333))
    points = np.stack(np.meshgrid(np.linspace(-32.5, 32.5, 49),
        np.linspace(-20, 20, 49), np.linspace(-20, 20, 49), indexing='ij'), axis=-1).reshape(-1, 3)
    points = points[np.all(np.linalg.norm(points[:, None] - cluster.position[None], axis=-1) > 10.05, axis=1)]
    chunks = [points[i:i + 2048] for i in range(0, len(points), 2048)]
    def evaluate(chunk):
        return exterior_electric_field(cluster, chunk)
    reference = None
    for workers in (1, 2, 4):
        times = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for repeat in range(2):
                start = time.perf_counter()
                fields = np.concatenate(list(pool.map(evaluate, chunks)), axis=1)
                times.append(time.perf_counter() - start)
                if reference is None:
                    reference = fields
                np.testing.assert_allclose(fields, reference, rtol=1e-12, atol=1e-12)
        row = dict(workers=workers, seconds=times, resolution=49, lmax=10,
            max_vector_difference=float(np.max(np.abs(fields - reference))))
        records['threads'].append(row)
        print(json.dumps(row), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(records, indent=2))


if __name__ == '__main__':
    main()
