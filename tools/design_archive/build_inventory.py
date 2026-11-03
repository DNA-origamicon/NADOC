"""Build the small, offline application inventory from archived evidence and explicit reviews."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re


def build(archive, output):
    snapshot = json.loads((archive / 'snapshot.json').read_text())
    inspected = {r['id']: r for r in snapshot['inspection']}
    publications = {r['doi']: r for r in snapshot['publications']}
    supplements = {p['doi']: p for p in json.loads((archive / 'supplements.json').read_text())}
    links = json.loads(Path(__file__).with_name('nanobase_publication_links.json').read_text())
    reviews = json.loads(Path(__file__).with_name('nanobase_figure_reviews.json').read_text())
    rows = []
    for s in snapshot['records']:
        record = inspected[s['id']]
        curated = links.get(str(s['id']))
        doi = curated['doi'] if curated else record['doi']
        pub = publications.get(doi, {}).get('crossref', {})
        link = 'https://doi.org/' + doi if doi else s.get('paperLink', '').strip()
        arxiv = re.search(r'arxiv[:.\w/]*(\d{4}\.\d{4,5})', s.get('citation', ''), re.I)
        if not doi and arxiv:
            link = 'https://arxiv.org/abs/' + arxiv[1]
        valid_link = bool(re.match(r'https?://[^/\s]+', link))
        status = ('Preprint linked' if (doi or '').startswith('10.1101/') or 'arxiv.org' in link else
                  'Journal article linked' if doi else 'Publication link unresolved' if valid_link else 'No publication supplied')
        publication = {'status': status, 'title': (pub.get('title') or [s.get('citation', '')])[0],
            'url': link if valid_link else None, 'deposited_url': s.get('paperLink'), 'doi': doi,
            'metadata_verified': bool(pub), 'metadata_source': 'https://api.crossref.org/works/' + doi if pub else None}
        if curated:
            publication.update(note=curated['note'], association_evidence=curated['evidence'])
        elif doi and not pub:
            publication['note'] = 'Depositor citation; Crossref metadata could not be verified during this scan.'
        notes = []
        description = s.get('description', '')
        if re.search(r're.creat|modif|not yet|adjusted|corrected|adapt', description, re.I):
            notes.append('Depositor describes a reconstruction, modification or adjustment; inspect the source description before pairing.')
        if re.search(r'not.*adjusted', description, re.I):
            notes.append('Depositor explicitly reports that bridge staples have not yet been adjusted for length.')
        files, software = [], set()
        descriptions = dict(zip(s.get('structureFilesArr', []), s.get('structureFileDescriptionsArr', [])))
        for f in record['files']:
            name = f['name']; ext = Path(name).suffix.lower()
            if ext in {'.webp', '.png', '.jpg', '.jpeg', '.gif'}:
                continue
            desc = descriptions.get(name, '')
            schema = f.get('schema')
            if schema and schema != 'Unclassified JSON':
                software.add(schema)
            if ext == '.mat':
                software.add('MagicDNA' if 'magicdna' in (desc + description + s['title']).lower() else 'MATLAB (.mat; software unverified)')
            elif ext == '.dna':
                software.add('Tiamat' if 'tiamat' in desc.lower() else 'Tiamat (.dna; inferred)')
            elif ext == '.vhelix':
                software.add('vHelix')
            elif ext in {'.oxview'}:
                software.add('oxView')
            elif ext in {'.json', '.sc'} and not schema:
                software.add('JSON (inspection failed)')
            is_sim = ext in {'.top', '.dat', '.oxdna', '.oxview', '.pdb', '.conf', '.par'} or f.get('filetype') in {'simResults', 'simProtocol'}
            if ext == '.top':
                software.add('oxDNA files')
            item = {'name': name, 'url': f.get('url'), 'category': 'simulation' if is_sim else 'design / auxiliary', 'schema': schema, 'description': desc, 'manifest_category': f.get('filetype')}
            if f.get('normalized_json_sha256'):
                item['normalized_json_sha256'] = f['normalized_json_sha256']
            if f.get('inspection_error'):
                notes.append(f'Native file inspection failed: {name}. Availability/schema unresolved.')
            files.append(item)
        if not software:
            software.add('Software not established')
        sup = supplements.get(doi, {})
        pdfs = sup.get('pdfs', [])
        supplement = {'status': 'Unresolved — retrieval unavailable' if sup.get('errors') else 'Unresolved — no PDF located', 'evidence': [], 'note': 'No absence claim: a missed or inaccessible supplement can still contain a design.'}
        if pdfs:
            supplement = {'status': 'Accessible PDF — figure review pending', 'evidence': [{'label': f'Supplement PDF ({p["pages"]} pages)', 'url': p['url'], 'sha256': p['sha256'], 'candidate_pages': [h['page'] for h in p['hits']]} for p in pdfs], 'note': 'PDF access confirmed. Text hits alone do not establish a caDNAno figure or a matching construct.'}
        review = reviews.get(str(s['id']))
        review_pdf = next((p for p in pdfs if review and p['sha256'] == review.get('pdf_sha256')), None)
        if review and review.get('doi') == doi and review_pdf:
            pdf = review_pdf
            supplement = {'status': {'cadnano': 'Verified caDNAno routing figure', 'other': 'Other design figures verified', 'partial': 'Routing example — construct unresolved'}[review['kind']],
                'evidence': [{'label': f'{review["figure"]} · PDF page {review["page"]}', 'url': pdf['url'] + ('' if pdf.get('archive_member') else f'#page={review["page"]}'), 'sha256': pdf['sha256']}],
                'note': review.get('note', 'Figure visually inspected. Sequence, topology and construct equivalence have not been compared.'),
                'review_method': review['review_method'], 'reviewed_at': review['reviewed_at']}
        if not valid_link and not curated:
            supplement = {'status': 'Unresolved — no publication identified', 'evidence': [], 'note': 'No associated publication was established in this audit.'}
        rows.append({'id': s['id'], 'title': s['title'], 'source_url': f'https://nanobase.org/structures/{s["id"]}', 'software': sorted(software), 'files': files, 'publication': publication, 'supplement': supplement, 'comparison': 'Not compared — not an approved training pair', 'notes': notes, 'depositor_description': description, 'license_as_deposited': s.get('licensing'), 'updated_at': s.get('lastUpdated')})
    result = {'schema_version': 1, 'retrieved_at': snapshot['retrieved_at'], 'coverage': f'{len(rows)} public records; complete public listing at retrieval',
        'source': snapshot['source'] + 'getAllPublicStructures_paginated', 'method': 'Public metadata and manifests; JSON schema checks; Crossref metadata; publisher-linked PDF retrieval; explicit visual figure reviews. No topology equivalence established.',
        'limitations': ['Snapshot, not a live index.', 'Europe PMC search returned service-unavailable responses; direct known-PMC retrieval was attempted separately.', 'No-publication-supplied is a metadata status, not proof that the design is unpublished.', 'Supplement retrieval failures and unreviewed PDFs remain unresolved.', 'Files listed are not simulation validation evidence.'], 'records': rows}
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(len(rows), 'rows;', dict(Counter(r['supplement']['status'] for r in rows)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('frontend/src/data/nanobase_inventory.json'))
    args = parser.parse_args(); build(args.archive, args.output)
