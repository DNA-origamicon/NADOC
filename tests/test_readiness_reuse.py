"""Readiness reuses derivation work without changing topology or verdicts."""

import weakref

import pytest

from backend.api import routes_design_readiness as routes
from backend.core import assembly_flatten, assembly_validate, design_readiness, sequences
from backend.core.models import Assembly, AssemblyJoint, LoopSkip, PartInstance, PartSourceFile, PartSourceInline
from backend.core.validator import validate_design
from tests.test_design_readiness import sequenced_design


@pytest.mark.parametrize("case", ["ordinary", "loop", "skip", "overhang", "binder", "reference", "invalid", "duplicate"])
def test_reused_sequence_map_preserves_complete_validation_and_readiness(monkeypatch, case):
    design = sequenced_design(n_helices=2)
    design.helices[0].loop_skips = [LoopSkip(bp_index=5, delta=-1 if case == "skip" else 1)]
    if case == "ordinary":
        design.helices[0].loop_skips = []
    elif case in ("overhang", "binder"):
        field = "overhang_id" if case == "overhang" else "binds_overhang_id"
        design.strands[1].domains[0] = design.strands[1].domains[0].model_copy(update={field: "overhang"})
    elif case == "reference":
        design.strands[1].is_reference = True
    elif case == "duplicate":
        design.strands.append(design.strands[1].model_copy(deep=True))
    for strand in design.strands:
        strand.sequence = "A" * sequences.strand_sequence_length(design, strand)
    if case == "invalid":
        design.strands[0].sequence = "N"
    before = design.model_dump()
    original_length = sequences.strand_sequence_length

    def legacy_length(design, strand, **_kwargs):
        return original_length(design, strand)  # Build the map for every call, as before.

    with monkeypatch.context() as patch:
        patch.setattr(sequences, "strand_sequence_length", legacy_length)
        patch.setattr(design_readiness, "strand_sequence_length", legacy_length)
        legacy_validation = validate_design(design)
        legacy_readiness = design_readiness.standard_readiness(design)
    assert validate_design(design) == legacy_validation
    assert design_readiness.standard_readiness(design) == legacy_readiness
    assert design.model_dump() == before


@pytest.mark.parametrize("assigned", [True, False])
def test_readiness_builds_one_loop_skip_map_per_design_projection(monkeypatch, assigned):
    design = sequenced_design(n_helices=2)
    design.strands *= 12  # Repeated object/ID entries must not be collapsed.
    if not assigned:
        for strand in design.strands:
            strand.sequence = None
    builds = []
    original = sequences._build_loop_skip_map

    def counted(design):
        builds.append(design)
        return original(design)

    monkeypatch.setattr(sequences, "_build_loop_skip_map", counted)
    monkeypatch.setattr(design_readiness, "_build_loop_skip_map", counted)
    design_readiness.standard_readiness(design)
    # Original editor Design in validation, active projection in readiness.
    assert len(builds) == (2 if assigned else 1)


def test_explicit_empty_map_is_reused_and_callers_without_map_still_recompute(monkeypatch):
    design = sequenced_design()
    before = sequences.strand_sequence_length(design, design.strands[0])
    design.helices[0].loop_skips = [LoopSkip(bp_index=5, delta=1)]
    assert sequences.strand_sequence_length(design, design.strands[0]) == before + 1
    # An empty map represents a previous snapshot; bulk callers own its lifetime.
    monkeypatch.setattr(sequences, "_build_loop_skip_map", lambda _: pytest.fail("map rebuilt"))
    assert sequences.strand_sequence_length(design, design.strands[0], loop_skip_map={}) == before


@pytest.mark.parametrize("case", ["valid", "joint", "duplicate", "missing"])
def test_validate_and_flatten_retains_report_and_exact_projection(case):
    design = sequenced_design()
    part = PartInstance(id="part", source=PartSourceInline(design=design))
    assembly = Assembly(instances=[part])
    if case == "joint":
        assembly.joints = [AssemblyJoint(instance_b_id="missing")]
    elif case == "duplicate":
        assembly.instances.append(part.model_copy(deep=True))
    elif case == "missing":
        part.source = PartSourceFile(path="__missing_readiness_reuse__.nadoc")
    expected_report = assembly_validate.validate_assembly_report(assembly)
    report, flattened = assembly_validate.validate_and_flatten_assembly(assembly)
    assert report == expected_report
    if case in ("duplicate", "missing"):
        assert flattened is None
    else:
        assert flattened.model_dump() == assembly_flatten.flatten_assembly(assembly).model_dump()


def test_assembly_readiness_flattens_once_and_keeps_canonical_projection(monkeypatch):
    part = PartInstance(source=PartSourceInline(design=sequenced_design()))
    assembly = Assembly(instances=[part])
    original_flatten = assembly_flatten.flatten_assembly
    expected = routes.Design.from_json(original_flatten(assembly).to_json())
    calls = []

    def counted(assembly):
        calls.append(assembly.id)
        return original_flatten(assembly)

    monkeypatch.setattr(assembly_flatten, "flatten_assembly", counted)
    projected, report = routes._assembly_report(assembly)
    assert calls == [assembly.id]
    assert projected.model_dump() == expected.model_dump()
    assert report["state"] == design_readiness.standard_readiness(expected)["state"]


def test_assembly_flatten_failure_retains_actionable_readiness_error():
    part = PartInstance(id="same", source=PartSourceInline(design=sequenced_design()))
    projected, report = routes._assembly_report(Assembly(instances=[part, part.model_copy(deep=True)]))
    assert projected is None
    assert report["available"] and report["state"] == "incomplete"
    assert report["steps"][0]["detail"] == "Review assembly topology before simulation."
    assert "duplicate helix IDs" in report["steps"][0]["issues"][0]


def test_readiness_releases_flattened_design_before_parsing_canonical_projection(monkeypatch):
    assembly = Assembly(instances=[PartInstance(source=PartSourceInline(design=sequenced_design()))])
    original_validate = assembly_validate.validate_and_flatten_assembly
    original_parse = routes.Design.from_json
    projection_refs = []

    def remember(assembly):
        report, projection = original_validate(assembly)
        projection_refs.append(weakref.ref(projection))
        return report, projection

    def parse(cls, serialized):
        assert projection_refs and projection_refs[-1]() is None
        return original_parse(serialized)

    monkeypatch.setattr(assembly_validate, "validate_and_flatten_assembly", remember)
    monkeypatch.setattr(routes.Design, "from_json", classmethod(parse))
    projected, report = routes._assembly_report(assembly)
    assert projected is not None and report["available"]
