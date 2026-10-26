"""Desktop fixtures reuse the native routing matrix and its actual suffix."""

from tests.test_part_routing_edit_native_matrix import (
    KINDS, base, parent, prepared_case, with_suffix,
)

FIXTURES = {f"routing-matrix-{kind}" for kind in (*KINDS, "loop-skip-clear-all")}


def fixture(name):
    kind = name.removeprefix("routing-matrix-")
    if kind == "loop-skip-clear-all":
        prefix = base(False)
        prefix = parent(prefix, [("loop-skip-insert", {
            "helix_id": prefix.helices[0].id, "bp_index": 10, "delta": 1,
        }, "prior-loop")], identity="prior-routing")
        original = {}
    else:
        prefix, original, _ = prepared_case(kind, False)
    sibling = {"helix_id": prefix.helices[-1].id, "bp_index": 60, "direction": "FORWARD"}
    return with_suffix(parent(prefix, [(kind, original, "selected-child"),
                                       ("nick", sibling, "later-child")]))
