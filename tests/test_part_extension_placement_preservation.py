"""Extension v2 preserves actual native placement and terminal ownership.

Cold-proof fixtures are native empty-root recipes. The separate pending-cycle
control is the existing valid routing fixture, not claimed as a native recipe.
No molecular formula, recovery body, external file or saved geometry is an oracle.
"""

from copy import deepcopy
from uuid import UUID

import numpy as np
import pytest

from backend.api import crud, part_proof_commands as commands
from backend.core import lattice, models as m
from backend.core.cluster_reconcile import reconcile_cluster_membership
from backend.core.deformation import deformed_helix_axes, deformed_nucleotide_arrays
from backend.core.design_geometry import _geometry_for_design
from backend.core.part_history_contract import assess_part_history, create_empty_part
from tests.test_part_deformation_preview import _append
from tests.test_part_group_lineage import cycle_source
from tests.test_part_transform_constraint_history import constraint_recipe
from tests.test_part_transform_preview import snapshot


CASES = ("overlap", "opposite-directions", "parent-driver")


def _verify(source):
    report = assess_part_history(
        source, execute=commands.execute, dependencies=commands.dependencies
    )
    assert report["status"] == "verified" and report["native_editable"], report


def _owner(source, identity):
    return next(owner for owner in source.cluster_transforms if owner.id == identity)


def _native_source(case):
    if case == "parent-driver":
        source, ids = constraint_recipe("duplex", suffix=False)
        child = _owner(source, ids["auxiliary"])
        assert child.parent_cluster_id == ids["fixed"]
        assert child.overhang_duplex_driver_id == ids["driver"]
        assert child.domain_ids and _owner(source, ids["fixed"]).translation != [0, 0, 0]
        return source, ids["fixed"]

    source = snapshot(
        create_empty_part("Native extension placement preservation", "HONEYCOMB"),
        "bundle-create",
        crud.BundleRequest(cells=[[0, 0]], length_bp=8, ligate_adjacent=False,
                           history_seed=UUID(int=13001)).model_dump(mode="json"),
        "bundle",
    )
    helix = source.helices[0]
    by_direction = {strand.domains[0].direction: strand for strand in source.strands}
    forward, reverse = by_direction[m.Direction.FORWARD], by_direction[m.Direction.REVERSE]
    for identity, strand, rotation, translation, pivot in (
        ("owner-a", forward, [0, .6, 0, .8], [2, -1, 3], [1, 0, 0]),
        ("owner-z", reverse if case == "opposite-directions" else forward,
         [0, 0, .6, .8], [-1, 2, .5], [0, 1, 0]),
    ):
        owner = m.ClusterRigidTransform(
            id=identity, name=identity, helix_ids=[helix.id],
            domain_ids=[m.DomainRef(strand_id=strand.id, domain_index=0)],
            rotation=rotation, translation=translation, pivot=pivot,
            color="#123456", opacity=.7,
        )
        source = _append(source, m.ClusterCreateLogEntry(
            id=f"create-{identity}", proof_version=2, cluster_id=identity,
            name=owner.name, helix_ids=owner.helix_ids,
            domain_ids=owner.domain_ids, cluster_snapshot=owner,
        ))
    # Native v2 creation retains the exhausted default because lattice frames
    # still reference its identity; extension authoring must not repopulate it.
    empty = next(owner for owner in source.cluster_transforms if owner.is_default)
    assert empty.helix_ids == [] and empty.domain_ids == []
    assert any(frame.placement_cluster_id == empty.id for frame in source.lattice_frames)
    return source, "owner-a"


def _organize(source):
    return snapshot(source, "group-organize", {
        "expected_placement_ids": [owner.id for owner in source.cluster_transforms],
    }, "organize")


def _inputs(source, *, version=2, end="three_prime", direction=m.Direction.FORWARD,
            sequence="AC", modification="cy3", create=True):
    ordinal = 0 if end == "five_prime" else -1
    strand = next(strand for strand in source.strands
                  if strand.domains[ordinal].direction == direction)
    return {"_proof_version": version, "entries": [{
        "create": create,
        "extension": {"id": "owned-terminal", "strand_id": strand.id,
                      "end": end, "sequence": sequence, "modification": modification,
                      "label": "Native terminal"},
    }]}


def _append_extension(source, params, identity="extension-v2"):
    # snapshot() is intentionally v1-only. Keep the actual recorded v2 marker.
    return _append(source, m.SnapshotLogEntry(
        id=identity, op_kind="extension-upsert", label="Terminal extension",
        params=deepcopy(params), evicted=True,
        design_snapshot_gz_b64="unusable-pre", post_state_gz_b64="unusable-post",
    ))


