"""
Round-trip tests for caDNAno v2 export ("export = import of export").

Regression guard for the exporter bug where designs whose strands run outside a
helix's nominal ``length_bp`` — scaffold overhangs extruded through the boundary,
extra bases, negative-bp editor segments — crashed export with ``IndexError``
(bp >= array_len) or silently corrupted it (bp < 0 wraps to the array tail).
``export_cadnano`` now shifts every bp by one uniform non-negative offset and
sizes the array to the true span rounded up to the lattice period.

Invariant model
───────────────
Absolute bp labels are intentionally relabelled on export (the origin is a free
gauge), so raw Design/JSON equality is NOT the round-trip contract. What must be
conserved is *topology*:

  * helix count,
  * per-strand TOTAL base count, grouped by strand type
    (domain SEGMENTATION legitimately differs — import coalesces contiguous
    same-helix runs — but no bases are created or destroyed),
  * loop/skip delta multiset.

Colors are NOT a universal invariant: caDNAno requires every staple to carry a
color, so export injects a default where the design had none — that cannot
round-trip to "no color". Colors are checked only on a colored native fixture.
"""

from __future__ import annotations

import json
import math
import pathlib
from collections import Counter

import pytest

from backend.core.models import Design, LatticeType
from backend.core.cadnano import (
    export_cadnano,
    import_cadnano,
    check_cadnano_compatibility,
    _assign_grid_coords,
    _HC_PERIOD,
    _SQ_PERIOD,
)
from backend.core.lattice import make_bundle_design

# ── Paths / fixtures ──────────────────────────────────────────────────────────

ROOT = pathlib.Path(__file__).parent.parent
EXAMPLES = ROOT / "Examples"
CN_JSON_DIR = EXAMPLES / "cadnano"

# Designs that previously CRASHED export (IndexError / silent negative-bp wrap).
REGRESSION_STEMS = ["2hb_xover_val", "NS_trans_fix", "U6hb"]


def _load_nadoc(path: pathlib.Path) -> Design:
    return Design.from_json(path.read_text())


def _exportable_nadoc_paths() -> list[pathlib.Path]:
    """All Examples/*.nadoc that load and have no ERROR-level incompatibility."""
    out = []
    for p in sorted(EXAMPLES.glob("*.nadoc")):
        try:
            d = _load_nadoc(p)
        except Exception:
            continue
        if any(w.startswith("ERROR") for w in check_cadnano_compatibility(d)):
            continue
        out.append(p)
    return out


def _cn_json_paths() -> list[pathlib.Path]:
    return sorted(CN_JSON_DIR.glob("*.json"))


NADOC_PATHS = _exportable_nadoc_paths()
JSON_PATHS = _cn_json_paths()


# ── Invariants ────────────────────────────────────────────────────────────────

def _topology_sig(d: Design) -> tuple:
    """Gauge-independent topology fingerprint: helix count, per-strand total
    base count grouped by type, and the loop/skip delta multiset."""
    by_type: dict[str, list[int]] = {}
    for s in d.strands:
        t = str(s.strand_type).split(".")[-1]
        total = sum(abs(dm.end_bp - dm.start_bp) + 1 for dm in s.domains)
        by_type.setdefault(t, []).append(total)
    return (
        len(d.helices),
        tuple(sorted((t, tuple(sorted(v))) for t, v in by_type.items())),
        tuple(sorted(ls.delta for h in d.helices for ls in h.loop_skips)),
    )


def _n_circular(warnings: list[str]) -> int:
    return sum(int(w.split()[0]) for w in warnings if "circular" in w)


def _assert_conserved(src: Design, re: Design, warnings: list[str]) -> None:
    """import(export(src)) must conserve topology. Circular strands are dropped
    on import, so with any circular drop we require the re-imported per-type base
    multiset to be a SUBSET of the source (rather than exact equality)."""
    s1, s2 = _topology_sig(src), _topology_sig(re)
    if s1 == s2:
        return
    n_circ = _n_circular(warnings)
    assert n_circ > 0, f"topology not conserved (no circular drop):\n {s1}\n {s2}"
    assert s1[0] == s2[0], "helix count changed"
    assert s1[2] == s2[2], "loop/skip multiset changed"
    src_by = {t: Counter(v) for t, v in s1[1]}
    for t, v in s2[1]:
        assert not (Counter(v) - src_by.get(t, Counter())), (
            f"re-imported {t} strands are not a subset of source (circ={n_circ})"
        )


def _assert_wellformed(data: dict) -> int:
    """A caDNAno v2 dict must have equal-length, period-multiple arrays and no
    dangling / out-of-range linked-list pointers. Returns array_len."""
    vs = data["vstrands"]
    assert vs, "no vstrands"
    array_len = len(vs[0]["scaf"])
    nums = {v["num"] for v in vs}
    for v in vs:
        for key in ("scaf", "stap", "loop", "skip"):
            assert len(v[key]) == array_len, f"ragged {key} on num {v['num']}"
        for arr in (v["scaf"], v["stap"]):
            for ph, pp, nh, np_ in arr:
                for hnum, bp in ((ph, pp), (nh, np_)):
                    if hnum == -1:
                        continue
                    assert hnum in nums, f"dangling helix pointer {hnum}"
                    assert 0 <= bp < array_len, f"bp {bp} out of range [0,{array_len})"
    return array_len


