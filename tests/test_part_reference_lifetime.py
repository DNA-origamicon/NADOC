"""Reference inventory releases scratch storage without waiting for cyclic GC.

These are typed-record tests only: no geometry, storage, workers or GC policy
changes. Exact sets protect the reference contract while traversal is extracted.
"""

from weakref import ref

import pytest

from backend.core import part_scope_references as inventory
from backend.core.models import (
    ClusterRigidTransform, Crossover, DeformationOp, DeformationRange, Direction,
    Domain, DomainRef, Duplex, DuplexEnd, ForcedLigation, HalfCrossover, Helix,
    OverhangBinding, OverhangSpec, PhotoproductJunction, ProteinAsset, Strand,
    SweepParams, Vec3,
)


def helix(identity, **changes):
    return Helix(id=identity, length_bp=4, axis_start=Vec3(x=0, y=0, z=0),
                 axis_end=Vec3(x=0, y=0, z=1), **changes)


def linker_strand():
    return Strand(id="__lnk__connection__s", name="unrelated-label", domains=[
        Domain(helix_id="a", start_bp=0, end_bp=3, direction=Direction.FORWARD,
               overhang_id="owned", binds_overhang_id="paired"),
        Domain(helix_id="b", start_bp=3, end_bp=0, direction=Direction.REVERSE),
    ])


def test_temporary_reference_storage_is_released_on_return(monkeypatch):
    source = linker_strand()
    scratch = []

    def tracked_set(*args):
        value = set(*args)
        scratch.append(ref(value))
        return value

    # Observe only scratch sets allocated by this module. The returned frozen
    # inventory must not keep its mutable accumulator alive through a cycle.
    monkeypatch.setattr(inventory, "set", tracked_set, raising=False)
    result = inventory.referenced_resources(source)
    assert scratch[0]() is None
    assert result == frozenset({("overhang_connection", "connection"),
        ("helix", "a"), ("helix", "b"), ("overhang", "owned"), ("overhang", "paired")})


@pytest.mark.parametrize("source,expected", [
    (linker_strand(), {("overhang_connection", "connection"), ("helix", "a"),
        ("helix", "b"), ("overhang", "owned"), ("overhang", "paired")}),
    (helix("__lnk__connection", lattice_frame_id="frame"),
        {("overhang_connection", "connection"), ("lattice_frame", "frame")}),
    (ClusterRigidTransform(id="cluster", helix_ids=["a", "a", "b"],
        parent_cluster_id="parent", overhang_duplex_driver_id="driver",
        domain_ids=[DomainRef(strand_id="carrier", domain_index=0)]),
        {("helix", "a"), ("helix", "b"), ("cluster", "parent"),
         ("overhang", "driver"), ("strand", "carrier")}),
    (ProteinAsset(id="asset", name="a", metadata={"helix_id": "a", "nested": {"id": "carrier"}}), set()),
])
def test_complete_nested_and_derived_references_preserve_authored_text(source, expected):
    before = source.model_dump(mode="json")
    assert inventory.referenced_resources(source) == frozenset(expected)
    assert source.model_dump(mode="json") == before


def test_deformation_targets_ranges_and_preceding_operations_are_all_references():
    source = DeformationOp(id="sweep", type="sweep", plane_a_bp=0, plane_b_bp=3,
        affected_helix_ids=["affected"], cluster_ids=["scope"],
        targets=[{"kind": "cluster", "id": "target-cluster"},
                 {"kind": "strand", "id": "target-strand"},
                 {"kind": "domain", "strandId": "camel-carrier", "domainIndex": 0},
                 {"kind": "domain", "strand_id": "snake-carrier", "domain_index": 1}],
        target_ranges=[DeformationRange(helix_id="range-host", strand_id="range-carrier",
            domain_index=0, start_bp=0, end_bp=3, direction=Direction.FORWARD)],
        params=SweepParams(points_nm=[(0, 0, 0), (0, 0, 1)], origin_nm=(0, 0, 0),
            initial_rotation=[1, 0, 0, 0, 1, 0, 0, 0, 1], steps=3, path_length_nm=1,
            preceding_op_ids=["previous", "previous"]))
    before = source.model_dump(mode="json")
    assert inventory.referenced_resources(source) == frozenset({
        ("helix", "affected"), ("cluster", "scope"), ("cluster", "target-cluster"),
        ("strand", "target-strand"), ("strand", "camel-carrier"), ("strand", "snake-carrier"),
        ("helix", "range-host"), ("strand", "range-carrier"), ("deformation", "previous"),
    })
    assert source.model_dump(mode="json") == before


