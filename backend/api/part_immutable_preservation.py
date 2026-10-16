"""Closed, constant-size document state retained by strict batch publication.

The full sealed bytes remain authoritative. This projection permits avoiding a
source decode only while every non-scalar preserved field has its reviewed
empty shape. Expanding batch admission cannot silently expand this contract.
"""

from backend.core.models import Design, VisibilityState
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import FIELD_ROLES
from backend.core.part_history_proof import digest


PRESERVATION_VERSION = 1
_ROLES = {
    "id": "document_identity",
    "plate_layout": "presentation", "representation_overrides": "presentation",
    "view_volumes": "presentation", "annotations": "presentation",
    "annotations_enabled": "presentation", "visibility_state": "presentation",
    "camera_poses": "presentation", "animations": "presentation",
    "chain_sim_projects": "physical", "loadouts": "physical", "atomistic_reference": "physical",
    "active_loadout_id": "physical", "last_editable_loadout_id": "physical",
    "repair_draft": "repair_draft",
}
_EMPTY_LISTS = ("representation_overrides", "view_volumes", "annotations", "camera_poses",
                "animations", "chain_sim_projects", "loadouts")
_ABSENT = ("plate_layout", "atomistic_reference", "active_loadout_id", "last_editable_loadout_id", "repair_draft")
_VISIBILITY = frozenset({"hidden_base_keys", "shown_base_keys", "hidden_cluster_ids"})


def _reject(detail):
    raise CommandContractError(detail, code="unsupported_revision_preservation")


def preservation_digest(design):
    """Check fixed shapes before hashing a tiny positive JSON projection.

    No serializer, recursive equality, list subclass method or nested authoring
    traversal runs here. Values outside the closed envelope are refused rather
    than discarded, including values introduced by a worker candidate.
    """
    if type(design) is not Design:
        _reject("Strict preservation requires an exact Design model")
    roles = {name: role for name, role in FIELD_ROLES.items()
             if role in {"presentation", "physical", "document_identity", "repair_draft"}}
    if roles != _ROLES:
        _reject("Strict preservation requires a reviewed document field schema")
    if type(design.id) is not str or not 1 <= len(design.id) <= 1024:
        _reject("Strict preservation requires a bounded nonempty document identity")
    if type(design.annotations_enabled) is not bool:
        _reject("Strict preservation requires an exact boolean annotation flag")
    for name in _EMPTY_LISTS:
        value = getattr(design, name)
        if type(value) is not list or len(value) != 0:
            _reject(f"Strict preservation initially requires empty {name}")
    for name in _ABSENT:
        if getattr(design, name) is not None:
            _reject(f"Strict preservation initially requires absent {name}")
    visibility = design.visibility_state
    if (type(visibility) is not VisibilityState
            or set(VisibilityState.model_fields) != _VISIBILITY
            or set(visibility.__dict__) != _VISIBILITY
            or getattr(visibility, "__pydantic_extra__", None)):
        _reject("Strict preservation requires the reviewed visibility schema")
    for name in _VISIBILITY:
        value = getattr(visibility, name)
        if type(value) is not list or len(value) != 0:
            _reject("Strict preservation initially requires empty visibility lists")
    return digest({
        "id": design.id, "annotations_enabled": design.annotations_enabled,
        **dict.fromkeys(_ABSENT), **{name: [] for name in _EMPTY_LISTS},
        "visibility_state": {name: [] for name in _VISIBILITY},
    })
