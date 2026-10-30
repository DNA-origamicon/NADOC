"""Paired folder enumeration, portable source audit and text-byte admission.

Uses original functions from a pinned revision, with shared unchanged services.
Run under validation_guard with an isolated Archive TMPDIR/workspace.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import time
from unittest.mock import patch

BASELINE = '2f3b962966b4917d9f626e486d56680306600363'


def original(module, name, path):
    source = subprocess.check_output(['git', 'show', f'{BASELINE}:{path}'], text=True)
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = dict(vars(module))
    exec(compile(ast.Module(body=[node], type_ignores=[]), path + ':original', 'exec'), namespace)
    return namespace[name]


def paired(old, new, repeats=21):
    assert old() == new()
    samples = {'baseline': [], 'candidate': []}
    for i in range(repeats):
        order = [('baseline', old), ('candidate', new)]
        for label, fn in order if i % 2 == 0 else order[::-1]:
            start = time.perf_counter()
            result = fn()
            samples[label].append((time.perf_counter() - start) * 1000)
    medians = {key: statistics.median(values) for key, values in samples.items()}
    return dict(median_ms=medians, samples_ms=samples, speedup=medians['baseline']/medians['candidate'])


def main():
    root = Path(os.environ['TMPDIR']).resolve()
    assert Path('/media/jojo/Archive').is_mount() and root.is_relative_to('/media/jojo/Archive')
    assert os.environ.get('NADOC_VALIDATION_SCOPE') == '1'
    assert Path(os.environ['NADOC_WORKSPACE']).resolve().is_relative_to(root)
    from backend.api import routes_fs
    from backend.core import part_document_io as transport, part_overlay_commands as commands
    from backend.core.part_input_sources import portable_sources
    from backend.core.models import Design, SnapshotLogEntry
    old_list = original(routes_fs, '_list_dir', 'backend/api/routes_fs.py')
    old_check = original(transport, 'check_text', 'backend/core/part_document_io.py')
    old_command = original(commands, 'command_input', 'backend/core/part_overlay_commands.py')
    current_command = commands.command_input
    rows = []
    with tempfile.TemporaryDirectory(prefix='round4-', dir=root) as directory:
        for count in (100, 1000, 10000):
            folder = Path(directory) / str(count)
            folder.mkdir()
            for i in range(count):
                path = folder / f'entry-{i:05d}'
                path.mkdir() if i % 10 == 0 else path.touch()
            # Drive free bytes can change independently of enumeration. Keep
            # discovery constant in both arms; end-to-end screen retains it.
            locations = routes_fs._locations()
            old_list.__globals__['_locations'] = lambda: locations
            with patch.object(routes_fs, '_locations', lambda: locations):
                result = paired(lambda: old_list(folder), lambda: routes_fs._list_dir(folder))
            rows.append(dict(operation='directory_enumeration', entries=count, **result))
        for count in (100, 1000, 10000):
            design = Design(feature_log=[SnapshotLogEntry(op_kind='nick', label='Synthetic history', params={}) for _ in range(count)])
            def audit(fn):
                with patch.object(commands, 'command_input', fn):
                    return portable_sources(design)
            rows.append(dict(operation='portable_source_audit', history=count, **paired(lambda: audit(old_command), lambda: audit(current_command))))
        for size in (1, 8, 64):
            text = 'x' * (size * 1024 * 1024)
            rows.append(dict(operation='ascii_text_admission', mib=size, **paired(lambda: old_check(text), lambda: transport.check_text(text))))
        text = 'é' * (4 * 1024 * 1024)
        rows.append(dict(operation='unicode_text_control', mib_utf8=8, **paired(lambda: old_check(text), lambda: transport.check_text(text))))
    sources = ['backend/api/routes_fs.py', 'backend/core/part_overlay_commands.py', 'backend/core/part_document_io.py']
    print(json.dumps(dict(baseline=BASELINE, scope='Warm paired GC-enabled component CPU; no HTTP/rendering. Folder drive discovery held constant; ASCII byte admission synthetic, not whole document parsing. Source audit excludes geometry and retains all source checks.', source_sha256={p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sources}, cases=rows, scratch_removed=not Path(directory).exists()), indent=2))


if __name__ == '__main__':
    main()
