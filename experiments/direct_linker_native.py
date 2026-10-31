"""Native producer input and explicitly isolated Direct continuation.

The three Extrude rows are genuine native recipes. Proposed Connect/patch/delete
outputs are diagnostic values only: no feature row or production engine receipt
is created for them, and no application path imports this module.
"""

from contextlib import contextmanager
from unittest.mock import patch
from uuid import UUID

from backend.core.part_history_contract import create_empty_part
from experiments.direct_linker_candidate import fit_candidate

SEED = str(UUID(int=9213))


def native_source(length=46):
    from tests.conftest import valid_overhang_sites
    from tests.test_part_pending_connection_versions import append

    design = append(create_empty_part("Native Direct root review", "HONEYCOMB"), "bundle-create", {
        "_proof_version": 1, "history_seed": str(UUID(int=9210)),
        "cells": [[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3]],
        "length_bp": 42, "name": "Native Direct root review", "lattice_type": "HONEYCOMB",
    }, "bundle")
    for index, (cell, bp) in enumerate((((0, 3), 41), ((1, 1), 0)), 1):
        helix = next(h for h in design.helices if tuple(h.grid_pos) == cell)
        site = next(s for s in valid_overhang_sites(design)
                    if s["helix_id"] == helix.id and s["bp_index"] == bp and not s["is_five_prime"])
        design = append(design, "overhang-extrude", {
            "_proof_version": 1, "history_seed": str(UUID(int=9210 + index)),
            **site, "direction": site["direction"].value, "length_bp": length,
            "reuse_existing_helix": False,
        }, f"endpoint-{index}")
    return design


def connect_inputs(source, *, reverse=False):
    a, b = source.overhangs
    if reverse:
        a, b = b, a
    return {"_proof_version": 1, "history_seed": SEED, "duplex_id": "diagnostic-duplex",
            "created_at": 4., "overhang_a_id": a.id, "overhang_b_id": b.id, "binding_ids": []}


@contextmanager
def candidate_placement(reference, capture=None):
    """Inject only the placement stage of a proposed command in this process.

    The exact unbound native reference is explicit. The real command still owns
    topology, snapshot constraints, registers, child clusters and dependencies.
    Never run a production history verifier or publish its receipt inside this
    context: this is a different, unapproved molecular implementation.
    """
    from backend.core import direct_root_placement

    def place(design, driver_id, targets):
        driven = [oid for oid in targets if oid != driver_id]
        if len(driven) != 1:
            raise ValueError("Native candidate currently requires exactly two rooted overhangs")
        if capture is not None:
            capture(design, driver_id, targets)
        return fit_candidate(design, reference, driver_id, driven, list(targets))

    with patch.object(direct_root_placement, "place_direct_roots", place):
        yield


def proposed_command(source, kind, inputs, *, reference):
    from backend.api.part_duplex_commands import build

    if kind not in {"duplex-connect", "duplex-patch", "duplex-delete"}:
        raise ValueError("Only isolated Direct topology commands are supported")
    with candidate_placement(reference):
        result = build(kind, source, inputs)
    if result.feature_log != source.feature_log:
        raise ValueError("Diagnostic continuation must not acquire an authored feature row")
    return result


def proposed_connect(source, *, reverse=False):
    return proposed_command(source, "duplex-connect", connect_inputs(source, reverse=reverse), reference=source)


def connection_inputs(source, *, connection_type="end-to-root"):
    a, b = source.overhangs
    return {"_proof_version": 1, "connection_version_contract": 1,
        "version_id": "diagnostic-direct", "overhang_a_id": a.id, "overhang_b_id": b.id,
        "name": "Native Direct root review", "created_at": 4., "connection_type": connection_type,
        "overhang_a_seq": None, "overhang_b_seq": None, "bridge_length": 7, "bridge_seq": None,
        "applied": False, "action": "connection-version-connect-direct",
        "direct_composition_version": 1, "history_seed": SEED,
        "conflict_connection_ids": [], "conflict_binding_ids": [],
        "conflict_duplex_ids": [], "conflict_version_ids": []}


def proposed_connection_command(source, inputs, *, reference, capture=None):
    from backend.api.part_proof_commands import execute

    if inputs.get("action") not in {"connection-version-connect-direct", "connection-version-apply-direct",
                                     "connection-version-disconnect"}:
        raise ValueError("Only isolated Direct connection lifecycle commands are supported")
    with candidate_placement(reference, capture):
        result = execute("overhang-bulk", source, inputs)
    if result.feature_log != source.feature_log:
        raise ValueError("Diagnostic continuation must not acquire an authored feature row")
    return result
