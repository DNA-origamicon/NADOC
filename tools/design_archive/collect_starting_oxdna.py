"""Download only explicitly unrelaxed configurations and candidate topology files."""
import hashlib
import json
from pathlib import Path
import httpx


def run(output):
    records = json.loads(Path('frontend/src/data/nanobase_inventory.json').read_text())['records']
    report = []
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        for r in records:
            if r['supplement']['status'] != 'Verified caDNAno routing figure':
                continue
            candidates = [f for f in r['files'] if f['name'].lower().endswith(('.dat', '.oxdna')) and 'unrelaxed' in (f['name'] + ' ' + f.get('description', '')).lower()]
            entry = {'id': r['id'], 'title': r['title'], 'status': 'unrelaxed label in filename or description; content verification required' if candidates else 'no explicitly unrelaxed configuration', 'files': []}
            if candidates:
                for f in candidates + [f for f in r['files'] if f['name'].endswith('.top')]:
                    dest = output / str(r['id']) / Path(f['name']).name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    info = dict(f, path=str(dest))
                    try:
                        if not dest.exists():
                            response = client.get(f['url']); response.raise_for_status()
                            if len(response.content) > 30 * 1024 * 1024:
                                raise ValueError('exceeds 30 MiB single-input limit')
                            dest.write_bytes(response.content)
                        info['sha256'] = hashlib.sha256(dest.read_bytes()).hexdigest()
                    except Exception as exc:
                        info['error'] = str(exc)
                    entry['files'].append(info)
            report.append(entry)
            print(r['id'],entry['status'],flush=True)
            output.mkdir(parents=True, exist_ok=True)
            (output / 'manifest.json').write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    import sys
    run(Path(sys.argv[1]))
