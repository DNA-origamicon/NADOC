import json
from pathlib import Path
import pytest
from experiments.cpd_anti_additive.portable_restart_v17 import digest,verify,run

def test_relocated_inputs_detect_tampering(tmp_path):
    root=tmp_path/'relocated with spaces';root.mkdir();f=root/'input';f.write_bytes(b'checkpoint')
    (root/'manifest.json').write_text(json.dumps({'files':{'input':digest(f)},'states':{}}))
    verify(root);f.write_bytes(b'changed')
    with pytest.raises(ValueError,match='hash mismatch'):verify(root)

def test_limits_and_no_overwrite_before_native_launch(tmp_path):
    for steps in [-1,1,500001,8000000]:
        with pytest.raises(ValueError):run(tmp_path,'anti-1',tmp_path/'out',Path('/nonexistent'),steps)
    (tmp_path/'manifest.json').write_text(json.dumps({'files':{},'states':{'anti-1':{}}}))
    (tmp_path/'templates').mkdir();(tmp_path/'templates/anti-1.probe.conf').write_text('run 0\n')
    out=tmp_path/'out';out.mkdir()
    with pytest.raises(FileExistsError):run(tmp_path,'anti-1',out,Path('/nonexistent'),0)
