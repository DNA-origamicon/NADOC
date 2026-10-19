"""Does a fine-routing command still operate on a strand? (cadnano-style removal)

When an upstream edit (for example a shorter extrude) leaves a fine-routing
feature — nick, ligation, resize, crossover, loop/skip … — with no strand at the
positions it operates on, the feature is removed from the log instead of the edit
being refused. This module decides "no longer applies" from the command inputs
and the design state just before the command, and nothing else:

* position-addressed kinds: every target (helix, bp, direction) slot is
  unoccupied (a loop/skip target counts any direction);
* id-addressed kinds: every referenced strand / crossover / forced ligation is
  gone.

Anything partially applicable, or any other failure, is not removable: the edit
is refused and the earliest failing feature is named, as before.
"""


def _occupied(design, helix_id, bp, direction):
    for strand in design.strands:
        if strand.is_reference:
            continue
        for dom in strand.domains:
            if dom.helix_id != helix_id:
                continue
            if direction is not None and getattr(dom.direction, "value", dom.direction) != direction:
                continue
            lo, hi = sorted((dom.start_bp, dom.end_bp))
            if lo <= bp <= hi:
                return True
    return False


def _half(half):
    return half.get("helix_id"), half.get("index"), half.get("strand")


def _positions(kind, params):
    if kind in {"nick", "ligate"}:
        return [(params.get("helix_id"), params.get("bp_index"), params.get("direction"))]
    if kind == "nick-batch":
        return [(n.get("helix_id"), n.get("bp_index"), n.get("direction")) for n in params.get("nicks", [])]
    if kind == "loop-skip-insert":
        return [(params.get("helix_id"), params.get("bp_index"), None)]
    if kind == "crossover-place":
        return [_half(params.get("half_a", {})), _half(params.get("half_b", {}))]
    if kind == "crossover-place-batch":
        return [h for p in params.get("placements", []) for h in (_half(p.get("half_a", {})), _half(p.get("half_b", {})))]
    return None


def _references(kind, params):
    """(collection, ids) for id-addressed kinds, else None."""
    if kind in {"strand-end-resize", "domain-shift"}:
        return "strands", [e.get("strand_id") for e in params.get("entries", [])]
    if kind == "forced-ligation-create":
        return "strands", [params.get("three_prime_strand_id"), params.get("five_prime_strand_id")]
    if kind in {"crossover-move", "crossover-delete", "crossover-extra-bases"}:
        return "crossovers", [params.get("crossover_id")]
    if kind == "crossover-move-batch":
        return "crossovers", [m.get("crossover_id") for m in params.get("moves", [])]
    if kind == "crossover-delete-batch":
        return "crossovers", list(params.get("crossover_ids", []))
    if kind == "crossover-extra-bases-batch":
        return "crossovers", [e.get("crossover_id") for e in params.get("entries", [])]
    if kind in {"forced-ligation-delete", "forced-ligation-extra-bases"}:
        return "forced_ligations", [params.get("fl_id")]
    if kind == "forced-ligation-delete-batch":
        return "forced_ligations", list(params.get("forced_ligation_ids", []))
    if kind in {"loop-skip-twist", "loop-skip-bend", "loop-skip-clear"}:
        return "helices", list(params.get("helix_ids", []))
    return None


def no_longer_applies(kind, params, design):
    """True when every target of this fine-routing command is unoccupied or gone."""
    from backend.core.positional_refs import positions as positional_targets
    positions = positional_targets(kind, params)
    if positions is None:
        positions = _positions(kind, params)
    if positions is not None:
        return bool(positions) and not any(
            _occupied(design, helix_id, bp, direction)
            for helix_id, bp, direction in positions
            if helix_id is not None and bp is not None)
    refs = _references(kind, params)
    if refs is None:
        return False
    collection, ids = refs
    present = {item.id for item in getattr(design, collection)}
    ids = [i for i in ids if i is not None]
    return bool(ids) and not any(i in present for i in ids)


def describe(kind, params):
    """Short human label for the removal report."""
    from backend.core.positional_refs import positions as positional_targets
    positions = positional_targets(kind, params) or _positions(kind, params)
    if positions:
        helix_id, bp, direction = positions[0]
        where = f" at {helix_id} bp {bp}" + (f" {direction}" if direction else "")
        more = f" (+{len(positions) - 1})" if len(positions) > 1 else ""
        return f"{kind}{where}{more}"
    return kind
