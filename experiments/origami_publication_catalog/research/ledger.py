"""Durable research sidecars; legacy ingestion never asserts a fresh review.

Run `python3 .../research/ledger.py init|validate|counts|select` from any cwd.
Edits use upsert(): atomic replacement, immutable identity, prior revisions retained.
Only one campaign writer may operate at a time (see RESEARCH_SETUP.md).
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'research'
DATE = '2026-11-05'
KEYS = {'publication_reviews': 'registry_key', 'design_evidence': 'design_id',
        'discovery_runs': 'run_id', 'discovery_edges': 'edge_id', 'batches': 'batch_id'}


def read(name, directory=HERE):
    path = directory / (name + '.jsonl')
    return [json.loads(line) for line in path.read_text().split('\n') if line.strip()] if path.exists() else []


def atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save(name, rows, directory=HERE):
    key = KEYS[name]
    if len({r[key] for r in rows}) != len(rows):
        raise ValueError('Duplicate stable key: ' + name)
    atomic(directory / (name + '.jsonl'), ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in rows))


def upsert(name, record, reason, directory=HERE):
    if not reason:
        raise ValueError('Revision reason required')
    rows = read(name, directory)
    key = KEYS[name]
    record = deepcopy(record)
    for i, old in enumerate(rows):
        if old[key] == record[key]:
            if {k:v for k,v in old.items() if k != 'revision_history'} == {k:v for k,v in record.items() if k != 'revision_history'}:
                return
            history = deepcopy(old.get('revision_history', []))
            prior = {k: v for k, v in old.items() if k != 'revision_history'}
            history.append({'superseded': prior, 'reason': reason, 'date': DATE})
            record['revision_history'] = history
            rows[i] = record
            break
    else:
        record.setdefault('revision_history', [])
        rows.append(record)
    save(name, rows, directory)


def init():
    registry = json.loads((ROOT / 'publication_registry.json').read_text())
    existing = {r['registry_key'] for r in read('publication_reviews')}
    rows = read('publication_reviews')
    for r in registry:
        if r['key'] in existing:
            continue
        rows.append({'registry_key': r['key'], 'registry_id': r['id'],
                     'doi': (r.get('doi') or '').lower(), 'canonical_work_id': 'work:' + r['key'],
                     'canonical_work_status': 'provisional_unreconciled', 'version_links': [],
                     'publication_type': r.get('publication_types', []),
                     'date_evidence': {'date': r.get('first_publication_date'), 'source': 'publication_registry.json', 'primary_verified': False},
                     'review_stage': 'unreviewed', 'relevance': 'uncertain', 'design_contributions': [],
                     'catalog_eligibility': 'unresolved', 'access': 'not_attempted',
                     'evidence': [], 'rationale': 'Legacy evidence retained; no new substantive review during ingestion.',
                     'reviewer': None, 'run_id': 'bootstrap-20261105', 'date': DATE,
                     'unresolved_questions': ['Verify primary publication date, relevance, design scope and sources.'],
                     'legacy_record': r, 'revision_history': []})
    save('publication_reviews', rows)
    designs = read('design_evidence'); known = {d['design_id'] for d in designs}
    by_doi = {(r.get('doi') or '').lower(): r['key'] for r in registry if r.get('doi')}
    for d in json.loads((ROOT / 'structure_map.json').read_text())['rows']:
        if d['id'] in known:
            continue
        designs.append({'design_id': d['id'], 'publication_keys': [by_doi[d['doi'].lower()]],
                        'variant_links': [], 'relationships': [], 'lattice_decision': 'legacy_not_revalidated',
                        'named_objects': [d['design']], 'evidence': [], 'source_files': [],
                        'core_variant_composition': 'not_revalidated', 'source_completeness': 'not_verified',
                        'outstanding_checks': ['Reinspect legacy evidence and exact variant mapping.'],
                        'legacy_record': d, 'revision_history': []})
    save('design_evidence', designs)
    for name in ['discovery_runs', 'discovery_edges', 'batches']:
        if not (HERE / (name + '.jsonl')).exists():
            save(name, [])


def counts():
    reviews = read('publication_reviews')
    verified_version_statuses = {'version_relation_verified_crossref', 'edition_relation_verified_publisher_header', 'version_relation_verified_arxiv'}
    return {'publication_versions': len(reviews),
            'canonical_work_keys': len({r['canonical_work_id'] for r in reviews}),
            'provisional_work_keys_not_reconciled': len({r['canonical_work_id'] for r in reviews if r.get('canonical_work_status') not in verified_version_statuses}),
            'versions_with_explicit_version_relation': sum(r.get('canonical_work_status') in verified_version_statuses for r in reviews),
            'review_stages': dict(Counter(r['review_stage'] for r in reviews)),
            'relevance': dict(Counter(r['relevance'] for r in reviews)),
            'catalog_eligibility': dict(Counter(r['catalog_eligibility'] for r in reviews)),
            'design_groups': len(read('design_evidence')),
            'design_source_reviews': sum(bool(d.get('review_run')) for d in read('design_evidence')),
            'discovery_runs': len(read('discovery_runs'))}


def select():
    """Persist 25 keys: candidates first; later batches reserve five low-signal keys."""
    batches = read('batches')
    active = [b for b in batches if b['status'] == 'in_progress'
              and b['batch_id'].startswith('B') and b['batch_id'][1:].isdigit()]
    if active:
        return active[0]
    done = {k for b in batches for k in b['input_keys']}
    rows = [r for r in read('publication_reviews') if r['registry_key'] not in done and r['review_stage'] == 'unreviewed']
    candidates = {k for d in read('design_evidence') if d['legacy_record'].get('map_status') == 'candidate' for k in d['publication_keys']}
    acs = {r['doi'] for r in json.loads((ROOT / 'acs_acquisition.json').read_text())['records'] if any(f['status'] == 'downloaded' for f in r['files'])}
    priority = sorted(rows, key=lambda r: (r['registry_key'] not in candidates, r['doi'] not in acs, r['registry_id'] or r['registry_key']))
    low = [r for r in rows if r['legacy_record'].get('priority') == 'discovery_only']
    chosen = priority[:25] if not batches else priority[:15]
    if batches:
        def rotate(pool, amount):
            groups = {}
            for r in pool:
                if r in chosen:
                    continue
                year = (r['date_evidence'].get('date') or 'unknown')[:4]
                publisher = r['doi'].split('/')[0] if r['doi'] else 'no-doi'
                groups.setdefault((year, publisher), []).append(r)
            buckets = sorted(groups)
            if buckets:
                offset = (len(batches) * 5) % len(buckets)
                buckets = buckets[offset:] + buckets[:offset]
            while buckets and amount:
                for bucket in list(buckets):
                    if not amount:
                        break
                    chosen.append(groups[bucket].pop(0))
                    amount -= 1
                    if not groups[bucket]:
                        buckets.remove(bucket)
        rotate(low, 5)
        rotate(rows, 25-len(chosen))
    batch = {'batch_id': f"B{max([int(b['batch_id'][1:]) for b in batches if b['batch_id'].startswith('B') and b['batch_id'][1:].isdigit()] or [0])+1:04}", 'date': DATE, 'status': 'in_progress',
             'input_keys': [r['registry_key'] for r in chosen], 'selection': 'Candidates then ACS; from B0003 reserve five discovery-only records and five broad records across rotating year/publisher buckets.',
             'completed_actions': [], 'before_counts': counts(), 'after_counts': None,
             'exclusion_audit': {'sample': [], 'reason': 'No final exclusions yet.'},
             'validation': [], 'unresolved_keys': [], 'next_queue': [], 'revision_history': []}
    upsert('batches', batch, 'Persist selection before review')
    return batch


def validate():
    all_rows = {name: read(name) for name in KEYS}
    for name, rows in all_rows.items():
        assert len({r[KEYS[name]] for r in rows}) == len(rows), name
    pubs = {r['registry_key'] for r in all_rows['publication_reviews']}
    registry = json.loads((ROOT / 'publication_registry.json').read_text())
    assert {r['key'] for r in registry} <= pubs
    original = {d['id'] for d in json.loads((ROOT / 'structure_map.json').read_text())['rows']}
    assert original <= {d['design_id'] for d in all_rows['design_evidence']}
    verified = 0
    hashes = {}
    for r in all_rows['publication_reviews']:
        assert r['review_stage'] in {'unreviewed', 'metadata_screened', 'fulltext_reviewed', 'design_sources_reviewed'}
        assert r['relevance'] in {'uncertain', 'design_bearing', 'background_or_review', 'not_origami'}
        assert r['catalog_eligibility'] in {'unresolved', 'eligible', 'mixed', 'excluded'}
        if r['review_stage'] != 'unreviewed':
            assert r['evidence'] and r['reviewer'] and r['rationale'], r['registry_key']
    for d in all_rows['design_evidence']:
        assert set(d['publication_keys']) <= pubs
    for b in all_rows['batches']:
        assert set(b['input_keys']) <= pubs
    for name in ['publication_reviews', 'design_evidence', 'discovery_runs']:
        for r in all_rows[name]:
            for e in r.get('evidence', []) + r.get('source_files', []) + r.get('discovery_evidence', []):
                if e.get('local_file'):
                    file = ROOT / e['local_file']
                    assert file.is_file(), str(file)
                    if file not in hashes:
                        hashes[file] = hashlib.sha256(file.read_bytes()).hexdigest()
                    assert hashes[file] == e['sha256'], str(file)
                    verified += 1
    runs = {r['run_id'] for r in all_rows['discovery_runs']}
    for edge in all_rows['discovery_edges']:
        assert edge['source_key'] in pubs | runs, edge['edge_id']
        assert edge['target_key'] in pubs or 'pending' in edge['reconciliation_state'], edge['edge_id']
        if edge.get('local_file'):
            file = ROOT / edge['local_file']
            assert file.is_file(), str(file)
            if file not in hashes:
                hashes[file] = hashlib.sha256(file.read_bytes()).hexdigest()
            assert hashes[file] == edge['sha256'], edge['edge_id']
            verified += 1
    return {'status': 'passed', 'publication_keys': len(pubs), 'stable_legacy_design_ids': len(original), 'hashed_evidence_references': verified}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'select', 'validate', 'counts'])
    args = parser.parse_args()
    print(json.dumps(globals()[args.action](), indent=2))
