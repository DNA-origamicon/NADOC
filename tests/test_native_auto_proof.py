"""Routing pipelines rebuild from commands, including identities and metadata."""

import pytest
from backend.api import crud, state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.api.part_history_verification import verify_current_part
from backend.api.routes_scaffold_routing import (
    auto_scaffold_seamed_endpoint,
    auto_scaffold_matched_endpoint,
    auto_scaffold_seamless_endpoint,
    route_for_polymerization_endpoint,
)
from backend.api.routes_assign_sequences import (
    full_autostaple_endpoint,
    _FullAutostapleBody,
)


@pytest.fixture(autouse=True)
def document():
    token = set_current_doc("native-auto-proof-test")
    try:
        crud.create_bundle(
            crud.BundleRequest(
                cells=[[r, c] for r in range(3) for c in range(2)],
                length_bp=96,
                lattice_type="SQUARE",
            )
        )
        yield
    finally:
        state.close_session()
        reset_current_doc(token)


def verified():
    result = verify_current_part()
    assert result["status"] == "verified", result


@pytest.mark.parametrize(
    "kind",
    ["seamed", "matched", "seamless", "polymer", "break", "merge", "crossover", "full"],
)
def test_auto_commands_and_upstream_length_edit(kind):
    if kind in {"seamed", "matched", "seamless"}:
        {
            "seamed": auto_scaffold_seamed_endpoint,
            "matched": auto_scaffold_matched_endpoint,
            "seamless": auto_scaffold_seamless_endpoint,
        }[kind]()
    else:
        auto_scaffold_seamed_endpoint()
        if kind == "polymer":
            route_for_polymerization_endpoint()
        elif kind == "full":
            full_autostaple_endpoint(_FullAutostapleBody(custom_sequence="ACGT" * 300))
        elif kind == "crossover":
            crud.auto_crossover()
        elif kind == "break":
            crud.auto_break()
        else:
            crud.auto_break()
            crud.auto_merge()
    verified()
    crud.edit_feature(0, crud.EditFeatureBody(params={"length_bp": 112}))
    verified()
