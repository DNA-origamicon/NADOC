"""Independent recipe replay and complete authoring-state comparison.

Only root inputs and command parameters are executable evidence. Saved feature
outputs/diffs are neither read nor decoded. Executors are injected by the API.
"""
import hashlib
import json

from backend.core.part_dependencies import Dependencies, DependencyIndex
from backend.core.part_command_errors import CommandContractError
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
    raw = source.model_dump_json(exclude={"repair_draft"})
    return PartRecipeRoot(kind="import", source_json=raw,
                          source_sha256=hashlib.sha256(raw.encode()).hexdigest())


def root_design(root, *, input_sources=None):
    from backend.core.models import Design
    if root.kind == "empty":
        if root.source_json is not None or root.source_sha256 is not None:
            raise ValueError("Empty root cannot contain imported state")
        return create_empty_part(root.initial_name, root.lattice_type).copy_with(
            input_sources=dict(input_sources or {}))
    if not root.source_json or hashlib.sha256(root.source_json.encode()).hexdigest() != root.source_sha256:
        raise ValueError("Import source digest mismatch")
    source = Design.model_validate_json(root.source_json)
    if source.feature_log or source.recipe_root is not None:
        raise ValueError("Import source contains nested recipe/history")
    if source.repair_draft is not None:
        raise ValueError("Import source contains repair draft metadata")
    source.recipe_root = root
    if input_sources is not None:
        source = source.copy_with(input_sources=dict(input_sources))
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
            from backend.core.part_overlay_commands import command_input
            kind, params = command_input(child)
            if child is not entry:
                from backend.core.part_group_organization import KINDS
                if kind in KINDS:
                    # Routing diffs currently carry topology collections only.
                    # A proof must not certify a row whose recovery drops groups.
                    raise ValueError("group_organization_requires_snapshot")
                if kind == "placement-poses":
                    raise ValueError("placement_poses_requires_snapshot")
            yield child.id, kind, params


def assess(design, *, max_entries, execute, dependencies, checkpoint):
    """Report reproduction and bounded structural closure as separate facts."""
    from backend.core.part_structure import assess_structure
    from backend.core.part_structure_gate import PartStructureError
    from backend.core.part_numerical_schema_compatibility import collect_implementation_compatibility

    with collect_implementation_compatibility() as compatibility:
        result = _assess_recipe(design, max_entries=max_entries, execute=execute,
                                dependencies=dependencies, checkpoint=checkpoint)
    if compatibility["transitions"] or compatibility["truncated"]:
        result["numerical_compatibility"] = compatibility
    result["reproducibility_status"] = result["status"]
    structure = assess_structure(design, checkpoint=checkpoint)
    result["structure"] = structure
    if structure["status"] != "valid":
        error = PartStructureError(structure)
        issue = error.as_issue()
        if origin := result.get("structure_origin"):
            issue.update(feature_id=origin["feature_id"], kind=origin["kind"],
                         possible_dependents=origin["possible_dependents"])
        result["issues"].append(issue)
        if result["status"] in {"verified", "reproduced_import"}:
            result["status"] = error.status
        result["native_editable"] = False
    return result


def _assess_recipe(design, *, max_entries, execute, dependencies, checkpoint):
    result = {"scope": "part", "contract_version": 1, "status": "unverified", "issues": [],
              "verification_scope": "authoring_reproducibility", "integrity_checked": False,
              "excluded_roles": ["presentation", "physical", "document_identity", "repair_draft"],
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
        rebuilt = root_design(root, input_sources=design.input_sources)
    except (ValueError, TypeError) as exc:
        issues.append({"code": "invalid_recipe_root", "detail": str(exc)})
        return result
    for feature_id, kind, params, _ in rows:
        check()
        # The known v1 grouping defect is attributed at its actual replay
        # boundary. This explicit proof scan never runs in slider evaluation.
        before_structure = None
        if kind == "cluster_create" and params.get("_proof_version") == 1 and "structure_origin" not in result:
            from backend.core.part_structure import assess_structure
            before_structure = assess_structure(rebuilt, checkpoint=check)
        try:
            rebuilt = execute(kind, rebuilt, params)
        except ProofBudgetExceeded as exc:
            issues.append({"code": "command_limit", "feature_id": feature_id, "detail": str(exc)})
            return result
        except CommandContractError as exc:
            result["status"] = exc.status
            issues.append({**exc.as_issue(), "feature_id": feature_id, "kind": kind,
                           "possible_dependents": sorted(index.affected([feature_id]) - {feature_id})})
            return result
        except Exception as exc:
            result["status"] = "failed"
            # The graph is conservative. A later feature is not proven blocked
            # until its own required references have failed to resolve.
            issues.append({"code": "command_failed", "feature_id": feature_id, "kind": kind,
                           "detail": str(exc), "possible_dependents": sorted(index.affected([feature_id]) - {feature_id})})
            return result
        result["checked_commands"] += 1
        if before_structure is not None and before_structure["status"] == "valid":
            after_structure = assess_structure(rebuilt, checkpoint=check)
            if after_structure["status"] == "invalid":
                result["structure_origin"] = {"feature_id": feature_id, "kind": kind,
                    "structure": after_structure,
                    "possible_dependents": sorted(index.affected([feature_id]) - {feature_id})}
    check()
    mismatches = sorted(name for name in AUTHORING_FIELDS if getattr(design, name) != getattr(rebuilt, name))
    if mismatches:
        result["status"] = "mismatch"
        issues.append({"code": "authoring_state_mismatch", "fields": mismatches})
    else:
        imported = sorted({resource for _, _, _, contract in rows for resource in contract.imported_sources})
        result["imported_sources"] = [{"kind": resource.kind, "identity": resource.identity} for resource in imported]
        native = root.kind == "empty" and not imported
        result["status"] = "verified" if native else "reproduced_import"
        result["native_editable"] = native
    return result
