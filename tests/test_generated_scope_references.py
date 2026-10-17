"""Typed scope identity, closure, compatibility and authored-text regressions."""

import pytest

from backend.api.generated_native_scope import execute, merge_changes, namespaced
from backend.core.models import (
    ClusterRigidTransform, Crossover, Design, Direction, Domain, HalfCrossover,
    Helix, LatticeFrame, Nanoparticle, OverhangConnection, OverhangSpec,
    PhotoproductJunction, ProteinAsset, ProteinAttachment, Strand, SubDomain, Vec3,
)
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_scope_references import (
    SCHEMAS, namespace_design, namespace_mapping, remap_design,
)


GROUP = "00000000-0000-0000-0000-000000000002"


def helix(identity, **changes):
    return Helix(id=identity, length_bp=10, axis_start=Vec3(x=0, y=0, z=0),
                 axis_end=Vec3(x=0, y=0, z=3), **changes)


def strand(identity, helix_id):
    return Strand(id=identity, domains=[Domain(
        helix_id=helix_id, start_bp=0, end_bp=2, direction=Direction.FORWARD,
    )])


def scoped(source, builder, inputs=(), version=2):
    scope = {"group_id": GROUP, "input_ids": list(inputs)}
    if version is not None:
        scope["version"] = version
    return execute("test", source, {"_generated_scope": scope},
                   lambda kind, local, params: builder(local))


def test_schema_inventory_requires_explicit_classification_of_new_fields():
    for model, schema in SCHEMAS.items():
        assert set(model.model_fields) == schema.fields, model.__name__


def test_version_two_preserves_text_equal_to_object_identity():
    source = Design()
    result = scoped(source, lambda local: local.copy_with(helices=[helix("raw", label="raw")]))
    assert result.helices[0].id == namespaced("raw", GROUP)
    assert result.helices[0].label == "raw"
    assert not source.helices


@pytest.mark.parametrize("version", [None, 1])
def test_unsafe_old_scope_requires_explicit_upgrade_without_mutating_source(version):
    source = Design()
    before = source.model_dump_json()
    with pytest.raises(NotImplementedError, match="explicit version-2"):
        scoped(source, lambda local: local.copy_with(helices=[helix("raw", label="raw")]), version=version)
    assert source.model_dump_json() == before


def test_safe_persisted_unversioned_scope_still_replays():
    result = scoped(Design(), lambda local: local.copy_with(helices=[helix("raw", label="Human label")]), version=None)
    result = scoped(result, lambda local: local.copy_with(helices=[
        local.helices[0].model_copy(update={"length_bp": 20})
    ]), version=None)
    assert result.helices[0].id == namespaced("raw", GROUP)
    assert result.helices[0].length_bp == 20
    assert result.helices[0].label == "Human label"


def test_equal_text_ids_in_distinct_resource_families_are_independent():
    generated = namespaced("raw", GROUP)
    source = Design(helices=[helix(generated)], strands=[strand("raw", generated)])
    result = scoped(source, lambda local: local.copy_with(helices=[
        local.helices[0].model_copy(update={"length_bp": 20})
    ]), inputs=["raw"])
    assert result.helices[0].id == generated
    assert result.strands[0].id == "raw"
    assert result.strands[0].domains[0].helix_id == generated


def overhang_source():
    return Design(helices=[helix("h")], strands=[strand("s", "h")], overhangs=[
        OverhangSpec(id="oh", helix_id="h", strand_id="s", sub_domains=[
            SubDomain(id="sub", length_bp=3),
        ]),
    ])


def test_nested_reference_requires_explicit_top_level_owner():
    source = overhang_source()
    with pytest.raises(ReferenceResolutionError, match="top-level owner") as caught:
        scoped(source, lambda local: pytest.fail("Incomplete scope reached native builder"), ["sub"])
    assert caught.value.as_issue()["references"][0]["identity"] == "oh"


def test_retaining_owner_preserves_nested_ids_and_requires_reference_closure():
    source = overhang_source()
    with pytest.raises(ReferenceResolutionError) as caught:
        scoped(source, lambda local: local, ["oh", "s"])
    assert caught.value.as_issue()["references"][0]["identity"] == "h"
    assert scoped(source, lambda local: local, ["oh", "s", "h"]) == source


