"""Closed Fine Routing edit inputs and pre-child reference binding.

These adapters validate metadata only. Existing native builders still own
topology, occupancy, polarity, loop feasibility and postprocessing. New batch
output IDs are allocated by the admitted host, never by a request model default.
"""

from copy import deepcopy
from math import isfinite
from types import MappingProxyType
from uuid import UUID, uuid4

from pydantic import ValidationError

from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_operation_input import validate_operation_input
from backend.core.positional_refs import KINDS as POSITIONAL_KINDS, V2, resolve as resolve_positions


_NICK = frozenset({"helix_id", "bp_index", "direction"})
_PLACE = frozenset({"half_a", "half_b", "nick_bp_a", "nick_bp_b", "process_id"})
_LOOP = frozenset({"helix_ids", "plane_a_bp", "plane_b_bp"})
EDIT_FIELDS = MappingProxyType({
    "strand-end-resize": frozenset({"entries"}),
    "domain-shift": frozenset({"entries"}),
    "nick": _NICK, "nick-batch": frozenset({"nicks"}), "ligate": _NICK,
    "forced-ligation-create": frozenset({"three_prime_strand_id", "five_prime_strand_id", "is_periodic_seam"}),
    "forced-ligation-delete": frozenset({"fl_id"}),
    "forced-ligation-delete-batch": frozenset({"forced_ligation_ids"}),
    "forced-ligation-extra-bases": frozenset({"fl_id", "sequence"}),
    "crossover-place": _PLACE,
    "crossover-place-batch": frozenset({"placements"}),
    "crossover-move": frozenset({"crossover_id", "new_index"}),
    "crossover-move-batch": frozenset({"moves"}),
    "crossover-delete": frozenset({"crossover_id"}),
    "crossover-delete-batch": frozenset({"crossover_ids"}),
    "crossover-extra-bases": frozenset({"crossover_id", "sequence"}),
    "crossover-extra-bases-batch": frozenset({"entries"}),
    "loop-skip-insert": frozenset({"helix_id", "bp_index", "delta"}),
    "loop-skip-twist": _LOOP | {"target_twist_deg"},
    "loop-skip-bend": _LOOP | {"radius_nm", "direction_deg"},
    "loop-skip-clear": _LOOP,
    "loop-skip-clear-all": frozenset(),
})
KINDS = frozenset(EDIT_FIELDS)
# Proof-v2 children name their targets by position (see core/positional_refs):
# a strand end / domain start slot, or a crossover's two halves.
_SLOT = frozenset({"helix_id", "bp_index", "direction"})
_HALVES = frozenset({"half_a", "half_b"})
POSITIONAL_FIELDS = MappingProxyType({
    "strand-end-resize": frozenset({"entries"}),
    "domain-shift": frozenset({"entries"}),
    "forced-ligation-create": frozenset({"three_prime_at", "five_prime_at", "is_periodic_seam"}),
    "crossover-move": frozenset({"crossover", "new_index"}),
    "crossover-move-batch": frozenset({"moves"}),
    "crossover-delete": frozenset({"crossover"}),
    "crossover-delete-batch": frozenset({"crossovers"}),
    "crossover-extra-bases": frozenset({"crossover", "sequence"}),
    "crossover-extra-bases-batch": frozenset({"entries"}),
})
MAX_WORK = 50_000
MAX_SOURCE_ITEMS = 30_000
_OPTIONAL = frozenset({"process_id", "is_periodic_seam", "direction_deg"})


def _invalid(detail, *, code="invalid_routing_input"):
    raise CommandContractError(detail, code=code)


def _json(value):
    try:
        validate_operation_input(value)
    except ValueError as error:
        _invalid(str(error), code="routing_input_limit")


def _shape(value, fields, *, optional=frozenset()):
    if type(value) is not dict or value.keys() - fields or fields - optional - value.keys():
        _invalid("Routing inputs must contain exactly the supported native fields.")


