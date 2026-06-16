"""Direct input→output unit tests for backend/core/overhang_ops.py.

These pin the overhang end-polarity & linker-compatibility rules service-pushed
out of crud.py in Refactor #38. No TestClient — pure functions only.
"""

from backend.core.models import Design, OverhangConnection
from backend.core.overhang_ops import (
    _check_linker_compatibility,
    _comp_first_polarity,
    _overhang_end,
    _used_overhang_ends,
)


# ── _overhang_end ──────────────────────────────────────────────────────────


def test_overhang_end_parses_suffix():
    assert _overhang_end("oh_3_5p") == "5p"
    assert _overhang_end("oh_3_3p") == "3p"


def test_overhang_end_none_without_suffix():
    assert _overhang_end("oh_3") is None
    assert _overhang_end("") is None


# ── _comp_first_polarity ───────────────────────────────────────────────────


def test_comp_first_polarity_5p():
    # 5p end is comp-first only when attached at its free end.
    assert _comp_first_polarity("5p", "free_end") is True
    assert _comp_first_polarity("5p", "root") is False


def test_comp_first_polarity_3p():
    # 3p end is comp-first only when attached at its root.
    assert _comp_first_polarity("3p", "root") is True
    assert _comp_first_polarity("3p", "free_end") is False


def test_comp_first_polarity_unknown_end():
    assert _comp_first_polarity(None, "root") is None


# ── _check_linker_compatibility ────────────────────────────────────────────
# Rule: ds linker requires comp_first(A) == comp_first(B); ss requires !=.


def test_ds_same_polarity_ok():
    # Two 5p ends both at free_end → both comp-first → ds duplex valid.
    assert _check_linker_compatibility("5p", "5p", "free_end", "free_end", "ds") is None


def test_ds_mismatched_polarity_rejected():
    # 5p free_end (comp-first) vs 5p root (bridge-first) → ds invalid.
    msg = _check_linker_compatibility("5p", "5p", "free_end", "root", "ds")
    assert msg is not None
    assert "dsDNA linker" in msg
    assert "matching attach" in msg  # same end_type branch


def test_ds_opposite_ends_message():
    # 5p free_end (comp-first) vs 3p free_end (bridge-first) → mismatch, mixed ends.
    msg = _check_linker_compatibility("5p", "3p", "free_end", "free_end", "ds")
    assert msg is not None
    assert "OPPOSITE" in msg


def test_ss_opposite_polarity_ok():
    # ss requires disagreement: 5p free_end (comp-first) vs 5p root (bridge-first).
    assert _check_linker_compatibility("5p", "5p", "free_end", "root", "ss") is None


def test_ss_same_polarity_rejected():
    msg = _check_linker_compatibility("5p", "5p", "free_end", "free_end", "ss")
    assert msg is not None
    assert "ssDNA linker" in msg


def test_unknown_end_lets_caller_proceed():
    # Fixture-friendly: an end with no _5p/_3p suffix yields no error.
    assert _check_linker_compatibility(None, "5p", "root", "free_end", "ds") is None
    assert _check_linker_compatibility("5p", None, "free_end", "root", "ss") is None


def test_unknown_linker_type_returns_none():
    assert _check_linker_compatibility("5p", "5p", "free_end", "root", "weird") is None


# ── _used_overhang_ends ────────────────────────────────────────────────────


def _conn(cid, a_id, a_attach, b_id, b_attach):
    return OverhangConnection(
        id=cid,
        overhang_a_id=a_id,
        overhang_a_attach=a_attach,
        overhang_b_id=b_id,
        overhang_b_attach=b_attach,
        linker_type="ss",
        length_value=4,
        length_unit="bp",
    )


def test_used_overhang_ends_collects_pairs():
    d = Design(name="t")
    d.overhang_connections = [
        _conn("L1", "oh_a_5p", "free_end", "oh_b_3p", "root"),
    ]
    used = _used_overhang_ends(d)
    assert used == {("oh_a_5p", "free_end"), ("oh_b_3p", "root")}


def test_used_overhang_ends_excludes_one_connection():
    d = Design(name="t")
    d.overhang_connections = [
        _conn("L1", "oh_a_5p", "free_end", "oh_b_3p", "root"),
        _conn("L2", "oh_c_5p", "root", "oh_d_3p", "free_end"),
    ]
    used = _used_overhang_ends(d, exclude_conn_id="L1")
    assert used == {("oh_c_5p", "root"), ("oh_d_3p", "free_end")}


def test_used_overhang_ends_empty():
    assert _used_overhang_ends(Design(name="t")) == set()
