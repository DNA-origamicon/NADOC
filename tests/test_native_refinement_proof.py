"""Selected refinement marks replay without job state or a live scratch session."""

import pytest
from backend.api import crud, state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.api.part_history_verification import verify_current_part


@pytest.fixture(autouse=True)
def document():
    token = set_current_doc("native-refinement-proof")
    try:
        crud.create_bundle(
            crud.BundleRequest(cells=[[0, 0]], length_bp=42, lattice_type="SQUARE")
        )
        yield
    finally:
        state.close_session()
        reset_current_doc(token)


def verified():
    result = verify_current_part()
    assert result["status"] == "verified", result


@pytest.mark.parametrize(
    "kind,variant",
    [
        ("autorefine-skips", "period"),
        ("autorefine-skips", "explicit"),
        ("cando-autorefine-marks", "explicit"),
    ],
)
def test_refinement_native_build_is_isolated_and_reproducible(kind, variant):
    from backend.api.part_refinement_commands import build

    hid = state.get_or_404().helices[0].id
    params = (
        {"skip_period": 16}
        if variant == "period"
        else (
            {"skips": {hid: [10, 20]}}
            if kind == "autorefine-skips"
            else {"marks": {hid: {10: -1, 20: 1}}}
        )
    )
    before, revision = state.get_design_with_revision()
    candidate = build(kind, before, params)
    assert state.get_design_with_revision() == (before, revision)
    assert not before.helices[0].loop_skips
    state.mutate_with_feature_log(
        kind, "Apply selected marks", params, lambda d: build(kind, d, params)
    )
    assert state.get_or_404().helices == candidate.helices
    verified()
    crud.edit_feature(0, crud.EditFeatureBody(params={"length_bp": 48}))
    verified()


def test_loop_application_and_clear_commands():
    from backend.api.routes_deformation import add_deformation, AddDeformationBody
    from backend.api.routes_loop_skip import clear_loop_skip_range
    from backend.api.routes_scaffold_routing import auto_scaffold_seamed_endpoint

    crud.create_bundle(
        crud.BundleRequest(
            cells=[[r, c] for r in range(3) for c in range(2)],
            length_bp=64,
            lattice_type="SQUARE",
        )
    )
    auto_scaffold_seamed_endpoint()
    hid = state.get_or_404().helices[0].id
    add_deformation(
        AddDeformationBody(
            type="twist",
            plane_a_bp=0,
            plane_b_bp=35,
            affected_helix_ids=[hid],
            params={"total_degrees": 20},
        )
    )
    crud.apply_loop_skips_from_deformations()
    verified()
    clear_loop_skip_range(helix_ids=hid, plane_a_bp=0, plane_b_bp=20)
    verified()
    crud.clear_all_loop_skips_endpoint()
    verified()
