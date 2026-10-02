"""Private full-size audit input; authored geometry is never simplified."""
import hashlib
import json
import os
from pathlib import Path
from backend.core.models import Design


def load(default):
    source=os.environ.get('NADOC_VR_AUDIT_DESIGN')
    if not source:return default()
    raw=Path(source).read_bytes()
    data=json.loads(raw)
    for item in data.get('loadouts',[]):
        item['head_revision_id']=None
        item['base_revision_id']=None
    data['metadata']['name']='__e2e__24HB audit'
    data['metadata']['identity_last_known_path']='audit-24hb.nadoc'
    design=Design.from_json(json.dumps(data))
    path=os.environ.get('NADOC_VR_AUDIT_INTERVALS')
    if path:Path(path).with_name('audit-design.json').write_text(json.dumps(dict(source=source,sha256=hashlib.sha256(raw).hexdigest(),helices=len(design.helices),strands=len(design.strands)),indent=2))
    return design
