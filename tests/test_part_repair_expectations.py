"""Canonical expectation transport does not weaken strict repair conflicts."""

import json
from math import copysign

import pytest
from pydantic import ValidationError

from backend.api.part_proof_commands import dependencies
from backend.core.models import SnapshotLogEntry
from backend.core.part_history_contract import create_empty_part
from backend.core.part_repair_expectations import (
    MAX_EXPECTATION_JSON_CHARS, decode_expected_old, encode_expected_old, normalize_expected_old,
)
from backend.core.part_repair_inputs import RepairRequest, SetInput
from backend.core.part_repair_planning import RepairInputError, plan_actions, same_input


def action(displayed=12, encoded="12.0", **extra):
    return {"action": "set_input", "feature_id": "gold", "parameter_path": ["diameter_nm"],
            "expected_old": displayed, "expected_old_json": encoded, "value": 13.5, **extra}


@pytest.mark.parametrize("exact,displayed", [
    (12.0, 12), (12, 12.0), (-0.0, 0), (1e-7, 1e-7), (True, True), (None, None),
    ([1.0, 0.0, -0.0, 3], [1, 0, 0, 3]),
    ({"position": [1.0, 2], "enabled": False, "label": 'brackets [{ \\" é'},
     {"label": 'brackets [{ \\" é', "enabled": False, "position": [1, 2.0]}),
])
def test_normalization_preserves_exact_old_value_and_opaque_canonical_text(exact, displayed):
    encoded = encode_expected_old(exact)
    raw = action(displayed, encoded)
    parsed = SetInput.model_validate(raw)
    assert same_input(parsed.expected_old, exact)
    assert parsed.expected_old_json == encoded
    assert parsed.model_dump()["expected_old_json"] == encoded
    assert same_input(raw["expected_old"], displayed)
    if exact == 0 and type(exact) is float:
        assert copysign(1, parsed.expected_old) == copysign(1, exact)


@pytest.mark.parametrize("displayed,encoded", [
    (True, "1"), (1, "true"), (False, "0.0"), (None, "0"), ("12", "12.0"),
    (12, "13.0"), ([1, 2], "[1.0]"), ({"a": 1}, '{"b":1.0}'),
    ({"a": True}, '{"a":1.0}'), (9007199254740992, "9007199254740993"),
])
def test_mismatching_display_or_boolean_integer_value_is_rejected(displayed, encoded):
    with pytest.raises(ValueError, match="does not match"):
        SetInput.model_validate(action(displayed, encoded))


@pytest.mark.parametrize("text", [
    '{"a":1,"a":1}', '{"a":1,"\\u0061":2}', "NaN", "Infinity", "-Infinity", "1e999", "-1e999",
    "18446744073709551616", "-18446744073709551616", "0" * 1000,
    " 12.0", "12.0 ", "1e0", '[1, 2]', '{"b":1,"a":2}', "{}{}", "[", '"unterminated',
])
def test_noncanonical_duplicate_nonfinite_overflow_or_invalid_json_is_rejected(text):
    with pytest.raises(ValueError):
        decode_expected_old(text)


def test_depth_guard_precedes_parser_and_ignores_brackets_inside_strings(monkeypatch):
    import backend.core.part_repair_expectations as codec
    native = codec.json.loads
    calls = []
    def loads(*args, **kwargs):
        calls.append(True)
        return native(*args, **kwargs)
    monkeypatch.setattr(codec.json, "loads", loads)
    with pytest.raises(ValueError, match="nesting"):
        decode_expected_old("[" * 65 + "0" + "]" * 65)
    assert not calls
    text = 'brackets [{\\"' * 100
    assert decode_expected_old(encode_expected_old(text)) == text
    assert calls == [True]


@pytest.mark.parametrize("text", ["[" + ",".join(["0"] * 10_001) + "]",
                                 json.dumps("x" * MAX_EXPECTATION_JSON_CHARS)])
def test_decoded_structure_and_encoded_text_keep_existing_bounds(text):
    with pytest.raises(ValueError):
        decode_expected_old(text)


def test_entire_action_and_aggregate_request_are_charged_without_per_receipt_allowances():
    # Each action fits alone; four together exceed the unchanged outer envelope.
    text = "x" * 8000
    raw = action(text, encode_expected_old(text), value="new")
    SetInput.model_validate(raw)
    with pytest.raises(ValueError, match="byte budget"):
        RepairRequest.model_validate({"repair_version": 1, "expected_design_id": "part", "expected_revision": 1,
            "actions": [{**raw, "feature_id": f"feature-{index}"} for index in range(4)]})
    with pytest.raises(ValueError, match="byte budget"):
        normalize_expected_old(action("x" * 40_000, encode_expected_old("x" * 40_000)))


def test_existing_actions_without_receipts_keep_original_values_and_stored_shape():
    raw = action()
    raw.pop("expected_old_json")
    parsed = SetInput.model_validate(raw)
    assert type(parsed.expected_old) is int and "expected_old_json" not in parsed.model_dump()
    assert SetInput.model_validate({**raw, "expected_old_json": None}).model_dump() == parsed.model_dump()


def test_normalization_owns_nested_values_without_mutating_the_request():
    raw = action([1, 2], "[1.0,2.0]")
    parsed = SetInput.model_validate(raw)
    parsed.expected_old[0] = 99
    assert raw["expected_old"] == [1, 2]
    assert raw["expected_old_json"] == "[1.0,2.0]"
    with pytest.raises(ValidationError):
        SetInput.model_validate(parsed.model_dump())


def source(diameter=12.0):
    design = create_empty_part("Typed expectation", "HONEYCOMB")
    design.feature_log = [SnapshotLogEntry(id="gold", op_kind="nanoparticle-create", label="Gold", params={
        "_proof_version": 1, "nanoparticle_version": 1, "nanoparticle_id": "stable", "diameter_nm": diameter})]
    return design


def test_receipt_only_restores_transport_strict_conflicts_and_output_guards_remain():
    design = source()
    target = plan_actions(design, [SetInput.model_validate(action())], dependencies=dependencies)["gold"]
    assert target.params["diameter_nm"] == 13.5 and target.params["nanoparticle_id"] == "stable"
    assert design.feature_log[0].params["diameter_nm"] == 12.0
    # A forged receipt for the numerically equal but differently typed value is
    # still rejected by the unchanged strict captured-source comparison.
    for raw in (action(12, "12"), action(13, "13.0")):
        with pytest.raises(RepairInputError) as error:
            plan_actions(design, [SetInput.model_validate(raw)], dependencies=dependencies)
        assert error.value.code == "repair_conflict"
    with pytest.raises(RepairInputError) as error:
        plan_actions(source(12), [SetInput.model_validate(action())], dependencies=dependencies)
    assert error.value.code == "repair_conflict"
    for path, old, new in (("nanoparticle_id", "stable", "replacement"), ("_proof_version", 1, 2)):
        raw = action(old, encode_expected_old(old), parameter_path=[path], value=new)
        with pytest.raises(RepairInputError) as error:
            plan_actions(design, [SetInput.model_validate(raw)], dependencies=dependencies)
        assert error.value.code == "protected_recipe_identity"
