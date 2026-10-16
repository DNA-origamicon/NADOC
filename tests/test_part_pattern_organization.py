"""Explicit organization copies use the native extraction's actual descendants.

Small, memory-only native fixtures. The unchanged legacy pattern is the placement
oracle; frozen deformation provenance is deliberately not resolved against the
current strand table. No session, worker, file or simulation is created here.
"""

from importlib import import_module

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.core import models as m
from backend.core.circular_pattern import create_circular_pattern
from backend.core.deformation import deformed_nucleotide_arrays
from backend.core.lattice import make_bundle_segment
from backend.core.lattice_frames import append_independent_bundle
from backend.core.linear_pattern import create_linear_pattern
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_group_model import GroupDomainRef, GroupOrganization, PartGroup


SEED = "edb4bd91-a13a-48ed-859b-a44047a5a090"
KINDS = ("linear", "circular")


def source(*, framed=False, overlap=False):
    if framed:
        design = append_independent_bundle(m.Design(), [[0, 0], [0, 1]], 14,
            translation_nm=[4, -2, 3], rotation_xyzw=[0, 0, .6, .8])
    else:
        design = make_bundle_segment(m.Design(), [(0, 1), (1, 1), (1, 2)],
                                     14, "XY", 0, "both")
        design = design.copy_with(cluster_transforms=[m.ClusterRigidTransform(
            id="placement", name="Placement", helix_ids=[h.id for h in design.helices],
            translation=[4, -2, 3], rotation=[0, 0, .6, .8])])
    if overlap:
        design = design.copy_with(cluster_transforms=[*design.cluster_transforms,
            m.ClusterRigidTransform(id="overlap", helix_ids=[design.helices[0].id],
                                    translation=[1, 2, 0])])
    group = PartGroup(id="named", name="Named selection", helix_ids=[h.id for h in design.helices],
                     color="#aBcDeF", opacity=.375, is_default=True, auto_created=True)
    return design.copy_with(group_organization=GroupOrganization(groups=[group]))


def pattern(design, kind, *, count=2, group_ids=None, contract=None, legacy=False):
    options = {"id_seed": SEED}
    if not legacy:
        # Lazy import keeps the tests-first dossier collectable before the new
        # module exists, and checks the agreed shared HTTP/native schema seam.
        module = import_module("backend.core.part_pattern_organization")
        assert module.OrganizationCopy is not None
        options["organization_copy"] = contract if contract is not None else {
            "version": 1, "group_ids": ["named"] if group_ids is None else group_ids}
    owner = design.cluster_transforms[0].id
    if kind == "linear":
        return create_linear_pattern(design, [owner], count, 17, "X", **options)
    return create_circular_pattern(design, owner, count, 180, [3, 5, 7], [0, 0, 1], **options)


def groups(design):
    return design.group_organization.groups


def transform(points, kind, *, count=2, instance=1):
    if kind == "linear":
        return points + np.array([17 * instance, 0, 0])
    angle = np.pi * instance / (count - 1)
    rotation = Rotation.from_rotvec([0, 0, angle]).as_matrix()
    return (points - [3, 5, 7]) @ rotation.T + [3, 5, 7]


@pytest.mark.parametrize("kind", KINDS)
def test_legacy_pattern_control_is_repeatable_without_organization(kind):
    design = source().copy_with(group_organization=None)
    before = design.model_dump(mode="json")
    first, _, _ = pattern(design, kind, legacy=True)
    second, _, _ = pattern(design, kind, legacy=True)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert design.model_dump(mode="json") == before


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("framed,overlap", [(False, False), (True, False), (False, True)])
def test_explicit_groups_preserve_native_placement_and_originals(kind, framed, overlap):
    design = source(framed=framed, overlap=overlap)
    before = design.model_dump(mode="json")
    expected, expected_ids, _ = pattern(design.copy_with(group_organization=None), kind, legacy=True)
    result, new_ids, _ = pattern(design, kind)
    assert new_ids == expected_ids
    assert result.model_dump(mode="json", exclude={"group_organization"}) == expected.model_dump(
        mode="json", exclude={"group_organization"})
    assert groups(result)[0] == groups(design)[0]
    copied = groups(result)[1]
    assert copied.id != groups(design)[0].id
    assert copied.helix_ids == new_ids and copied.domain_ids == []
    assert (copied.name, copied.color, copied.opacity) == ("Named selection", "#aBcDeF", .375)
    assert copied.is_default is False and copied.auto_created is False
    assert result.cluster_transforms[:len(design.cluster_transforms)] == design.cluster_transforms
    for original, copied_helix in zip(design.helices, result.helices[len(design.helices):], strict=True):
        for field in ("positions", "base_positions"):
            assert np.allclose(deformed_nucleotide_arrays(copied_helix, result)[field],
                               transform(deformed_nucleotide_arrays(original, design)[field], kind),
                               atol=1e-8)
    m.Design.model_validate_json(result.model_dump_json())
    assert design.model_dump(mode="json") == before


