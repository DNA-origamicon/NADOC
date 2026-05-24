"""
Process-level server identity.

``SERVER_INSTANCE_ID`` is regenerated every time the Python process starts, so
a frontend tab that remembers the previous value can detect a backend restart
(the id changed) and re-sync — distinct from a mere document change (same id,
different document).  Exposed via ``GET /api/health``.
"""

from __future__ import annotations

import datetime as _dt
import uuid

# New random id per process start. Survives nothing — that's the point.
SERVER_INSTANCE_ID: str = uuid.uuid4().hex
STARTED_AT: str = _dt.datetime.now(_dt.timezone.utc).isoformat()