def _id(value):
    if type(value) is not str or not 1 <= len(value) <= 512:
        _invalid("Routing identities must be bounded nonempty strings.")


def _output_id(value):
    _id(value)
    try:
        if str(UUID(value)) != value:
            _invalid("Crossover output identities must be canonical UUIDs.")
    except ValueError as error:
        _invalid(f"Invalid crossover output identity: {error}")


def _integer(value):
    if type(value) is not int or value.bit_length() > 64:
        _invalid("Routing indices and deltas must be exact bounded integers.")


def _number(value):
    if type(value) not in {int, float} or not isfinite(value):
        _invalid("Routing numerical inputs must be finite numbers.")


def _choice(value, options):
    if type(value) is not str or value not in options:
        _invalid("Unsupported routing direction or strand end.")


def _list(value):
    if type(value) is not list:
        _invalid("Routing batches require ordered lists.")
    return value


def _sequence(value):
    if type(value) is not str or any(base not in "ACGTNacgtn" for base in value):
        _invalid("Extra-base sequences accept only A, C, G, T and N; empty clears.")


def _positional(kind, values):
    return kind in POSITIONAL_KINDS and type(values) is dict and values.get("_proof_version") == V2


def _fields(kind, values):
    return POSITIONAL_FIELDS[kind] if _positional(kind, values) else EDIT_FIELDS[kind]


def _slot(value):
    _shape(value, _SLOT)
    _id(value["helix_id"])
    _integer(value["bp_index"])
    _choice(value["direction"], {"FORWARD", "REVERSE"})


def _crossover_halves(value):
    _shape(value, _HALVES)
    for name in ("half_a", "half_b"):
        half = value[name]
        _shape(half, {"helix_id", "index", "strand"})
        _id(half["helix_id"])
        _integer(half["index"])
        _choice(half["strand"], {"FORWARD", "REVERSE"})


def _validate_positional(kind, values):
    if kind in {"strand-end-resize", "domain-shift"}:
        work = 0
        for item in _list(values["entries"]):
            _shape(item, {"at", "helix_id", "end", "delta_bp"} if kind == "strand-end-resize"
                   else {"at", "delta_bp"})
            _slot(item["at"])
            _integer(item["delta_bp"])
            work += abs(item["delta_bp"])
            if kind == "strand-end-resize":
                _id(item["helix_id"])
                _choice(item["end"], {"5p", "3p"})
        if work > MAX_WORK:
            _invalid("Routing exceeds the 50000 work allowance.", code="routing_input_limit")
    elif kind == "forced-ligation-create":
        _slot(values["three_prime_at"])
        _slot(values["five_prime_at"])
        if "is_periodic_seam" in values and type(values["is_periodic_seam"]) is not bool:
            _invalid("is_periodic_seam must be a boolean.")
    elif kind == "crossover-delete-batch":
        for item in _list(values["crossovers"]):
            _crossover_halves(item)
    else:
        batch = kind.endswith("-batch")
        entries = _list(values["entries" if "extra-bases" in kind else "moves"]) if batch else [values]
        for item in entries:
            if batch:
                _shape(item, {"crossover", "sequence" if "extra-bases" in kind else "new_index"})
            _crossover_halves(item["crossover"])
            if "extra-bases" in kind:
                _sequence(item["sequence"])
            elif "move" in kind:
                _integer(item["new_index"])


def _protected(kind):
    return (frozenset({"_proof_version"})
            | ({"crossover_id"} if kind == "crossover-place" else set())
            | ({"_fl_id"} if kind == "forced-ligation-create" else set()))


def _placement(value, *, allow_new=False):
    fields = _PLACE | {"crossover_id"}
    _shape(value, fields, optional={"process_id"} | ({"crossover_id"} if allow_new else set()))
    if not (allow_new and value.get("crossover_id") is None):
        _output_id(value["crossover_id"])
    for name in ("half_a", "half_b"):
        half = value[name]
        _shape(half, {"helix_id", "index", "strand"})
        _id(half["helix_id"])
        _integer(half["index"])
        _choice(half["strand"], {"FORWARD", "REVERSE"})
    _integer(value["nick_bp_a"])
    _integer(value["nick_bp_b"])
    if value.get("process_id") is not None:
        if type(value["process_id"]) is not str:
            _invalid("Crossover process_id must be a string or null.")


