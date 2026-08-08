"""PSF !NBOND parsing must handle PACKED fixed-width columns at >=10M atoms.

The CHARMM PSF bond section is (8I8) (standard) / (8I10) (EXT) with NO separators. A
whitespace split() works only while every index is narrower than its column; at >= 10M
atoms an 8-digit index fills an I8 field and adjacent bonds merge into one token -> the old
split() parser dropped half the numbers and IndexErrored. This blocked the ~11.8M-atom
VoltronCore full-box HMR PSF (the 2.85M shell, 7-digit indices, was fine).
"""

from __future__ import annotations

from backend.core.md_protocols import _iter_packed_psf_pairs


def test_packed_i8_bonds_with_8digit_indices_do_not_merge():
    # Two bonds per line, indices 8 digits wide -> in I8 they PACK with no space.
    # (10000001-10000002) and (10000003-10000004): the line is 32 chars, no separators.
    a1, a2, a3, a4 = 10000001, 10000002, 10000003, 10000004
    line = f"{a1:8d}{a2:8d}{a3:8d}{a4:8d}"
    assert " " not in line  # genuinely packed — split() would see 1 token, not 4
    pairs = list(_iter_packed_psf_pairs([line], 0, 2, width=8))
    assert pairs == [(a1, a2), (a3, a4)]


def test_packed_i8_bonds_small_indices_still_parse():
    # Small (<8-digit) indices are left-padded with spaces; fixed-width slicing must still
    # read them exactly (the shell/2.85M path must be unchanged).
    line = f"{1:8d}{2:8d}{3:8d}{4:8d}"
    assert list(_iter_packed_psf_pairs([line], 0, 2, width=8)) == [(1, 2), (3, 4)]


def test_pairs_span_multiple_rows_and_stop_at_count():
    rows = [f"{1:8d}{2:8d}{3:8d}{4:8d}", f"{5:8d}{6:8d}"]
    # ask for only 2 of the 3 encoded pairs -> stops mid-stream at the count
    assert list(_iter_packed_psf_pairs(rows, 0, 2, width=8)) == [(1, 2), (3, 4)]
    assert list(_iter_packed_psf_pairs(rows, 0, 3, width=8)) == [(1, 2), (3, 4), (5, 6)]


def test_ext_width_10_columns():
    a1, a2 = 1000000001, 1000000002  # 10-digit, fill an I10 column (EXT)
    line = f"{a1:10d}{a2:10d}"
    assert " " not in line
    assert list(_iter_packed_psf_pairs([line], 0, 1, width=10)) == [(a1, a2)]
