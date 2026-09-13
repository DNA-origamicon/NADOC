import json

import pytest

from backend.core.models import Design
from backend.core import namd_peg_review as review


def test_review_metadata_roundtrip_has_no_fake_dna():
    d = Design()
    d.metadata.namd_peg_review = dict(schema='nadoc.namd_peg_review.v1', coordinates_nm=[[1, 2, 3]])
    restored = Design.from_json(d.model_dump_json())
    assert restored.metadata.namd_peg_review == d.metadata.namd_peg_review
    assert restored.helices == restored.strands == []


def test_document_without_successful_runs_has_no_completed_jobs(tmp_path, monkeypatch):
    source, workspace = tmp_path/'source', tmp_path/'workspace'; source.mkdir()
    monkeypatch.setattr(review, 'verify_inputs', lambda p: {})
    monkeypatch.setattr(review, 'review_payload', lambda p: dict(jobs=[], schema='nadoc.namd_peg_review.v1'))
    (source/'resident_execution.json').write_text(json.dumps(dict(returncode=1)))
    (source/'resident.log').write_text('FATAL ERROR: stopped')
    path, jobs = review.publish_review(source, workspace)
    assert path.exists() and jobs == []
    assert Design.from_json(path.read_text()).metadata.namd_peg_review['jobs'] == []
    assert not (workspace/'md_jobs').exists()
    with pytest.raises(FileExistsError):
        review.publish_review(source, workspace)


def test_review_document_refuses_path_escape(tmp_path):
    with pytest.raises(ValueError, match='basename'):
        review.publish_review(tmp_path, tmp_path, '../outside.nadoc')


def test_recorded_qualification_cannot_be_promoted_by_normal_production_route():
    from backend.api.routes_md import _production_ready_checkpoint
    from backend.core.md_job import new_job
    job = new_job('PEG', 'qualification', 'system', 'package', run_kind=review.KIND)
    index, spec, reason, warning = _production_ready_checkpoint(job)
    assert index is spec is None
    assert 'not wired' in reason
