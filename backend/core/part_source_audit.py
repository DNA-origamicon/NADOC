"""Explicit portable-input diagnostics for current and inactive part branches.

This is a file/branch inspection, never a native-proof dependency. Recovery
snapshots are decoded only when the caller explicitly requests loadout auditing.
No source is substituted, discarded, or fetched from a cache or network.
"""

from backend.core.part_command_errors import CommandContractError
from backend.core.part_document_io import MAX_DOCUMENT_BYTES, decode_snapshot_bytes
from backend.core.part_input_sources import EmbeddedResolver, InputSource, command_source_bindings

MAX_LOADOUTS = 256
MAX_AUDIT_BYTES = 512 * 1024 * 1024
MAX_AUDIT_ENTRIES = 20_000


def audit_current_sources(design, *, loadout_id=None):
    """Report source evidence independently of scientific/model validity."""
    from backend.core.part_overlay_commands import command_input

    result = {"complete": True, "sources": [], "issues": []}
    if loadout_id is not None:
        result["loadout_id"] = loadout_id

    def issue(error, *, feature_id=None, parameter=None):
        detail = error.as_issue() if isinstance(error, CommandContractError) else {
            "code": "invalid_source_contract", "detail": str(error)}
        if parameter is not None and "references" in detail:
            detail["references"] = [{**reference, "parameter_path": [parameter]}
                                    for reference in detail["references"]]
        result["issues"].append({"status": "unverified", **detail,
            **({"loadout_id": loadout_id} if loadout_id is not None else {}),
            **({"feature_id": feature_id} if feature_id is not None else {})})

    try:
        resolver = EmbeddedResolver(design.input_sources)
    except (ValueError, TypeError) as error:
        issue(error)
        result["complete"] = False
        return result
    descriptors = {}
    checked = {}
    entries = 0
    for entry in design.feature_log:
        entries += 1
        if entries > MAX_AUDIT_ENTRIES:
            issue(CommandContractError("Source audit entry budget exceeded", code="source_audit_limit"))
            result["complete"] = False
            result["sources"] = list(descriptors.values())
            return result
        children = entry.children if entry.feature_type == "routing-cluster" else [entry]
        for child in children:
            if child is not entry:
                entries += 1
            if entries > MAX_AUDIT_ENTRIES:
                issue(CommandContractError("Source audit entry budget exceeded", code="source_audit_limit"))
                result["complete"] = False
                result["sources"] = list(descriptors.values())
                return result
            try:
                kind, params = command_input(child)
                for parameter, source in command_source_bindings(kind, params):
                    descriptors[source.sha256] = source.model_dump(mode="json")
                    key = source.sha256, source.size_bytes
                    if key not in checked:
                        try:
                            resolver(source)
                            checked[key] = None
                        except CommandContractError as error:
                            checked[key] = error
                    if checked[key] is not None:
                        issue(checked[key], feature_id=child.id, parameter=parameter)
            except (ValueError, TypeError) as error:
                issue(error, feature_id=child.id)
    # Retained bytes can be used by undo or a later explicit repair. Check them
    # too, but do not count a source already reported missing/corrupt twice.
    for digest, blob in design.input_sources.items():
        if digest in descriptors:
            continue
        try:
            encoded = blob.data_b64
            size = (len(encoded) // 4) * 3 - (len(encoded) - len(encoded.rstrip("=")))
            source = InputSource(sha256=digest, size_bytes=max(0, size),
                                 format="blob", media_type="application/octet-stream")
            descriptors[digest] = source.model_dump(mode="json")
            resolver(source)
        except (ValueError, TypeError) as error:
            issue(error)
    result["sources"] = list(descriptors.values())
    return result


def audit_loadout_sources(design, *, max_bytes=MAX_AUDIT_BYTES, max_loadouts=MAX_LOADOUTS):
    """Inspect each embedded branch once with cumulative decoded-byte bounds."""
    from backend.core.models import Design

    result = {"complete": True, "loadouts": [], "issues": []}
    remaining = max_bytes
    for index, loadout in enumerate(design.loadouts):
        if index >= max_loadouts or remaining <= 0:
            result["complete"] = False
            result["issues"].append({"status": "unverified", "code": "source_audit_limit",
                "detail": "Inactive loadout source audit budget exceeded",
                "loadout_id": loadout.id, "remaining_loadouts": len(design.loadouts) - index})
            break
        branch_limit = min(MAX_DOCUMENT_BYTES, remaining)
        raw = None
        try:
            raw = decode_snapshot_bytes(loadout.design_snapshot_gz_b64,
                                        limit=branch_limit)
            remaining -= len(raw)
            restored = Design.model_validate_json(raw)
            branch = audit_current_sources(restored, loadout_id=loadout.id)
            if restored.loadouts:
                branch["complete"] = False
                branch["issues"].append({"status": "unverified", "code": "nested_loadout_sources",
                    "loadout_id": loadout.id,
                    "detail": "Nested legacy loadouts require separate inspection"})
            del restored
            raw = None
        except (ValueError, TypeError) as error:
            if raw is None:
                # A CRC/limit failure may happen after consuming the entire
                # permitted output. Charge its allowance before another branch.
                remaining -= branch_limit
            detail = error.as_issue() if hasattr(error, "as_issue") else {
                "code": "loadout_unavailable", "detail": str(error)}
            branch = {"complete": False, "loadout_id": loadout.id, "sources": [],
                      "issues": [{"status": "unverified", **detail, "loadout_id": loadout.id}]}
        result["loadouts"].append(branch)
        result["complete"] = result["complete"] and branch["complete"]
    return result


def with_source_warnings(response, design, *, loadout_id=None):
    """Thin load/activation seam; ordinary design responses never call this."""
    audit = audit_current_sources(design, loadout_id=loadout_id)
    if audit["issues"]:
        response["source_warnings"] = audit["issues"]
    return response
