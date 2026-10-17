"""Negotiated native geometry response; JSON remains the compatibility default."""

from fastapi.responses import ORJSONResponse, Response

from backend.core.native_geometry_binary import MEDIA_TYPE, pack_geometry_binary
from backend.core.native_compact_geometry import geometry_arrays_to_lists


def native_geometry_response(payload: dict, wire_format: str = "json") -> Response:
    if wire_format == "ndgb1":
        # Already compact binary64 arrays. Compressing this local display stream
        # delays first paint and blocks the server's event loop in gzip middleware.
        return Response(pack_geometry_binary(payload), media_type=MEDIA_TYPE,
                        headers={"Content-Encoding": "identity"})
    return ORJSONResponse(geometry_arrays_to_lists(payload))
