"""Private admission shares exact capture budgets without copying a graph."""

from copy import deepcopy

from pydantic import BaseModel, Field
import pytest

from backend.core import part_capture_inputs
from backend.core.models import (
    ClusterCreateLogEntry, ClusterOpLogEntry, DeformationLogEntry, Design,
    MinorMutationLogEntry, OverhangRotationLogEntry, ProteinAsset,
    RoutingClusterLogEntry, SnapshotLogEntry,
)
from backend.core.part_input_sources import describe, embed
from backend.core.part_verification_capture import CaptureLimit, admit, capture
from tests.test_part_capture_copy import atom, design_with_atoms, selected_protein


def owned_projection(source, *, max_nodes=30_000, max_bytes=2_000_000, preserve_entry_types=False):
    return part_capture_inputs.visit_inputs(source, max_nodes=max_nodes, max_bytes=max_bytes,
        seconds=5, preserve_entry_types=preserve_entry_types, copy_inputs=False, retain_owned=True)


class SmallInput(BaseModel):
    """Fixed projection makes the inherited accounting boundaries explicit."""
    id: str = "d"
    metadata: dict = Field(default_factory=dict)
    recipe_root: object = None
    feature_log: list = Field(default_factory=list)
    feature_log_cursor: int = -1
    feature_log_sub_cursor: int | None = None


@pytest.mark.parametrize("case,nodes,size", [
    ("empty", 3, 4), ("mapping", 9, 16), ("alias", 9, 12),
    # Suppression adds its key and boolean (two nodes, forty string bytes) per header.
    ("cycle", 6, 8), ("minor", 14, 144), ("group", 19, 196),
])
def test_inherited_accounting_has_fixed_node_byte_boundaries(case, nodes, size):
    source = SmallInput()
    if case == "mapping":
        source.metadata = {"a": [1, 2], "b": "é"}
    elif case == "alias":
        shared = [1, 2]
        source.metadata = {"a": shared, "b": shared}
    elif case == "cycle":
        cycle = []
        cycle.append(cycle)
        source.metadata = {"x": cycle}
    elif case in {"minor", "group"}:
        row = MinorMutationLogEntry(id="f", op_subtype="nick", label="Ignored label", params={"bp": 2})
        source.feature_log = [row if case == "minor" else RoutingClusterLogEntry(id="g", children=[row])]
    for operation in (admit, owned_projection, lambda source, **limits: capture(source, seconds=5, **limits)):
        operation(source, max_nodes=nodes, max_bytes=size)
        with pytest.raises(CaptureLimit):
            operation(source, max_nodes=nodes - 1, max_bytes=size)
        with pytest.raises(CaptureLimit):
            operation(source, max_nodes=nodes, max_bytes=size - 1)


def history():
    return [
        SnapshotLogEntry.model_construct(id="unsupported", op_kind="retired-operation", label="Legacy",
            params={"selection": ["α", "β"]}, design_snapshot_gz_b64="recovery" * 1000),
        RoutingClusterLogEntry(id="group", label="Fine routing", timestamp="fixed", children=[
            MinorMutationLogEntry(id="nick", op_subtype="nick", label="Nick", params={"bp": 2},
                                  diff_added_b64="ignored diff" * 1000)]),
        ClusterCreateLogEntry(id="group-create", cluster_id="cluster", name="Group", helix_ids=[], proof_version=1),
        ClusterOpLogEntry(id="pose", cluster_id="cluster", translation=[1, 2, 3], rotation=[0, 0, 0, 1],
                         pivot=[0, 0, 0], authored_fields={"name": "β"}, proof_version=1),
        DeformationLogEntry(id="bend", deformation_id="deformation", proof_version=1),
        OverhangRotationLogEntry(id="rotate", overhang_ids=["overhang"], rotations=[[0, 0, 0, 1]], proof_version=1),
    ]


