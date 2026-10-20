"""Sweep controls and native display stay detached from source authority."""

from copy import deepcopy
import json

import pytest

from backend.core import deformation, design_geometry
from backend.core.part_command_errors import CommandContractError
from backend.core.part_dna_comparison_codec import unpack_records
from tests.test_part_sweep_preview import prepared, service

from tests.preview_test_limits import preview_test_scale_limits  # noqa: F401  (fixture)

# Bounding-mechanism tests use tiny fixtures at the original test-scale allowances.
pytestmark = pytest.mark.usefixtures("preview_test_scale_limits")



def dto():
    from backend.api import part_sweep_preview_dto
    return part_sweep_preview_dto


def inputs(**kwargs):
    _, owner = prepared(**kwargs)
    return owner.copy_prefix(), service().evaluate(owner, {})


@pytest.mark.parametrize("attached,posed,organized", [(False, False, False),
    (True, False, False), (True, True, False), (True, True, True)])
def test_guides_and_fixed_prefix_context_without_full_sweep_candidate(attached, posed, organized):
    prefix, evaluated = inputs(attached=attached, posed=posed, organized=organized)
    before = prefix.model_dump(mode="json"), evaluated.design.model_dump(mode="json")
    result = dto().prepare_display(prefix, evaluated)
    assert result["projection_version"] == 1
    assert result["stage"] == "feature"
    for field in ("source_equivalence_checked", "downstream_evaluated", "physical_validity"):
        assert result[field] is False
    assert result["sweep_preview"] == evaluated.sweep
    assert "feasibility" not in result
    assert result["candidate"] is None
    for name, design in (("before", prefix),):
        records = design_geometry._geometry_for_design(design)
        axes = deformation.deformed_helix_axes(design)
        axes = deformation._apply_ovhg_rotations_to_axes(design, axes, records)
        assert result[name]["component_kind"] == "deformation-preview-dna"
        assert result[name]["component_version"] == 3
        assert unpack_records(result[name]["nucleotides"]) == records
        assert result[name]["helix_axes"] == axes
    controls = result["control_context"]
    assert set(controls) == {"inputs", "lattice_type", "helices", "lattice_frames"}
    assert controls["inputs"] == evaluated.params
    assert controls["lattice_type"] == prefix.lattice_type.value
    assert controls["lattice_frames"] == [frame.model_dump(mode="json") for frame in prefix.lattice_frames]
    fields = {"id", "label", "grid_pos", "lattice_frame_id", "bp_start", "length_bp", "axis_start", "axis_end"}
    assert controls["helices"] == [helix.model_dump(mode="json", include=fields) for helix in prefix.helices]
    assert not any(helix["id"].endswith(evaluated.params["sweep_id"]) for helix in controls["helices"])
    wire = json.loads(json.dumps(result, allow_nan=False))
    controls["helices"].clear()
    controls["inputs"]["cells"].clear()
    result["sweep_preview"]["points_nm"].clear()
    result["before"]["display_topology"]["strands"].clear()
    assert (prefix.model_dump(mode="json"), evaluated.design.model_dump(mode="json")) == before
    assert dto().prepare_display(prefix, evaluated) == wire


@pytest.mark.parametrize("include_geometry", [False, True])
def test_all_updates_keep_guides_and_feedback_without_nucleotide_projection(monkeypatch, include_geometry):
    prefix, evaluated = inputs(attached=True)
    monkeypatch.setattr(design_geometry, "_geometry_for_design", lambda *_: pytest.fail("allocated nucleotides"))
    monkeypatch.setattr(deformation, "deformed_helix_axes", lambda *_: pytest.fail("allocated axes"))
    result = dto().evaluate_display(prefix, evaluated, include_geometry=include_geometry)
    assert result["candidate"] is None
    assert "before" not in result and "control_context" not in result
    assert result["sweep_preview"] == evaluated.sweep
    for key in ("source_frame", "origin_nm", "point_rotation", "orientation_basis", "point_bases",
                "path_nm", "points_nm", "cross_section_nm", "feasibility"):
        assert key in result["sweep_preview"]


