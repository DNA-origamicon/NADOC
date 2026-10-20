"""Transform response accounting retains closure while using the C encoder."""
import json

import pytest

from backend.api.part_transform_display_contract import bounded
from backend.core.part_command_errors import CommandContractError


@pytest.mark.parametrize("value", [
    {"text": "é\n\\\"😀", "coordinates": [0.0, -1.25, 1e-100, 1e100] * 3},
    {"a": [None, True, False, {"b": [1, 2, 3]}]},
])
def test_wire_boundary_matches_original_chunked_encoding(value):
    size = sum(len(chunk.encode("utf-8")) for chunk in
               json.JSONEncoder(allow_nan=False, separators=(",", ":")).iterencode(value))
    assert bounded(value, max_nodes=1000, max_bytes=size) is value
    with pytest.raises(CommandContractError) as error:
        bounded(value, max_nodes=1000, max_bytes=size - 1)
    assert error.value.code == "preview_limit"


@pytest.mark.parametrize("value", [
    {"coordinates": [float("nan")]},
    {"coordinates": [float("inf")]},
    {"coordinates": [-float("inf")]},
    {"unsupported": {1, 2}},
])
def test_invalid_values_remain_refused(value):
    with pytest.raises(CommandContractError) as error:
        bounded(value)
    assert error.value.code == "invalid_preview_geometry"


def test_cycle_remains_refused():
    value = []
    value.append(value)
    with pytest.raises(CommandContractError) as error:
        bounded(value)
    assert error.value.code == "invalid_preview_geometry"


def test_graph_refusal_precedes_encoding(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Encoding ran before graph admission")
    monkeypatch.setattr(json, "dumps", forbidden)
    with pytest.raises(CommandContractError) as error:
        bounded({"coordinates": [0] * 50}, max_nodes=10)
    assert error.value.code == "preview_limit"


def test_shared_tree_expansion_is_bounded_before_encoding(monkeypatch):
    value = ["small"]
    for _ in range(20):
        value = [value, value]
    def forbidden(*args, **kwargs):
        raise AssertionError("Unbounded shared tree reached the allocating encoder")
    monkeypatch.setattr(json, "dumps", forbidden)
    with pytest.raises(CommandContractError) as error:
        bounded(value, max_nodes=128, max_bytes=4096)
    assert error.value.code == "preview_limit"


def test_ordinary_shared_coordinate_vectors_remain_supported():
    point = [1.0, 2.0, 3.0]
    value = {"start": point, "end": point, "samples": [point, point]}
    assert bounded(value) is value
