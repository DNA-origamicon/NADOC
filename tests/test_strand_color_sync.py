"""
Tests for strand colour synchronisation between the cadnano 2D editor and the
3D helix renderer.

Both views must show the *same* colour for every staple strand.

Color assignment model
──────────────────────
Backend (crud.py add_strand):
    strand.color = STAPLE_PALETTE[N]
    where N = number of staple strands that already existed before this one.

Backend (crud.py add_nick):
    Left fragment  → keeps original strand.color (model_copy).
    Right fragment → STAPLE_PALETTE[original_staple_count] (first new slot).

Cadnano editor (pathview.js strandColor):
    if strand.color is set  → use it directly
    else                    → STAPLE_PALETTE[strand_index_in_design.strands]

3D view (helix_renderer.js nucColor + client.js getDesign):
    if strand.id in strandColors (populated from strand.color) → use it
    else                                                        → buildStapleColorMap
                                                                  (palette by geometry order)

When strand.color is set in the design, both views converge on the same value.
These tests verify that property holds for every strand created by the pencil
tool or the nick tool, and that ligation preserves it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api import state as design_state
from backend.api.routes import _demo_design
from backend.core.constants import STAPLE_PALETTE
from backend.core.models import StrandType


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset():
    """Fresh HC demo design before each test; restored afterwards."""
    design_state.set_design(_demo_design())
    yield
    design_state.set_design(_demo_design())


@pytest.fixture
def client():
    return TestClient(app)


# ── Colour model helpers (mirror the JS logic) ─────────────────────────────────

def cadnano_color(strand: dict, idx: int) -> str | None:
    """Mirror pathview.js strandColor(strand, idx).

    Returns the colour the cadnano editor would display for this strand at
    position `idx` in the design.strands array.
    """
    if strand["strand_type"] == "scaffold":
        return None                                    # scaffold has a fixed CSS colour
    if strand.get("color"):
        return strand["color"]                         # explicit backend-assigned colour
    return STAPLE_PALETTE[idx % len(STAPLE_PALETTE)]  # index-based fallback


def build_strand_colors(design: dict) -> dict[str, str]:
    """Mirror client.js getDesign() strandColors merge.

    Collects strand.color values from the design JSON into the strandColors
    map that the 3D view uses as customColors.
    """
    result: dict[str, str] = {}
    for strand in design["strands"]:
        color = strand.get("color")
        if color and strand["id"] not in result:
            result[strand["id"]] = color
    return result


def threed_color(strand: dict, strand_colors: dict[str, str],
                 geometry_idx: int) -> str | None:
    """Mirror helix_renderer.js nucColor() + buildStapleColorMap fallback.

    `geometry_idx` is the position this strand would receive in
    buildStapleColorMap (first-appearance order in the geometry array).
    When strand.color is set, geometry_idx is irrelevant — customColors wins.
    """
    if strand["strand_type"] == "scaffold":
        return None
    sid = strand["id"]
    if sid in strand_colors:
        return strand_colors[sid]                          # customColors priority
    return STAPLE_PALETTE[geometry_idx % len(STAPLE_PALETTE)]  # fallback


# ── API helpers ───────────────────────────────────────────────────────────────

def _make_hc_design(client) -> dict:
    r = client.post("/api/design", json={"name": "test", "lattice_type": "HONEYCOMB"})
    assert r.status_code == 201
    return r.json()["design"]


def _add_helix(client, row: int, col: int) -> dict:
    r = client.post("/api/design/helix-at-cell", json={"row": row, "col": col})
    assert r.status_code == 201
    return r.json()


def _paint_staple(client, helix_id: str, start_bp: int, end_bp: int,
                  direction: str = "FORWARD") -> dict:
    """Add a single-domain staple via the pencil-tool endpoint."""
    r = client.post("/api/design/strands", json={
        "domains": [{
            "helix_id": helix_id,
            "start_bp": start_bp,
            "end_bp":   end_bp,
            "direction": direction,
        }],
        "strand_type": "staple",
    })
    assert r.status_code == 201, r.text
    return r.json()


def _nick(client, helix_id: str, bp_index: int, direction: str) -> dict:
    r = client.post("/api/design/nick", json={
        "helix_id": helix_id, "bp_index": bp_index, "direction": direction,
    })
    assert r.status_code == 201, r.text
    return r.json()


def _ligate(client, helix_id: str, bp_index: int, direction: str) -> dict:
    r = client.post("/api/design/ligate", json={
        "helix_id": helix_id, "bp_index": bp_index, "direction": direction,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _staples(design: dict) -> list[dict]:
    """Return only staple strands from a design dict, preserving design order."""
    return [s for s in design["strands"] if s["strand_type"] == "staple"]


# ── Tests: pencil-painted strands ─────────────────────────────────────────────

class TestPencilStrandColors:
    """POST /design/strands — new strands from the pencil tool."""

    def test_first_staple_gets_palette_0(self, client):
        """First staple painted → strand.color == STAPLE_PALETTE[0]."""
        _make_hc_design(client)
        r = _add_helix(client, 0, 0)
        hid = r["design"]["helices"][0]["id"]

        resp = _paint_staple(client, hid, 0, 10)
        color = resp["strand"]["color"]
        assert color == STAPLE_PALETTE[0], (
            f"Expected STAPLE_PALETTE[0]={STAPLE_PALETTE[0]!r}, got {color!r}"
        )

    def test_sequential_strands_get_sequential_palette_colors(self, client):
        """Three staples painted in sequence → palette[0], palette[1], palette[2]."""
        _make_hc_design(client)
        r = _add_helix(client, 0, 0)
        hid = r["design"]["helices"][0]["id"]

        for i in range(3):
            resp = _paint_staple(client, hid, i * 15, i * 15 + 10)
            got = resp["strand"]["color"]
            want = STAPLE_PALETTE[i]
            assert got == want, f"Strand {i}: expected {want!r}, got {got!r}"

    def test_palette_cycles_after_12_strands(self, client):
        """Palette wraps at 12 — strand 12 gets STAPLE_PALETTE[0] again."""
        _make_hc_design(client)
        r = _add_helix(client, 0, 0)
        hid = r["design"]["helices"][0]["id"]

        for i in range(13):
            _paint_staple(client, hid, i * 3, i * 3 + 1)

        design = client.get("/api/design").json()["design"]
        staples = _staples(design)
        assert len(staples) == 13

        for idx, strand in enumerate(staples):
            want = STAPLE_PALETTE[idx % len(STAPLE_PALETTE)]
            assert strand["color"] == want, (
                f"Strand at idx={idx}: expected {want!r}, got {strand['color']!r}"
            )

    def test_cadnano_and_3d_agree_for_pencil_strands(self, client):
        """For every pencil-painted staple, cadnano color == 3D color."""
        _make_hc_design(client)
        r = _add_helix(client, 0, 0)
        hid = r["design"]["helices"][0]["id"]

        for i in range(6):
            _paint_staple(client, hid, i * 6, i * 6 + 4)

        design = client.get("/api/design").json()["design"]
        staples = _staples(design)
        strand_colors = build_strand_colors(design)

        mismatches = []
        for idx, strand in enumerate(staples):
            cn = cadnano_color(strand, idx)
            td = strand_colors.get(strand["id"])
            if cn != td:
                mismatches.append(
                    f"  idx={idx} id={strand['id'][:8]}: cadnano={cn!r} 3D={td!r}"
                )
        assert not mismatches, (
            "Cadnano / 3D colour mismatch for pencil strands:\n" + "\n".join(mismatches)
        )


# ── Tests: nick tool ──────────────────────────────────────────────────────────

class TestNickStrandColors:
    """POST /design/nick — colour assignment on split strands."""

    CELLS_6HB = [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)]

    # ── helpers ───────────────────────────────────────────────────────────────

    def _setup_single_staple(self, client) -> tuple[str, str, str]:
        """
        HC design, one helix, one FORWARD staple bp 0..41.
        Returns (helix_id, strand_id, strand_color).
        """
        _make_hc_design(client)
        r = _add_helix(client, 0, 0)
        hid = r["design"]["helices"][0]["id"]
        resp = _paint_staple(client, hid, 0, 41)
        s = resp["strand"]
        return hid, s["id"], s["color"]

    def _setup_6hb_with_one_staple_per_helix(self, client) -> tuple[list[str], dict]:
        """
        6-helix HC bundle, one FORWARD staple per helix.
        Returns (helix_ids, design).
        """
        _make_hc_design(client)
        helix_ids = []
        for row, col in self.CELLS_6HB:
            r = client.post(
                "/api/design/helix-at-cell", json={"row": row, "col": col}
            )
            assert r.status_code == 201
            helix_ids.append(r.json()["design"]["helices"][-1]["id"])

        for hid in helix_ids:
            _paint_staple(client, hid, 5, 35)

        design = client.get("/api/design").json()["design"]
        return helix_ids, design

    # ── single-strand tests ───────────────────────────────────────────────────

    def test_left_fragment_keeps_original_color(self, client):
        """Left fragment (same ID) keeps the original strand color after nick."""
        hid, orig_id, orig_color = self._setup_single_staple(client)
        assert orig_color == STAPLE_PALETTE[0]

        resp = _nick(client, hid, 20, "FORWARD")
        design = resp["design"]
        staples = _staples(design)
        assert len(staples) == 2

        left = next(s for s in staples if s["id"] == orig_id)
        assert left["color"] == orig_color, (
            f"Left fragment should keep {orig_color!r}, got {left['color']!r}"
        )

    def test_right_fragment_gets_next_palette_slot(self, client):
        """Right fragment (new ID) gets STAPLE_PALETTE[1] (1 staple existed before nick)."""
        hid, orig_id, _ = self._setup_single_staple(client)
        resp = _nick(client, hid, 20, "FORWARD")
        staples = _staples(resp["design"])
        assert len(staples) == 2

        right = next(s for s in staples if s["id"] != orig_id)
        assert right["color"] == STAPLE_PALETTE[1], (
            f"Right fragment: expected STAPLE_PALETTE[1]={STAPLE_PALETTE[1]!r}, "
            f"got {right['color']!r}"
        )

    def test_right_fragment_has_color_set(self, client):
        """Right fragment must have strand.color set (not None) so 3D view syncs."""
        hid, orig_id, _ = self._setup_single_staple(client)
        resp = _nick(client, hid, 20, "FORWARD")
        staples = _staples(resp["design"])
        right = next(s for s in staples if s["id"] != orig_id)
        assert right["color"] is not None, (
            "Right fragment has color=None — 3D view will use buildStapleColorMap "
            "fallback, which may differ from cadnano editor index-based fallback."
        )

    def test_cadnano_and_3d_agree_after_nick(self, client):
        """After nick, cadnano color == 3D color for both fragments."""
        hid, _, _ = self._setup_single_staple(client)
        resp = _nick(client, hid, 20, "FORWARD")
        design = resp["design"]
        staples = _staples(design)
        strand_colors = build_strand_colors(design)

        mismatches = []
        for idx, strand in enumerate(staples):
            cn = cadnano_color(strand, idx)
            td = strand_colors.get(strand["id"])
            if cn != td:
                mismatches.append(
                    f"  idx={idx} id={strand['id'][:8]}: cadnano={cn!r} 3D={td!r}"
                )
        assert not mismatches, (
            "Cadnano / 3D colour mismatch after nick:\n" + "\n".join(mismatches)
        )

    def test_double_nick_all_fragments_colored(self, client):
        """Two nicks → three fragments, all with strand.color set and views agreeing."""
        hid, _, _ = self._setup_single_staple(client)
        _nick(client, hid, 14, "FORWARD")
        resp = _nick(client, hid, 28, "FORWARD")
        design = resp["design"]
        staples = _staples(design)
        assert len(staples) == 3, f"Expected 3 fragments, got {len(staples)}"

        strand_colors = build_strand_colors(design)
        mismatches = []
        for idx, strand in enumerate(staples):
            assert strand["color"] is not None, (
                f"Fragment {strand['id'][:8]} has color=None"
            )
            cn = cadnano_color(strand, idx)
            td = strand_colors.get(strand["id"])
            if cn != td:
                mismatches.append(
                    f"  idx={idx} id={strand['id'][:8]}: cadnano={cn!r} 3D={td!r}"
                )
        assert not mismatches, (
            "Cadnano / 3D colour mismatch after double nick:\n" + "\n".join(mismatches)
        )

    # ── 6HB tests ─────────────────────────────────────────────────────────────

    def test_6hb_nick_does_not_shift_other_strand_colors(self, client):
        """
        Nick one staple in a 6HB.  All OTHER strands must keep exactly the
        same strand.color they had before — _assign_staple_colors must NOT
        retroactively recolour existing strands.
        """
        helix_ids, design_before = self._setup_6hb_with_one_staple_per_helix(client)
        before = {s["id"]: s["color"] for s in _staples(design_before)}

        # Nick the first helix's staple at bp 15
        resp = _nick(client, helix_ids[0], 15, "FORWARD")
        after = {s["id"]: s["color"] for s in _staples(resp["design"])}

        # IDs present in both before and after (left fragment + all untouched strands)
        unchanged_ids = set(before.keys()) & set(after.keys())
        shifts = []
        for sid in unchanged_ids:
            if after[sid] != before[sid]:
                shifts.append(
                    f"  {sid[:8]}: was {before[sid]!r}, now {after[sid]!r}"
                )
        assert not shifts, (
            "Nick caused colour shift in unrelated strands:\n" + "\n".join(shifts)
        )

    def test_6hb_cadnano_and_3d_agree_after_nick(self, client):
        """After nicking one staple in a 6HB all views must still agree on all strands."""
        helix_ids, _ = self._setup_6hb_with_one_staple_per_helix(client)
        resp = _nick(client, helix_ids[2], 18, "FORWARD")
        design = resp["design"]
        staples = _staples(design)
        strand_colors = build_strand_colors(design)

        mismatches = []
        for idx, strand in enumerate(staples):
            cn = cadnano_color(strand, idx)
            td = strand_colors.get(strand["id"])
            if cn != td:
                mismatches.append(
                    f"  idx={idx} id={strand['id'][:8]}: cadnano={cn!r} 3D={td!r}"
                )
        assert not mismatches, (
            "Cadnano / 3D mismatch in 6HB after nick:\n" + "\n".join(mismatches)
        )


# ── Tests: ligate ─────────────────────────────────────────────────────────────

class TestLigateStrandColors:
    """POST /design/ligate — colour preservation after strand merge."""

    def _setup_nicked(self, client, bp: int = 20) -> tuple[str, str, str, str]:
        """
        HC design, one helix, one FORWARD staple (bp 0..41), then nick at `bp`.
        Returns (helix_id, orig_strand_id, orig_color, right_color).
        """
        _make_hc_design(client)
        r = _add_helix(client, 0, 0)
        hid = r["design"]["helices"][0]["id"]
        resp = _paint_staple(client, hid, 0, 41)
        orig_id = resp["strand"]["id"]
        orig_color = resp["strand"]["color"]
        nick_resp = _nick(client, hid, bp, "FORWARD")
        staples = _staples(nick_resp["design"])
        right = next(s for s in staples if s["id"] != orig_id)
        return hid, orig_id, orig_color, right["color"]

    def test_ligate_produces_one_staple(self, client):
        """After ligating the nick, only one staple remains."""
        hid, _, _, _ = self._setup_nicked(client)
        resp = _ligate(client, hid, 20, "FORWARD")
        assert len(_staples(resp["design"])) == 1

    def test_ligate_merged_strand_has_left_id(self, client):
        """Merged strand keeps the left fragment's ID (original strand ID)."""
        hid, orig_id, _, _ = self._setup_nicked(client)
        resp = _ligate(client, hid, 20, "FORWARD")
        merged = _staples(resp["design"])[0]
        assert merged["id"] == orig_id, (
            f"Expected original id {orig_id[:8]!r}, got {merged['id'][:8]!r}"
        )

    def test_ligate_merged_strand_keeps_left_color(self, client):
        """Merged strand color == left fragment color (strand_a.color from ligate logic)."""
        hid, _, orig_color, _ = self._setup_nicked(client)
        resp = _ligate(client, hid, 20, "FORWARD")
        merged = _staples(resp["design"])[0]
        assert merged["color"] == orig_color, (
            f"Merged strand: expected {orig_color!r} (left color), got {merged['color']!r}"
        )

    def test_ligate_cadnano_and_3d_agree(self, client):
        """After ligate, cadnano color == 3D color for the merged strand."""
        hid, _, _, _ = self._setup_nicked(client)
        resp = _ligate(client, hid, 20, "FORWARD")
        design = resp["design"]
        staples = _staples(design)
        strand_colors = build_strand_colors(design)

        mismatches = []
        for idx, strand in enumerate(staples):
            cn = cadnano_color(strand, idx)
            td = strand_colors.get(strand["id"])
            if cn != td:
                mismatches.append(
                    f"  idx={idx} id={strand['id'][:8]}: cadnano={cn!r} 3D={td!r}"
                )
        assert not mismatches, (
            "Cadnano / 3D mismatch after ligate:\n" + "\n".join(mismatches)
        )

    def test_nick_then_ligate_restores_original_color(self, client):
        """Round-trip: nick then ligate → merged strand has the same color as before the nick."""
        hid, orig_id, orig_color, _ = self._setup_nicked(client)
        resp = _ligate(client, hid, 20, "FORWARD")
        merged = _staples(resp["design"])[0]
        assert merged["color"] == orig_color, (
            f"Round-trip color: expected {orig_color!r}, got {merged['color']!r}"
        )

    def test_multiple_nick_ligate_cycles_stable_color(self, client):
        """Nick and ligate twice in a row — color stays stable throughout."""
        _make_hc_design(client)
        r = _add_helix(client, 0, 0)
        hid = r["design"]["helices"][0]["id"]
        resp = _paint_staple(client, hid, 0, 41)
        orig_color = resp["strand"]["color"]

        for _ in range(2):
            _nick(client, hid, 20, "FORWARD")
            resp = _ligate(client, hid, 20, "FORWARD")

        merged = _staples(resp["design"])[0]
        assert merged["color"] == orig_color, (
            f"Color after 2× nick+ligate: expected {orig_color!r}, got {merged['color']!r}"
        )