def fragmented_source():
    design = source()
    helices = [h.id for h in design.helices]
    originals = [next(s for s in design.strands if s.domains[0].helix_id == hid
                      and s.domains[0].direction == m.Direction.FORWARD) for hid in helices]
    # A selected/unselected/selected path produces two actual native fragments.
    joined = originals[0].model_copy(update={"domains": [s.domains[0] for s in originals]})
    removed = {s.id for s in originals}
    design = design.copy_with(strands=[joined, *[s for s in design.strands if s.id not in removed]],
        cluster_transforms=[design.cluster_transforms[0].model_copy(update={"helix_ids": [helices[0], helices[2]]})])
    selected = PartGroup(id="named", name="Domains", helix_ids=helices,
        domain_ids=[GroupDomainRef(strand_id=joined.id, domain_index=2),
                    GroupDomainRef(strand_id=joined.id, domain_index=0)])
    excluded = PartGroup(id="outside", name="Not extracted", helix_ids=[helices[0]],
                        domain_ids=[GroupDomainRef(strand_id=joined.id, domain_index=1)])
    return design.copy_with(group_organization=GroupOrganization(groups=[selected, excluded])), joined


@pytest.mark.parametrize("kind", KINDS)
def test_domain_members_follow_actual_split_receipt_order_and_never_widen(kind, monkeypatch):
    from backend.core import pattern_copy

    design, joined = fragmented_source()
    calls = []
    real_extract = pattern_copy.extract_cluster_subdesign

    def extract(*args, **kwargs):
        calls.append(1)
        return real_extract(*args, **kwargs)

    monkeypatch.setattr(pattern_copy, "extract_cluster_subdesign", extract)
    result, new_ids, _ = pattern(design, kind, group_ids=["named", "outside"])
    assert calls == [1]
    assert groups(result)[:2] == groups(design)
    copied, outside = groups(result)[2:]
    new_strands = {s.id: s for s in result.strands[len(design.strands):]}
    assert len(copied.domain_ids) == 2
    actual = [new_strands[r.strand_id].domains[r.domain_index] for r in copied.domain_ids]
    assert [d.helix_id for d in actual] == [new_ids[1], new_ids[0]]
    assert [r.domain_index for r in copied.domain_ids] == [0, 0]
    assert all(r.strand_id != joined.id for r in copied.domain_ids)
    assert outside.domain_ids == [] and outside.helix_ids == []
    assert design.strands[0] == joined


@pytest.mark.parametrize("kind", KINDS)
def test_count_edits_preserve_existing_group_and_member_identities(kind):
    design, _ = fragmented_source()
    twice, _, _ = pattern(design, kind, group_ids=["outside", "named"])
    three, _, _ = pattern(design, kind, count=3, group_ids=["outside", "named"])
    again, _, _ = pattern(design, kind, group_ids=["outside", "named"])
    assert groups(twice) == groups(again)
    assert groups(three)[:len(groups(twice))] == groups(twice)
    assert [g.name for g in groups(three)[2:]] == ["Not extracted", "Domains"] * 2
    assert len({g.id for g in groups(three)}) == len(groups(three))
    # Presentation is a separate namespace: hidden originals do not hide copies.
    design.visibility_state.hidden_part_group_ids = ["named"]
    visible, _, _ = pattern(design, kind, group_ids=["named"])
    assert visible.visibility_state.hidden_part_group_ids == ["named"]


