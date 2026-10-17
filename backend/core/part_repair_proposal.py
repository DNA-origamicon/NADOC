"""Draft/source-discovery adapters over the shared pure repair action planner."""

from copy import deepcopy

from backend.core.part_repair_planning import (
    RepairInputError, check_numerical_expectations, plan_actions, validate_target,
)


class DraftInputError(RepairInputError):
    """Draft metadata errors retain the same structured action diagnostics."""


def proposed_inputs(source, actions, *, copy_value=deepcopy, check_expectations=True, dependencies=None,
                    recognize_invalid=None):
    """Return private proposed inputs, never current pins or a publishable model.

    Source capture uses the planner's nonhashing discovery mode. Draft admission
    adds numerical-family/old-pin checks without importing a numerical builder.
    Only the existing isolated job may select upgraded implementation pins.
    """
    targets = plan_actions(source, actions, dependencies=dependencies, recognize_invalid=recognize_invalid,
        copy_value=copy_value,
        check_expectations=check_expectations, error_type=DraftInputError, annotate_contract_errors=True)
    result = []
    for target in targets.values():
        if check_expectations:
            if target.upgrade is not None:
                kind, params = target.kind, target.params
                if kind not in {"photoproduct-create", "photoproduct-relax", "duplex-relax", "nanoparticle-patch"} or (
                    kind == "nanoparticle-patch" and ("coating_version" not in params or params.get("action") != "set")
                ):
                    raise DraftInputError("This definition has no supported numerical upgrade",
                                          code="unsupported_numerical_upgrade", action=target.upgrade)
                check_numerical_expectations(params, target.upgrade, error_type=DraftInputError)
            if dependencies is not None:
                validate_target(target, dependencies, error_type=DraftInputError, annotate_contract_errors=True)
        result.append((target.kind, target.params))
    return result
