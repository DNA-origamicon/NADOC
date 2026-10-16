"""Strict reference checks at the native recipe boundary.

Some established interactive batch builders intentionally skip missing or
inapplicable targets. Recipe replay must diagnose those inputs: silently doing
less work would conceal a broken dependency. These checks do not change the
legacy live builders, and only index the object families a command references.
"""

from backend.core.part_command_errors import CommandReference, ReferenceResolutionError


def _reference(kind: str, identity: str, path: list[str | int]) -> CommandReference:
    return {"kind": kind, "identity": identity, "parameter_path": path}


def validate_command_references(kind, design, params):
    """Reject missing targets before executing a permissive native builder."""
    references = []
    if kind == "nick":
        references = [_reference("helix", params["helix_id"], ["helix_id"])]
    elif kind == "nick-batch":
        references = [
            _reference("helix", nick["helix_id"], ["nicks", i, "helix_id"])
            for i, nick in enumerate(params["nicks"])
        ]
    elif kind == "loop-skip-clear":
        references = [
            _reference("helix", identity, ["helix_ids", i])
            for i, identity in enumerate(params["helix_ids"])
        ]
    elif kind == "overhang-bulk" and params.get("action") == "delete-selected":
        references = [
            _reference("overhang", identity, ["overhang_ids", i])
            for i, identity in enumerate(params["overhang_ids"])
        ]
    elif kind in {"domain-shift", "strand-end-resize"}:
        for i, entry in enumerate(params["entries"]):
            references.append(
                _reference("strand", entry["strand_id"], ["entries", i, "strand_id"])
            )
            if kind == "strand-end-resize":
                references.append(
                    _reference("helix", entry["helix_id"], ["entries", i, "helix_id"])
                )
    else:
        return

    fields = {"helix": "helices", "strand": "strands", "overhang": "overhangs"}
    objects = {
        resource: {item.id: item for item in getattr(design, fields[resource])}
        for resource in {reference["kind"] for reference in references}
    }
    missing = [
        reference
        for reference in references
        if reference["identity"] not in objects[reference["kind"]]
    ]
    if missing:
        raise ReferenceResolutionError(
            "Command targets no longer exist", references=missing
        )

    if kind not in {"domain-shift", "strand-end-resize"}:
        return
    for i, entry in enumerate(params["entries"]):
        strand = objects["strand"][entry["strand_id"]]
        if kind == "domain-shift":
            domain_index = int(entry["domain_index"])
            if not 0 <= domain_index < len(strand.domains):
                raise ReferenceResolutionError(
                    "Selected strand domain no longer exists",
                    references=[_reference(
                        "domain", f"{strand.id}:{domain_index}",
                        ["entries", i, "domain_index"],
                    )],
                )
        elif not strand.domains or (
            strand.domains[0 if entry["end"] == "5p" else -1].helix_id
            != entry["helix_id"]
        ):
            raise ReferenceResolutionError(
                "Selected strand end is not on the specified helix",
                code="invalid_selection",
                references=[
                    _reference("strand", strand.id, ["entries", i, "strand_id"]),
                    _reference("helix", entry["helix_id"], ["entries", i, "helix_id"]),
                ],
            )


def build_strict_nick_batch(design, params):
    """Apply every authored nick in order; a failed selection fails the command.

    Use the same native operation as the live batch, without its exception
    suppression. Sequential execution detects an already nicked site (including
    duplicate requests) and a target that disappears after an earlier nick.
    """
    from backend.api.crud import NickBatchRequest
    from backend.core.lattice import make_nick

    body = NickBatchRequest.model_validate(params)
    current = design
    for i, nick in enumerate(body.nicks):
        try:
            current = make_nick(
                current, nick.helix_id, nick.bp_index, nick.direction
            )
        except ValueError as exc:
            raise ReferenceResolutionError(
                str(exc),
                code="invalid_selection",
                references=[_reference(
                    "helix", nick.helix_id, ["nicks", i, "helix_id"]
                )],
            ) from exc
    return current
