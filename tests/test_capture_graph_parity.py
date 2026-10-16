"""Fixed accounting oracles recorded before extracting the shared graph walker.

These tests use the existing public proof capture/admission and recovery helper;
they do not depend on the proposed extraction or the new oxDNA modules.
"""

from copy import deepcopy

from pydantic import BaseModel, Field
import pytest

from backend.api.part_recovery_budget import retained_recovery_bytes
from backend.core import part_capture_inputs as inputs
from backend.core.models import MinorMutationLogEntry, RoutingClusterLogEntry, SnapshotLogEntry
from backend.core.part_verification_capture import CaptureLimit, admit, capture


class SmallInput(BaseModel):
    id: str = "d"
    metadata: dict = Field(default_factory=dict)
    recipe_root: object = None
    feature_log: list = Field(default_factory=list)
    feature_log_cursor: int = -1
    feature_log_sub_cursor: int | None = None


def owned(source, **limits):
    return inputs.visit_inputs(source, max_nodes=limits["max_nodes"], max_bytes=limits["max_bytes"],
        seconds=5, preserve_entry_types=False, copy_inputs=False, retain_owned=True)


@pytest.mark.parametrize("case,nodes,size", [
    ("tuple", 10, 12), ("alias", 9, 16), ("cycle", 6, 8),
])
def test_existing_capture_has_independently_counted_limits(case, nodes, size):
    source = SmallInput()
    if case == "tuple":
        source.metadata = {"α": ("β", None, True, 17, 2.5)}
    elif case == "alias":
        shared = [1, "é"]
        source.metadata = {"x": shared, "y": shared}
    else:
        cycle = []
        cycle.append(cycle)
        source.metadata = {"x": cycle}

    for operation in (admit, owned, lambda value, **limits: capture(value, seconds=5, **limits)):
        operation(source, max_nodes=nodes, max_bytes=size)
        with pytest.raises(CaptureLimit):
            operation(source, max_nodes=nodes - 1, max_bytes=size)
        with pytest.raises(CaptureLimit):
            operation(source, max_nodes=nodes, max_bytes=size - 1)

    copied = capture(source, seconds=5, max_nodes=nodes, max_bytes=size)
    if case == "alias":
        assert copied.metadata["x"] is copied.metadata["y"]
        assert copied.metadata["x"] is not source.metadata["x"]
    elif case == "cycle":
        assert copied.metadata["x"][0] is copied.metadata["x"]
        assert copied.metadata["x"] is not source.metadata["x"]
    else:
        assert copied.metadata == source.metadata


def test_existing_copy_keeps_the_callers_clock_and_deepcopy_seams(monkeypatch):
    source = SmallInput(metadata={"values": [1, 2]})
    before = deepcopy(source)
    now = [0.0]
    copies = []

    def delayed_copy(value, memo=None):
        copies.append(value)
        result = deepcopy(value, memo)
        now[0] = .026
        return result

    monkeypatch.setattr(inputs, "monotonic", lambda: now[0])
    monkeypatch.setattr(inputs, "deepcopy", delayed_copy)
    with pytest.raises(CaptureLimit):
        capture(source)
    assert copies == ["d"]
    assert source == before


def recovery_rows():
    return [
        SnapshotLogEntry(id="old", op_kind="overhang-bulk", label="Legacy",
            design_snapshot_gz_b64="bad!", snapshot_size_bytes=999_999_999),
        RoutingClusterLogEntry(id="group", children=[
            MinorMutationLogEntry(id="child", op_subtype="nick", label="Nick",
                diff_added_b64="é", diff_removed_b64="A")]),
    ]


def test_existing_recovery_charge_counts_opaque_strings_and_child_rows_exactly():
    rows = recovery_rows()
    # Four ASCII characters, conservative four-byte Unicode, one ASCII byte.
    assert retained_recovery_bytes(rows, max_rows=3, limit=9) == 9
    with pytest.raises(CaptureLimit):
        retained_recovery_bytes(rows, max_rows=3, limit=8)
    with pytest.raises(CaptureLimit):
        retained_recovery_bytes(rows, max_rows=2, limit=9)


def test_recovery_storage_charge_remains_separate_from_proof_input_charge():
    source = SmallInput(feature_log=recovery_rows())
    initial = capture(source, seconds=5, preserve_entry_types=True)
    source.feature_log[0].design_snapshot_gz_b64 *= 1000
    expanded = capture(source, seconds=5, preserve_entry_types=True)
    assert initial == expanded
    assert not expanded.feature_log[0].design_snapshot_gz_b64
    assert retained_recovery_bytes(source.feature_log, max_rows=3, limit=4005) == 4005
