import hashlib,json
from types import SimpleNamespace
import pytest
from backend.core.namd_experimental_engine import experimental_engine


def test_regular_jobs_keep_normal_engine_resolution(tmp_path):
    assert experimental_engine(SimpleNamespace(prep_params={}),tmp_path) is None


def test_experimental_engine_requires_available_unchanged_matching_binary(tmp_path):
    binary=tmp_path/'namd3';binary.write_text('recorded experimental engine');binary.chmod(0o755)
    job=SimpleNamespace(prep_params={'experimental_namd_binary':str(binary)})
    manifest={'two_electrodes':{'normal_axis':1},'experimental_validation':{'binary':str(binary),'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest()}}
    path=tmp_path/'manifest.json';path.write_text(json.dumps(manifest))
    assert experimental_engine(job,tmp_path)==str(binary)
    binary.write_text('changed engine')
    with pytest.raises(RuntimeError,match='checksum changed'):experimental_engine(job,tmp_path)
    binary.unlink()
    with pytest.raises(RuntimeError,match='unavailable'):experimental_engine(job,tmp_path)
    manifest['experimental_validation']['binary']='different';path.write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError,match='provenance'):experimental_engine(job,tmp_path)
