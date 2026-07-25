"""Direct unit tests for the per-nucleotide display-geometry kernel.

These pin the pure compute functions service-pushed out of crud.py into
``backend/core/design_geometry.py`` (carve-up #46). They import the functions
DIRECTLY from the core module (not via crud's re-export) so they assert the
core module's own input→output behavior — the earned pin for the moved code.
"""

from backend.core.design_geometry import (
    _strand_nucleotide_info,
    _straight_helix_axes,
    _geometry_for_design,
    _geometry_for_design_straight,
    _compact_geometry_from_nucleotides,
    _compact_geometry_for_design,
    _positions_by_helix,
    _positions_for_design,
)
from backend.core.models import (
    Design,
    Helix,
    Strand,
    Domain,
    StrandExtension,
    DesignMetadata,
    Direction,
    StrandType,
    LatticeType,
)
from backend.core.constants import BDNA_RISE_PER_BP


def _single_helix_design(*, direction=Direction.FORWARD, length_bp=10,
                         strand_type=StrandType.STAPLE, is_reference=False,
                         extensions=None):
    """One helix + one full-span strand. start_bp/end_bp follow the 5'→3'
    convention for the given direction."""
    h = Helix(
        id="h0",
        length_bp=length_bp,
        bp_start=0,
        axis_start={"x": 0, "y": 0, "z": 0},
        axis_end={"x": 0, "y": 0, "z": length_bp * BDNA_RISE_PER_BP},
        phase_offset=0.0,
    )
    if direction == Direction.FORWARD:
        dom = Domain(helix_id="h0", direction=direction, start_bp=0, end_bp=length_bp - 1)
    else:
        dom = Domain(helix_id="h0", direction=direction, start_bp=length_bp - 1, end_bp=0)
    strand = Strand(id="s0", domains=[dom], strand_type=strand_type,
                    is_reference=is_reference)
    return Design(
        metadata=DesignMetadata(name="t"),
        lattice_type=LatticeType.HONEYCOMB,
        helices=[h],
        strands=[strand],
        extensions=list(extensions or []),
    )


def test_strand_nucleotide_info_forward_termini():
    """FORWARD strand: 5' at start_bp, 3' at end_bp."""
    d = _single_helix_design(direction=Direction.FORWARD, length_bp=12)
    info = _strand_nucleotide_info(d)
    assert info[("h0", 0, Direction.FORWARD)]["is_five_prime"]
    assert info[("h0", 11, Direction.FORWARD)]["is_three_prime"]
    assert not info[("h0", 11, Direction.FORWARD)]["is_five_prime"]
    # Every bp on the span is keyed, carrying the strand id + type.
    assert len(info) == 12
    assert info[("h0", 5, Direction.FORWARD)]["strand_id"] == "s0"
    assert info[("h0", 5, Direction.FORWARD)]["strand_type"] == StrandType.STAPLE.value


def test_strand_nucleotide_info_reverse_termini():
    """REVERSE strand: 5' at the high bp (start_bp), 3' at bp 0 (end_bp)."""
    d = _single_helix_design(direction=Direction.REVERSE, length_bp=12)
    info = _strand_nucleotide_info(d)
    assert info[("h0", 11, Direction.REVERSE)]["is_five_prime"]
    assert info[("h0", 0, Direction.REVERSE)]["is_three_prime"]
    assert not info[("h0", 0, Direction.REVERSE)]["is_five_prime"]


def test_strand_nucleotide_info_is_reference_flows_through():
    """The display-only is_reference flag is copied onto every bead."""
    d = _single_helix_design(is_reference=True)
    info = _strand_nucleotide_info(d)
    assert all(v["is_reference"] for v in info.values())


def test_strand_nucleotide_info_helix_filter():
    """A helix_ids filter restricts the emitted beads to those helices."""
    d = _single_helix_design()
    assert _strand_nucleotide_info(d, frozenset({"h0"}))  # matches → non-empty
    assert _strand_nucleotide_info(d, frozenset({"other"})) == {}  # no match → empty


def test_straight_helix_axes_uses_stored_endpoints():
    """Axes come straight from the stored axis_start/axis_end (no re-derivation)."""
    d = _single_helix_design(length_bp=10)
    axes = _straight_helix_axes(d)
    assert len(axes) == 1
    ax = axes[0]
    assert ax["helix_id"] == "h0"
    assert ax["start"] == [0.0, 0.0, 0.0]
    assert ax["end"][2] == 10 * BDNA_RISE_PER_BP
    assert ax["samples"] is None


