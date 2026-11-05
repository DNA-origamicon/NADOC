"""Check or restore the committed ACS evidence on another machine.

Does not change acquisition/review history. Uses public source URLs and verifies
the retained SHA-256 before publishing a restored file. No credentials required.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from fetch_acs_repository import get, LIMIT

ROOT = Path(__file__).resolve().parents[1]


def destination(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Asset path escapes selected directory')
    return path


def verify(data, source):
    if len(data) != source['bytes'] or hashlib.sha256(data).hexdigest() != source['sha256']:
        raise ValueError('Source bytes differ from retained size/SHA-256')


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.restore.tmp')
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore', action='store_true', help='Download missing files; default only checks')
    parser.add_argument('--assets', type=Path, default=ROOT / 'assets', help='Existing local asset root or new directory')
    args = parser.parse_args()
    root = args.assets
    if root.is_symlink() and not root.exists():
        raise SystemExit('Asset symlink target unavailable; mount or configure storage first')
    audit = json.loads((ROOT / 'acs_acquisition.json').read_text())
    files = {}
    articles = {}
    for record in audit['records']:
        for f in record['files']:
            if f['status'] == 'downloaded':
                files[f['local_file']] = f
        for article in record['articles']:
            articles[article['id']] = (article, record['doi'])
    missing = []
    for relative, source in files.items():
        path = destination(root, relative)
        if path.exists():
            verify(path.read_bytes(), source)
        else:
            missing.append((path, source))
    metadata = []
    for identifier, (article, doi) in articles.items():
        path = destination(root, f'sources/acs-expansion-20261104/article-{identifier}.json')
        if not path.exists():
            metadata.append((path, article, doi))
    print(f'{len(files) - len(missing)}/{len(files)} document files verified; '
          f'{len(missing)} documents and {len(metadata)} metadata files missing', flush=True)
    if not args.restore:
        return 1 if missing or metadata else 0
    parent = root.resolve()
    while not parent.exists():
        parent = parent.parent
    needed = sum(f['bytes'] for _, f in missing) + 512 * 1024**2
    if shutil.disk_usage(parent).free < needed:
        raise SystemExit(f'Need {needed} free bytes on selected asset filesystem')
    for n, (path, source) in enumerate(missing, 1):
        data = get(source['url'], LIMIT)
        verify(data, source)
        save(path, data)
        print(f'Restored document {n}/{len(missing)}: {path.name}', flush=True)
    for path, article, doi in metadata:
        data = get(article['url'])
        value = json.loads(data)
        if value['id'] != article['id'] or value.get('resource_doi', '').lower() != doi.lower():
            raise ValueError('Repository metadata identity mismatch')
        if not value.get('url_public_html', '').startswith('https://acs.figshare.com/'):
            raise ValueError('Unexpected repository origin')
        save(path, data)
    print('ACS source restoration complete. Acquisition and review ledgers unchanged.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
