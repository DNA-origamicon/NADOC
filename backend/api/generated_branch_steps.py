"""Compile generated forks into separate native, editable construction steps.

Selected numeric path recipes are inputs. Evaluated paths, candidate geometry,
and saved design objects never enter a feature's parameters.
"""

from uuid import uuid4

from backend.api.part_path_commands import ConstraintCreateRequest, ForkPathRequest


def compile_fork_steps(design, summary):
    """Choose complete path/rule inputs and output identities before execution."""
    if summary.get("branch_geometry") != "curved":
        raise ValueError("Fork construction requires a curved fork plan")
    faces, recipes = summary["fork_faces"], summary.get("fork_path_recipes")
    if not faces or recipes is None or len(faces) != len(recipes):
        raise ValueError("Every fork face needs its retained numeric path recipe")
    ids = {}
    for helix in design.helices:
        if helix.grid_pos in ids:
            raise ValueError("Ambiguous lattice cell while compiling fork paths")
        ids[helix.grid_pos] = helix.id
    groups = [[ids[tuple(cell)] for cell in face] for face in faces]
    steps = []
    for i, (helix_ids, recipe) in enumerate(zip(groups, recipes)):
        params = ForkPathRequest.model_validate({
            **recipe, "deformation_id": f"generated_fork_sweep_{i}",
            "helix_ids": helix_ids, "_proof_version": 1,
        }).model_dump(mode="json", by_alias=True)
        steps.append(("fork-path", f"Curve fork section {i + 1}", params, f"fork-path:{i}"))
    specs = summary.get("fork_rule_specs", [(0, 1, summary["fork_crossover_intervals"])])
    for i, (first, second, intervals) in enumerate(specs):
        if (type(first) is not int or type(second) is not int
                or not 0 <= first < len(groups) or not 0 <= second < len(groups)):
            raise ValueError("Fork crossover rule names an unavailable face")
        params = ConstraintCreateRequest.model_validate({
            "constraint_id": str(uuid4()), "helix_ids_a": groups[first],
            "helix_ids_b": groups[second], "allowed_bp_intervals": intervals,
            "_proof_version": 1,
        }).model_dump(mode="json", by_alias=True)
        steps.append(("crossover-constraint-create", f"Constrain fork junction {i + 1}",
                      params, f"fork-rule:{i}"))
    return steps


def _execute_recorded(design, history, kind, label, params, key):
    from backend.api.part_proof_commands import execute

    updated = execute(kind, design, params)
    if history:
        history.record(design, updated, kind, label, params, key)
    return updated


def apply_fork_steps(design, summary, history):
    for kind, label, params, key in compile_fork_steps(design, summary):
        design = _execute_recorded(design, history, kind, label, params, key)
    return design


def encode_fork_curvature(design, history, key="curve-marks"):
    """Recompute compensation after path/routing edits, with explicit targets."""
    return _execute_recorded(
        design, history, "encode-sweep-curvature",
        "Encode fork curvature with insertions/deletions",
        {"op_ids": [op.id for op in design.deformations if op.type == "sweep"],
         "_proof_version": 1}, key,
    )


def fit_fork_budget(design, summary, budget, history):
    """Preserve the existing pre-staple encoding and optional terminal trim."""
    design = encode_fork_curvature(design, history, "branch-curvature")
    if summary.get("budget_trim_nt"):
        scaffolds = [strand for strand in design.scaffolds() if not strand.is_reference]
        if len(scaffolds) != 1:
            raise ValueError("Fork fitting requires one active scaffold")
        design = _execute_recorded(
            design, history, "scaffold-budget-fit", "Fit scaffold ends to selected budget",
            {"scaffold_id": scaffolds[0].id,
             "target_nt": summary.get("budget_pre_staple_nt", budget), "_proof_version": 1},
            "branch-budget",
        )
    return design