def test_geometry_for_design_emits_one_bead_per_bp():
    """Full geometry yields a dict per REAL nucleotide with the four position arrays."""
    d = _single_helix_design(direction=Direction.FORWARD, length_bp=10)
    nucs = _geometry_for_design(d)
    # Only the occupied strand is emitted — the empty REVERSE side no longer produces a
    # ghost base (ss-overhang regions render single-stranded), so a 10-bp single-FORWARD
    # strand emits exactly 10 positions, all FORWARD.
    on_helix = [n for n in nucs if n["helix_id"] == "h0"]
    assert len(on_helix) == 10
    fwd = [n for n in on_helix if n["direction"] == Direction.FORWARD.value]
    assert len(fwd) == 10
    assert not [n for n in on_helix if n.get("strand_id") is None]   # no phantom bases
    sample = fwd[0]
    for key in ("backbone_position", "base_position", "base_normal", "axis_tangent"):
        assert len(sample[key]) == 3  # xyz vector
    assert sample["strand_id"] == "s0"


def test_geometry_for_design_straight_strips_deformations_and_clusters():
    """The t=0 base geometry ignores deformations + cluster transforms.

    With an empty deformation/cluster list the straight geometry is identical to
    the full geometry (nothing to strip), proving the model_copy(update=...) does
    not perturb base positions."""
    d = _single_helix_design(length_bp=10)
    full = _geometry_for_design(d)
    straight = _geometry_for_design_straight(d)
    full_by_key = {(n["helix_id"], n["bp_index"], n["direction"]): n["backbone_position"]
                   for n in full}
    for n in straight:
        k = (n["helix_id"], n["bp_index"], n["direction"])
        assert full_by_key[k] == n["backbone_position"]


def test_geometry_for_design_five_prime_extension_tip_is_cube():
    """Full mode appends extension beads; the outermost 5' bead is is_five_prime."""
    ext = StrandExtension(strand_id="s0", end="five_prime", sequence="TT")
    d = _single_helix_design(direction=Direction.FORWARD, length_bp=10, extensions=[ext])
    nucs = _geometry_for_design(d)
    ext_beads = [n for n in nucs
                 if n.get("extension_id") == ext.id and not n.get("is_modification")]
    assert ext_beads
    ext_beads.sort(key=lambda n: n["bp_index"])
    assert ext_beads[-1]["is_five_prime"]
    # The real-helix 5' terminal loses its cube when a 5' extension exists.
    real_terminal = next(n for n in nucs
                         if n["helix_id"] == "h0" and n["bp_index"] == 0
                         and n["direction"] == Direction.FORWARD.value)
    assert not real_terminal["is_five_prime"]


# ── Compaction / positions kernel (service push #48) ─────────────────────────

def test_compact_geometry_from_nucleotides_buckets_by_helix_and_direction():
    """Flat nuc dicts → per-helix-per-direction parallel arrays with matching
    lengths, and the bp values are preserved in order."""
    d = _single_helix_design(direction=Direction.FORWARD, length_bp=10)
    nucs = _geometry_for_design(d)
    compact = _compact_geometry_from_nucleotides(nucs)
    assert "h0" in compact
    fwd = compact["h0"][Direction.FORWARD.value]
    # Parallel arrays for the core position fields are all the same length.
    n = len(fwd["bp"])
    assert n == 10
    for key in ("bb", "bs", "bn", "at", "sid", "stype", "is5", "is3"):
        assert len(fwd[key]) == n
    # bp values round-trip from the source nuc dicts (same FORWARD bps).
    src_bps = sorted(x["bp_index"] for x in nucs
                     if x["helix_id"] == "h0" and x["direction"] == Direction.FORWARD.value)
    assert sorted(fwd["bp"]) == src_bps


def test_compact_geometry_from_nucleotides_drops_unused_sparse_fields():
    """A plain (no-modification/no-extension) design ships none of the sparse
    fields — they're popped, not shipped as empty arrays."""
    d = _single_helix_design(length_bp=8)
    compact = _compact_geometry_from_nucleotides(_geometry_for_design(d))
    for by_dir in compact.values():
        for bucket in by_dir.values():
            for sparse in ("extid", "ismod", "mod", "base"):
                assert sparse not in bucket


