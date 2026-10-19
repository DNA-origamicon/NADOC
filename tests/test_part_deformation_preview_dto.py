"""Owned native preview display/control values, without a host or renderer."""

from copy import deepcopy
import json

import pytest

from backend.api import part_deformation_preview as preview
from backend.core import deformation, design_geometry
from backend.core.models import DeformationLogEntry, LoopSkip, Strand
from backend.core.part_command_errors import CommandContractError
from backend.core.part_dna_comparison_codec import unpack_records
from backend.core.validator import validate_design
from tests.test_part_deformation_preview import native_source, owned_capture, patch
from tests.test_part_dna_comparison import small

from tests.preview_test_limits import preview_test_scale_limits  # noqa: F401  (fixture)

# Bounding-mechanism tests use tiny fixtures at the original test-scale allowances.
pytestmark = pytest.mark.usefixtures("preview_test_scale_limits")



def _service():
    from backend.api import part_deformation_preview_dto
    return part_deformation_preview_dto


def _owned(kind="bend", *, grouped=False, scoped=False):
    source = native_source(kind, grouped=grouped, scoped=scoped)
    prepared = preview.prepare_from_capture(owned_capture(source), "edited-feature")
    return prepared.copy_prefix(), preview.evaluate(prepared, patch(kind))


def _component_input(kind):
    candidate = small(kind)
    prefix = candidate.model_copy(deep=True, update={"deformations": []})
    op = candidate.deformations[-1]
    entry = DeformationLogEntry(id="selected", deformation_id=op.id,
                                op_snapshot=op.model_copy(deep=True), proof_version=1)
    return prefix, preview.EvaluatedPreview(candidate, entry, validate_design(candidate))


def _ordinary_geometry(design):
    records = design_geometry._geometry_for_design(design)
    axes = deformation.deformed_helix_axes(design)
    return records, deformation._apply_ovhg_rotations_to_axes(design, axes, records)


@pytest.mark.parametrize("kind", ["bend", "twist"])
@pytest.mark.parametrize("grouped,scoped", [(False, False), (True, False), (False, True)])
def test_complete_native_geometry_and_controls_are_owned(kind, grouped, scoped):
    prefix, evaluated = _owned(kind, grouped=grouped, scoped=scoped)
    before = prefix.model_dump(mode="json"), evaluated.design.model_dump(mode="json")
    entry_before = evaluated.entry.model_dump(mode="json")
    result = _service().prepare_display(prefix, evaluated)
    wire = json.loads(json.dumps(result, allow_nan=False))
    for label, design in (("before", prefix), ("candidate", evaluated.design)):
        records, axes = _ordinary_geometry(design)
        component = wire[label]
        assert component["component_kind"] == "deformation-preview-dna"
        assert component["component_version"] == 2
        assert unpack_records(component["nucleotides"]) == records
        assert component["helix_axes"] == axes
    assert result["stage"] == "feature"
    assert result["source_equivalence_checked"] is False
    assert result["downstream_evaluated"] is False
    assert result["physical_validity"] is False
    controls = result["control_context"]
    assert controls["selected_operation"] == evaluated.entry.op_snapshot.model_dump(mode="json")
    assert controls["deformations"] == [op.model_dump(mode="json") for op in prefix.deformations]
    assert controls["capabilities"]["change_targets"] is False
    assert controls["capabilities"]["change_clusters"] is (not scoped)
    if scoped:
        assert any("samples" in segment for axis in result["candidate"]["helix_axes"]
                   for segment in axis["segments"])
    # DTO consumers may mutate every returned layer without modifying either
    # private input or the next independent projection.
    result["before"]["nucleotides"][0][4][0] += 100
    result["candidate"]["display_topology"]["strands"][0]["domains"].clear()
    controls["strands"][0]["domains"].clear()
    controls["selected_operation"]["affected_helix_ids"].clear()
    assert (prefix.model_dump(mode="json"), evaluated.design.model_dump(mode="json")) == before
    assert evaluated.entry.model_dump(mode="json") == entry_before
    assert _service().prepare_display(prefix, evaluated) == wire


