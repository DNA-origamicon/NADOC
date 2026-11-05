"""Acquire publisher-deposited ACS supplements; never infer design eligibility.

Reads the retained registry, so the historical bulk-source mount is unnecessary.
DOI matches and file checksums are verified before attaching evidence. No login
state, request headers, cookies, or credentials are written to the audit.
"""
import argparse
import hashlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'assets/sources/acs-expansion-20261104'
AUDIT = ROOT / 'acs_acquisition.json'
LIMIT = 100 * 1024 * 1024
_last_request = 0.0


class RetrievalError(Exception):
    """Safe HTTP diagnosis without response bodies, credentials, or cookies."""
    def __init__(self, url, status, content_type):
        self.diagnostic = {'url': url, 'http_status': status, 'content_type': content_type,
                           'classification': 'authentication_required' if status == 401 else
                           'forbidden_access_or_request_block' if status == 403 else
                           'rate_limited' if status == 429 else 'http_error'}
        super().__init__(f'HTTP {status}: {self.diagnostic["classification"]}')


def retry_after_seconds(value):
    if not value:
        return 0.0
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(0.0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError):
            return 0.0


def get(url, limit=8 * 1024 * 1024):
    global _last_request
    for attempt in range(3):
        # One process, sequential calls, below Figshare's one-request/second advice.
        time.sleep(max(0, 2.0 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
        request = urllib.request.Request(url, headers={'User-Agent': 'NADOC-literature-catalog/1.0'})
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError('response exceeds size bound')
            return data
        except urllib.error.HTTPError as exc:
            diagnostic = RetrievalError(url, exc.code, exc.headers.get('Content-Type', ''))
            retry_after = retry_after_seconds(exc.headers.get('Retry-After'))
            status = exc.code
            exc.close()
            # Never shorten a server-requested long cooldown: defer this request.
            if attempt == 2 or status not in (403, 429, 502, 503, 504) or retry_after > 60:
                raise diagnostic from None
            time.sleep(max(30 * (attempt + 1), retry_after))


def fetch(record):
    doi = record['doi']
    result = {'doi': doi, 'publication': record['publication'], 'status': 'pending', 'articles': [], 'files': []}
    url = 'https://api.figshare.com/v2/articles?' + urllib.parse.urlencode({'resource_doi': doi, 'page_size': 100})
    result['query_url'] = url
    try:
        entries = json.loads(get(url))
        page = 1
        while len(entries) == page * 100:
            page += 1
            entries.extend(json.loads(get(url + '&page=' + str(page))))
        for entry in entries:
            if entry.get('resource_doi', '').lower() != doi.lower():
                continue
            meta_url = entry['url']
            meta = json.loads(get(meta_url))
            if meta.get('resource_doi', '').lower() != doi.lower():
                raise ValueError('detail DOI mismatch')
            (OUT / f"article-{meta['id']}.json").write_text(json.dumps(meta, indent=2) + '\n')
            result['articles'].append({'id': meta['id'], 'url': meta_url, 'title': meta['title'], 'description': meta.get('description', ''), 'license': meta.get('license')})
            for source in meta.get('files', []):
                f = {'name': source['name'], 'url': source['download_url'], 'publisher_bytes': source['size'], 'article_id': meta['id']}
                result['files'].append(f)
                if not re.search(r'\.(pdf|zip|xlsx?|docx?|csv|txt|json|cdn)$', source['name'], re.I):
                    f['status'] = 'deferred_media_format'
                    continue
                if source['size'] > LIMIT:
                    f['status'] = 'deferred_size_over_100_MiB'
                    continue
                name = f"{source['id']}-" + re.sub(r'[^A-Za-z0-9._-]', '_', source['name'])
                path = OUT / name
                try:
                    data = path.read_bytes() if path.exists() else get(source['download_url'], LIMIT)
                    if len(data) != source['size']:
                        raise ValueError('publisher size mismatch')
                    md5 = hashlib.md5(data).hexdigest()
                    if source.get('computed_md5') and md5 != source['computed_md5']:
                        raise ValueError('publisher checksum mismatch')
                    if source['name'].lower().endswith('.pdf') and not data.startswith(b'%PDF'):
                        raise ValueError('not PDF')
                    if source['name'].lower().endswith(('.zip', '.docx', '.xlsx')) and not data.startswith(b'PK'):
                        raise ValueError('not ZIP/Office')
                    if not path.exists():
                        path.write_bytes(data)
                    f.update(status='downloaded', local_file=str(path.relative_to(ROOT / 'assets')), bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), publisher_md5_verified=bool(source.get('computed_md5')))
                except Exception as exc:
                    f.update(status='download_failed', error=str(exc))
                    if isinstance(exc, RetrievalError):
                        f['diagnostic'] = exc.diagnostic
                time.sleep(0.2)
        result['status'] = 'repository_matched' if result['articles'] else 'no_matching_deposit'
    except Exception as exc:
        result.update(status='repository_lookup_failed', error=str(exc))
        if isinstance(exc, RetrievalError):
            result['diagnostic'] = exc.diagnostic
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    if shutil.disk_usage(ROOT).free < 8 * 1024**3:
        raise SystemExit('Need 8 GiB free for bounded acquisition')
    OUT.mkdir(parents=True, exist_ok=True)
    registry = json.loads((ROOT / 'publication_registry.json').read_text())
    # Broad metadata selection includes out-of-scope leads, retained as such.
    records = [r for r in registry if r['doi'].startswith('10.1021/') and (re.search(r'origami|scaffold|DNA nanostruct|DNA nanotube', r['publication'], re.I) or r.get('structure_ids') or r.get('sequence_evidence'))]
    records = records[:args.limit] if args.limit else records
    previous = json.loads(AUDIT.read_text()) if AUDIT.exists() else {'records': []}
    results = {r['doi']: r for r in previous['records']}
    pending = [r for r in records if r['doi'] not in results or results[r['doi']]['status'] == 'repository_lookup_failed' or any(f['status'] == 'download_failed' for f in results[r['doi']]['files'])]
    consecutive_failures = 0
    for n, record in enumerate(pending, 1):
        result = fetch(record)
        previous_result = results.get(result['doi'])
        if previous_result:
            result['attempt_history'] = previous_result.get('attempt_history', []) + [{k: previous_result.get(k) for k in ('query_url', 'status', 'error', 'diagnostic')}]
        if previous_result and result['status'] == 'repository_lookup_failed':
            # A retry must not discard files already retrieved in a partial pass.
            result['files'] = list({f['url']: f for f in previous_result['files'] + result['files']}.values())
            result['articles'] = list({a['id']: a for a in previous_result['articles'] + result['articles']}.values())
        results[result['doi']] = result
        audit = {'date': '2026-11-04', 'source': 'ACS publisher deposits on Figshare', 'scope': 'Acquisition only; not eligibility or sequence-completeness certification', 'selection': 'ACS DOI plus origami/scaffold/DNA nanostructure/nanotube title or existing sequence evidence/structure IDs', 'request_policy': {'minimum_interval_seconds': 2, 'maximum_attempts_per_request': 3, 'backoff_seconds': [30, 60], 'authentication': 'none'}, 'records': list(results.values())}
        temporary = AUDIT.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(audit, indent=2) + '\n')
        temporary.replace(AUDIT)
        print(n, '/', len(pending), result['doi'], result['status'], sum(f['status'] == 'downloaded' for f in result['files']), flush=True)
        consecutive_failures = consecutive_failures + 1 if result['status'] == 'repository_lookup_failed' else 0
        if consecutive_failures >= 3:
            print('Stopping after three consecutive lookup failures; remaining records retained for later retry.', flush=True)
            break


if __name__ == '__main__':
    main()
