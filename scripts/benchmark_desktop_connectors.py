"""Paired connector/FK benchmark with complete state equality, no live API state."""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import subprocess
import time
from unittest.mock import patch

import numpy as np
import orjson

from backend.core.assembly_connectors import _enforce_connector_coincidence
from backend.core.assembly_fk import _move_instance_with_fk_delta
from backend.core.models import Mat4x4, InterfacePoint, Vec3, ConnectionType
from scripts.benchmark_assembly_shared_index import _fixture
from scripts.benchmark_assembly_fk import _assembly

BASELINE = '2f3b962966b4917d9f626e486d56680306600363'
ROOT = Path(__file__).resolve().parents[1]


def original_converter():
    source = subprocess.check_output(['git', 'show', f'{BASELINE}:backend/core/models.py'], cwd=ROOT, text=True)
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'Mat4x4')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'from_array')
    scope = {'np': np, 'Mat4x4': Mat4x4}
    exec(compile(ast.Module(body=[method], type_ignores=[]), 'baseline:Mat4x4.from_array', 'exec'), scope)
    return scope['from_array'], hashlib.sha256(source.encode()).hexdigest()


def snapshot(assembly, visited):
    return orjson.dumps({'instances': [x.model_dump(mode='json') for x in assembly.instances],
                         'joints': [j.model_dump(mode='json') for j in assembly.joints],
                         'visited': sorted(visited)})


def fixtures():
    for n in (1, 100, 500):
        yield f'independent-mates-{n}', *_fixture(n), 'connectors'
    for topology in ('chain', 'star'):
        assembly = _assembly(100, 4, topology)
        for i, inst in enumerate(assembly.instances):
            inst.interface_points = [InterfacePoint(label=label, connection_type=ConnectionType.BLUNT_END, position=Vec3(x=.1, y=.2, z=.3),
                                     normal=Vec3(x=0, y=0, z=1)) for label in ('A', 'B')]
            angle = i * .03
            matrix = np.array([[np.cos(angle), -np.sin(angle), 0, i*.1],
                               [np.sin(angle), np.cos(angle), 0, .2], [0, 0, 1, .3], [0, 0, 0, 1.]])
            inst.transform = Mat4x4.from_array(matrix)
            inst.base_transform = Mat4x4.from_array(matrix)
        assembly.instances[15].fixed = True
        assembly.instances[25].base_transform = None
        for j in assembly.joints:
            j.connector_a_label, j.connector_b_label = 'A', 'B'
        yield f'{topology}-rotated-fixed-subtree', assembly, {'i1'}, 'connectors'
        yield f'{topology}-fk', assembly, set(), 'fk'
    assembly, visited = _fixture(3)
    assembly.joints[0].connector_b_label = 'missing'
    assembly.joints[1].instance_a_id = None
    assembly.instances[-1].base_transform = None
    yield 'missing-world-null-base', assembly, visited, 'connectors'


def main():
    before, baseline_hash = original_converter()
    after = Mat4x4.__dict__['from_array']
    results = []
    delta = np.array([[0., -1, 0, .1], [1, 0, 0, .2], [0, 0, 1, .3], [0, 0, 0, 1]])
    for name, template, visited, operation in fixtures():
        original = snapshot(template, visited)
        samples = {'before': [], 'after': []}
        for iteration in range(17):
            states = {}
            for label, method in ([('before', before), ('after', after)] if iteration % 2 else [('after', after), ('before', before)]):
                assembly, active = deepcopy(template), set(visited)
                with patch.object(Mat4x4, 'from_array', method):
                    start = time.perf_counter()
                    if operation == 'connectors':
                        _enforce_connector_coincidence(assembly, active)
                    else:
                        _move_instance_with_fk_delta(assembly, 'i0', delta, active)
                    elapsed = (time.perf_counter() - start) * 1000
                states[label] = snapshot(assembly, active)
                if iteration >= 2:
                    samples[label].append(elapsed)
            assert states['before'] == states['after'], name
        assert snapshot(template, visited) == original, name
        summary = {k: dict(median_ms=statistics.median(v), p95_ms=sorted(v)[math.ceil(len(v)*.95)-1]) for k, v in samples.items()}
        results.append(dict(case=name, operation=operation, samples_ms=samples, summary=summary,
                            speedup=summary['before']['median_ms']/summary['after']['median_ms'],
                            exact_complete_state=True))
    print(json.dumps(dict(scope='CPU connector/FK calls only; fixture copying, context patch and comparisons outside timer; GC enabled',
                          baseline=BASELINE, baseline_source_sha256=baseline_hash,
                          candidate_source_sha256=hashlib.sha256((ROOT/'backend/core/models.py').read_bytes()).hexdigest(),
                          python=platform.python_version(), repeats=15, results=results), indent=2))


if __name__ == '__main__':
    main()
