"""Collect public Nanobase evidence. Run explicitly; no designs are imported.

Usage: python tools/design_archive/inventory_nanobase.py --archive PATH
Raw responses and downloaded native JSON stay under the supplied archive.
Only public listing IDs are followed; no private-ID enumeration.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote

API = 'https://api.nanobase.org/api/v1/structure/'
LEGACY_DOIS = {
    '359/6373/296': '10.1126/science.aao4284',
    '354/6310/305': '10.1126/science.aah5974',
    '339/6126/1412': '10.1126/science.1232252',
    '371/6531/eabd6179': '10.1126/science.abd6179',
    '115/32/E7512': '10.1073/pnas.1800585115',
    '338/6109/932': '10.1126/science.1225624',
}


def doi_for(s):
    # Citation fallback is evidence supplied by the depositor, not an inferred title match.
    for value in [s.get('paperLink', ''), s.get('citation', '')]:
        nature = re.search(r'nature\.com/articles/([^/?#\s]+)', value)
        if nature:
            return '10.1038/' + nature[1].lower()
        match = re.search(r'10\.\d{4,9}/[^\s<>"\)]+', value, re.I)
        if match:
            return re.sub(r'v\d+(?:\.abstract)?$', '', match[0].rstrip('.,').lower())
        for fragment, doi in LEGACY_DOIS.items():
            if fragment in value:
                return doi
    return None


def collect(archive):
    import requests

    archive.mkdir(parents=True, exist_ok=True)
    def fetch(url, target):
        path = archive / target
        if path.exists():
            return json.loads(path.read_text())
        response = requests.get(url, timeout=45)
        response.raise_for_status()
        value = response.json()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2))
        return value

    expected_count = fetch(API + 'count', 'count.json')['count']
    rows, skip = [], 0
    while True:
        chunk = fetch(f'{API}getAllPublicStructures_paginated?skip={skip}&take=100', f'listing-{skip}.json')['structures']
        if not chunk:
            break
        rows.extend(chunk)
        skip += len(chunk)
    records = [r['structure'] for r in rows if r['structure'].get('private') is False]

    if len(records) != expected_count or len({r['id'] for r in records}) != expected_count:
        raise ValueError('Listing changed or is incomplete; use a new archive directory to retry.')

    def inspect(s):
        result = {'id': s['id'], 'doi': doi_for(s), 'files': [], 'errors': []}
        try:
            files = fetch(f'{API}structure-files?id={s["id"]}', f'files/{s["id"]}.json')
            for f in files:
                item = dict(f)
                item['url'] = API + 'files/' + quote(f['url'], safe='/') if f.get('url') else None
                if f['name'].lower().endswith(('.json', '.sc')) and item['url']:
                    try:
                        data = fetch(item['url'], f'native/{s["id"]}/{Path(f["name"]).name}')
                        item['schema'] = ('caDNAno v2' if isinstance(data, dict) and isinstance(data.get('vstrands'), list)
                            else 'scadnano' if isinstance(data, dict) and 'helices' in data and 'strands' in data
                            else 'oxView' if isinstance(data, dict) and 'systems' in data else 'Unclassified JSON')
                        item['normalized_json_sha256'] = hashlib.sha256((archive / f'native/{s["id"]}/{Path(f["name"]).name}').read_bytes()).hexdigest()
                    except Exception as e:
                        item['inspection_error'] = str(e)
                result['files'].append(item)
        except Exception as e:
            result['errors'].append(str(e))
        return result
    with ThreadPoolExecutor(max_workers=3) as pool:
        inspected = list(pool.map(inspect, records))
    links = json.loads(Path(__file__).with_name('nanobase_publication_links.json').read_text())
    dois = sorted({r['doi'] for r in inspected if r['doi']} | {r['doi'] for r in links.values()})

    def publication(doi):
        out = {'doi': doi}
        key = doi.replace('/', '_')
        try:
            out['crossref'] = fetch('https://api.crossref.org/works/' + quote(doi, safe=''), f'publications/{key}-crossref.json')['message']
        except Exception as e:
            out['crossref_error'] = str(e)
        try:
            data = fetch('https://www.ebi.ac.uk/europepmc/webservices/rest/search?format=json&resultType=core&query=' + quote(f'DOI:"{doi}"'), f'publications/{key}-epmc.json')
            out['europepmc'] = data['resultList']['result']
        except Exception as e:
            out['europepmc_error'] = str(e)
        return out
    with ThreadPoolExecutor(max_workers=3) as pool:
        pubs = list(pool.map(publication, dois))
    snapshot = {'retrieved_at': datetime.fromtimestamp((archive / 'listing-0.json').stat().st_mtime, timezone.utc).isoformat(),
        'audited_at': datetime.now(timezone.utc).isoformat(), 'public_count': expected_count, 'source': API,
        'records': records, 'inspection': inspected, 'publications': pubs}
    (archive / 'snapshot.json').write_text(json.dumps(snapshot, indent=2))
    print(f'{len(records)} public records; {len(dois)} unique DOIs; archive: {archive}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    collect(parser.parse_args().archive)
