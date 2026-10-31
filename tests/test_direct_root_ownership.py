"""Covalent constraints remain typed, remappable authoring references."""

from copy import deepcopy

import pytest

from backend.api.connection_version_direct import materialize_direct
from backend.api.generated_native_scope import namespaced
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_saved_topology import snapshot_for
from backend.core.part_scope_references import namespace_design, namespace_mapping, remap_design, referenced_resources
from tests.test_direct_root_constraints import reachable_source

GROUP = "00000000-0000-0000-0000-000000000081"


@pytest.fixture(scope="module")
def connected():
    return materialize_direct(reachable_source(), "oh_a", "oh_b", "free_end", "root", "end-to-root")


def test_namespace_roundtrip_preserves_lengths_and_remaps_every_root(connected):
    before = connected.model_dump_json()
    mapped = namespace_design(connected, GROUP)
    original = connected.overhang_bindings[0].prior_driven_topology["root_bond_lengths_nm"]
    actual = mapped.overhang_bindings[0].prior_driven_topology["root_bond_lengths_nm"]
    assert actual == {namespaced(identity, GROUP): lengths for identity, lengths in original.items()}
    mapping = namespace_mapping(connected, GROUP)
    restored = remap_design(mapped, {(kind, target): identity for (kind, identity), target in mapping.items()})
    assert restored.model_dump(include=AUTHORING_FIELDS) == connected.model_dump(include=AUTHORING_FIELDS)
    assert connected.model_dump_json() == before


@pytest.mark.parametrize("lengths", [None, [], {"viewer": .1}, {"viewer": True, "export": .1},
    {"viewer": float("nan"), "export": .1}, {"viewer": .1, "export": -.1},
    {"viewer": .1, "export": .1, "unknown": .1}])
def test_malformed_root_constraints_are_not_silently_accepted(connected, lengths):
    binding = deepcopy(connected.overhang_bindings[0])
    binding.prior_driven_topology["root_bond_lengths_nm"] = {"oh_a": lengths}
    with pytest.raises(NotImplementedError, match="covalent root constraints"):
        snapshot_for(binding)


def test_missing_comoving_root_remains_an_explicit_dependency(connected):
    broken = connected.model_copy(deep=True)
    binding = broken.overhang_bindings[0]
    binding.prior_driven_topology["root_bond_lengths_nm"]["missing-partner"] = {"viewer": .1, "export": .1}
    assert ("overhang", "missing-partner") in referenced_resources(binding)
    with pytest.raises(ReferenceResolutionError) as caught:
        namespace_design(broken, GROUP)
    assert caught.value.as_issue()["references"][0]["identity"] == "missing-partner"
