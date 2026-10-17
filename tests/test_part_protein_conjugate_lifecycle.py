"""Owned conjugate edits use native motion and closed directional deletion."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.api import part_protein_conjugate_lifecycle as commands, routes_protein as routes, state
from backend.api.part_protein_conjugation_commands import build as conjugate
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.core import models as m
from backend.core.cluster_autodetect import with_default_cluster
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.protein import parse_protein_pdb
from tests.test_protein import _SYNTH_PDB, _design_with_overhang


def _params(**values):
    return {"_proof_version": 1, "protein_version": 1, "conjugation_version": 1,
            "attachment_id": "placement", "binder_strand_id": "binder", **values}


def _move():
    return {"pivot": [0, 0, 0], "translation": [0.2, 0.3, 0.1], "rotation": [0, 0, 0, 1]}


def _make_conjugate():
    asset = parse_protein_pdb(_SYNTH_PDB, name="synth")
    asset.id = "asset"
    initial = _design_with_overhang().copy_with(protein_assets=[asset])
    initial.overhangs[0].sequence = "ACGTACGT"
    initial = with_default_cluster(initial, identity_factory=lambda *_a: "source-cluster")
    return conjugate("protein-conjugate", initial, {
        **_params(), "asset_id": "asset", "overhang_id": "oh_5p", "group_id": "group",
        "conjugation_atom_serial": 9, "azide_end": "5p",
    })


@pytest.fixture(scope="module")
def native_conjugate():
    return _make_conjugate()


@pytest.fixture
def design(native_conjugate):
    return deepcopy(native_conjugate)


def _authored(design):
    return design.model_dump(mode="json", include=AUTHORING_FIELDS)


@pytest.mark.parametrize("resized", [False, True])
def test_constrained_move_matches_unchanged_legacy_algorithm_and_transport(design, monkeypatch, resized):
    if resized:
        design.find_strand("binder").domains[0].end_bp -= 2
    before = design.model_dump_json()
    patch = {"gizmo_move": _move(), "visible": False}
    candidate, effect = commands.evaluate("protein-attach-patch", design, _params(**patch))
    assert effect["protein_constraint"]["mode"] == "two_ball_joint"
    assert effect["changed_helix_ids"] == ["oh_helix"]
    assert candidate.protein_attachments[0].visible is False
    assert candidate.strands == design.strands and candidate.staple_groups == design.staple_groups
    assert design.model_dump_json() == before
    token = set_current_doc("owned-conjugate-native-motion-parity")
    try:
        monkeypatch.setattr(routes, "_native_conjugate_lifecycle_eligible", lambda *_a: False)
        state.load_design(deepcopy(design))
        response = routes.patch_protein_attachment("placement", routes.ProteinAttachPatchRequest(**patch))
        legacy = deepcopy(state.get_or_404())
    finally:
        state.close_session()
        reset_current_doc(token)
    assert effect["protein_constraint"] == response["protein_constraint"]
    assert _authored(candidate) == _authored(legacy)
    transported = m.Design.model_validate_json(design.model_dump_json())
    assert _authored(commands.build("protein-attach-patch", transported, _params(**patch))) == _authored(candidate)


def test_visibility_uses_no_geometry_or_mutable_asset_dependency(design, monkeypatch):
    from backend.core import design_geometry

    design.protein_assets = []
    monkeypatch.setattr(design_geometry, "_geometry_for_helices",
                        lambda *_a, **_kw: pytest.fail("Visibility generated geometry"))
    candidate, effect = commands.evaluate("protein-attach-patch", design, _params(visible=False))
    assert not candidate.protein_attachments[0].visible
    assert not effect["changed_helix_ids"] and effect["protein_constraint"] is None
    assert candidate.model_dump(include=AUTHORING_FIELDS - {"protein_attachments"}) == design.model_dump(
        include=AUTHORING_FIELDS - {"protein_attachments"})
    assert commands.build("protein-attach-patch", design, _params(visible=None, gizmo_move=None)) == design


def test_delete_uses_current_ownership_without_recovery_and_prunes_only_declared_membership(design):
    design.feature_log = []
    design.staple_groups.append(m.StapleGroup(id="empty", name="Keep empty", strand_ids=[]))
    design.staple_groups.append(m.StapleGroup(id="shared", name="Shared", strand_ids=["binder", "scaf"]))
    design.representation_overrides = [m.RepresentationOverride(id="placement-style", protein_attachment_ids=["placement"])]
    before = design.model_dump_json()
    candidate, effect = commands.evaluate("protein-attach-delete", design, _params())
    assert not candidate.protein_attachments and candidate.find_strand("binder") is None
    assert [(item.id, item.strand_ids) for item in candidate.staple_groups] == [("empty", []), ("shared", ["scaf"])]
    assert not candidate.representation_overrides
    assert candidate.helices == design.helices and candidate.overhangs == design.overhangs
    assert candidate.protein_assets == design.protein_assets
    assert candidate.cluster_transforms == design.cluster_transforms
    assert effect == {"protein_constraint": None, "changed_helix_ids": ["oh_helix"]}
    assert design.model_dump_json() == before
    assert commands.resources("protein-attach-delete", _params()) == {"sources": (), "imports": False}


def test_owned_delete_matches_legacy_delete_without_using_its_history_in_native_command(design, monkeypatch):
    candidate = commands.build("protein-attach-delete", design, _params())
    legacy_input = design.copy_with(feature_log=[m.SnapshotLogEntry(
        op_kind="protein-conjugate", label="Legacy ownership proof", design_snapshot_gz_b64="unused",
        params={"asset_id": "asset", "overhang_id": "oh_5p", "attachment_id": "placement", "binder_strand_id": "binder"})])
    token = set_current_doc("owned-conjugate-native-delete-parity")
    try:
        monkeypatch.setattr(routes, "_native_conjugate_lifecycle_eligible", lambda *_a: False)
        state.load_design(legacy_input)
        routes.delete_protein_attachment("placement")
        legacy = deepcopy(state.get_or_404())
    finally:
        state.close_session()
        reset_current_doc(token)
    assert _authored(candidate) == _authored(legacy)


@pytest.mark.parametrize("missing", ["asset", "overhang", "helix"])
def test_delete_can_remove_explicit_owned_binder_despite_missing_parent_resource(design, missing):
    if missing == "asset":
        design.protein_assets = []
    elif missing == "overhang":
        design.overhangs = []
    else:
        design.helices = [item for item in design.helices if item.id != "oh_helix"]
    candidate = commands.build("protein-attach-delete", design, _params())
    assert not candidate.protein_attachments and candidate.find_strand("binder") is None


@pytest.mark.parametrize("case", ["attachment", "binder", "wrong_binder", "duplicate_binder", "spliced_binder", "shared_binder", "overlap"])
def test_missing_or_ambiguous_ownership_does_not_guess_history_or_mutate(design, case):
    if case == "attachment":
        design.protein_attachments = []
    elif case == "binder":
        design.strands = [item for item in design.strands if item.id != "binder"]
    elif case == "wrong_binder":
        design.protein_attachments[0].binder_strand_id = "other"
    elif case == "duplicate_binder":
        design.strands.append(design.find_strand("binder"))
    elif case == "spliced_binder":
        design.find_strand("binder").domains.append(design.strands[0].domains[0])
    elif case == "shared_binder":
        design.protein_attachments.append(m.ProteinAttachment(id="other", asset_id="asset", target=m.ProteinTargetFree(), binder_strand_id="binder"))
    else:
        design.strands.append(design.find_strand("binder").model_copy(update={"id": "overlapping"}))
    before = design.model_dump_json()
    with pytest.raises(ReferenceResolutionError):
        commands.build("protein-attach-delete", design, _params())
    assert design.model_dump_json() == before


def _add_dependent(design, family, *, direction=None, bp=3):
    binder = design.find_strand("binder")
    domain = binder.domains[0]
    direction = direction or domain.direction
    half = m.HalfCrossover(helix_id=domain.helix_id, index=bp, strand=direction)
    other_half = m.HalfCrossover(helix_id="h0", index=bp, strand=direction)
    endpoint = m.JoinEndpoint(helix_id=domain.helix_id, bp_index=bp, direction=direction)
    other_endpoint = m.JoinEndpoint(helix_id="h0", bp_index=bp, direction=direction)
    if family == "extension":
        design.extensions = [m.StrandExtension(id="dependent", strand_id="binder", end="five_prime", sequence="TT")]
    elif family == "cluster":
        design.cluster_transforms.append(m.ClusterRigidTransform(id="dependent", domain_ids=[m.DomainRef(strand_id="binder", domain_index=0)]))
    elif family == "flexible_mark":
        design.flexible_segment_marks = [m.FlexibleSegmentMark(id="dependent", strand_id="binder", domain_index=0, bp_index=bp, direction=direction)]
    elif family == "nanoparticle":
        design.nanoparticles = [m.Nanoparticle(id="dependent", diameter_nm=5, biotin_dna=[m.BiotinDNA(strand_id="binder", helix_id=domain.helix_id, chain="A")])]
    elif family == "overhang":
        design.overhangs.append(m.OverhangSpec(id="dependent", strand_id="binder", helix_id=domain.helix_id))
    elif family == "crossover":
        design.crossovers = [m.Crossover(id="dependent", half_a=half, half_b=other_half)]
    elif family == "forced_ligation":
        design.forced_ligations = [m.ForcedLigation(id="dependent", three_prime_helix_id=domain.helix_id,
            three_prime_bp=bp, three_prime_direction=direction, five_prime_helix_id="h0", five_prime_bp=bp, five_prime_direction=direction)]
    elif family == "nucleotide_transform":
        design.nucleotide_transforms = [m.NucleotideTransform(id="dependent", kind="base", helix_id=domain.helix_id,
            bp_index=bp, direction=direction, copy_k=1)]
    elif family == "join_constraint":
        pair = m.JoinAttachment(cluster_id="source-cluster", source=endpoint, target=other_endpoint)
        design.cluster_join_constraints = [m.ClusterJoinConstraint(id="dependent", first=pair, second=pair, reach_nm=1)]
    elif family == "deformation":
        design.deformations = [m.DeformationOp(id="dependent", type="twist", plane_a_bp=0, plane_b_bp=7,
            target_ranges=[m.DeformationRange(helix_id=domain.helix_id, start_bp=bp, end_bp=bp, direction=direction)],
            params=m.TwistParams(kind="twist", total_degrees=0))]
    elif family == "routing_seed":
        design.strands[0].routing_seed = [m.Domain(helix_id=domain.helix_id, start_bp=bp, end_bp=bp, direction=direction)]
    elif family == "photoproduct":
        design.photoproduct_junctions = [m.PhotoproductJunction(id="dependent",
            base_key_1=f"{domain.helix_id}:{bp}:{direction.value}:1", base_key_2=f"h0:{bp}:FORWARD",
            bond_relaxation={"retained_report": True})]
    else:
        raise AssertionError(family)


@pytest.mark.parametrize("family", ["extension", "cluster", "flexible_mark", "nanoparticle", "overhang",
    "crossover", "forced_ligation", "nucleotide_transform", "join_constraint", "deformation", "routing_seed", "photoproduct"])
def test_delete_reports_external_typed_and_directional_residue_dependencies(design, family):
    _add_dependent(design, family)
    before = design.model_dump_json()
    with pytest.raises(commands.ConjugateOwnershipError) as error:
        commands.build("protein-attach-delete", design, _params())
    issue = error.value.as_issue()
    assert issue["references"] == [{"kind": "strand", "identity": "binder", "parameter_path": ["binder_strand_id"]}]
    assert issue["dependent_resources"][0]["identity"] == ("scaf" if family == "routing_seed" else "dependent")
    assert design.model_dump_json() == before


@pytest.mark.parametrize("family", ["crossover", "forced_ligation", "nucleotide_transform", "join_constraint", "deformation", "routing_seed", "photoproduct"])
@pytest.mark.parametrize("independent", ["opposite_direction", "outside_interval"])
def test_delete_preserves_independent_references_on_shared_helix(design, family, independent):
    direction = m.Direction.FORWARD if independent == "opposite_direction" else m.Direction.REVERSE
    _add_dependent(design, family, direction=direction, bp=3 if independent == "opposite_direction" else 99)
    before = _authored(design)
    candidate = commands.build("protein-attach-delete", design, _params())
    expected = {**before, "strands": [strand for strand in before["strands"] if strand["id"] != "binder"],
                "staple_groups": [], "protein_attachments": []}
    assert _authored(candidate) == expected


def test_unknown_legacy_photoproduct_references_remain_unverified(design):
    design.photoproduct_junctions = [m.PhotoproductJunction(id="legacy", t1_stable_id="unknown-one", t2_stable_id="unknown-two")]
    with pytest.raises(CommandContractError) as error:
        commands.build("protein-attach-delete", design, _params())
    assert error.value.status == "unverified" and error.value.code == "unsupported_conjugate_lifecycle"


def test_constrained_move_rejects_residue_constraints_before_geometry(design, monkeypatch):
    from backend.core import design_geometry

    _add_dependent(design, "nucleotide_transform")
    monkeypatch.setattr(design_geometry, "_geometry_for_helices",
                        lambda *_a, **_kw: pytest.fail("Constrained residue reached native geometry"))
    with pytest.raises(commands.ConjugateOwnershipError):
        commands.build("protein-attach-patch", design, _params(gizmo_move=_move()))


def test_missing_motion_geometry_has_structured_reference_issue(design, monkeypatch):
    from backend.core import design_geometry

    monkeypatch.setattr(design_geometry, "_geometry_for_helices", lambda *_a, **_kw: [])
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build("protein-attach-patch", design, _params(gizmo_move=_move()))
    assert error.value.code == "missing_reference"
    assert error.value.as_issue()["references"][0]["parameter_path"] == ["attachment_id"]


@pytest.mark.parametrize("change", [
    lambda p: p.pop("conjugation_version"), lambda p: p.update(conjugation_version=True),
    lambda p: p.update(binder_strand_id=""), lambda p: p.update(pose=[0] * 16),
    lambda p: p.update(conjugation_atom_serial=9), lambda p: p.update(handle_spacer_nt=0),
    lambda p: p.update(visible=1), lambda p: p.update(gizmo_move={**_move(), "rotation": [0, 0, 0, 0]}),
])
def test_lifecycle_contract_excludes_unsupported_pose_or_site_edits(change):
    params = _params(gizmo_move=_move())
    change(params)
    with pytest.raises(ValidationError):
        commands.parse_command("protein-attach-patch", params)
