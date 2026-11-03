"""Download publisher-linked PDF evidence for manual screening. Research only."""
import concurrent.futures
import html
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
import sys

root = Path(sys.argv[1]).resolve()
sources = root / 'sources'
rows = json.loads((sources / 'screening.json').read_text())

def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'OrigamiLiteratureResearch/0.1'})
    with urllib.request.urlopen(req, timeout=25) as response:
        return response.read(), response.url

def fetch(row):
    pmc, doi = row['pmcid'], row.get('doi') or ''
    result = {'pmcid': pmc, 'downloads': [], 'errors': []}
    try:
        page_url = 'https://pmc.ncbi.nlm.nih.gov/articles/' + pmc + '/'
        data, _ = get(page_url)
        (sources / (pmc + '.html')).write_bytes(data)
        links = [html.unescape(s) for s in re.findall(r'(?:href|src)="([^"]+)"', data.decode())]
        figures = {g for f in row.get('cad_figures', []) for g in f['graphics']}
        chosen = [u for u in links if 'cdn.ncbi.nlm.nih.gov/pmc/' in u and any(g and g.rsplit('/',1)[-1] in u for g in figures)]
        if doi.startswith('10.1038/'):
            page, _ = get('https://www.nature.com/articles/' + doi.split('/',1)[1])
            (sources / (pmc + '-publisher.html')).write_bytes(page)
            chosen += [html.unescape(u) for u in re.findall(r'href="([^"]+)"',page.decode()) if '/esm/' in u and '.pdf' in u]
        else:
            chosen += [urllib.parse.urljoin(page_url,u) for u in links if '/bin/' in u and u.endswith('.pdf')]
        for url in sorted(set(chosen))[:6]:
            filename = urllib.parse.unquote(url.split('/')[-1].split('?')[0])
            dest = sources / (pmc + '-' + filename)
            try:
                if dest.exists(): content = dest.read_bytes(); final = url
                else: content, final = get(url)
                if not (content.startswith(b'%PDF') or content.startswith(b'\xff\xd8') or content.startswith(b'\x89PNG')):
                    raise ValueError('Not a PDF/JPEG/PNG (possible access challenge)')
                dest.write_bytes(content)
                result['downloads'].append({'source_url': url, 'resolved_url': final, 'path': str(dest.relative_to(root)), 'bytes': len(content)})
            except Exception as e: result['errors'].append({'url': url, 'error': str(e)})
    except Exception as e:
        result['errors'].append({'error': str(e)})
    return result

selected = [r for r in rows if 'access_error' not in r and (r.get('cad_figures') or (r.get('doi') or '').startswith('10.1038/')) and not any(s in r['title'].lower() for s in ('wireframe','free-form','bricks','10,000','lattice-free','rna origami'))]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
    results=[]
    for r in ex.map(fetch, selected):
        results.append(r)
        print(r['pmcid'],len(r['downloads']),len(r['errors']),flush=True)
        (sources/'evidence-downloads.json').write_text(json.dumps(results,indent=2))
