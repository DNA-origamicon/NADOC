"""Paired whole-surface check for round-2 normal reuse; isolated CPU fixtures."""
from __future__ import annotations

import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
import types
from unittest.mock import patch

from backend.core import surface_remesh
from backend.api.routes_display_geometry import _build_design_surface_mesh
from tests.conftest import make_6hb_design

BASELINE = '2f3b962966b4917d9f626e486d56680306600363'


def main():
    if os.environ.get('NADOC_VALIDATION_SCOPE') != '1':
        raise SystemExit('Use scripts/validation_guard.sh')
    os.environ['NADOC_SURFACE_GPU'] = '0'
    source = subprocess.check_output(
        ['git', 'show', f'{BASELINE}:backend/core/surface_remesh.py'], text=True)
    old = types.ModuleType('desktop_original_remesh')
    sys.modules[old.__name__] = old
    exec(compile(source, '<original-remesh>', 'exec'), old.__dict__)
    current = surface_remesh.remesh_sharp_patches
    design = make_6hb_design(84)
    design_before = design.model_dump_json()
    rows = []
    for detail in ('coarse', 'chimerax'):
        samples = [[], []]
        expected = None
        for repeat in range(-1, 7):
            for index in ((0, 1) if repeat % 2 == 0 else (1, 0)):
                with patch.object(surface_remesh, 'remesh_sharp_patches',
                                  old.remesh_sharp_patches if index == 0 else current):
                    start = time.perf_counter()
                    mesh = _build_design_surface_mesh(design, .2, None, 1.3, 15, detail)
                    elapsed = (time.perf_counter() - start) * 1000
                if expected is None:
                    expected = mesh
                assert mesh.vertices.dtype == expected.vertices.dtype
                assert mesh.faces.dtype == expected.faces.dtype
                assert mesh.vertices.tobytes() == expected.vertices.tobytes()
                assert mesh.faces.tobytes() == expected.faces.tobytes()
                assert mesh.vertex_strand_ids == expected.vertex_strand_ids
                assert mesh.vertex_nuc_ids == expected.vertex_nuc_ids
                assert design.model_dump_json() == design_before
                if repeat >= 0:
                    samples[index].append(elapsed)
        before, after = map(statistics.median, samples)
        rows.append(dict(detail=detail, before_ms=before, after_ms=after,
                         speedup=before/after, samples_ms=samples, exact=True,
                         vertices=len(mesh.vertices), faces=len(mesh.faces),
                         vertex_sha256=hashlib.sha256(mesh.vertices.tobytes()).hexdigest(),
                         face_sha256=hashlib.sha256(mesh.faces.tobytes()).hexdigest()))
    print(json.dumps(dict(baseline=BASELINE, warmups=1, repeats=7,
                          scope='Whole CPU surface build; only remesh function alternates. Exact bytes and ownership checked outside timer. No GPU/E2E claim.',
                          results=rows), indent=2))


if __name__ == '__main__':
    main()
