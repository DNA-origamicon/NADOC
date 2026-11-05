"""Merge audited acquisition and explicit reviews into retained catalog artifacts.

Preserves stable IDs, original image scores, and prior recovery qualification.
Can run without the historical source mount. Re-running is idempotent.
"""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from render_map import render

H = Path(__file__).resolve().parents[1]

def read(name):
    return json.loads((H / name).read_text())

def write(name, value):
    (H / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')

def csvout(name, rows):
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with (H / name).open('w', newline='') as out:
        writer = csv.DictWriter(out, keys, lineterminator='\n')
        writer.writeheader()
        writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in r.items()} for r in rows)

def norm(doi):
    return doi.lower().removeprefix('https://doi.org/')

def merge_files(old, new):
    return list({f.get('local_file', f.get('url', str(f))): f for f in old + new}.values())

def main():
    audit = read('acs_acquisition.json')
    decisions = read('expansion/acs_reviews.json')
    catalog = read('structure_map.json')
    registry = read('publication_registry.json')
    publications = {norm(r['doi']): r for r in registry if r['doi']}
    rows = {r['id']: r for r in catalog['rows']}
    sources = {}
    for acquisition in audit['records']:
        d = acquisition['doi']
        files = [f for f in acquisition['files'] if f['status'] == 'downloaded']
        for f in files:
            path = H / 'assets' / f['local_file']
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != f['sha256']:
                raise ValueError('Missing or corrupt source: ' + f['local_file'])
        sources[d] = files
        pub = publications[d]
        pub['downloaded_supplements'] = merge_files(pub.get('downloaded_supplements', []), files)
        pub['supplement_acquisition_20261104'] = acquisition['status']
        pub['locally_verified_supplement_count_20261104'] = len(files)
        if files and not pub['structure_ids']:
            pub['priority'] = 'downloaded_supplement_to_review'
    for decision in decisions:
        d = decision['doi']
        pub = publications[d]
        fs = sources.get(d, [])
        if not fs:
            raise ValueError('Review has no retrieved source: ' + d)
        identifier = decision['id']
        row = rows.get(identifier, {})
        if row and norm(row['doi']) != d:
            raise ValueError('Stable ID collision')
        row.update(decision)
        row.update(publication=pub['publication'], first_publication_date=pub['first_publication_date'], publication_url=pub['publication_url'], review_date='2026-11-04', complete_staple_set_validated=False)
        row.setdefault('image_file', None)
        row.setdefault('quality_score', None)
        row.setdefault('image_kind', 'not_scored')
        row.setdefault('rating_status', 'not_scored_no_image_reconstruction_assessment')
        row.setdefault('design_files', [])
        row['publication_supplements'] = merge_files(row.get('publication_supplements', []), fs)
        row['staple_list'] = {'status': decision.get('staple_status', 'published_list_located_variant_completeness_unverified'), 'location': decision['sequence_location'], 'sources': fs, 'notes': decision['notes']}
        row['structural_characterization'] = {'modalities': decision.get('characterization', []), 'source_url': pub['publication_url'], 'scope': 'Published characterization; raw data and exact experimental variant not independently verified.'}
        row.setdefault('imaging_datasets', {'public_raw_dataset_status': 'not_verified', 'resources': []})
        rows[identifier] = row
        if identifier not in pub['structure_ids']:
            pub['structure_ids'].append(identifier)
    for row in rows.values():
        fs = sources.get(norm(row['doi']), [])
        if fs:
            row['publication_supplements'] = merge_files(row.get('publication_supplements', []), fs)
    for pub in registry:
        mapped = [rows[i] for i in pub['structure_ids']]
        if mapped:
            pub['review_status'] = 'contains_reviewed_structure_groups' if any(r['map_status'] == 'reviewed_in_scope' for r in mapped) else 'named_structure_candidate: scope/list verification pending'
            pub['priority'] = 'named_structure'
    catalog['rows'] = list(rows.values())
    counts = catalog['counts']
    counts.update(reviewed_design_groups=sum(r['map_status'] == 'reviewed_in_scope' for r in rows.values()), candidate_design_groups=sum(r['map_status'] == 'candidate' for r in rows.values()), reviewed_publications=len({norm(r['doi']) for r in rows.values() if r['map_status'] == 'reviewed_in_scope'}), mapped_publications=len({norm(r['doi']) for r in rows.values()}), registry_review_states=dict(Counter(r['review_status'] for r in registry)))
    counts['new_sequence_only_reviewed_groups'] = sum(r['id'].startswith('S') and r['map_status'] == 'reviewed_in_scope' and r.get('inclusion_basis') == 'published_staple_list' for r in rows.values())
    counts['downloaded_supplement_files'] = len({f['local_file'] for p in registry for f in p['downloaded_supplements'] if f.get('local_file')})
    summary = {'date': '2026-11-04', 'attempted_publications': len(audit['records']), 'repository_matched_publications': sum(r['status'] == 'repository_matched' for r in audit['records']), 'publications_with_downloads': sum(bool(fs) for fs in sources.values()), 'downloaded_files': sum(len(fs) for fs in sources.values()), 'downloaded_bytes': sum(f['bytes'] for fs in sources.values() for f in fs), 'file_states': dict(Counter(f['status'] for r in audit['records'] for f in r['files'])), 'publication_states': dict(Counter(r['status'] for r in audit['records'])), 'review_decisions': len(decisions), 'counts_after': counts, 'credentials_stored': False, 'limitations': ['ACS acquisition is not a complete literature search.', 'Publisher deposits are accessible; VPN necessity was not established by an off-VPN comparison.', 'Downloaded files do not establish design eligibility or sequence completeness.', 'Historical download counts include files not present on this checkout.', 'No new native molecular structures were authored.']}
    retried = [r for r in audit['records'] if any(h.get('status') == 'repository_lookup_failed' for h in r.get('attempt_history', []))]
    summary['retried_lookup_records'] = len(retried)
    summary['retry_dispositions'] = dict(Counter(r['status'] for r in retried))
    summary['request_policy'] = audit.get('request_policy', {})
    catalog['reviewed'] = '2026-11-04'
    catalog['acquisition_report'] = 'acs_expansion_summary.json'
    write('structure_map.json', catalog)
    write('publication_registry.json', registry)
    csvout('structure_map.csv', catalog['rows'])
    csvout('publication_registry.csv', registry)
    csvout('priority_review_gaps.csv', [r for r in registry if r['priority'] != 'discovery_only' and r['review_status'] != 'contains_reviewed_structure_groups'])
    coverage = read('search_coverage.json')
    coverage['counts'] = counts
    coverage['acs_expansion_20261104'] = {k: v for k, v in summary.items() if k != 'counts_after'}
    write('search_coverage.json', coverage)
    write('acs_expansion_summary.json', summary)
    render(catalog['rows'], registry, counts)
    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    main()