def _native_schema(kind):
    from backend.api import crud

    return {
        "strand-end-resize": crud.StrandEndResizeRequest,
        "domain-shift": crud.DomainShiftRequest,
        "nick": crud.NickRequest, "nick-batch": crud.NickBatchRequest, "ligate": crud.NickRequest,
        "forced-ligation-create": crud.ForcedLigationRequest,
        "forced-ligation-delete-batch": crud.BatchDeleteForcedLigationsRequest,
        "crossover-place": crud.PlaceCrossoverRequest,
        "crossover-place-batch": crud.PlaceCrossoverBatchRequest,
        "crossover-move": crud.MoveCrossoverRequest,
        "crossover-move-batch": crud.BatchMoveCrossoversRequest,
        "crossover-delete-batch": crud.BatchDeleteCrossoversRequest,
        "crossover-extra-bases-batch": crud.BatchCrossoverExtraBasesRequest,
    }.get(kind)


def _validate(kind, values, *, allow_new=False):
    """Strict JSON shape validation before native request coercion or copying."""
    if type(kind) is not str or kind not in KINDS:
        _invalid("Choose a supported native Fine Routing child.")
    _json(values)
    fields = _fields(kind, values) | _protected(kind)
    _shape(values, fields, optional=_OPTIONAL)
    if type(values["_proof_version"]) is not int or values["_proof_version"] not in (
            (1, V2) if kind in POSITIONAL_KINDS else (1,)):
        _invalid("Routing editing requires native proof version 1, or 2 for positional routing.",
                 code="unsupported_routing_definition")
    if "_fl_id" in values:
        _id(values["_fl_id"])
    if _positional(kind, values):
        _validate_positional(kind, values)
        return
    if kind in {"strand-end-resize", "domain-shift"}:
        work = 0
        for item in _list(values["entries"]):
            fields = ({"strand_id", "helix_id", "end", "delta_bp"} if kind == "strand-end-resize"
                      else {"strand_id", "domain_index", "delta_bp"})
            _shape(item, fields)
            _id(item["strand_id"])
            _integer(item["delta_bp"])
            work += abs(item["delta_bp"])
            if kind == "strand-end-resize":
                _id(item["helix_id"])
                _choice(item["end"], {"5p", "3p"})
            else:
                _integer(item["domain_index"])
                if item["domain_index"] < 0:
                    _invalid("Domain ordinals must be nonnegative.")
        if work > MAX_WORK:
            _invalid("Routing exceeds the 50000 work allowance.", code="routing_input_limit")
    elif kind in {"nick", "ligate", "nick-batch"}:
        entries = _list(values["nicks"]) if kind == "nick-batch" else [values]
        for item in entries:
            if kind == "nick-batch":
                _shape(item, _NICK)
            _id(item["helix_id"])
            _integer(item["bp_index"])
            _choice(item["direction"], {"FORWARD", "REVERSE"})
    elif kind == "forced-ligation-create":
        _id(values["three_prime_strand_id"])
        _id(values["five_prime_strand_id"])
        if "is_periodic_seam" in values and type(values["is_periodic_seam"]) is not bool:
            _invalid("is_periodic_seam must be a boolean.")
    elif kind in {"crossover-place", "crossover-place-batch"}:
        entries = (_list(values["placements"]) if kind.endswith("-batch")
                   else [{key: item for key, item in values.items() if key != "_proof_version"}])
        outputs = set()
        for item in entries:
            _placement(item, allow_new=allow_new and kind.endswith("-batch"))
            identity = item.get("crossover_id")
            if identity is not None:
                if identity in outputs:
                    _invalid("Each crossover creation output slot must be unique.")
                outputs.add(identity)
    elif kind.startswith(("crossover-", "forced-ligation-")):
        identity = "fl_id" if kind.startswith("forced") else "crossover_id"
        if "delete-batch" in kind:
            field = "forced_ligation_ids" if kind.startswith("forced") else "crossover_ids"
            for item in _list(values[field]):
                _id(item)
        else:
            field = "entries" if "extra-bases" in kind else "moves"
            entries = _list(values[field]) if kind.endswith("-batch") else [values]
            for item in entries:
                if kind.endswith("-batch"):
                    _shape(item, {identity, "sequence" if "extra-bases" in kind else "new_index"})
                _id(item[identity])
                if "extra-bases" in kind:
                    _sequence(item["sequence"])
                elif "move" in kind:
                    _integer(item["new_index"])
    elif kind == "loop-skip-insert":
        _id(values["helix_id"])
        _integer(values["bp_index"])
        _integer(values["delta"])
        if values["delta"] not in {-1, 0, 1}:
            _invalid("Loop/skip delta must be -1, 0 or 1.")
    elif kind != "loop-skip-clear-all":
        for identity in _list(values["helix_ids"]):
            _id(identity)
        _integer(values["plane_a_bp"])
        _integer(values["plane_b_bp"])
        if kind in {"loop-skip-twist", "loop-skip-bend"}:
            if not values["helix_ids"]:
                _invalid("Twist/bend requires a selected helix.")
            work = max(0, values["plane_b_bp"] - values["plane_a_bp"]) * len(values["helix_ids"])
            if work > MAX_WORK:
                _invalid("Routing exceeds the 50000 work allowance.", code="routing_input_limit")
            _number(values["target_twist_deg" if kind.endswith("twist") else "radius_nm"])
            if kind.endswith("bend"):
                if values["radius_nm"] <= 0:
                    _invalid("Loop/skip bend radius must be positive.")
                _number(values.get("direction_deg", 0))