def _assert_native_material_unchanged(before, after):
    assert after.model_dump(mode="json", exclude={"extensions"}) == before.model_dump(
        mode="json", exclude={"extensions"})
    assert deformed_helix_axes(after) == deformed_helix_axes(before)
    for helix in before.helices:
        original = deformed_nucleotide_arrays(helix, before)
        current = deformed_nucleotide_arrays(helix, after)
        for field in ("positions", "base_positions", "base_normals", "axis_tangents",
                      "axis_points", "radial_hats"):
            np.testing.assert_array_equal(current[field], original[field])


@pytest.mark.parametrize("case", CASES)
def test_native_placement_fixture_has_valid_roundtrip_and_cold_reproduction(case):
    source, _ = _native_source(case)
    assert m.Design.model_validate_json(source.model_dump_json()) == source
    _verify(source)
    assert _geometry_for_design(source)
    assert any(owner.translation != [0, 0, 0] for owner in source.cluster_transforms)
    if case != "parent-driver":
        first, second = _owner(source, "owner-a"), _owner(source, "owner-z")
        assert first.helix_ids == second.helix_ids
        assert (first.domain_ids == second.domain_ids) == (case == "overlap")
        rest = source.copy_with(cluster_transforms=[owner.model_copy(update={
            "translation": [0, 0, 0], "rotation": [0, 0, 0, 1], "pivot": [0, 0, 0],
        }) for owner in source.cluster_transforms])
        assert _geometry_for_design(source) != _geometry_for_design(rest)


@pytest.mark.parametrize("case,end,direction,sequence,modification", [
    ("overlap", "five_prime", m.Direction.FORWARD, "AC", None),
    ("overlap", "three_prime", m.Direction.REVERSE, None, "cy3"),
    ("opposite-directions", "five_prime", m.Direction.FORWARD, "AC", "cy3"),
    ("opposite-directions", "three_prime", m.Direction.FORWARD, "AC", None),
    ("opposite-directions", "five_prime", m.Direction.REVERSE, None, "cy3"),
    ("opposite-directions", "three_prime", m.Direction.REVERSE, "AC", "cy3"),
    ("parent-driver", "five_prime", m.Direction.FORWARD, "AC", None),
    ("parent-driver", "three_prime", m.Direction.REVERSE, "AC", "cy3"),
])
def test_v2_preserves_all_owners_and_existing_native_material_while_emitting_native_tail(
        case, end, direction, sequence, modification):
    source, _ = _native_source(case)
    source = _organize(source)
    before = source.model_dump(mode="json")
    params = _inputs(source, end=end, direction=direction,
                     sequence=sequence, modification=modification)
    frozen = deepcopy(params)
    expected = source.copy_with(extensions=[m.StrandExtension.model_validate(
        params["entries"][0]["extension"])])
    actual = commands.execute("extension-upsert", source, params)
    _assert_native_material_unchanged(source, actual)
    # The expected state is authored directly from the closed requested row,
    # independently of the dispatcher/reconcile/retry pipeline under test.
    geometry = _geometry_for_design(actual)
    assert geometry == _geometry_for_design(expected)
    tail = [record for record in geometry if record.get("extension_id") == "owned-terminal"]
    assert len(tail) == len(sequence or "") + int(modification is not None)
    assert all(record["strand_id"] == params["entries"][0]["extension"]["strand_id"] for record in tail)
    assert source.model_dump(mode="json") == before and params == frozen


def test_v2_tail_on_actual_duplex_child_terminal_preserves_rotated_parent_frame():
    source, ids = constraint_recipe("duplex", suffix=False)
    child = _owner(source, ids["auxiliary"])
    parent = _owner(source, child.parent_cluster_id)
    strands = {strand.id: strand for strand in source.strands}
    terminals = [(ref, "five_prime" if ref.domain_index == 0 else "three_prime")
                 for ref in child.domain_ids
                 if ref.domain_index in {0, len(strands[ref.strand_id].domains) - 1}]
    assert terminals, "The native duplex producer must supply an actual child-owned terminus"
    target, end = terminals[0]
    domain = strands[target.strand_id].domains[target.domain_index]
    assert domain.overhang_id in {ids["driver"], ids["driven"]}
    extension = m.StrandExtension(id="child-terminal", strand_id=target.strand_id,
                                 end=end, sequence="AC", label="Native child terminal")
    unrotated = source.copy_with(extensions=[extension])
    rotated = _append(source, m.ClusterOpLogEntry(
        id="rotate-native-parent", cluster_id=parent.id, proof_version=1,
        translation=list(parent.translation), rotation=[0, .6, 0, .8], pivot=[1, 2, 0],
    ))
    assert _owner(rotated, child.id) == child
    assert _owner(rotated, parent.id).rotation != parent.rotation
    organized = _organize(rotated)
    before = organized.model_dump(mode="json")
    params = {"_proof_version": 2, "entries": [{
        "create": True, "extension": extension.model_dump(mode="json"),
    }]}
    actual = _append_extension(organized, params)
    _assert_native_material_unchanged(
        organized, actual.copy_with(feature_log=organized.feature_log))
    expected = organized.copy_with(extensions=[extension])
    geometry = _geometry_for_design(actual)
    assert geometry == _geometry_for_design(expected)
    def tail(records):
        return [record["backbone_position"] for record in records
                if record.get("extension_id") == extension.id]

    assert len(tail(geometry)) == 2
    # Establish that this terminal really uses the nonidentity parent frame;
    # matching an unaffected terminal elsewhere would not qualify this case.
    assert tail(geometry) != tail(_geometry_for_design(unrotated))
    restored = m.Design.from_json(actual.to_json())
    assert restored.model_dump(mode="json") == actual.model_dump(mode="json")
    _verify(restored)
    assert organized.model_dump(mode="json") == before


