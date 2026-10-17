"""Closed native editor work; shared leases and publication stay in the host.

These three families share ownership/lifecycle, not command schemas or display
contracts. Imports are lazy so a disabled route does not load native projection.
There is no caller-provided handler, registry or publication authority here.
"""

from copy import deepcopy

from backend.core.part_command_errors import CommandContractError


FAMILIES = frozenset({"deformation", "sweep", "transform"})


def _native(family):
    if family == "deformation":
        from backend.api import part_deformation_preview as native
    elif family == "sweep":
        from backend.api import part_sweep_preview as native
    elif family == "transform":
        from backend.api import part_transform_preview as native
    else:
        raise CommandContractError("Unknown preview family", code="invalid_preview_family")
    return native


def _display(family):
    if family == "deformation":
        from backend.api import part_deformation_preview_dto as display
    elif family == "sweep":
        from backend.api import part_sweep_preview_dto as display
    elif family == "transform":
        from backend.api import part_transform_preview_dto as display
    else:
        raise CommandContractError("Unknown preview family", code="invalid_preview_family")
    return display


def prepare(family, captured, feature_id, *, creation=None):
    native = _native(family)
    if creation is not None:
        if family != "deformation":
            raise CommandContractError("This editor does not create new features", code="invalid_preview_family")
        return native.prepare_creation_from_capture(captured, feature_id=feature_id, **creation)
    return native.prepare_from_capture(captured, feature_id)


def identity_fields(family, prepared=None):
    """Only scalar identity survives after publication releases the prefix."""
    if family == "transform":
        return {"family": "transform", "command_kind": None if prepared is None else prepared.kind}
    if family in {"deformation", "sweep"}:
        return {"deformation_id": None if prepared is None else prepared.deformation_id}
    raise CommandContractError("Unknown preview family", code="invalid_preview_family")


def _creation(family, prepared):
    if family != "deformation":
        return False
    from backend.api.part_deformation_preview import PreparedCreation

    return type(prepared) is PreparedCreation


def evaluate_original(family, prepared):
    return None if _creation(family, prepared) else evaluate(family, prepared, {})


def evaluate(family, prepared, patch):
    return _native(family).evaluate(prepared, patch)


def prepare_display(family, prepared, evaluated, *, envelope):
    display = _display(family)
    if _creation(family, prepared):
        return display.prepare_creation_display(prepared.copy_prefix(), prepared, envelope=envelope)
    return display.prepare_display(prepared.copy_prefix(), evaluated, envelope=envelope)


def evaluate_display(family, prepared, evaluated, *, include_geometry, envelope):
    display = _display(family)
    options = {"creation": _creation(family, prepared)} if family == "deformation" else {}
    return display.evaluate_display(prepared.copy_prefix(), evaluated,
        include_geometry=include_geometry, envelope=envelope, **options)


def apply_params(family, prepared, patch):
    """Validate the local draft without replacing fresh full-recipe Apply proof.

    Sweep edits consume complete normalized inputs. Transform and deformation
    edits must retain the explicit patch: binding a reset target or editing an
    overlay uses the selected entry and the freshly proved prefix at Apply.
    """
    evaluated = evaluate(family, prepared, patch)
    return evaluated.params if family == "sweep" else deepcopy(patch)
