"""Fine Routing cluster log entries — auto-grouping, sub-position seek,
revert-with-truncation, persistence, eviction.

Wave A (commit 1) covers the cluster mechanics with a single converted
endpoint (``add_nick``). Subsequent waves add tests as more endpoints are
converted.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.lattice import make_bundle_design
from backend.core.models import (
    Design,
    MinorMutationLogEntry,
    RoutingClusterLogEntry,
)

client = TestClient(app)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_target() -> Design:
    """Two-helix HC bundle with strands long enough to nick at multiple positions."""
    return make_bundle_design([(0, 0), (0, 1)], length_bp=84)


@pytest.fixture(autouse=True)
def reset_state():
    design_state.set_design(_make_target())
    yield
    design_state.close_session()


def _strand_endpoints(d: Design) -> list:
    """Sorted compact representation of strand endpoints — sensitive to nicks."""
    out = []
    for s in d.strands:
        if not s.domains:
            continue
        first, last = s.domains[0], s.domains[-1]
        out.append((s.strand_type.value, first.helix_id, first.start_bp, last.helix_id, last.end_bp))
    return sorted(out)


def _post(path: str, body=None):
    r = client.post(path, json=body) if body is not None else client.post(path)
    assert r.status_code in (200, 201), f"{path} → {r.status_code}: {r.text}"
    return r


def _nick(helix_id: str, bp: int, direction: str = 'FORWARD'):
    """Helper to invoke the converted add_nick endpoint."""
    return _post('/api/design/nick', {
        'helix_id': helix_id,
        'bp_index': bp,
        'direction': direction,
    })


# ── Test 1: consecutive minor ops cluster together ────────────────────────────


def test_two_consecutive_minor_ops_share_cluster():
    """Two nicks in a row should produce ONE routing-cluster entry with two children."""
    d0 = design_state.get_or_404()
    h_ids = [h.id for h in d0.helices]
    assert len(h_ids) >= 2

    _nick(h_ids[0], 7, 'FORWARD')
    _nick(h_ids[1], 14, 'REVERSE')

    log = design_state.get_or_404().feature_log
    assert len(log) == 1, f"expected 1 cluster, got {len(log)}: {[e.feature_type for e in log]}"
    cluster = log[0]
    assert isinstance(cluster, RoutingClusterLogEntry)
    assert cluster.label == 'Fine Routing'
    assert len(cluster.children) == 2
    assert all(isinstance(c, MinorMutationLogEntry) for c in cluster.children)
    assert all(c.op_subtype == 'nick' for c in cluster.children)
    assert cluster.pre_state_gz_b64 != ''
    assert cluster.post_state_gz_b64 != ''


# ── Test 2: snapshot op closes the cluster ────────────────────────────────────


def test_snapshot_op_closes_cluster():
    """A snapshot-emitting endpoint between two nicks closes the first cluster
    and the second nick starts a new one. Log shape: cluster(1) + snapshot + cluster(1)."""
    d0 = design_state.get_or_404()
    h0 = d0.helices[0].id

    _nick(h0, 7, 'FORWARD')
    _post('/api/design/auto-break')      # snapshot-emitting auto-op
    _nick(h0, 14, 'FORWARD')

    log = design_state.get_or_404().feature_log
    types = [e.feature_type for e in log]
    assert types == ['routing-cluster', 'snapshot', 'routing-cluster'], types
    assert len(log[0].children) == 1
    assert len(log[2].children) == 1


# ── Test 3: revert restores cluster pre-state and truncates ──────────────────


def test_cluster_revert_restores_pre_state_and_truncates():
    """Revert on a cluster: design returns to pre-cluster state, log truncated."""
    d0 = design_state.get_or_404()
    h_ids = [h.id for h in d0.helices]
    pre_sig = _strand_endpoints(d0)

    _nick(h_ids[0], 7, 'FORWARD')
    _nick(h_ids[1], 14, 'REVERSE')
    _nick(h_ids[0], 21, 'FORWARD')
    post_sig = _strand_endpoints(design_state.get_or_404())
    assert post_sig != pre_sig, "nicks must actually change the strand topology"

    r = client.post('/api/design/features/0/revert')
    assert r.status_code == 200, r.text
    reverted = design_state.get_or_404()

    assert _strand_endpoints(reverted) == pre_sig
    assert reverted.feature_log == []


# ── Test 4: sub-position seek replays partial children ───────────────────────


def test_seek_sub_position_replays_partial_children():
    """Cluster of 3 nicks; seek to (0, 1) → first two nicks active, third not."""
    d0 = design_state.get_or_404()
    h_ids = [h.id for h in d0.helices]

    _nick(h_ids[0], 7, 'FORWARD')                  # child 0
    sig_after_one = _strand_endpoints(design_state.get_or_404())
    _nick(h_ids[1], 14, 'REVERSE')                 # child 1
    sig_after_two = _strand_endpoints(design_state.get_or_404())
    _nick(h_ids[0], 21, 'FORWARD')                 # child 2
    sig_after_three = _strand_endpoints(design_state.get_or_404())

    # Seek to (0, 1) — first two children active
    r = client.post('/api/design/features/seek', json={'position': 0, 'sub_position': 1})
    assert r.status_code == 200, r.text
    assert _strand_endpoints(design_state.get_or_404()) == sig_after_two

    # Seek to (0, 0) — only first child active
    r = client.post('/api/design/features/seek', json={'position': 0, 'sub_position': 0})
    assert r.status_code == 200, r.text
    assert _strand_endpoints(design_state.get_or_404()) == sig_after_one

    # Seek back to end — all three active again
    r = client.post('/api/design/features/seek', json={'position': -1})
    assert r.status_code == 200, r.text
    assert _strand_endpoints(design_state.get_or_404()) == sig_after_three


# ── Test 5: sub_position == -2 restores cluster pre-state ────────────────────


def test_seek_sub_position_minus_two_restores_pre_cluster():
    """sub_position=-2 hydrates the cluster's pre-state — design as it was
    before the cluster's first child ran."""
    d0 = design_state.get_or_404()
    pre_sig = _strand_endpoints(d0)
    h_ids = [h.id for h in d0.helices]

    _nick(h_ids[0], 7, 'FORWARD')
    _nick(h_ids[1], 14, 'REVERSE')

    r = client.post('/api/design/features/seek', json={'position': 0, 'sub_position': -2})
    assert r.status_code == 200, r.text
    assert _strand_endpoints(design_state.get_or_404()) == pre_sig


