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

    def enabled(self):
        from backend.api import routes_connection_versions as routes
        return routes.OWNED_COMBINED_CONNECTION_APPLY_ENABLED or routes.NATIVE_LINKER_V2_ENABLED

    def get_route_handler(self):
        owned = super().get_route_handler()
        legacy = APIRoute.get_route_handler(self)

        async def dispatch(request):
            return await (owned(request) if self.enabled() else legacy(request))

        return dispatch


async def _no_apply_inputs(request, **_kwargs):
    from fastapi import HTTPException
    # Apply selects its saved definition by path ID; there are no body inputs.
    if (len(request.headers.getlist('content-length')) > 1
            or request.headers.get('content-length') not in {None, '0'}
            or 'transfer-encoding' in request.headers):
        raise HTTPException(400, detail='Version Apply does not accept a request body.')
    return {}


class ApplyRoute(ConnectRoute):
    input_prefix = 'connection_apply'
    input_label = 'Apply connection version'
    body_reader = staticmethod(lambda *args, **kwargs: _no_apply_inputs(*args, **kwargs))

    def enabled(self):
        from backend.api.routes_connection_versions import NATIVE_LINKER_V2_ENABLED
        return NATIVE_LINKER_V2_ENABLED
