"""Research-only Europe PMC discovery; preserves evidence, never auto-accepts papers."""
import argparse
import concurrent.futures
import json
from pathlib import Path
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

API = 'https://www.ebi.ac.uk/europepmc/webservices/rest/'
QUERY = '(cadnano OR scadnano OR "DNA origami") AND FIRST_PDATE:[1900-01-01 TO 2019-12-31]'
XLINK = '{http://www.w3.org/1999/xlink}href'

def get(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()

def discover(out):
    cursor = '*'
    records = {}
    pages = []
    while True:
        url = API + 'search?' + urllib.parse.urlencode(dict(query=QUERY, format='json', pageSize=1000, resultType='core', cursorMark=cursor))
        data = json.loads(get(url))
        pages.append({'url': url, 'hit_count': data['hitCount'], 'returned': len(data['resultList']['result'])})
        for record in data['resultList']['result']:
            records[record['source'] + ':' + record['id']] = record
        nxt = data.get('nextCursorMark')
        if not nxt or nxt == cursor or not data['resultList']['result']:
            break
        cursor = nxt
    (out / 'discovery.json').write_text(json.dumps({'query': QUERY, 'retrieved': '2026-11-02', 'pages': pages, 'records': list(records.values())}, indent=2))
    return list(records.values())

def screen(record, out):
    pmc = record.get('pmcid')
    result = {k: record.get(k) for k in ('id', 'pmcid', 'doi', 'title', 'firstPublicationDate')}
    result['status'] = 'awaiting_manual_review'
    path = out / (pmc + '.xml')
    try:
        if not path.exists():
            path.write_bytes(get(API + pmc + '/fullTextXML'))
        root = ET.fromstring(path.read_bytes())
        def txt(e): return ' '.join(''.join(e.itertext()).split())
        result['cad_figures'] = [{'id': e.get('id'), 'caption': txt(e), 'graphics': [g.get(XLINK) for g in e.iter('graphic')]} for e in root.iter('fig') if 'cadnano' in txt(e).lower()]
        result['supplements'] = [{'text': txt(e), 'links': [n.get(XLINK) for n in e.iter() if n.get(XLINK)]} for e in root.iter('supplementary-material')]
        result['repository_links'] = sorted({e.get(XLINK) for e in root.iter() if e.get(XLINK) and any(s in e.get(XLINK).lower() for s in ('github', 'zenodo', 'figshare', 'dryad', 'cadnano.org', 'nanobase', 'data.'))})
        result['cad_contexts'] = [txt(e) for e in root.iter('p') if 'cadnano' in txt(e).lower() and len(txt(e)) < 5000]
    except Exception as e:
        result['access_error'] = str(e)
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True, help='Existing archive-mounted asset directory')
    parser.add_argument('--discover', action='store_true')
    args = parser.parse_args()
    out = args.assets.resolve() / 'sources'
    out.mkdir(parents=True, exist_ok=True)
    if args.discover:
        discover(out)
    seed_path = out / 'cadnano-search.json'
    if not seed_path.exists():
        query = '(cadnano OR scadnano) AND FIRST_PDATE:[1900-01-01 TO 2019-12-31]'
        url = API + 'search?' + urllib.parse.urlencode(dict(query=query, format='json', pageSize=1000, resultType='core'))
        seed_path.write_bytes(get(url))
    seeds = json.loads(seed_path.read_text())['resultList']['result']
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda r: screen(r, out), [r for r in seeds if r.get('pmcid')]))
    (out / 'screening.json').write_text(json.dumps(results, indent=2))
    print(json.dumps({'screened': len(results), 'accessible': sum('access_error' not in r for r in results), 'with_cad_figures': sum(bool(r.get('cad_figures')) for r in results)}))

if __name__ == '__main__':
    main()
