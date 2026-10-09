"""Read-only paired scene-export benchmark for an authored design.

Run with --baseline <git revision> to check the optimized exporter against the
previous serializer and curve sampler. Includes geometry construction; excludes
browser transport, native activation and headset frame timing (use the live tour
for those). Never writes the input design or publishes to a viewer.
"""
import argparse
import ast
from contextlib import ExitStack
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time
from unittest.mock import patch

from backend.api import routes_vr as vr
from backend.core import native_slab_placement, vr_axis_lines, vr_scene_projection
from backend.core.models import Design


def previous_function(revision, module, name):
    path = str(Path(module.__file__).relative_to(Path(__file__).resolve().parents[1]))
    source = subprocess.check_output(['git', 'show', f'{revision}:{path}'], text=True)
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = vars(module).copy()
    from backend.core.native_slab_placement import authoritative_slab_pose
    scope['authoritative_slab_pose'] = authoritative_slab_pose
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, 'exec'), scope)
    return scope[name]


def wire_difference(before, after):
    """Exact record/identity checks, with 1e-12 absolute float roundoff only."""
    maximum = 0.
    changed = 0
    numeric_start = {'P': 2, 'C': 2, 'H': 2, 'B': 2, 'N': 2, 'V': 2, 'U': 2,
                     'J': 4, 'K': 2, 'O': 1}
    for left, right in zip(before, after, strict=True):
        if left == right:
            continue
        changed += 1
        a, b = left.split(), right.split()
        start = numeric_start.get(a[0], len(a))
        if len(a) != len(b) or a[:start] != b[:start]:
            raise RuntimeError(f'Scene structure changed: {left!r} / {right!r}')
        for x, y in zip(a[start:], b[start:], strict=True):
            delta = abs(float(x) - float(y))
            if not math.isfinite(delta) or delta > 1e-12:
                raise RuntimeError(f'Scene geometry changed: {left!r} / {right!r}')
            maximum = max(maximum, delta)
    return dict(changed_records=changed, max_absolute_numeric_delta=maximum)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design', type=Path, required=True)
    parser.add_argument('--baseline')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--representation', default='full')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.design.read_bytes()
    design = Design.model_validate_json(raw)
    before = None
    if args.baseline:
        before = (previous_function(args.baseline, vr, '_serialize_scene'),
                  previous_function(args.baseline, vr_scene_projection, '_centripetal_catmull_rom'),
                  previous_function(args.baseline, native_slab_placement, 'attach_native_slab_poses'))
    rows = []
    reference_lines = None
    parity = []
    for repeat in range(args.repeats):
        for baseline in ([True, False] if repeat % 2 == 0 else [False, True]):
            if baseline and before is None:
                continue
            digest = hashlib.sha256()
            count = 0
            lines = []
            def write(line):
                nonlocal count
                digest.update((line + '\n').encode())
                count += 1
                lines.append(line)
            with ExitStack() as stack:
                if baseline:
                    stack.enter_context(patch.object(vr, '_serialize_scene', before[0]))
                    stack.enter_context(patch.object(vr_scene_projection, '_centripetal_catmull_rom', before[1]))
                    stack.enter_context(patch.object(vr_axis_lines, '_centripetal_catmull_rom', before[1]))
                    stack.enter_context(patch.object(native_slab_placement, 'attach_native_slab_poses', before[2]))
                started = time.perf_counter()
                vr._snapshot(vr.VRLaunchRequest(representation=args.representation),
                             design_snapshot=design, line_writer=write,
                             representations={'full', args.representation})
                elapsed = time.perf_counter() - started
            row = dict(baseline=baseline, repeat=repeat, seconds=elapsed,
                       lines=count, sha256=digest.hexdigest())
            rows.append(row)
            print(json.dumps(row), flush=True)
            if reference_lines is None:
                reference_lines = lines
            parity.append(wire_difference(reference_lines, lines))
    report = dict(design=str(args.design), source_sha256=hashlib.sha256(raw).hexdigest(),
                  baseline=args.baseline, representation=args.representation, samples=rows,
                  exact_wire_parity=len({r['sha256'] for r in rows}) == 1,
                  numeric_roundoff_tolerance=1e-12, parity=parity)
    args.output.write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
