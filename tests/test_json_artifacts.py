import gzip

from backend.core.json_artifacts import (
    json_artifact_exists, read_json_artifact, write_json_artifact,
)


def test_compressed_evidence_is_lossless_and_readable_via_legacy_path(tmp_path):
    path = tmp_path / 'summary.json'
    payload = {'pairs': [{'value': 1.23456789012345}], 'label': 'α'}
    plain = write_json_artifact(path, payload).read_bytes()
    archived = write_json_artifact(path, payload, compressed=True)
    assert gzip.decompress(archived.read_bytes()) == plain
    assert not path.exists()
    assert json_artifact_exists(path)
    assert read_json_artifact(path) == payload
    assert read_json_artifact(archived) == payload
    first = archived.read_bytes()
    write_json_artifact(path, payload, compressed=True)
    assert archived.read_bytes() == first


def test_fresh_plain_output_takes_precedence_over_archive(tmp_path):
    path = tmp_path / 'summary.json'
    write_json_artifact(path, {'run': 1}, compressed=True)
    write_json_artifact(path, {'run': 2})
    assert read_json_artifact(path) == {'run': 2}