# ── Tests: 6HB full colour comparison ─────────────────────────────────────────

class TestSixHelixBundleColors:
    """End-to-end: 6-helix HC design, one staple per helix, full colour check."""

    CELLS_6HB = [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)]

    def _build(self, client) -> tuple[list[str], dict]:
        """Create 6HB, paint one FORWARD staple per helix. Return (helix_ids, design)."""
        _make_hc_design(client)
        helix_ids = []
        for row, col in self.CELLS_6HB:
            r = client.post(
                "/api/design/helix-at-cell", json={"row": row, "col": col}
            )
            assert r.status_code == 201
            helix_ids.append(r.json()["design"]["helices"][-1]["id"])
        for hid in helix_ids:
            _paint_staple(client, hid, 5, 35)
        return helix_ids, client.get("/api/design").json()["design"]

    def test_all_6hb_staples_have_color(self, client):
        """Every staple on the 6HB has strand.color set — both views will agree."""
        _, design = self._build(client)
        staples = _staples(design)
        assert len(staples) == 6
        no_color = [s["id"][:8] for s in staples if not s.get("color")]
        assert not no_color, (
            f"Staples missing color (cadnano/3D will disagree): {no_color}"
        )

    def test_6hb_palette_assigned_by_creation_order(self, client):
        """Staple i (in design.strands order) gets STAPLE_PALETTE[i]."""
        _, design = self._build(client)
        staples = _staples(design)
        for idx, strand in enumerate(staples):
            want = STAPLE_PALETTE[idx % len(STAPLE_PALETTE)]
            assert strand["color"] == want, (
                f"Strand idx={idx}: expected {want!r}, got {strand['color']!r}"
            )

    def test_6hb_cadnano_and_3d_agree_on_all_staples(self, client):
        """Cadnano editor color == 3D view color for every staple in the 6HB."""
        _, design = self._build(client)
        staples = _staples(design)
        strand_colors = build_strand_colors(design)

        mismatches = []
        for idx, strand in enumerate(staples):
            cn = cadnano_color(strand, idx)
            td = strand_colors.get(strand["id"])
            helix = strand["domains"][0]["helix_id"][:8]
            if cn != td:
                mismatches.append(
                    f"  helix={helix} idx={idx}: cadnano={cn!r} 3D={td!r}"
                )
        assert not mismatches, (
            "Cadnano / 3D colour mismatch across 6HB:\n" + "\n".join(mismatches)
        )

    def test_6hb_nick_then_check_all_colors(self, client):
        """
        Nick one staple in the 6HB.  Full check:
          • Existing strands keep their colours.
          • Both fragments (left + right) have strand.color set.
          • Cadnano and 3D agree on all strands including fragments.
        """
        helix_ids, design_before = self._build(client)
        before = {s["id"]: s["color"] for s in _staples(design_before)}

        resp = _nick(client, helix_ids[3], 18, "FORWARD")
        design_after = resp["design"]
        staples_after = _staples(design_after)
        assert len(staples_after) == 7, f"Expected 7 staples after nick, got {len(staples_after)}"

        after_map = {s["id"]: s for s in staples_after}
        strand_colors = build_strand_colors(design_after)

        # Existing strands must not shift colour
        unchanged = set(before.keys()) & set(after_map.keys())
        shifts = [
            f"  {sid[:8]}: was {before[sid]!r}, now {after_map[sid]['color']!r}"
            for sid in unchanged
            if after_map[sid]["color"] != before[sid]
        ]
        assert not shifts, "Nick shifted colours of unrelated strands:\n" + "\n".join(shifts)

        # All strands must have color set
        no_color = [s["id"][:8] for s in staples_after if not s.get("color")]
        assert not no_color, f"Strands missing color after nick: {no_color}"

        # Cadnano and 3D must agree
        mismatches = []
        for idx, strand in enumerate(staples_after):
            cn = cadnano_color(strand, idx)
            td = strand_colors.get(strand["id"])
            if cn != td:
                mismatches.append(
                    f"  idx={idx} id={strand['id'][:8]}: cadnano={cn!r} 3D={td!r}"
                )
        assert not mismatches, (
            "Cadnano / 3D mismatch after nick in 6HB:\n" + "\n".join(mismatches)
        )
