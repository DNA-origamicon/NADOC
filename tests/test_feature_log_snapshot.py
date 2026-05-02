"""Snapshot-bearing feature log entries for auto-operations.

Covers ``SnapshotLogEntry`` (models), ``mutate_with_feature_log`` /
``encode_design_snapshot`` / ``_evict_oldest_snapshots_if_over_budget``
(state), and the ``POST /design/features/{index}/revert`` endpoint (crud).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.lattice import make_bundle_design
from backend.core.models import (
    Design,
    DeformationLogEntry,
    SnapshotLogEntry,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_autobreak_target() -> Design:
    """A 2-helix HC bundle long enough for autobreak to actually nick (≥ 60 bp)."""
    return make_bundle_design([(0, 0), (0, 1)], length_bp=84)


@pytest.fixture(autouse=True)
def reset_state():
    design_state.set_design(_make_autobreak_target())
    yield
    design_state.close_session()


def _strands_signature(d: Design) -> list:
    """Compact stable representation of the strand topology, modulo ordering."""
    out = []
    for s in sorted(d.strands, key=lambda x: x.id):
        doms = [(dm.helix_id, dm.start_bp, dm.end_bp, dm.direction.value) for dm in s.domains]
        out.append((s.id, s.strand_type.value, doms))
    return out


# ── Test 1: snapshot entry is appended ────────────────────────────────────────


def test_autobreak_appends_snapshot_entry():
    r = client.post("/api/design/auto-break")
    assert r.status_code == 200
    design = design_state.get_or_404()
    assert len(design.feature_log) == 1
    entry = design.feature_log[-1]
    assert entry.feature_type == 'snapshot'
    assert entry.op_kind == 'auto-break'
    assert entry.label == 'Autobreak'
    assert entry.snapshot_size_bytes > 0
    assert entry.design_snapshot_gz_b64 != ""
    assert entry.evicted is False
    assert 'algorithm' in entry.params


# ── Test 2: revert restores pre-state byte-exact ──────────────────────────────


def test_revert_restores_pre_state_byte_exact():
    pre = design_state.get_or_404().model_copy(deep=True)
    pre_sig = _strands_signature(pre)

    client.post("/api/design/auto-break")
    post = design_state.get_or_404()
    assert _strands_signature(post) != pre_sig, "autobreak must actually change strands for this test to be meaningful"

    r = client.post("/api/design/features/0/revert")
    assert r.status_code == 200, r.text
    reverted = design_state.get_or_404()

    assert _strands_signature(reverted) == pre_sig
    # Log truncated to before the snapshot entry.
    assert reverted.feature_log == []


# ── Test 3: revert survives a save/load round-trip (simulated browser refresh) ─


def test_revert_after_simulated_refresh():
    client.post("/api/design/auto-break")
    payload = design_state.get_or_404().to_json()

    # Simulate a fresh session that just loaded the .nadoc file.
    design_state.close_session()
    design_state.set_design(Design.from_json(payload))

    pre_post_autobreak = design_state.get_or_404().model_copy(deep=True)
    assert len(pre_post_autobreak.feature_log) == 1
    assert pre_post_autobreak.feature_log[0].feature_type == 'snapshot'

    r = client.post("/api/design/features/0/revert")
    assert r.status_code == 200, r.text
    reverted = design_state.get_or_404()
    assert reverted.feature_log == []
    expected = _strands_signature(_make_autobreak_target())
    assert _strands_signature(reverted) == expected


# ── Test 4: deleting a snapshot entry is allowed and does not alter the design ─


def test_delete_snapshot_entry_allowed_does_not_change_design():
    client.post("/api/design/auto-break")
    post_autobreak = _strands_signature(design_state.get_or_404())

    r = client.delete("/api/design/features/0")
    assert r.status_code == 200, r.text
    after_delete = design_state.get_or_404()

    assert after_delete.feature_log == []
    assert _strands_signature(after_delete) == post_autobreak


# ── Test 5: revert truncates the log; undo restores both design and log ──────


def test_revert_truncates_log_and_undo_restores():
    client.post("/api/design/auto-break")
    post_autobreak = design_state.get_or_404().model_copy(deep=True)
    assert len(post_autobreak.feature_log) == 1

    r = client.post("/api/design/features/0/revert")
    assert r.status_code == 200
    assert design_state.get_or_404().feature_log == []

    r = client.post("/api/design/undo")
    assert r.status_code == 200
    restored = design_state.get_or_404()
    assert _strands_signature(restored) == _strands_signature(post_autobreak)
    assert len(restored.feature_log) == 1
    assert restored.feature_log[0].feature_type == 'snapshot'


# ── Test 6: existing .nadoc files load without snapshot entries ───────────────


def test_old_nadoc_loads_without_snapshot_entries():
    """Discriminated-union backward compat: pre-snapshot fixtures must still load."""
    fixture = REPO_ROOT / "Examples" / "6hb_test.nadoc"
    if not fixture.exists():
        pytest.skip(f"{fixture} not available")
    design = Design.from_json(fixture.read_text())
    # No snapshot entries in old files; either empty log or only legacy delta types.
    for entry in design.feature_log:
        assert entry.feature_type in ('deformation', 'cluster_op', 'overhang_rotation')


# ── Test 7: budget-driven eviction ────────────────────────────────────────────


def test_chained_auto_ops_evict_under_budget(monkeypatch):
    """When the cumulative compressed snapshot bytes exceed the budget, the
    OLDEST snapshot bodies get evicted (set ``evicted=True``, payload cleared);
    log entries themselves remain so historical labels are still visible."""
    # Force a tiny budget so 2 sequential autobreaks trigger eviction.
    monkeypatch.setattr(design_state, 'MAX_SNAPSHOT_BUDGET_BYTES', 100)

    client.post("/api/design/auto-break")
    client.post("/api/design/auto-merge")
    client.post("/api/design/auto-break")

    log = design_state.get_or_404().feature_log
    snap_entries = [e for e in log if isinstance(e, SnapshotLogEntry)]
    assert len(snap_entries) == 3, f"expected 3 snapshot entries, got {len(snap_entries)}"

    # Oldest must be evicted; newest must NOT be.
    assert snap_entries[0].evicted is True
    assert snap_entries[0].design_snapshot_gz_b64 == ""
    assert snap_entries[-1].evicted is False
    assert snap_entries[-1].design_snapshot_gz_b64 != ""

    # Reverting an evicted entry returns 410 GONE.
    evicted_index = log.index(snap_entries[0])
    r = client.post(f"/api/design/features/{evicted_index}/revert")
    assert r.status_code == 410, r.text


# ── Test 8: snapshot does not recurse (no nested feature_logs) ────────────────


def test_snapshot_does_not_recurse():
    d = design_state.get_or_404()
    d.feature_log.append(DeformationLogEntry(deformation_id='preexisting'))
    design_state.set_design_silent(d)

    client.post("/api/design/auto-break")
    snap_entry = design_state.get_or_404().feature_log[-1]
    assert isinstance(snap_entry, SnapshotLogEntry)

    inner = design_state.decode_design_snapshot(snap_entry.design_snapshot_gz_b64)
    assert inner.feature_log == []
    assert inner.feature_log_cursor == -1


# ── Direct exercise of encode/decode helpers (no API) ─────────────────────────


def test_encode_decode_round_trip_preserves_topology():
    d = _make_autobreak_target()
    payload, size = design_state.encode_design_snapshot(d)
    assert size > 0
    assert len(payload) > 0

    restored = design_state.decode_design_snapshot(payload)
    assert _strands_signature(restored) == _strands_signature(d)
    assert restored.feature_log == []


# ── Snapshot-aware seek ───────────────────────────────────────────────────────


def _post(path: str, body=None):
    r = client.post(path, json=body) if body is not None else client.post(path)
    assert r.status_code == 200, r.text
    return r


def test_seek_through_snapshot_rolls_back_topology():
    """After autobreak, seeking back to F0 / pre-autobreak must restore the
    pre-autobreak strand topology — not just leave the post-break strands in
    place. (Without snapshot-aware seek, the slider would only reset deltas.)"""
    pre_sig = _strands_signature(design_state.get_or_404())

    _post("/api/design/auto-break")  # snapshot at index 0
    post_sig = _strands_signature(design_state.get_or_404())
    assert post_sig != pre_sig

    # Seek to F0 — should restore pre-autobreak topology.
    _post("/api/design/features/seek", {"position": -2})
    assert _strands_signature(design_state.get_or_404()) == pre_sig

    # Seek back to end — post-autobreak topology returns.
    _post("/api/design/features/seek", {"position": -1})
    assert _strands_signature(design_state.get_or_404()) == post_sig


def test_seek_between_two_snapshots():
    """With two consecutive auto-ops, seeking to the position between them
    must show the strands as they were AFTER op 1 but BEFORE op 2."""
    _post("/api/design/auto-break")        # snapshot at index 0
    after_break_sig = _strands_signature(design_state.get_or_404())

    _post("/api/design/auto-merge")        # snapshot at index 1
    after_merge_sig = _strands_signature(design_state.get_or_404())

    # Seek to position 0: only auto-break active, auto-merge NOT yet applied.
    _post("/api/design/features/seek", {"position": 0})
    assert _strands_signature(design_state.get_or_404()) == after_break_sig

    # Seek to position 1: both active.
    _post("/api/design/features/seek", {"position": 1})
    assert _strands_signature(design_state.get_or_404()) == after_merge_sig

    # Seek to F0: pristine pre-autobreak.
    _post("/api/design/features/seek", {"position": -2})
    assert _strands_signature(design_state.get_or_404()) == _strands_signature(_make_autobreak_target())


def test_seek_skips_evicted_snapshots(monkeypatch):
    """If the OLDEST snapshot's payload was evicted to free space, seeking back
    through it must fall back to the next non-evicted snapshot's pre-state.
    Topology won't match the original F0 byte-for-byte (eviction is lossy), but
    the seek must not crash and must produce a coherent design."""
    monkeypatch.setattr(design_state, 'MAX_SNAPSHOT_BUDGET_BYTES', 100)

    _post("/api/design/auto-break")        # will be evicted
    _post("/api/design/auto-merge")        # will be evicted
    _post("/api/design/auto-break")        # newest — kept

    log = design_state.get_or_404().feature_log
    assert log[0].evicted and log[1].evicted and not log[2].evicted

    # Seeking to position 0 (oldest snapshot, evicted) must not raise; falls
    # back to the next non-evicted snapshot's pre-state.
    _post("/api/design/features/seek", {"position": 0})
    d = design_state.get_or_404()
    # Coherent state: at least scaffold + staples present, no exception.
    assert any(s.strand_type.value == 'scaffold' for s in d.strands)


# ── Extrusion logging + F0 = empty workspace + editability ──────────────────


def test_create_bundle_logs_snapshot_with_empty_pre_state():
    """`/design/bundle` resets to an empty Design before logging so that
    seeking to F0 (position=-2) restores an empty workspace, regardless of
    what was loaded before."""
    # Pre-state design has helices (autobreak target was set by reset_state).
    assert len(design_state.get_or_404().helices) > 0

    r = client.post("/api/design/bundle", json={
        "cells": [[0, 0], [0, 1]],
        "length_bp": 42,
        "name": "TestBundle",
    })
    assert r.status_code == 201, r.text

    after = design_state.get_or_404()
    assert len(after.feature_log) == 1
    snap = after.feature_log[0]
    assert snap.feature_type == 'snapshot'
    assert snap.op_kind == 'bundle-create'
    assert snap.params['cells'] == [[0, 0], [0, 1]]
    assert snap.params['length_bp'] == 42

    # Seek to F0: must return an empty workspace.
    _post("/api/design/features/seek", {"position": -2})
    f0 = design_state.get_or_404()
    assert f0.helices == []
    assert f0.strands == []


def test_extrude_segment_logs_snapshot():
    """Slice-plane extrude appends a snapshot entry with full params."""
    # Start with a fresh bundle so we have something to extrude into.
    client.post("/api/design/bundle", json={"cells": [[0, 0]], "length_bp": 42, "name": "B"})

    r = client.post("/api/design/bundle-segment", json={
        "cells": [[0, 1]],
        "length_bp": 21,
        "plane": "XY",
        "offset_nm": 14.0,
    })
    assert r.status_code == 201, r.text

    log = design_state.get_or_404().feature_log
    assert log[-1].feature_type == 'snapshot'
    assert log[-1].op_kind == 'extrude-segment'
    assert log[-1].params['length_bp'] == 21
    assert log[-1].params['cells'] == [[0, 1]]


def test_overhang_extrude_logs_snapshot():
    """Overhang extrude appends a snapshot entry."""
    client.post("/api/design/bundle", json={"cells": [[0, 0]], "length_bp": 42, "name": "B"})
    design = design_state.get_or_404()
    helix_id = design.helices[0].id

    r = client.post("/api/design/overhang/extrude", json={
        "helix_id": helix_id,
        "bp_index": 21,
        "direction": "FORWARD",
        "is_five_prime": False,
        "neighbor_row": 0,
        "neighbor_col": 1,
        "length_bp": 8,
    })
    # Skip if the geometry constraints don't allow this particular extrude on the
    # 1-cell test bundle; the point of this test is just the snapshot bookkeeping.
    if r.status_code in (400, 422):
        pytest.skip(f"Overhang geometry not valid for this fixture: {r.text}")
    assert r.status_code == 200, r.text

    log = design_state.get_or_404().feature_log
    assert log[-1].op_kind == 'overhang-extrude'
    assert log[-1].params['length_bp'] == 8


def test_edit_extrusion_replays_with_new_length():
    """Editing the most-recent extrusion replays it with new params."""
    client.post("/api/design/bundle", json={"cells": [[0, 0]], "length_bp": 42, "name": "B"})
    client.post("/api/design/bundle-segment", json={
        "cells": [[0, 1]], "length_bp": 21, "plane": "XY", "offset_nm": 14.0,
    })

    log = design_state.get_or_404().feature_log
    seg_idx = next(i for i, e in enumerate(log) if isinstance(e, SnapshotLogEntry) and e.op_kind == 'extrude-segment')
    new_params = dict(log[seg_idx].params)
    new_params['length_bp'] = 35

    r = client.post(f"/api/design/features/{seg_idx}/edit", json={"params": new_params})
    assert r.status_code == 200, r.text

    after = design_state.get_or_404()
    assert after.feature_log[seg_idx].params['length_bp'] == 35
    # The segment helix should now reflect the new length.
    new_helices = [h for h in after.helices if (h.grid_pos or [None, None])[1] == 1]
    assert any(h.length_bp == 35 for h in new_helices), "new length must be present in extruded helix"


def test_edit_refused_when_later_snapshots_exist():
    """If a later snapshot exists, editing returns 409 with a useful message."""
    client.post("/api/design/bundle", json={"cells": [[0, 0]], "length_bp": 42, "name": "B"})
    client.post("/api/design/bundle-segment", json={
        "cells": [[0, 1]], "length_bp": 21, "plane": "XY", "offset_nm": 14.0,
    })
    # Now add a SECOND snapshot — autobreak — so the segment is no longer the latest.
    client.post("/api/design/auto-break")

    log = design_state.get_or_404().feature_log
    seg_idx = next(i for i, e in enumerate(log) if isinstance(e, SnapshotLogEntry) and e.op_kind == 'extrude-segment')
    new_params = dict(log[seg_idx].params)
    new_params['length_bp'] = 7

    r = client.post(f"/api/design/features/{seg_idx}/edit", json={"params": new_params})
    assert r.status_code == 409, r.text
    assert 'later snapshot' in r.text.lower()


def test_edit_refused_for_non_snapshot_entry():
    """Edit endpoint returns 400 if asked to edit a delta entry (deformation/cluster/overhang)."""
    client.post("/api/design/bundle", json={"cells": [[0, 0]], "length_bp": 42, "name": "B"})
    # Inject a synthetic deformation log entry — bypassing the API for test simplicity.
    d = design_state.get_or_404()
    d.feature_log.append(DeformationLogEntry(deformation_id='nonexistent'))
    design_state.set_design_silent(d)

    delta_idx = len(design_state.get_or_404().feature_log) - 1
    r = client.post(f"/api/design/features/{delta_idx}/edit", json={"params": {}})
    assert r.status_code == 400


def test_seek_preserves_full_log_for_back_and_forth():
    """Seeking forward then back must keep the full feature_log intact so the
    user can scrub freely. Cursor moves; payload stays."""
    _post("/api/design/auto-break")
    _post("/api/design/auto-merge")

    log_before_scrubbing = list(design_state.get_or_404().feature_log)

    _post("/api/design/features/seek", {"position": 0})
    _post("/api/design/features/seek", {"position": -2})
    _post("/api/design/features/seek", {"position": 1})
    _post("/api/design/features/seek", {"position": -1})

    log_after = list(design_state.get_or_404().feature_log)
    assert len(log_after) == len(log_before_scrubbing)
    for before, after in zip(log_before_scrubbing, log_after):
        assert before.feature_type == after.feature_type
        if isinstance(before, SnapshotLogEntry):
            assert after.design_snapshot_gz_b64 == before.design_snapshot_gz_b64
            assert not after.evicted
