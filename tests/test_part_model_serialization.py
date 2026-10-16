"""Expanded serialization work is bounded before any model or JSON encoder."""

from enum import Enum
from importlib import import_module
from typing import Any

import pytest
from pydantic import BaseModel

from backend.api import part_immutable_revision as revisions
from backend.core.part_capture_graph import CaptureLimit, GraphBudget
from backend.core.part_command_errors import CommandContractError


class Record(BaseModel):
    payload: Any


def guard(value, **options):
    return import_module("backend.api.part_model_serialization").admit_model_serialization(value, **options)


def alias_dag(depth):
    value = ["x"]
    for _ in range(depth):
        value = [value, value]
    return value


def test_tiny_alias_dag_cannot_expand_past_group_budget_before_serialization(monkeypatch):
    from backend.core.models import ProteinAsset

    source = ProteinAsset(id="protein", metadata={"nested": alias_dag(20)})
    # Existing capture deliberately counts unique model/container ownership.
    GraphBudget(max_nodes=1_000, max_bytes=20_000, seconds=None, clock=lambda: 0).charge(source)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Expanded admission called a model serializer")

    monkeypatch.setattr(ProteinAsset, "model_dump", forbidden)
    monkeypatch.setattr(ProteinAsset, "model_dump_json", forbidden)
    with pytest.raises(CaptureLimit):
        guard(source, max_bytes=2_000_000, max_nodes=30_000)


def test_shared_lists_are_charged_per_occurrence_at_exact_limits():
    child = ["x", 1]
    value = [child, child]
    # Seven expanded values (114 charged bytes). Existing immutable admission
    # also reserves its pending leave markers: the last child needs 129 bytes.
    assert guard(value, max_nodes=7, max_bytes=129) is None
    with pytest.raises(CaptureLimit):
        guard(value, max_nodes=6, max_bytes=129)
    with pytest.raises(CaptureLimit):
        guard(value, max_nodes=7, max_bytes=128)
    assert value[0] is child and value[1] is child and child == ["x", 1]


def test_same_model_at_two_positions_is_valid_when_expansion_fits():
    record = Record(payload=[1, 2])
    assert guard([record, record], max_nodes=9, max_bytes=176) is None


def test_large_child_list_refuses_before_visiting_children():
    opaque = object()
    with pytest.raises(CaptureLimit):
        guard([opaque] * 100, max_nodes=10, max_bytes=16_000_000)


@pytest.mark.parametrize("container", ["list", "mapping", "model"])
def test_cycles_are_shape_refusals_without_serialization(container):
    module = import_module("backend.api.part_model_serialization")
    value = [] if container == "list" else {} if container == "mapping" else Record(payload=None)
    if container == "list":
        value.append(value)
    elif container == "mapping":
        value["self"] = value
    else:
        value.payload = value
    with pytest.raises(module.SerializationShapeError, match="cyclic"):
        guard(value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 1 << 65, {1: "bad key"}, object()])
def test_non_json_values_fail_with_shape_error(value):
    module = import_module("backend.api.part_model_serialization")
    with pytest.raises(module.SerializationShapeError):
        guard(value)


def test_undeclared_model_storage_is_not_silently_skipped():
    module = import_module("backend.api.part_model_serialization")
    value = Record(payload=1)
    value.__dict__["unclassified"] = "state"
    with pytest.raises(module.SerializationShapeError, match="schema"):
        guard(value)


def test_fixed_depth_guard_precedes_python_recursion_or_encoding():
    module = import_module("backend.api.part_model_serialization")
    value = 0
    for _ in range(65):
        value = [value]
    with pytest.raises(module.SerializationShapeError, match="depth"):
        guard(value)


def test_enums_and_tuples_keep_the_existing_immutable_json_semantics():
    class Token(Enum):
        VALUE = "value"

    assert guard(Record(payload=(Token.VALUE, None, True, 1, 2.5))) is None


@pytest.mark.parametrize("exception", [ValueError, TypeError, KeyboardInterrupt])
@pytest.mark.parametrize("stop_at", [1, 5])
def test_checkpoint_failures_propagate_exactly_during_expanded_walk(exception, stop_at):
    failure = exception("cancelled")
    count = 0

    def checkpoint():
        nonlocal count
        count += 1
        if count == stop_at:
            raise failure

    with pytest.raises(exception) as caught:
        guard(alias_dag(5), checkpoint=checkpoint)
    assert caught.value is failure and count == stop_at


def test_immutable_wrapper_retains_no_extra_30k_node_limit():
    # This is intentionally larger than the group's node ceiling, but tiny
    # within immutable storage's unchanged 16,000,000-byte work allowance.
    assert revisions._check_structure([None] * 30_001, lambda: None) is None


def test_immutable_wrapper_retains_existing_transport_bound(monkeypatch):
    monkeypatch.setattr(revisions, "MAX_CANDIDATE_BYTES", 34)
    with pytest.raises(CaptureLimit, match="Immutable revision exceeds its full transport allowance"):
        revisions._check_structure(["abc"], lambda: None)


def test_immutable_wrapper_retains_shape_error_code_and_message():
    value = []
    value.append(value)
    with pytest.raises(CommandContractError) as failure:
        revisions._check_structure(value, lambda: None)
    assert failure.value.code == "invalid_revision_payload"
    assert str(failure.value) == "Immutable revision cannot contain a cyclic model or JSON value"


def test_immutable_wrapper_uses_shared_guard_without_changing_defaults(monkeypatch):
    module = import_module("backend.api.part_model_serialization")
    original = module.admit_model_serialization
    seen = []

    def observe(value, **options):
        seen.append(options)
        return original(value, **options)

    monkeypatch.setattr(module, "admit_model_serialization", observe)
    assert revisions._check_structure(Record(payload=[1]), lambda: None) is None
    assert len(seen) == 1
    assert seen[0]["max_bytes"] == 16_000_000
    assert seen[0].get("max_nodes") is None
