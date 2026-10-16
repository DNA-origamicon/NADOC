"""Refuse malformed owned-preparation inputs before hooks or source copying.

These are boundary tests, without geometry, protocol preparation or file I/O.
"""

from dataclasses import replace

from fastapi import HTTPException
import pytest

from backend.core import models as m
from backend.core.part_capture_graph import CaptureLimit, GraphBudget
from tests.test_oxdna_preparation_capture import (
    _document_context, core, forbidden, host, options, source,
)


class HookBomb:
    def __bool__(self):
        pytest.fail("Admission evaluated an unreviewed truthiness hook")

    def __deepcopy__(self, _memo):
        pytest.fail("Admission copied an unreviewed object")

    @property
    def __dict__(self):
        pytest.fail("Admission inspected an unreviewed record")


class IdentityBomb(str):
    def startswith(self, *_args):
        pytest.fail("Admission invoked an unreviewed string method")


class KeyBomb:
    def __init__(self, field):
        self.field = field

    def __hash__(self):
        return hash(self.field)

    def __eq__(self, _other):
        pytest.fail("Admission invoked an unreviewed mapping key equality hook")


def test_model_storage_keys_refuse_before_schema_equality_hooks(monkeypatch):
    original = source()
    data = dict(original.__dict__)
    value = data.pop("metadata")
    data[KeyBomb("metadata")] = value
    object.__setattr__(original, "__dict__", data)
    monkeypatch.setattr(core(), "deepcopy", forbidden)
    with pytest.raises(core().UnsupportedPreparation):
        core().capture_archive(original)


def test_option_keys_refuse_before_schema_equality_hooks(monkeypatch):
    values = options()
    value = values.pop("backend")
    values[KeyBomb("backend")] = value
    monkeypatch.setattr(core(), "capture_archive", forbidden)
    with _document_context():
        captured = host().capture_current(values)
        assert not captured.supported and captured.design is None
        assert captured.coverage["status"] == "unknown"


def test_host_origin_storage_keys_refuse_before_design_id_lookup(monkeypatch):
    with _document_context() as (_identity, session, original):
        data = dict(original.__dict__)
        identity = data.pop("id")
        data[KeyBomb("id")] = identity
        object.__setattr__(original, "__dict__", data)
        monkeypatch.setattr(core(), "capture_archive", forbidden)
        with pytest.raises(HTTPException) as failure:
            host().capture_current(options())
        assert failure.value.status_code == 422
        assert session.design is original and session.revision == 7


def test_model_storage_dict_subclass_refuses_before_mapping_or_copy_hooks(monkeypatch):
    class StorageBomb(dict):
        def keys(self):
            pytest.fail("Admission inspected an unreviewed model storage mapping")

        def values(self):
            pytest.fail("Admission walked an unreviewed model storage mapping")

        def __deepcopy__(self, _memo):
            pytest.fail("Admission copied an unreviewed model storage mapping")

    original = source()
    object.__setattr__(original, "__dict__", StorageBomb(original.__dict__))
    monkeypatch.setattr(core(), "deepcopy", forbidden)
    with pytest.raises(core().UnsupportedPreparation):
        core().capture_archive(original)


@pytest.mark.parametrize("location", ["row", "child", "children"])
def test_history_shape_refusal_precedes_storage_introspection_and_copy(monkeypatch, location):
    original = source()
    if location == "row":
        original.feature_log = [HookBomb()]
    else:
        row = m.RoutingClusterLogEntry(id="group", children=[])
        row.children = [HookBomb()] if location == "child" else HookBomb()
        original.feature_log = [row]
    monkeypatch.setattr(core(), "deepcopy", forbidden)
    with pytest.raises(core().UnsupportedPreparation):
        core().capture_archive(original)


@pytest.mark.parametrize("field,value", [
    ("id", IdentityBomb("unreviewed")),
    ("id", HookBomb()),
    ("native_source", HookBomb()),
    ("native_residues", HookBomb()),
])
def test_helix_profile_rejects_opaque_values_without_hooks(monkeypatch, field, value):
    original = source()
    setattr(original.helices[0], field, value)
    monkeypatch.setattr(core(), "deepcopy", forbidden)
    with pytest.raises(core().UnsupportedPreparation):
        core().capture_archive(original)


@pytest.mark.parametrize("field", ["auxiliary_endpoint", "strand_anim_setup"])
def test_overhang_profile_rejects_opaque_values_without_truthiness(monkeypatch, field):
    original = source()
    overhang = m.OverhangSpec(id="oh", helix_id=original.helices[0].id,
                            strand_id="dna", sequence="ACGT")
    setattr(overhang, field, HookBomb())
    original.overhangs = [overhang]
    monkeypatch.setattr(core(), "deepcopy", forbidden)
    with pytest.raises(core().UnsupportedPreparation):
        core().capture_archive(original)


def test_mapping_child_count_is_admitted_before_inspecting_key_shapes():
    # The parent is affordable, but neither child is. A malformed key must not
    # trigger a key scan before the already-impossible count is refused.
    budget = GraphBudget(max_nodes=1, max_bytes=100, seconds=None, clock=lambda: 0.)
    with pytest.raises(CaptureLimit, match="node budget"):
        budget.charge({object(): None}, validate=core()._shape, reject_cycles=True)


def test_complete_source_classification_happens_once_per_locked_capture(monkeypatch):
    classify = core().source_reason
    calls = []

    def counted(value):
        calls.append(value)
        return classify(value)

    monkeypatch.setattr(core(), "source_reason", counted)
    with _document_context() as (_identity, _session, original):
        captured = host().capture_current(options())
        assert captured.supported and calls == [original]


def test_changed_source_design_identity_refuses_package_guard_without_revision_bump():
    with _document_context() as (_identity, _session, original):
        captured = host().capture_current(options())
        original.id = "different-part"
        with pytest.raises(HTTPException) as failure:
            host().require_current(captured)
        assert failure.value.status_code == 409


def test_strict_source_refuses_without_decode_or_mutable_copy(monkeypatch):
    from backend.api import part_immutable_revision as revisions
    from backend.core.part_history_contract import create_empty_part

    sealed = revisions.prepare_revision(create_empty_part("Strict", "HONEYCOMB"))
    monkeypatch.setattr(revisions, "materialize_revision", forbidden)
    monkeypatch.setattr(core(), "capture_archive", forbidden)
    with _document_context() as (_identity, session, _original):
        session.design = sealed
        with pytest.raises(HTTPException) as failure:
            host().capture_current(options())
        assert failure.value.status_code == 409
        assert failure.value.detail["code"] == "immutable_design_access"
        assert session.design is sealed


def test_copied_capture_record_cannot_authorize_package_guard():
    with _document_context():
        captured = host().capture_current(options())
        with pytest.raises(HTTPException) as failure:
            host().require_current(replace(captured))
        assert failure.value.status_code == 409
