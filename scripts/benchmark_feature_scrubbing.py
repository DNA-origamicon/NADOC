"""Paired, offline scrub benchmark; never touches a running document or user file.

Run with `just validate-safe uv run python -m scripts.benchmark_feature_scrubbing
--design workspace/VoltronCoreArmV2.nadoc --output /tmp/feature-scrub.json`.
The scalar slab conversion is the pre-optimization reference. Every pair checks
full state and wire-geometry equality, including history bodies after rehydration.
"""
from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
from time import perf_counter

from scipy.spatial.transform import Rotation

from backend.api import state
from backend.api.routes_feature_log import SeekFeaturesBody, preview_features, seek_features
from backend.core.models import Design
from backend.core import native_slab_placement as slab


def scalar_slab_reference(records):
    for record in records:
        pose = slab._expected_slab_pose(record)
        if pose is None:
            record['slab_position'] = None
            record['slab_quaternion'] = None
        else:
            center, frame = pose
            record['slab_position'] = center.tolist()
            record['slab_quaternion'] = Rotation.from_matrix(frame).as_quat().tolist()
    return records


def benchmark(path: Path, repeats: int):
    design = Design.from_json(path.read_text())
    positions = [(max(0, len(design.feature_log) // 2), None), (-1, None)]
    for index, entry in enumerate(design.feature_log):
        if getattr(entry, 'children', None):
            positions.append((index, len(entry.children) // 2))
            break
    optimized = slab.attach_native_slab_poses
    rows = []
    try:
        for position, child in positions:
            for repeat in range(repeats + 1):  # first pair warms imports/caches
                pair = {}
                for mode in (['baseline', 'optimized'] if repeat % 2 == 0 else ['optimized', 'baseline']):
                    slab.attach_native_slab_poses = scalar_slab_reference if mode == 'baseline' else optimized
                    state.load_design(design)
                    revision = state.revision()
                    gc.collect()
                    start = perf_counter()
                    options = {}
                    preview_s = None
                    if mode == 'optimized':
                        preview = json.loads(preview_features(SeekFeaturesBody(position=position, sub_position=child)).body)
                        preview_s = perf_counter() - start
                        options = dict(preview_token=preview['preview_token'], known_revision=revision)
                    response = seek_features(SeekFeaturesBody(position=position, sub_position=child, **options))
                    elapsed = perf_counter() - start
                    row = dict(mode=mode, repeat=repeat, position=position, sub_position=child,
                               preview_s=preview_s, ready_s=elapsed, bytes=len(response.body),
                               server_timing=response.headers.get('server-timing'))
                    rows.append(row)
                    print(json.dumps(row), flush=True)
                    payload = json.loads(response.body)
                    payload.pop('revision', None)
                    payload.pop('feature_log_payloads_partial', None)
                    payload['design']['feature_log'] = [entry.model_dump(mode='json') for entry in design.feature_log]
                    pair[mode] = (state.get_or_404().model_dump(), payload)
                    state.close_session()
                assert pair['baseline'] == pair['optimized'], (position, child, 'state/geometry changed')
    finally:
        slab.attach_native_slab_poses = optimized
        state.close_session()
    return dict(design=path.name, helices=len(design.helices), strands=len(design.strands),
                features=len(design.feature_log), warmup_repeat=0, rows=rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(benchmark(args.design, args.repeats), indent=2) + '\n')
