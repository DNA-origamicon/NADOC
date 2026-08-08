"""Direct input→output unit tests for backend/core/overhang_ops.py.

These pin the overhang end-polarity & linker-compatibility rules service-pushed
out of crud.py in Refactor #38. No TestClient — pure functions only.
"""

import pytest

from backend.core.models import (
    Design,
    Direction,
    Domain,
    OverhangConnection,
    OverhangSpec,
    Strand,
    SubDomain,
)
from backend.core.overhang_ops import (
    SubDomainTilingError,
    _apply_boundary_hairpin_warnings,
    _check_linker_compatibility,
    _comp_first_polarity,
    _compute_sub_domain_annotations,
    _overhang_end,
    _ovhg_backing_length,
    _ovhg_domain_lengths,
    _replace_ovhg,
    _resolve_sub_domain_sequence,
    _used_overhang_ends,
    validate_sub_domain_tiling,
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


# ── Sub-domain tiling / sequence / annotations (Refactor #39) ────────────────


def _design_with_overhang(
    ovhg_id="oh_x_5p",
    backing_len=8,
    sub_domains=None,
    sequence=None,
    direction=Direction.FORWARD,
):
    """Design with one overhang backed by a single domain of length backing_len."""
    spec = OverhangSpec(
        id=ovhg_id,
        helix_id="h_oh",
        strand_id="s1",
        sequence=sequence,
        sub_domains=sub_domains if sub_domains is not None else [],
    )
    if direction == Direction.FORWARD:
        dom = Domain(
            helix_id="h0",
            start_bp=0,
            end_bp=backing_len - 1,
            direction=Direction.FORWARD,
            overhang_id=ovhg_id,
        )
    else:
        dom = Domain(
            helix_id="h0",
            start_bp=backing_len - 1,
            end_bp=0,
            direction=Direction.REVERSE,
            overhang_id=ovhg_id,
        )
    d = Design(name="t")
    d.strands = [Strand(id="s1", domains=[dom])]
    d.overhangs = [spec]
    return d


# _ovhg_backing_length / _ovhg_domain_lengths


def test_ovhg_backing_length_forward():
    d = _design_with_overhang(backing_len=8)
    assert _ovhg_backing_length(d, "oh_x_5p") == 8


def test_ovhg_backing_length_reverse_uses_abs():
    d = _design_with_overhang(backing_len=8, direction=Direction.REVERSE)
    assert _ovhg_backing_length(d, "oh_x_5p") == 8


def test_ovhg_backing_length_none_when_orphaned():
    d = _design_with_overhang()
    assert _ovhg_backing_length(d, "no_such_overhang") is None


def test_ovhg_domain_lengths_maps_every_overhang_domain():
    d = _design_with_overhang(ovhg_id="oh_x_5p", backing_len=6)
    assert _ovhg_domain_lengths(d) == {"oh_x_5p": 6}


def test_ovhg_domain_lengths_ignores_non_overhang_domains():
    d = Design(name="t")
    d.strands = [
        Strand(
            id="s1",
            domains=[
                Domain(
                    helix_id="h0", start_bp=0, end_bp=10, direction=Direction.FORWARD
                ),
            ],
        )
    ]
    assert _ovhg_domain_lengths(d) == {}


# validate_sub_domain_tiling


def test_validate_tiling_ok():
    subs = [
        SubDomain(name="a", start_bp_offset=0, length_bp=4),
        SubDomain(name="b", start_bp_offset=4, length_bp=4),
    ]
    d = _design_with_overhang(backing_len=8, sub_domains=subs)
    validate_sub_domain_tiling(d, "oh_x_5p")  # no raise


def test_validate_tiling_overhang_not_found():
    d = _design_with_overhang(
        backing_len=8, sub_domains=[SubDomain(name="a", length_bp=8)]
    )
    with pytest.raises(SubDomainTilingError) as exc:
        validate_sub_domain_tiling(d, "missing")
    assert exc.value.status == 404


def test_validate_tiling_no_sub_domains():
    d = _design_with_overhang(
        backing_len=8, sub_domains=[SubDomain(name="a", length_bp=8)]
    )
    d.overhangs[0].sub_domains = []
    with pytest.raises(SubDomainTilingError) as exc:
        validate_sub_domain_tiling(d, "oh_x_5p")
    assert exc.value.status == 422
    assert "no sub-domains" in exc.value.detail


def test_validate_tiling_length_below_one():
    subs = [SubDomain(name="a", start_bp_offset=0, length_bp=0)]
    d = _design_with_overhang(backing_len=8, sub_domains=subs)
    with pytest.raises(SubDomainTilingError) as exc:
        validate_sub_domain_tiling(d, "oh_x_5p")
    assert "length_bp < 1" in exc.value.detail


def test_validate_tiling_not_gap_less():
    subs = [
        SubDomain(name="a", start_bp_offset=0, length_bp=4),
        SubDomain(name="b", start_bp_offset=5, length_bp=3),
    ]
    d = _design_with_overhang(backing_len=8, sub_domains=subs)
    with pytest.raises(SubDomainTilingError) as exc:
        validate_sub_domain_tiling(d, "oh_x_5p")
    assert "not gap-less" in exc.value.detail


def test_validate_tiling_override_length_mismatch():
    subs = [
        SubDomain(name="a", start_bp_offset=0, length_bp=4, sequence_override="ACG")
    ]
    d = _design_with_overhang(backing_len=4, sub_domains=subs)
    with pytest.raises(SubDomainTilingError) as exc:
        validate_sub_domain_tiling(d, "oh_x_5p")
    assert "sequence_override length" in exc.value.detail


def test_validate_tiling_override_non_acgtn():
    subs = [
        SubDomain(name="a", start_bp_offset=0, length_bp=3, sequence_override="ACX")
    ]
    d = _design_with_overhang(backing_len=3, sub_domains=subs)
    with pytest.raises(SubDomainTilingError) as exc:
        validate_sub_domain_tiling(d, "oh_x_5p")
    assert "non-ACGTN" in exc.value.detail


def test_validate_tiling_sum_mismatch_backing():
    subs = [SubDomain(name="a", start_bp_offset=0, length_bp=4)]
    d = _design_with_overhang(backing_len=8, sub_domains=subs)
    with pytest.raises(SubDomainTilingError) as exc:
        validate_sub_domain_tiling(d, "oh_x_5p")
    assert "tiling sum" in exc.value.detail


# _resolve_sub_domain_sequence


def test_resolve_sequence_uses_override_uppercased():
    ovhg = OverhangSpec(id="o", helix_id="h", strand_id="s", sequence="acgtacgt")
    sd = SubDomain(name="a", start_bp_offset=0, length_bp=3, sequence_override="acg")
    assert _resolve_sub_domain_sequence(ovhg, sd) == "ACG"


def test_resolve_sequence_slices_parent():
    ovhg = OverhangSpec(id="o", helix_id="h", strand_id="s", sequence="ACGTACGT")
    sd = SubDomain(name="a", start_bp_offset=2, length_bp=3)
    assert _resolve_sub_domain_sequence(ovhg, sd) == "GTA"


def test_resolve_sequence_none_without_parent():
    ovhg = OverhangSpec(id="o", helix_id="h", strand_id="s", sequence=None)
    sd = SubDomain(name="a", start_bp_offset=0, length_bp=3)
    assert _resolve_sub_domain_sequence(ovhg, sd) is None


def test_resolve_sequence_none_when_slice_too_short():
    ovhg = OverhangSpec(id="o", helix_id="h", strand_id="s", sequence="ACGTACGT")
    sd = SubDomain(name="a", start_bp_offset=6, length_bp=4)
    assert _resolve_sub_domain_sequence(ovhg, sd) is None


# _compute_sub_domain_annotations


def test_compute_annotations_empty_seq():
    ann = _compute_sub_domain_annotations(None, na_mM=50.0, conc_nM=100.0)
    assert ann == {
        "tm_celsius": None,
        "gc_percent": None,
        "hairpin_warning": False,
        "dimer_warning": False,
    }


def test_compute_annotations_real_seq():
    ann = _compute_sub_domain_annotations("ACGTACGTACGT", na_mM=50.0, conc_nM=100.0)
    assert ann["tm_celsius"] is not None
    assert ann["gc_percent"] is not None
    assert isinstance(ann["hairpin_warning"], bool)
    assert isinstance(ann["dimer_warning"], bool)


# ── _replace_ovhg (Refactor #40) ─────────────────────────────────────────────


def test_replace_ovhg_swaps_matching_id():
    d = _design_with_overhang(ovhg_id="oh_x_5p", backing_len=8, sequence="ACGTACGT")
    new_spec = d.overhangs[0].model_copy(update={"sequence": "TTTTTTTT"})
    out = _replace_ovhg(d, new_spec)
    assert out is not d  # new model
    assert out.overhangs[0].sequence == "TTTTTTTT"
    # Original design untouched (immutability of the transform).
    assert d.overhangs[0].sequence == "ACGTACGT"


def test_replace_ovhg_leaves_other_overhangs():
    d = _design_with_overhang(ovhg_id="oh_a_5p", backing_len=8, sequence="ACGTACGT")
    other = OverhangSpec(id="oh_b_3p", helix_id="h_oh", strand_id="s1", sequence="GGGG")
    d.overhangs = [d.overhangs[0], other]
    new_spec = d.overhangs[0].model_copy(update={"sequence": "TTTTTTTT"})
    out = _replace_ovhg(d, new_spec)
    by_id = {o.id: o for o in out.overhangs}
    assert by_id["oh_a_5p"].sequence == "TTTTTTTT"
    assert by_id["oh_b_3p"].sequence == "GGGG"  # untouched


# ── _apply_boundary_hairpin_warnings (Refactor #40) ──────────────────────────


def test_hairpin_warnings_noop_when_overhang_missing():
    d = _design_with_overhang(
        backing_len=8, sub_domains=[SubDomain(name="a", length_bp=8)]
    )
    assert _apply_boundary_hairpin_warnings(d, "no_such_overhang") is d


def test_hairpin_warnings_noop_when_no_sub_domains():
    d = _design_with_overhang(backing_len=8)  # sub_domains == []
    assert _apply_boundary_hairpin_warnings(d, "oh_x_5p") is d


def test_hairpin_warnings_no_change_returns_same_design():
    # Benign sequence, flag already False → nothing to toggle → identity.
    subs = [
        SubDomain(
            name="a",
            start_bp_offset=0,
            length_bp=8,
            sequence_override="AAAAAAAA",
            hairpin_warning=False,
        )
    ]
    d = _design_with_overhang(backing_len=8, sub_domains=subs)
    assert _apply_boundary_hairpin_warnings(d, "oh_x_5p") is d


def test_hairpin_warnings_clears_stale_true():
    # Benign sequence + no boundary hairpin, but flag stuck True → cleared.
    subs = [
        SubDomain(
            name="a",
            start_bp_offset=0,
            length_bp=8,
            sequence_override="AAAAAAAA",
            hairpin_warning=True,
        )
    ]
    d = _design_with_overhang(backing_len=8, sub_domains=subs)
    out = _apply_boundary_hairpin_warnings(d, "oh_x_5p")
    assert out is not d
    assert out.overhangs[0].sub_domains[0].hairpin_warning is False


def test_hairpin_warnings_sets_from_inner_sequence():
    # Strongly self-complementary inner sequence → has_hairpin fires → flag set.
    subs = [
        SubDomain(
            name="a",
            start_bp_offset=0,
            length_bp=12,
            sequence_override="GCGCGCGCGCGC",
            hairpin_warning=False,
        )
    ]
    d = _design_with_overhang(backing_len=12, sub_domains=subs)
    out = _apply_boundary_hairpin_warnings(d, "oh_x_5p")
    assert out is not d
    assert out.overhangs[0].sub_domains[0].hairpin_warning is True
