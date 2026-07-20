"""Regression guard for the poly-T-scaffold incident (6hbx100_90deg): an unassigned
scaffold sequence is silently built as thymine, wasting a full MD run on a physically
meaningless reference. See backend/core/md_sequence_guard.py.
"""
from pathlib import Path

import pytest

from backend.core.models import Design, StrandType
from backend.core.md_sequence_guard import (
    scaffold_sequence_problems, require_sequenced_scaffold, _strand_build_nt_count)

EXAMPLES = Path(__file__).resolve().parent.parent / "Examples"


def _load(stem: str) -> Design:
    return Design.model_validate_json((EXAMPLES / f"{stem}.nadoc").read_text())


def test_unsequenced_scaffold_is_flagged():
    d = _load("6hb_test")  # scaffolds present, no sequence assigned (acgt=0)
    problems = scaffold_sequence_problems(d)
    assert problems, "an unsequenced scaffold MUST be flagged"
    assert all("scaffold" in p for p in problems)
    with pytest.raises(ValueError, match="scaffold"):
        require_sequenced_scaffold(d)


def test_fully_sequenced_scaffold_passes():
    d = _load("U6hb")  # 2588/2588 scaffold bases assigned
    assert scaffold_sequence_problems(d) == []
    require_sequenced_scaffold(d)  # must not raise


def test_assigning_the_sequence_clears_the_flag():
    d = _load("6hb_test")
    assert scaffold_sequence_problems(d)  # flagged beforehand
    for s in d.strands:
        if s.strand_type == StrandType.SCAFFOLD:
            s.sequence = "A" * _strand_build_nt_count(d, s)  # assignment (any ACGT) clears it
    assert scaffold_sequence_problems(d) == []


def test_partial_scaffold_is_flagged():
    # half-assigned scaffold: the remaining nt would still build as poly-T -> must flag.
    d = _load("6hb_test")
    for s in d.strands:
        if s.strand_type == StrandType.SCAFFOLD:
            n = _strand_build_nt_count(d, s)
            s.sequence = "ACGT" * (n // 8)  # ~half coverage
    probs = scaffold_sequence_problems(d)
    assert probs and any("under-sequenced" in p for p in probs)