def _complete(kind, values):
    _validate(kind, values)
    schema = None if _positional(kind, values) else _native_schema(kind)
    if schema is None:
        result = deepcopy(values)
    else:
        try:
            result = schema.model_validate(values).model_dump(mode="json")
        except ValidationError as error:
            _invalid(str(error))
        result.update({key: deepcopy(values[key]) for key in _protected(kind)})
    if "extra-bases" in kind:
        for item in result["entries"] if kind.endswith("-batch") else [result]:
            item["sequence"] = item["sequence"].upper()
    if kind == "loop-skip-bend":
        result.setdefault("direction_deg", 0)
    _json(result)
    return result


def _edit_values(kind, previous, changes):
    _validate(kind, previous)
    _json(changes)
    if type(changes) is not dict or changes.keys() - _fields(kind, previous) - _protected(kind):
        _invalid("Routing edit contains unsupported fields.")
    for key in _protected(kind) & changes.keys():
        if type(changes[key]) is not type(previous[key]) or changes[key] != previous[key]:
            _invalid("Routing output identities and proof metadata cannot be edited.")
    return {**previous, **changes}


def normalize(kind, previous, changes, *, added_output_ids=()):
    """Return complete detached native inputs; new IDs need a private host receipt."""
    values = _edit_values(kind, previous, changes)
    _validate(kind, values)
    if type(added_output_ids) not in {list, tuple} or len(added_output_ids) > 10_000:
        _invalid("Invalid batch output allocation receipt.")
    _json(list(added_output_ids))
    for identity in added_output_ids:
        _output_id(identity)
    if len(set(added_output_ids)) != len(added_output_ids):
        _invalid("Batch output allocation receipt repeats an identity.")
    added = set(added_output_ids)
    if kind == "crossover-place-batch":
        old = {item["crossover_id"] for item in previous["placements"]}
        new = {item["crossover_id"] for item in values["placements"]}
        if added & old or new - old != added:
            _invalid("New crossover slots require exactly the host-allocated identities.")
    elif added:
        _invalid("Only batch crossover creation accepts output allocations.")
    return _complete(kind, values)


