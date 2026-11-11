"""Paced public research fetches with resumable SHA-256 manifests (no credentials)."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.request
from urllib.parse import urlsplit, parse_qsl
import ledger


def validate_payload(filename, data):
    if filename.lower().endswith(('.html', '.htm')):
        preview = data[:200000].lower()
        if (b'nc state university libraries bot detection' in preview or b'verifying you are not a bot' in preview or (b'const challengeid' in preview and b'cookies must be enabled' in preview)):
            raise ValueError('Automated-access challenge is not acquired source evidence')
    if filename.lower().endswith('.pdf') and b'%PDF-' not in data[:1024]:
        raise ValueError('Expected PDF bytes; received a non-PDF response')


def fetch(url, filename):
    directory = ledger.ROOT / 'assets/research-20261105'
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / 'acquisition.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    path = directory / filename
    if filename in manifest and manifest[filename].get('status') == 'available':
        item = manifest[filename]
        old_url, new_url = urlsplit(item['url']), urlsplit(url)
        if old_url[:3] != new_url[:3] or sorted(parse_qsl(old_url.query, keep_blank_values=True)) != sorted(parse_qsl(new_url.query, keep_blank_values=True)):
            raise ValueError('Filename identity conflict')
        if path.is_file() and path.stat().st_size:
            assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']
            validate_payload(filename, path.read_bytes())
            return item
    time.sleep(2)
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'OrigamiLiteratureResearch/1.0'})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(100 * 1024**2 + 1)
            if not data:
                raise ValueError('Empty response is not acquired source evidence')
            if len(data) > 100 * 1024**2:
                raise ValueError('Source exceeds 100 MiB')
        validate_payload(filename, data)
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_bytes(data)
        temporary.replace(path)
        item = {'url': url, 'local_file': str(path.relative_to(ledger.ROOT)),
                'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'date': ledger.DATE, 'status': 'available'}
    except Exception as error:
        item = {'url': url, 'date': ledger.DATE, 'status': 'failed', 'error': str(error)}
    manifest[filename] = item
    ledger.atomic(manifest_path, json.dumps(manifest, indent=2))
    return item


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url'); parser.add_argument('filename')
    args = parser.parse_args()
    print(json.dumps(fetch(args.url, args.filename), indent=2))
