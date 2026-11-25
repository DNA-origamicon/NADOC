"""Lossless, frame-addressable derived EM volumes; no molecular authoring.

Each NPZ contains byte-shuffled little-endian float64 samples (C-order xyz for
uniform grids, spatially ordered leaves for octrees), a packed exterior mask, and JSON
metadata. Only committed files appear in the atomically replaced manifest.
Uses NumPy + stdlib only; no pickle, float32 conversion or temporal prediction.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np

FORMAT = 'nadoc-em-volume-v2'


def _json(value):
    return json.dumps(value, allow_nan=False, separators=(',', ':')).encode('utf-8')


def _replace(path, write):
    temporary = path.with_suffix(path.suffix + '.tmp')
    try:
        with temporary.open('xb') as stream:
            write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class VolumeArchive:
    """Single writer, new destination only. Completed frames survive later failure."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=False)
        self.manifest = {'format': FORMAT, 'status': 'writing', 'frames': [],
                         'dtype': '<f8', 'order': 'per-frame: C xyz or octree leaves', 'axes': 'xyz',
                         'mask_bitorder': 'little', 'precision': 'unrounded-float64'}
        self._save()

    def _save(self):
        _replace(self.path / 'manifest.json', lambda f: f.write(_json(self.manifest)))

    def append(self, result, *, frame_index, time_ps=None):
        if self.manifest['status'] != 'writing':
            raise ValueError('Archive is closed.')
        if type(frame_index) is not int or frame_index < 0:
            raise ValueError('frame_index must be a nonnegative integer.')
        if any(row['frame_index'] == frame_index for row in self.manifest['frames']):
            raise ValueError('Duplicate source frame_index.')
        if time_ps is not None and (isinstance(time_ps, bool) or not math.isfinite(time_ps)):
            raise ValueError('time_ps must be finite or null.')
        shape = result['shape']
        adaptive = result.get('sampling', {}).get('layout') == 'octree'
        valid_shape = (len(shape) == 1 and type(shape[0]) is int and 1 <= shape[0] <= 5 * 49**3) if adaptive else (len(shape) == 3 and all(type(n) is int and 1 <= n <= 512 for n in shape))
        if not valid_shape:
            raise ValueError('Expected a bounded three-dimensional grid.')
        count = math.prod(shape)
        values = np.asarray(result['intensity'], dtype='<f8').reshape(-1)
        outside = np.asarray(result['outside'])
        if values.size != count or outside.size != count or outside.dtype != np.bool_:
            raise ValueError('Grid, intensity and boolean mask sizes must agree.')
        if not np.all(np.isfinite(values)) or np.any(values < 0):
            raise ValueError('Intensity must be finite and nonnegative.')
        spatial = {}
        if adaptive:
            for key in ('sample_positions_nm', 'cell_sizes_nm'):
                value = np.asarray(result[key], dtype='<f8')
                if value.shape != (count, 3) or not np.all(np.isfinite(value)):
                    raise ValueError('Invalid adaptive sample geometry.')
                if key == 'cell_sizes_nm' and np.any(value <= 0):
                    raise ValueError('Cell sizes must be positive.')
                spatial[key] = value
        metadata = {key: value for key, value in result.items()
                    if key not in ('intensity', 'outside', *spatial)}
        metadata.update(archive_format=FORMAT, frame_index=frame_index, time_ps=time_ps)
        metadata_bytes = np.frombuffer(_json(metadata), dtype=np.uint8)
        shuffled = np.ascontiguousarray(values).view(np.uint8).reshape(count, 8).T.copy()
        filename = f'frame-{len(self.manifest["frames"]):06d}.npz'
        path = self.path / filename
        _replace(path, lambda f: np.savez_compressed(
            f, intensity_f64_bytes=shuffled,
            outside_bits=np.packbits(outside.reshape(-1), bitorder='little'),
            metadata_utf8=metadata_bytes, **spatial))
        self.manifest['frames'].append({
            'file': filename, 'frame_index': frame_index, 'time_ps': time_ps,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'bytes': path.stat().st_size})
        self._save()

    def finish(self, error=None):
        if self.manifest['status'] != 'writing':
            raise ValueError('Archive is closed.')
        self.manifest['status'] = 'failed' if error is not None else 'complete'
        if error is not None:
            self.manifest['error'] = str(error)
        self._save()


