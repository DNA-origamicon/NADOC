"""Bounded acquisition for the staged ordinary Connect route."""
from threading import Lock

from fastapi.routing import APIRoute

from backend.api.part_bounded_json import read_operation_json
from backend.api.part_source_bound_route import SourceBoundRoute


class ConnectRoute(SourceBoundRoute):
    policy_operation = 'finite_connection_apply'
    input_prefix = 'connection_connect'
    input_label = 'Create and connect'
    input_slot = Lock()
    allow_empty_delete = False
    body_reader = staticmethod(lambda *args, **kwargs: read_operation_json(*args, **kwargs))

    def get_route_handler(self):
        owned = super().get_route_handler()
        legacy = APIRoute.get_route_handler(self)

        async def dispatch(request):
            from backend.api.routes_connection_versions import OWNED_COMBINED_CONNECTION_APPLY_ENABLED
            return await (owned(request) if OWNED_COMBINED_CONNECTION_APPLY_ENABLED else legacy(request))

        return dispatch