def test_frame_and_parent_cluster_closure_is_checked_before_builder():
    source = Design(
        helices=[helix("h", grid_pos=(0, 0), lattice_frame_id="f")],
        lattice_frames=[LatticeFrame(id="f", placement_cluster_id="c")],
        cluster_transforms=[
            ClusterRigidTransform(id="c", helix_ids=["h"], parent_cluster_id="parent"),
            ClusterRigidTransform(id="parent"),
        ],
    )
    with pytest.raises(ReferenceResolutionError) as caught:
        scoped(source, lambda local: pytest.fail("Missing parent reached builder"), ["h", "f", "c"])
    assert caught.value.as_issue()["references"][0]["identity"] == "parent"
    assert scoped(source, lambda local: local, ["h", "f", "c", "parent"]) == source


def linker_source():
    source = overhang_source()
    second = OverhangSpec(id="oh2", helix_id="h2", strand_id="s2", sub_domains=[
        SubDomain(id="sub2", length_bp=3),
    ])
    return source.copy_with(
        helices=[*source.helices, helix("h2"), helix("__lnk__conn")],
        strands=[*source.strands, strand("s2", "h2"), strand("__lnk__conn__s", "__lnk__conn")],
        overhangs=[*source.overhangs, second],
        overhang_connections=[OverhangConnection(
            id="conn", overhang_a_id="oh", overhang_b_id="oh2",
            overhang_a_attach="free_end", overhang_b_attach="free_end",
            linker_type="ss", length_value=3, length_unit="bp",
        )],
    )


def test_linker_create_edit_delete_preserves_derived_identity_grammar():
    raw = linker_source()
    generated = scoped(Design(), lambda local: raw)
    owner = namespaced("conn", GROUP)
    assert generated.helices[-1].id == f"__lnk__{owner}"
    assert generated.strands[-1].id == f"__lnk__{owner}__s"
    assert generated.strands[-1].domains[0].helix_id == f"__lnk__{owner}"

    def edit(local):
        assert local.helices[-1].id == "__lnk__conn"
        return local.copy_with(overhang_connections=[local.overhang_connections[0].model_copy(update={"name": "conn"})])

    edited = scoped(generated, edit)
    assert edited.overhang_connections[0].name == "conn"
    assert edited.helices == generated.helices

    def delete(local):
        return local.copy_with(overhang_connections=[], helices=local.helices[:-1], strands=local.strands[:-1])

    deleted = scoped(edited, delete)
    assert not deleted.overhang_connections
    assert all(not h.id.startswith("__lnk__") for h in deleted.helices)


def test_cpd_canonical_keys_round_trip_colon_owners_and_dictionary_keys():
    hid, cid = "owner:helix:0", "owner:crossover:0"
    keys = [f"{hid}:0:FORWARD:1", f"__xb__:{cid}:0"]
    coordinates = {key: {"C5": [0., 1., 2.], "C6": [1., 2., 3.]} for key in keys}
    raw = Design(helices=[helix(hid)], crossovers=[Crossover(
        id=cid, half_a=HalfCrossover(helix_id=hid, index=0, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id=hid, index=0, strand=Direction.REVERSE), extra_bases="TT",
    )], photoproduct_junctions=[PhotoproductJunction(
        id="product", base_key_1=keys[0], base_key_2=keys[1], design_coordinates=coordinates,
    )])
    mapping = namespace_mapping(raw, GROUP)
    mapped = remap_design(raw, mapping)
    lesion = mapped.photoproduct_junctions[0]
    assert lesion.base_key_1 == f"{namespaced(hid, GROUP)}:0:FORWARD:1"
    assert lesion.base_key_2 == f"__xb__:{namespaced(cid, GROUP)}:0"
    assert set(lesion.design_coordinates) == {lesion.base_key_1, lesion.base_key_2}
    assert list(lesion.design_coordinates.values()) == list(coordinates.values())
    inverse = {(kind, target): identity for (kind, identity), target in mapping.items()}
    restored = remap_design(mapped, inverse)
    assert restored.model_dump(include=AUTHORING_FIELDS) == raw.model_dump(include=AUTHORING_FIELDS)