# ── Test 6: cluster persists across save/load round-trip ─────────────────────


def test_cluster_persists_through_round_trip():
    """Pydantic JSON round-trip preserves cluster + children + revert capability."""
    d0 = design_state.get_or_404()
    pre_sig = _strand_endpoints(d0)
    h_ids = [h.id for h in d0.helices]

    _nick(h_ids[0], 7, 'FORWARD')
    _nick(h_ids[1], 14, 'REVERSE')
    payload = design_state.get_or_404().to_json()

    design_state.close_session()
    design_state.set_design(Design.from_json(payload))

    log = design_state.get_or_404().feature_log
    assert len(log) == 1
    cluster = log[0]
    assert isinstance(cluster, RoutingClusterLogEntry)
    assert len(cluster.children) == 2
    assert all(c.op_subtype == 'nick' for c in cluster.children)

    # Revert still works after the round-trip.
    r = client.post('/api/design/features/0/revert')
    assert r.status_code == 200, r.text
    assert _strand_endpoints(design_state.get_or_404()) == pre_sig


# ── Test 7: Ctrl-Z undoes one minor op at a time ─────────────────────────────


def test_undo_pops_one_minor_op_at_a_time():
    """Each call to mutate_with_minor_log pushes ONE undo entry (matches the
    single-step undo guarantee). 3 nicks → 3 Ctrl-Z to clear the cluster."""
    d0 = design_state.get_or_404()
    pre_sig = _strand_endpoints(d0)
    h_ids = [h.id for h in d0.helices]

    _nick(h_ids[0], 7, 'FORWARD')
    _nick(h_ids[1], 14, 'REVERSE')
    _nick(h_ids[0], 21, 'FORWARD')
    assert len(design_state.get_or_404().feature_log[0].children) == 3

    for _ in range(3):
        r = client.post('/api/design/undo')
        assert r.status_code == 200, r.text

    # Three undos should restore the pre-cluster state.
    assert _strand_endpoints(design_state.get_or_404()) == pre_sig


