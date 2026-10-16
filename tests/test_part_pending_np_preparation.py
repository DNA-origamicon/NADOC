"""Reuse native admission only inside the same locked pending transaction."""

import pytest
from pydantic import ValidationError

from backend.api import part_nanoparticle_connection_commands as native
from backend.api import routes_nanoparticles as routes
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from tests.test_part_pending_np_connections import (
    CREATE, creation, document as document, native_prefix as native_prefix,
    request, signature, source as source,
)


def count_preparation(monkeypatch):
    counts = {name: 0 for name in ("_bounded", "typed_ownership_supported", "identity_index")}
    for name in counts:
        original = getattr(native, name)
        def wrapped(*args, _name=name, _original=original, **kwargs):
            counts[_name] += 1
            return _original(*args, **kwargs)
        monkeypatch.setattr(native, name, wrapped)
    return counts


def test_live_create_performs_each_complete_admission_pass_once(document, monkeypatch):
    counts = count_preparation(monkeypatch)
    result = routes.create_np_connection_version("gold", request(document))
    assert result["version_id"]
    assert counts == {"_bounded": 1, "typed_ownership_supported": 1, "identity_index": 1}


def test_standalone_replay_always_prepares_current_source_independently(source, monkeypatch):
    counts = count_preparation(monkeypatch)
    native.build(CREATE, source, creation(source))
    native.build(CREATE, source, creation(source, version_id="second"))
    assert counts == {"_bounded": 2, "typed_ownership_supported": 2, "identity_index": 2}
    # A later invalid input cannot reuse an identity index from an earlier call.
    source.helices.append(source.helices[0])
    with pytest.raises(ReferenceResolutionError) as error:
        native.build(CREATE, source, creation(source, version_id="third"))
    assert error.value.code == "invalid_selection"
    assert counts["identity_index"] == 3


def test_preparation_cannot_be_reused_for_equal_identity_or_shallow_alias_design(source):
    prepared = native._prepare_source(source)
    body = native.parse_command(CREATE, creation(source))
    for other in (source.model_copy(deep=True), source.model_copy()):
        assert other.id == source.id and other is not source
        with pytest.raises(CommandContractError) as error:
            native._build_prepared(CREATE, other, body, prepared)
        assert error.value.code == "source_changed"


def test_missing_live_target_stays_typed_and_atomic_after_preparation(document, monkeypatch):
    from fastapi import HTTPException

    before = signature()
    counts = count_preparation(monkeypatch)
    with pytest.raises(HTTPException) as error:
        routes.create_np_connection_version("gold", request(document, overhang_id="missing"))
    assert error.value.status_code == 404
    assert error.value.detail["references"][0]["parameter_path"] == ["overhang_id"]
    assert signature() == before
    assert counts == {"_bounded": 1, "typed_ownership_supported": 1, "identity_index": 1}


def test_unsupported_and_oversize_sources_stop_before_identity_index(source, monkeypatch):
    monkeypatch.setattr(native, "identity_index", lambda *_a: pytest.fail("Unsupported source was indexed"))
    monkeypatch.setattr(native, "_bounded", lambda *_a: False)
    assert not native._route_eligible(source, "gold", None, {})
    with pytest.raises(CommandContractError):
        native.build(CREATE, source, creation(source))
    monkeypatch.setattr(native, "_bounded", lambda *_a: True)
    monkeypatch.setattr(native, "typed_ownership_supported", lambda *_a: False)
    assert not native._route_eligible(source, "gold", None, {})
    with pytest.raises(CommandContractError):
        native.build(CREATE, source, creation(source))


def test_invalid_command_schema_never_prepares_an_inventory(source, monkeypatch):
    monkeypatch.setattr(native, "_prepare_source", lambda *_a: pytest.fail("Invalid schema was prepared"))
    with pytest.raises(ValidationError):
        native.build(CREATE, source, creation(source, nanoparticle_connection_version=2))
