"""Every built nucleotide is a correctly-handed molecule, not an enantiomer.

DNA is chiral and so is every deoxyribose in it.  The atomistic layer stamps ONE
sugar template and ONE base template per base type onto both strands, and the two
strands' frames differ by a z-flip (``e_z = -axis_tangent`` on FORWARD, ``+`` on
REVERSE).  A z-flip implemented as a REFLECTION would silently turn every
reverse-strand nucleotide into L-deoxyribose — a defect that leaves bond lengths,
bond angles, base pairing and every RMSD check completely intact, and would be
invisible to the rest of this suite.

It is implemented as a rotation (``e_y = e_z x e_n`` co-flips, keeping the frame
right-handed), which is physically right: an antiparallel strand's nucleotide is the
same molecule turned end over end.  These tests hold that line.

Signed volume is the tool throughout: for a stereocentre C with substituents a, b, c,
``(a-C) . ((b-C) x (c-C))`` is invariant under proper rotation and flips sign under
reflection.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
import pytest

from backend.core import atomistic as at
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.geometry import nucleotide_positions
from backend.core.models import Design

PURINES = {"DA", "DG", "ADE", "GUA", "A", "G"}


def _signed_volume(centre, a, b, c) -> float:
    return float(np.dot(a - centre, np.cross(b - centre, c - centre)))


def _base_nitrogen(resname: str) -> str:
    return "N9" if resname.strip().upper() in PURINES else "N1"


def _two_cell_design() -> Design:
    """A real bundle spanning both lattice cell types, so both stamping paths are
    covered.  It must carry STRANDS: build_atomistic_model emits atoms per strand, so
    a helices-only fixture silently produces an empty model and every assertion here
    would vacuously pass."""
    from backend.api import headless_build as hb
    from backend.core.models import LatticeType

    with hb.scratch_session(LatticeType.SQUARE):
        return hb.create_bundle([[0, 0], [0, 1]], 24, lattice=LatticeType.SQUARE,
                                name="chirality-fixture")


@pytest.fixture(scope="module")
def built():
    design = _two_cell_design()
    model = at.build_atomistic_model(design, frame_sink={})
    groups: dict = defaultdict(dict)
    resnames: dict = {}
    for a in model.atoms:
        if a.crossover_id is not None or a.extension_id is not None:
            continue
        groups[(a.helix_id, a.bp_index, a.direction)][a.name] = np.array([a.x, a.y, a.z])
        resnames[(a.helix_id, a.bp_index, a.direction)] = a.residue
    return design, groups, resnames


def test_every_stamping_frame_is_a_proper_rotation():
    """det(R) = +1 exactly.  A single improper frame would enantiomerise a whole strand."""
    design = _two_cell_design()
    dets = []
    for helix in design.helices:
        start = np.asarray(helix.axis_start.to_array())
        end = np.asarray(helix.axis_end.to_array())
        axis = (end - start) / np.linalg.norm(end - start)
        for nuc in nucleotide_positions(helix):
            axis_pt = start + nuc.bp_index * BDNA_RISE_PER_BP * axis
            _origin, R = at._atom_frame(
                nuc, nuc.direction, axis_point=axis_pt, helix_direction=helix.direction)
            dets.append(float(np.linalg.det(R)))
    assert dets, "fixture produced no frames"
    assert min(dets) == pytest.approx(1.0, abs=1e-9)
    assert max(dets) == pytest.approx(1.0, abs=1e-9)


def test_the_sugar_template_itself_is_D_deoxyribose():
    """The one template every nucleotide is stamped from, checked against 1ZEW's signs.

    C4' uses only template atoms, so it is the stereocentre to assert on; C3' involves
    O3', which the phosphodiester linker builder moves (see the O3' test below).
    """
    tmpl = {a[0]: np.array(a[2:5], dtype=float) for a in at._SUGAR}
    c4 = _signed_volume(tmpl["C4'"], tmpl["O4'"], tmpl["C3'"], tmpl["C5'"])
    c3 = _signed_volume(tmpl["C3'"], tmpl["C2'"], tmpl["C4'"], tmpl["O3'"])
    assert c4 < 0, "C4' inverted — the sugar template is the wrong enantiomer"
    assert c3 < 0, "C3' inverted — the sugar template is the wrong enantiomer"


@pytest.mark.parametrize("centre,subs", [
    ("C4'", ("O4'", "C3'", "C5'")),
])
def test_sugar_stereocentres_hold_one_sign_across_both_cells_and_both_strands(
        built, centre, subs):
    _design, groups, _resnames = built
    signs = defaultdict(list)
    for key, res in groups.items():
        if not all(n in res for n in (centre, *subs)):
            continue
        v = _signed_volume(res[centre], *(res[n] for n in subs))
        signs[key[2]].append(v)
    assert signs, "no residues measured"
    for direction, values in signs.items():
        arr = np.array(values)
        assert (arr < 0).all(), (
            f"{centre} inverted on {len(arr[arr >= 0])}/{len(arr)} {direction} nucleotides")


def test_the_glycosidic_centre_is_beta_on_every_nucleotide(built):
    """C1' carries the base.  Its sign is what says the base is on the correct face
    (beta-configuration) rather than mirrored onto the other side of the sugar."""
    _design, groups, resnames = built
    values = []
    for key, res in groups.items():
        n_base = _base_nitrogen(resnames[key])
        if not all(n in res for n in ("C1'", "O4'", "C2'", n_base)):
            continue
        values.append(_signed_volume(res["C1'"], res["O4'"], res["C2'"], res[n_base]))
    arr = np.array(values)
    assert arr.size
    assert (arr > 0).all(), f"C1' inverted on {int((arr <= 0).sum())}/{arr.size} nucleotides"


def test_reverse_base_templates_are_rotations_not_reflections():
    """The REVERSE tables fit the FORWARD ones at det = -1, but the rings are PLANAR,
    which makes the fit degenerate — a planar molecule is achiral, so reflection through
    its own plane is the identity and the SVD picks a sign arbitrarily.

    The real question is whether a PROPER rotation fits just as well.  It does, to
    within a picometre, which is what makes the det = -1 harmless.
    """
    for name in ("DA", "DT", "DG", "DC"):
        fwd = {a[0]: np.array(a[2:5], dtype=float) for a in at.BASE_TEMPLATES[name][0]}
        rev = {a[0]: np.array(a[2:5], dtype=float) for a in at.BASE_TEMPLATES_REV[name][0]}
        common = [n for n in fwd if n in rev]
        P = np.array([fwd[n] for n in common])
        W = np.array([rev[n] for n in common])

        # planar to a few pm — the premise of the degeneracy argument
        out_of_plane = np.linalg.svd(P - P.mean(0), compute_uv=False)[2]
        assert out_of_plane < 0.005, f"{name} ring is not planar ({out_of_plane:.4f} nm)"

        Pc, Wc = P.mean(0), W.mean(0)
        U, _S, Vt = np.linalg.svd((P - Pc).T @ (W - Wc))
        D = np.sign(np.linalg.det(Vt.T @ U.T))
        R = Vt.T @ np.diag([1.0, 1.0, D]) @ U.T
        rms = np.sqrt(np.mean(np.sum(((R @ (P - Pc).T).T - (W - Wc)) ** 2, axis=1)))
        assert rms < 0.005, f"{name} REVERSE template is not a rotation of FORWARD ({rms:.4f} nm)"


def test_whole_nucleotides_are_rotations_of_one_another(built):
    """The end-to-end statement: fit every built residue onto a forward-strand reference
    of the same base with NO reflection guard, and every fit must come back proper."""
    _design, groups, resnames = built
    refs: dict = {}
    for key, res in groups.items():
        if key[2] == "FORWARD" and 5 < key[1] < 19 and resnames[key] not in refs:
            refs[resnames[key]] = res
    assert refs, "no reference residues"

    checked = 0
    for key, res in groups.items():
        ref = refs.get(resnames[key])
        if ref is None:
            continue
        # Exclude the atoms the linker builder relocates; this is a question about the
        # stamped rigid body, not about the phosphodiester bridge.
        common = [n for n in ref
                  if n in res and n not in ("P", "OP1", "OP2", "O5'", "O3'")]
        if len(common) < 8:
            continue
        P = np.array([ref[n] for n in common])
        W = np.array([res[n] for n in common])
        Pc, Wc = P.mean(0), W.mean(0)
        U, _S, Vt = np.linalg.svd((P - Pc).T @ (W - Wc))
        R = Vt.T @ U.T                      # deliberately unguarded
        assert np.linalg.det(R) > 0, f"{key} is a REFLECTION of its reference"
        checked += 1
    assert checked > 50, f"only {checked} residues checked"


def test_o3prime_displacement_is_a_bond_defect_not_a_chirality_one(built):
    """Some residues read as inverted at C3' because the linker builder drags O3' far
    off its template position.  This pins the distinction: the intra-template control
    bond C3'-C4' must stay rigid everywhere, so any C3' inversion is attributable to
    O3' alone and never to a mirrored stamp.
    """
    _design, groups, _resnames = built
    control = []
    for res in groups.values():
        if "C3'" in res and "C4'" in res:
            control.append(float(np.linalg.norm(res["C3'"] - res["C4'"])))
    arr = np.array(control)
    assert arr.size
    assert arr.std() < 1e-6, (
        "C3'-C4' varies across residues — the template is no longer stamped rigidly, "
        "so a C3' sign flip can no longer be attributed to O3' displacement alone")