def scoped_source(*, target_kind="part_group", historical=False):
    design = source()
    strand = design.strands[0]
    domain = strand.domains[0]
    target = ({"kind": "part_group", "id": "named"} if target_kind == "part_group" else
              {"kind": "domain", "strand_id": strand.id, "domain_index": 0})
    op = m.DeformationOp(id="twist", type="twist", plane_a_bp=1, plane_b_bp=12,
        targets=[target], target_ranges=[m.DeformationRange(helix_id=domain.helix_id,
            start_bp=domain.start_bp, end_bp=domain.end_bp, direction=domain.direction,
            strand_id=strand.id, domain_index=0)], affected_helix_ids=[domain.helix_id],
        params=m.TwistParams(total_degrees=23))
    design = design.copy_with(deformations=[op])
    if historical:
        from backend.api.part_proof_commands import execute

        design = execute("nick", design, {"_proof_version": 1, "helix_id": domain.helix_id,
                                          "bp_index": 7, "direction": domain.direction.value})
        assert design.deformations[0] == op
    return design


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("historical", [False, True])
def test_named_deformation_copy_maps_live_groups_and_only_geometric_range_ownership(kind, historical):
    design = scoped_source(historical=historical)
    before = design.model_dump(mode="json")
    result, new_ids, _ = pattern(design, kind)
    copied = result.deformations[-1]
    assert copied.targets == [{"kind": "part_group", "id": groups(result)[1].id}]
    assert copied.target_ranges[0].helix_id == new_ids[0]
    assert copied.target_ranges[0].model_dump(exclude={"helix_id"}) == design.deformations[0].target_ranges[0].model_dump(exclude={"helix_id"})
    assert copied.affected_helix_ids == [new_ids[0]]
    assert set(copied.cluster_ids) <= {c.id for c in result.cluster_transforms[len(design.cluster_transforms):]}
    assert np.allclose(deformed_nucleotide_arrays(result.helices[len(design.helices)], result)["positions"],
                       transform(deformed_nucleotide_arrays(design.helices[0], design)["positions"], kind), atol=1e-8)
    assert design.model_dump(mode="json") == before


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("provenance", ["deleted", "same_id_new_ordinal"])
def test_primitive_provenance_is_never_reinterpreted_using_current_domain_ordinals(kind, provenance):
    design = scoped_source(target_kind="domain", historical=True)
    op = design.deformations[0]
    sid = op.targets[0]["strand_id"]
    # The selected primitive is historical. Both absent and reused source IDs
    # must behave identically; the frozen range is the numerical authority.
    strands = [s.model_copy(update={"id": "new-survivor"}) if s.id == sid else s
               for s in design.strands]
    if provenance == "same_id_new_ordinal":
        survivor = next(s for s in strands if s.domains[0].helix_id != op.affected_helix_ids[0])
        strands = [s for s in strands if s.id != survivor.id]
        strands.append(survivor.model_copy(update={"id": sid}))
    design = design.copy_with(strands=strands)
    result, new_ids, _ = pattern(design, kind)
    copied = result.deformations[-1]
    assert copied.targets == op.targets
    assert copied.target_ranges[0].helix_id == new_ids[0]
    assert copied.target_ranges[0].strand_id == sid
    assert copied.target_ranges[0].domain_index == 0


@pytest.mark.parametrize("kind", KINDS)
def test_explicit_empty_group_remains_a_named_copy_when_required_by_frozen_operation(kind):
    design = scoped_source()
    design = design.copy_with(group_organization=GroupOrganization(groups=[PartGroup(id="named")]))
    result, _, _ = pattern(design, kind)
    assert groups(result)[1].helix_ids == [] and groups(result)[1].domain_ids == []
    assert result.deformations[-1].targets == [{"kind": "part_group", "id": groups(result)[1].id}]


def test_required_named_groups_refuse_before_extraction(monkeypatch):
    from backend.core import pattern_copy

    def forbidden(*args, **kwargs):
        raise AssertionError("Undeclared live selectors must refuse before extraction")

    monkeypatch.setattr(pattern_copy, "extract_cluster_subdesign", forbidden)
    with pytest.raises(ReferenceResolutionError) as error:
        pattern(scoped_source(), "linear", group_ids=[])
    assert any(r["kind"] == "part_group" and r["identity"] == "named" for r in error.value.references)


def test_typed_deformation_without_frozen_ranges_refuses_before_extraction(monkeypatch):
    from backend.core import pattern_copy

    design = scoped_source()
    design.deformations[0].target_ranges = None
    monkeypatch.setattr(pattern_copy, "extract_cluster_subdesign", lambda *a, **k: pytest.fail("native extraction"))
    with pytest.raises(CommandContractError) as error:
        pattern(design, "linear")
    assert error.value.code == "unsupported_pattern_organization_source"


@pytest.mark.parametrize("active,explicit", [(True, False), (False, True)])
def test_organization_contract_is_explicit_and_never_activates_a_legacy_design(active, explicit):
    import_module("backend.core.part_pattern_organization")
    design = source()
    if not active:
        design = design.copy_with(group_organization=None)
    with pytest.raises(CommandContractError):
        pattern(design, "linear", legacy=not explicit)


