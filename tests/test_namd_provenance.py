import json
from types import SimpleNamespace

from backend.core import namd_provenance as provenance
from backend.core.namd_resources import estimate_memory


def test_receipt_records_exact_build_config_and_device(tmp_path,monkeypatch):
    binary=tmp_path/'namd';binary.write_bytes(b'original')
    conf=tmp_path/'run.conf';conf.write_text('run 100\n')
    monkeypatch.setattr(provenance.subprocess,'run',lambda *a,**k:SimpleNamespace(
        stdout='NVIDIA GeForce RTX 3080 Ti, GPU-test, 580.178.04, 12288\n'))
    receipt=provenance.resource_receipt(binary,conf,estimate_memory(100000),threads=16,devices='0')
    assert receipt['gpu']['driver']=='580.178.04'
    assert receipt['gpu']['total_mib']==12288
    assert not receipt['missing_provenance']
    assert receipt['forecast']['confidence'] is None
    old=receipt['engine']['sha256']
    binary.write_bytes(b'replaced')
    assert provenance.file_identity(binary)['sha256']!=old
    assert json.loads(json.dumps(receipt))['configuration']['sha256']


def test_unknown_identity_stays_unknown(tmp_path,monkeypatch):
    def unavailable(*args,**kwargs):raise FileNotFoundError('no nvidia-smi')
    monkeypatch.setattr(provenance.subprocess,'run',unavailable)
    receipt=provenance.resource_receipt(tmp_path/'missing',tmp_path/'missing.conf',
        estimate_memory(100000),threads=16,devices='0')
    assert receipt['gpu'] is None and receipt['engine']['sha256'] is None
    assert set(receipt['missing_provenance'])=={'engine_sha256','config_sha256','gpu','driver'}


def test_cpu_receipt_does_not_query_gpu(tmp_path,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('GPU queried for CPU execution')
    monkeypatch.setattr(provenance.subprocess,'run',forbidden)
    binary=tmp_path/'namd';binary.write_bytes(b'cpu')
    receipt=provenance.resource_receipt(binary,binary,estimate_memory(100000),threads=16,devices='cpu')
    assert not receipt['missing_provenance'] and receipt['gpu'] is None