def test_single_helix_twist_preserves_visible_base_and_slab_orientation():
    prefix, evaluated = _component_input("twist")
    result = _service().prepare_display(prefix, evaluated)
    before = unpack_records(result["before"]["nucleotides"])
    after = unpack_records(result["candidate"]["nucleotides"])
    assert len(result["candidate"]["helix_axes"]) == 1
    assert any(a["base_normal"] != b["base_normal"] for a, b in zip(before, after, strict=True))
    assert any(a["slab_quaternion"] != b["slab_quaternion"] for a, b in zip(before, after, strict=True))
    assert after == design_geometry._geometry_for_design(evaluated.design)


def test_loop_copy_and_reference_flags_remain_lossless_native_fields():
    prefix, evaluated = _component_input("twist")
    for design in (prefix, evaluated.design):
        design.helices[0].loop_skips = [LoopSkip(bp_index=3, delta=1), LoopSkip(bp_index=8, delta=-1)]
        design.strands[1].is_reference = True
    result = _service().prepare_display(prefix, evaluated)
    records = unpack_records(result["candidate"]["nucleotides"])
    assert records == design_geometry._geometry_for_design(evaluated.design)
    assert any(record["copy_k"] == 1 for record in records)
    assert any(record["is_reference"] for record in records)
    assert not any(record["bp_index"] == 8 for record in records)


def test_prefix_controls_retain_polymer_and_scope_inputs_without_latest_history():
    prefix, evaluated = _component_input("periodic")
    prefix.strands[0].notes = "Polymerization connector: keep this exact note"
    evaluated.design.strands[0].notes = prefix.strands[0].notes
    result = _service().prepare_display(prefix, evaluated)
    controls = result["control_context"]
    assert controls["strands"][0]["notes"] == prefix.strands[0].notes
    assert controls["forced_ligations"] == [x.model_dump(mode="json") for x in prefix.forced_ligations]
    assert controls["helices"][0]["bp_start"] == prefix.helices[0].bp_start
    assert controls["selected_operation"]["params"]["polymer_circle_count"] == 1
    assert "feature_log" not in controls and "recipe_root" not in controls


@pytest.mark.parametrize("kind,scoped", [("bend", False), ("twist", False), ("bend", True), ("twist", True)])
def test_feasibility_matches_ordinary_native_route_on_the_same_prefix(monkeypatch, kind, scoped):
    from backend.api import routes_loop_skip

    prefix, evaluated = _owned(kind, scoped=scoped)
    op = evaluated.entry.op_snapshot
    monkeypatch.setattr(routes_loop_skip.design_state, "get_or_404", lambda: prefix)
    expected = routes_loop_skip.validate_deformation(routes_loop_skip.DeformationValidateRequest(
        type=op.type, plane_a_bp=op.plane_a_bp, plane_b_bp=op.plane_b_bp,
        params=op.params.model_dump(mode="json"), cluster_ids=op.cluster_ids,
        helix_ids=op.affected_helix_ids, targets=op.targets,
    ))
    result = _service().evaluate_display(prefix, evaluated, include_geometry=False)
    assert result["candidate"] is None
    assert result["feasibility"] == expected


def test_feedback_without_visual_preview_does_not_allocate_native_geometry(monkeypatch):
    prefix, evaluated = _owned()
    monkeypatch.setattr(design_geometry, "_geometry_for_design", lambda *_a, **_k: pytest.fail("geometry was allocated"))
    monkeypatch.setattr(deformation, "deformed_helix_axes", lambda *_a: pytest.fail("axes were allocated"))
    result = _service().evaluate_display(prefix, evaluated, include_geometry=False)
    assert result["candidate"] is None and result["feasibility"]["op_type"] == "bend"


