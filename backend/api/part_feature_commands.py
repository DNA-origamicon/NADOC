"""Stateless adapters for existing standard-part command builders.

No snapshot fallback and no live routes/session replacement. Builder algorithms
and existing reconciliation behavior are unchanged by this extraction.
"""
from importlib import import_module

from fastapi import HTTPException

from backend.core.feature_registry import PART_MINOR_COMMANDS, PART_SNAPSHOT_COMMANDS


def _execute(spec, design, params):
    module = import_module(spec.module)
    builder = getattr(module, spec.builder)
    request = getattr(module, spec.schema).model_validate(params) if spec.schema else params
    if spec.adapter == "bundle":
        return builder([tuple(cell) for cell in request.cells], request).copy_with(recipe_root=design.recipe_root)
    if spec.parameter_keys:
        return builder(design, *(params[key] for key in spec.parameter_keys))
    result = builder(design, request)
    if spec.adapter == "reconcile":
        from backend.core.cluster_reconcile import reconcile_cluster_membership
        updated, report = result
        return reconcile_cluster_membership(design, updated, report)
    if spec.adapter == "first":
        return result[0]
    return result


def replay_snapshot(kind, design, params):
    spec = PART_SNAPSHOT_COMMANDS.get(kind)
    if spec is None:
        raise HTTPException(400, detail=f"op_kind {kind!r} is not editable via this endpoint. "
                            "Auto-ops (auto-scaffold, auto-break, etc.) should be reverted and re-run.")
    if kind != "sweep":
        # Preserve the clustering policy of features saved before this setting.
        params = {"separate_fresh_extrusions": False, **params}
    return _execute(spec, design, params)


def replay_minor(kind, design, params):
    spec = PART_MINOR_COMMANDS.get(kind)
    if spec is None:
        raise NotImplementedError(
            f"Mid-cluster replay for op_subtype {kind!r} is not implemented in v1. "
            "Falling back to cluster post-state."
        )
    return _execute(spec, design, params)


def delete_helix(design, params):
    out = design.model_copy(deep=True)
    index = next((i for i, h in enumerate(out.helices) if h.id == params["helix_id"]), None)
    if index is None:
        raise HTTPException(404, detail=f"Helix {params['helix_id']!r} not found at replay.")
    out.helices.pop(index)
    return out


def delete_crossover(design, params):
    from backend.api.crud import _desplice_strands_for_crossover
    cid = params["crossover_id"]
    crossover = next((c for c in design.crossovers if c.id == cid), None)
    if crossover is None:
        raise HTTPException(404, detail=f"Crossover {cid!r} missing at replay.")
    strands = _desplice_strands_for_crossover(design, crossover.half_a, crossover.half_b)
    out = design.model_copy(deep=True)
    out.crossovers = [c for c in out.crossovers if c.id != cid]
    out.strands = strands
    return out
