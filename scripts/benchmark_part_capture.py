"""In-memory native capture diagnostic; no GC changes, retries or raised limits.

Run with ``just validate-safe uv run python -m scripts.benchmark_part_capture``.
Measures capture only, not HTTP/lock contention/rendering or native regeneration.
GC callbacks observe overlapping collections; they cannot attribute scheduling
delays. Instrumentation adds overhead. stdout contains all samples, no designs.
"""

import gc
import json
from time import perf_counter
from unittest.mock import patch

from backend.core import part_capture_inputs
from backend.core.part_verification_capture import CaptureLimit, capture
from scripts.benchmark_part_recipe_edit import fixture


def measure(source, repeats=20):
    samples = []
    original_copy = part_capture_inputs.deepcopy
    copy_seconds = 0.0
    copy_calls = 0
    collections = []
    started_collections = {}

    def observe(phase, info):
        generation = info['generation']
        if phase == 'start':
            started_collections[generation] = perf_counter()
        elif generation in started_collections:
            collections.append((started_collections.pop(generation), perf_counter(), generation))

    def copied(*args, **kwargs):
        nonlocal copy_seconds, copy_calls
        start = perf_counter()
        try:
            return original_copy(*args, **kwargs)
        finally:
            copy_seconds += perf_counter() - start
            copy_calls += 1

    gc.callbacks.append(observe)
    try:
        with patch.object(part_capture_inputs, 'deepcopy', copied):
            for _ in range(repeats):
                copy_seconds, copy_calls = 0.0, 0
                collections.clear()
                start = perf_counter()
                result = None
                try:
                    result = capture(source, preserve_entry_types=True)
                except CaptureLimit as error:
                    status = str(error)
                else:
                    status = 'captured'
                end = perf_counter()
                samples.append({'elapsed_ms': (end - start) * 1000,
                    'copy_ms': copy_seconds * 1000, 'copy_calls': copy_calls,
                    'status': status, 'gc': [
                        {'generation': generation, 'overlap_ms':
                            (min(end, stop) - max(start, began)) * 1000}
                        for began, stop, generation in collections
                        if stop > start and began < end]})
                # Destruction is outside the timed interval; no retained copies.
                del result
    finally:
        gc.callbacks.remove(observe)
    return samples


def main():
    cases = []
    for helices, poses in [(1, 0), (24, 25), (96, 25), (192, 25)]:
        source = fixture(helices, poses)
        cases.append({'helices': helices, 'pose_features': poses,
            'strands': len(source.strands),
            'domains': sum(len(s.domains) for s in source.strands),
            'samples': measure(source)})
    print(json.dumps({'diagnostic': 'ordinary-part-capture',
        'limits': {'seconds': .025, 'nodes': 30000, 'bytes': 2000000},
        'gc_enabled': gc.isenabled(), 'gc_threshold': gc.get_threshold(),
        'qualified': False, 'cases': cases}, indent=2))


if __name__ == '__main__':
    main()
