"""Real browser launch/acknowledgements plus ScryWrite representation checks."""
import argparse
import subprocess
import json
import urllib.request
import uuid
import shutil
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--doc', required=True, help='Existing read-only document ID')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--validate', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    # Import an isolated copy through the ordinary browser Open action. A fresh
    # tab intentionally starts at Welcome; backend metadata alone is not readiness.
    doc = '__e2e__vr_browser_' + uuid.uuid4().hex
    filename = doc + '.nadoc'
    from backend.api.assembly import _WORKSPACE_DIR
    from backend.core.models import Design
    source = _WORKSPACE_DIR/filename
    cache = _WORKSPACE_DIR/'.session'/doc
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'inventory.txt').write_text(f'Private workspace file {source}; private document {doc}; cache {cache}. finally deletes document, source and cache. No original design/file is changed. Browser temporary profile removed by close; native viewer stopped by matching PID. Evidence remains here.\n')
    def request(path, method='GET'):
        req=urllib.request.Request('http://127.0.0.1:8000/api/'+path, method=method, headers={'X-NADOC-Doc':args.doc})
        return json.load(urllib.request.urlopen(req,timeout=30))
    original=request('design')['design']
    design=Design.model_validate(original)
    design.metadata.name=doc
    try:
        source.write_text(design.to_json())
        command = ['node', 'scripts/verify-vr-browser.mjs', doc, str(args.output.resolve()), filename]
        if args.validate:
            command.append('--validate')
        subprocess.run(command, cwd=root/'frontend', check=True)
    finally:
        try:
            request('documents/'+doc, 'DELETE')
        finally:
            source.unlink(missing_ok=True)
            # Allow the running session-cache flush to see the closed document.
            time.sleep(2)
            if cache.exists():
                shutil.rmtree(cache)
            assert not source.exists() and not cache.exists()
        assert request('design')['design']==original, 'Original document changed'
        (args.output/'cleanup.json').write_text(json.dumps({'sourceRemoved':True,'cacheRemoved':True,'originalUnchanged':True}))



if __name__ == '__main__':
    main()