@pytest.mark.parametrize("field", ["nanoparticles", "protein_assets", "protein_attachments", "extensions"])
def test_unsupported_geometry_family_never_disappears_from_preview(monkeypatch, field):
    prefix, evaluated = _owned()
    setattr(evaluated.design, field, [object()])
    monkeypatch.setattr(design_geometry, "_geometry_for_design", lambda *_a, **_k: pytest.fail("partial native geometry"))
    with pytest.raises(CommandContractError) as caught:
        _service().prepare_display(prefix, evaluated)
    assert caught.value.code == "unsupported_preview_scope"


@pytest.mark.parametrize("change", ["large_text", "remote_domain"])
def test_input_and_prospective_limits_refuse_before_geometry(monkeypatch, change):
    prefix, evaluated = _owned()
    if change == "large_text":
        prefix.strands[0].notes = "x" * 500_001
    else:
        evaluated.design.strands[0].domains[0].end_bp = 1_000_000
    monkeypatch.setattr(design_geometry, "_geometry_for_design", lambda *_a, **_k: pytest.fail("geometry before admission"))
    if change == "large_text":
        monkeypatch.setattr(Strand, "model_dump", lambda *_a, **_k: pytest.fail("control serialization before admission"))
    with pytest.raises(CommandContractError) as caught:
        _service().prepare_display(prefix, evaluated)
    assert caught.value.code == "preview_limit"


@pytest.mark.parametrize("damage", ["missing", "duplicate", "extra_field"])
def test_incomplete_native_output_is_refused(monkeypatch, damage):
    prefix, evaluated = _owned()
    original = design_geometry._geometry_for_design

    def broken(*args, **kwargs):
        result = original(*args, **kwargs)
        if damage == "missing":
            result.pop()
        elif damage == "duplicate":
            result.append(deepcopy(result[0]))
        else:
            result[0]["unreviewed"] = True
        return result

    monkeypatch.setattr(design_geometry, "_geometry_for_design", broken)
    with pytest.raises(CommandContractError):
        _service().evaluate_display(prefix, evaluated)


def test_scoped_segment_sample_limit_counts_all_emitted_samples(monkeypatch):
    from backend.core import part_dna_comparison_contract

    prefix, evaluated = _owned(scoped=True)
    original = deformation.deformed_helix_axes

    def oversized(design):
        axes = original(design)
        for axis in axes:
            for segment in axis["segments"]:
                if "samples" in segment:
                    segment["samples"] = [[0.0, 0.0, 0.0]] * (part_dna_comparison_contract.MAX_AXIS_POINTS + 1)
                    return axes
        pytest.fail("scoped fixture emitted no native segment samples")

    monkeypatch.setattr(deformation, "deformed_helix_axes", oversized)
    with pytest.raises(CommandContractError) as caught:
        _service().evaluate_display(prefix, evaluated)
    assert caught.value.code == "preview_limit"


@pytest.mark.parametrize("limit", ["MAX_OUTPUT_BYTES", "MAX_OUTPUT_NODES"])
def test_combined_result_has_independent_output_allowances(monkeypatch, limit):
    prefix, evaluated = _owned()
    service = _service()
    monkeypatch.setattr(service, limit, 100)
    with pytest.raises(CommandContractError) as caught:
        service.prepare_display(prefix, evaluated)
    assert caught.value.code == "preview_limit"


def test_comparison_v3_and_preview_v2_preserve_same_scoped_axes_and_limits(monkeypatch):
    from backend.core import part_dna_comparison as projection

    _prefix, evaluated = _owned(scoped=True)
    comparison = projection.project(evaluated.design)
    displayed = projection.project_for_deformation_preview(evaluated.design)
    assert comparison["component_version"] == 3
    assert displayed["component_version"] == 2
    assert displayed["component_kind"] == "deformation-preview-dna"
    assert {key: value for key, value in displayed.items() if key not in {
        "component_version", "component_kind"}} == {
        key: value for key, value in comparison.items() if key != "component_version"}
    assert comparison["helix_axes"] == _ordinary_geometry(evaluated.design)[1]
    assert any("samples" in segment for axis in comparison["helix_axes"] for segment in axis["segments"])
    monkeypatch.setattr(projection, "MAX_AXIS_POINTS", 1)
    for project in (projection.project, projection.project_for_deformation_preview):
        with pytest.raises(CommandContractError) as caught:
            project(evaluated.design)
        assert caught.value.code == "comparison_limit"


