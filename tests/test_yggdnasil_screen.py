"""Cross-check native traversal screening against brute force on small graphs."""
import itertools
import json
from pathlib import Path

from scripts.screen_yggdnasil import adjacency, load_atlas, search_graph


def brute_path(adj):
    return next((p for p in itertools.permutations(adj)
                 if all(b in adj[a] for a, b in zip(p, p[1:]))), None)


def test_search_distinguishes_proof_from_budget_exhaustion():
    star = {'0': {'1', '2', '3'}, '1': {'0'}, '2': {'0'}, '3': {'0'}}
    assert search_graph(star)['status'] == 'no_path'
    assert search_graph(star, 1)['status'] == 'unresolved'
    line = {'0': {'1'}, '1': {'0', '2'}, '2': {'1'}}
    assert search_graph(line)['status'] == 'path_found'


def test_published_witnesses_and_small_impossibility_claims():
    atlas = load_atlas(8064)
    report = json.loads(Path('frontend/src/design/yggdnasil_routing.json').read_text())
    lookup = {r['key']: r for r in report['records']}
    assert len(lookup) == len(atlas['entries'])
    for e in atlas['entries']:
        adj = adjacency(e)
        r = lookup[f"{e['lattice']}:{e['sources'][0]['center']}:{e['helices']}"]
        if r['status'] == 'path_found':
            path = list(map(str, r['path']))
            assert set(path) == set(adj) and len(path) == len(adj)
            assert all(b in adj[a] for a, b in zip(path, path[1:]))
        elif r['status'] == 'parity_obstruction':
            assert abs(r['even'] - r['odd']) > 1
        elif r['status'] == 'no_path':
            assert r['visits'] < report['budget_per_footprint']
        elif r['status'] == 'unresolved':
            assert r['visits'] == report['budget_per_footprint']
        if len(adj) <= 8:
            exists = brute_path(adj) is not None
            assert exists == (r['status'] == 'path_found')
