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
    """Full geometry yields a dict per bp with the four position arrays."""
    d = _single_helix_design(direction=Direction.FORWARD, length_bp=10)
    nucs = _geometry_for_design(d)
    # The helix slot carries both strands of the duplex (FORWARD + REVERSE),
    # so a 10-bp helix emits 20 positions; the occupied FORWARD side is 10.
    on_helix = [n for n in nucs if n["helix_id"] == "h0"]
    assert len(on_helix) == 20
    fwd = [n for n in on_helix if n["direction"] == Direction.FORWARD.value]
    assert len(fwd) == 10
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
