"""Bounded source-bound acquisition for the five existing extension routes."""

from threading import Lock

from backend.api.part_bounded_json import read_operation_json
from backend.api.part_source_bound_route import SourceBoundRoute, require_current

__all__ = ["ExtensionRoute", "require_current"]

_input_slot = Lock()


class ExtensionRoute(SourceBoundRoute):
    policy_operation = "extension_authoring"
    input_prefix = "extension"
    input_label = "Extension edit"
    input_slot = _input_slot
    allow_empty_delete = True
    body_reader = staticmethod(lambda *args, **kwargs: read_operation_json(*args, **kwargs))
