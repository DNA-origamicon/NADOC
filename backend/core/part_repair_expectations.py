"""Lossless old-value transport for browser-authored repair actions.

The canonical text is an encoding, never authority. Decoded values still pass
unchanged strict planning expectations against the captured original definition.
"""

import json
from math import isfinite

from backend.core.part_operation_input import MAX_OPERATION_BYTES, validate_operation_input


# The enclosing action/request charges every receipt together with all other
# inputs. This local ceiling never grants another envelope's worth of work.
MAX_EXPECTATION_JSON_CHARS = MAX_OPERATION_BYTES // 4
_MAX_CONTAINER_DEPTH = 64


def _preflight(text):
    if type(text) is not str or not text or len(text) > MAX_EXPECTATION_JSON_CHARS:
        raise ValueError("Repair expected_old_json must be bounded canonical JSON text")
    # Bound nesting before the standard parser allocates nested containers.
    # This is only a string-aware work guard; json.loads validates JSON syntax.
    quoted, escaped, depth = False, False, 0
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > _MAX_CONTAINER_DEPTH:
                raise ValueError("Repair expected_old_json exceeds the nesting allowance")
        elif char in "]}":
            depth -= 1
            if depth < 0:
                raise ValueError("Repair expected_old_json has invalid container nesting")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Repair expected_old_json contains duplicate object keys")
        result[key] = value
    return result


def _integer(text):
    if len(text) > 21:
        raise ValueError("Repair expected_old_json integer exceeds the supported range")
    value = int(text)
    if value.bit_length() > 64:
        raise ValueError("Repair expected_old_json integer exceeds the supported range")
    return value


def _float(text):
    value = float(text)
    if not isfinite(value):
        raise ValueError("Repair expected_old_json numbers must be finite")
    return value


def _invalid_constant(_text):
    raise ValueError("Repair expected_old_json numbers must be finite JSON")


def encode_expected_old(value):
    """Called on the bounded privately captured value, outside the state lock."""
    validate_operation_input(value)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    _preflight(encoded)
    return encoded


def decode_expected_old(text):
    """Parse one bounded exact encoding without defaults or type inference."""
    _preflight(text)
    try:
        value = json.loads(text, object_pairs_hook=_unique_object, parse_int=_integer,
                           parse_float=_float, parse_constant=_invalid_constant)
    except (ValueError, RecursionError) as error:
        raise ValueError(f"Invalid repair expected_old_json: {error}") from error
    validate_operation_input(value)
    if encode_expected_old(value) != text:
        raise ValueError("Repair expected_old_json must use the server canonical encoding")
    return value


def _same_display_value(displayed, exact):
    """Only finite JSON numeric representation may differ on browser return."""
    pending = [(displayed, exact)]
    while pending:
        left, right = pending.pop()
        if type(left) in {int, float} and type(right) in {int, float}:
            if left != right:
                return False
        elif type(left) is not type(right):
            return False
        elif type(left) is dict:
            if left.keys() != right.keys():
                return False
            pending.extend((left[key], right[key]) for key in left)
        elif type(left) is list:
            if len(left) != len(right):
                return False
            pending.extend(zip(left, right))
        elif left != right:
            return False
    return True


def normalize_expected_old(action):
    """Normalize before SetInput construction; retain text for future reloads.

    Entire raw and normalized actions are charged. Enclosing request/draft
    validators retain their existing aggregate budgets across every action.
    Display equivalence guarantees decoding cannot smuggle a larger structure
    in place of the separately charged expected_old value.
    """
    if type(action) is not dict or action.get("expected_old_json") is None:
        return action
    validate_operation_input(action)
    if "expected_old" not in action:
        raise ValueError("Repair expected_old_json requires its displayed expected_old value")
    exact = decode_expected_old(action["expected_old_json"])
    if not _same_display_value(action["expected_old"], exact):
        raise ValueError("Repair expected_old does not match its canonical JSON encoding")
    normalized = {**action, "expected_old": exact}
    validate_operation_input(normalized)
    return normalized