@pytest.mark.parametrize("case", ["overlap", "opposite-directions"])
def test_saved_v1_retains_its_direction_blind_single_winner_reconciliation(case):
    source, _ = _native_source(case)
    before = source.model_dump(mode="json")
    actual = commands.execute("extension-upsert", source, _inputs(source, version=1))
    expected_refs = [m.DomainRef(strand_id=strand.id, domain_index=0) for strand in source.strands]
    assert _owner(actual, "owner-a").domain_ids == expected_refs
    assert _owner(actual, "owner-z").domain_ids == []
    assert actual.cluster_transforms != source.cluster_transforms
    # This is a characterization of the retained v1 defect, not a new desired
    # pose. The same source must exercise a real geometry difference.
    old_arrays = deformed_nucleotide_arrays(source.helices[0], source)
    new_arrays = deformed_nucleotide_arrays(actual.helices[0], actual)
    assert not np.array_equal(old_arrays["positions"], new_arrays["positions"])
    assert source.model_dump(mode="json") == before


def test_actual_pending_cycle_v1_retries_v2_preserves_and_later_nick_really_merges(monkeypatch):
    source = cycle_source()
    assert m.Design.model_validate_json(source.model_dump_json()) == source
    assert lattice._unligated_ids_inline(source) == {"pending-cycle"}
    native_retry = lattice.retry_pending_ligations
    retries = []

    def observed_retry(before, after):
        retries.append(lattice._unligated_ids_inline(before))
        return native_retry(before, after)

    monkeypatch.setattr(lattice, "retry_pending_ligations", observed_retry)
    legacy = commands.execute("extension-upsert", source, _inputs(source, version=1))
    assert retries == [{"pending-cycle"}]
    assert legacy.strands == source.strands and legacy.crossovers == source.crossovers
    # Conversion is a real native operation; this small routing fixture itself
    # has no authored input history and is deliberately not cold-proofed.
    organized = commands.execute("group-organize", source, {
        "_proof_version": 1,
        "expected_placement_ids": [owner.id for owner in source.cluster_transforms],
    })
    retries.clear()
    current = commands.execute("extension-upsert", organized, _inputs(organized))
    assert retries == []
    _assert_native_material_unchanged(organized, current)
    assert lattice._unligated_ids_inline(current) == {"pending-cycle"}

    # Extension upsert cannot enable a merge without changing topology. The
    # separate native nick actually splits the cycle; native retry then merges
    # it. This asserts native routing behavior, not a new extension-end policy.
    raw = lattice.make_nick(current, current.helices[0].id, 8, m.Direction.FORWARD)
    completed = native_retry(current, reconcile_cluster_membership(current, raw))
    assert len(raw.strands) == 2 and len(completed.strands) == 1
    assert [(domain.start_bp, domain.end_bp) for domain in completed.strands[0].domains] == [(9, 20), (0, 8)]
    assert completed.strands[0].id != source.strands[0].id


@pytest.mark.parametrize("case", CASES)
def test_native_producers_conversion_v2_and_later_pose_reload_and_cold_prove(case):
    source, selected = _native_source(case)
    source = _organize(source)
    before = source.model_dump(mode="json")
    params = _inputs(source)
    current = _append_extension(source, params)
    extension_row = current.feature_log[-1]
    assert extension_row.params["_proof_version"] == 2
    assert current.model_dump(mode="json", exclude={"extensions", "feature_log"}) == source.model_dump(
        mode="json", exclude={"extensions", "feature_log"})
    prior = _owner(current, selected)
    moved = _append(current, m.ClusterOpLogEntry(
        id="later-placement", cluster_id=selected, proof_version=1,
        translation=[prior.translation[0] + .5, *prior.translation[1:]],
        rotation=list(prior.rotation), pivot=list(prior.pivot),
    ))
    assert moved.extensions == current.extensions
    assert moved.group_organization == source.group_organization
    assert _geometry_for_design(moved) != _geometry_for_design(current)
    assert [row.id for row in moved.feature_log[-2:]] == ["extension-v2", "later-placement"]
    loaded = m.Design.from_json(moved.to_json())
    assert loaded.model_dump(mode="json") == moved.model_dump(mode="json")
    _verify(loaded)
    assert source.model_dump(mode="json") == before
