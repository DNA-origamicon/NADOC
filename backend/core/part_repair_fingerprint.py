"""Explicit, bounded identity of a repair's published definition base.

The caller supplies stable captured definitions/source records and calls this
outside the session lock. This function does not capture a concurrently mutable
Design, poll, execute commands, read recovery, or certify reproducibility.
"""

import hashlib
import json
from math import isfinite

from backend.core.part_command_errors import CommandContractError
from backend.core.part_input_sources import (
    MAX_ENCODED_BYTES, MAX_SOURCES, EmbeddedInput, SourceContractError,
    command_source_bindings, decode,
)
from backend.core.part_overlay_commands import command_input
from backend.core.part_repair_draft import RepairBaseFingerprint


MAX_ENTRIES = 2000
MAX_INPUT_BYTES = 2_000_000
MAX_INPUT_NODES = 30_000
_CHUNK = 65_536


class RepairFingerprintLimit(ValueError):
    pass


class _Budget:
    def __init__(self, nodes, size, checkpoint):
        self.nodes, self.size, self.checkpoint = nodes, size, checkpoint

    def charge(self, value):
        pending = [(value, 0)]
        while pending:
            self.checkpoint()
            item, depth = pending.pop()
            self.nodes -= 1
            self.size -= 16
            if self.nodes < 0 or self.size < 0 or depth > 64:
                raise RepairFingerprintLimit("Repair definition fingerprint exceeds its structural budget")
            if type(item) is str:
                self.size -= 4 * len(item)
            elif item is None or type(item) is bool:
                pass
            elif type(item) is int:
                if item.bit_length() > 64:
                    raise ValueError("Repair definition integer exceeds the supported range")
            elif type(item) is float:
                if not isfinite(item):
                    raise ValueError("Repair definition numbers must be finite")
            elif type(item) in {dict, list, tuple}:
                if len(item) + len(pending) > self.nodes:
                    raise RepairFingerprintLimit("Repair definition fingerprint exceeds its node budget")
                if type(item) is dict:
                    for key, child in item.items():
                        if type(key) is not str:
                            raise ValueError("Repair definition object keys must be strings")
                        self.size -= 4 * len(key)
                        pending.append((child, depth + 1))
                else:
                    pending.extend((child, depth + 1) for child in item)
            else:
                raise ValueError("Repair definitions must contain JSON-compatible values")
            if self.size < 0:
                raise RepairFingerprintLimit("Repair definition fingerprint exceeds its byte budget")


def _digest(value, checkpoint):
    digest = hashlib.sha256()
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False)
    for chunk in encoder.iterencode(value):
        checkpoint()
        digest.update(chunk.encode("utf-8"))
    return digest.hexdigest()


def _blob_digest(encoded, checkpoint):
    digest = hashlib.sha256()
    for start in range(0, len(encoded), _CHUNK):
        checkpoint()
        # Invalid base64 is still a stable, repairable base state. Preserve its
        # exact representation, including non-ASCII corruption, in the hash.
        digest.update(encoded[start:start + _CHUNK].encode("utf-8", errors="surrogatepass"))
    return digest.hexdigest()


def repair_base_fingerprint(design, *, max_entries=MAX_ENTRIES,
                            max_input_bytes=MAX_INPUT_BYTES,
                            max_input_nodes=MAX_INPUT_NODES,
                            max_source_encoded_bytes=MAX_ENCODED_BYTES,
                            checkpoint=lambda: None):
    """Hash root, ordered definition structure and published source evidence.

    Missing/corrupt source bytes get a stable fingerprint, not a successful
    verification result. Actual source checks use the existing immutable-source
    decoder. Retained inputs unused by published commands are not visited.
    Malformed source descriptors fail schema validation; this version does not
    invent bindings for them or produce a fingerprint usable by a saved draft.
    Bounds are independent of, and never raise, worker/capture admission limits.
    """
    checkpoint()
    budget = _Budget(max_input_nodes, max_input_bytes, checkpoint)
    root = design.recipe_root.model_dump(mode="json") if design.recipe_root is not None else None
    budget.charge(root)
    root_hash = _digest(root, checkpoint)
    definitions, bindings, identities = [], [], set()
    remaining_entries = max_entries

    def identify(entry):
        nonlocal remaining_entries
        checkpoint()
        remaining_entries -= 1
        if remaining_entries < 0:
            raise RepairFingerprintLimit("Repair definition fingerprint exceeds its entry budget")
        if type(entry.id) is not str or not entry.id:
            raise ValueError("Repair definitions require nonempty feature identities")
        if entry.id in identities:
            raise CommandContractError("Feature and routing-child identities must be unique",
                                       code="ambiguous_feature_identity")
        identities.add(entry.id)

    def command(entry):
        identify(entry)
        kind, params = command_input(entry)
        header = {"id": entry.id, "feature_type": entry.feature_type, "kind": kind, "params": params}
        budget.charge(header)
        for parameter, source in command_source_bindings(kind, params):
            binding = {"feature_id": entry.id, "parameter": parameter, "source": source.model_dump(mode="json")}
            budget.charge(binding)
            bindings.append((binding, source))
        return header

    for entry in design.feature_log:
        if entry.feature_type == "routing-cluster":
            identify(entry)
            header = {"id": entry.id, "feature_type": entry.feature_type}
            budget.charge(header)
            definitions.append({**header, "children": [command(child) for child in entry.children]})
        else:
            definitions.append(command(entry))
    cursor = [design.feature_log_cursor, design.feature_log_sub_cursor]
    budget.charge(cursor)
    commands_hash = _digest({"definitions": definitions, "cursor": cursor}, checkpoint)

    if len({source.sha256 for _, source in bindings}) > MAX_SOURCES:
        raise RepairFingerprintLimit("Repair fingerprint exceeds its source count budget")
    evidence, blob_hashes, checks = [], {}, {}
    remaining_sources = max_source_encoded_bytes
    for binding, source in bindings:
        checkpoint()
        blob = design.input_sources.get(source.sha256)
        item = {**binding, "state": "missing"}
        if blob is not None:
            if not isinstance(blob, EmbeddedInput):
                raise ValueError("Repair source evidence requires admitted immutable input records")
            if source.sha256 not in blob_hashes:
                remaining_sources -= len(blob.data_b64)
                if remaining_sources < 0:
                    raise RepairFingerprintLimit("Repair fingerprint exceeds its source byte budget")
                blob_hashes[source.sha256] = _blob_digest(blob.data_b64, checkpoint)
            key = (source.sha256, source.size_bytes)
            if key not in checks:
                try:
                    # decode bounds before allocating and verifies canonical
                    # base64, declared size and actual decoded SHA-256.
                    decode(source, blob)
                    checks[key] = "present"
                except SourceContractError as error:
                    checks[key] = error.code
                checkpoint()
            item.update(state=checks[key], encoded_sha256=blob_hashes[source.sha256])
        evidence.append(item)
    return RepairBaseFingerprint(version=1, root_sha256=root_hash,
        commands_sha256=commands_hash, sources_sha256=_digest(evidence, checkpoint))
