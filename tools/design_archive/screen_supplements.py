"""Discover publisher-linked supplements and screen PDFs; candidates are not verified figures."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import urljoin
import requests
import pymupdf as fitz


def screen(archive):
    snapshot = json.loads((archive / 'snapshot.json').read_text())
    def run(pub):
        doi = pub['doi']
        key = doi.replace('/', '_')
        folder = archive / 'supplements' / key
        folder.mkdir(parents=True, exist_ok=True)
        cache = folder / 'review.json'
        if cache.exists() and json.loads(cache.read_text()).get("pdfs"):
            return json.loads(cache.read_text())
        out = {'doi': doi, 'sources': [], 'pdfs': [], 'errors': []}
        urls = []
        try:
            if doi.startswith('10.1021/'):
                response = requests.post('https://api.figshare.com/v2/articles/search', json={'search_for': doi, 'limit': 100}, timeout=40)
                response.raise_for_status()
                for match in response.json():
                    if match.get('resource_doi', '').lower() != doi and not match.get('doi', '').lower().startswith(doi + '.'):
                        continue
                    r = requests.get(match['url_public_api'], timeout=40); r.raise_for_status(); article = r.json()
                    out['sources'].append({'url': match['url_public_html'], 'license': article.get('license')})
                    urls.extend(f['download_url'] for f in article['files'] if f['name'].lower().endswith('.pdf'))
            else:
                url = ('https://www.nature.com/articles/' + doi.split('/', 1)[1]) if doi.startswith('10.1038/') else 'https://doi.org/' + doi
                r = requests.get(url, timeout=40); r.raise_for_status()
                out['sources'].append({'url': r.url})
                (folder / 'article.html').write_text(r.text)
                links = [urljoin(r.url, html.unescape(v)) for v in re.findall(r'href=["\']([^"\']+)["\']', r.text)]
                urls = list(dict.fromkeys(u for u in links if ('.pdf' in u.lower() and any(t in u.lower() for t in ['moesm', 'suppl', '/sup', '_sm', 'suppinfo', 'dc1', 'media', 'supporting']))))
            for i, url in enumerate(dict.fromkeys(urls)):
                try:
                    r = requests.get(url, timeout=60); r.raise_for_status()
                    if not r.content.startswith(b'%PDF'):
                        raise ValueError('Response is not a PDF')
                    path = folder / f'supplement-{i+1}.pdf'; path.write_bytes(r.content)
                    doc = fitz.open(path)
                    hits = []
                    for n, page in enumerate(doc):
                        text = page.get_text()
                        excerpts = [re.sub(r'\s+', ' ', text[max(0, m.start()-100):m.end()+220]) for m in re.finditer(r'cadnano|magicdna|tiamat|scadnano|routing|strand diagram', text, re.I)]
                        if excerpts:
                            hits.append({'page': n+1, 'excerpts': excerpts[:8]})
                    out['pdfs'].append({'url': url, 'path': str(path.resolve()), 'pages': len(doc), 'sha256': hashlib.sha256(r.content).hexdigest(), 'hits': hits})
                except Exception as e:
                    out['errors'].append(f'{url}: {e}')
        except Exception as e:
            out['errors'].append(str(e))
        cache.write_text(json.dumps(out, indent=2))
        print(doi, len(out['pdfs']), 'PDFs', sum(len(p['hits']) for p in out['pdfs']), 'hit pages', flush=True)
        return out
    with ThreadPoolExecutor(max_workers=3) as pool:
        reviews = list(pool.map(run, snapshot['publications']))
    (archive / 'supplements.json').write_text(json.dumps(reviews, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    screen(parser.parse_args().archive)
