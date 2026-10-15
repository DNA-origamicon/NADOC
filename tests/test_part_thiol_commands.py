"""Thiol recipes preserve native geometry and guard exact child ownership."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.api import part_thiol_commands as commands
from backend.core.cluster_autodetect import with_default_cluster
from backend.core.conjugate_strands import assign_conjugate_group
from backend.core.feature_identity import identity_factory
from backend.core.models import (
    ClusterRigidTransform, Design, DomainRef, NanoparticleConnectionVersion,
    OverhangSpec, StapleGroup, StrandExtension,
)
from backend.core.nanoparticle import build_thiol_conjugation, create_gold_nanosphere
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_proof import AUTHORING_FIELDS


SEED = "a4d19d22-111c-4317-b008-76efe3a333ad"
NEXT_SEED = "bbc85cc9-52a1-4258-b6e3-e1353b6a892b"


def params(**changes):
    return {"_proof_version": 1, "thiol_version": 1, "history_seed": SEED,
            "nanoparticle_id": "gold", "replace_conjugation_ids": [], "conjugation_id": "graft",
            "scheme": "direct_thiol", "sequence": "ACGTACGT", "count": 2,
            "attach_end": "5p", "spacer_nm": None, "seed": 17, **changes}


def source():
    return Design(nanoparticles=[create_gold_nanosphere(10, nanoparticle_id="gold")],
                  metadata={"unrelated": "gold"}, staple_groups=[StapleGroup(id="empty", name="Retained")])


def deletion(**changes):
    return {"_proof_version": 1, "thiol_version": 1, "history_seed": NEXT_SEED,
            "nanoparticle_id": "gold", "replace_conjugation_ids": ["graft"], **changes}


def authored(design):
    return design.model_dump(mode="json", include=AUTHORING_FIELDS)


@pytest.mark.parametrize("scheme", ["direct_thiol", "alkyl_thiol", "peg_thiol", "peg_backfill"])
@pytest.mark.parametrize("attach_end", ["5p", "3p"])
def test_complete_authoring_matches_native_builder_and_survives_transport(scheme, attach_end):
    before = source()
    original = before.model_dump_json()
    inputs = params(scheme=scheme, attach_end=attach_end)
    factory = identity_factory(SEED)
    conjugation, helices, strands = build_thiol_conjugation(before.nanoparticles[0],
        scheme=scheme, sequence=inputs["sequence"], count=2, attach_end=attach_end, seed=17,
        conjugation_id="graft", identity_factory=factory)
    strands, group = assign_conjugate_group(before, strands, prefix="NP", fallback="NP",
                                            group_id="conjugate-" + factory("thiol-group", []))
    overhangs = [OverhangSpec(id=record.overhang_id, helix_id=record.helix_id, strand_id=strand.id,
        sequence=strand.sequence, label=strand.name, auxiliary_endpoint=True)
        for record, strand in zip(conjugation.surface_strands, strands)]
    expected = with_default_cluster(before.copy_with(helices=helices, strands=strands, overhangs=overhangs,
        nanoparticle_conjugations=[conjugation], staple_groups=[*before.staple_groups, group]),
        identity_factory=lambda *_: factory("thiol-default-cluster", []))
    actual = commands.build("nanoparticle-conjugate", before, inputs)
    assert authored(actual) == authored(expected)
    assert before.model_dump_json() == original
    assert all(helix.id.startswith("__np__") for helix in actual.helices)
    assert all(strand.name == f"NP-1:S{i}" for i, strand in enumerate(actual.strands, 1))
    transported = Design.model_validate_json(before.model_dump_json())
    assert authored(commands.build("nanoparticle-conjugate", transported, inputs)) == authored(actual)
    assert commands.resources("nanoparticle-conjugate", inputs) == {"sources": (), "imports": False}


def test_native_identity_parameters_are_optional_and_do_not_change_geometry():
    particle = source().nanoparticles[0]
    settings = {"scheme": "peg_thiol", "sequence": "ACGT", "count": 3, "seed": 3}
    legacy = build_thiol_conjugation(particle, **settings)
    native = build_thiol_conjugation(particle, **settings, identity_factory=identity_factory(SEED), conjugation_id="graft")
    assert legacy[0].id != native[0].id
    for old, new in zip(legacy[1], native[1]):
        assert old.model_dump(exclude={"id"}) == new.model_dump(exclude={"id"})
    for old, new in zip(legacy[0].surface_strands, native[0].surface_strands):
        assert old.model_dump(exclude={"helix_id", "strand_id", "overhang_id"}) == new.model_dump(
            exclude={"helix_id", "strand_id", "overhang_id"})


def test_count_sequence_and_distribution_edits_preserve_surviving_output_ids():
    first = commands.build("nanoparticle-conjugate", source(), params())
    changed = commands.build("nanoparticle-conjugate", source(), params(count=3, sequence="TTTT", seed=19))
    assert [item.id for item in first.helices] == [item.id for item in changed.helices[:2]]
    assert [item.id for item in first.strands] == [item.id for item in changed.strands[:2]]
    assert [item.id for item in first.overhangs] == [item.id for item in changed.overhangs[:2]]
    assert first.cluster_transforms[0].id == changed.cluster_transforms[0].id
    assert first.staple_groups[-1].id == changed.staple_groups[-1].id
    assert first.helices[0].axis_start != changed.helices[0].axis_start
    assert changed.helices[0].length_bp == 4


def test_replacement_and_delete_prune_only_owned_children_preserving_unrelated_groups_and_pose():
    before = commands.build("nanoparticle-conjugate", source(), params())
    before.cluster_transforms[0].translation = [1, 2, 3]
    snapshot = before.model_dump_json()
    replacement = commands.build("nanoparticle-conjugate", before,
        params(history_seed=NEXT_SEED, conjugation_id="replacement", replace_conjugation_ids=["graft"], count=3))
    assert {item.id for item in before.strands}.isdisjoint(item.id for item in replacement.strands)
    assert replacement.staple_groups[0] == before.staple_groups[0]
    assert replacement.staple_groups[-1].name == "NP-1"
    assert replacement.cluster_transforms[0].translation == [1, 2, 3]
    assert replacement.metadata == before.metadata
    assert before.model_dump_json() == snapshot
    deleted = commands.build("nanoparticle-conjugation-delete", before, deletion())
    assert not deleted.helices and not deleted.strands and not deleted.overhangs
    assert not deleted.nanoparticle_conjugations
    assert deleted.nanoparticles == before.nanoparticles
    assert deleted.staple_groups == before.staple_groups[:1]
    assert deleted.cluster_transforms[0].helix_ids == []
    assert deleted.cluster_transforms[0].translation == [1, 2, 3]


@pytest.mark.parametrize("case", ["particle", "conjugation", "helix", "strand", "overhang"])
def test_missing_target_and_owned_child_diagnostics(case):
    design = commands.build("nanoparticle-conjugate", source(), params())
    field = {"particle": "nanoparticles", "conjugation": "nanoparticle_conjugations",
             "helix": "helices", "strand": "strands", "overhang": "overhangs"}[case]
    setattr(design, field, [])
    snapshot = design.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build("nanoparticle-conjugation-delete", design, deletion())
    assert error.value.code == "missing_reference"
    reference = error.value.as_issue()["references"][0]
    assert reference["kind"] == {"particle": "nanoparticle", "conjugation": "nanoparticle_conjugation"}.get(case, case)
    assert reference["parameter_path"] == (["nanoparticle_id"] if case == "particle" else ["replace_conjugation_ids", 0])
    assert design.model_dump_json() == snapshot


@pytest.mark.parametrize("consumer", ["extension", "strand", "explicit_cluster", "domain_cluster", "connection", "bound", "shared"])
def test_incoming_consumers_or_shared_ownership_block_destructive_native_command(consumer):
    design = commands.build("nanoparticle-conjugate", source(), params())
    strand, helix, spec = design.strands[0], design.helices[0], design.overhangs[0]
    if consumer == "extension":
        design.extensions = [StrandExtension(strand_id=strand.id, end="five_prime", sequence="TT")]
    elif consumer == "strand":
        design.strands.append(strand.model_copy(update={"id": "outside"}))
    elif consumer == "explicit_cluster":
        design.cluster_transforms.append(ClusterRigidTransform(id="outside", helix_ids=[helix.id]))
    elif consumer == "domain_cluster":
        design.cluster_transforms[0].domain_ids = [DomainRef(strand_id=strand.id, domain_index=0)]
    elif consumer == "connection":
        design.nanoparticle_connection_versions = [NanoparticleConnectionVersion(
            nanoparticle_id="gold", strand_id=strand.id, overhang_id=spec.id, duplex_id="outside")]
    elif consumer == "bound":
        design.nanoparticle_conjugations[0].surface_strands[0].bound_overhang_id = "outside"
    else:
        design.nanoparticle_conjugations[0].surface_strands[1] = deepcopy(design.nanoparticle_conjugations[0].surface_strands[0])
    snapshot = design.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build("nanoparticle-conjugation-delete", design, deletion())
    assert error.value.code == "invalid_selection"
    assert design.model_dump_json() == snapshot


@pytest.mark.parametrize("change", [
    {"thiol_version": True}, {"thiol_version": 2}, {"count": True}, {"count": 129},
    {"count": 128, "sequence": "A" * 500}, {"sequence": "AUGC"}, {"history_seed": "unknown"},
    {"spacer_nm": float("nan")}, {"seed": 2**63}, {"saved_helices": []},
    {"replace_conjugation_ids": ["graft", "graft"]},
])
def test_recipe_schema_is_strict_and_bounded(change):
    with pytest.raises(ValidationError):
        commands.parse_command("nanoparticle-conjugate", params(**change))


def test_native_route_bound_does_not_silently_reduce_supported_legacy_count():
    assert commands.native_route_eligible(source(), "gold", count=128, sequence="ACGT")
    assert not commands.native_route_eligible(source(), "gold", count=129, sequence="ACGT")
    assert not commands.native_route_eligible(source(), "gold", count=128, sequence="A" * 500)


def test_existing_output_id_or_dangling_consumer_cannot_be_claimed():
    original = commands.build("nanoparticle-conjugate", source(), params())
    with pytest.raises(ReferenceResolutionError, match="already exists"):
        commands.build("nanoparticle-conjugate", original, params(replace_conjugation_ids=["graft"]))
    dangling = source().copy_with(extensions=[StrandExtension(
        strand_id=original.strands[0].id, end="five_prime", sequence="TT")])
    with pytest.raises(ReferenceResolutionError, match="incoming reference"):
        commands.build("nanoparticle-conjugate", dangling, params())


def test_live_adapter_captures_current_ownership_and_pose_inside_transaction(monkeypatch):
    from backend.api import state
    from backend.core.nanoparticle import replace_gold_nanosphere

    locked = commands.build("nanoparticle-conjugate", source(), params())
    locked = replace_gold_nanosphere(locked, "gold", diameter_nm=14)
    recorded = {}

    def transaction(kind, label, inputs, mutate):
        candidate = mutate(locked)
        recorded.update(inputs)
        return candidate, None, None

    monkeypatch.setattr(state, "mutate_with_feature_log", transaction)
    created, _, _ = commands.record("nanoparticle-conjugate", "Replace graft", {
        "nanoparticle_id": "gold", "scheme": "direct_thiol", "sequence": "ACGT",
        "count": 1, "attach_end": "5p", "spacer_nm": None, "seed": 17})
    assert recorded["replace_conjugation_ids"] == ["graft"]
    assert created.nanoparticle_conjugations[0].id == recorded["conjugation_id"]
    assert created.nanoparticles[0].diameter_nm == 14
    assert authored(created) == authored(commands.build("nanoparticle-conjugate", locked, recorded))
    assert "helices" not in recorded and "surface_strands" not in recorded
