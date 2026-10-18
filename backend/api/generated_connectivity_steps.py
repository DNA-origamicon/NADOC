"""Compile reviewed connectivity choices into ordinary native part features."""

from uuid import uuid4

from backend.api.part_connectivity_commands import ConnectivityPathRequest
from backend.api.part_path_commands import ConstraintCreateRequest


def _groups(design, summary):
    by_cell = {}
    for helix in design.helices:
        if helix.grid_pos in by_cell:
            raise ValueError("Ambiguous lattice cell while compiling connectivity paths")
        by_cell[helix.grid_pos] = helix.id
    try:
        return [[by_cell[tuple(cell)] for cell in face]
                for face in summary["connectivity_faces"]]
    except KeyError as exc:
        raise ValueError("Connectivity face references an unavailable lattice track") from exc


def compile_connectivity_steps(design, summary):
    """Use endpoint recipes, never the candidate's evaluated indexed paths."""
    if summary.get("branch_geometry") != "connectivity":
        raise ValueError("Connectivity construction requires a reviewed connectivity plan")
    groups = _groups(design, summary)
    recipes = summary.get("connectivity_path_recipes")
    if not groups or recipes is None or len(recipes) != len(groups):
        raise ValueError("Every connectivity face needs its retained segment recipe")
    identities = [f"connectivity_sweep_{index}" for index in range(len(groups))]
    steps = []
    for index, (helix_ids, recipe) in enumerate(zip(groups, recipes)):
        if set(recipe) != {"start_bp", "parent", "shared_interval", "segments"}:
            raise ValueError("Connectivity path recipe contains unsupported fields")
        parent = recipe["parent"]
        if parent is not None and (type(parent) is not int or not 0 <= parent < index):
            raise ValueError("Connectivity parent must precede its daughter path")
        params = ConnectivityPathRequest.model_validate({
            "_proof_version": 1, "deformation_id": identities[index], "helix_ids": helix_ids,
            "start_bp": recipe["start_bp"], "segments": recipe["segments"],
            "parent_deformation_id": identities[parent] if parent is not None else None,
            "shared_interval": recipe["shared_interval"],
        }).model_dump(mode="json", by_alias=True)
        steps.append(("connectivity-path", f"Build connectivity section {index + 1}",
                      params, f"connectivity-path:{index}"))
    for first in range(len(groups)):
        for second in range(first + 1, len(groups)):
            intervals = [j["interval"] for j in summary["connectivity_junctions"]
                         if j["parent"] == first and j["child"] == second]
            params = ConstraintCreateRequest.model_validate({
                "_proof_version": 1, "constraint_id": str(uuid4()),
                "helix_ids_a": groups[first], "helix_ids_b": groups[second],
                "allowed_bp_intervals": intervals,
            }).model_dump(mode="json", by_alias=True)
            steps.append(("crossover-constraint-create", "Constrain connectivity shared interval",
                          params, f"connectivity-rule:{first}:{second}"))
    return steps


def compile_connectivity_route_params(design, summary, history_seed):
    from backend.api.part_branch_commands import SectionRouteRequest, compile_partition_params

    params = compile_partition_params(design, summary, history_seed)
    groups = _groups(design, summary)
    junctions = sorted(summary["connectivity_junctions"], key=lambda item: item["child"])
    if (len(junctions) != len(params["windows"])
            or [j["child"] for j in junctions] != list(range(1, len(groups)))):
        raise ValueError("Each connectivity daughter needs one explicit routing parent")
    for window, junction in zip(params["windows"], junctions):
        parent, child = junction["parent"], junction["child"]
        if type(parent) is not int or not 0 <= parent < child:
            raise ValueError("Connectivity routing parent must precede its daughter")
        window["parent_helix_ids"] = groups[parent]
    return SectionRouteRequest.model_validate(params).model_dump(mode="json", by_alias=True)


def build_connectivity_steps(source, summary, history=None):
    """Construct the selected plan without reading a saved candidate Design."""
    from backend.api.part_branch_commands import compile_sparse_seed_params
    from backend.api.part_proof_commands import execute
    from backend.core.curved_rod_generator import physical_scaffold_nt
    from backend.core.models import Design

    design = Design(lattice_type=source.lattice_type)

    def apply(kind, label, params, key):
        nonlocal design
        before = design
        design = execute(kind, before, params)
        if history is not None:
            history.record(before, design, kind, label, params, key)

    apply("branch-seed", "Create connectivity lattice sections",
          compile_sparse_seed_params(summary, uuid4()), "connectivity-seed")
    for kind, label, params, key in compile_connectivity_steps(design, summary):
        apply(kind, label, params, key)
    if summary["branch_windows"]:
        apply("auto-scaffold-sections", "Route connectivity scaffold through shared sections",
              compile_connectivity_route_params(design, summary, uuid4()), "connectivity-route")
    else:
        targets = [cluster for cluster in design.cluster_transforms
                   if set(cluster.helix_ids) == {helix.id for helix in design.helices}
                   and not cluster.domain_ids]
        if len(targets) != 1:
            raise ValueError("Terminal connectivity bundle needs one authored section cluster")
        apply("auto-scaffold-connectivity-section", "Route terminal connectivity bundle",
              {"history_seed": str(uuid4()), "cluster_id": targets[0].id,
               "lattice_column_offset": 0, "_proof_version": 1}, "connectivity-route")
    scaffolds = [strand for strand in design.scaffolds() if not strand.is_reference]
    if len(scaffolds) != 1:
        raise ValueError("Connectivity sections must route as one scaffold")
    selected_ops = [op.id for op in design.deformations if op.type == "sweep"]
    encoding = {"_proof_version": 1, "op_ids": selected_ops}
    apply("encode-sweep-curvature", "Encode connectivity curvature", encoding, "connectivity-curvature")
    budget, scaffold_name = summary["scaffold_size"], summary["scaffold_name"]
    if {7249: "M13mp18", 8064: "p8064"}.get(budget) != scaffold_name:
        raise ValueError("Connectivity requires its selected native scaffold catalog entry")
    if physical_scaffold_nt(design) > budget:
        raise ValueError("Connectivity paths exceed the selected scaffold budget")
    apply("full-autostaple", "Route and sequence connectivity staples",
          {"_proof_version": 1, "history_seed": str(uuid4()), "scaffold_name": scaffold_name},
          "connectivity-autostaple")
    apply("encode-sweep-curvature", "Recompute connectivity staple curvature", encoding,
          "connectivity-staple-curvature")
    if physical_scaffold_nt(design) > budget:
        raise ValueError("Connectivity curvature corrections exceed the scaffold budget")
    for strand in design.scaffolds():
        if not strand.is_reference:
            apply("assign-scaffold-sequence", "Sequence connectivity scaffold",
                  {"_proof_version": 1, "scaffold_name": scaffold_name, "strand_id": strand.id},
                  f"connectivity-scaffold-sequence:{strand.id}")
    apply("assign-staple-sequences", "Sequence connectivity staples", {"_proof_version": 1},
          "connectivity-staple-sequences")
    return design
