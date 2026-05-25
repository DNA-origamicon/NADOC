"""Diff-based per-sub-step revert/delete for Fine Routing clusters.

Covers the design_diff module (round-trip, defensive apply) and the end-to-end
per-sub-step boundary reconstruction / revert / delete using NON-replayable op
subtypes (ligate, strands-color-bulk) — the cases the old replay-only path
could not handle.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.crud import _state_at_child_boundary
from backend.api.main import app
from backend.core.design_diff import (
    apply_child_diff_forward,
    encode_child_diff,
    is_diff_child,
    _DIFF_FIELDS,
)
from backend.core.lattice import make_bundle_design
from backend.core.models import Design, RoutingClusterLogEntry

client = TestClient(app)


def _make_target() -> Design:
    return make_bundle_design([(0, 0), (0, 1)], length_bp=84)


@pytest.fixture(autouse=True)
def reset_state():
    design_state.set_design(_make_target())
    yield
    design_state.close_session()


def _sig(d: Design):
    """Topology + color signature — sensitive to nicks/ligations AND recolors."""
    out = []
    for s in d.strands:
        if not s.domains:
            continue
        first, last = s.domains[0], s.domains[-1]
        out.append((s.strand_type.value, first.helix_id, first.start_bp,
                    last.helix_id, last.end_bp, s.color))
    return sorted(out)


def _fields_equal(a: Design, b: Design) -> bool:
    for f in _DIFF_FIELDS:
        if [o.model_dump(mode="json") for o in getattr(a, f)] != \
           [o.model_dump(mode="json") for o in getattr(b, f)]:
            return False
    return True


def _post(path, body=None):
    r = client.post(path, json=body) if body is not None else client.post(path)
    assert r.status_code in (200, 201), f"{path} → {r.status_code}: {r.text}"
    return r


def _nick(helix_id, bp, direction='FORWARD'):
    return _post('/api/design/nick', {'helix_id': helix_id, 'bp_index': bp, 'direction': direction})


def _recolor(strand_ids, color):
    r = client.patch('/api/design/strands/colors', json={'strand_ids': strand_ids, 'color': color})
    assert r.status_code == 200, r.text
    return r


# ── design_diff unit tests ───────────────────────────────────────────────────


def test_diff_roundtrip_add_remove_modify():
    """encode then forward-apply reproduces the post-state on the diffed fields,
    for adds + removes + modifications across strands."""
    pre = _make_target()
    strands = list(pre.strands)
    # remove one strand, add a clone with a new id, modify another's color
    added = strands[0].model_copy(update={'id': 'ADDED-1', 'color': '#abcdef'})
    modified = strands[1].model_copy(update={'color': '#123456'})
    post = pre.copy_with(strands=[modified] + strands[2:] + [added])  # strands[0] removed

    a, r, m, size = encode_child_diff(pre, post)
    assert a and r and m and size > 0          # all three categories present
    got, warnings = apply_child_diff_forward(pre, a, r, m)
    assert warnings == []
    assert _fields_equal(got, post)


def test_diff_empty_when_unchanged():
    d = _make_target()
    a, r, m, size = encode_child_diff(d, d)
    assert (a, r, m, size) == ("", "", "", 0)


def test_defensive_apply_readds_absent_modify_with_warning():
    """Delete-of-base scenario: a child added strand B, a later child modified B.
    Applying the later child's diff to a base WITHOUT B (the adder was deleted)
    re-adds B (POST is self-contained) and records a warning."""
    pre = _make_target()
    b = pre.strands[0].model_copy(update={'id': 'B-ENT', 'color': '#111111'})
    mid = pre.copy_with(strands=pre.strands + [b])
    b2 = b.model_copy(update={'color': '#222222'})
    post = mid.copy_with(strands=mid.strands[:-1] + [b2])

    _a, _r, m, _s = encode_child_diff(mid, post)   # a "modify B" diff
    assert m

    # Non-defensive: absent modify is dropped silently → B not present.
    got_nd, w_nd = apply_child_diff_forward(pre, "", "", m, defensive=False)
    assert all(s.id != 'B-ENT' for s in got_nd.strands)
    assert w_nd == []

    # Defensive: absent modify re-adds B's POST state, with a warning.
    got_d, w_d = apply_child_diff_forward(pre, "", "", m, defensive=True)
    readded = [s for s in got_d.strands if s.id == 'B-ENT']
    assert readded and readded[0].color == '#222222'
    assert w_d, "defensive re-add should emit a warning"


def test_is_diff_child_flags():
    d = _make_target()
    _nick(d.helices[0].id, 7)
    cluster = design_state.get_or_404().feature_log[0]
    assert is_diff_child(cluster.children[0]) is True
    cluster.children[0].diff_added_b64 = ""
    cluster.children[0].diff_removed_b64 = ""
    cluster.children[0].diff_modified_b64 = ""
    assert is_diff_child(cluster.children[0]) is False


# ── Capture ──────────────────────────────────────────────────────────────────


def test_minor_ops_capture_diffs():
    """A non-replayable op (recolor) records a non-empty diff just like a nick."""
    d = design_state.get_or_404()
    h0 = d.helices[0].id
    _nick(h0, 7)
    staples = [s.id for s in design_state.get_or_404().strands if s.strand_type.value == 'staple']
    _recolor(staples[:1], '#FF00FF')

    cluster = design_state.get_or_404().feature_log[0]
    assert [c.op_subtype for c in cluster.children] == ['nick', 'strands-color-bulk']
    for c in cluster.children:
        assert is_diff_child(c), f"{c.op_subtype} captured no diff"


# ── Boundary reconstruction with non-replayable ops ──────────────────────────


def test_boundary_reconstruction_nonreplayable():
    d = design_state.get_or_404()
    h_ids = [h.id for h in d.helices]
    sigs = [_sig(design_state.get_or_404())]                       # boundary 0 (pre)

    _nick(h_ids[0], 7); sigs.append(_sig(design_state.get_or_404()))          # child 0
    _post('/api/design/ligate', {'helix_id': h_ids[0], 'bp_index': 7, 'direction': 'FORWARD'})
    sigs.append(_sig(design_state.get_or_404()))                              # child 1 (ligate, non-replayable)
    staples = [s.id for s in design_state.get_or_404().strands if s.strand_type.value == 'staple']
    _recolor(staples[:1], '#00FFAA'); sigs.append(_sig(design_state.get_or_404()))  # child 2 (color, non-replayable)

    cluster = design_state.get_or_404().feature_log[0]
    assert isinstance(cluster, RoutingClusterLogEntry)
    n = len(cluster.children)
    assert n == 3
    for k in range(n + 1):
        rebuilt = _state_at_child_boundary(cluster, k)
        assert _sig(rebuilt) == sigs[k], f"boundary({k}) mismatch"
    # boundary(n) == cluster post-state
    assert _sig(_state_at_child_boundary(cluster, n)) == \
           _sig(design_state.decode_design_snapshot(cluster.post_state_gz_b64))


# ── Revert before a non-replayable sub-step ──────────────────────────────────


def test_revert_before_nonreplayable_substep():
    d = design_state.get_or_404()
    h0 = d.helices[0].id
    _nick(h0, 7)
    sig_after_nick = _sig(design_state.get_or_404())
    staples = [s.id for s in design_state.get_or_404().strands if s.strand_type.value == 'staple']
    _recolor(staples[:1], '#00FFAA')                       # child 1 (non-replayable)

    # Revert before the recolor → topology has the nick, colors pre-recolor.
    r = client.post('/api/design/features/0/revert?sub_index=1')
    assert r.status_code == 200, r.text
    d = design_state.get_or_404()
    assert _sig(d) == sig_after_nick
    assert len(d.feature_log) == 1 and len(d.feature_log[0].children) == 1


def test_revert_before_first_substep_drops_cluster():
    pre = _sig(design_state.get_or_404())
    h0 = design_state.get_or_404().helices[0].id
    _nick(h0, 7)
    staples = [s.id for s in design_state.get_or_404().strands if s.strand_type.value == 'staple']
    _recolor(staples[:1], '#00FFAA')
    r = client.post('/api/design/features/0/revert?sub_index=0')
    assert r.status_code == 200, r.text
    d = design_state.get_or_404()
    assert d.feature_log == []
    assert _sig(d) == pre


# ── Delete a non-replayable sub-step ─────────────────────────────────────────


def test_delete_nonreplayable_substep_keeps_rest():
    """Cluster [recolor, nick]; delete the recolor (non-replayable) → nick stays,
    color reverts."""
    d = design_state.get_or_404()
    h0 = d.helices[0].id
    staples = [s.id for s in d.strands if s.strand_type.value == 'staple']
    pre_color = next(s.color for s in d.strands if s.id == staples[0])
    _recolor([staples[0]], '#00FFAA')      # child 0 (non-replayable)
    _nick(h0, 7)                            # child 1 (replayable)
    sig_both = _sig(design_state.get_or_404())

    r = client.delete('/api/design/features/0?sub_index=0')   # delete the recolor
    assert r.status_code == 200, r.text
    d = design_state.get_or_404()
    cluster = d.feature_log[0]
    assert len(cluster.children) == 1 and cluster.children[0].op_subtype == 'nick'
    # nick survives (topology differs from a clean bundle), recolor undone.
    assert _sig(d) != sig_both
    color_now = next((s.color for s in d.strands if s.id == staples[0]), None)
    assert color_now == pre_color


def test_delete_substep_undo_restores():
    d = design_state.get_or_404()
    h0 = d.helices[0].id
    staples = [s.id for s in d.strands if s.strand_type.value == 'staple']
    _recolor([staples[0]], '#00FFAA')
    _nick(h0, 7)
    sig_both = _sig(design_state.get_or_404())
    client.delete('/api/design/features/0?sub_index=0')
    r = client.post('/api/design/undo')
    assert r.status_code == 200, r.text
    assert _sig(design_state.get_or_404()) == sig_both


def test_entangled_delete_emits_warning():
    """Delete a nick whose new strand was later recolored → defensive re-add +
    a placement_warnings entry on the response."""
    d = design_state.get_or_404()
    h0 = d.helices[0].id
    before_ids = {s.id for s in d.strands}
    _nick(h0, 7)                                    # child 0 — splits a strand (new ids)
    new_ids = [s.id for s in design_state.get_or_404().strands if s.id not in before_ids]
    assert new_ids
    _recolor(new_ids[:1], '#00FFAA')                # child 1 — recolors a nick-created strand

    r = client.delete('/api/design/features/0?sub_index=0')   # delete the nick
    assert r.status_code == 200, r.text
    warns = r.json().get('placement_warnings') or []
    assert warns, "entangled delete should surface a best-effort warning"


# ── Eviction + persistence ───────────────────────────────────────────────────


def test_eviction_clears_child_diffs(monkeypatch):
    monkeypatch.setattr(design_state, 'MAX_SNAPSHOT_BUDGET_BYTES', 100)
    d0 = design_state.get_or_404()
    h0 = d0.helices[0].id
    _nick(h0, 7)                       # cluster 0 (to be evicted)
    _post('/api/design/auto-break')    # snapshot closes cluster 0
    _nick(h0, 21)                      # cluster 2 (newest, kept)

    log = design_state.get_or_404().feature_log
    cluster0 = log[0]
    assert isinstance(cluster0, RoutingClusterLogEntry)
    assert cluster0.evicted is True
    assert cluster0.diffs_evicted is True
    assert all(not is_diff_child(c) for c in cluster0.children)


def test_diffs_survive_nadoc_round_trip():
    d = design_state.get_or_404()
    h0 = d.helices[0].id
    _nick(h0, 7)
    staples = [s.id for s in design_state.get_or_404().strands if s.strand_type.value == 'staple']
    _recolor(staples[:1], '#00FFAA')
    sig_after = _sig(design_state.get_or_404())

    payload = design_state.get_or_404().to_json()
    design_state.close_session()
    design_state.set_design(Design.from_json(payload))

    cluster = design_state.get_or_404().feature_log[0]
    assert all(is_diff_child(c) for c in cluster.children)
    # Reconstruction still works post round-trip.
    assert _sig(_state_at_child_boundary(cluster, len(cluster.children))) == sig_after
    # Revert before the recolor still works.
    r = client.post('/api/design/features/0/revert?sub_index=1')
    assert r.status_code == 200, r.text
