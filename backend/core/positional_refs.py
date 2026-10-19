"""Position-addressed Fine Routing references (proof version 2).

A (helix, bp, direction) slot holds at most one base of one strand (see
``core/occupancy``), so a position names a strand end, a domain or a crossover
unambiguously. Strand and crossover ids are not stable across an upstream edit
that reruns routing (autostaple re-derives staples), so recorded Fine Routing
commands store the *position* of what they act on and resolve it on replay to
whatever strand/crossover occupies it then — the cadnano model.

``to_positional`` runs at record time on the pre-command design; ``resolve``
runs before execution and returns the version-1 parameters the unchanged native
builders expect. Resolution failure means nothing occupies that position any
more, which the edit path treats as "no longer applies" (cadnano-style removal).
"""

from backend.core.part_command_errors import ReferenceResolutionError

V2 = 2
KINDS = frozenset({
    "strand-end-resize", "domain-shift", "forced-ligation-create",
    "crossover-move", "crossover-move-batch", "crossover-delete", "crossover-delete-batch",
    "crossover-extra-bases", "crossover-extra-bases-batch",
})


class PositionNotOccupied(ReferenceResolutionError):
    """Nothing occupies a recorded Fine Routing position any more.

    Reported like any missing target: kind ``position``, identity
    ``helix:bp:direction``, and the parameter path of the recorded slot.
    """

    def __init__(self, detail, slot=None, path=()):
        identity = f"{slot['helix_id']}:{slot['bp_index']}:{slot['direction']}" if slot else ""
        super().__init__(detail, references=[{"kind": "position", "identity": identity,
                                              "parameter_path": list(path)}])


def _direction(value):
    return getattr(value, "value", value)


def _slot(domain, bp):
    return {"helix_id": domain.helix_id, "bp_index": bp, "direction": _direction(domain.direction)}


def _end_slot(strand, end):
    domain = strand.domains[0] if end == "5p" else strand.domains[-1]
    return _slot(domain, domain.start_bp if end == "5p" else domain.end_bp)


def _strands(design):
    return [s for s in design.strands if not s.is_reference and s.domains]


def _strand_by_id(design, strand_id):
    strand = next((s for s in design.strands if s.id == strand_id), None)
    if strand is None or not strand.domains:
        raise PositionNotOccupied(f"Strand {strand_id!r} not found")
    return strand


def _strand_with_end(design, slot, end, path):
    for strand in _strands(design):
        if _end_slot(strand, end) == slot:
            return strand
    raise PositionNotOccupied(f"No strand {end} end at {slot['helix_id']} bp {slot['bp_index']} {slot['direction']}", slot, path)


def _domain_starting_at(design, slot, path):
    for strand in _strands(design):
        for index, domain in enumerate(strand.domains):
            if _slot(domain, domain.start_bp) == slot:
                return strand, index
    raise PositionNotOccupied(f"No domain starts at {slot['helix_id']} bp {slot['bp_index']} {slot['direction']}", slot, path)


def _half(half):
    return {"helix_id": half.helix_id, "index": half.index, "strand": _direction(half.strand)}


def _crossover_halves(design, crossover_id):
    crossover = next((x for x in design.crossovers if x.id == crossover_id), None)
    if crossover is None:
        raise PositionNotOccupied(f"Crossover {crossover_id!r} not found")
    return {"half_a": _half(crossover.half_a), "half_b": _half(crossover.half_b)}


def _crossover_at(design, halves, path):
    wanted = {tuple(sorted(halves["half_a"].items())), tuple(sorted(halves["half_b"].items()))}
    for crossover in design.crossovers:
        found = {tuple(sorted(_half(crossover.half_a).items())), tuple(sorted(_half(crossover.half_b).items()))}
        if found == wanted:
            return crossover.id
    a = halves["half_a"]
    raise PositionNotOccupied(f"No crossover at {a['helix_id']} bp {a['index']}",
                              {"helix_id": a["helix_id"], "bp_index": a["index"], "direction": a["strand"]}, path)


