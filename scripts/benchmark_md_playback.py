#!/usr/bin/env python3
"""Read-only job-specific playback benchmark (not an automated heavy test suite).

Run from the repository root with `uv run python scripts/benchmark_md_playback.py
--job 594917c0d119 --frames 5000 --stride 20 --cold`. Cold is advisory eviction of
only the selected DCD prefix pages, never a machine-wide cache flush.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from threadpoolctl import threadpool_limits  # noqa: E402
from backend.core.models import Design  # noqa: E402
from backend.core.md_playback_context import playback_context  # noqa: E402
from backend.core.md_read_ahead import read_ahead  # noqa: E402
from backend.core.md_trajectory import _extract_md_atoms_frame, _extract_md_full_frame  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', required=True)
    parser.add_argument('--workspace', type=Path, default=Path('workspace'))
    parser.add_argument('--design', type=Path, help='explicit frozen/source design override')
    parser.add_argument('--frames', type=int, default=5000)
    parser.add_argument('--stride', type=int, default=20)
    parser.add_argument('--cold', action='store_true')
    args = parser.parse_args()
    if args.frames < 1 or args.stride < 1:
        parser.error('frames and stride must be positive')
    root = args.workspace / 'md_jobs' / args.job
    job = json.loads((root / 'job.json').read_text())
    package = root / job['package_subdir']
    stem = job['name_stem']
    source = args.design or (root / 'design.json')
    if not source.exists():
        source = args.workspace / job['design_source_path']
    design = Design.from_json(source.read_text())
    dcd = max((package / 'output').glob('*.dcd'), key=lambda p: p.stat().st_size)
    started = time.perf_counter()
    with threadpool_limits(limits=1, user_api='blas'):
        ctx = playback_context(package / (stem + '.psf'), [dcd], package / (stem + '.pdb'), design)
        setup = time.perf_counter() - started
        reader = ctx['dcd_prefix'].readers[0]
        indices = list(range(0, min(args.frames, reader.n_frames), args.stride))

        def evict():
            if not args.cold:
                return
            for i in indices:
                base = reader.frame_start + i * reader.frame_bytes + reader.cell_record_bytes
                for axis in range(3):
                    offset = base + axis * reader.coord_record_bytes
                    start = offset // 4096 * 4096
                    end = (offset + 4 * reader.prefix_atoms + 8191) // 4096 * 4096
                    os.posix_fadvise(reader.fd, start, end - start, os.POSIX_FADV_DONTNEED)

        timings = {}
        for name, extract, ahead in (
            ('read_only', lambda i: reader.frame(i), False),
            ('atoms_aligned', lambda i: _extract_md_atoms_frame(ctx, i, positions_only=True), True),
            ('full_measured_bases', lambda i: _extract_md_full_frame(ctx, i), True),
        ):
            evict()
            start = time.perf_counter()
            with read_ahead(ctx, indices) if ahead else _no_context():
                for index in indices:
                    extract(index)
            timings[name] = time.perf_counter() - start
        print(json.dumps(dict(job=args.job, dcd=str(dcd.resolve()), dcd_bytes=dcd.stat().st_size,
                              source_frames=reader.n_frames, selected_frames=len(indices),
                              stride=args.stride, setup_seconds=setup, advisory_cold=args.cold,
                              prefix_bytes=len(indices)*reader.prefix_atoms*12,
                              heavy_atoms=len(ctx['heavy_idx']),
                              seconds=timings), indent=2))
        ctx['dcd_prefix'].close()


def _no_context():
    from contextlib import nullcontext
    return nullcontext()


if __name__ == '__main__':
    main()