def test_asset_metadata_is_not_an_identity_or_reference_and_retained_np_is_unchanged():
    particle = Nanoparticle(id="particle", diameter_nm=10)
    asset = ProteinAsset(id="asset", name="asset", source_filename="asset", metadata={"id": "opaque", "note": "asset"})
    source = Design(nanoparticles=[particle], protein_assets=[asset])
    mapped = namespace_design(source, GROUP, ["particle"])
    assert mapped.nanoparticles == [particle]
    assert mapped.protein_assets[0].id == namespaced("asset", GROUP)
    assert mapped.protein_assets[0].metadata == asset.metadata
    assert mapped.protein_assets[0].name == mapped.protein_assets[0].source_filename == "asset"
    generated = scoped(source, lambda local: local.copy_with(helices=[helix("raw")]), ["particle"])
    assert generated.nanoparticles == source.nanoparticles
    assert generated.protein_assets == source.protein_assets


def test_selected_protein_attachment_requires_asset_closure():
    source = Design(protein_assets=[ProteinAsset(id="asset")], protein_attachments=[
        ProteinAttachment(id="attachment", asset_id="asset", target={"kind": "free"}),
    ])
    with pytest.raises(ReferenceResolutionError) as caught:
        scoped(source, lambda local: local, ["attachment"])
    assert caught.value.as_issue()["references"][0]["kind"] == "protein_asset"
    assert scoped(source, lambda local: local, ["attachment", "asset"]) == source


def test_particle_overhang_identity_survives_native_carrier_strand_changes():
    # __np_oh__ is an initial allocation convention, not a permanent ownership
    # grammar: native nick/extrusion may change the carrier but retain this ID.
    source = overhang_source()
    original_id = "__np_oh__former-carrier"
    source.overhangs[0].id = original_id
    mapping = namespace_mapping(source, GROUP)
    mapped = remap_design(source, mapping)
    assert mapped.overhangs[0].id == namespaced(original_id, GROUP)
    assert mapped.overhangs[0].strand_id == namespaced("s", GROUP)
    inverse = {(kind, target): identity for (kind, identity), target in mapping.items()}
    restored = remap_design(mapped, inverse)
    assert restored.overhangs == source.overhangs


@pytest.mark.parametrize("prefix", ["__np__", "join_", "__strep_dna__"])
def test_functional_prefixes_survive_namespace_round_trip(prefix):
    original = prefix + "raw"
    generated = scoped(Design(), lambda local: local.copy_with(helices=[helix(original)]))
    assert generated.helices[0].id.startswith(prefix)
    seen = []
    scoped(generated, lambda local: (seen.append(local.helices[0].id) or local))
    assert seen == [original]


def test_unclassified_embedded_snapshot_fails_closed():
    source = overhang_source()
    source.overhangs[0].strand_anim_setup = {"binder_strand_id": "s"}
    with pytest.raises(NotImplementedError, match="strand_anim_setup"):
        namespace_design(source, GROUP)


def test_scope_selection_never_deepcopies_unselected_recovery_or_physical_payloads():
    class NoCopy:
        def __deepcopy__(self, memo):
            pytest.fail("Scope selection copied an excluded payload")

    recovery, physical = NoCopy(), NoCopy()
    source = Design().model_copy(update={"feature_log": [recovery], "loadouts": [physical]})
    result = scoped(source, lambda local: local.copy_with(helices=[helix("raw")]))
    assert result.feature_log[0] is recovery
    assert result.loadouts[0] is physical


def test_deleting_retained_source_cannot_leave_outside_dependent_dangling():
    source = Design(helices=[helix("h")], strands=[strand("outside", "h")])
    before = source.model_dump_json()
    with pytest.raises(ReferenceResolutionError, match="existing dependent"):
        scoped(source, lambda local: local.copy_with(helices=[]), ["h"])
    assert source.model_dump_json() == before


def test_retained_linker_owner_cannot_leave_excluded_derived_children():
    source = linker_source()
    before = source.model_dump_json()
    with pytest.raises(ReferenceResolutionError, match="existing dependent") as caught:
        scoped(source, lambda local: local.copy_with(overhang_connections=[]),
               ["conn", "oh", "oh2", "h", "h2", "s", "s2"])
    assert caught.value.as_issue()["references"][0]["kind"] == "overhang_connection"
    assert source.model_dump_json() == before