def to_positional(kind, params, design):
    """Version-2 parameters naming positions instead of ids (record time)."""
    if kind not in KINDS or params.get("_proof_version") != 1:
        return params
    p = {k: v for k, v in params.items() if k != "_proof_version"}
    if kind == "strand-end-resize":
        p["entries"] = [{**{k: v for k, v in e.items() if k != "strand_id"},
                         "at": _end_slot(_strand_by_id(design, e["strand_id"]), e["end"])}
                        for e in p["entries"]]
    elif kind == "domain-shift":
        entries = []
        for e in p["entries"]:
            strand = _strand_by_id(design, e["strand_id"])
            domain = strand.domains[e["domain_index"]]
            entries.append({"delta_bp": e["delta_bp"], "at": _slot(domain, domain.start_bp)})
        p["entries"] = entries
    elif kind == "forced-ligation-create":
        p["three_prime_at"] = _end_slot(_strand_by_id(design, p.pop("three_prime_strand_id")), "3p")
        p["five_prime_at"] = _end_slot(_strand_by_id(design, p.pop("five_prime_strand_id")), "5p")
    elif kind in {"crossover-move", "crossover-delete", "crossover-extra-bases"}:
        p["crossover"] = _crossover_halves(design, p.pop("crossover_id"))
    elif kind == "crossover-move-batch":
        p["moves"] = [{"new_index": m["new_index"], "crossover": _crossover_halves(design, m["crossover_id"])}
                      for m in p["moves"]]
    elif kind == "crossover-delete-batch":
        p["crossovers"] = [_crossover_halves(design, i) for i in p.pop("crossover_ids")]
    elif kind == "crossover-extra-bases-batch":
        p["entries"] = [{"sequence": e["sequence"], "crossover": _crossover_halves(design, e["crossover_id"])}
                        for e in p["entries"]]
    return {**p, "_proof_version": V2}


def resolve(kind, params, design):
    """Version-1 (id) parameters for the native builder (execution time)."""
    if kind not in KINDS or type(params) is not dict or params.get("_proof_version") != V2:
        return params
    p = {k: v for k, v in params.items() if k != "_proof_version"}
    if kind == "strand-end-resize":
        p["entries"] = [{**{k: v for k, v in e.items() if k != "at"},
                         "strand_id": _strand_with_end(design, e["at"], e["end"], ["entries", i, "at"]).id}
                        for i, e in enumerate(p["entries"])]
    elif kind == "domain-shift":
        entries = []
        for i, e in enumerate(p["entries"]):
            strand, index = _domain_starting_at(design, e["at"], ["entries", i, "at"])
            entries.append({"strand_id": strand.id, "domain_index": index, "delta_bp": e["delta_bp"]})
        p["entries"] = entries
    elif kind == "forced-ligation-create":
        p["three_prime_strand_id"] = _strand_with_end(design, p.pop("three_prime_at"), "3p", ["three_prime_at"]).id
        p["five_prime_strand_id"] = _strand_with_end(design, p.pop("five_prime_at"), "5p", ["five_prime_at"]).id
    elif kind in {"crossover-move", "crossover-delete", "crossover-extra-bases"}:
        p["crossover_id"] = _crossover_at(design, p.pop("crossover"), ["crossover"])
    elif kind == "crossover-move-batch":
        p["moves"] = [{"new_index": m["new_index"],
                       "crossover_id": _crossover_at(design, m["crossover"], ["moves", i, "crossover"])}
                      for i, m in enumerate(p["moves"])]
    elif kind == "crossover-delete-batch":
        p["crossover_ids"] = [_crossover_at(design, h, ["crossovers", i]) for i, h in enumerate(p.pop("crossovers"))]
    elif kind == "crossover-extra-bases-batch":
        p["entries"] = [{"sequence": e["sequence"],
                         "crossover_id": _crossover_at(design, e["crossover"], ["entries", i, "crossover"])}
                        for i, e in enumerate(p["entries"])]
    return {**p, "_proof_version": 1}


def positions(kind, params):
    """(helix_id, bp, direction) targets of a version-2 command, for removal checks."""
    if kind not in KINDS or type(params) is not dict or params.get("_proof_version") != V2:
        return None
    slots = []
    if kind in {"strand-end-resize", "domain-shift"}:
        slots = [e["at"] for e in params.get("entries", [])]
    elif kind == "forced-ligation-create":
        slots = [params["three_prime_at"], params["five_prime_at"]]
    else:
        halves = ([params["crossover"]] if "crossover" in params else
                  params.get("crossovers") or [m["crossover"] for m in params.get("moves", params.get("entries", []))])
        return [(h[k]["helix_id"], h[k]["index"], h[k]["strand"]) for h in halves for k in ("half_a", "half_b")]
    return [(s["helix_id"], s["bp_index"], s["direction"]) for s in slots]