def _period_for(d: Design) -> int:
    return _SQ_PERIOD if d.lattice_type == LatticeType.SQUARE else _HC_PERIOD


# ═════════════════════════════════════════════════════════════════════════════
# TIER 1 — well-formedness: export never crashes and emits a valid caDNAno dict
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("path", NADOC_PATHS, ids=lambda p: p.stem)
def test_export_wellformed(path: pathlib.Path):
    d = _load_nadoc(path)
    data = export_cadnano(d)             # must not raise
    array_len = _assert_wellformed(data)
    assert array_len % _period_for(d) == 0, (
        f"array_len {array_len} not a multiple of lattice period"
    )
    assert len(data["vstrands"]) == len(d.helices)


# ═════════════════════════════════════════════════════════════════════════════
# TIER 2 — round-trip conservation: import(export(d)) conserves topology
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("path", NADOC_PATHS, ids=lambda p: p.stem)
def test_roundtrip_conserves_nadoc(path: pathlib.Path):
    d = _load_nadoc(path)
    d2, warnings = import_cadnano(export_cadnano(d))
    _assert_conserved(d, d2, warnings)


@pytest.mark.parametrize("path", JSON_PATHS, ids=lambda p: p.stem)
def test_roundtrip_conserves_cadnano_native(path: pathlib.Path):
    # Import a real caDNAno file, then export→import and confirm topology holds.
    d0, _ = import_cadnano(json.loads(path.read_text()))
    d1, warnings = import_cadnano(export_cadnano(d0))
    _assert_conserved(d0, d1, warnings)


# ═════════════════════════════════════════════════════════════════════════════
# TIER 3 — regression: the three designs that previously crashed export
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("stem", REGRESSION_STEMS)
def test_regression_extended_designs_export(stem: str):
    path = EXAMPLES / f"{stem}.nadoc"
    if not path.exists():
        pytest.skip(f"{path} not present")
    d = _load_nadoc(path)
    data = export_cadnano(d)             # previously IndexError
    _assert_wellformed(data)
    d2, warnings = import_cadnano(data)
    _assert_conserved(d, d2, warnings)


def test_negative_bp_offset_no_corruption():
    """U6hb has scaffold bp down to -9; before the fix Python negative indexing
    silently wrote those into the array tail. Assert every written pointer is
    in-range and the total scaffold base count survives the offset."""
    path = EXAMPLES / "U6hb.nadoc"
    if not path.exists():
        pytest.skip("U6hb.nadoc not present")
    d = _load_nadoc(path)
    data = export_cadnano(d)
    array_len = _assert_wellformed(data)  # would fail on tail-wrap corruption
    # Non-trivial widening happened (offset + period rounding).
    assert array_len >= 438
    d2, warnings = import_cadnano(data)
    _assert_conserved(d, d2, warnings)


def test_negative_bp_offset_preserves_crossover_register():
    """The export bp shift must be a lattice-period multiple.

    A minimal non-negative offset avoids array underflow, but changes ``bp %
    period`` and moves every crossover off caDNAno's registered positions.
    """
    d = make_bundle_design([(0, 0)], length_bp=42)
    d.strands[0].domains[0].start_bp = -1
    d.strands[0].domains[0].end_bp = 1
    data = export_cadnano(d)
    active = [
        bp
        for v in data["vstrands"]
        for bp, entry in enumerate(v["scaf"])
        if entry != [-1, -1, -1, -1]
    ]
    assert active == [20, 21, 22]


def test_export_preserves_6hb_grid_parity():
    """The native 6HB tube must not have its honeycomb parity flipped on export."""
    path = EXAMPLES / "U6hb.nadoc"
    if not path.exists():
        pytest.skip("U6hb.nadoc not present")
    d = _load_nadoc(path)
    helix_scaffold_dir = {h.id: None for h in d.helices}
    for strand in d.strands:
        if not strand.is_scaffold:
            continue
        for domain in strand.domains:
            helix_scaffold_dir[domain.helix_id] = domain.direction
    rows, cols, _ = _assign_grid_coords(d.helices, helix_scaffold_dir, d.lattice_type)

    for h in d.helices:
        assert h.grid_pos is not None
        original_parity = (h.grid_pos[0] + h.grid_pos[1]) % 2
        exported_parity = (rows[h.id] + cols[h.id]) % 2
        assert exported_parity == original_parity


# ═════════════════════════════════════════════════════════════════════════════
# Color preservation on a colored native fixture (secondary invariant)
# ═════════════════════════════════════════════════════════════════════════════

def test_colors_preserved_on_colored_fixture():
    path = CN_JSON_DIR / "Honeycomb_6hb_test1.json"
    if not path.exists():
        pytest.skip("fixture not present")
    d0, _ = import_cadnano(json.loads(path.read_text()))
    colors0 = sorted(s.color for s in d0.strands if s.color)
    if not colors0:
        pytest.skip("fixture has no staple colors")
    d1, _ = import_cadnano(export_cadnano(d0))
    colors1 = sorted(s.color for s in d1.strands if s.color)
    assert colors0 == colors1
