"""Atomic, request-scoped progress snapshots for two-base measurements."""
import json
from pathlib import Path


def write_progress(path, done, total):
    if path is None:
        return
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(dict(done=done,total=total,percent=100*done/total if total else 0)))
    temp.replace(path)