def read_frame(path, ordinal):
    """Read one committed frame, including from incomplete/failed jobs, as arrays."""
    path = Path(path)
    manifest = json.loads((path / 'manifest.json').read_text())
    if manifest['format'] not in (FORMAT, 'nadoc-em-volume-v1'):
        raise ValueError('Unsupported EM archive format.')
    if type(ordinal) is not int or not 0 <= ordinal < len(manifest['frames']):
        raise IndexError('Frame ordinal is outside the committed index.')
    row = manifest['frames'][ordinal]
    filename = row['file']
    if filename != f'frame-{ordinal:06d}.npz':
        raise ValueError('Invalid frame filename.')
    frame_path = path / filename
    if hashlib.sha256(frame_path.read_bytes()).hexdigest() != row['sha256']:
        raise ValueError('EM frame checksum mismatch.')
    with np.load(frame_path, allow_pickle=False) as frame:
        result = json.loads(frame['metadata_utf8'].tobytes())
        if result.get('sampling', {}).get('layout') == 'octree':
            for key in ('sample_positions_nm', 'cell_sizes_nm'):
                result[key] = frame[key].copy()
        count = math.prod(result['shape'])
        shuffled = frame['intensity_f64_bytes']
        if shuffled.dtype != np.uint8 or shuffled.shape != (8, count):
            raise ValueError('Invalid intensity byte layout.')
        bits = frame['outside_bits']
        if bits.dtype != np.uint8 or bits.shape != ((count + 7) // 8,):
            raise ValueError('Invalid exterior mask layout.')
        result['intensity'] = shuffled.T.copy().reshape(-1).view('<f8').reshape(result['shape'])
        result['outside'] = np.unpackbits(bits, count=count, bitorder='little').astype(bool).reshape(result['shape'])
    return result


def write_snapshots(lines, destination, *, solver=None, compute_backend=None):
    """Consume {frame_index, time_ps?, input} JSONL, stopping on the first error."""
    if compute_backend not in (None, 'cpu', 'gpu'):
        raise ValueError('Unknown EM compute backend.')
    if solver is None:
        from backend.physics.em_analysis import solve
        solver = solve
    archive = VolumeArchive(destination)
    try:
        for line in lines:
            entry = json.loads(line)
            payload = dict(entry['input']) if compute_backend is not None else entry['input']
            if compute_backend is not None:
                payload['compute_backend'] = compute_backend
            result = solver(payload, arrays=True)
            archive.append(result, frame_index=entry['frame_index'], time_ps=entry.get('time_ps'))
    except BaseException as exc:
        archive.finish(error=f'{type(exc).__name__}: {exc}')
        raise
    archive.finish()
    return archive.manifest


def main():
    import argparse
    import contextlib
    import sys
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path, help='New archive directory; never overwritten')
    parser.add_argument('--compute-backend', choices=('auto', 'cpu', 'gpu'), default='auto',
                        help='Auto compares eligible GPU against resource-limited parallel CPU')
    parser.add_argument('--workers', type=int, default=None, help='CPU worker ceiling (1–4); resource limits still apply')
    parser.add_argument('--allow-busy-gpu', action='store_true', help='Explicitly permit GPU contention')
    args = parser.parse_args()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            from backend.physics.em_trajectory import write_trajectory
            manifest = write_trajectory(sys.stdin, args.destination, compute_backend=args.compute_backend,
                                        workers=args.workers, allow_busy_gpu=args.allow_busy_gpu)
        print(json.dumps({'status': manifest['status'], 'frames': len(manifest['frames'])}))
    except Exception as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
