import base64
import hashlib
import io
import json
import zipfile
import pytest
from backend.core.article_native_reconstruction import reconstruct_package


def test_reconstruction_failure_returns_actionable_report_not_a_fake_model(monkeypatch):
    import backend.core.publication_authoring as author
    def fail(*args,**kwargs):raise ValueError('Unresolved lattice placement')
    monkeypatch.setattr(author,'compile_publication',fail)
    data=b'%PDF-1.7\nsource'
    payload={'paper':{'name':'source.pdf','data':base64.b64encode(data).decode()},'selections':[
        {'source_sha256':hashlib.sha256(data).hexdigest(),'diagram_page':1,'table_page':2}]}
    with zipfile.ZipFile(io.BytesIO(reconstruct_package(payload))) as archive:
        assert not any(n.endswith('.nadoc') for n in archive.namelist())
        report=json.loads(archive.read('Reconstructed-1-p1.reconstruction.json'))
        assert report['status']=='not_constructed'
        assert report['construction_error']=='Unresolved lattice placement'


@pytest.mark.parametrize('selection',[[],[{'source_sha256':'absent','diagram_page':1,'table_page':2}]])
def test_rejects_missing_source_or_selection(selection):
    with pytest.raises(ValueError):reconstruct_package({'selections':selection})