@pytest.mark.parametrize("after_ids,expected", [
    (["b", "a"], ["left", "b", "middle", "a", "right"]),
    (["new", "b", "a"], ["left", "new", "middle", "b", "right", "a"]),
    (["a"], ["left", "a", "middle", "right"]),
    ([], ["left", "middle", "right"]),
    (["a", "b", "new"], ["left", "a", "middle", "b", "right", "new"]),
])
def test_composition_preserves_native_subsequence_and_independent_order(after_ids, expected):
    source = Design(helices=[helix(identity, label=identity) for identity in
                             ["left", "a", "middle", "b", "right"]])
    original = source.model_dump_json()
    before = Design(helices=[source.helices[1], source.helices[3]])
    after = Design(helices=[helix(identity, label=identity) for identity in after_ids])
    result = merge_changes(source, before, after)
    assert [h.id for h in result.helices] == expected
    assert [h.id for h in result.helices if h.id not in {"left", "middle", "right"}] == after_ids
    assert [h for h in result.helices if h.id in {"left", "middle", "right"}] == [
        source.helices[0], source.helices[2], source.helices[4],
    ]
    assert result.model_dump(include=AUTHORING_FIELDS - {"helices"}) == source.model_dump(
        include=AUTHORING_FIELDS - {"helices"}
    )
    assert source.model_dump_json() == original


def test_old_reorder_scope_requires_explicit_ordering_upgrade():
    source = Design(helices=[helix(namespaced(identity, GROUP), label="Independent text")
                             for identity in ("a", "b")])
    original = source.model_dump_json()
    with pytest.raises(NotImplementedError, match="ordering upgrade"):
        scoped(source, lambda local: local.copy_with(helices=list(reversed(local.helices))), version=None)
    assert source.model_dump_json() == original


def test_generated_native_reorder_uses_the_same_composition_as_replay():
    from backend.api.generated_history import GeneratedHistory
    from backend.api.part_proof_commands import execute as native_execute
    from backend.core.two_np_generator import GeneratorSettings

    raw = Design(helices=[helix(identity, label=identity) for identity in ("a", "b")])
    source = namespace_design(raw, GROUP)
    source = source.copy_with(helices=[
        helix("left"), source.helices[0], helix("middle"), source.helices[1], helix("right"),
    ])
    history = GeneratedHistory(source, GeneratorSettings(), group_id=GROUP)
    params = {"_proof_version": 1, "ordered_ids": ["b", "a"]}
    after = native_execute("helix-reorder", raw, params)
    history.record(raw, after, "helix-reorder", "Reorder helices", params, "reorder")
    assert [h.id for h in history.design.helices] == [
        "left", namespaced("b", GROUP), "middle", namespaced("a", GROUP), "right",
    ]
    assert history.design.model_dump(include=AUTHORING_FIELDS - {"helices"}) == source.model_dump(
        include=AUTHORING_FIELDS - {"helices"}
    )
    child = history.design.feature_log[0].children[0]
    replayed = native_execute("helix-reorder", source, child.params)
    assert replayed.model_dump(include=AUTHORING_FIELDS) == history.design.model_dump(include=AUTHORING_FIELDS)


def test_declared_native_noop_curvature_step_survives_recording_and_reload(monkeypatch):
    from backend.api.generated_history import GeneratedHistory, _StopRecording
    from backend.api.part_proof_commands import execute as native_execute
    from backend.core import sweep_loop_skips
    from backend.core.models import DeformationOp, SweepParams
    from backend.core.two_np_generator import GeneratorSettings

    source = Design(helices=[helix("h")], deformations=[DeformationOp(
        id="sweep", type="sweep", plane_a_bp=0, plane_b_bp=9, affected_helix_ids=["h"],
        params=SweepParams(points_nm=[(0, 0, 0), (0, 0, 3)], origin_nm=(0, 0, 0),
                           initial_rotation=[1., 0., 0., 0., 1., 0., 0., 0., 1.],
                           steps=9, path_length_nm=3),
    )])
    # The encoder's legitimately empty result must not erase the authored step.
    monkeypatch.setattr(sweep_loop_skips, "generated_sweep_loop_skips", lambda *_: ({}, []))
    params = {"_proof_version": 1, "op_ids": ["sweep"]}
    after = native_execute("encode-sweep-curvature", source, params)
    assert after == source
    history = GeneratedHistory(source, GeneratorSettings(), stop_key="curve-marks")
    with pytest.raises(_StopRecording):
        history.record(source, after, "encode-sweep-curvature", "Encode curvature",
                       params, "curve-marks", scoped=False)
    restored = Design.model_validate_json(history.design.model_dump_json())
    assert restored.model_dump(include=AUTHORING_FIELDS) == source.model_dump(include=AUTHORING_FIELDS)
    assert len(restored.feature_log) == 1
    assert restored.feature_log[0].op_kind == "encode-sweep-curvature"
    assert restored.feature_log[0].params == params
