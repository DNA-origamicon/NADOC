"""Prior canonical visibility remains exact through strict byte recovery.

Tiny in-memory records plus one real spawned recovery; no cache or solver files.
"""

import base64
import gzip
import json

import pytest

from backend.api import part_immutable_revision as revisions
from backend.api.part_immutable_recovery_inputs import prepare_stored
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import FIELD_ROLES
from backend.core.part_history_proof import digest
from tests.test_immutable_recovery_worker import (
    _design, _record, admission as admission, transport as transport,
)
from tests.test_immutable_recovery_worker_lifecycle import _complete, _worker


def prior_payload():
    # Reconstruct the exact former full-document encoding, changing no other
    # default, identity, recipe header, number representation or field.
    data = _design("empty").model_dump(mode="json")
    data["visibility_state"].pop("hidden_part_group_ids", None)
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def test_empty_visibility_preserves_prior_canonical_bytes_and_preservation_digest():
    original = prior_payload()
    candidate = revisions.prepare_revision(_design("empty"))
    assert candidate.payload == original
    fields = {name for name, role in FIELD_ROLES.items()
              if role in {"presentation", "physical", "document_identity", "repair_draft"}}
    expected = {key: value for key, value in json.loads(original).items() if key in fields}
    assert revisions.revision_metadata(candidate).preserved_document_sha256 == digest(expected)


def test_nonempty_group_mask_stays_in_saved_json_and_roundtrips():
    from backend.core.models import Design

    source = _design("empty")
    source.visibility_state.hidden_part_group_ids = ["dormant-group"]
    payload = source.to_json()
    assert json.loads(payload)["visibility_state"]["hidden_part_group_ids"] == ["dormant-group"]
    assert Design.from_json(payload).visibility_state.hidden_part_group_ids == ["dormant-group"]


def test_prior_three_field_snapshot_loads_with_an_independent_empty_group_mask():
    from backend.api.state import decode_design_snapshot

    encoded = base64.b64encode(gzip.compress(prior_payload())).decode("ascii")
    first, second = decode_design_snapshot(encoded), decode_design_snapshot(encoded)
    assert first.visibility_state.hidden_part_group_ids == []
    first.visibility_state.hidden_part_group_ids.append("private")
    assert second.visibility_state.hidden_part_group_ids == []


def test_prior_strict_record_prepares_and_materializes_exact_original_bytes(admission):
    record = _record(admission, prior_payload())
    original = record.payload
    candidate, captured = prepare_stored(record)
    assert candidate.payload == original
    assert record.payload is original
    assert record.lease is None
    assert captured.visibility_state.hidden_part_group_ids == []
    decoded = revisions.materialize_revision(candidate)
    assert decoded.visibility_state.hidden_part_group_ids == []
    assert revisions.prepare_revision(decoded).payload == original


def test_spawned_prior_strict_record_retains_exact_source_and_materializes(transport, admission):
    record = _record(admission, prior_payload())
    ticket = transport.reserve_input(record, admission=admission.handle)
    with _worker(transport, ticket) as worker:
        report = _complete(worker)
        candidate = worker.take_revision(ticket, admission=admission.handle)
        assert report["status"] == "verified"
        assert candidate.payload is ticket.payload is record.payload
        decoded = revisions.materialize_revision(candidate)
        assert decoded.visibility_state.hidden_part_group_ids == []
        assert revisions.prepare_revision(decoded).payload == record.payload
    assert admission.session.design is None and admission.session.revision == 0


@pytest.mark.parametrize("damage", ["missing_existing_default", "unknown_visibility", "nonempty_group_mask"])
def test_prior_compatibility_does_not_allow_unrelated_normalization(admission, damage):
    data = json.loads(prior_payload())
    if damage == "missing_existing_default":
        data.pop("annotations_enabled")
    elif damage == "unknown_visibility":
        data["visibility_state"]["future_visibility"] = []
    else:
        data["visibility_state"]["hidden_part_group_ids"] = ["not-in-strict-scope"]
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    with pytest.raises(CommandContractError):
        prepare_stored(_record(admission, payload))
