"""Native conjugation reproduces the established gate and owns exact outputs."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.api import part_protein_conjugation_commands as commands
from backend.api import routes_protein, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.core.cluster_autodetect import with_default_cluster
from backend.core.models import (
    Design, Duplex, DuplexEnd, OverhangConnection, ProteinAttachment,
    ProteinTargetDesign, ProteinTargetFree, SnapshotLogEntry, StapleGroup,
)
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_history_proof import AUTHORING_FIELDS, ProofBudgetExceeded
from backend.core.protein import parse_protein_pdb
from tests.test_protein import _SYNTH_PDB, _design_with_overhang


def _params(**changes):
    return {
        "_proof_version": 1, "protein_version": 1, "conjugation_version": 1,
        "asset_id": "asset", "overhang_id": "oh_5p", "conjugation_atom_serial": 9,
        "azide_end": "5p", "attachment_id": "placement", "binder_strand_id": "binder",
        "group_id": "binder-group", **changes,
    }


@pytest.fixture
def design():
    asset = parse_protein_pdb(_SYNTH_PDB, name="synth")
    asset.id = "asset"
    base = _design_with_overhang().copy_with(protein_assets=[asset])
    base.overhangs[0].sequence = "ACGTACGT"
    return with_default_cluster(base, identity_factory=lambda *_a: "source-cluster")


def _authored(design):
    return design.model_dump(mode="json", include=AUTHORING_FIELDS)


@pytest.mark.parametrize("azide_end,convert", [("5p", False), ("3p", True)])
def test_complete_authoring_matches_established_native_route_and_transport(design, azide_end, convert, monkeypatch):
    params = _params(azide_end=azide_end)
    if convert:
        params["source_attachment_id"] = "placement"
        design.protein_attachments = [ProteinAttachment(
            id="placement", asset_id="asset", target=ProteinTargetFree(), conjugation_atom_serial=9)]
    before = design.model_dump_json()
    candidate, report = commands.evaluate("protein-conjugate", design, params)
    assert report["valid"], report
    assert report["failed_metrics"] == []
    assert candidate.find_strand("binder").name == "synth-1:S1"
    assert candidate.staple_groups[-1].id == "binder-group"
    assert candidate.staple_groups[-1].strand_ids == ["binder"]
    assert candidate.protein_attachments[-1].binder_strand_id == "binder"
    assert candidate.protein_attachments[-1].handle_sequence == candidate.find_strand("binder").sequence
    assert candidate.protein_assets == design.protein_assets
    assert len(candidate.protein_attachments) == 1
    assert design.model_dump_json() == before

    # Compare with the pre-existing route, normalizing only its three random
    # output identities. Its molecular algorithms and validation stay the oracle.
    token = set_current_doc("native-conjugation-command-parity")
    try:
        monkeypatch.setattr(routes_protein, "_native_conjugation_eligible", lambda *_a: False)
        state.load_design(deepcopy(design))
        result = routes_protein.conjugate_protein_to_overhang(routes_protein.ProteinConjugateRequest(
            asset_id="asset", overhang_id="oh_5p", conjugation_atom_serial=9,
            azide_end=azide_end, source_attachment_id=params.get("source_attachment_id")))
        assert result["element_validation"]["valid"], result
        native = deepcopy(state.get_or_404())
    finally:
        state.close_session()
        reset_current_doc(token)
    native.strands[-1].id = "binder"
    native.staple_groups[-1].id = "binder-group"
    native.staple_groups[-1].strand_ids = ["binder"]
    native.protein_attachments[-1].id = "placement"
    native.protein_attachments[-1].binder_strand_id = "binder"
    assert _authored(candidate) == _authored(native)
    transported = Design.model_validate_json(design.model_dump_json())
    repeated = commands.build("protein-conjugate", transported, params)
    assert _authored(repeated) == _authored(candidate)
    assert commands.resources("protein-conjugate", params) == {"sources": (), "imports": False}


def test_conversion_keeps_identity_and_legacy_selected_subsequence_order(design):
    design.protein_attachments = [ProteinAttachment(
        id=identity, asset_id="asset", target=ProteinTargetFree(), conjugation_atom_serial=9)
        for identity in ("placement", "independent")]
    candidate = commands.build("protein-conjugate", design, _params(source_attachment_id="placement"))
    assert [item.id for item in candidate.protein_attachments] == ["independent", "placement"]
    assert candidate.protein_attachments[0] == design.protein_attachments[1]


def test_recovery_payloads_do_not_supply_native_conjugation_output(design):
    expected = commands.build("protein-conjugate", design, _params())
    design.feature_log = [SnapshotLogEntry(op_kind="protein-attach", label="Poisoned recovery",
        params={"asset_id": "asset"}, design_snapshot_gz_b64="not a snapshot",
        post_state_gz_b64="not an output")]
    actual = commands.build("protein-conjugate", design, _params())
    assert _authored(actual) == _authored(expected)


def test_sparse_source_default_cluster_is_authored_deterministically(design):
    design.cluster_transforms = []
    first = commands.build("protein-conjugate", design, _params())
    second = commands.build("protein-conjugate", design, _params())
    assert len(first.cluster_transforms) == 1
    assert first.cluster_transforms[0].is_default and first.cluster_transforms[0].auto_created
    assert first.cluster_transforms == second.cluster_transforms
    assert not design.cluster_transforms


@pytest.mark.parametrize("case,kind,path", [
    ("asset", "protein_asset", ["asset_id"]),
    ("atom", "protein_atom", ["conjugation_atom_serial"]),
    ("overhang", "overhang", ["overhang_id"]),
    ("helix", "helix", ["overhang_id"]),
    ("strand", "strand", ["overhang_id"]),
    ("domain", "overhang", ["overhang_id"]),
    ("source", "protein_attachment", ["source_attachment_id"]),
])
def test_missing_references_fail_before_native_construction(design, monkeypatch, case, kind, path):
    from backend.core import lattice

    params = _params()
    if case == "asset":
        design.protein_assets = []
    elif case == "atom":
        params["conjugation_atom_serial"] = 999
    elif case == "overhang":
        design.overhangs = []
    elif case == "helix":
        design.helices = [item for item in design.helices if item.id != "oh_helix"]
    elif case == "strand":
        design.strands = [item for item in design.strands if item.id != "oh_strand"]
    elif case == "domain":
        design.find_strand("oh_strand").domains[0].overhang_id = None
    else:
        params["source_attachment_id"] = "placement"
    monkeypatch.setattr(lattice, "make_binder_for_overhang",
                        lambda *_a, **_kw: pytest.fail("Missing references reached binder construction"))
    before = design.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build("protein-conjugate", design, params)
    assert error.value.code == "missing_reference"
    assert error.value.as_issue()["references"][0]["kind"] == kind
    assert error.value.as_issue()["references"][0]["parameter_path"] == path
    assert design.model_dump_json() == before


@pytest.mark.parametrize("case", ["duplicate_spec", "duplicate_domain", "wrong_owner", "bound_target",
                                  "attachment_id", "binder_id", "group_id", "dangling_binder"])
def test_ambiguous_or_reused_ownership_fails_before_geometry(design, monkeypatch, case):
    from backend.core import design_geometry

    if case == "duplicate_spec":
        design.overhangs *= 2
    elif case == "duplicate_domain":
        design.find_strand("oh_strand").domains *= 2
    elif case == "wrong_owner":
        design.overhangs[0].strand_id = design.strands[0].id
    elif case == "bound_target":
        design.strands[0].domains[0].binds_overhang_id = "oh_5p"
    elif case == "attachment_id":
        design.protein_attachments = [ProteinAttachment(id="placement", asset_id="asset", target=ProteinTargetFree())]
    elif case == "binder_id":
        design.strands[0].id = "binder"
    elif case == "group_id":
        design.staple_groups = [StapleGroup(id="binder-group", name="Existing", strand_ids=[])]
    else:
        design.staple_groups = [StapleGroup(id="existing", name="Dangling", strand_ids=["binder"])]
    monkeypatch.setattr(design_geometry, "_geometry_for_helices",
                        lambda *_a: pytest.fail("Ambiguous ownership reached geometry"))
    before = design.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build("protein-conjugate", design, _params())
    assert error.value.code == "invalid_selection"
    assert design.model_dump_json() == before


@pytest.mark.parametrize("ownership", ["other_asset", "overhang", "binder", "azide"])
def test_only_unowned_free_placement_can_be_converted(design, ownership):
    source = ProteinAttachment(id="placement", asset_id="asset", target=ProteinTargetFree())
    if ownership == "other_asset":
        source.asset_id = "other-asset"
    elif ownership == "overhang":
        source.target = ProteinTargetDesign(overhang_id="oh_5p")
    elif ownership == "binder":
        source.binder_strand_id = "old-binder"
    else:
        source.azide_end = "5p"
    design.protein_attachments = [source]
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build("protein-conjugate", design, _params(source_attachment_id="placement"))
    assert error.value.as_issue()["references"][0]["parameter_path"] == ["source_attachment_id"]


def test_nonreactive_atom_is_invalid_for_conjugation_before_building_binder(design, monkeypatch):
    from backend.core import lattice

    monkeypatch.setattr(lattice, "make_binder_for_overhang",
                        lambda *_a, **_kw: pytest.fail("Invalid reactive site reached binder construction"))
    with pytest.raises(ReferenceResolutionError, match="reactive site") as error:
        commands.build("protein-conjugate", design, _params(conjugation_atom_serial=2))
    assert error.value.as_issue()["references"][0]["parameter_path"] == ["conjugation_atom_serial"]


def test_missing_anchor_geometry_never_uses_native_fallback_as_proof(design, monkeypatch):
    from backend.core import design_geometry

    monkeypatch.setattr(design_geometry, "_geometry_for_helices", lambda *_a: [])
    before = design.model_dump_json()
    with pytest.raises(ReferenceResolutionError, match="anchor geometry"):
        commands.build("protein-conjugate", design, _params())
    assert design.model_dump_json() == before


def test_native_element_validation_is_a_commit_gate(design):
    design.overhangs[0].sequence = None
    before = design.model_dump_json()
    with pytest.raises(commands.ConjugationValidationError) as error:
        commands.build("protein-conjugate", design, _params())
    assert error.value.status == "failed"
    assert error.value.code == "element_validation_failed"
    assert "sequence_fidelity" in error.value.report["failed_metrics"]
    assert not error.value.as_issue()["element_validation"]["valid"]
    assert design.model_dump_json() == before


def test_coupled_target_ownership_requires_separate_contract(design):
    design.duplexes = [Duplex(id="coupled", created_at=0,
        left=DuplexEnd(overhang_id="oh_5p", start_bp=0, end_bp=7),
        right=DuplexEnd(overhang_id="other-overhang", start_bp=7, end_bp=0))]
    with pytest.raises(ReferenceResolutionError, match="coupled ownership"):
        commands.build("protein-conjugate", design, _params())


def test_linker_source_remains_explicitly_unverified(design):
    design.overhang_connections = [OverhangConnection(id="linker", overhang_a_id="a", overhang_b_id="b",
        overhang_a_attach="root", overhang_b_attach="root", linker_type="ds", length_value=8, length_unit="bp")]
    with pytest.raises(CommandContractError) as error:
        commands.build("protein-conjugate", design, _params())
    assert error.value.status == "unverified"
    assert error.value.code == "unsupported_conjugation_source"


@pytest.mark.parametrize("case", ["protein", "helix", "sparse_domain"])
def test_allocation_admission_precedes_native_geometry(design, monkeypatch, case):
    from backend.core import design_geometry

    if case == "protein":
        design.protein_assets[0].atoms.extend([design.protein_assets[0].atoms[0]] * 1000)
    elif case == "helix":
        design.helices[0].length_bp = 50_001
    else:
        design.strands[0].domains[0].end_bp = 50_001
    monkeypatch.setattr(design_geometry, "_geometry_for_helices",
                        lambda *_a: pytest.fail("Oversized source reached geometry"))
    with pytest.raises(ProofBudgetExceeded):
        commands.build("protein-conjugate", design, _params())


def test_admission_includes_the_prospective_binder_domain(design, monkeypatch):
    from backend.core import lattice

    # An imported draft can have overlapping domains. Domain traversal needs
    # its own bound even when the emitted helix span is much smaller.
    design.strands[0].domains *= 10
    occupied = sum(abs(domain.end_bp - domain.start_bp) + 1
                   for strand in design.strands for domain in strand.domains)
    target = design.find_strand("oh_strand").domains[0]
    extra = abs(target.end_bp - target.start_bp) + 1
    monkeypatch.setattr(commands, "MAX_GEOMETRY_BASES", occupied + extra - 1)
    monkeypatch.setattr(lattice, "make_binder_for_overhang",
                        lambda *_a, **_kw: pytest.fail("Prospective overflow reached binder construction"))
    assert not commands.native_route_eligible(design, "asset", "oh_5p")
    with pytest.raises(ProofBudgetExceeded):
        commands.build("protein-conjugate", design, _params())


@pytest.mark.parametrize("change", [
    lambda p: p.pop("conjugation_version"),
    lambda p: p.update(conjugation_version=True),
    lambda p: p.update(protein_version=2),
    lambda p: p.update(azide_end="other"),
    lambda p: p.update(conjugation_atom_serial=None),
    lambda p: p.update(source_attachment_id="different-placement"),
    lambda p: p.update(pose=[0] * 16),
    lambda p: p.update(binder={}),
    lambda p: p.update(conjugation_chemistry="cys"),
    lambda p: p.update(parsed_asset={}),
    lambda p: p.update(operation_id=[]),
])
def test_contract_only_accepts_reference_choices_and_stable_identities(change):
    params = _params()
    change(params)
    with pytest.raises(ValidationError):
        commands.parse_command("protein-conjugate", params)
