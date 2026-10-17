"""Isolated browser-authoritative VR clipboard validation, including runtime scratch."""
import json
import os
from pathlib import Path
import tempfile
from backend.api.vr_capture_launch import load_config
from tools.vr_workflows.ligation_tour import main


def run():
    config = load_config()
    if config is None:
        raise RuntimeError('Configure Archive VR capture storage before this tour')
    original = Path(os.environ.get('NADOC_VR_CAPTURE_CONFIG', str(Path.home()/'.config/nadoc/vr-capture.json')))
    previous = {key: os.environ.get(key) for key in ('NADOC_VR_CAPTURE_CONFIG', 'TMPDIR')}
    # All runtime sidecars, unused journal directories, sockets and browser scratch
    # are owned by this context; failed profiles cannot leave files in shared storage.
    with tempfile.TemporaryDirectory(prefix='cb-', dir=config.archive_mount) as temp:
        root = Path(temp)
        data = json.loads(original.read_text())
        data.update(storage_root=str(root/'runtime'), socket_root=str(root/'sockets'))
        path = root/'capture.json'; path.write_text(json.dumps(data)); path.chmod(0o600)
        os.environ.update(NADOC_VR_CAPTURE_CONFIG=str(path), TMPDIR=temp)
        old_tempdir = tempfile.tempdir; tempfile.tempdir = temp
        print(f'Private VR clipboard runtime: {temp}', flush=True)
        try:
            main('clipboard')
        finally:
            tempfile.tempdir = old_tempdir
            for key, value in previous.items():
                if value is None: os.environ.pop(key, None)
                else: os.environ[key] = value
    print(f'Private VR clipboard runtime removed: {temp}', flush=True)

if __name__ == '__main__':
    run()
