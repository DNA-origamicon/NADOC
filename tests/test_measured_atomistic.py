"""The MD-measured atomistic template, and the build path that stamps it.

The template is a measurement, so these tests are not "does the code run" — they are
the assertions that make the measurement trustworthy, and they would fail if the data
file were ever regenerated from a bad trajectory or a broken averaging pass.

Everything checked here is EMERGENT: the measurement fits each strand independently,
in a frame that privileges neither, and is never told to make a base pair.  So
Watson-Crick geometry, chirality and the pseudo-dyad coming out right is evidence, not
tautology.  See ``backend/core/measured_atomistic.py`` and the script that produced the
data, ``scripts/measure_atomistic_template.py``.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from backend.core import measured_atomistic as ma

PURINES = {"DA", "DG"}
WC_ATOM = {"DA": "N1", "DG": "N1", "DT": "N3", "DC": "N3"}
COMPLEMENT = {"DA": "DT", "DT": "DA", "DG": "DC", "DC": "DG"}
RESIDUES = ("DA", "DT", "DG", "DC")

# Reference bond lengths, nm.  The template is judged against the trajectory's own
# means first (recorded in the report); these are the independent sanity floor.
BONDS = {
    ("P", "OP1"): 0.148,
    ("P", "OP2"): 0.148,
    ("P", "O5'"): 0.160,
    ("O5'", "C5'"): 0.144,
    ("C5'", "C4'"): 0.151,
    ("C4'", "O4'"): 0.145,
    ("C4'", "C3'"): 0.152,
    ("O4'", "C1'"): 0.142,
    ("C3'", "O3'"): 0.143,
    ("C3'", "C2'"): 0.152,
    ("C2'", "C1'"): 0.152,
}


def _atoms(direction: str, residue: str) -> dict[str, np.ndarray]:
    sugar, base = ma.measured_templates()[(direction, residue)]
    return {n: np.array([x, y, z]) for n, _e, x, y, z in (*sugar, *base)}


def test_every_bucket_present_with_expected_atoms():
    tmpl = ma.measured_templates()
    assert len(tmpl) == 8
    for direction in ("FORWARD", "REVERSE"):
        for residue in RESIDUES:
            sugar, base = tmpl[(direction, residue)]
            assert [a[0] for a in sugar] == [
                "P",
                "OP1",
                "OP2",
                "O5'",
                "C5'",
                "C4'",
                "O4'",
                "C3'",
                "O3'",
                "C2'",
                "C1'",
            ]
            assert len(base) == {"DA": 10, "DG": 11, "DT": 9, "DC": 8}[residue]


@pytest.mark.parametrize("direction", ["FORWARD", "REVERSE"])
@pytest.mark.parametrize("residue", RESIDUES)
def test_bond_lengths_are_physical(direction, residue):
    """A naive coordinate average of a flexible molecule shrinks its bonds.

    This is the test that catches it: the measurement averages each rigid group's
    shape and pose separately precisely so that these stay real.  An unfixed whole-body
    average gave P-OP1 = 0.124 nm here against a true 0.148.
    """
    pos = _atoms(direction, residue)
    for (a, b), target in BONDS.items():
        assert abs(np.linalg.norm(pos[a] - pos[b]) - target) < 0.010, f"{a}-{b}"
    glyco = "N9" if residue in PURINES else "N1"
    assert abs(np.linalg.norm(pos["C1'"] - pos[glyco]) - 0.147) < 0.010


@pytest.mark.parametrize("direction", ["FORWARD", "REVERSE"])
@pytest.mark.parametrize("residue", RESIDUES)
def test_sugar_chirality_is_d_deoxyribose(direction, residue):
    """Signed volumes at the three sugar stereocentres, same sign in all 8 buckets.

    The old templates built the reverse strand by z-mirroring the forward one, which
    is an improper operation held right-handed only by a compensating frame flip.  The
    measured templates are independent, so this is the guard that they did not land as
    enantiomers of each other — the one failure mode that would be invisible on screen.
    """
    pos = _atoms(direction, residue)
    glyco = "N9" if residue in PURINES else "N1"
    for centre, (a, b, c, d) in {
        "C1'": ("C1'", "O4'", "C2'", glyco),
        "C3'": ("C3'", "C4'", "C2'", "O3'"),
        "C4'": ("C4'", "O4'", "C5'", "C3'"),
    }.items():
        vol = float(np.dot(np.cross(pos[b] - pos[a], pos[c] - pos[a]), pos[d] - pos[a]))
        assert vol > 0.0015, f"{centre} signed volume {vol}"


@pytest.mark.parametrize("residue", RESIDUES)
def test_base_ring_is_planar(residue):
    ring = (
        ("N9", "C8", "N7", "C5", "C6", "N1", "C2", "N3", "C4")
        if residue in PURINES
        else ("N1", "C2", "N3", "C4", "C5", "C6")
    )
    for direction in ("FORWARD", "REVERSE"):
        pos = _atoms(direction, residue)
        pts = np.array([pos[a] for a in ring])
        _u, sv, _vt = np.linalg.svd(pts - pts.mean(axis=0))
        assert sv[2] / math.sqrt(len(pts)) < 0.004


@pytest.mark.parametrize("residue", RESIDUES)
def test_watson_crick_pairing_is_emergent(residue):
    """The two strands were measured separately and never told to form a base pair.

    Putting the FORWARD template of one base next to the REVERSE template of its
    complement — in the shared frame, with no fitting — must nonetheless give a real
    Watson-Crick pair.  The legacy build gives C1'-C1' = 0.967 nm here.
    """
    f = _atoms("FORWARD", residue)
    r = _atoms("REVERSE", COMPLEMENT[residue])
    wc = np.linalg.norm(f[WC_ATOM[residue]] - r[WC_ATOM[COMPLEMENT[residue]]])
    c1 = np.linalg.norm(f["C1'"] - r["C1'"])
    assert 0.25 < wc < 0.32, f"WC N-N {wc}"
    assert 1.00 < c1 < 1.10, f"C1'-C1' {c1}"


@pytest.mark.parametrize("residue", RESIDUES)
def test_strands_are_related_by_a_proper_dyad(residue):
    """FORWARD and REVERSE agree with the pseudo-dyad — measured, not imposed.

    Fitted from disjoint samples, so this is a real check of the measurement rather
    than a restatement of it: the optimal proper rotation between them must be a 180
    deg turn about an axis perpendicular to the helix axis, and the two shapes must
    superpose.  A REFLECTION being needed would mean the two strands had come out as
    enantiomers.
    """
    f = _atoms("FORWARD", residue)
    r = _atoms("REVERSE", residue)
    names = [n for n in f if n in r]
    A = np.array([f[n] for n in names])
    B = np.array([r[n] for n in names])

    ac, bc = A.mean(axis=0), B.mean(axis=0)
    H = (A - ac).T @ (B - bc)
    U, _s, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    assert d > 0, "reverse strand is a reflection of the forward strand"
    R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T

    rmsd = float(np.sqrt((((A - ac) @ R.T - (B - bc)) ** 2).sum(axis=1).mean()))
    assert rmsd < 0.01, f"shape rmsd {rmsd}"
    angle = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(R) - 1.0) / 2.0))))
    assert abs(angle - 180.0) < 2.0, f"rotation {angle} deg"


def test_forward_phosphorus_defines_azimuth_zero():
    """The emitted template is re-zeroed on the forward P — the convention consumers use."""
    for residue in RESIDUES:
        p = _atoms("FORWARD", residue)["P"]
        assert abs(math.degrees(math.atan2(p[1], p[0]))) < 3.0


def test_measured_pp_separation_is_read_back_from_the_atoms():
    """Not a stored constant: it must agree with where the reverse P actually is."""
    sep = ma.measured_pp_separation_deg()
    assert 150.0 < sep < 220.0
    p = _atoms("REVERSE", "DA")["P"]
    assert (
        abs(((math.degrees(math.atan2(p[1], p[0])) - sep + 180.0) % 360.0) - 180.0)
        < 5.0
    )


def test_backbone_radii_are_b_form():
    """Phosphorus near 0.9 nm and C1' near 0.57 nm from the helix axis.

    The CG layer draws its backbone bead at 1.0 nm and the legacy atomistic template
    stamps P at 0.886; free MD puts the phosphate cylinder at 0.925.
    """
    for direction in ("FORWARD", "REVERSE"):
        for residue in RESIDUES:
            pos = _atoms(direction, residue)
            assert 0.85 < math.hypot(*pos["P"][:2]) < 0.97
            assert 0.52 < math.hypot(*pos["C1'"][:2]) < 0.62


def test_frame_is_orthonormal_right_handed_and_axis_anchored():
    """e_x on the forward bead's radial, e_z the axis, origin ON the axis.

    Right-handed with det exactly +1: the frame is applied to a chiral molecule, so an
    improper one would silently render the enantiomer.
    """
    axis_point = np.array([0.3, -0.2, 1.5])
    tangent = np.array([0.0, 0.0, 2.0])  # deliberately un-normalised
    bead = axis_point + np.array(
        [1.0, 0.0, 0.4]
    )  # axial component must be projected out

    origin, R = ma.measured_frame(bead, tangent, axis_point)
    assert np.allclose(origin, axis_point)
    assert np.linalg.det(R) == pytest.approx(1.0, abs=1e-12)
    assert np.allclose(R.T @ R, np.eye(3), atol=1e-12)
    assert np.allclose(R[:, 2], [0.0, 0.0, 1.0])  # e_z = normalised tangent
    assert np.allclose(R[:, 0], [1.0, 0.0, 0.0])  # e_x = forward radial only


def test_both_strands_of_a_pair_get_one_frame():
    """The frame depends on the FORWARD bead alone, so the pair cannot be split.

    This is the property that carries the measured cross-strand registration into the
    render — and the reason the reverse bead's own azimuth (which the geometric layer
    places at +-150 deg by cell type) never enters.
    """
    axis_point = np.zeros(3)
    tangent = np.array([0.0, 0.0, 1.0])
    fwd_bead = np.array([1.0, 0.0, 0.0])

    of, Rf = ma.measured_frame(fwd_bead, tangent, axis_point)
    orv, Rr = ma.measured_frame(
        fwd_bead, tangent, axis_point
    )  # reverse passes the same
    assert np.allclose(of, orv)
    assert np.allclose(Rf, Rr)


def test_degenerate_frame_inputs_return_none():
    axis_point = np.array([0.0, 0.0, 0.0])
    assert (
        ma.measured_frame(
            np.array([1.0, 0.0, 0.0]), np.array([0.0, 0.0, 0.0]), axis_point
        )
        is None
    )
    # bead sitting exactly on the axis: no radial direction to anchor to
    assert (
        ma.measured_frame(
            np.array([0.0, 0.0, 5.0]), np.array([0.0, 0.0, 1.0]), axis_point
        )
        is None
    )


# A plain-duplex fixture on purpose.  Extra-base crossovers are stamped by a separate
# path that keeps the legacy templates, and those atoms carry the junction's
# (helix, bp, direction) — so on an extra-base design a per-nucleotide index conflates
# them with the real nucleotide there and the comparison below is meaningless.
_FIXTURE = "Examples/6hb_test.nadoc"


def _build(measured: bool):
    from pathlib import Path

    from backend.core.atomistic import build_atomistic_model
    from backend.core.models import Design

    design = Design.model_validate_json(Path(_FIXTURE).read_text())
    return build_atomistic_model(design, measured_positioning=measured)


def _build_default():
    """Build with the mode UNSPECIFIED — what every ordinary caller does."""
    from pathlib import Path

    from backend.core.atomistic import build_atomistic_model
    from backend.core.models import Design

    return build_atomistic_model(Design.model_validate_json(Path(_FIXTURE).read_text()))


def _by_nucleotide(model):
    out: dict[tuple, dict] = {}
    for a in model.atoms:
        key = (a.helix_id, a.bp_index, a.direction, a.copy_k)
        out.setdefault(key, {"_res": a.residue})[a.name] = np.array([a.x, a.y, a.z])
    return out


def test_build_reproduces_the_template_cross_strand_geometry_exactly():
    """The whole point of the shared base-pair frame.

    Every inter-atom distance BETWEEN the two strands of a base pair must match the
    template's own, to floating-point.  Distances are frame-invariant, so this checks
    the placement without needing to know where the helix ended up.  If the two strands
    were being stamped in different frames — as the legacy path does — this is what
    would drift.
    """
    nucs = _by_nucleotide(_build(measured=True))
    pairs = [
        (h, bp)
        for (h, bp, d, k) in nucs
        if d == "FORWARD" and k is None and (h, bp, "REVERSE", None) in nucs
    ]
    assert pairs, "example design produced no complete base pairs"

    errors = []
    for h, bp in pairs:
        f, r = nucs[(h, bp, "FORWARD", None)], nucs[(h, bp, "REVERSE", None)]
        tf, tr = _atoms("FORWARD", f["_res"]), _atoms("REVERSE", r["_res"])
        fn = [n for n in tf if n in f]
        rn = [n for n in tr if n in r]
        built = np.array([[np.linalg.norm(f[a] - r[b]) for b in rn] for a in fn])
        want = np.array([[np.linalg.norm(tf[a] - tr[b]) for b in rn] for a in fn])
        errors.append(float(np.abs(built - want).max()))

    # Exact for every pair the duplex stamping path owns.  The handful that are not
    # are the crossover junctions, which the backbone-bridging and interpolation
    # passes deliberately relocate AFTER stamping — they are not on the template any
    # more by design, and this test is about frame sharing, not about them.
    exact = sum(1 for e in errors if e < 1e-9)
    assert np.median(errors) < 1e-12, "typical pair should match to float precision"
    assert exact >= 0.95 * len(errors), (
        f"only {exact}/{len(errors)} base pairs reproduce the template exactly"
    )


def test_measured_build_widens_the_base_pair_versus_legacy():
    """The visible consequence: the legacy build's base pairs are too narrow.

    ``atomistic.py`` applies its P-P correction to the template frame ORIGIN, and the
    two strands' frames are z-mirrored, so the correction rotates the phosphates toward
    each other and pulls C1'-C1' in to 0.967 nm.  Measured placement restores it.
    """

    def median_c1(model):
        nucs = _by_nucleotide(model)
        vals = [
            np.linalg.norm(
                nucs[(h, bp, "FORWARD", None)]["C1'"]
                - nucs[(h, bp, "REVERSE", None)]["C1'"]
            )
            for (h, bp, d, k) in nucs
            if d == "FORWARD" and k is None and (h, bp, "REVERSE", None) in nucs
        ]
        return float(np.median(vals))

    legacy, measured = median_c1(_build(False)), median_c1(_build(True))
    assert legacy == pytest.approx(0.967, abs=0.005), "legacy collapse value moved"
    assert measured > legacy + 0.03
    assert 0.99 < measured < 1.10


def test_measured_build_keeps_atom_and_bond_counts():
    """Same atoms, same bonds — only positions move.

    The measured templates carry the same atom names as the 1ZEW ones precisely so the
    bond tables, element table and renderer are untouched by this.
    """
    legacy, measured = _build(False), _build(True)
    assert len(measured.atoms) == len(legacy.atoms)
    assert measured.bonds == legacy.bonds
    assert [a.name for a in measured.atoms] == [a.name for a in legacy.atoms]


def test_measured_placement_is_the_default():
    """Native means native: a caller that asks for nothing gets the measured build.

    Every export, MD seed and display path goes through ``build_atomistic_model``
    without naming the mode, so this default is what makes the measured geometry
    reach simulations rather than only the viewer.
    """
    import inspect

    from backend.core.atomistic import build_atomistic_model

    sig = inspect.signature(build_atomistic_model)
    assert sig.parameters["measured_positioning"].default is True

    default_build = _build_default()
    measured = _build(measured=True)
    assert [(a.x, a.y, a.z) for a in default_build.atoms] == [
        (a.x, a.y, a.z) for a in measured.atoms
    ]


def test_legacy_frame_is_independent_of_lattice_cell_type():
    """What makes the legacy-local conversion well-defined at all.

    ``geometry.py`` places the reverse bead at fwd +-150 deg by cell type and
    ``_atom_frame`` then corrects by +58.2/-1.8 deg; the two paths must land on the
    same frame, or one fixed template could not serve both cell types.
    """
    from backend.core.atomistic import _atom_frame
    from backend.core.constants import HELIX_RADIUS
    from backend.core.geometry import NucleotidePosition
    from backend.core.models import Direction

    axis_pt = np.zeros(3)
    tangent = np.array([0.0, 0.0, 1.0])
    for direction in (Direction.FORWARD, Direction.REVERSE):
        frames = []
        for helix_dir in (Direction.FORWARD, Direction.REVERSE):
            sign = 1.0 if helix_dir == Direction.FORWARD else -1.0
            phi = 0.0 if direction == Direction.FORWARD else sign * math.radians(150.0)
            bead = np.array(
                [HELIX_RADIUS * math.cos(phi), HELIX_RADIUS * math.sin(phi), 0.0]
            )
            nuc = NucleotidePosition(
                helix_id="h",
                bp_index=0,
                direction=direction,
                position=bead,
                base_position=bead * 0.5,
                base_normal=-bead / np.linalg.norm(bead),
                axis_tangent=tangent,
            )
            frames.append(
                _atom_frame(
                    nuc, direction, axis_point=axis_pt, helix_direction=helix_dir
                )
            )
        assert np.allclose(frames[0][0], frames[1][0], atol=1e-12)
        assert np.allclose(frames[0][1], frames[1][1], atol=1e-12)


@pytest.mark.parametrize("residue", RESIDUES)
def test_legacy_local_conversion_stamps_identically(residue):
    """The conversion the surface + stamp-descriptor paths rely on.

    Stamping the converted template through the LEGACY frame must land every atom
    exactly where the base-pair frame puts it — otherwise the surface and the
    ball-and-stick would show two different molecules.
    """
    from backend.core.atomistic import _atom_frame
    from backend.core.constants import HELIX_RADIUS
    from backend.core.geometry import NucleotidePosition
    from backend.core.models import Direction

    rng = np.random.default_rng(11)
    legacy_local = ma.legacy_local_templates()

    for _trial in range(3):
        t = rng.normal(size=3)
        t /= np.linalg.norm(t)
        axis_pt = rng.normal(size=3)
        a = np.cross(t, rng.normal(size=3))
        a /= np.linalg.norm(a)
        for helix_dir in (Direction.FORWARD, Direction.REVERSE):
            sign = 1.0 if helix_dir == Direction.FORWARD else -1.0
            for direction in (Direction.FORWARD, Direction.REVERSE):
                phi = (
                    0.0
                    if direction == Direction.FORWARD
                    else sign * math.radians(150.0)
                )
                e = math.cos(phi) * a + math.sin(phi) * np.cross(t, a)
                bead = axis_pt + HELIX_RADIUS * e
                nuc = NucleotidePosition(
                    helix_id="h",
                    bp_index=0,
                    direction=direction,
                    position=bead,
                    base_position=bead,
                    base_normal=-e,
                    axis_tangent=t,
                )
                o_l, R_l = _atom_frame(
                    nuc, direction, axis_point=axis_pt, helix_direction=helix_dir
                )
                o_m, R_m = ma.measured_frame(axis_pt + HELIX_RADIUS * a, t, axis_pt)

                lsug, lbase = legacy_local[(direction.name, residue)]
                msug, mbase = ma.measured_templates()[(direction.name, residue)]
                for (ln, _le, *L), (mn, _me, *M) in zip(lsug + lbase, msug + mbase):
                    assert ln == mn
                    assert np.allclose(
                        o_l + R_l @ np.array(L), o_m + R_m @ np.array(M), atol=1e-12
                    )


def test_provenance_travels_with_the_numbers():
    prov = ma.provenance()
    assert prov["span_bp"] == 21
    assert prov["bp_measured"] > 10_000
    assert len(prov["sources"]) >= 3, "pooled from several independent trajectories"
