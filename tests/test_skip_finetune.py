"""Phase 5 (re-scoped) — greedy 1–5 discrete skip fine-tuner: pure candidate logic."""
from __future__ import annotations


from backend.api.skip_twist_tuning import build_sq_skip_design, square_cells
from backend.core.regional_skip_placer import core_candidates
from backend.core.skip_finetune import (
    apply_finetune_edit, current_skips_by_helix, identify_finetune_edits,
)

OVER = [(0.0, 0.0), (1.0, 6.0)]    # positive slope => locally over-wound => ADD
UNDER = [(0.0, 0.0), (1.0, -6.0)]  # negative slope => locally under-wound => REMOVE


def _flat_field(design, value=1.0):
    return {(h.id, bp): value for h in design.helices
            for bp in range(h.bp_start, h.bp_start + h.length_bp)}


def test_no_hotspots_no_edits():
    """A uniform/noise-only deviation field yields NO edits — the fine-tuner does no harm."""
    base = build_sq_skip_design(square_cells(2, 3), 40, 24)
    assert identify_finetune_edits(base, _flat_field(base), OVER, sigma=1.0) == []


def test_overwound_hotspot_proposes_add():
    base = build_sq_skip_design(square_cells(2, 3), 40, 24)
    field = _flat_field(base, 1.0)
    h = next(hh for hh in base.helices if core_candidates(base, hh))
    spot = core_candidates(base, h)[len(core_candidates(base, h)) // 2]
    field[(h.id, spot)] = 100.0                       # one strong hotspot
    edits = identify_finetune_edits(base, field, OVER, max_edits=5, sigma=1.0)
    assert len(edits) == 1
    e = edits[0]
    assert e["op"] == "add" and e["helix_id"] == h.id
    assert abs(e["bp_index"] - spot) <= 1             # at/near the hotspot, on a free core bp
    assert e["bp_index"] in core_candidates(base, h)


def test_underwound_hotspot_proposes_remove_of_nearest_skip():
    base = build_sq_skip_design(square_cells(2, 3), 40, 24)
    field = _flat_field(base, 1.0)
    # put the hotspot on a helix that actually has a skip to remove
    skips = current_skips_by_helix(base)
    h_id = next(hid for hid, s in skips.items() if s)
    near = skips[h_id][0]
    field[(h_id, near)] = 100.0
    edits = identify_finetune_edits(base, field, UNDER, max_edits=5, sigma=1.0)
    assert len(edits) == 1 and edits[0]["op"] == "remove"
    assert edits[0]["helix_id"] == h_id and edits[0]["bp_index"] == near


def test_caps_and_spaces_edits():
    base = build_sq_skip_design(square_cells(2, 3), 40, 24)
    field = _flat_field(base, 1.0)
    h = next(hh for hh in base.helices if len(core_candidates(base, hh)) >= 6)
    for bp in core_candidates(base, h):               # make the WHOLE helix a hotspot
        field[(h.id, bp)] = 100.0
    edits = identify_finetune_edits(base, field, OVER, max_edits=3, sigma=1.0, min_spacing=8)
    assert len(edits) <= 3                             # capped
    bps = sorted(e["bp_index"] for e in edits)
    assert all(b - a >= 8 for a, b in zip(bps, bps[1:]))   # spaced


def test_apply_add_and_remove():
    skips = {"A": [10, 30], "B": [20]}
    added = apply_finetune_edit(skips, {"helix_id": "A", "bp_index": 20, "op": "add"})
    assert added["A"] == [10, 20, 30] and skips["A"] == [10, 30]   # original untouched
    removed = apply_finetune_edit(skips, {"helix_id": "A", "bp_index": 28, "op": "remove"})
    assert removed["A"] == [10]                        # nearest (30) removed
    # remove the last skip on a helix drops the helix entry
    cleared = apply_finetune_edit({"B": [20]}, {"helix_id": "B", "bp_index": 20, "op": "remove"})
    assert "B" not in cleared


def test_signed_slope_sign():
    from backend.core.skip_finetune import _signed_overtwist_slope
    assert _signed_overtwist_slope(OVER, 0.5) > 0
    assert _signed_overtwist_slope(UNDER, 0.5) < 0
    assert _signed_overtwist_slope([], 0.5) == 0.0


# ── greedy loop orchestration (engine stubbed via _finetune_measure) ───────────

def _field(design, value=1.0):
    return {(h.id, bp): value for h in design.helices
            for bp in range(h.bp_start, h.bp_start + h.length_bp)}


def test_greedy_does_no_harm_when_no_hotspots(monkeypatch):
    """Flat deviation field → no candidates → 0 edits, converged skips returned intact."""
    import backend.api.skip_twist_tuning as st
    conv = build_sq_skip_design(square_cells(2, 3), 40, 24)
    orig = current_skips_by_helix(conv)
    monkeypatch.setattr(st, "_finetune_measure", lambda design, ws, **k: {
        "twist": 2.0, "dev_max": 2.0, "dev_mean": 1.0,
        "deviation_by_bp": _field(conv), "shape_profile": OVER})
    r = st.greedy_finetune_skips(conv, "/tmp", max_edits=3, tol_twist_deg=8.0)
    assert r["status"] == "done" and r["edits_kept"] == [] and r["converged_skips"] == orig


def test_greedy_accepts_improving_edit(monkeypatch):
    """A hotspot → one candidate; a trial that lowers dev_max within twist tol is ACCEPTED."""
    import backend.api.skip_twist_tuning as st
    conv = build_sq_skip_design(square_cells(2, 3), 40, 24)
    h = next(hh for hh in conv.helices if core_candidates(conv, hh))
    spot = core_candidates(conv, h)[len(core_candidates(conv, h)) // 2]
    field = _field(conv); field[(h.id, spot)] = 100.0
    calls = {"n": 0}
    def fake(design, ws, **k):
        calls["n"] += 1
        dev_max = 5.0 if calls["n"] == 1 else 3.0          # trial improves
        return {"twist": 3.0, "dev_max": dev_max, "dev_mean": 1.2,
                "deviation_by_bp": field, "shape_profile": OVER}
    monkeypatch.setattr(st, "_finetune_measure", fake)
    r = st.greedy_finetune_skips(conv, "/tmp", max_edits=2, tol_twist_deg=8.0)
    assert r["status"] == "done" and len(r["edits_kept"]) >= 1
    assert r["after"]["dev_max"] == 3.0
    placed = any(any(abs(b - spot) <= 1 for b in bps) for bps in r["converged_skips"].values())
    assert placed                                          # the add landed near the hotspot


def test_greedy_reverts_when_twist_breaks_tolerance(monkeypatch):
    """A trial that improves dev_max but pushes net twist out of tol is REVERTED."""
    import backend.api.skip_twist_tuning as st
    conv = build_sq_skip_design(square_cells(2, 3), 40, 24)
    orig = current_skips_by_helix(conv)
    h = next(hh for hh in conv.helices if core_candidates(conv, hh))
    spot = core_candidates(conv, h)[len(core_candidates(conv, h)) // 2]
    field = _field(conv); field[(h.id, spot)] = 100.0
    calls = {"n": 0}
    def fake(design, ws, **k):
        calls["n"] += 1
        twist = 3.0 if calls["n"] == 1 else 40.0           # trial breaks twist tol
        return {"twist": twist, "dev_max": 5.0 if calls["n"] == 1 else 1.0, "dev_mean": 1.0,
                "deviation_by_bp": field, "shape_profile": OVER}
    monkeypatch.setattr(st, "_finetune_measure", fake)
    r = st.greedy_finetune_skips(conv, "/tmp", max_edits=2, tol_twist_deg=5.0)
    assert r["status"] == "done" and r["edits_kept"] == []
    assert r["converged_skips"] == orig                    # reverted → unchanged


def test_greedy_reports_error_when_baseline_unmeasurable(monkeypatch):
    import backend.api.skip_twist_tuning as st
    conv = build_sq_skip_design(square_cells(2, 3), 40, 24)
    monkeypatch.setattr(st, "_finetune_measure", lambda design, ws, **k: None)
    r = st.greedy_finetune_skips(conv, "/tmp")
    assert r["status"] == "error" and r["edits_kept"] == []