def test_host_envelope_is_owned_and_cannot_replace_projection_fields():
    prefix, evaluated = inputs()
    envelope = {"preview_id": "open", "expected_design_id": prefix.id, "expected_revision": 2,
        "feature_id": evaluated.entry.id, "lease_id": "lease", "doc_id": "doc",
        "deformation_id": evaluated.design.deformations[-1].id, "request_sequence": 1, "remaining_seconds": 55.0}
    result = dto().evaluate_display(prefix, evaluated, envelope=envelope)
    assert all(result[key] == value for key, value in envelope.items())
    envelope["feature_id"] = "changed"
    assert result["feature_id"] == evaluated.entry.id
    with pytest.raises(CommandContractError):
        dto().prepare_display(prefix, evaluated, envelope={"candidate": None})


@pytest.mark.parametrize("field", ["nanoparticles", "protein_assets", "extensions"])
def test_unsupported_geometry_does_not_silently_disappear(monkeypatch, field):
    prefix, evaluated = inputs()
    setattr(evaluated.design, field, [object()])
    monkeypatch.setattr(design_geometry, "_geometry_for_design", lambda *_: pytest.fail("projected partial candidate"))
    with pytest.raises(CommandContractError):
        dto().prepare_display(prefix, evaluated)


def test_forged_selected_sweep_identity_refuses_before_geometry(monkeypatch):
    prefix, evaluated = inputs()
    evaluated.design.deformations[-1].id = "other-sweep"
    monkeypatch.setattr(design_geometry, "_geometry_for_design", lambda *_: pytest.fail("projected wrong operation"))
    with pytest.raises(CommandContractError):
        dto().prepare_display(prefix, evaluated)


def test_combined_wire_budget_includes_native_path_metadata():
    prefix, evaluated = inputs()
    original = deepcopy(evaluated.sweep)
    evaluated.sweep["feasibility"]["message"] = "x" * 2_000_001
    with pytest.raises(CommandContractError) as caught:
        dto().evaluate_display(prefix, evaluated, include_geometry=False)
    assert caught.value.code == "preview_limit"
    evaluated.sweep.clear()
    evaluated.sweep.update(original)
    assert dto().evaluate_display(prefix, evaluated, include_geometry=False)["candidate"] is None


def test_static_prefix_projection_still_rejects_nonfinite_coordinates(monkeypatch):
    prefix, evaluated = inputs()
    original = design_geometry._geometry_for_design
    def malformed(design):
        records = original(design)
        records[0]["backbone_position"][0] = float("nan")
        return records
    monkeypatch.setattr(design_geometry, "_geometry_for_design", malformed)
    with pytest.raises(CommandContractError) as caught:
        dto().prepare_display(prefix, evaluated)
    assert caught.value.code == "invalid_preview_geometry"


def test_sweep_metadata_is_not_trusted_as_validated_native_coordinates():
    prefix, evaluated = inputs()
    evaluated.sweep["path_nm"][0][0] = float("nan")
    with pytest.raises(CommandContractError) as caught:
        dto().evaluate_display(prefix, evaluated)
    assert caught.value.code == "invalid_preview_geometry"


def test_open_projects_only_the_static_prefix_never_the_selected_sweep(monkeypatch):
    from backend.core import part_dna_comparison
    prefix, evaluated = inputs(attached=True)
    original = part_dna_comparison.project_for_deformation_preview
    seen = []
    def project(design):
        assert design is prefix
        seen.append(design)
        return original(design)
    monkeypatch.setattr(part_dna_comparison, "project_for_deformation_preview", project)
    result = dto().prepare_display(prefix, evaluated)
    assert seen == [prefix] and result["candidate"] is None
