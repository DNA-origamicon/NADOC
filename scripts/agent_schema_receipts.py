"""Validate old serialized receipts without discarding independent replay.

Schema-added defaults change byte hashes. An old receipt is usable only when its
exact old bytes hash correctly AND validation equals the independently replayed
current model. Snapshots never supply missing construction commands.
"""
import base64
import gzip
import json

from backend.core.document_operations import branch_value, content_digest
from backend.core.models import Design


def raw_snapshot(payload):
    return gzip.decompress(base64.b64decode(payload))


def matches_source_receipt(design, expected, digest):
    payloads = []
    for row in design.feature_log:
        for field in ('design_snapshot_gz_b64', 'post_state_gz_b64', 'pre_state_gz_b64'):
            if value := getattr(row, field, None):
                payloads.append(value)
    payloads.extend(branch.design_snapshot_gz_b64 for branch in design.loadouts)
    for payload in payloads:
        raw = json.loads(raw_snapshot(payload))
        if branch_value(Design.model_validate(raw)) != expected:
            continue
        historical = {key: raw[key] for key in expected if key in raw}
        historical['metadata'] = dict(historical['metadata'])
        for key in ('identity_last_known_path', 'identity_confirmed_at'):
            historical['metadata'].pop(key, None)
        if content_digest(historical) == digest:
            return True
    return False