def test_compact_geometry_for_design_equals_compose():
    """_compact_geometry_for_design is exactly the compaction of the full
    per-nuc geometry (it's a thin composition wrapper)."""
    d = _single_helix_design(length_bp=10)
    assert _compact_geometry_for_design(d) == \
        _compact_geometry_from_nucleotides(_geometry_for_design(d))


def test_positions_by_helix_emits_only_position_fields():
    """The positions_only payload carries just bp + the four position arrays,
    no strand metadata."""
    d = _single_helix_design(length_bp=10)
    pos = _positions_by_helix(_geometry_for_design(d))
    fwd = pos["h0"][Direction.FORWARD.value]
    assert set(fwd.keys()) == {"bp", "bb", "bs", "bn", "at"}
    n = len(fwd["bp"])
    assert n == 10
    for key in ("bb", "bs", "bn", "at"):
        assert len(fwd[key]) == n


def test_positions_for_design_matches_dict_path_backbone():
    """The numpy-direct positions path produces the same backbone positions as
    the dict-based _positions_by_helix(_geometry_for_design(...)) fallback."""
    d = _single_helix_design(direction=Direction.FORWARD, length_bp=12)
    direct, axes = _positions_for_design(d)
    fallback = _positions_by_helix(_geometry_for_design(d))

    def _bb_by_key(payload):
        out = {}
        for hid, by_dir in payload.items():
            for dir_name, bucket in by_dir.items():
                for i, bp in enumerate(bucket["bp"]):
                    out[(hid, dir_name, bp)] = bucket["bb"][i]
        return out

    assert _bb_by_key(direct) == _bb_by_key(fallback)
    # Axes come back alongside positions, one per real helix.
    assert [ax["helix_id"] for ax in axes] == ["h0"]


def test_positions_for_design_includes_extension_tail_beads():
    """The compact positions path must emit the __ext_ tail beads too, or the
    auto-embedded straight_positions_by_helix (which feeds the deform toggle's
    straight anchor) has no entry for them — the extension beads then stay
    pinned at their deformed position when the toggle goes OFF. The compact
    path must match the full per-nuc path bead-for-bead, extensions included."""
    ext3 = StrandExtension(strand_id="s0", end="three_prime", sequence="TT")
    d = _single_helix_design(direction=Direction.FORWARD, length_bp=10,
                             extensions=[ext3])
    direct, _ = _positions_for_design(d)
    fallback = _positions_by_helix(_geometry_for_design(d))

    ext_hid = f"__ext_{ext3.id}"
    # The synthetic extension helix is present in the compact payload.
    assert ext_hid in direct, "extension tail beads dropped from compact path"

    def _bb_by_key(payload):
        out = {}
        for hid, by_dir in payload.items():
            for dir_name, bucket in by_dir.items():
                for i, bp in enumerate(bucket["bp"]):
                    out[(hid, dir_name, bp)] = bucket["bb"][i]
        return out

    # Compact path == full path everywhere, including the __ext_ beads. If the
    # tail beads were missing (the bug), the two key sets would differ.
    assert _bb_by_key(direct) == _bb_by_key(fallback)


def test_positions_for_design_extension_survives_deformation_strip():
    """Straight anchor path: with a deformation present, the straight payload is
    computed on a deformations-stripped copy. Extension tail beads must still be
    emitted (and at the STRAIGHT anchor position), so the deform lerp has a t=0
    target for them."""
    from backend.core.models import DeformationOp, TwistParams
    ext = StrandExtension(strand_id="s0", end="three_prime", sequence="TTT")
    d = _single_helix_design(direction=Direction.FORWARD, length_bp=12,
                             extensions=[ext])
    d.deformations = [
        DeformationOp(type="twist", plane_a_bp=2, plane_b_bp=9,
                      params=TwistParams(total_degrees=90.0)),
    ]
    # Mirror crud.py's straight-anchor build: strip deformations, then compact.
    straight = d.model_copy(update={"deformations": [], "cluster_transforms": []})
    direct, _ = _positions_for_design(straight)
    full_straight = _positions_by_helix(_geometry_for_design(straight))

    ext_hid = f"__ext_{ext.id}"
    assert ext_hid in direct
    # Straight compact == straight full for the tail beads.
    d_ext = direct[ext_hid]
    f_ext = full_straight[ext_hid]
    assert d_ext.keys() == f_ext.keys()
    for dir_name in d_ext:
        assert d_ext[dir_name]["bb"] == f_ext[dir_name]["bb"]
