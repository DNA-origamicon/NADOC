"""Frozen legacy routing result: a verified stand-in for an unreplayable legacy row.

Legacy auto-scaffold/autostaple rows never recorded the ``history_seed`` their
native contracts require, so they cannot be regenerated with their saved
identities. Those kinds are deformation-independent (tests/test_part_replay_cache.py):
their output topology is a function of input topology alone, and they pass
deformations through. A frozen row therefore stores the row's saved output
topology plus a digest of its saved input topology, and replays as:

    input topology == saved input topology  ->  saved output topology,
                                                 deformations passed through
    otherwise                               ->  refuse (an upstream topology edit
                                                 would need the real command)

This is exactly what re-running the original command would produce whenever it
runs at all, so upstream Bend/Twist (geometry-only) edits replay through it. It
never guesses a new routing result.
"""

import base64
import gzip
import json

from backend.core.part_history_proof import AUTHORING_FIELDS, digest

MARKER = "_frozen_legacy"  # params key: the row keeps its original routing kind
VERSION = 1
# Document-level settings are not produced by routing commands (see legacy conversion).
DOCUMENT_FIELDS = frozenset({"metadata", "tm_settings", "dimensions"})
TOPOLOGY_FIELDS = frozenset(AUTHORING_FIELDS - {"deformations"} - DOCUMENT_FIELDS)


def topology_digest(design):
    return digest(design.model_dump(mode="json", include=set(TOPOLOGY_FIELDS)))


def is_frozen(params):
    return type(params) is dict and MARKER in params


def params_for(pre, post, *, legacy_params):
    output = post.model_dump(mode="json", include=set(TOPOLOGY_FIELDS))
    payload = base64.b64encode(gzip.compress(json.dumps(output, separators=(",", ":")).encode(), 3)).decode()
    return {**legacy_params, "_proof_version": VERSION,
            MARKER: {"input_sha256": topology_digest(pre), "output_gz_b64": payload}}


def valid_params(params):
    frozen = params.get(MARKER) if type(params) is dict else None
    return (params.get("_proof_version") == VERSION and type(frozen) is dict
            and type(frozen.get("input_sha256")) is str and len(frozen["input_sha256"]) == 64
            and type(frozen.get("output_gz_b64")) is str and frozen["output_gz_b64"])


def build(kind, design, params):
    from backend.core.models import Design

    if not valid_params(params):
        raise ValueError("Invalid frozen legacy routing result")
    frozen = params[MARKER]
    if topology_digest(design) != frozen["input_sha256"]:
        raise ValueError(
            f"This frozen legacy {kind} result only replays on its original "
            "upstream topology; an upstream topology change needs the original command, "
            "which this legacy file cannot regenerate")
    output = json.loads(gzip.decompress(base64.b64decode(frozen["output_gz_b64"])))
    if set(output) - TOPOLOGY_FIELDS:
        raise ValueError("Frozen legacy result contains non-topology fields")
    return Design.model_validate({**design.model_dump(mode="json"), **output})
