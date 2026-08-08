"""Phase 1: revert + delete semantics for bend/twist deformation feature-log entries.

A bend or twist logs a lightweight ``DeformationLogEntry`` (a "delta" entry that
carries the op, not a baked topology snapshot). These tests pin:

  * ``POST /design/features/{i}/revert`` on a deformation entry truncates the log
    to ``[0..i-1]`` and rebuilds the design WITHOUT that deformation (and without
    every later entry) — the same user-facing contract as snapshot revert.
  * ``POST /design/undo`` restores the reverted deformation.
  * Reverting the FIRST of two stacked deformations drops both.
  * ``DELETE /design/features/{i}`` on a bend, with a later FLAT extrude segment,
    drops the bend from ``design.deformations`` while leaving the appended
    segment intact (the non-baked "append reflects the un-bent part" case).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.lattice import make_bundle_design
from backend.core.models import Design

client = TestClient(app)


def _make_bundle() -> Design:
    """A 2-helix HC bundle long enough to host a bend window."""
    return make_bundle_design([(0, 0), (0, 1)], length_bp=84)


@pytest.fixture(autouse=True)
def reset_state():
    design_state.set_design(_make_bundle())
    yield
    design_state.close_session()


def _add_bend(plane_a: int = 20, plane_b: int = 60, kappa: float = 1.0):
    return client.post(
        "/api/design/deformation",
        json={
            "type": "bend",
            "plane_a_bp": plane_a,
            "plane_b_bp": plane_b,
            "params": {
                "kind": "bend",
                "curvature_deg_per_bp": kappa,
                "direction_deg": 0.0,
            },
        },
    )


def test_bend_logs_deformation_entry():
    r = _add_bend()
    assert r.status_code == 200, r.text
    d = design_state.get_or_404()
    assert len(d.deformations) == 1
    assert len(d.feature_log) == 1
    assert d.feature_log[-1].feature_type == "deformation"


def test_revert_before_bend_truncates_and_unbends():
    _add_bend()
    bend_index = len(design_state.get_or_404().feature_log) - 1

    r = client.post(f"/api/design/features/{bend_index}/revert")
    assert r.status_code == 200, r.text
    reverted = design_state.get_or_404()
    assert reverted.deformations == []  # un-bent
    assert reverted.feature_log == []  # truncated to before the bend


def test_revert_before_bend_undo_restores():
    _add_bend()
    bend_index = len(design_state.get_or_404().feature_log) - 1
    client.post(f"/api/design/features/{bend_index}/revert")
    assert design_state.get_or_404().deformations == []

    r = client.post("/api/design/undo")
    assert r.status_code == 200, r.text
    restored = design_state.get_or_404()
    assert len(restored.deformations) == 1  # bend is back
    assert len(restored.feature_log) == 1


def test_revert_before_first_of_two_bends_drops_both():
    _add_bend(plane_a=10, plane_b=30)
    _add_bend(plane_a=40, plane_b=70)
    d = design_state.get_or_404()
    assert len(d.deformations) == 2
    assert len(d.feature_log) == 2

    r = client.post("/api/design/features/0/revert")
    assert r.status_code == 200, r.text
    reverted = design_state.get_or_404()
    assert reverted.deformations == []
    assert reverted.feature_log == []


def test_delete_bend_keeps_later_flat_append():
    """Deleting a bend that precedes a FLAT extrude segment drops the bend from
    design.deformations while the appended segment survives (the un-baked case
    where a later append correctly reflects the un-bent part)."""
    # Fresh single-cell bundle via the endpoint so the log starts with a
    # bundle-create snapshot we can restore topology from after the delete.
    r = client.post(
        "/api/design/bundle", json={"cells": [[0, 0]], "length_bp": 42, "name": "B"}
    )
    assert r.status_code == 201, r.text

    assert _add_bend(plane_a=8, plane_b=30).status_code == 200

    seg = client.post(
        "/api/design/bundle-segment",
        json={
            "cells": [[0, 1]],
            "length_bp": 21,
            "plane": "XY",
            "offset_nm": 14.0,
        },
    )
    assert seg.status_code == 201, seg.text

    d = design_state.get_or_404()
    helices_before = len(d.helices)
    assert len(d.deformations) == 1
    bend_index = next(
        i for i, e in enumerate(d.feature_log) if e.feature_type == "deformation"
    )

    r = client.delete(f"/api/design/features/{bend_index}")
    assert r.status_code == 200, r.text
    after = design_state.get_or_404()
    assert after.deformations == []  # un-bent
    assert len(after.helices) == helices_before  # appended segment intact
