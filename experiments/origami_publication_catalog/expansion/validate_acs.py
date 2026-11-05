"""Audit saved acquisition, stable IDs, source hashes and deterministic integration."""
import hashlib
import argparse
import json
from pathlib import Path
import subprocess
import sys

H = Path(__file__).resolve().parents[1]

def read(name):
    return json.loads((H / name).read_text())

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--require-complete-acquisition', action='store_true')
    args = parser.parse_args()
    acquisition = read('acs_acquisition.json')['records']
    lookup_failures = sum(r['status'] == 'repository_lookup_failed' for r in acquisition)
    download_failures = sum(f['status'] == 'download_failed' for r in acquisition for f in r['files'])
    if args.require_complete_acquisition:
        assert lookup_failures == 0, 'Unresolved repository lookup failures'
        assert download_failures == 0, 'Unresolved document download failures'
    d003_before = next(r for r in read('structure_map.json')['rows'] if r['id'] == 'D003').get('complete_staple_set_validated')
    integration = H / 'expansion/integrate_acs.py'
    subprocess.run([sys.executable, str(integration)], check=True, capture_output=True)
    generated = ['structure_map.json', 'structure_map.csv', 'structure_map.html', 'publication_registry.json', 'publication_registry.csv', 'publication_registry.html', 'search_coverage.json', 'priority_review_gaps.csv', 'acs_expansion_summary.json']
    before = {f: hashlib.sha256((H / f).read_bytes()).hexdigest() for f in generated}
    subprocess.run([sys.executable, str(integration)], check=True, capture_output=True)
    assert before == {f: hashlib.sha256((H / f).read_bytes()).hexdigest() for f in generated}, 'integration not idempotent'
    catalog = read('structure_map.json')
    rows = {r['id']: r for r in catalog['rows']}
    assert len(rows) == len(catalog['rows'])
    legacy = {f'D{i:03}' for i in range(1, 33)} | {f'S{i:03}' for i in range(1, 47)}
    assert legacy <= rows.keys(), 'legacy IDs lost'
    for row in read('catalog.json')['rows']:
        for key in ['design', 'quality_score', 'image_file', 'first_publication_date']:
            assert rows[row['id']][key] == row[key], (row['id'], key)
    assert rows['D003'].get('complete_staple_set_validated') == d003_before
    decisions = read('expansion/acs_reviews.json')
    for r in decisions:
        row = rows[r['id']]
        assert row['first_publication_date'] < '2020-01-01'
        assert row['complete_staple_set_validated'] is False
        assert row['quality_score'] is None
        assert row['staple_list']['sources']
    checked = 0
    for r in read('acs_acquisition.json')['records']:
        for f in r['files']:
            if f['status'] != 'downloaded':
                continue
            b = (H / 'assets' / f['local_file']).read_bytes()
            assert len(b) == f['publisher_bytes'] == f['bytes']
            assert hashlib.sha256(b).hexdigest() == f['sha256']
            assert f['publisher_md5_verified']
            meta = read('assets/sources/acs-expansion-20261104/article-' + str(f['article_id']) + '.json')
            assert meta['resource_doi'].lower() == r['doi'].lower()
            assert meta['url_public_html'].startswith('https://acs.figshare.com/')
            source = next(x for x in meta['files'] if x['name'] == f['name'])
            assert hashlib.md5(b).hexdigest() == source['computed_md5']
            checked += 1
    html = (H / 'structure_map.html').read_text()
    assert html.count('<tr class=') == len(rows)
    for r in decisions:
        assert r['id'] + '<br>' in html
    report = {'status': 'passed', 'date': '2026-11-04', 'verified_downloads': checked, 'lookup_failures': lookup_failures, 'download_failures': download_failures, 'complete_acquisition_required': args.require_complete_acquisition, 'legacy_ids_preserved': len(legacy), 'review_decisions_checked': len(decisions), 'saved_structure_rows': len(rows), 'original_image_scores_and_paths_preserved': True, 'D003_qualification_preserved': True, 'integration_idempotent': True, 'new_native_structures_authored': 0, 'qualification': 'Catalog/data checks; not molecular topology, synthesis completeness, or an application UI test.'}
    (H / 'acs_validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
