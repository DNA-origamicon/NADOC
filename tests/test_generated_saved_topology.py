"""Relocation snapshots preserve historical definitions and current ownership."""

from copy import deepcopy

import pytest

from backend.api.generated_native_scope import execute as scoped_execute, namespaced
from backend.api.part_duplex_commands import build
from backend.core.duplex import connect_register, relocate_duplex, revert_duplex_relocation
from backend.core.models import OverhangBinding
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_scope_references import (
    identity_index, namespace_design, namespace_mapping, referenced_resources,
    remap_design, scope_identity_index,
)
from tests.test_part_duplex_commands import SEED, connect_params, source


GROUP = "00000000-0000-0000-0000-000000000081"


def connected(*, rooted=True, equal=False):
    original = source(rooted=rooted, equal=equal)
    original.helices[-1 if not rooted else -2].label = "b"
    return build("duplex-connect", original, connect_params())


def authored(design):
    return design.model_dump(mode="json", include=AUTHORING_FIELDS)


def scoped(design, builder, inputs=()):
    return scoped_execute("test", design, {"_generated_scope": {
        "version": 2, "group_id": GROUP, "input_ids": list(inputs),
    }}, lambda _kind, local, _params: builder(local))


@pytest.mark.parametrize("rooted", [False, True])
def test_saved_missing_helix_is_reserved_but_never_recreated_by_mapping(rooted):
    original = connected(rooted=rooted)
    before = original.model_dump_json()
    assert "b" not in {helix.id for helix in original.helices}
    live, _ = identity_index(original)
    reserved, owners = scope_identity_index(original)
    assert ("helix", "b") not in live
    assert owners["helix", "b"] == ("duplex", "duplex")
    assert ("helix", "b") in reserved

    mapped = namespace_design(original, GROUP)
    snapshot = mapped.duplexes[0].prior_driven_topology
    assert snapshot["driven_helix"]["id"] == namespaced("b", GROUP)
    assert snapshot["driven_helix"]["label"] == "b"
    assert snapshot["strand_id"] == namespaced("st-b", GROUP)
    assert snapshot["driven_oh_id"] == namespaced("oh-b", GROUP)
    assert snapshot["prior_domain"]["helix_id"] == namespaced("b", GROUP)
    assert namespaced("b", GROUP) not in {helix.id for helix in mapped.helices}
    if rooted:
        assert snapshot["crossovers"][0]["id"] == namespaced("xo-b", GROUP)
        assert snapshot["forced_ligation"]["id"] == mapped.forced_ligations[0].id
    mapping = namespace_mapping(original, GROUP)
    inverse = {(kind, target): identity for (kind, identity), target in mapping.items()}
    assert authored(remap_design(mapped, inverse)) == authored(original)
    assert original.model_dump_json() == before


def test_scoped_native_unbind_and_rebind_preserve_geometry_and_restoration_ids():
    original = connected()
    mapped = namespace_design(original, GROUP)

    def unbind(local):
        # Core restoration changes topology; its caller must also refresh the
        # graph's coordinate metadata in that restored domain, as native connect
        # does after relocation. A stale [7,4] register on [0,3] is invalid.
        restored = revert_duplex_relocation(local, local.duplexes[0])
        edge = restored.duplexes[0]
        left, right = connect_register(restored, edge.left.overhang_id, "free_end",
                                       edge.right.overhang_id, "root")
        return restored.copy_with(duplexes=[edge.model_copy(update={"left": left, "right": right})])

    restored = scoped(mapped, unbind)
    expected = unbind(original)
    assert authored(restored) == authored(namespace_design(expected, GROUP))
    assert namespaced("b", GROUP) in {helix.id for helix in restored.helices}
    assert namespaced("xo-b", GROUP) in {item.id for item in restored.crossovers}
    assert not restored.forced_ligations
    assert restored.duplexes[0].prior_driven_topology is None

    def rebind(local):
        rebound = relocate_duplex(local, local.duplexes[0], identity_seed=SEED)
        edge = rebound.duplexes[0]
        left, right = connect_register(rebound, edge.left.overhang_id, "free_end",
                                       edge.right.overhang_id, "root")
        return rebound.copy_with(duplexes=[edge.model_copy(update={"left": left, "right": right})])

    rebound = scoped(restored, rebind)
    expected = rebind(expected)
    assert authored(rebound) == authored(namespace_design(expected, GROUP))
    assert namespaced("b", GROUP) not in {helix.id for helix in rebound.helices}