@pytest.mark.parametrize("kind,path", [("linear", ["cluster_ids", 0]), ("circular", ["cluster_id"])])
def test_missing_pattern_placement_reports_exact_authored_parameter_path(kind, path, monkeypatch):
    from backend.core import pattern_copy

    design = source()
    before = design.model_dump(mode="json")
    monkeypatch.setattr(pattern_copy, "extract_cluster_subdesign", lambda *a, **k: pytest.fail("native extraction"))
    options = {"id_seed": SEED, "organization_copy": {"version": 1, "group_ids": ["named"]}}
    with pytest.raises(ReferenceResolutionError) as error:
        if kind == "linear":
            create_linear_pattern(design, ["missing-placement"], 2, 17, "X", **options)
        else:
            create_circular_pattern(design, "missing-placement", 2, 180, [0, 0, 0], [0, 0, 1], **options)
    assert error.value.code == "missing_reference"
    assert list(error.value.references) == [{"kind": "cluster", "identity": "missing-placement",
                                             "parameter_path": path}]
    assert design.model_dump(mode="json") == before


@pytest.mark.parametrize("target", [
    {"kind": "part_group", "id": "named", "extra": True},
    {"kind": "unknown", "id": "named"},
    {"kind": "domain", "strand_id": "historical", "domain_index": True},
])
def test_organized_copy_requires_closed_selector_provenance_before_extraction(target, monkeypatch):
    from backend.core import pattern_copy

    design = scoped_source()
    design.deformations[0].targets = [target]
    monkeypatch.setattr(pattern_copy, "extract_cluster_subdesign", lambda *a, **k: pytest.fail("native extraction"))
    with pytest.raises(CommandContractError):
        pattern(design, "linear")


@pytest.mark.parametrize("contract", [
    {"version": True, "group_ids": []}, {"version": 2, "group_ids": []},
    {"version": 1, "group_ids": ["named", "named"]},
    {"version": 1, "group_ids": [False]}, {"version": 1, "group_ids": [""]},
    {"version": 1, "group_ids": ["x" * 513]},
    {"version": 1, "group_ids": [], "placement_ids": []},
])
def test_contract_is_closed_and_strict_before_native_work(contract, monkeypatch):
    from backend.core import pattern_copy

    monkeypatch.setattr(pattern_copy, "extract_cluster_subdesign", lambda *a, **k: pytest.fail("native extraction"))
    with pytest.raises(CommandContractError):
        pattern(source(), "linear", contract=contract)


@pytest.mark.parametrize("case", ["missing", "ambiguous", "missing_domain"])
def test_source_group_references_are_exact_and_failure_atomic(case, monkeypatch):
    from backend.core import pattern_copy

    design = source()
    if case == "missing":
        selected = ["absent"]
    elif case == "ambiguous":
        design.group_organization.groups.append(groups(design)[0].model_copy(deep=True))
        selected = ["named"]
    else:
        design.group_organization.groups[0].domain_ids = [GroupDomainRef(strand_id="absent", domain_index=0)]
        selected = ["named"]
    before = design.model_dump(mode="json")
    monkeypatch.setattr(pattern_copy, "extract_cluster_subdesign", lambda *a, **k: pytest.fail("native extraction"))
    with pytest.raises(ReferenceResolutionError):
        pattern(design, "linear", group_ids=selected)
    assert design.model_dump(mode="json") == before


@pytest.mark.parametrize("case", ["group_count", "expanded_metadata"])
def test_expanded_organization_budget_precedes_extraction_and_copy(case, monkeypatch):
    from backend.core import pattern_copy

    design = source()
    count = 128
    total = 17 if case == "group_count" else 12
    name = "n" * 512 if case == "expanded_metadata" else "G"
    design.group_organization.groups = [PartGroup(id=f"g{i}", name=name,
        helix_ids=[h.id for h in design.helices]) for i in range(total)]
    monkeypatch.setattr(pattern_copy, "extract_cluster_subdesign", lambda *a, **k: pytest.fail("native extraction"))
    with pytest.raises(CommandContractError) as error:
        pattern(design, "linear", count=count, group_ids=[g.id for g in groups(design)])
    assert "limit" in error.value.code


@pytest.mark.parametrize("kind", KINDS)
def test_zero_copies_keep_identity_and_explicit_no_groups_does_not_infer(kind):
    design = source()
    unchanged, ids, _ = pattern(design, kind, count=1)
    assert unchanged is design and ids == []
    copied, _, _ = pattern(design, kind, group_ids=[])
    assert groups(copied) == groups(design)


