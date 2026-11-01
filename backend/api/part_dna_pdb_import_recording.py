"""Prepare an ordinary DNA PDB navigation using the existing converter only."""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException

from backend.api import part_dna_pdb_commands as commands, state
from backend.api.part_recovery_budget import RecoveryBudget
from backend.core.models import SnapshotLogEntry
from backend.core.part_dna_pdb_source import MAX_SOURCE_BYTES, parse_source
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import ProofBudgetExceeded
from backend.core.part_input_sources import EmbeddedResolver, SourceContractError, describe, embed


def prepare_ordinary(content):
    if len(content) > MAX_SOURCE_BYTES:
        return None, "DNA PDB source exceeds the 200,000-byte reproducible conversion allowance"
    raw = content.encode("utf-8")
    source = describe(raw, format="dna-pdb", media_type="chemical/x-pdb")
    try:
        parse_source(raw, source)
    except SourceContractError as error:
        return None, str(error)
    # Structural selection is now closed: native preparation failures never
    # retry the converter through a different path or publish half a lineage.
    from backend.api.crud import _design_response
    from backend.core.validator import validate_design
    initial = create_empty_part("PDB Import", "HONEYCOMB").copy_with(input_sources={source.sha256: embed(source, raw)})
    params = {"_proof_version": 1, "pdb_import_version": 1, "importer_version": 1,
        "source": source.model_dump(mode="json"), "history_seed": str(uuid4()),
        "identity_policy": "source-content-v1", "loss_policy": "existing-duplex-projection-v1", "name_override": None}
    try:
        budget = RecoveryBudget()
        pre, pre_size = state.encode_design_snapshot(initial)
        budget.charge(pre)
        candidate, warnings, atoms = commands.evaluate("dna-pdb-import", initial, params,
            resolver=EmbeddedResolver(initial.input_sources))
        post, post_size = state.encode_design_snapshot(candidate)
        budget.charge(post)
    except ProofBudgetExceeded as error:
        raise HTTPException(413, detail={"status": "unverified", "code": "command_limit", "detail": str(error)}) from error
    entry = SnapshotLogEntry(op_kind="dna-pdb-import", label="Import DNA PDB",
        timestamp=datetime.now(timezone.utc).isoformat(), params=params,
        design_snapshot_gz_b64=pre, snapshot_size_bytes=pre_size,
        post_state_gz_b64=post, post_state_size_bytes=post_size)
    candidate = candidate.copy_with(feature_log=[entry])
    response = _design_response(candidate, validate_design(candidate), full_feature_log=True)
    if warnings:
        response["import_warnings"] = warnings
    response["import_history"] = {"status": "reproduced_import", "native_editable": False,
                                  "loss_policy": "existing-duplex-projection-v1"}
    return (candidate, atoms, response), None
