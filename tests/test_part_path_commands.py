"""Native path recipes preserve established geometry and isolate selected work."""

import numpy as np
import pytest
from pydantic import ValidationError

from backend.api.part_path_commands import build
from backend.core.lattice import make_bundle_design
from backend.core.models import (
    CrossoverConstraint, DeformationOp, LatticeType, LoopSkip, StrandExtension,
    TwistParams,
)
from backend.core.part_command_errors import ReferenceResolutionError


def path_params(*, double=False, mirror=1):
    return dict(deformation_id="fork", radius_nm=12.0, stem_bp=42, arc_bp=56,
                tail_bp=7, double=double, mirror=mirror)


def path_source(params, lattice=LatticeType.HONEYCOMB):
    steps = params["stem_bp"] + (params["arc_bp"] + params["tail_bp"]) * (2 if params["double"] else 1) + (0 if params["double"] else params["tail_bp"])
    return make_bundle_design([(0, 0), (0, 1), (3, 5)], steps + 1, lattice_type=lattice)


@pytest.mark.parametrize("lattice", list(LatticeType))
@pytest.mark.parametrize("double,mirror", [(False, 1), (True, -1)])
def test_fork_recipe_matches_native_path_and_preserves_unrelated_state(lattice, double, mirror):
    from backend.core.curved_branches import _path, apply_fork_geometry

    params = path_params(double=double, mirror=mirror)
    original = path_source(params, lattice)
    params["helix_ids"] = [helix.id for helix in original.helices[:2]]
    other = DeformationOp(id="other", type="twist", plane_a_bp=0, plane_b_bp=10,
                          affected_helix_ids=[original.helices[-1].id],
                          params=TwistParams(total_degrees=5))
    rule = CrossoverConstraint(id="existing", helix_ids_a=[original.helices[0].id],
                               helix_ids_b=[original.helices[-1].id], allowed_bp_intervals=[])
    original = original.copy_with(deformations=[other], crossover_constraints=[rule])
    before = original.model_dump_json()
    expected = apply_fork_geometry(original.copy_with(helices=original.helices[:2]), {
        "fork_faces": [[list(helix.grid_pos) for helix in original.helices[:2]]],
        "fork_paths": [_path(params["radius_nm"], params["stem_bp"], params["arc_bp"],
                              params["tail_bp"], double, mirror)],
        "fork_rule_specs": [], "fork_crossover_intervals": [],
    }).deformations[0].model_copy(update={"id": "fork"})
    result = build("fork-path", original, params)
    assert original.model_dump_json() == before
    assert result == original.copy_with(deformations=[other, expected])


@pytest.mark.parametrize("change", [
    {"radius_nm": float("nan")}, {"radius_nm": 0}, {"stem_bp": True},
    {"stem_bp": 2015}, {"double": 1}, {"mirror": 0},
    {"point_frames": []}, {"points_nm": [[0, 0, 0], [1, 1, 1]]},
])
def test_fork_rejects_unbounded_or_opaque_inputs(change):
    params = path_params()
    source = path_source(params)
    params["helix_ids"] = [source.helices[0].id]
    with pytest.raises(ValidationError):
        build("fork-path", source, {**params, **change})


@pytest.mark.parametrize("change", [
    {"lattice_frame_id": "frame"}, {"grid_pos": None}, {"bp_start": 1},
    {"length_bp": 10},
])
def test_fork_rejects_unsupported_track_frames_and_extents(change):
    params = path_params()
    source = path_source(params)
    source = source.copy_with(helices=[source.helices[0].model_copy(update=change)])
    params["helix_ids"] = [source.helices[0].id]
    with pytest.raises(ReferenceResolutionError) as caught:
        build("fork-path", source, params)
    assert caught.value.as_issue()["references"][0]["parameter_path"] == ["helix_ids", 0]


def test_fork_rejects_ambiguous_cells_and_missing_targets():
    params = path_params()
    source = path_source(params)
    source = source.copy_with(helices=[source.helices[0], source.helices[0].model_copy(update={"id": "duplicate-cell"})])
    with pytest.raises(ReferenceResolutionError, match="distinct"):
        build("fork-path", source, {**params, "helix_ids": [h.id for h in source.helices]})
    with pytest.raises(ReferenceResolutionError) as caught:
        build("fork-path", source, {**params, "helix_ids": ["missing"]})
    assert caught.value.as_issue()["references"] == [{
        "kind": "helix", "identity": "missing", "parameter_path": ["helix_ids", 0],
    }]
    assert caught.value.code == "missing_reference"


def test_constraints_preserve_empty_prohibition_and_have_explicit_identity():
    source = make_bundle_design([(0, 0), (0, 1)], 64)
    params = dict(constraint_id="rule", helix_ids_a=[source.helices[0].id],
                  helix_ids_b=[source.helices[1].id], allowed_bp_intervals=[])
    result = build("crossover-constraint-create", source, params)
    assert result.crossover_constraints == [CrossoverConstraint(id="rule", **{
        key: value for key, value in params.items() if key != "constraint_id"
    })]
    assert build("crossover-constraint-delete", result, {"constraint_id": "rule"}) == source
    with pytest.raises(ReferenceResolutionError, match="already exists"):
        build("crossover-constraint-create", result, params)
    with pytest.raises(ReferenceResolutionError) as caught:
        build("crossover-constraint-delete", source, {"constraint_id": "rule"})
    assert caught.value.as_issue()["references"][0]["parameter_path"] == ["constraint_id"]


