"""Independent recipe replay and complete authoring-state comparison.

Only root inputs and command parameters are executable evidence. Saved feature
outputs/diffs are neither read nor decoded. Executors are injected by the API.
"""
import hashlib
import json

from backend.core.part_dependencies import Dependencies, DependencyIndex
from backend.core.part_history_contract import FIELD_ROLES, create_empty_part


AUTHORING_FIELDS = frozenset(k for k, role in FIELD_ROLES.items() if role == "authoring")


class ProofBudgetExceeded(Exception):
    pass


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def import_root(source):
    """Explicit source capture, never called by history recovery or verification."""
    from backend.core.part_history_contract import PartRecipeRoot
    if source.feature_log or source.recipe_root is not None:
        raise ValueError("Import source must be an explicit history-free source document")
    raw = source.model_dump_json()
    return PartRecipeRoot(kind="import", source_json=raw,
                          source_sha256=hashlib.sha256(raw.encode()).hexdigest())


def root_design(root):
    from backend.core.models import Design
    if root.kind == "empty":
        if root.source_json is not None or root.source_sha256 is not None:
            raise ValueError("Empty root cannot contain imported state")
        return create_empty_part(root.initial_name, root.lattice_type)
    if not root.source_json or hashlib.sha256(root.source_json.encode()).hexdigest() != root.source_sha256:
        raise ValueError("Import source digest mismatch")
    source = Design.model_validate_json(root.source_json)
    if source.feature_log or source.recipe_root is not None:
        raise ValueError("Import source contains nested recipe/history")
    source.recipe_root = root
    return source


def command_rows(design, limit):
    count = 0
    for entry in design.feature_log:
        count += 1
        if count > limit:
            raise ValueError("entry_limit")
        children = entry.children if entry.feature_type == "routing-cluster" else [entry]
        if not children:
            yield entry.id, "empty-routing-cluster", {}
        for child in children:
            if child is not entry:
                count += 1
                if count > limit:
                    raise ValueError("entry_limit")
            kind = getattr(child, "op_kind", getattr(child, "op_subtype", child.feature_type))
            yield child.id, kind, getattr(child, "params", {})


def assess(design, *, max_entries, execute, dependencies, checkpoint):
    result = {"scope": "part", "contract_version": 1, "status": "unverified", "issues": [],
              "verification_scope": "authoring_reproducibility", "integrity_checked": False,
              "excluded_roles": ["presentation", "physical", "document_identity"],
              "checked_commands": 0, "proof_coverage": "versioned_commands", "native_editable": False}
    issues = result["issues"]
    check = checkpoint or (lambda: None)
    check()
    missing = set(type(design).model_fields) - FIELD_ROLES.keys()
    if missing:
        issues.append({"code": "unclassified_fields", "fields": sorted(missing)})
        return result
    root = design.recipe_root
    if root is None:
        issues.append({"code": "missing_recipe_root"})
    elif root.version != 1:
        issues.append({"code": "unsupported_root_version", "version": root.version})
    if design.feature_log_cursor != -1 or design.feature_log_sub_cursor is not None:
        issues.append({"code": "historical_cursor"})
    rows = []
    index = DependencyIndex()
    try:
        for feature_id, kind, params in command_rows(design, max_entries):
            check()
            contract = dependencies(kind, params) if dependencies else Dependencies(known=False)
            index.append(feature_id, contract)
            rows.append((feature_id, kind, params, contract))
            if not contract.known or execute is None:
                code = "empty_routing_cluster" if kind == "empty-routing-cluster" else "missing_proof_contract"
                issues.append({"code": code, "feature_id": feature_id, "kind": kind})
    except (ValueError, KeyError, TypeError) as exc:
        issues.append({"code": "entry_limit" if str(exc) == "entry_limit" else "invalid_command", "detail": str(exc)})
        return result
    result["dependencies"] = index.as_dict()
    result["recipe_fingerprint"] = digest({"contract": 1, "root": root.model_dump(mode="json") if root else None,
        "commands": [(fid, kind, params) for fid, kind, params, _ in rows],
        "cursor": [design.feature_log_cursor, design.feature_log_sub_cursor]})
    result["authoring_fingerprint"] = digest(design.model_dump(mode="json", include=AUTHORING_FIELDS))
    if issues:
        return result
    try:
        rebuilt = root_design(root)
    except (ValueError, TypeError) as exc:
        issues.append({"code": "invalid_recipe_root", "detail": str(exc)})
        return result
    for feature_id, kind, params, _ in rows:
        check()
        try:
            rebuilt = execute(kind, rebuilt, params)
        except ProofBudgetExceeded as exc:
            issues.append({"code": "command_limit", "feature_id": feature_id, "detail": str(exc)})
            return result
        except Exception as exc:
            result["status"] = "failed"
            issues.append({"code": "command_failed", "feature_id": feature_id,
                           "detail": str(exc), "blocked": sorted(index.affected([feature_id]) - {feature_id})})
            return result
        result["checked_commands"] += 1
    check()
    mismatches = sorted(name for name in AUTHORING_FIELDS if getattr(design, name) != getattr(rebuilt, name))
    if mismatches:
        result["status"] = "mismatch"
        issues.append({"code": "authoring_state_mismatch", "fields": mismatches})
    else:
        result["status"] = "verified" if root.kind == "empty" else "reproduced_import"
        result["native_editable"] = root.kind == "empty"
    return result
