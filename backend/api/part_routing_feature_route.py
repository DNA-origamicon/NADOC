"""Thin source-bound HTTP adapter for native Fine Routing child editors."""

from threading import Lock

from fastapi import APIRouter

from backend.api.part_bounded_json import read_operation_json
from backend.api.part_source_bound_route import SourceBoundRoute


class FeatureEditRoute(SourceBoundRoute):
    policy_operation = "owned_recipe_rebuild"
    input_prefix = "feature_edit"
    input_label = "Feature edit"
    input_slot = Lock()
    allow_empty_delete = False
    body_reader = staticmethod(lambda *args, **kwargs: read_operation_json(*args, **kwargs))


router = APIRouter(route_class=FeatureEditRoute)


def owns_edit(design, entry, body, sub_index):
    # Captured requests must never fall through to a legacy address-only path,
    # including a parent replaced by a different kind between UI and request.
    guarded = any(value is not None for value in (body.expected_design_id,
        body.expected_revision, body.expected_feature_id, body.expected_child_id))
    return (body.expected_child_id is not None or
            (sub_index is not None and entry.feature_type == "routing-cluster"
             and (guarded or design.group_organization is not None)))


def edit_response(index, body, *, sub_index):
    from backend.api.crud import _design_response_with_geometry
    from backend.api.part_ordinary_recipe_recording import edit_routing

    candidate, report, parent = edit_routing(index, sub_index, body.params,
        expected_design_id=body.expected_design_id, expected_revision=body.expected_revision,
        expected_feature_id=body.expected_feature_id, expected_child_id=body.expected_child_id)
    return _design_response_with_geometry(candidate, report, embed_straight=True,
        normalize_legacy=False, preserve_feature_log_id=parent.id, full_feature_log=True)


@router.get("/design/features/{index}/routing-inputs")
def routing_inputs(index: int, sub_index: int, expected_design_id: str, expected_revision: int,
                   expected_feature_id: str, expected_child_id: str):
    from backend.api.part_ordinary_recipe_recording import routing_inputs as prepare
    return prepare(index, sub_index, expected_design_id=expected_design_id,
        expected_revision=expected_revision, expected_feature_id=expected_feature_id,
        expected_child_id=expected_child_id)