def allocate_output_slots(kind, previous, changes):
    """After source admission, allocate omitted/null batch IDs once per request.

    The returned ``added_ids`` is private worker metadata, not caller authority.
    Callers must bind it to the selected row and request before worker replay.
    """
    values = _edit_values(kind, previous, changes)
    _validate(kind, values, allow_new=True)
    if kind != "crossover-place-batch" or "placements" not in changes:
        normalize(kind, previous, changes)
        return {"changes": deepcopy(changes), "added_ids": []}
    old = {item["crossover_id"] for item in previous["placements"]}
    if any(item.get("crossover_id") is not None and item["crossover_id"] not in old
           for item in values["placements"]):
        _invalid("A request cannot supply a replacement crossover output identity.")
    result, added = deepcopy(changes), []
    used = set(old)
    for item in result["placements"]:
        if item.get("crossover_id") is None:
            identity = str(uuid4())
            if identity in used:
                _invalid("Allocated crossover output identity collided.")
            item["crossover_id"] = identity
            used.add(identity)
            added.append(identity)
    normalize(kind, previous, result, added_output_ids=added)
    return {"changes": result, "added_ids": added}


def _reference(kind, identity, path):
    return {"kind": kind, "identity": identity, "parameter_path": path}


def _references(kind, params):
    refs = []
    def add(resource, identity, path):
        refs.append(_reference(resource, identity, path))

    if kind in {"nick", "ligate", "loop-skip-insert"}:
        add("helix", params["helix_id"], ["helix_id"])
    elif kind == "nick-batch":
        for index, item in enumerate(params["nicks"]):
            add("helix", item["helix_id"], ["nicks", index, "helix_id"])
    elif kind in {"strand-end-resize", "domain-shift"}:
        for index, item in enumerate(params["entries"]):
            add("strand", item["strand_id"], ["entries", index, "strand_id"])
            if kind == "strand-end-resize":
                add("helix", item["helix_id"], ["entries", index, "helix_id"])
    elif kind == "forced-ligation-create":
        for name in ("three_prime_strand_id", "five_prime_strand_id"):
            add("strand", params[name], [name])
    elif kind in {"crossover-place", "crossover-place-batch"}:
        entries = enumerate(params["placements"]) if kind.endswith("-batch") else [(None, params)]
        for index, item in entries:
            base = ["placements", index] if index is not None else []
            for half in ("half_a", "half_b"):
                add("helix", item[half]["helix_id"], [*base, half, "helix_id"])
    elif kind.startswith(("crossover-", "forced-ligation-")):
        resource, key = ("forced_ligation", "fl_id") if kind.startswith("forced") else ("crossover", "crossover_id")
        if "delete-batch" in kind:
            field = "forced_ligation_ids" if kind.startswith("forced") else "crossover_ids"
            for index, identity in enumerate(params[field]):
                add(resource, identity, [field, index])
        elif kind.endswith("-batch"):
            field = "entries" if "extra-bases" in kind else "moves"
            for index, item in enumerate(params[field]):
                add(resource, item[key], [field, index, key])
        else:
            add(resource, params[key], [key])
    elif kind != "loop-skip-clear-all":
        for index, identity in enumerate(params["helix_ids"]):
            add("helix", identity, ["helix_ids", index])
    return refs


def _inventories(prefix, resources):
    fields = {"helix": "helices", "strand": "strands", "crossover": "crossovers", "forced_ligation": "forced_ligations"}
    indexes, ambiguous, count, size = {}, {}, 0, 0
    for resource in resources:
        items = getattr(prefix, fields[resource])
        if type(items) is not list:
            _invalid("Invalid routing source inventory.")
        count += len(items)
        if count > MAX_SOURCE_ITEMS:
            _invalid("Routing source inventory exceeds its allowance.", code="routing_input_limit")
        index, duplicates = {}, set()
        for item in items:
            _id(item.id)
            size += 4 * len(item.id) + 32
            if resource == "strand":
                if type(item.domains) is not list:
                    _invalid("Invalid routing source domains.")
                count += len(item.domains)
            if count > MAX_SOURCE_ITEMS or size > 2_000_000:
                _invalid("Routing source inventory exceeds its allowance.", code="routing_input_limit")
            if item.id in index:
                duplicates.add(item.id)
            index[item.id] = item
        indexes[resource], ambiguous[resource] = index, duplicates
    return indexes, ambiguous


