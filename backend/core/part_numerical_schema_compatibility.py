"""Explicit equivalence for reviewed, non-numerical schema transitions.

This helper belongs to every participating engine's implementation manifest.
The fixed policy JSON is separately reviewed host trust policy: including its
own current-manifest hashes in those manifests would create a hash cycle.
There is no inferred compatibility, transitive upgrade, or replacement pin.
"""

from contextlib import contextmanager
from contextvars import ContextVar
import json
from pathlib import Path
import re

from backend.core.part_numerical_runtime import digest


POLICY_PATH = Path(__file__).resolve().parent / "data/numerical_schema_compatibility_v1.json"
_SCHEMA = "nadoc.numerical-schema-compatibility.v1"
_MAX_BYTES = 16 * 1024
_MAX_TRANSITIONS = 16
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = frozenset({"id", "event", "source_checkpoint", "engine_id", "from_sha256",
                     "to_sha256", "changed_paths", "rationale"})
_COLLECTOR = ContextVar("numerical_schema_compatibility", default=None)


@contextmanager
def collect_implementation_compatibility():
    """Collect bounded diagnostic evidence for this explicit verification only."""
    result = {"transitions": [], "truncated": False}
    token = _COLLECTOR.set(result)
    try:
        yield result
    finally:
        _COLLECTOR.reset(token)


def _record(entry):
    collector = _COLLECTOR.get()
    if collector is None:
        return
    record = {"transition_id": entry["id"], "engine_id": entry["engine_id"],
              "from_sha256": entry["from_sha256"], "to_sha256": entry["to_sha256"]}
    if record in collector["transitions"]:
        return
    if len(collector["transitions"]) == 3:
        collector["truncated"] = True
    else:
        collector["transitions"].append(record)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate policy key")
        result[key] = value
    return result


def _nonfinite(_value):
    raise ValueError("Non-finite policy value")


def _text(value, maximum):
    return type(value) is str and 0 < len(value) <= maximum


def _hash(value):
    return type(value) is str and _HASH.fullmatch(value) is not None


def _policy():
    # Read a bounded private file only when exact-current validation failed.
    # No cache can retain policy authority after a deployment changes the file.
    with POLICY_PATH.open("rb") as stream:
        payload = stream.read(_MAX_BYTES + 1)
    if len(payload) > _MAX_BYTES:
        raise ValueError("Compatibility policy exceeds its byte bound")
    policy = json.loads(payload, object_pairs_hook=_object, parse_constant=_nonfinite)
    if (type(policy) is not dict or set(policy) != {"schema", "transitions"}
            or policy["schema"] != _SCHEMA or type(policy["transitions"]) is not list
            or len(policy["transitions"]) > _MAX_TRANSITIONS):
        raise ValueError("Unsupported compatibility policy")
    identities, edges = set(), set()
    for entry in policy["transitions"]:
        if type(entry) is not dict or set(entry) != _FIELDS:
            raise ValueError("Unsupported compatibility transition")
        if (not all(_text(entry[name], 128) for name in ("id", "event", "engine_id"))
                or not _text(entry["rationale"], 1024)
                or type(entry["source_checkpoint"]) is not str
                or re.fullmatch(r"[0-9a-f]{7,40}", entry["source_checkpoint"]) is None
                or not _hash(entry["from_sha256"]) or not _hash(entry["to_sha256"])
                or entry["from_sha256"] == entry["to_sha256"]):
            raise ValueError("Invalid compatibility transition identity")
        paths = entry["changed_paths"]
        if (type(paths) is not list or not 0 < len(paths) <= 8
                or any(not _text(path, 256) or not path.startswith("backend/")
                       or "\\" in path or any(part in {"", ".", ".."} for part in path.split("/"))
                       for path in paths)
                or len(set(paths)) != len(paths)):
            raise ValueError("Invalid reviewed source path inventory")
        edge = (entry["engine_id"], entry["from_sha256"], entry["to_sha256"])
        if entry["id"] in identities or edge in edges:
            raise ValueError("Ambiguous compatibility transition")
        identities.add(entry["id"])
        edges.add(edge)
    return policy["transitions"]


def require_implementation(engine_id, authored_sha256, manifest, *, error_type, detail):
    """Return the applied transition ID, or None for the unchanged exact check.

    The caller retains its native runtime/template checks and error family. An old
    pin is accepted only for one explicit engine and the entire reviewed current
    manifest. A later source/data/helper change requires another reviewed decision.
    """
    try:
        current_sha256 = digest(manifest)
        if not _hash(authored_sha256):
            raise ValueError("Invalid authored implementation hash")
        if authored_sha256 == current_sha256:
            return None
        if type(manifest) is not dict or manifest.get("id") != engine_id:
            raise ValueError("Compatibility engine identity differs")
        for entry in _policy():
            if (entry["engine_id"] == engine_id and entry["from_sha256"] == authored_sha256
                    and entry["to_sha256"] == current_sha256):
                _record(entry)
                return entry["id"]
    except (OSError, TypeError, ValueError, RecursionError):
        pass
    raise error_type(detail, code="engine_mismatch")
