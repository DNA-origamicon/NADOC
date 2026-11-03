"""Confirm normal reuse on intermediate meshes captured from a real surface build."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import types
from unittest.mock import patch

from backend.api.routes_display_geometry import _build_design_surface_mesh
from backend.core import surface_remesh
from tests.conftest import make_6hb_design

BASELINE = '2f3b962966b4917d9f626e486d56680306600363'


def fingerprint(mesh):
    return (mesh.vertices.dtype.str, mesh.vertices.shape, mesh.vertices.tobytes(),
            mesh.faces.dtype.str, mesh.faces.shape, mesh.faces.tobytes(),
            tuple(mesh.vertex_strand_ids), tuple(mesh.vertex_nuc_ids))


def main():
    if os.environ.get('NADOC_VALIDATION_SCOPE') != '1':
        raise SystemExit('Use scripts/validation_guard.sh')
    os.environ['NADOC_SURFACE_GPU'] = '0'
    source = subprocess.check_output(
        ['git', 'show', f'{BASELINE}:backend/core/surface_remesh.py'], text=True)
    old = types.ModuleType('desktop_remesh_kernel_original')
    sys.modules[old.__name__] = old
    exec(compile(source, '<original-remesh>', 'exec'), old.__dict__)
    inputs = []
    current = surface_remesh.remesh_sharp_patches

    def capture(mesh, **kwargs):
        inputs.append((mesh, kwargs))
        return current(mesh, **kwargs)

    with patch.object(surface_remesh, 'remesh_sharp_patches', capture):
        _build_design_surface_mesh(make_6hb_design(84), .2, None, 1.3, 15, 'chimerax')
    assert inputs, 'Fixture must exercise local refinement'
    original_inputs = [fingerprint(mesh) for mesh, _ in inputs]
    expected = [fingerprint(old.remesh_sharp_patches(mesh, **kw)) for mesh, kw in inputs]
    samples = [[], []]
    functions = [old.remesh_sharp_patches, current]
    for repeat in range(-2, 15):
        for index in ((0, 1) if repeat % 2 == 0 else (1, 0)):
            start = time.perf_counter()
            outputs = [functions[index](mesh, **kw) for mesh, kw in inputs]
            elapsed = (time.perf_counter() - start) * 1000
            assert [fingerprint(m) for m in outputs] == expected
            assert [fingerprint(m) for m, _ in inputs] == original_inputs
            if repeat >= 0:
                samples[index].append(elapsed)
    normal_calls = []
    for module in (old, surface_remesh):
        with patch.object(module, '_normals', wraps=module._normals) as wrapped:
            for mesh, kw in inputs:
                module.remesh_sharp_patches(mesh, **kw)
            normal_calls.append(wrapped.call_count)
    before, after = map(statistics.median, samples)
    print(json.dumps(dict(baseline=BASELINE,
        candidate_sha256=hashlib.sha256(Path(surface_remesh.__file__).read_bytes()).hexdigest(),
        scope='CPU remeshing of intermediate inputs captured from detailed 6hb-84bp build. Capture, byte comparisons and call counting outside timer; no E2E claim.',
        meshes=len(inputs), input_vertices=sum(len(m.vertices) for m, _ in inputs),
        repeats=15, warmups=2, before_ms=before, after_ms=after, speedup=before/after,
        samples_ms=samples, exact=True, inputs_unchanged=True, normal_calls=normal_calls), indent=2))


if __name__ == '__main__':
    main()
