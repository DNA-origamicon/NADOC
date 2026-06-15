"""Phase 2: a primitive appended onto a BENT face re-places when the upstream
bend is deleted or edited.

A deformed continuation (``make_bundle_deformed_continuation``) bakes the deformed
cross-section frame into its new helices. Storing ``source_bp`` makes the op
replayable: deleting/editing the bend re-runs the continuation against the
un-bent design (frame recomputed live), so the appended segment follows the part
back to straight instead of dangling at the old bent pose.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.models import Design

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_state():
    yield
    design_state.close_session()


def _new_helix_axis_dir(design: Design, known_ids: set[str]) -> np.ndarray:
    """Unit axis direction of the single helix not in ``known_ids`` (the helix the
    deformed continuation appended)."""
    new = [h for h in design.helices if h.id not in known_ids]
    assert len(new) == 1, f"expected exactly one appended helix, got {len(new)}"
    h = new[0]
    d = np.array([
        h.axis_end.x - h.axis_start.x,
        h.axis_end.y - h.axis_start.y,
        h.axis_end.z - h.axis_start.z,
    ])
    return d / np.linalg.norm(d)


def _setup_bend_then_append(kappa: float = 2.0):
    """Fresh 84-bp bundle → bend its middle → append a primitive onto the bent far
    end via a deformed continuation. Returns (ref_helix_id, base_ids, bend_index)."""
    r = client.post("/api/design/bundle", json={"cells": [[0, 0]], "length_bp": 84, "name": "B"})
    assert r.status_code == 201, r.text
    d = design_state.get_or_404()
    ref = d.helices[0].id
    base_ids = {h.id for h in d.helices}

    b = client.post("/api/design/deformation", json={
        "type": "bend", "plane_a_bp": 20, "plane_b_bp": 60,
        "params": {"kind": "bend", "curvature_deg_per_bp": kappa, "direction_deg": 0.0},
    })
    assert b.status_code == 200, b.text

    src = 84
    fr = client.get(f"/api/design/deformed-frame?source_bp={src}&ref_helix_id={ref}").json()
    c = client.post("/api/design/bundle-deformed-continuation", json={
        "cells": [[0, 0]], "length_bp": 21, "plane": "XY",
        "grid_origin": fr["grid_origin"], "axis_dir": fr["axis_dir"],
        "frame_right": fr["frame_right"], "frame_up": fr["frame_up"],
        "ref_helix_id": ref, "source_bp": src,
    })
    assert c.status_code == 201, c.text

    log = design_state.get_or_404().feature_log
    bend_i = next(i for i, e in enumerate(log) if e.feature_type == 'deformation')
    return ref, base_ids, bend_i


def test_appended_primitive_is_bent_before_delete():
    """Sanity: with the bend present, the appended helix points away from +Z."""
    _ref, base_ids, _bend_i = _setup_bend_then_append()
    bent = _new_helix_axis_dir(design_state.get_or_404(), base_ids)
    assert abs(bent[2]) < 0.9, f"expected a bent append, got axis dir {bent}"


def test_delete_bend_replaces_primitive_on_bent_face():
    _ref, base_ids, bend_i = _setup_bend_then_append()
    bent = _new_helix_axis_dir(design_state.get_or_404(), base_ids)
    assert abs(bent[2]) < 0.9

    r = client.delete(f"/api/design/features/{bend_i}")
    assert r.status_code == 200, r.text

    after = design_state.get_or_404()
    assert after.deformations == []                    # bend gone
    straight = _new_helix_axis_dir(after, base_ids)
    # Re-placed: the appended helix now extends straight along the base axis (+Z).
    assert abs(straight[2]) > 0.999, f"expected straight re-placement, got {straight}"


def test_edit_bend_to_zero_replaces_primitive():
    _ref, base_ids, bend_i = _setup_bend_then_append()
    bent = _new_helix_axis_dir(design_state.get_or_404(), base_ids)
    assert abs(bent[2]) < 0.9

    # Straighten the bend (curvature → 0) via the edit-feature endpoint.
    e = client.post(f"/api/design/features/{bend_i}/edit", json={"params": {
        "type": "bend", "plane_a_bp": 20, "plane_b_bp": 60,
        "params": {"kind": "bend", "curvature_deg_per_bp": 0.0, "direction_deg": 0.0},
    }})
    assert e.status_code == 200, e.text

    straight = _new_helix_axis_dir(design_state.get_or_404(), base_ids)
    assert abs(straight[2]) > 0.999, f"expected straight re-placement, got {straight}"


def test_legacy_continuation_without_source_bp_is_left_baked():
    """A continuation that never stored source_bp can't recompute its frame, so
    deleting the bend leaves it at the baked (bent) pose — graceful degradation,
    not a crash."""
    r = client.post("/api/design/bundle", json={"cells": [[0, 0]], "length_bp": 84, "name": "B"})
    assert r.status_code == 201
    d = design_state.get_or_404()
    ref = d.helices[0].id
    base_ids = {h.id for h in d.helices}

    client.post("/api/design/deformation", json={
        "type": "bend", "plane_a_bp": 20, "plane_b_bp": 60,
        "params": {"kind": "bend", "curvature_deg_per_bp": 2.0, "direction_deg": 0.0},
    })
    fr = client.get(f"/api/design/deformed-frame?source_bp=84&ref_helix_id={ref}").json()
    # NOTE: no source_bp → legacy baked-frame path.
    c = client.post("/api/design/bundle-deformed-continuation", json={
        "cells": [[0, 0]], "length_bp": 21, "plane": "XY",
        "grid_origin": fr["grid_origin"], "axis_dir": fr["axis_dir"],
        "frame_right": fr["frame_right"], "frame_up": fr["frame_up"],
        "ref_helix_id": ref,
    })
    assert c.status_code == 201, c.text
    bent = _new_helix_axis_dir(design_state.get_or_404(), base_ids)

    log = design_state.get_or_404().feature_log
    bend_i = next(i for i, e in enumerate(log) if e.feature_type == 'deformation')
    r = client.delete(f"/api/design/features/{bend_i}")
    assert r.status_code == 200, r.text

    after = design_state.get_or_404()
    assert after.deformations == []
    still = _new_helix_axis_dir(after, base_ids)
    # No source_bp → frame couldn't be recomputed → append stays at the bent pose.
    assert np.allclose(still, bent, atol=1e-6), f"expected unchanged baked pose, got {still} vs {bent}"