def test_saved_binding_uses_the_same_typed_codec_as_duplex():
    design = connected(equal=True)
    snapshot = deepcopy(design.duplexes[0].prior_driven_topology)
    binding = OverhangBinding(id="binding", created_at=1.0, name="b", bound=True,
        sub_domain_a_id="sd-a", sub_domain_b_id="sd-b", overhang_a_id="oh-a",
        overhang_b_id="oh-b", driver_oh_id="oh-a", driven_oh_id="oh-b",
        prior_driven_topology=snapshot)
    design = design.copy_with(duplexes=[], overhang_bindings=[binding])
    mapped = namespace_design(design, GROUP)
    assert mapped.overhang_bindings[0].name == "b"
    assert mapped.overhang_bindings[0].prior_driven_topology["driven_helix"]["id"] == namespaced("b", GROUP)
    refs = referenced_resources(binding)
    assert ("strand", "st-b") in refs
    assert ("helix", "root-b") in refs
    assert ("helix", "b") not in refs


@pytest.mark.parametrize("mutation", ["unknown", "nested_unknown", "duplicate", "mismatched_helix"])
def test_unsupported_saved_shapes_fail_without_altering_design(mutation):
    design = connected()
    snapshot = deepcopy(design.duplexes[0].prior_driven_topology)
    if mutation == "unknown":
        snapshot["opaque_geometry"] = {}
    elif mutation == "nested_unknown":
        snapshot["driven_helix"]["axis_start"]["unexpected"] = 1
    elif mutation == "duplicate":
        snapshot["crossovers"].append(deepcopy(snapshot["crossovers"][0]))
    else:
        snapshot["prior_ovhg_helix_id"] = "different"
    design = design.copy_with(duplexes=[design.duplexes[0].model_copy(update={
        "prior_driven_topology": snapshot})])
    before = design.model_dump_json()
    with pytest.raises(NotImplementedError):
        namespace_design(design, GROUP)
    assert design.model_dump_json() == before


def test_current_missing_owner_stays_a_structured_reference_error():
    design = connected().copy_with(overhangs=[])
    with pytest.raises(ReferenceResolutionError) as caught:
        namespace_design(design, GROUP)
    assert caught.value.as_issue()["references"][0]["kind"] == "overhang"
    assert caught.value.as_issue()["references"][0]["identity"] in {"oh-a", "oh-b"}


def test_stale_domain_ownership_cannot_be_repaired_by_saved_geometry():
    design = connected()
    snapshot = {**design.duplexes[0].prior_driven_topology, "domain_index": 0}
    design = design.copy_with(duplexes=[design.duplexes[0].model_copy(update={
        "prior_driven_topology": snapshot})])
    with pytest.raises(ReferenceResolutionError) as caught:
        namespace_design(design, GROUP)
    assert caught.value.code == "invalid_selection"
    assert caught.value.as_issue()["references"][0]["identity"] == "oh-b"


def test_historical_definition_requires_its_top_level_owner():
    design = connected()
    with pytest.raises(ReferenceResolutionError, match="top-level owner"):
        scoped(design, lambda _local: pytest.fail("Incomplete scope reached builder"), ["b"])


def test_two_historical_owners_cannot_alias_one_restorable_identity():
    design = connected()
    other = design.duplexes[0].model_copy(update={"id": "other"})
    design = design.copy_with(duplexes=[*design.duplexes, other])
    with pytest.raises(NotImplementedError, match="ambiguous historical identity ownership"):
        namespace_design(design, GROUP)
