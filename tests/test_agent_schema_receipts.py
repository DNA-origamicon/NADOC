"""Old receipt bytes remain binding after an optional model field is added."""
import base64
import gzip
import hashlib
import json

import pytest

from backend.core.document_operations import branch_value, content_digest
from backend.core.document_revision_evidence import verify
from backend.core.design_loadouts import decode_snapshot
from backend.core.project_revisions import refresh_active_revision
from scripts.agent_schema_receipts import matches_source_receipt, raw_snapshot
from tests.test_agent_structure_guard import part


def legacy_payload(raw):
    for cluster in raw.get('cluster_transforms', []):
        cluster.pop('folding_order', None)
    data = json.dumps(raw, separators=(',', ':'), ensure_ascii=False).encode()
    return base64.b64encode(gzip.compress(data)).decode(), data


def test_historical_receipt_requires_both_exact_hash_and_independent_replay():
    design = part().design
    raw = json.loads(raw_snapshot(design.feature_log[0].post_state_gz_b64))
    payload, _ = legacy_payload(raw)
    design.feature_log[0].post_state_gz_b64 = payload
    expected = branch_value(design)
    historical = {k: raw[k] for k in expected}
    historical['metadata'] = dict(historical['metadata'])
    for k in ('identity_last_known_path', 'identity_confirmed_at'):
        historical['metadata'].pop(k, None)
    digest = content_digest(historical)
    assert matches_source_receipt(design, expected, digest)
    assert not matches_source_receipt(design, expected, '0'*64)
    expected['helices'][0]['length_bp'] += 1
    assert not matches_source_receipt(design, expected, digest)


def test_old_revision_receipt_binds_exact_serialized_snapshot(tmp_path):
    design = refresh_active_revision(tmp_path, part().design)
    branch = design.loadouts[0]
    raw = json.loads(raw_snapshot(branch.design_snapshot_gz_b64))
    payload, data = legacy_payload(raw)
    branch.design_snapshot_gz_b64 = payload
    branch.snapshot_size_bytes = len(data)
    record = dict(branch.revision_records[branch.head_revision_id])
    stripped = {**raw, 'loadouts':[], 'active_loadout_id':None, 'last_editable_loadout_id':None}
    record['snapshot_sha256'] = hashlib.sha256(json.dumps(stripped, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    header = {key:record[key] for key in ('schema_version','project_id','loadout_id','parent_revision_id','snapshot_sha256')}
    identity = hashlib.sha256(json.dumps(header, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    record['revision_id'] = identity
    branch.head_revision_id = identity
    branch.base_revision_id = identity if branch.base_revision_id else None
    branch.revision_records = {identity:record}
    snapshot = decode_snapshot(payload)
    verify(design, branch, snapshot)
    snapshot.helices[0].phase_offset += .1
    with pytest.raises(ValueError, match='snapshot'):
        verify(design, branch, snapshot)
