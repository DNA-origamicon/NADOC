"""Resolve terminal-extension inputs under the same lock as their one history write."""

from uuid import uuid4
from fastapi import HTTPException

from backend.api import state
from backend.api.feature_recording import record_feature
from backend.api.part_extension_commands import MAX_ENTRIES, build, parse_command
from backend.core.part_command_errors import CommandContractError


def record(action, values, *, extension_id=None):
    if len(values) > MAX_ENTRIES:
        raise HTTPException(422, detail="Too many extension edits in one operation")
    with state._lock:
        state._require_compatibility_write("extension_authoring")
        session = state._session()
        source = session.design
        if source is None:
            raise HTTPException(404, detail="No active design.")
        state._assert_active_loadout_editable(source)
        if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
            raise HTTPException(
                409,
                detail="Return to the latest history position before editing extensions.",
            )
        if action == "delete":
            ids = list(dict.fromkeys(values))
            if not ids:
                return source, state.validate_design(source), []
            kind, params = (
                "extension-delete",
                {"_proof_version": 1, "extension_ids": ids},
            )
        else:
            by_end = {(ext.strand_id, ext.end): ext for ext in source.extensions}
            by_id = {ext.id: ext for ext in source.extensions}
            entries = {}
            if action == "update":
                old = by_id.get(extension_id)
                if old is None:
                    raise HTTPException(
                        404, detail=f"StrandExtension {extension_id!r} not found."
                    )
                value = old.model_dump(mode="json")
                for key, item in values[0].items():
                    if item is not None:
                        value[key] = (
                            None
                            if key in {"sequence", "modification"} and item == ""
                            else item
                        )
                values = [value]
            for item in values:
                key = item["strand_id"], item["end"]
                old = by_end.get(key)
                if action == "create" and old is not None:
                    raise HTTPException(
                        400,
                        detail=f"Strand {key[0]!r} already has a {key[1]} extension.",
                    )
                previous = entries.get(key)
                identity = (
                    old.id
                    if old
                    else previous["extension"]["id"]
                    if previous
                    else str(uuid4())
                )
                sequence = item.get("sequence")
                # Preserve existing batch last-item-wins and empty-sequence semantics.
                if action == "batch" and sequence == "":
                    sequence = None
                ext = {
                    "id": identity,
                    "strand_id": key[0],
                    "end": key[1],
                    "sequence": sequence.upper()
                    if isinstance(sequence, str)
                    else sequence,
                    "modification": item.get("modification"),
                    "label": item.get("label"),
                }
                entry = {"create": old is None, "extension": ext}
                # Validate every supplied item before last-item-wins coalescing.
                # A later valid duplicate must not hide an invalid earlier edit.
                try:
                    parse_command(
                        "extension-upsert", {"_proof_version": 1, "entries": [entry]}
                    )
                except CommandContractError as error:
                    raise HTTPException(400, detail=error.as_issue()) from error
                entries[key] = entry
            if not entries:
                return source, state.validate_design(source), []
            kind, params = (
                "extension-upsert",
                {"_proof_version": 1, "entries": list(entries.values())},
            )
        try:
            # Resolve all references and build privately before recorder snapshots.
            candidate = build(kind, source, params)
            result, report, _entry = record_feature(
                session,
                kind,
                "Remove terminal extensions"
                if action == "delete"
                else "Edit terminal extensions",
                params,
                lambda _source: candidate,
            )
        except CommandContractError as error:
            status = 404 if error.code == "missing_reference" else 400
            raise HTTPException(status, detail=error.as_issue()) from error
        return (
            result,
            report,
            params.get(
                "extension_ids",
                [item["extension"]["id"] for item in params.get("entries", [])],
            ),
        )
