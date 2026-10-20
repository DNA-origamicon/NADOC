"""Read-only command relationships from the same contracts used by replay."""
from time import monotonic

from fastapi import HTTPException

from backend.api import state
from backend.api.part_proof_commands import dependencies
from backend.core.part_dependencies import DependencyIndex
from backend.core.part_history_proof import command_rows


def current_dependencies():
    source, revision = state.get_design_with_revision()
    if source is None:
        raise HTTPException(404, detail="No part is open")
    # Read only saved inputs, never geometry or recovery snapshots. Holding the
    # document lock keeps the returned graph and revision from different edits.
    with state._lock:
        session = state._session()
        if session.design is not source or session.revision != revision:
            raise HTTPException(409, detail="The part changed. Reopen its dependencies.")
        deadline = monotonic() + .5
        metadata = {}
        for index, entry in enumerate(source.feature_log):
            children = entry.children if entry.feature_type == "routing-cluster" else []
            for child in children or [entry]:
                if len(metadata) >= 10_000 or monotonic() > deadline:
                    raise HTTPException(413, detail="History dependency view exceeds its bounded read allowance")
                if child.id in metadata:
                    raise HTTPException(409, detail="History feature identities are ambiguous")
                kind = getattr(getattr(child, "op_snapshot", None), "type", child.feature_type)
                metadata[child.id] = {"id": child.id, "row_index": index,
                    "label": str(getattr(child, "label", None) or getattr(child, "op_kind", None) or kind)[:256]}
        graph, features = DependencyIndex(), []
        try:
            for identity, kind, params in command_rows(source, 10_000):
                if monotonic() > deadline:
                    raise HTTPException(408, detail="History dependency view time limit")
                contract = dependencies(kind, params)
                graph.append(identity, contract)
                features.append({**metadata[identity], "known": contract.known,
                    "conservative": contract.barrier or not contract.known})
        except (ValueError, KeyError, TypeError) as error:
            raise HTTPException(409, detail=f"History dependencies unavailable: {error}") from error
        for feature in features:
            identity = feature["id"]
            feature.update(parents=sorted(graph.parents[identity]), children=sorted(graph.children[identity]))
        return {"design_id": source.id, "revision": revision, "complete": graph.complete, "features": features}