def bind_prefix(kind, params, prefix):
    """Check actual pre-child references; never replay or inspect recovery/atoms.

    ``params`` must already pass source-bound normalization. This binder does
    not allocate output slots or grant authority to supplied new identities.
    """
    result = _complete(kind, params)
    if _positional(kind, result):
        # Resolve each position to its occupant immediately before this child
        # (structured missing_reference on an empty slot), then apply the
        # version-1 strand/end/domain checks to the resolved targets.
        bind_prefix(kind, resolve_positions(kind, result, prefix), prefix)
        return result
    references = _references(kind, result)
    resources = {item["kind"] for item in references}
    output_resource = ("crossover" if kind in {"crossover-place", "crossover-place-batch"}
                       else "forced_ligation" if kind == "forced-ligation-create" else None)
    if output_resource:
        resources.add(output_resource)
    objects, duplicates = _inventories(prefix, resources)
    missing = [item for item in references if item["identity"] not in objects[item["kind"]]]
    if missing:
        raise ReferenceResolutionError("Routing targets no longer exist.", references=missing)
    ambiguous = [item for item in references if item["identity"] in duplicates[item["kind"]]]
    if ambiguous:
        raise ReferenceResolutionError("Routing targets are ambiguous.", code="invalid_selection", references=ambiguous)
    if output_resource:
        outputs = ([(_reference("crossover", item["crossover_id"], ["placements", i, "crossover_id"]))
                    for i, item in enumerate(result["placements"])] if kind.endswith("-batch")
                   else [_reference(output_resource, result["crossover_id" if output_resource == "crossover" else "_fl_id"],
                                    ["crossover_id" if output_resource == "crossover" else "_fl_id"])])
        collisions = [item for item in outputs if item["identity"] in objects[output_resource]]
        if collisions:
            raise ReferenceResolutionError("Routing output identity already exists at this prefix.",
                                           code="invalid_selection", references=collisions)
    if kind in {"strand-end-resize", "domain-shift"}:
        for index, item in enumerate(result["entries"]):
            strand = objects["strand"][item["strand_id"]]
            if kind == "domain-shift":
                ordinal = item["domain_index"]
                if ordinal >= len(strand.domains):
                    raise ReferenceResolutionError("Selected routing domain no longer exists.", references=[
                        _reference("domain", f"{strand.id}:{ordinal}", ["entries", index, "domain_index"])])
            elif not strand.domains or strand.domains[0 if item["end"] == "5p" else -1].helix_id != item["helix_id"]:
                raise ReferenceResolutionError("Selected strand end is not on the specified helix.", code="invalid_selection",
                    references=[_reference("strand", strand.id, ["entries", index, "strand_id"]),
                                _reference("helix", item["helix_id"], ["entries", index, "helix_id"])])
    elif kind == "forced-ligation-create":
        a, b = (objects["strand"][result[name]] for name in ("three_prime_strand_id", "five_prime_strand_id"))
        if a.id == b.id or not a.domains or not b.domains:
            raise ReferenceResolutionError("Forced ligation requires distinct strands with terminal domains.",
                                           code="invalid_selection", references=references)
    elif kind == "loop-skip-insert" and result["delta"] != 0:
        helix = objects["helix"][result["helix_id"]]
        if not helix.bp_start <= result["bp_index"] < helix.bp_start + helix.length_bp:
            raise ReferenceResolutionError("Loop/skip position is outside the selected helix.",
                                           code="invalid_selection", references=references)
    return result