def test_cpd_canonical_base_keys_include_coordinate_keys_and_colon_owners():
    endpoints = ("owner:helix:0:FORWARD:1", "__xb__:owner:crossover:0")
    source = PhotoproductJunction(id="product", base_key_1=endpoints[0], base_key_2=endpoints[1],
        design_coordinates={key: {"C5": [0, 1, 2], "C6": [1, 2, 3]} for key in endpoints})
    before = source.model_dump(mode="json")
    assert inventory.referenced_resources(source) == frozenset({
        ("helix", "owner:helix"), ("crossover", "owner:crossover"),
    })
    assert source.model_dump(mode="json") == before


def saved_owner(kind):
    saved = helix("historical", lattice_frame_id="external-frame")
    crossover = Crossover(id="historical-crossover",
        half_a=HalfCrossover(helix_id="historical", index=0, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id="external-root", index=0, strand=Direction.REVERSE))
    ligation = ForcedLigation(id="historical-ligation", three_prime_helix_id="historical",
        three_prime_bp=3, three_prime_direction=Direction.FORWARD,
        five_prime_helix_id="external-junction", five_prime_bp=0,
        five_prime_direction=Direction.FORWARD)
    snapshot = {"driver_oh_id": "driver", "driven_oh_id": "driven", "strand_id": "carrier",
        "domain_index": 0, "prior_ovhg_helix_id": "historical",
        "driven_helix": saved.model_dump(mode="json"),
        "prior_domain": {"helix_id": "historical", "start_bp": 0, "end_bp": 3, "direction": "FORWARD"},
        "crossovers": [crossover.model_dump(mode="json")],
        "forced_ligation": ligation.model_dump(mode="json")}
    common = {"id": "owner", "name": "Historical owner", "created_at": 1.0,
              "target_joint_id": "joint", "prior_driven_topology": snapshot}
    if kind == "duplex":
        return Duplex(**common, left=DuplexEnd(overhang_id="driver", start_bp=0, end_bp=3),
                      right=DuplexEnd(overhang_id="driven", start_bp=3, end_bp=0))
    return OverhangBinding(**common, sub_domain_a_id="sub-a", sub_domain_b_id="sub-b",
        overhang_a_id="driver", overhang_b_id="driven", driver_oh_id="driver", driven_oh_id="driven")


@pytest.mark.parametrize("kind", ["binding", "duplex"])
def test_saved_definitions_hide_owned_ids_but_keep_every_external_reference(kind):
    source = saved_owner(kind)
    expected = {("overhang", "driver"), ("overhang", "driven"), ("strand", "carrier"),
        ("joint", "joint"), ("lattice_frame", "external-frame"),
        ("helix", "external-root"), ("helix", "external-junction")}
    if kind == "binding":
        expected |= {("sub_domain", "sub-a"), ("sub_domain", "sub-b")}
    before = source.model_dump(mode="json")
    assert inventory.referenced_resources(source) == frozenset(expected)
    assert source.model_dump(mode="json") == before


@pytest.mark.parametrize("damage", ["unknown_saved_field", "blocked_animation"])
def test_unclassified_shapes_still_fail_closed_without_mutation(damage):
    if damage == "unknown_saved_field":
        source = saved_owner("binding")
        source.prior_driven_topology["opaque_output"] = {}
        message = "Unsupported saved binding topology"
    else:
        source = OverhangSpec(id="oh", helix_id="h", strand_id="s").model_copy(
            update={"strand_anim_setup": {"opaque": True}})
        message = "OverhangSpec.strand_anim_setup"
    before = source.model_dump(mode="json")
    with pytest.raises(NotImplementedError, match=message):
        inventory.referenced_resources(source)
    assert source.model_dump(mode="json") == before
