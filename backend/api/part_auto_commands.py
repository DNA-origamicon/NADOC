"""Native routing pipeline adapters; no live sessions or stored result data."""

SCAFFOLD_KINDS = frozenset(
    {
        "auto-scaffold-seamed",
        "auto-scaffold-matched",
        "auto-scaffold-seamless",
        "route-for-polymerization",
    }
)
KINDS = SCAFFOLD_KINDS | {
    "auto-break",
    "auto-merge",
    "auto-crossover",
    "full-autostaple",
}


def scaffold(kind, design, *, history_seed=None):
    from backend.core.routing_identity import identity_scope

    with identity_scope(history_seed):
        return _scaffold(kind, design)


def _scaffold(kind, design):
    from backend.core.seamed_router import auto_scaffold_seamed, auto_scaffold_matched
    from backend.core.seamless_router import auto_scaffold_seamless
    from backend.core.polymer_router import route_for_polymerization
    from backend.core.cluster_join_constraints import realize_join_constraints

    runner = {
        "auto-scaffold-seamed": auto_scaffold_seamed,
        "auto-scaffold-matched": auto_scaffold_matched,
        "auto-scaffold-seamless": auto_scaffold_seamless,
        "route-for-polymerization": route_for_polymerization,
    }[kind]
    updated, result = runner(design)
    if hasattr(result, "valid") and not result.valid:
        raise ValueError("; ".join(result.errors))
    pending_count = len(updated.cluster_join_constraints)
    updated = realize_join_constraints(updated)
    if pending_count and hasattr(result, "warnings"):
        result.warnings.append(
            f"Realized all {pending_count} saved Join connections; {len(updated.scaffolds())} linear scaffold paths remain."
        )
    if kind.startswith("auto-scaffold"):
        updated = updated.copy_with(
            strands=[
                s.model_copy(update={"routing_seed": []})
                if s.is_scaffold and not s.is_reference
                else s
                for s in updated.strands
            ]
        )
    return updated, result


def crossovers(design, *, history_seed=None):
    from backend.core.routing_identity import identity_scope

    with identity_scope(history_seed):
        return _crossovers(design)


def _crossovers(design):
    from backend.api.crud import _place_auto_crossovers

    total = sites = 0
    for _ in range(12):
        design, stats = _place_auto_crossovers(design)
        sites = sites or stats["sites_considered"]
        total += stats["placed"]
        if stats["placed"] == 0:
            break
    return design, {"sites_considered": sites, "placed": total}


def build(kind, design, params):
    if kind in SCAFFOLD_KINDS:
        return scaffold(kind, design, history_seed=params.get("history_seed"))[0]
    if kind == "auto-crossover":
        return crossovers(design, history_seed=params.get("history_seed"))[0]
    if kind == "full-autostaple":
        from backend.api.part_autostaple_command import build_full_autostaple
        from backend.api.routes_assign_sequences import _FullAutostapleBody

        return build_full_autostaple(
            design, _FullAutostapleBody.model_validate(params)
        )[0]
    from backend.core.lattice import make_autobreak, make_merge_short_staples

    return (make_autobreak if kind == "auto-break" else make_merge_short_staples)(
        design
    )
