"""Bounded historical choices for Fine Routing, with no display geometry."""

import json

from backend.core.part_capture_graph import GraphBudget
from backend.core.part_command_errors import CommandContractError
from backend.api.part_model_serialization import admit_model_serialization


MAX_ITEMS = 30_000
MAX_BYTES = 2_000_000
COLLECTIONS = ("helices", "strands", "crossovers", "forced_ligations")


def _invalid(message):
    raise CommandContractError(message, code="invalid_routing_result")


def inventory(source):
    budget = GraphBudget(max_nodes=MAX_ITEMS, max_bytes=MAX_BYTES, seconds=None, clock=lambda: 0)
    if any(type(getattr(source, name)) is not list for name in COLLECTIONS):
        _invalid("Historical routing choices require native collections")
    if sum(len(getattr(source, name)) for name in COLLECTIONS) > MAX_ITEMS:
        _invalid("Historical routing choices exceed their metadata allowance")
    result = {name: [] for name in COLLECTIONS}
    fields = {
        "helices": {"id", "bp_start", "length_bp"},
        "crossovers": {"id", "half_a", "half_b", "extra_bases"},
        "forced_ligations": {"id", "three_prime_helix_id", "three_prime_bp", "three_prime_direction",
                            "five_prime_helix_id", "five_prime_bp", "five_prime_direction", "extra_bases"},
    }
    for name in COLLECTIONS:
        for item in getattr(source, name):
            if name == "strands":
                if len(item.domains) > MAX_ITEMS:
                    _invalid("Historical strand domain choices exceed their metadata allowance")
                record = {"id": item.id, "name": item.name, "is_scaffold": item.is_scaffold, "domains": []}
                budget.charge({key: value for key, value in record.items() if key != "domains"})
                for domain in item.domains:
                    value = {"helix_id": domain.helix_id, "start_bp": domain.start_bp,
                             "end_bp": domain.end_bp, "direction": domain.direction.value}
                    budget.charge(value)
                    record["domains"].append(value)
            else:
                # Admission precedes serialization even for unbounded sequence strings.
                budget.charge({key: getattr(item, key) for key in fields[name]})
                record = item.model_dump(mode="json", include=fields[name])
            result[name].append(record)
    budget.finish()
    return result


def _same_json(left, right):
    # Python container equality otherwise treats true, 1 and 1.0 as identical.
    # Both trees have already passed expanded serialization admission.
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(_same_json(value, right[key]) for key, value in left.items())
    if type(left) is list:
        return len(left) == len(right) and all(_same_json(a, b) for a, b in zip(left, right))
    return left == right


def _identity(value):
    return type(value) is str and 1 <= len(value) <= 512


def _integer(value):
    return type(value) is int


def _direction(value):
    return type(value) is str and value in {"FORWARD", "REVERSE"}


def _text_or_null(value):
    return value is None or type(value) is str


def _fields(value, schema):
    return (type(value) is dict and value.keys() == schema.keys()
            and all(check(value[key]) for key, check in schema.items()))


def _domains(value):
    schema = {"helix_id": _identity, "start_bp": _integer, "end_bp": _integer, "direction": _direction}
    return type(value) is list and all(_fields(domain, schema) for domain in value)


def _half(value):
    return _fields(value, {"helix_id": _identity, "index": _integer, "strand": _direction})


_SCHEMAS = {
    "helices": {"id": _identity, "bp_start": _integer, "length_bp": _integer},
    "strands": {"id": _identity, "name": _text_or_null,
                "is_scaffold": lambda value: type(value) is bool, "domains": _domains},
    "crossovers": {"id": _identity, "half_a": _half, "half_b": _half, "extra_bases": _text_or_null},
    "forced_ligations": {"id": _identity, "three_prime_helix_id": _identity,
        "three_prime_bp": _integer, "three_prime_direction": _direction,
        "five_prime_helix_id": _identity, "five_prime_bp": _integer,
        "five_prime_direction": _direction, "extra_bases": _text_or_null},
}


def validate_packet(packet, *, kind, design_id, revision, feature_id, child_id, expected_params):
    if (type(packet) is not dict or set(packet) != {"kind", "params", "prefix", "source_design_id",
            "source_revision", "feature_id", "child_id"}
            or packet["kind"] != kind or packet["source_design_id"] != design_id
            or type(packet["source_revision"]) is not int or packet["source_revision"] != revision
            or packet["feature_id"] != feature_id or packet["child_id"] != child_id
            or type(packet["params"]) is not dict or type(expected_params) is not dict
            or type(packet["prefix"]) is not dict
            or set(packet["prefix"]) != set(COLLECTIONS)):
        _invalid("Historical routing choices differ from the owned child")
    admit_model_serialization(packet, max_nodes=MAX_ITEMS, max_bytes=MAX_BYTES,
                              label="Historical routing choices")
    admit_model_serialization(expected_params, max_nodes=MAX_ITEMS, max_bytes=MAX_BYTES,
                              label="Owned routing inputs")
    if not _same_json(packet["params"], expected_params):
        _invalid("Historical routing choices differ from the owned inputs")
    for name in COLLECTIONS:
        records = packet["prefix"][name]
        if type(records) is not list or any(not _fields(row, _SCHEMAS[name]) for row in records):
            _invalid("Historical routing choices contain malformed native metadata")
        if len({row["id"] for row in records}) != len(records):
            _invalid("Historical routing choices contain ambiguous identities")
    encoded = json.dumps(packet, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_BYTES:
        _invalid("Historical routing choices exceed their serialized allowance")
    return json.loads(encoded)