@pytest.mark.parametrize("changes,error", [
    ({"helix_ids_b": ["missing"]}, ReferenceResolutionError),
    ({"allowed_bp_intervals": [[10, 2]]}, ValidationError),
    ({"allowed_bp_intervals": [[0, 10], [9, 20]]}, ValidationError),
    ({"allowed_bp_intervals": [[0, 64]]}, ReferenceResolutionError),
])
def test_constraint_checks_references_and_intervals(changes, error):
    source = make_bundle_design([(0, 0), (0, 1)], 64)
    params = dict(constraint_id="rule", helix_ids_a=[source.helices[0].id],
                  helix_ids_b=[source.helices[1].id], allowed_bp_intervals=[[7, 21]])
    with pytest.raises(error):
        build("crossover-constraint-create", source, {**params, **changes})


def test_curvature_filter_retains_complete_geometry_context_and_default(monkeypatch):
    from backend.core import sweep_loop_skips
    from backend.core.generated_sweep import encode_sweep

    params = path_params()
    source = path_source(params)
    source = build("fork-path", source, {**params, "helix_ids": [source.helices[0].id]})
    source = build("fork-path", source, {**params, "deformation_id": "other",
                                         "helix_ids": [source.helices[1].id]})
    called = []

    def marks(design, operation):
        assert design is source
        assert len(design.deformations) == 2
        assert len(design.helices) == 3
        called.append(operation.id)
        return {operation.affected_helix_ids[0]: [LoopSkip(bp_index=7, delta=-1)]}, []

    monkeypatch.setattr(sweep_loop_skips, "generated_sweep_loop_skips", marks)
    before = source.model_dump_json()
    result = build("encode-sweep-curvature", source, {"op_ids": ["other"]})
    assert called == ["other"]
    assert result.helices[0] == source.helices[0]
    assert result.helices[1].loop_skips == [LoopSkip(bp_index=7, delta=-1)]
    assert source.model_dump_json() == before
    called.clear()
    encode_sweep(source)
    assert called == ["fork", "other"]
    with pytest.raises(ReferenceResolutionError, match="missing"):
        build("encode-sweep-curvature", source, {"op_ids": ["deleted"]})


def test_budget_fit_preserves_native_terminal_trim_and_unrelated_state():
    from backend.core.branch_optimizer import trim_to_budget
    from backend.core.curved_rod_generator import physical_scaffold_nt

    source = make_bundle_design([(0, 0)], 64)
    unrelated = make_bundle_design([(3, 3)], 64, strand_filter="staples")
    extra = StrandExtension(id="unrelated", strand_id=unrelated.strands[0].id,
                            end="five_prime", sequence="TT")
    source = source.copy_with(helices=[*source.helices, *unrelated.helices],
                              strands=[*source.strands, *unrelated.strands], extensions=[extra])
    scaffold = source.scaffolds()[0]
    before = source.model_dump_json()
    result = build("scaffold-budget-fit", source, {"scaffold_id": scaffold.id, "target_nt": 63})
    assert result == trim_to_budget(source, 63)
    assert result.extensions == [extra]
    assert physical_scaffold_nt(result) == 63
    assert source.model_dump_json() == before


def test_budget_fit_rejects_wrong_scaffold_and_attached_targets_before_trim(monkeypatch):
    from backend.core import branch_optimizer

    source = make_bundle_design([(0, 0)], 64)
    scaffold = source.scaffolds()[0]
    source = source.copy_with(extensions=[StrandExtension(
        id="attached", strand_id=scaffold.id, end="five_prime", sequence="TT",
    )])

    def forbidden(*_):
        raise AssertionError("Unsafe input reached the native fitter")

    monkeypatch.setattr(branch_optimizer, "trim_to_budget", forbidden)
    for selected in (scaffold.id, "missing", source.staples()[0].id):
        with pytest.raises(ReferenceResolutionError) as caught:
            build("scaffold-budget-fit", source, {"scaffold_id": selected, "target_nt": 63})
        assert caught.value.as_issue()["references"][0]["parameter_path"] == ["scaffold_id"]
    multiple = make_bundle_design([(0, 0), (0, 1)], 64)
    with pytest.raises(ReferenceResolutionError, match="single active scaffold"):
        build("scaffold-budget-fit", multiple, {"scaffold_id": multiple.scaffolds()[0].id, "target_nt": 127})


def test_selected_fork_plan_and_reinforcement_retain_numeric_recipe():
    from backend.core.curved_branches import _candidate, _path
    from backend.core.branch_optimizer import reinforce_stem

    local = np.array([[-35, 0, -80], [35, 0, -80], [-35, 0, 80], [35, 0, 80]])
    summary = _candidate(local, np.eye(3), True)
    for recipe, path in zip(summary["fork_path_recipes"], summary["fork_paths"]):
        assert path == _path(recipe["radius_nm"], recipe["stem_bp"], recipe["arc_bp"],
                             recipe["tail_bp"], recipe["double"], recipe["mirror"])
    reinforced = reinforce_stem(summary, [(r, c) for r in range(2) for c in range(1, 4)],
                                LatticeType.HONEYCOMB)
    assert len(reinforced["fork_path_recipes"]) == len(reinforced["fork_paths"]) == 3
    assert reinforced["fork_path_recipes"][-1] == summary["fork_path_recipes"][0]
    assert reinforced["fork_path_recipes"][-1] is not summary["fork_path_recipes"][0]