def _host_envelope():
    return {"preview_id": "opening", "expected_design_id": "part", "expected_revision": 4,
            "feature_id": "feature", "lease_id": "lease", "doc_id": "document",
            "deformation_id": "operation", "request_sequence": 2, "remaining_seconds": 30.5}


@pytest.mark.parametrize("operation", ["prepare", "evaluate", "controls"])
def test_optional_host_envelope_is_owned_and_preserves_standalone_payload(operation, monkeypatch):
    service = _service()
    prefix, evaluated = _owned()

    def project(**kwargs):
        if operation == "prepare":
            return service.prepare_display(prefix, evaluated, **kwargs)
        return service.evaluate_display(prefix, evaluated, include_geometry=operation != "controls", **kwargs)

    expected = project()
    original = service._bounded
    bounded = []

    def observe(value, **options):
        bounded.append(deepcopy(value))
        return original(value, **options)

    monkeypatch.setattr(service, "_bounded", observe)
    envelope = _host_envelope()
    result = project(envelope=envelope)
    assert result == {**expected, **envelope}
    assert bounded == [result]
    envelope["feature_id"] = "caller-modified"
    assert result["feature_id"] == "feature"


@pytest.mark.parametrize("envelope", [
    {"candidate": None}, {"control_context": None}, {"before": None}, {"stage": "feature"},
    {"source_equivalence_checked": False}, {"unexpected": "scalar"}, {"doc_id": ["document"]},
    {"expected_revision": True}, {"request_sequence": -1}, {"remaining_seconds": float("nan")},
    {"remaining_seconds": float("inf")}, {"remaining_seconds": -1}, {"feature_id": "x" * 257},
    [("doc_id", "document")],
])
def test_invalid_or_colliding_host_envelope_refuses_before_native_projection(monkeypatch, envelope):
    service = _service()
    prefix, evaluated = _owned()
    monkeypatch.setattr(service, "_inputs", lambda *_a: pytest.fail("Native admission before envelope refusal"))
    with pytest.raises(CommandContractError) as caught:
        service.prepare_display(prefix, evaluated, envelope=envelope)
    assert caught.value.code == "invalid_preview_definition"


def test_whole_host_envelope_counts_toward_the_same_output_allowance(monkeypatch):
    from backend.core.part_capture_graph import GraphBudget

    service = _service()
    prefix, evaluated = _owned()
    payload = service.evaluate_display(prefix, evaluated, include_geometry=False)
    budget = GraphBudget(max_nodes=service.MAX_OUTPUT_NODES, max_bytes=service.MAX_OUTPUT_BYTES,
                         seconds=None, clock=lambda: 0)
    budget.charge(payload)
    monkeypatch.setattr(service, "MAX_OUTPUT_NODES", service.MAX_OUTPUT_NODES - budget.remaining[0])
    assert service.evaluate_display(prefix, evaluated, include_geometry=False) == payload
    with pytest.raises(CommandContractError) as caught:
        service.evaluate_display(prefix, evaluated, include_geometry=False, envelope=_host_envelope())
    assert caught.value.code == "preview_limit"


def test_standalone_nonfinite_output_still_refuses(monkeypatch):
    service = _service()
    prefix, evaluated = _owned()
    monkeypatch.setattr(service, "_feasibility", lambda *_a: {"metric": float("nan")})
    with pytest.raises(CommandContractError) as caught:
        service.evaluate_display(prefix, evaluated, include_geometry=False)
    assert caught.value.code == "invalid_preview_geometry"
