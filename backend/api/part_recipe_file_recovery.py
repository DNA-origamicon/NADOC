"""Private reconstruction of a saved recipe; no file or session publication.

The eventual HTTP host must run these bounded calls in its isolated process.
Neither function installs the definition carrier or grants a publishing permit.
Only explicit reviewed grouping upgrades are admitted in this first workflow.
"""

import hashlib
import json
from dataclasses import asdict
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from backend.core.part_command_errors import CommandContractError
from backend.core.part_input_sources import Digest
from backend.core.part_operation_input import validate_operation_input
from backend.core.part_repair_inputs import MAX_REPAIR_ACTIONS, UpgradeClusterCreation
from backend.core.part_verification_capture import CaptureLimit


class FileRecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: StrictInt = Field(ge=1, le=1)
    expected_source_sha256: Digest
    actions: list[UpgradeClusterCreation] = Field(min_length=1, max_length=MAX_REPAIR_ACTIONS)


class _Interrupted(BaseException):
    """Keep caller cancellation distinct from nested input-error normalization."""

    def __init__(self, error):
        self.error = error


def _cancellable(checkpoint):
    def check():
        try:
            checkpoint()
        except BaseException as error:
            raise _Interrupted(error) from error
    return check


def _receipt(admitted):
    return {
        "source_sha256": admitted.original_sha256,
        "source_size_bytes": len(admitted.original_bytes),
        "source_design_id": admitted.source.id,
        "excluded_fields": list(admitted.excluded_fields),
        "stripped_recovery_field_count": len(admitted.stripped_recovery_fields),
        "old_state_verified": False,
        "basis": "saved_recipe_inputs",
    }


def _failure(error, recovery=None):
    if isinstance(error, CommandContractError):
        status, issue = error.status, error.as_issue()
    elif isinstance(error, CaptureLimit):
        status, issue = "unverified", {"code": "recovery_input_limit", "detail": str(error)}
    elif isinstance(error, ValidationError):
        # Do not reflect an entire untrusted file/large input in an error string.
        status, issue = "failed", {"code": "invalid_recovery_inputs",
                                  "detail": "Recovery input does not match the supported schema"}
    else:
        status, issue = "failed", {"code": "invalid_recovery_inputs", "detail": str(error)[:2048]}
    result = {"status": status, "issues": [issue], "native_editable": False}
    if recovery is not None:
        result["recovery"] = recovery
    return result


def _admit(data, checkpoint):
    from backend.core.part_input_sources import portable_sources
    from backend.core.part_recipe_file import admit_recipe_file
    from backend.core.part_verification_capture import admit

    admitted = admit_recipe_file(data, checkpoint=checkpoint)
    # Wire size, decoded JSON shape and existing recipe admission are distinct
    # limits. A small compressed/source string must not bypass the latter.
    admit(admitted.source, preserve_entry_types=True)
    checkpoint()
    portable_sources(admitted.source)
    checkpoint()
    return admitted


def _upgrades(source):
    from backend.core.models import ClusterCreateLogEntry
    from backend.core.part_group_repair import upgrade_action

    upgrades = []
    for entry in source.feature_log:
        if type(entry) is ClusterCreateLogEntry and entry.proof_version == 1:
            upgrades.append({"label": "Preserve empty group owners (v2)",
                             "action": upgrade_action(entry)})
    if not upgrades:
        raise CommandContractError("This recipe has no supported grouping v1 recovery action",
                                   code="unsupported_file_recovery")
    return upgrades


def inspect_recipe_file(data, *, checkpoint=lambda: None):
    """Inspect definitions and offer explicit actions; never replay or load output."""
    recovery = None
    checkpoint = _cancellable(checkpoint)
    try:
        checkpoint()
        admitted = _admit(data, checkpoint)
        recovery = _receipt(admitted)
        upgrades = _upgrades(admitted.source)
        checkpoint()
        return {"status": "review", "issues": [], "recovery": recovery, "upgrades": upgrades}
    except _Interrupted as stopped:
        raise stopped.error
    except (CommandContractError, CaptureLimit, ValueError, TypeError) as error:
        return _failure(error, recovery)


def _roundtrip(candidate, checkpoint):
    from backend.api.part_evaluation_worker import MAX_CANDIDATE_BYTES
    from backend.api.part_verification_worker import _result_bytes
    from backend.core.models import Design
    from backend.core.part_history_proof import digest
    from backend.core.part_verification_capture import admit

    admit(candidate, preserve_entry_types=True)
    checkpoint()
    value = candidate.model_dump(mode="json")
    encoded = _result_bytes(value, limit=MAX_CANDIDATE_BYTES,
                            limit_result={"recovery_result_limit": True})
    # The shared bounded encoder emits a small refusal instead of excess output.
    if encoded == b'{"recovery_result_limit":true}':
        raise CommandContractError("Recovered copy exceeds its result byte limit", code="result_limit")
    # Normal typed loading is the acceptance gate, never a fallback for the
    # original invalid file. It must not silently normalize recovered authoring.
    restored = Design.from_json(encoded.decode("utf-8"))
    # Canonical JSON distinguishes bool/int/float where Python equality does
    # not. Dictionary order is not part of the definition contract.
    if digest(restored.model_dump(mode="json")) != digest(value):
        raise CommandContractError("Recovered copy changes during ordinary loading",
                                   code="recovery_roundtrip_mismatch")
    checkpoint()
    return restored, value


