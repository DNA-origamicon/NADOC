"""Explicit, exact-definition migration of recognized grouping v1 to v2.

Callers own source capture. Recognition and discovery inspect bounded typed
inputs only; complete-row hashing occurs outside the source lock. Neither path
executes grouping, reads recovery geometry, or selects numerical contracts.
"""

from copy import deepcopy
from math import isfinite

from pydantic import BaseModel

from backend.core.models import ClusterCreateLogEntry, ClusterRigidTransform, DomainRef
from backend.core.part_capture_graph import CaptureLimit, CaptureShapeError, GraphBudget
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_proof import digest
from backend.core.part_operation_input import MAX_OPERATION_BYTES, MAX_OPERATION_NODES, validate_operation_input
from backend.core.part_repair_inputs import UpgradeClusterCreation


class GroupUpgradeError(CommandContractError):
    status = "failed"


def _unsupported():
    raise GroupUpgradeError("Only a coherent typed grouping v1 definition can adopt grouping v2",
                            code="unsupported_cluster_upgrade")


def _shape(value):
    if isinstance(value, BaseModel):
        if type(value) not in {ClusterCreateLogEntry, ClusterRigidTransform, DomainRef}:
            _unsupported()
        fields = type(value).model_fields
        if (len(value.__dict__) != len(fields) or any(name not in fields for name in value.__dict__)
                or value.__pydantic_extra__ or value.__pydantic_private__):
            _unsupported()
    elif type(value) in {str, bool, list, dict} or value is None:
        return
    elif type(value) is int and value.bit_length() <= 64:
        return
    elif type(value) is float and isfinite(value):
        return
    else:
        _unsupported()


def _recognize(entry, *, versions=(1,)):
    if type(entry) is not ClusterCreateLogEntry:
        _unsupported()
    try:
        GraphBudget(max_nodes=MAX_OPERATION_NODES, max_bytes=MAX_OPERATION_BYTES,
                    seconds=None, clock=lambda: 0).charge(entry, validate=_shape, reject_cycles=True)
    except CaptureLimit as exc:
        raise GroupUpgradeError("Grouping definition exceeds the repair input budget",
                                code="group_definition_limit") from exc
    except CaptureShapeError as exc:
        raise GroupUpgradeError("Grouping definition contains an unsupported recursive shape",
                                code="unsupported_cluster_upgrade") from exc
    group = entry.cluster_snapshot
    if (entry.feature_type != "cluster_create" or type(entry.proof_version) is not int
            or entry.proof_version not in versions or type(group) is not ClusterRigidTransform
            or any(type(value) is not str or not 1 <= len(value) <= 256
                   for value in (entry.id, entry.cluster_id, group.id))
            or entry.cluster_id != group.id or entry.name != group.name
            or entry.helix_ids != group.helix_ids or entry.domain_ids != group.domain_ids):
        _unsupported()


def _recognized_sha256(entry):
    value = entry.model_dump(mode="json")
    try:
        validate_operation_input(value)
    except ValueError as exc:
        raise GroupUpgradeError("Grouping definition exceeds the repair input budget",
                                code="group_definition_limit") from exc
    return digest(value)


def definition_sha256(entry):
    """Hash a coherent supported row, including v2 for upgrade provenance."""
    _recognize(entry, versions=(1, 2))
    return _recognized_sha256(entry)


def upgrade_action(entry):
    """Return only the closed action; display labels belong to the caller."""
    _recognize(entry)
    fingerprint = _recognized_sha256(entry)
    return {"action": "upgrade_cluster_creation", "feature_id": entry.id, "child_id": None,
            "expected_version": 1, "expected_cluster_id": entry.cluster_id,
            "expected_definition_sha256": fingerprint}


def upgrade_entry(entry, action, *, check_expectations=True, copy_value=deepcopy):
    """Make a private typed replacement; discovery never hashes the definition.

    The capture host supplies its charged copier for discovery. Final planning
    uses an independently captured row and the ordinary private deep copier.
    """
    if not isinstance(action, UpgradeClusterCreation):
        raise TypeError("Grouping upgrade requires a parsed repair action")
    _recognize(entry)
    if check_expectations and (
        action.feature_id != entry.id or action.child_id is not None
        or action.expected_version != entry.proof_version or action.expected_cluster_id != entry.cluster_id
        or action.expected_definition_sha256 != _recognized_sha256(entry)
    ):
        raise GroupUpgradeError("The grouping definition changed after this repair was prepared",
                                code="repair_conflict")
    return copy_value(entry).model_copy(update={"proof_version": 2})
