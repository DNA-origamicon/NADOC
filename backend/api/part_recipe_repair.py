"""Explicit, bounded repair of native definitions from the declared part root.

Unlike ordinary edits, repair does not certify the old materialized model first.
Only a complete regenerated candidate is returned. Publication, cancellation and
the numerical process policy remain responsibilities of the existing job host.
"""

from copy import deepcopy

from fastapi import HTTPException

from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import FIELD_ROLES
from backend.core.part_history_proof import ProofBudgetExceeded, command_rows
from backend.core.part_repair_inputs import (
    MAX_REPAIR_ACTIONS as MAX_REPAIR_ACTIONS,
    RepairRequest as RepairRequest,
    SetInput as SetInput,
    UpgradeNumericalContract as UpgradeNumericalContract,
)

from backend.core.part_repair_planning import (
    RepairInputError as RepairInputError,
    check_numerical_expectations,
    plan_actions,
    same_input as _same,
    validate_target,
)


def _reject(code, detail, action=None):
    raise RepairInputError(detail, code=code, action=action)


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
    check_numerical_expectations(previous, action)
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
    from backend.api.part_repair_contracts import recognizes_invalid_inputs

    list(command_rows(source, 2000))  # retain the existing entry-limit admission
    targets = plan_actions(source, request.actions, dependencies=dependency_resolver,
                           recognize_invalid=recognizes_invalid_inputs)
    upgrades = []
    for target in targets.values():
        if target.upgrade is not None:
            try:
                target.params, provenance = _upgrade(target.kind, target.params, target.upgrade, numerical_provider)
            except CommandContractError as error:
                raise _ReplayStopped(error.status, {**error.as_issue(), "feature_id": target.entry.id,
                                                    "kind": target.kind}) from error
            upgrades.append(provenance)
        validate_target(target, dependency_resolver)
    log = []
    for entry in source.feature_log:
        if entry.feature_type == "routing-cluster":
            children = [child.model_copy(update={"params": targets[child.id].params})
                        if child.id in targets else child for child in entry.children]
            entry = entry.model_copy(update={"children": children})
        elif entry.id in targets:
            entry = entry.model_copy(update={"params": targets[entry.id].params})
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