def input_design(case):
    if case in {"nanoparticles", "protein_assets"}:
        source = design_with_atoms(case)
        protein = selected_protein(source, case)
        twin = atom()
        object.__setattr__(twin, "__dict__", protein.atoms[0].__dict__)
        protein.atoms.append(twin)
        protein.metadata["fields"] = twin.__dict__
    else:
        source = Design()
    if case == "cycle":
        cycle = []
        cycle.append(cycle)
        source.metadata.__dict__["opaque"] = cycle
    elif case == "future_atom":
        value = atom()
        value.__dict__["future"] = ["opaque"]
        source.protein_assets = [ProteinAsset.model_construct(atoms=[value], metadata={"again": value})]
    elif case == "sources":
        descriptor = describe(b"original imported bytes", format="blob", media_type="application/octet-stream")
        source.input_sources = {descriptor.sha256: embed(descriptor, b"original imported bytes")}
    source.feature_log = history()
    return source


def minimum_budget(operation, source, budget, preserve):
    low, high = 0, 100_000
    while low < high:
        middle = (low + high) // 2
        try:
            operation(source, preserve_entry_types=preserve, **{budget: middle})
        except CaptureLimit:
            low = middle + 1
        else:
            high = middle
    assert low < 100_000
    return low


@pytest.mark.parametrize("case", ["nanoparticles", "protein_assets", "cycle", "future_atom", "sources"])
@pytest.mark.parametrize("preserve", [False, True])
@pytest.mark.parametrize("budget", ["max_nodes", "max_bytes"])
def test_capture_and_private_admission_agree_at_exact_resource_boundary(case, preserve, budget):
    source = input_design(case)
    isolated = lambda source, **limits: capture(source, seconds=5, **limits)
    boundary = minimum_budget(isolated, source, budget, preserve)
    assert minimum_budget(admit, source, budget, preserve) == boundary
    assert minimum_budget(owned_projection, source, budget, preserve) == boundary
    admit(source, preserve_entry_types=preserve, **{budget: boundary})
    with pytest.raises(CaptureLimit):
        admit(source, preserve_entry_types=preserve, **{budget: boundary - 1})


@pytest.mark.parametrize("preserve", [False, True])
def test_private_admission_neither_copies_nor_constructs_models_or_reads_clock(monkeypatch, preserve):
    source = input_design("protein_assets")
    before = source.model_dump()
    def forbidden(*_args, **_kwargs):
        pytest.fail("Private admission copied/constructed a model or read an isolation clock")
    monkeypatch.setattr(part_capture_inputs, "deepcopy", forbidden)
    monkeypatch.setattr(part_capture_inputs, "monotonic", forbidden)
    monkeypatch.setattr(BaseModel, "model_copy", forbidden)
    monkeypatch.setattr(BaseModel, "model_construct", classmethod(forbidden))
    assert admit(source, preserve_entry_types=preserve) is None
    assert source.model_dump() == before
    with pytest.raises(CaptureLimit):
        admit(source, max_nodes=1, preserve_entry_types=preserve)
    assert source.model_dump() == before


def test_source_capture_keeps_deadline_and_cannot_disable_it(monkeypatch):
    source = input_design("protein_assets")
    before = deepcopy(source)
    now = 0
    def clock():
        nonlocal now
        now += .01
        return now
    monkeypatch.setattr(part_capture_inputs, "monotonic", clock)
    with pytest.raises(CaptureLimit):
        capture(source, seconds=.025)
    with pytest.raises(TypeError, match="time allowance"):
        capture(source, seconds=None)
    assert source == before


@pytest.mark.parametrize("preserve", [False, True])
def test_recovery_payloads_are_not_admitted_and_legacy_kinds_are_not_normalized(preserve):
    source = input_design("sources")
    baseline = minimum_budget(admit, source, "max_bytes", preserve)
    source.feature_log[0].design_snapshot_gz_b64 = "ignored payload" * 100_000
    source.feature_log[1].children[0].diff_added_b64 = "ignored diff" * 100_000
    assert minimum_budget(admit, source, "max_bytes", preserve) == baseline
    captured = capture(source, seconds=5, preserve_entry_types=preserve)
    first = captured.feature_log[0]
    assert getattr(first, "op_kind" if preserve else "op_subtype") == "retired-operation"
    assert not getattr(first, "design_snapshot_gz_b64", "")
    assert not captured.feature_log[1].children[0].diff_added_b64
    source.feature_log[0].params["selection"][0] = "live mutation"
    assert first.params["selection"] == ["α", "β"]
