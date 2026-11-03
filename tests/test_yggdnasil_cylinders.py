"""Verify hollow-cylinder witnesses against NADOC's native crossover graph."""
import hashlib
import json
from pathlib import Path
import subprocess
from scripts.screen_yggdnasil import adjacency

ROOT = Path(__file__).resolve().parents[1]


def test_cylinder_report_matches_native_graphs_and_source_identities():
    report = json.loads((ROOT / 'frontend/src/design/yggdnasil_cylinder_routing.json').read_text())
    for name, digest in report['source_sha256'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    command = "import {enumerateCylinders} from './frontend/src/design/yggdnasil_cylinders.js'; console.log(JSON.stringify(enumerateCylinders()));"
    atlas = json.loads(subprocess.check_output(['node', '--input-type=module', '-e', command], cwd=ROOT))
    records = {key: r for r in report['records'] for key in r['keys']}
    witnesses = 0
    for entry in atlas['entries']:
        record = records[entry['sources'][0]['key']]
        assert record['canonical_sha256'] == hashlib.sha256(entry['canonical'].encode()).hexdigest()
        even = sum((p['row'] + p['col']) % 2 == 0 for p in entry['points'])
        assert (record['even'], record['odd']) == (even, len(entry['points']) - even)
        if record['status'] == 'parity_obstruction':
            assert abs(record['even'] - record['odd']) > 1
        elif record['status'] == 'path_found':
            adj = adjacency(entry)
            path = [str(i) for i in record['path']]
            assert len(path) == len(adj) and set(path) == set(adj)
            assert all(b in adj[a] for a, b in zip(path, path[1:]))
            witnesses += 1
        elif record['status'] == 'no_path':
            assert record['visits'] < report['budget_per_footprint']
        else:
            assert record['status'] == 'unresolved'
            assert record['visits'] >= report['budget_per_footprint']
    assert witnesses == 166
