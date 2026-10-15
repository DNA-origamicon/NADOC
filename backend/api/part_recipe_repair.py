"""Explicit, bounded repair of native definitions from the declared part root.

Unlike ordinary edits, repair does not certify the old materialized model first.
Only a complete regenerated candidate is returned. Publication, cancellation and
the numerical process policy remain responsibilities of the existing job host.
"""

from copy import deepcopy
from typing import Annotated, Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.core.feature_identity import preserve_proof_identity
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import FIELD_ROLES
from backend.core.part_history_proof import ProofBudgetExceeded, command_rows, digest
from backend.core.part_operation_input import validate_operation_input
from backend.core.part_overlay_commands import command_input


MAX_REPAIR_ACTIONS = 64
_Id = Annotated[str, Field(strict=True, min_length=1, max_length=256)]
_Token = _Id | Annotated[StrictInt, Field(ge=0)]


class _Target(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    feature_id: _Id
    child_id: _Id | None = None


class SetInput(_Target):
    action: Literal["set_input"]
    parameter_path: list[_Token] = Field(min_length=1, max_length=16)
    expected_old: Any
    value: Any


class UpgradeNumericalContract(_Target):
    action: Literal["upgrade_numerical_contract"]
    expected_engine: dict[str, Any]
    expected_template: dict[str, Any] | None = None


class RepairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    repair_version: StrictInt = Field(ge=1, le=1)
    expected_design_id: _Id
    expected_revision: StrictInt = Field(ge=0)
    actions: list[Annotated[SetInput | UpgradeNumericalContract, Field(discriminator="action")]] = Field(
        min_length=1, max_length=MAX_REPAIR_ACTIONS)

    @model_validator(mode="before")
    @classmethod
    def bounded_json(cls, value):
        validate_operation_input(value)
        return value


class RepairInputError(CommandContractError):
    status = "failed"

    def __init__(self, detail, *, code, action=None):
        super().__init__(detail, code=code)
        self.action = action

    def as_issue(self):
        issue = super().as_issue()
        if self.action is not None:
            issue["feature_id"] = self.action.feature_id
            if self.action.child_id is not None:
                issue["child_id"] = self.action.child_id
            if isinstance(self.action, SetInput):
                issue["parameter_path"] = list(self.action.parameter_path)
        return issue


def _reject(code, detail, action=None):
    raise RepairInputError(detail, code=code, action=action)


def _same(left, right):
    # JSON comparison must distinguish bool/int and integer/float expectations.
    return digest(left) == digest(right)


def _at(params, path, action):
    value = params
    for token in path:
        if type(value) is dict and type(token) is str and token in value:
            value = value[token]
        elif type(value) is list and type(token) is int and 0 <= token < len(value):
            value = value[token]
        else:
            _reject("invalid_parameter_path", "Repair paths must identify an existing authored input", action)
    return value


def _current_numerical_pins(kind, _params):
    # Invoked only by an explicit upgrade, inside the job's numerical worker.
    if kind in {"photoproduct-create", "photoproduct-relax"}:
        from backend.core.part_cpd_contract import contract_defaults
    elif kind == "duplex-relax":
        from backend.core.part_duplex_relax_contract import contract_defaults
    elif kind == "nanoparticle-patch":
        from backend.core.part_streptavidin_contract import contract_defaults
    else:
        raise CommandContractError("This command has no supported numerical upgrade", code="unsupported_numerical_upgrade")
    return contract_defaults()


def _numerical_parser(kind):
    if kind in {"photoproduct-create", "photoproduct-relax"}:
        from backend.core.part_cpd_contract import parse_command
        return lambda params: parse_command(kind, params)
    if kind == "duplex-relax":
        from backend.core.part_duplex_relax_contract import parse_command
        return parse_command
    if kind == "nanoparticle-patch":
        from backend.api.part_streptavidin_commands import SetRequest, parse_command

        def parse_coating(params):
            command = parse_command(kind, params)
            if not isinstance(command, SetRequest):
                raise CommandContractError("Only coating set/repack has a numerical upgrade",
                                           code="unsupported_numerical_upgrade")
            return command

        return parse_coating
    raise CommandContractError("This command has no supported numerical upgrade", code="unsupported_numerical_upgrade")


def _upgrade(kind, previous, action, provider):
    parse = _numerical_parser(kind)
    parse(previous)  # Old recognized schema/family, without validating old pins.
    if not _same(previous["engine"], action.expected_engine) or not _same(
            previous.get("template"), action.expected_template):
        _reject("repair_conflict", "The numerical contract changed after this repair was prepared", action)
    defaults = provider(kind, deepcopy(previous))
    allowed = {"engine", "template", "_proof_version", "conversion_version", "relaxation_version",
               "coating_version", "importer_version"}
    if set(defaults) - allowed or "engine" not in defaults:
        raise ValueError("Numerical provider returned fields outside the pin contract")
    updated = {**previous, **deepcopy(defaults)}
    parse(updated)
    # This increment upgrades code/runtime pins within a recognized algorithm;
    # it does not migrate algorithms, command versions or template families.
    if previous["engine"]["id"] != updated["engine"]["id"]:
        raise ValueError("Numerical upgrade cannot change the engine family")
    for key in ("_proof_version", "conversion_version", "relaxation_version", "coating_version", "importer_version"):
        if previous.get(key) != updated.get(key):
            raise ValueError("Numerical upgrade cannot change command versions")
    if "template" in previous and any(previous["template"][key] != updated["template"][key]
                                       for key in ("product_id", "schema")):
        raise ValueError("Numerical upgrade cannot change the template family")
    fields = ("engine", "template") if "template" in previous else ("engine",)
    return updated, {"feature_id": action.feature_id, "child_id": action.child_id,
        "kind": kind, "before": {key: deepcopy(previous[key]) for key in fields},
        "after": {key: deepcopy(updated[key]) for key in fields},
        "changed": any(not _same(previous[key], updated[key]) for key in fields)}


def _definitions(source, request, dependency_resolver, numerical_provider):
    rows = list(command_rows(source, 2000))
    identities = [entry.id for entry in source.feature_log]
    identities.extend(child.id for entry in source.feature_log if entry.feature_type == "routing-cluster"
                      for child in entry.children)
    if len(identities) != len(set(identities)):
        _reject("ambiguous_feature_identity", "Feature and routing-child identities must be unique")
    if any(kind == "empty-routing-cluster" for _, kind, _ in rows):
        raise CommandContractError("Empty routing groups have no replay contract", code="empty_routing_cluster")
    entries = {entry.id: entry for entry in source.feature_log}
    targets, paths, upgrades = {}, {}, []
    # Resolve every expectation against the original definitions, so action
    # ordering cannot turn stale or overlapping edits into a different repair.
    for action in request.actions:
        entry = entries.get(action.feature_id)
        if entry is None:
            _reject("missing_feature", "The selected repair feature no longer exists", action)
        if action.child_id is not None:
            if entry.feature_type != "routing-cluster":
                _reject("invalid_repair_target", "A routing-child target needs its containing group", action)
            child = next((item for item in entry.children if item.id == action.child_id), None)
            if child is None:
                _reject("missing_feature", "The selected routing child no longer exists in this group", action)
            entry = child
        elif entry.feature_type != "snapshot":
            _reject("unsupported_repair_target", "This repair version edits snapshot or explicit routing-child definitions", action)
        kind, previous = command_input(entry)
        if not dependency_resolver(kind, previous).known:
            raise CommandContractError("Repair cannot promote a legacy or unknown command contract",
                                       code="missing_proof_contract")
        target = targets.setdefault(entry.id, {"entry": entry, "kind": kind, "params": deepcopy(previous), "upgrade": None})
        if isinstance(action, SetInput):
            path = tuple(action.parameter_path)
            old_paths = paths.setdefault(entry.id, [])
            if any(path[:len(other)] == other or other[:len(path)] == path for other in old_paths):
                _reject("overlapping_repair_paths", "Repair actions cannot overlap within a definition", action)
            old_paths.append(path)
            if not _same(_at(previous, path, action), action.expected_old):
                _reject("repair_conflict", "The selected input changed after this repair was prepared", action)
            container = _at(target["params"], path[:-1], action)
            container[path[-1]] = deepcopy(action.value)
            if not _same(preserve_proof_identity(previous, target["params"], kind=kind), target["params"]):
                _reject("protected_recipe_identity", "Repair cannot replace output identities, versions, namespaces or closed scopes", action)
        else:
            if target["upgrade"] is not None:
                _reject("duplicate_numerical_upgrade", "A definition can be upgraded only once per repair", action)
            target["upgrade"] = action
    for target in targets.values():
        if target["upgrade"] is not None:
            try:
                target["params"], provenance = _upgrade(target["kind"], target["params"], target["upgrade"], numerical_provider)
            except CommandContractError as error:
                raise _ReplayStopped(error.status, {**error.as_issue(), "feature_id": target["entry"].id,
                                                    "kind": target["kind"]}) from error
            upgrades.append(provenance)
        if not dependency_resolver(target["kind"], target["params"]).known:
            _reject("invalid_repaired_contract", "Patched inputs do not satisfy the registered native command schema")
    log = []
    for entry in source.feature_log:
        if entry.feature_type == "routing-cluster":
            children = [child.model_copy(update={"params": targets[child.id]["params"]})
                        if child.id in targets else child for child in entry.children]
            entry = entry.model_copy(update={"children": children})
        elif entry.id in targets:
            entry = entry.model_copy(update={"params": targets[entry.id]["params"]})
        log.append(entry)
    return log, upgrades


class _ReplayStopped(Exception):
    def __init__(self, status, issue):
        self.status, self.issue = status, issue


def prepare_repair(source, request, *, source_revision, executor, dependency_resolver,
                   checkpoint=lambda: None, numerical_provider=None):
    """Build an isolated candidate or diagnostics; never mutate/publish source.

    ``source_revision`` must come from the trusted host's captured revision.
    Numerical upgrades must run in the existing worker's fixed thread/runtime
    policy. Test injection replaces pin capture, never the production allowlist.
    A ready Design and ValidationReport use the existing evaluation serializer.
    """
    from backend.api.part_recipe_edit import regenerate
    from backend.core.validator import validate_design

    request = RepairRequest.model_validate(request)
    rows, completed, upgrades = [], [], []
    phase = "admission"

    def result(status, issue):
        pending = [identity for identity, _, _ in rows[len(completed):]]
        failed = issue.get("feature_id")
        return {"status": status, "issues": [issue], "native_editable": False,
            "repair": {"phase": phase, "source_revision": source_revision,
                "source_design_id": source.id, "old_state_verified": False,
                "completed_prefix": list(completed),
                "not_evaluated": [identity for identity in pending if identity != failed],
                "numerical_upgrades": upgrades}}

    try:
        checkpoint()
        if request.expected_design_id != source.id or type(source_revision) is not int or request.expected_revision != source_revision:
            _reject("repair_conflict", "The repair belongs to a different part or captured revision")
        if source.recipe_root is None:
            raise CommandContractError("Repair requires an explicit part root", code="missing_recipe_root")
        if source.recipe_root.version != 1:
            raise CommandContractError("Unsupported part root version", code="unsupported_root_version")
        if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
            raise CommandContractError("Repair requires the complete recipe", code="historical_cursor")
        if set(type(source).model_fields) - FIELD_ROLES.keys():
            raise CommandContractError("Design fields lack proof ownership", code="unclassified_fields")
        rows = list(command_rows(source, 2000))
        log, upgrades = _definitions(source, request, dependency_resolver, numerical_provider or _current_numerical_pins)
        rows = list(command_rows(source.copy_with(feature_log=log), 2000))

        def run(kind, current, params):
            nonlocal phase
            phase = "replay"
            identity, expected_kind, _ = rows[len(completed)]
            if kind != expected_kind:
                raise RuntimeError("Repair replay diverged from the planned command order")
            try:
                if not dependency_resolver(kind, params).known:
                    raise CommandContractError("Recipe row has no supported native contract", code="missing_proof_contract")
                updated = executor(kind, current, deepcopy(params))
            except CommandContractError as error:
                raise _ReplayStopped(error.status, {**error.as_issue(), "feature_id": identity, "kind": kind}) from error
            except ValueError as error:
                raise _ReplayStopped("failed", {"code": "invalid_command_inputs", "detail": str(error)[:2048],
                                              "feature_id": identity, "kind": kind}) from error
            except HTTPException as error:
                status = "unverified" if error.status_code in {408, 413, 429} else "failed"
                raise _ReplayStopped(status, {"code": "evaluation_rejected", "detail": error.detail,
                    "http_status": error.status_code, "feature_id": identity, "kind": kind}) from error
            completed.append(identity)
            phase = "recovery"
            return updated

        phase = "root"
        candidate = regenerate(source, log, checkpoint, executor=run)
        if len(completed) != len(rows):
            raise RuntimeError("Repair did not execute every planned command")
        phase = "validation"
        validation = validate_design(candidate)
        checkpoint()
        return {"status": "ready", "issues": [], "candidate": candidate, "validation": validation,
            "repair": {"source_revision": source_revision, "source_design_id": source.id,
                "old_state_verified": False, "completed_prefix": completed, "not_evaluated": [],
                "numerical_upgrades": upgrades, "integrity_checked": True}}
    except _ReplayStopped as error:
        return result(error.status, error.issue)
    except CommandContractError as error:
        return result(error.status, error.as_issue())
    except ProofBudgetExceeded as error:
        return result("unverified", {"code": "command_limit", "detail": str(error)[:2048]})
    except ValueError as error:
        return result("unverified" if str(error) == "entry_limit" else "failed", {
            "code": "entry_limit" if str(error) == "entry_limit" else "invalid_repair_inputs", "detail": str(error)[:2048]})
