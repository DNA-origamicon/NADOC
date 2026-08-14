"""Direct tests for HTTP-free connection-version invariants."""

from backend.core.connection_versions import (
    assign_default_names,
    clean_sequence,
    enforce_applied_mutex,
    pair_key,
)
from backend.core.models import ConnectionVersion, Design


def _version(a: str, b: str, *, name: str = "", applied: bool = False):
    return ConnectionVersion(
        name=name,
        overhang_a_id=a,
        overhang_b_id=b,
        connection_type="end-to-end-dsdna-linker",
        applied=applied,
    )


def test_clean_sequence_normalizes_and_filters_input():
    assert clean_sequence(" ac-gTxn! ") == "ACGTN"
    assert clean_sequence("---") is None
    assert clean_sequence(None) is None


def test_pair_key_is_direction_independent():
    assert pair_key("a", "b") == pair_key("b", "a")


def test_default_names_are_allocated_independently_per_pair():
    first = _version("a", "b", name="V2")
    second = _version("b", "a")
    other_pair = _version("a", "c")
    design = Design(connection_versions=[first, second, other_pair])
    assign_default_names(design)
    assert [item.name for item in design.connection_versions] == ["V2", "V1", "V1"]


def test_applied_mutex_only_clears_versions_for_the_same_pair():
    selected = _version("a", "b", applied=True)
    sibling = _version("b", "a", applied=True)
    unrelated = _version("a", "c", applied=True)
    design = Design(connection_versions=[selected, sibling, unrelated])
    enforce_applied_mutex(design, selected.id)
    assert selected.applied is True
    assert sibling.applied is False
    assert unrelated.applied is True
