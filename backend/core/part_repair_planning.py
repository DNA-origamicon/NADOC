"""Shared pure action planning for draft preparation and isolated repair jobs.

This module resolves authored input paths and expectations. It never executes a
command, selects numerical pins, reads saved geometry, or publishes a model.
Callers supply bounded, stable definitions and a cheap command schema resolver.
"""

from copy import deepcopy
from dataclasses import dataclass

from backend.core.part_edit_identity import preserve_proof_identity
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_proof import digest
from backend.core.part_overlay_commands import command_input
from backend.core.models import ClusterCreateLogEntry
from backend.core.part_repair_inputs import SetInput, UpgradeClusterCreation, UpgradeNumericalContract


class RepairInputError(CommandContractError):
    status = "failed"

    def __init__(self, detail, *, code, action=None, include_parameter_path=True):
        super().__init__(detail, code=code)
        self.action = action
        self.include_parameter_path = include_parameter_path

    def as_issue(self):
        issue = super().as_issue()
        if self.action is not None:
            issue["feature_id"] = self.action.feature_id
            if self.action.child_id is not None:
                issue["child_id"] = self.action.child_id
            if self.include_parameter_path and isinstance(self.action, SetInput):
                issue["parameter_path"] = list(self.action.parameter_path)
        return issue


@dataclass
class RepairTarget:
    entry: object
    kind: str
    # Structural source discovery retains only its typed replacement. None is
    # deliberately not executable input; final planning always fills params.
    params: dict | None
    action: SetInput | UpgradeNumericalContract | UpgradeClusterCreation
    upgrade: UpgradeNumericalContract | None = None
    structural_replacement: ClusterCreateLogEntry | None = None


def same_input(left, right):
    # Preserve the existing JSON distinction between bool/int and int/float.
    return digest(left) == digest(right)


def _at(params, path, action, error_type):
    value = params
    for token in path:
        if type(value) is dict and type(token) is str and token in value:
            value = value[token]
        elif type(value) is list and type(token) is int and 0 <= token < len(value):
            value = value[token]
        else:
            raise error_type("Repair paths must identify an existing authored input",
                             code="invalid_parameter_path", action=action)
    return value


def plan_actions(source, actions, *, dependencies=None, recognize_invalid=None, copy_value=deepcopy,
                 check_expectations=True, error_type=RepairInputError,
                 annotate_contract_errors=False):
    """Return private target inputs in first-action order.

    Every expectation addresses the original definition. The capture-only mode
    skips hashing, protected-input/contract checks and empty-group admission;
    it exists solely to discover named proposed sources before leaving the lock.
    Numerical upgrades are recorded for a later caller-owned numerical phase.
    An optional reviewed recognition callback can admit an invalid old editable
    value; it never replaces final dependency/schema checks or native replay.
    """
    entries, identities, empty_groups = {}, set(), False
    for entry in source.feature_log:
        children = entry.children if entry.feature_type == "routing-cluster" else []
        empty_groups |= entry.feature_type == "routing-cluster" and not children
        for item in [entry, *children]:
            if item.id in identities:
                raise error_type("Feature and routing-child identities must be unique", code="ambiguous_feature_identity")
            identities.add(item.id)
        entries[entry.id] = entry
    if check_expectations and empty_groups:
        raise CommandContractError("Empty routing groups have no replay contract", code="empty_routing_cluster")
    targets, paths = {}, {}
    for action in actions:
        if not isinstance(action, (SetInput, UpgradeNumericalContract, UpgradeClusterCreation)):
            raise TypeError("Repair planning requires parsed repair actions")
        entry = entries.get(action.feature_id)
        if entry is None:
            raise error_type("The selected repair feature no longer exists", code="missing_feature", action=action)
        if action.child_id is not None:
            if entry.feature_type != "routing-cluster":
                raise error_type("A routing-child target needs its containing group", code="invalid_repair_target", action=action)
            entry = next((child for child in entry.children if child.id == action.child_id), None)
            if entry is None:
                raise error_type("The selected routing child no longer exists in this group", code="missing_feature", action=action)
        elif entry.feature_type != "snapshot" and not isinstance(action, UpgradeClusterCreation):
            raise error_type("This repair version edits snapshot or explicit routing-child definitions",
                             code="unsupported_repair_target", action=action)
        replacement = None
        if isinstance(action, UpgradeClusterCreation):
            from backend.core.part_group_repair import upgrade_entry

            if entry.id in targets:
                raise error_type("A grouping definition can be upgraded only once per repair",
                                 code="duplicate_cluster_upgrade", action=action)
            try:
                replacement = upgrade_entry(entry, action, check_expectations=check_expectations,
                                            copy_value=copy_value)
            except CommandContractError as exc:
                raise error_type(str(exc), code=exc.code, action=action) from exc
            if not check_expectations:
                targets[entry.id] = RepairTarget(entry, "cluster_create", None, action,
                                                structural_replacement=replacement)
                continue
        kind, previous = command_input(entry)
        if (check_expectations and dependencies is not None and not dependencies(kind, previous).known
                and not (recognize_invalid is not None and recognize_invalid(kind, previous))):
            detail = "Repair cannot promote a legacy or unknown command contract"
            if annotate_contract_errors:
                raise error_type(detail, code="missing_proof_contract", action=action)
            raise CommandContractError(detail, code="missing_proof_contract")
        if replacement is not None:
            _, params = command_input(replacement)
            targets[entry.id] = RepairTarget(entry, kind, params, action, structural_replacement=replacement)
            continue
        if entry.id not in targets:
            targets[entry.id] = RepairTarget(entry, kind, copy_value(previous), action)
        target = targets[entry.id]
        if isinstance(action, SetInput):
            path = tuple(action.parameter_path)
            old_paths = paths.setdefault(entry.id, [])
            if any(path[:len(other)] == other or other[:len(path)] == path for other in old_paths):
                raise error_type("Repair actions cannot overlap within a definition", code="overlapping_repair_paths", action=action)
            old_paths.append(path)
            old = _at(previous, path, action, error_type)
            if check_expectations and not same_input(old, action.expected_old):
                raise error_type("The selected input changed after this repair was prepared", code="repair_conflict", action=action)
            container = _at(target.params, path[:-1], action, error_type)
            container[path[-1]] = copy_value(action.value)
            if check_expectations and not same_input(preserve_proof_identity(previous, target.params, kind=kind), target.params):
                raise error_type("Repair cannot replace output identities, versions, namespaces or closed scopes",
                                 code="protected_recipe_identity", action=action)
        elif isinstance(action, UpgradeNumericalContract):
            if target.upgrade is not None:
                raise error_type("A definition can be upgraded only once per repair", code="duplicate_numerical_upgrade", action=action)
            target.upgrade = action
    return targets


def check_numerical_expectations(params, action, *, error_type=RepairInputError):
    """Check authored old pins only; this never identifies the current runtime."""
    if not same_input(params.get("engine"), action.expected_engine) or not same_input(
        params.get("template"), action.expected_template
    ):
        raise error_type("The numerical contract changed after this repair was prepared", code="repair_conflict", action=action)


def validate_target(target, dependencies, *, error_type=RepairInputError, annotate_contract_errors=False):
    """Validate final input shape, after any caller-owned numerical pin update."""
    if target.params is None:
        raise TypeError("Source discovery targets do not contain executable command inputs")
    if not dependencies(target.kind, target.params).known:
        options = {"action": target.action, "include_parameter_path": False} if annotate_contract_errors else {}
        raise error_type("Patched inputs do not satisfy the registered native command schema",
                         code="invalid_repaired_contract", **options)
