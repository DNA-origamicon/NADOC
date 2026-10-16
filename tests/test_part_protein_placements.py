"""Part protein placement records inputs without creating or deleting binders."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.api import part_protein_commands as commands
from backend.core.conjugation import conjugation_candidate_for_serial
from backend.core.models import (
    Mat4x4, ProteinAttachment, ProteinTargetFree, RepresentationOverride,
    RepresentationSegment,
)
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.protein import gizmo_move_to_pose, parse_protein_pdb, reverse_complement
from tests.test_protein import _SYNTH_PDB, _design_with_overhang


def _params(**values):
    return {"_proof_version": 1, "protein_version": 1, "attachment_id": "placement", **values}


def _attach_params(target="free", **values):
    return _params(asset_id="asset", target=({"kind": "free"} if target == "free" else {
        "kind": "overhang", "overhang_id": "oh_5p", "attach_end": "free_end",
    }), conjugation_atom_serial=9, handle_complement_bp=0, handle_spacer_nt=0, **values)


@pytest.fixture
def design():
    source = _design_with_overhang()
    source.overhangs[0].sequence = "ACGTACGT"
    asset = parse_protein_pdb(_SYNTH_PDB, name="synth", source_filename="synth.pdb")
    asset.id = "asset"
    return source.copy_with(protein_assets=[asset])


@pytest.mark.parametrize("target", ["free", "overhang"])
def test_native_placement_preserves_existing_geometry_inputs_without_topology_mutation(design, target):
    params = _attach_params(target)
    before = design.model_dump_json()
    result = commands.build("protein-attach", design, params,
                            resolver=lambda _s: pytest.fail("Placement resolved external input"))
    attachment = result.protein_attachments[0]
    assert attachment.id == "placement" and attachment.asset_id == "asset"
    assert attachment.conjugation_atom_serial == 9
    assert attachment.target.kind == target
    assert attachment.pose == Mat4x4()
    assert attachment.binder_strand_id is None and attachment.azide_end is None
    assert not attachment.handle_complement_bp and not attachment.handle_spacer_nt
    if target == "overhang":
        selected = conjugation_candidate_for_serial(design.protein_assets[0], 9)
        assert selected is not None
        assert attachment.conjugation_chemistry == selected["chemistry"]
        assert attachment.conjugation_accessible_fraction == selected["accessible"]
        assert attachment.handle_sequence == reverse_complement(design.overhangs[0].sequence)
    else:
        expected = ProteinAttachment(id="placement", asset_id="asset",
            target=ProteinTargetFree(), conjugation_atom_serial=9)
        assert attachment == expected
    assert result.model_dump(include=AUTHORING_FIELDS - {"protein_attachments", "cluster_transforms"}) == design.model_dump(
        include=AUTHORING_FIELDS - {"protein_attachments", "cluster_transforms"})
    assert len(result.cluster_transforms) == 1
    cluster = result.cluster_transforms[0]
    assert cluster.is_default and cluster.auto_created
    assert cluster.helix_ids == [helix.id for helix in design.helices]
    replay = commands.build("protein-attach", design, params)
    assert replay.cluster_transforms == result.cluster_transforms
    assert design.model_dump_json() == before
    assert commands.resources("protein-attach", params) == {"sources": (), "imports": False}


def test_selected_atom_does_not_change_when_asset_default_changes(design):
    params = _attach_params()
    design.protein_assets[0].default_conjugation_atom_serial = 1
    result = commands.build("protein-attach", design, params)
    assert result.protein_attachments[0].conjugation_atom_serial == 9


@pytest.mark.parametrize("kind", ["protein-attach-patch", "protein-attach-delete"])
def test_sparse_placement_edits_bootstrap_default_cluster_before_response(design, kind):
    design.protein_attachments = [ProteinAttachment(
        id="placement", asset_id="asset", target=ProteinTargetFree(), conjugation_atom_serial=9)]
    original = design.model_dump_json()
    result = commands.build(kind, design, _params())
    repeated = commands.build(kind, design, _params())
    assert len(result.cluster_transforms) == 1
    assert result.cluster_transforms == repeated.cluster_transforms
    assert result.cluster_transforms[0].is_default
    assert design.model_dump_json() == original


def test_overhang_creation_retains_native_nonreactive_atom_selection(design):
    # The established attach route permits placement at any existing atom;
    # reactive-site gating applies when explicitly editing a conjugation site.
    params = {**_attach_params("overhang"), "conjugation_atom_serial": 2}
    result = commands.build("protein-attach", design, params)
    assert result.protein_attachments[0].conjugation_atom_serial == 2
    assert result.protein_attachments[0].conjugation_chemistry is None


@pytest.mark.parametrize("target", ["free", "overhang"])
def test_pose_patch_matches_native_gizmo_order_and_preserves_other_state(design, target):
    source = commands.build("protein-attach", design, _attach_params(target))
    source.protein_attachments.append(ProteinAttachment(
        id="independent", asset_id="asset", target=ProteinTargetFree(), conjugation_atom_serial=1))
    old_pose = Mat4x4()
    old_pose.values[3] = 7
    source.protein_attachments[0].pose = old_pose
    before = source.model_dump_json()
    move = {"pivot": [1, 2, 3], "translation": [3, -2, 4], "rotation": [0, 0, 1, 0]}
    absolute = Mat4x4().values
    absolute[3] = -20
    params = _params(pose=absolute, gizmo_move=move, visible=False,
                     handle_complement_bp=4, handle_spacer_nt=3)
    result = commands.build("protein-attach-patch", source, params)
    expected = Mat4x4.from_array(gizmo_move_to_pose(old_pose.to_array(), **move))
    changed = result.protein_attachments[0]
    assert changed.id == "placement" and changed.pose == expected
    assert changed.visible is False
    assert (changed.handle_complement_bp, changed.handle_spacer_nt) == (4, 3)
    assert changed.target == source.protein_attachments[0].target
    assert result.protein_attachments[1] == source.protein_attachments[1]
    assert result.model_dump(include=AUTHORING_FIELDS - {"protein_attachments"}) == source.model_dump(
        include=AUTHORING_FIELDS - {"protein_attachments"})
    assert source.model_dump_json() == before


def test_explicit_site_patch_uses_existing_chemistry_and_accessibility_gate(design):
    source = commands.build("protein-attach", design, _attach_params())
    result = commands.build("protein-attach-patch", source, _params(conjugation_atom_serial=9))
    expected = conjugation_candidate_for_serial(design.protein_assets[0], 9)
    assert result.protein_attachments[0].conjugation_chemistry == expected["chemistry"]
    assert result.protein_attachments[0].conjugation_accessible_fraction == expected["accessible"]
    with pytest.raises(ReferenceResolutionError, match="surface-accessible"):
        commands.build("protein-attach-patch", source, _params(conjugation_atom_serial=2))


def test_explicit_atom_patch_can_repair_a_removed_selected_atom(design):
    source = commands.build("protein-attach", design, _attach_params())
    source.protein_attachments[0].conjugation_atom_serial = 999
    result = commands.build("protein-attach-patch", source, _params(conjugation_atom_serial=9))
    assert result.protein_attachments[0].conjugation_atom_serial == 9


def test_null_patch_fields_preserve_legacy_noop_semantics(design):
    source = commands.build("protein-attach", design, _attach_params())
    result = commands.build("protein-attach-patch", source, _params(
        pose=None, gizmo_move=None, visible=None, conjugation_atom_serial=None,
        handle_complement_bp=None, handle_spacer_nt=None))
    assert result == source


@pytest.mark.parametrize("case,kind,path", [
    ("asset", "protein_asset", ["asset_id"]),
    ("atom", "protein_atom", ["conjugation_atom_serial"]),
    ("overhang", "overhang", ["target", "overhang_id"]),
    ("helix", "helix", ["target", "overhang_id"]),
    ("strand", "strand", ["target", "overhang_id"]),
    ("domain", "overhang", ["target", "overhang_id"]),
])
def test_missing_placement_references_fail_before_native_selection(design, case, kind, path, monkeypatch):
    from backend.core import conjugation

    if case == "asset":
        design.protein_assets = []
    elif case == "atom":
        design.protein_assets[0].atoms = [atom for atom in design.protein_assets[0].atoms if atom.serial != 9]
    elif case == "overhang":
        design.overhangs = []
    elif case == "helix":
        design.helices = [helix for helix in design.helices if helix.id != "oh_helix"]
    elif case == "strand":
        design.strands = [strand for strand in design.strands if strand.id != "oh_strand"]
    else:
        design.find_strand("oh_strand").domains[0].overhang_id = None
    monkeypatch.setattr(conjugation, "conjugation_candidate_for_serial",
                        lambda *_a: pytest.fail("Broken references reached native selection"))
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build("protein-attach", design, _attach_params("overhang"))
    assert error.value.code == "missing_reference"
    reference = error.value.as_issue()["references"][0]
    assert reference["kind"] == kind and reference["parameter_path"] == path


@pytest.mark.parametrize("family", ["asset", "atom", "overhang", "attachment"])
def test_ambiguous_or_reused_identity_is_rejected(design, family):
    if family == "asset":
        design.protein_assets *= 2
    elif family == "atom":
        design.protein_assets[0].atoms.append(design.protein_assets[0].atoms[-1])
    elif family == "overhang":
        design.overhangs *= 2
    else:
        design = commands.build("protein-attach", design, _attach_params("overhang"))
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build("protein-attach", design, _attach_params("overhang"))
    assert error.value.code == "invalid_selection"


@pytest.mark.parametrize("kind", ["protein-attach-patch", "protein-attach-delete"])
@pytest.mark.parametrize("duplicate", [False, True])
def test_missing_or_duplicate_attachment_is_not_a_silent_noop(design, kind, duplicate):
    if duplicate:
        design = commands.build("protein-attach", design, _attach_params())
        design.protein_attachments *= 2
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build(kind, design, _params())
    assert error.value.code == ("invalid_selection" if duplicate else "missing_reference")
    assert error.value.as_issue()["references"][0]["parameter_path"] == ["attachment_id"]


@pytest.mark.parametrize("ownership", ["binder", "azide", "legacy"])
@pytest.mark.parametrize("kind", ["protein-attach-patch", "protein-attach-delete"])
def test_conjugate_ownership_is_rejected_without_changing_dna(design, ownership, kind):
    source = commands.build("protein-attach", design, _attach_params("overhang"))
    if ownership == "binder":
        source.protein_attachments[0].binder_strand_id = "missing-binder"
    elif ownership == "azide":
        source.protein_attachments[0].azide_end = "5p"
    else:
        source.strands[0].domains[0].binds_overhang_id = "oh_5p"
    before = source.model_dump_json()
    with pytest.raises(ReferenceResolutionError, match="ownership contract"):
        commands.build(kind, source, _params())
    assert source.model_dump_json() == before


def test_bound_target_is_rejected_before_selected_atom_calculation(design, monkeypatch):
    from backend.core import conjugation

    design.strands[0].domains[0].binds_overhang_id = "oh_5p"
    monkeypatch.setattr(conjugation, "conjugation_candidate_for_serial",
                        lambda *_a: pytest.fail("Bound target reached native selection"))
    with pytest.raises(ReferenceResolutionError, match="ownership contract") as error:
        commands.build("protein-attach", design, _attach_params("overhang"))
    assert error.value.as_issue()["references"][0]["parameter_path"] == ["target", "overhang_id"]


def test_delete_repairs_missing_dependencies_and_prunes_overrides_without_mutation(design):
    source = commands.build("protein-attach", design, _attach_params("overhang"))
    source.protein_assets = []
    source.overhangs = []
    source.protein_attachments.append(ProteinAttachment(
        id="other", asset_id="missing-asset", target=ProteinTargetFree(), conjugation_atom_serial=1))
    source.representation_overrides = [
        RepresentationOverride(id="removed", protein_attachment_ids=["placement"]),
        RepresentationOverride(id="shared", protein_attachment_ids=["placement", "other"]),
        RepresentationOverride(id="dna", protein_attachment_ids=["placement"],
            segments=[RepresentationSegment(helix_id=source.helices[0].id, bp_start=0, bp_end=1)]),
    ]
    before = deepcopy(source)
    result = commands.build("protein-attach-delete", source, _params())
    assert [item.id for item in result.protein_attachments] == ["other"]
    assert [item.id for item in result.representation_overrides] == ["shared", "dna"]
    assert [item.protein_attachment_ids for item in result.representation_overrides] == [["other"], []]
    assert result.strands == source.strands and result.helices == source.helices
    assert source == before


@pytest.mark.parametrize("change", [
    lambda p: p.update(target={"kind": "assembly", "instance_id": "instance"}),
    lambda p: p.update(binder_strand_id="binder"),
    lambda p: p.update(azide_end="5p"),
    lambda p: p.update(conjugation_atom_serial=None),
    lambda p: p.update(conjugation_atom_serial=True),
    lambda p: p.update(handle_complement_bp=-1),
    lambda p: p.update(pose=[0] * 15),
    lambda p: p.update(pose=[float("nan")] * 16),
    lambda p: p.update(protein_version=True),
    lambda p: p.update(parsed_asset={}),
])
def test_placement_schema_excludes_assembly_chemistry_and_malformed_inputs(change):
    params = _attach_params()
    change(params)
    with pytest.raises(ValidationError):
        commands.parse_command("protein-attach", params)
