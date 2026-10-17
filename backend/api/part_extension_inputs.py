"""Resolve ordinary extension CRUD into closed, input-only commands."""
from uuid import uuid4
from fastapi import HTTPException
from backend.api.part_extension_commands import MAX_ENTRIES, parse_command
from backend.core.part_command_errors import CommandContractError


def resolve(source, action, values, *, extension_id=None, version=1):
    if type(values) is not list or len(values) > MAX_ENTRIES:
        raise HTTPException(422, detail="Too many extension edits in one operation")
    if type(action) is not str or action not in {"create", "update", "batch", "delete"} or (action in {"create", "update"} and len(values) != 1):
        raise HTTPException(422, detail="Select a complete terminal-extension operation")
    if action == "delete":
        if any(type(value) is not str for value in values):
            raise HTTPException(422, detail="Extension deletion requires identities")
        ids = list(dict.fromkeys(values))
        if not ids:
            return None, None, []
        kind, params = (
            "extension-delete",
            {"_proof_version": version, "extension_ids": ids},
        )
    else:
        fields = {"sequence", "modification", "label"}
        if action != "update":
            fields |= {"strand_id", "end"}
        for item in values:
            if type(item) is not dict or set(item) - fields:
                raise HTTPException(422, detail="Extension edits require closed authored fields")
            if action != "update" and (type(item.get("strand_id")) is not str or type(item.get("end")) is not str):
                raise HTTPException(422, detail="Extension edits require a strand and terminus")
        if action == "update" and type(extension_id) is not str:
            raise HTTPException(422, detail="Extension update requires an identity")
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
                    "extension-upsert", {"_proof_version": version, "entries": [entry]}
                )
            except CommandContractError as error:
                raise HTTPException(400, detail=error.as_issue()) from error
            entries[key] = entry
        if not entries:
            return None, None, []
        kind, params = (
            "extension-upsert",
            {"_proof_version": version, "entries": list(entries.values())},
        )
    return kind, params, params.get("extension_ids", [item["extension"]["id"] for item in params.get("entries", [])])