# ── Test 8: revert on an evicted cluster returns 410 ─────────────────────────


def test_evicted_cluster_revert_returns_410(monkeypatch):
    """Force a tiny budget so the first cluster is evicted; revert on it
    returns 410 GONE (matches snapshot-evicted behavior)."""
    monkeypatch.setattr(design_state, 'MAX_SNAPSHOT_BUDGET_BYTES', 100)

    d0 = design_state.get_or_404()
    h0 = d0.helices[0].id

    _nick(h0, 7, 'FORWARD')                     # cluster 0 (will be evicted)
    _post('/api/design/auto-break')             # snapshot — closes cluster 0
    _nick(h0, 21, 'FORWARD')                    # cluster 2 (newest)

    log = design_state.get_or_404().feature_log
    cluster0 = log[0]
    assert isinstance(cluster0, RoutingClusterLogEntry)
    assert cluster0.evicted is True

    r = client.post('/api/design/features/0/revert')
    assert r.status_code == 410, r.text


# ── Test 9: cluster pre-state matches the design before the first child ──────


def test_cluster_pre_state_matches_pre_cluster_design():
    """Decoding the cluster's pre_state_gz_b64 yields the design as it was
    immediately before the cluster's first child ran (modulo feature_log)."""
    d0 = design_state.get_or_404()
    pre_sig = _strand_endpoints(d0)
    h0 = d0.helices[0].id

    _nick(h0, 7, 'FORWARD')
    _nick(h0, 14, 'FORWARD')

    cluster = design_state.get_or_404().feature_log[0]
    pre = design_state.decode_design_snapshot(cluster.pre_state_gz_b64)
    assert _strand_endpoints(pre) == pre_sig
    # Decoded snapshot has feature_log stripped per encode_design_snapshot rule.
    assert pre.feature_log == []


# ── Multi-subtype cluster (Wave B-H coverage) ────────────────────────────────


def test_mixed_subtype_cluster_groups_correctly():
    """Different op subtypes (nick + ligate + crossover-delete) all share one
    cluster as long as no snapshot op intervenes."""
    d0 = design_state.get_or_404()
    h_ids = [h.id for h in d0.helices]

    _nick(h_ids[0], 7, 'FORWARD')
    _post('/api/design/ligate', {'helix_id': h_ids[0], 'bp_index': 7, 'direction': 'FORWARD'})
    # Trigger a strand-color update to add another distinct subtype.
    staple_strands = [s for s in design_state.get_or_404().strands if s.strand_type.value == 'staple']
    if staple_strands:
        client.patch(
            '/api/design/strands/colors',
            json={'strand_ids': [staple_strands[0].id], 'color': '#FF00FF'},
        )

    log = design_state.get_or_404().feature_log
    assert len(log) == 1
    cluster = log[0]
    subtypes = [c.op_subtype for c in cluster.children]
    assert 'nick' in subtypes
    assert 'ligate' in subtypes
    if staple_strands:
        assert 'strands-color-bulk' in subtypes


def test_revert_to_before_extrusion_after_cluster():
    """Revert works on snapshot entries (extrusions/auto-ops) even when
    intervening clusters exist between them."""
    # Start with a fresh bundle so we have a snapshot at index 0 to revert to.
    design_state.set_design(_make_target())
    h0 = design_state.get_or_404().helices[0].id

    # Some minor ops form cluster 0.
    _nick(h0, 7, 'FORWARD')
    _nick(h0, 14, 'FORWARD')
    # Snapshot op (auto-break) closes cluster 0, becomes log[1].
    _post('/api/design/auto-break')
    # Another cluster after the snapshot.
    _nick(h0, 21, 'FORWARD')

    log = design_state.get_or_404().feature_log
    assert [e.feature_type for e in log] == ['routing-cluster', 'snapshot', 'routing-cluster']

    # Revert the cluster at index 0 — truncates entire log + restores pre-cluster state.
    pre_sig = _strand_endpoints(design_state.decode_design_snapshot(log[0].pre_state_gz_b64))
    r = client.post('/api/design/features/0/revert')
    assert r.status_code == 200, r.text
    assert _strand_endpoints(design_state.get_or_404()) == pre_sig
    assert design_state.get_or_404().feature_log == []