@pytest.mark.parametrize("field", ["cluster_transforms", "strands"])
def test_organized_linear_source_count_refuses_before_native_selection_scan(field):
    class Unread:
        def __getattribute__(self, name):
            raise AssertionError("Oversized metadata collection was scanned")

    design = source()
    setattr(design, field, [Unread()] * 30_001)
    with pytest.raises(CommandContractError) as error:
        create_linear_pattern(design, ["placement"], 2, 17, "X", id_seed=SEED,
                              organization_copy={"version": 1, "group_ids": ["named"]})
    assert "limit" in error.value.code


@pytest.mark.parametrize("field", ["domains", "helix_ids"])
def test_organized_linear_cumulative_member_counts_refuse_before_member_scan(field):
    class Unread:
        def __getattribute__(self, name):
            raise AssertionError("Oversized nested metadata was scanned")

        def __hash__(self):
            raise AssertionError("Oversized member IDs entered a native set")

    design = source()
    if field == "domains":
        # Each list is individually below the bound; their sum is not.
        design.strands[0].domains = [Unread()] * 15_001
        design.strands[1].domains = [Unread()] * 15_001
    else:
        design.cluster_transforms[0].helix_ids = [Unread()] * 15_001
        design.cluster_transforms.append(m.ClusterRigidTransform(id="other").model_copy(
            update={"helix_ids": [Unread()] * 15_001}))
    with pytest.raises(CommandContractError) as error:
        create_linear_pattern(design, ["placement"], 2, 17, "X", id_seed=SEED,
                              organization_copy={"version": 1, "group_ids": ["named"]})
    assert "limit" in error.value.code


def test_aliased_frozen_ranges_are_charged_per_serialized_occurrence_before_extraction(monkeypatch):
    from backend.core import pattern_copy

    design = scoped_source()
    design.deformations[0].target_ranges = [design.deformations[0].target_ranges[0]] * 4_000
    monkeypatch.setattr(pattern_copy, "extract_cluster_subdesign", lambda *a, **k: pytest.fail("native extraction"))
    with pytest.raises(CommandContractError) as error:
        pattern(design, "linear")
    assert "limit" in error.value.code


def test_aliased_operation_header_lists_are_each_charged_before_extraction(monkeypatch):
    from backend.core import pattern_copy

    design = source()
    outside = design.helices[1].id
    design.cluster_transforms[0].helix_ids = [design.helices[0].id]
    design.cluster_transforms.append(m.ClusterRigidTransform(id=outside, helix_ids=[outside]))
    shared = [outside] * 16_000
    op = m.DeformationOp(type="twist", plane_a_bp=0, plane_b_bp=13,
                        params=m.TwistParams(total_degrees=8))
    op.affected_helix_ids = shared
    op.cluster_ids = shared
    design.deformations = [op]
    # This operation is outside the copied scope, so only complete source
    # accounting can catch the expansion; no output estimate masks the check.
    monkeypatch.setattr(pattern_copy, "extract_cluster_subdesign", lambda *a, **k: pytest.fail("native extraction"))
    with pytest.raises(CommandContractError) as error:
        pattern(design, "linear")
    assert "limit" in error.value.code


@pytest.mark.parametrize("kind", KINDS)
def test_native_sweep_copy_remaps_consumed_operations_without_reapplying_prior_bend(kind):
    from backend.core.sweep import SweepRequest, build_sweep

    design = source()
    prior = m.DeformationOp(id="before-sweep", type="bend", plane_a_bp=0, plane_b_bp=13,
        affected_helix_ids=[h.id for h in design.helices],
        params=m.BendParams(curvature_deg_per_bp=.5))
    design = design.copy_with(deformations=[prior])
    design = build_sweep(design, SweepRequest(
        cells=[h.grid_pos for h in design.helices], source_helix_id=design.helices[0].id,
        points_nm=[(0, 0, 0), (0, 0, 5), (3, 0, 8)], ligate_adjacent=False))
    assert prior.id in design.deformations[-1].params.preceding_op_ids
    before = design.model_dump(mode="json")
    result, _, _ = pattern(design, kind)
    copied_prior, copied_sweep = result.deformations[len(design.deformations):]
    assert copied_sweep.params.preceding_op_ids == [copied_prior.id]
    for original, copied in zip(design.helices, result.helices[len(design.helices):], strict=True):
        np.testing.assert_allclose(deformed_nucleotide_arrays(copied, result)["positions"],
            transform(deformed_nucleotide_arrays(original, design)["positions"], kind), atol=1e-8)
    assert design.model_dump(mode="json") == before
