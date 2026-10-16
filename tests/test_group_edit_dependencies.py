"""Group command dependencies must cover authored membership without source work."""

from copy import deepcopy

import pytest

from backend.api import part_proof_commands as commands
from backend.core.part_dependencies import Dependencies, DependencyIndex, Resource


def command(**fields):
    return {"_proof_version": 1, "cluster_id": "group", "translation": [1, 2, 3],
            "rotation": [0, 0, 0, 1], "pivot": [0, 0, 0], **fields}


def test_pose_only_keeps_existing_narrow_cluster_dependency():
    contract = commands.dependencies("cluster_op", command(name="Moved", opacity=0.5))
    group = Resource("cluster", "group")
    assert contract == Dependencies(frozenset({group}), frozenset({group}))


def test_membership_reads_typed_helices_and_owning_strands_without_domain_identity():
    params = command(helix_ids=["same", "other", "same"], domain_ids=[
        {"strand_id": "same", "domain_index": 0},
        {"strand_id": "same", "domain_index": 1},
    ])
    before = deepcopy(params)
    contract = commands.dependencies("cluster_op", params)
    assert contract.known and contract.barrier
    assert contract.reads == frozenset({commands.PART_TOPOLOGY, Resource("cluster", "group"),
        Resource("helix", "same"), Resource("helix", "other"), Resource("strand", "same")})
    assert contract.writes == frozenset({Resource("cluster", "group")})
    assert params == before


@pytest.mark.parametrize("fields", [{"helix_ids": []}, {"domain_ids": []}])
def test_clearing_membership_still_forms_a_topology_barrier(fields):
    contract = commands.dependencies("cluster_op", command(**fields))
    assert contract.known and contract.barrier
    assert commands.PART_TOPOLOGY in contract.reads


def test_membership_change_invalidates_suffix_after_topology_and_domain_changes():
    index = DependencyIndex()
    index.append("source-topology", Dependencies(writes=frozenset({commands.PART_TOPOLOGY})))
    index.append("domain-reorder", Dependencies(writes=frozenset({Resource("strand", "strand")})))
    index.append("membership", commands.dependencies("cluster_op", command(
        domain_ids=[{"strand_id": "strand", "domain_index": 0}])))
    index.append("later-pose", commands.dependencies("cluster_op", command(cluster_id="other")))
    assert index.complete
    assert index.affected(["source-topology"]) == {"source-topology", "membership", "later-pose"}
    assert index.affected(["domain-reorder"]) == {"domain-reorder", "membership", "later-pose"}


def test_saved_full_authored_pose_is_conservatively_a_membership_command():
    from backend.core.models import ClusterOpLogEntry
    from backend.core.part_overlay_commands import command_input

    entry = ClusterOpLogEntry(proof_version=1, cluster_id="group", translation=[1, 2, 3],
        rotation=[0, 0, 0, 1], pivot=[0, 0, 0], authored_fields={
            "name": "Arm", "helix_ids": ["helix"], "domain_ids": [], "color": None, "opacity": 1.0})
    kind, params = command_input(entry)
    contract = commands.dependencies(kind, params)
    assert contract.known and contract.barrier
    assert Resource("helix", "helix") in contract.reads


@pytest.mark.parametrize("params", [
    None, [], {}, {"_proof_version": 1},
    command(cluster_id=None), command(cluster_id=[]), command(cluster_id=5), command(cluster_id=""),
    command(helix_ids=None), command(helix_ids="helix"), command(helix_ids=[{}]),
    command(domain_ids=None), command(domain_ids=["strand"]),
    command(domain_ids=[{"strand_id": "strand"}]),
    command(domain_ids=[{"strand_id": "strand", "domain_index": -1}]),
    command(domain_ids=[{"strand_id": "strand", "domain_index": []}]),
    command(translation=[1, 2]), command(rotation=[0, 0, 0, float("nan")]),
    command(opacity="invalid"), command(_proof_version=True), command(_proof_version=2),
])
def test_malformed_command_is_unknown_instead_of_crashing_or_claiming_independence(params):
    assert commands.dependencies("cluster_op", params) == Dependencies(known=False)


def test_operation_bounds_refuse_before_model_parsing(monkeypatch):
    from backend.core.models import ClusterRigidTransform
    from backend.core.part_operation_input import MAX_OPERATION_BYTES, MAX_OPERATION_NODES

    def unexpected(*args, **kwargs):
        raise AssertionError("oversized dependency command reached typed parsing")

    monkeypatch.setattr(ClusterRigidTransform, "model_validate", unexpected)
    assert not commands.dependencies("cluster_op", command(helix_ids=["h"] * (MAX_OPERATION_NODES + 1))).known
    assert not commands.dependencies("cluster_op", command(name="x" * MAX_OPERATION_BYTES)).known


def test_cycle_and_non_json_metadata_refuse_without_recursive_execution():
    cyclic = []
    cyclic.append(cyclic)
    assert not commands.dependencies("cluster_op", command(domain_ids=cyclic)).known
    assert not commands.dependencies("cluster_op", command(extra=object())).known


def test_dependency_resolution_never_calls_native_builder_or_serializes_design(monkeypatch):
    from backend.core import part_overlay_commands
    from backend.core.models import Design

    def unexpected(*args, **kwargs):
        raise AssertionError("dependencies must inspect command metadata only")

    monkeypatch.setattr(part_overlay_commands, "build", unexpected)
    monkeypatch.setattr(Design, "model_dump", unexpected)
    assert commands.dependencies("cluster_op", command(helix_ids=["h"])).known


def test_saved_v1_native_builder_membership_and_pose_semantics_stay_unchanged():
    from backend.core.models import ClusterRigidTransform, Design, Direction, Domain, Helix, Strand, Vec3
    from backend.core.part_overlay_commands import build

    source = Design(helices=[Helix(id="h", axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=2), length_bp=6)],
        strands=[Strand(id="s", domains=[Domain(helix_id="h", start_bp=0, end_bp=5,
            direction=Direction.FORWARD)])],
        cluster_transforms=[ClusterRigidTransform(id="group"), ClusterRigidTransform(id="unrelated")])
    before = source.model_dump(mode="json")
    params = command(helix_ids=["h"], domain_ids=[{"strand_id": "s", "domain_index": "0"}],
        name="Named", color="#123456", opacity=0.5, ignored_legacy_field="unchanged")
    assert commands.dependencies("cluster_op", params).known
    result = build("cluster_op", source, params)
    group = result.cluster_transforms[0]
    assert group.helix_ids == ["h"] and group.domain_ids[0].domain_index == 0
    assert group.translation == [1, 2, 3] and group.rotation == [0, 0, 0, 1]
    assert (group.name, group.color, group.opacity) == ("Named", "#123456", 0.5)
    assert result.cluster_transforms[1] is source.cluster_transforms[1]
    assert result.helices == source.helices and result.strands == source.strands
    assert source.model_dump(mode="json") == before
