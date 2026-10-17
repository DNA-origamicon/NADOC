"""Private target binding and original-source proof for owned routing editors."""

from fastapi import HTTPException

from backend.core.part_command_errors import CommandContractError


def selected_child(source, index, sub_index, *, expected_feature_id, expected_child_id):
    from backend.api.part_routing_edit_inputs import KINDS
    if (type(index) is not int or not 0 <= index < len(source.feature_log)
            or type(sub_index) is not int or sub_index < 0
            or type(expected_feature_id) is not str or not 1 <= len(expected_feature_id) <= 512
            or type(expected_child_id) is not str or not 1 <= len(expected_child_id) <= 512):
        raise CommandContractError("Select the original routing parent and child", code="source_changed")
    parent = source.feature_log[index]
    if (parent.id != expected_feature_id or parent.feature_type != "routing-cluster"
            or sub_index >= len(parent.children)):
        raise CommandContractError("The selected routing parent changed", code="source_changed")
    child = parent.children[sub_index]
    if (child.id != expected_child_id or child.op_subtype not in KINDS
            or type(child.params.get("_proof_version")) is not int or child.params["_proof_version"] != 1
            or "_generated_scope" in child.params or "_generator" in child.params):
        raise CommandContractError("The selected native routing child changed", code="source_changed")
    return child


def evaluate(source, operation, *, executor=None, dependency_resolver=None):
    from backend.api.part_evaluation import EvaluationRequest, _evaluate
    from backend.api.part_routing_edit_inputs import normalize, bind_prefix

    try:
        header = operation["header"]
        request = EvaluationRequest.model_validate(operation["request"])
        if (type(header.get("routing_recording_version")) is not int or header["routing_recording_version"] != 1
                or "extrusion_recording_version" in header or "pattern_recording_version" in header
                or type(header.get("routing_inputs_only")) is not bool
                or type(header.get("source_revision")) is not int
                or header["source_revision"] != request.expected_revision
                or header.get("source_design_id") != source.id):
            raise CommandContractError("Routing editor lacks its exact captured context", code="invalid_capture_context")
        if request.operation != "edit" or request.sub_index is None:
            raise CommandContractError("Unknown owned routing operation", code="invalid_operation_admission")
        child = selected_child(source, request.index, request.sub_index,
            expected_feature_id=header.get("expected_feature_id"), expected_child_id=header.get("expected_child_id"))
        if header.get("expected_kind") != child.op_subtype:
            raise CommandContractError("The selected routing subtype changed", code="source_changed")
        added_ids = header.get("added_output_ids")
        if type(added_ids) is not list or (header["routing_inputs_only"] and added_ids):
            raise CommandContractError("Routing output allocations lack an exact receipt", code="invalid_capture_context")
        normalized = normalize(child.op_subtype, child.params, request.params, added_output_ids=added_ids)
        if normalized != request.params:
            raise CommandContractError("Routing inputs changed after normalization", code="invalid_capture_context")
        if header["routing_inputs_only"]:
            if normalized != normalize(child.op_subtype, child.params, {}):
                raise CommandContractError("Input preview cannot change a routing child", code="invalid_operation_admission")
            return _inputs(source, request, header, executor, dependency_resolver)

        def bind(kind, params, prefix):
            if kind != child.op_subtype or params != normalized:
                raise CommandContractError("Routing input binding differs from the owned edit", code="invalid_capture_context")
            return bind_prefix(kind, params, prefix)

        return _evaluate(source, operation, executor=executor,
                         dependency_resolver=dependency_resolver, input_binder=bind)
    except CommandContractError as error:
        return {"status": error.status, "issues": [error.as_issue()], "native_editable": False}
    except HTTPException as error:
        if isinstance(error.detail, dict) and error.detail.get("code") == "recipe_not_reproducible":
            return error.detail["assessment"]
        return {"status": "failed", "issues": [{"code": "evaluation_rejected", "detail": error.detail}],
                "native_editable": False}
    except (ValueError, KeyError, TypeError) as error:
        return {"status": "failed", "issues": [{"code": "invalid_routing_input", "detail": str(error)[:2048]}],
                "native_editable": False}


def _inputs(source, request, header, executor, dependency_resolver):
    from backend.api.part_proof_commands import execute_long, dependencies
    from backend.api.part_recipe_prefix import ReplayPrefix
    from backend.api.part_routing_edit_context import inventory, validate_packet
    from backend.core.part_history_contract import assess_part_history

    executor = executor or execute_long
    prefix = ReplayPrefix(source, request.index, sub_index=request.sub_index)
    proof = assess_part_history(source, execute=lambda kind, design, params: prefix.execute(executor, kind, design, params),
                                dependencies=dependency_resolver or dependencies)
    if proof["status"] not in {"verified", "reproduced_import"}:
        return proof
    if prefix.child_design is None:
        raise CommandContractError("Historical routing prefix is unavailable", code="missing_routing_prefix")
    values = dict(kind=header["expected_kind"], design_id=source.id, revision=header["source_revision"],
                  feature_id=header["expected_feature_id"], child_id=header["expected_child_id"])
    packet = {"kind": values["kind"], "params": request.params, "prefix": inventory(prefix.child_design),
              "source_design_id": source.id, "source_revision": values["revision"],
              "feature_id": values["feature_id"], "child_id": values["child_id"]}
    return {"status": "preview", "issues": [],
            "routing_inputs": validate_packet(packet, expected_params=request.params, **values)}