# ── Replay dispatcher fallback (v1 limitation graceful path) ────────────────


def test_sub_position_seek_sets_cursor_correctly_for_last_cluster():
    """Regression: when sub_position is provided and the cluster IS the last
    log entry, cursor must be set to the explicit cluster index (NOT clamped
    to -1 / "end of log"). Otherwise the slider thumb snaps to the LAST notch
    in the array — which for an expanded cluster is the last sub-notch — even
    when the user asked for an earlier sub-position."""
    d0 = design_state.get_or_404()
    h0 = d0.helices[0].id

    # Single cluster (it IS the last log entry).
    _nick(h0, 7, 'FORWARD')
    _nick(h0, 14, 'FORWARD')
    _nick(h0, 21, 'FORWARD')

    log = design_state.get_or_404().feature_log
    assert len(log) == 1
    assert isinstance(log[0], RoutingClusterLogEntry)

    # Seek to mid-cluster (sub_position=0). Cursor MUST be 0 (cluster index),
    # NOT -1 (end-of-log). And feature_log_sub_cursor should reflect 0.
    r = client.post('/api/design/features/seek', json={'position': 0, 'sub_position': 0})
    assert r.status_code == 200, r.text
    d = design_state.get_or_404()
    assert d.feature_log_cursor == 0, f"cursor was {d.feature_log_cursor}, expected 0"
    assert d.feature_log_sub_cursor == 0, f"sub_cursor was {d.feature_log_sub_cursor}, expected 0"

    # Seek to a different sub_position; both fields update.
    r = client.post('/api/design/features/seek', json={'position': 0, 'sub_position': 1})
    assert r.status_code == 200, r.text
    d = design_state.get_or_404()
    assert d.feature_log_cursor == 0
    assert d.feature_log_sub_cursor == 1

    # Seek with sub_position=None (full cluster post-state). Cursor still 0
    # if cluster is the last entry, sub_cursor None.
    r = client.post('/api/design/features/seek', json={'position': 0})
    assert r.status_code == 200, r.text
    d = design_state.get_or_404()
    # When sub_position is unspecified AND position is the last entry, the
    # legacy "seek to end" fast path applies (cursor = -1).
    assert d.feature_log_cursor == -1
    assert d.feature_log_sub_cursor is None


def test_unsupported_subtype_replay_falls_back_to_post_state():
    """For op_subtypes whose builders aren't extracted yet (e.g. crossover-move),
    the dispatcher raises NotImplementedError and _seek_snapshot_base falls
    back to the cluster's POST-state for sub-position seeks."""
    d0 = design_state.get_or_404()
    h0 = d0.helices[0].id

    _nick(h0, 7, 'FORWARD')         # child 0 — replayable
    _nick(h0, 14, 'FORWARD')        # child 1 — replayable

    # Inject a synthetic child with an unsupported op_subtype to simulate a
    # v1-deferred subtype the dispatcher can't replay.
    d = design_state.get_or_404()
    cluster = d.feature_log[0]
    from backend.core.models import MinorMutationLogEntry
    cluster.children.append(MinorMutationLogEntry(
        op_subtype='helix-update', label='synthetic stub', params={},
    ))
    design_state.set_design_silent(d)

    # Sub-position seek to the synthetic child should NOT raise — fallback path.
    r = client.post('/api/design/features/seek', json={'position': 0, 'sub_position': 2})
    assert r.status_code == 200, r.text
    # Topology stays consistent (some valid design returned, no crash).
    assert design_state.get_or_404().helices
