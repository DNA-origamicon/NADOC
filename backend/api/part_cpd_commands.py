"""Expensive native CPD commands, called only by the bounded long-job worker.

This adapter neither selects a live document nor changes global atomistic
defaults. Legacy conversion/relaxation routes retain their existing behavior.
"""

from backend.core.part_cpd_contract import (
    CPDContractError, KINDS, native_source, prepare_command, validate_environment, validate_inputs,
)
from backend.core.part_history_contract import FIELD_ROLES


__all__ = ["KINDS", "prepare_command", "build"]
_OUTPUTS = frozenset({"photoproduct_junctions", "nucleotide_transforms"})


def build(kind, design, params):
    command = validate_inputs(kind, design, params)
    validate_environment(command)
    source = native_source(design)
    # Installed sources/templates are immutable for the duration of a worker.
    # Checking again prevents publication if that deployment premise was broken.
    if kind == "photoproduct-create":
        from backend.core.cpd_design import convert_extra_pair
        updated, _ = convert_extra_pair(source, command.base_keys, command.stereochemistry,
                                        identity_seed=command.history_seed)
    elif kind == "photoproduct-relax":
        from backend.core.cpd_design import relax_existing_cpd
        updated, _ = relax_existing_cpd(source, command.photoproduct_id)
    else:
        raise ValueError("Unsupported native CPD command")
    validate_environment(command)
    if any(getattr(updated, name) != getattr(design, name) for name, role in FIELD_ROLES.items()
           if role == "authoring" and name not in _OUTPUTS):
        raise CPDContractError("Native CPD builder changed unrelated authoring fields", code="builder_output_mismatch")
    return design.copy_with(**{name: getattr(updated, name) for name in _OUTPUTS})
