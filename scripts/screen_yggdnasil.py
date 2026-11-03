#!/usr/bin/env python3
"""Audit YggDNAsil's finite rod grammar against NADOC's Hamiltonian traversal.

Run from the repository root: .venv/bin/python scripts/screen_yggdnasil.py
No live designs or routing algorithms are modified. A full-period crossover
supergraph makes graph impossibility independent of axial length/register.
Witnesses prove traversal only, not a full scaffold route or budget completion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.core.crossover_positions import crossover_neighbor
from backend.core.models import LatticeType
from backend.core.seamed_router import _ham_path_search


def adjacency(entry):
    points = entry['points']
    cells = {(p['row'], p['col']): str(i) for i, p in enumerate(points)}
    lattice = LatticeType[entry['lattice'].upper()]
    period = 21 if entry['lattice'] == 'honeycomb' else 32
    adj = {str(i): set() for i in range(len(points))}
    for i, p in enumerate(points):
        for bp in range(period):
            neighbor = crossover_neighbor(lattice, p['row'], p['col'], bp, is_scaffold=True)
            if neighbor in cells:
                adj[str(i)].add(cells[neighbor])
    assert all(a in adj[b] for a in adj for b in adj[a]), 'Expected undirected crossover graph'
    assert all((points[int(a)]['row'] + points[int(a)]['col'] - points[int(b)]['row'] - points[int(b)]['col']) % 2 for a in adj for b in adj[a])
    return adj


def search_graph(adj, budget_limit=20000):
    ids = list(adj)
    order = lambda n: (len(adj[n]), n)
    budget = [budget_limit]
    path = _ham_path_search(ids, adj, order, sorted(ids, key=order), budget)
    if path:
        assert len(path) == len(adj) and set(path) == set(adj)
        assert all(b in adj[a] for a, b in zip(path, path[1:]))
    return {
        'status': 'path_found' if path else ('unresolved' if budget[0] <= 0 else 'no_path'),
        'visits': budget_limit - budget[0],
        'path': [int(n) for n in path] if path else None,
    }


def screen_entry(entry, budget_limit=20000):
    points = entry['points']
    even = sum((p['row'] + p['col']) % 2 == 0 for p in points)
    record = {'key': f"{entry['lattice']}:{entry['sources'][0]['center']}:{len(points)}",
              'even': even, 'odd': len(points) - even,
              'canonical_sha256': hashlib.sha256(entry['canonical'].encode()).hexdigest()}
    if abs(2 * even - len(points)) > 1:
        record.update(status='parity_obstruction', visits=0, path=None)
    else:
        record.update(search_graph(adjacency(entry), budget_limit))
    return record


def load_atlas(scaffold):
    command = "import {enumerateRods} from './frontend/src/design/yggdnasil.js'; console.log(JSON.stringify(enumerateRods({scaffold:" + str(scaffold) + "})));"
    return json.loads(subprocess.check_output(['node', '--input-type=module', '-e', command], cwd=ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--budget', type=int, default=20000)
    args = parser.parse_args()
    if args.budget < 1:
        parser.error('budget must be positive')
    atlas = load_atlas(8064)
    records = []
    for i, entry in enumerate(atlas['entries']):
        records.append(screen_entry(entry, args.budget))
        if (i + 1) % 25 == 0:
            print(f"Screened {i + 1}/{len(atlas['entries'])} footprints", flush=True)
    source_paths = ['frontend/src/design/yggdnasil.js', 'backend/core/seamed_router.py',
                    'backend/core/crossover_positions.py', 'backend/core/constants.py']
    report = {'schema': 1, 'scope': 'Straight uniform bundles; one Hamiltonian helix traversal on the full-period native scaffold crossover graph. No arbitrary custom routes, indels, return tracks, or multiple scaffolds.',
              'budget_per_footprint': args.budget, 'max_scaffold': 8064, 'minimum_length': 21,
              'interpretation': {'parity_obstruction': 'Impossible traversal: parity populations differ by more than one.',
                  'no_path': 'Impossible traversal: all starts exhausted without exhausting the search budget.',
                  'path_found': 'Verified helix traversal witness only; bp placement, end-turn overhead and exact scaffold completion untested.',
                  'unresolved': 'Search budget exhausted; do not prune.'},
              'source_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in source_paths},
              'records': records}
    lookup = {r['key']: r for r in records}
    summaries = []
    for scaffold in (7249, 7560, 8064):
        current = load_atlas(scaffold)
        totals = {}
        for entry in current['entries']:
            record = lookup[f"{entry['lattice']}:{entry['sources'][0]['center']}:{entry['helices']}"]
            assert record['canonical_sha256'] == hashlib.sha256(entry['canonical'].encode()).hexdigest()
            status = record['status']
            for group in ('all', entry['lattice']):
                target = totals.setdefault(group, {})
                count = target.setdefault(status, {'footprints': 0, 'candidates': 0})
                count['footprints'] += 1
                count['candidates'] += entry['count']
        summaries.append({'scaffold': scaffold, 'total': current['count'], 'totals': totals})
    report['summaries'] = summaries
    destination = ROOT / 'frontend/src/design/yggdnasil_routing.json'
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(summaries, indent=2))
    print(f'Wrote {destination}')


if __name__ == '__main__':
    main()