def recover_recipe_file(data, request, *, checkpoint=lambda: None):
    """Return a new validated copy from exact bytes and explicitly selected repairs.

    The private copy uses a local revision zero only to reuse the repair engine's
    expectation checks. It is never a document session or a publication receipt.
    The caller owns cancellation and discards results after a cancelled request.
    """
    from backend.api import part_proof_commands, part_recipe_repair
    from backend.core import part_history_contract
    from backend.core.models import Design
    from backend.core.part_recipe_file import MAX_FILE_BYTES

    recovery = None
    checkpoint = _cancellable(checkpoint)
    try:
        checkpoint()
        validate_operation_input(request)
        request = FileRecoveryRequest.model_validate(request)
        # Check exact bytes before parsing definitions or resolving any inputs.
        if type(data) is not bytes or len(data) > MAX_FILE_BYTES:
            raise CommandContractError("Saved recipe exceeds the recovery byte limit or is not bytes",
                                       code="recovery_input_limit")
        if hashlib.sha256(data).hexdigest() != request.expected_source_sha256:
            raise CommandContractError("The original file changed after inspection", code="repair_conflict")
        admitted = _admit(data, checkpoint)
        recovery = _receipt(admitted)
        _upgrades(admitted.source)  # Recognize scope; do not select/apply actions.
        copy_id = str(uuid4())
        source = admitted.source.copy_with(id=copy_id)
        body = {"repair_version": 1, "expected_design_id": copy_id, "expected_revision": 0,
                "actions": [action.model_dump(mode="json") for action in request.actions]}
        result = part_recipe_repair.prepare_repair(source, body, source_revision=0,
            executor=part_proof_commands.execute, dependency_resolver=part_proof_commands.dependencies,
            checkpoint=checkpoint)
        if result["status"] != "ready":
            return {**result, "recovery": recovery}
        candidate = result["candidate"]
        if not isinstance(candidate, Design) or candidate.id != copy_id:
            raise CommandContractError("Repair did not preserve the private copy identity",
                                       code="invalid_recovery_candidate")
        # Publication must not turn a merely evaluated but invalid model into a
        # downloadable success. Structural validity and validation are separate.
        if not result["validation"].passed:
            return {"status": "failed", "issues": [{"code": "recovery_validation_failed"}],
                    "validation": {"passed": False, **asdict(result["validation"])},
                    "repair": result["repair"], "recovery": recovery, "native_editable": False}
        restored, candidate_json = _roundtrip(candidate, checkpoint)
        # Exact typed roundtrip equality preserves the earlier validation
        # verdict. Independent proof below also checks structural closure; avoid
        # repeating the identical validator/structure walks a third time.
        validation = result["validation"]
        proof = part_history_contract.assess_part_history(restored,
            execute=part_proof_commands.execute, dependencies=part_proof_commands.dependencies,
            checkpoint=checkpoint)
        checkpoint()
        if proof["status"] not in {"verified", "reproduced_import"}:
            return {"status": "failed", "issues": [{"code": "recovered_recipe_not_reproducible"}],
                    "proof": proof, "repair": result["repair"], "recovery": recovery,
                    "native_editable": False}
        output = {"status": "ready", "issues": [], "candidate": candidate_json,
                  "validation": {"passed": True, **asdict(validation)}, "proof": proof,
                  "repair": result["repair"], "recovery": {**recovery,
                      "recovered_design_id": copy_id,
                      "definition_upgrades": result["repair"]["definition_upgrades"]}}
        # Bound the complete response including proof and provenance, not just
        # its candidate. The eventual process transport applies the same ceiling.
        from backend.api.part_evaluation_worker import MAX_CANDIDATE_BYTES
        from backend.api.part_verification_worker import _result_bytes
        encoded = _result_bytes(output, limit=MAX_CANDIDATE_BYTES, limit_result=_failure(
            CommandContractError("Recovered response exceeds its result byte limit", code="result_limit"),
            recovery))
        checkpoint()
        return json.loads(encoded)
    except _Interrupted as stopped:
        raise stopped.error
    except (CommandContractError, CaptureLimit, ValueError, TypeError) as error:
        return _failure(error, recovery)
