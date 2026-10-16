"""Unbound thiol motion reuses native geometry with exact owned selectors."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.api import part_thiol_commands as graft_commands
from backend.api import part_thiol_patch_commands as commands
from backend.core import models as m
from backend.core.nanoparticle import replace_gold_nanosphere
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_history_proof import AUTHORING_FIELDS, ProofBudgetExceeded
from tests.test_part_thiol_commands import params as graft_params, source


def params(**changes):
    return {"_proof_version": 1, "nanoparticle_version": 1, "thiol_version": 1,
            "nanoparticle_id": "gold", "conjugation_ids": ["graft"], **changes}


def graft(attach_end="5p"):
    return graft_commands.build("nanoparticle-conjugate", source(), graft_params(attach_end=attach_end))


def move():
    return {"pivot": [2, -1, 3], "translation": [1, 3, -2], "rotation": [0, 0, .6, .8]}


def authored(design):
    return design.model_dump(mode="json", include=AUTHORING_FIELDS)


@pytest.mark.parametrize("attach_end", ["5p", "3p"])
@pytest.mark.parametrize("patch", [
    {"diameter_nm": 14}, {"gizmo_move": move()},
    {"pose": [1, 0, 0, 7, 0, 1, 0, -3, 0, 0, 1, 2, 0, 0, 0, 1]},
    {"diameter_nm": 12, "gizmo_move": move()},
])
def test_complete_authoring_matches_existing_particle_math_and_keeps_owned_identities(attach_end, patch):
    design = graft(attach_end)
    before = design.model_dump_json()
    expected = replace_gold_nanosphere(design, "gold", **patch)
    actual = commands.build("nanoparticle-patch", design, params(**patch))
    assert authored(actual) == authored(expected)
    assert actual.helices != design.helices
    assert actual.strands == design.strands
    assert actual.overhangs == design.overhangs
    assert actual.staple_groups == design.staple_groups
    assert actual.cluster_transforms == design.cluster_transforms
    assert actual.metadata == design.metadata
    assert [item.id for item in actual.helices] == [item.id for item in design.helices]
    assert [item.id for item in actual.nanoparticle_conjugations] == ["graft"]
    assert design.model_dump_json() == before
    transported = m.Design.model_validate_json(design.model_dump_json())
    assert authored(commands.build("nanoparticle-patch", transported, params(**patch))) == authored(actual)
    assert commands.resources("nanoparticle-patch", params(**patch)) == {"sources": (), "imports": False}


def test_repeated_native_patches_use_current_input_pose_and_keep_unrelated_particle():
    design = graft()
    unrelated = m.Nanoparticle(id="independent", diameter_nm=7)
    design.nanoparticles.append(unrelated)
    for patch in ({"gizmo_move": move()}, {"diameter_nm": 17}, {"gizmo_move": move()}):
        before = design
        design = commands.build("nanoparticle-patch", design, params(**patch))
        assert authored(design) == authored(replace_gold_nanosphere(before, "gold", **patch))
        assert design.nanoparticles[1] == unrelated
    assert commands.build("nanoparticle-patch", design, params(coating=None)) == replace_gold_nanosphere(design, "gold")


@pytest.mark.parametrize("missing,kind", [
    ("nanoparticles", "nanoparticle"), ("nanoparticle_conjugations", "nanoparticle_conjugation"),
    ("helices", "helix"), ("strands", "strand"), ("overhangs", "overhang"),
])
def test_missing_particle_or_owned_child_fails_before_geometry(missing, kind, monkeypatch):
    design = graft()
    setattr(design, missing, [])
    monkeypatch.setattr(commands, "replace_gold_nanosphere", lambda *_a, **_kw: pytest.fail("Missing ownership reached geometry"))
    before = design.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build("nanoparticle-patch", design, params(gizmo_move=move()))
    assert error.value.code == "missing_reference"
    issue = error.value.as_issue()["references"][0]
    assert issue["kind"] == kind
    assert issue["parameter_path"] == (["nanoparticle_id"] if kind == "nanoparticle" else ["conjugation_ids", 0])
    assert design.model_dump_json() == before


def test_exact_current_conjugation_selection_and_duplicate_owned_ids_are_required():
    design = graft()
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build("nanoparticle-patch", design, params(conjugation_ids=["other"], diameter_nm=12))
    assert error.value.code == "missing_reference"
    assert error.value.as_issue()["references"][0]["identity"] == "other"
    design.nanoparticle_conjugations.append(design.nanoparticle_conjugations[0].model_copy(update={"id": "extra"}))
    with pytest.raises(ReferenceResolutionError, match="exactly"):
        commands.build("nanoparticle-patch", design, params(diameter_nm=12))
    with pytest.raises(ReferenceResolutionError, match="shared"):
        commands.build("nanoparticle-patch", design, params(conjugation_ids=["graft", "extra"], diameter_nm=12))


def dependent(design, family):
    strand, helix, spec = design.strands[0], design.helices[0], design.overhangs[0]
    if family == "extension":
        design.extensions = [m.StrandExtension(strand_id=strand.id, end="five_prime", sequence="TT")]
    elif family == "strand":
        design.strands.append(strand.model_copy(update={"id": "dependent"}))
    elif family == "cluster":
        design.cluster_transforms.append(m.ClusterRigidTransform(id="dependent", helix_ids=[helix.id]))
    elif family == "photoproduct":
        design.photoproduct_junctions = [m.PhotoproductJunction(id="dependent",
            base_key_1=f"{helix.id}:0:FORWARD", base_key_2=f"{helix.id}:1:FORWARD")]
    elif family == "nucleotide_transform":
        design.nucleotide_transforms = [m.NucleotideTransform(id="dependent", kind="base",
            helix_id=helix.id, bp_index=0, direction=m.Direction.FORWARD, copy_k=1)]
    elif family == "forced_ligation":
        design.forced_ligations = [m.ForcedLigation(id="dependent", three_prime_helix_id=helix.id,
            three_prime_bp=7, three_prime_direction=m.Direction.FORWARD,
            five_prime_helix_id=helix.id, five_prime_bp=0, five_prime_direction=m.Direction.REVERSE)]
    elif family == "protein":
        design.protein_attachments = [m.ProteinAttachment(id="dependent", asset_id="asset",
            target=m.ProteinTargetDesign(overhang_id=spec.id), conjugation_atom_serial=1)]
    elif family == "bound":
        design.nanoparticle_conjugations[0].surface_strands[0].bound_overhang_id = "dependent"
    elif family == "connection":
        design.nanoparticle_connection_versions = [m.NanoparticleConnectionVersion(nanoparticle_id="gold",
            strand_id=strand.id, overhang_id=spec.id, duplex_id="dependent")]
    else:
        raise AssertionError(family)


@pytest.mark.parametrize("family", ["extension", "strand", "cluster", "photoproduct", "nucleotide_transform",
                                    "forced_ligation", "protein", "bound", "connection"])
def test_motion_refuses_external_consumers_or_coupled_ownership_before_geometry(family, monkeypatch):
    design = graft()
    dependent(design, family)
    if family not in {"bound", "connection"}:
        assert commands.native_route_eligible(design, "gold")
    monkeypatch.setattr(commands, "replace_gold_nanosphere", lambda *_a, **_kw: pytest.fail("Dependent reached geometry"))
    before = design.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build("nanoparticle-patch", design, params(gizmo_move=move()))
    assert error.value.code == "invalid_selection"
    assert design.model_dump_json() == before


@pytest.mark.parametrize("change", [
    {"thiol_version": True}, {"nanoparticle_version": 2}, {"quantum_dot_version": 1},
    {"conjugation_ids": []}, {"conjugation_ids": ["graft", "graft"]},
    {"pose": [0] * 15}, {"diameter_nm": float("inf")}, {"coating": {}},
    {"gizmo_move": {**move(), "rotation": [0, 0, 0, 0]}}, {"source": {}},
])
def test_patch_schema_is_strict_and_contains_no_output_geometry(change):
    with pytest.raises(ValidationError):
        commands.parse_command("nanoparticle-patch", params(**change))


def test_native_route_separates_unsupported_opaque_and_coupled_inputs_from_missing_refs():
    design = graft()
    assert commands.native_route_eligible(design, "gold")
    assert not commands.native_route_eligible(source(), "gold")
    for family in ("bound", "connection"):
        changed = deepcopy(design)
        dependent(changed, family)
        assert not commands.native_route_eligible(changed, "gold")
    changed = deepcopy(design)
    changed.overhangs[0].strand_anim_setup = {"binder_strand_id": "opaque"}
    assert not commands.native_route_eligible(changed, "gold")
    with pytest.raises(CommandContractError) as error:
        commands.build("nanoparticle-patch", changed, params(diameter_nm=12))
    assert error.value.status == "unverified"
    design.overhangs = []
    assert commands.native_route_eligible(design, "gold")


def test_current_owned_base_budget_is_checked_without_expanding_nucleotides(monkeypatch):
    design = graft()
    for helix, strand, spec in zip(design.helices, design.strands, design.overhangs):
        helix.length_bp = 25_000
        strand.domains[0].end_bp = 24_999
        strand.sequence = spec.sequence = "N" * 25_000
        spec.sub_domains[0].length_bp = 25_000
    assert commands.native_route_eligible(design, "gold")
    design.helices[0].length_bp += 1
    design.strands[0].domains[0].end_bp += 1
    design.strands[0].sequence += "N"
    design.overhangs[0].sequence += "N"
    design.overhangs[0].sub_domains[0].length_bp += 1
    monkeypatch.setattr(commands, "replace_gold_nanosphere", lambda *_a, **_kw: pytest.fail("Oversize source reached geometry"))
    assert not commands.native_route_eligible(design, "gold")
    with pytest.raises(ProofBudgetExceeded):
        commands.build("nanoparticle-patch", design, params(gizmo_move=move()))


def test_live_record_resolves_current_ownership_inside_lock(monkeypatch):
    from backend.api import state

    design = graft()
    design.nanoparticle_conjugations[0].id = "current-graft"
    recorded = {}

    def transaction(kind, label, inputs, mutate):
        candidate = mutate(design)
        recorded.update(inputs)
        return candidate, None, None

    monkeypatch.setattr(state, "mutate_with_feature_log", transaction)
    updated, _, _ = commands.record("nanoparticle-patch", "Move particle", {
        "nanoparticle_id": "gold", "gizmo_move": move()})
    assert recorded["conjugation_ids"] == ["current-graft"]
    assert authored(updated) == authored(replace_gold_nanosphere(design, "gold", gizmo_move=move()))
    assert "helices" not in recorded and "surface_strands" not in recorded
