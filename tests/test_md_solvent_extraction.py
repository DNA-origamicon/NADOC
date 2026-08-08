"""Real-topology solvent extraction — the physics the fast tests cannot check.

SLOW (area ``md``, registered whole-file in conftest): opens a real solvated
PSF + DCD, so every test here pays a ~2 s universe build plus a per-frame
neighbour search. Test-dedicated session only.

What the fast suite already covers (selection helpers, the affine, the wire
format) is deliberately NOT repeated. These assert the things that only a real
solvated trajectory can answer:

  * the shell really is a shell, measured AFTER the display transform
  * water molecules survive the periodic imaging intact
  * ion counts match the package's own charge audit
  * the drawn cell actually contains the DNA
"""

from __future__ import annotations

from pathlib import Path

import json
import numpy as np
import pytest

from backend.core import md_solvent as MS
from backend.core import md_trajectory as MT

REPO = Path(__file__).resolve().parent.parent
PKG = REPO / "workspace/md_validation/10hb_managed_strict/package/10hb_namd_solvated"
PSF = PKG / "10hb.psf"
REF = PKG / "10hb.pdb"
DCD = PKG / "output/10hb_01_050K_NVT_k5_p10.dcd"
DESIGN = REPO / "workspace/10hb.nadoc"

pytestmark = pytest.mark.skipif(
    not (PSF.exists() and REF.exists() and DCD.exists() and DESIGN.exists()),
    reason="needs the real solvated 10hb validation package (user workspace)",
)


@pytest.fixture(scope="module")
def solvated():
    """(ctx, solvent ctx, frame_out, xform, DNA display coords) for frame 0."""
    from backend.core.models import Design

    design = Design.model_validate_json(DESIGN.read_text())
    ctx = MT._build_md_nadoc_ctx(PSF, [DCD], REF, design, with_atoms=True)
    sctx = MS.build_solvent_ctx(ctx["universe"])
    fo: dict = {}
    atoms = MT._extract_md_atoms_frame(ctx, 0, frame_out=fo)
    assert fo, "the heavy extractor did not hand over its display transform"
    xf = MS.DisplayXform.build(
        T_dyn=fo["T_dyn"],
        c_box=fo["c_box"],
        box_nm=fo["box_nm"],
        mob_c=fo["mob_c"],
        eq_centroid=fo["eq_centroid"],
        R=fo["R_align"],
    )
    dna = np.array([[a["x"], a["y"], a["z"]] for a in atoms])
    return ctx, sctx, fo, xf, dna


def _extract(solvated, **kw):
    ctx, sctx, fo, xf, _dna = solvated
    return MS.extract_solvent_frame(
        ctx["universe"], sctx, fo["pos_raw"], fo["pos_pre"], xf, **kw
    )


# ── the transform actually reaches the wire ──────────────────────────────────


def test_the_emitted_affine_reproduces_the_served_dna_exactly(solvated):
    """If this drifts, solvent lands somewhere else from the DNA it belongs to.

    Not 'close' — the affine handed over by `frame_out` must be the SAME
    arithmetic the extractor applied, so the residual is exactly zero.
    """
    _ctx, _sctx, fo, xf, dna = solvated
    assert np.abs(MS.apply_xform(fo["pos_pre"], xf) - dna).max() == 0.0


# ── the shell is a shell ─────────────────────────────────────────────────────


@pytest.mark.parametrize("shell_ang", [3.5, 5.0, 8.0])
def test_every_selected_water_is_inside_the_shell_after_the_transform(
    solvated, shell_ang
):
    """A rotation is an isometry, so 'within N Å of a DNA atom' has to still be
    true on screen. This is the property that makes the shell mean anything."""
    from scipy.spatial import cKDTree

    _ctx, _sctx, _fo, _xf, dna = solvated
    out = _extract(solvated, shell_nm=shell_ang / 10.0)
    water = out["water"].reshape(-1, 3)
    assert water.shape[0] > 0
    d, _ = cKDTree(dna).query(water, k=1)
    assert d.max() <= shell_ang / 10.0 + 1e-6


def test_a_larger_shell_strictly_contains_a_smaller_one(solvated):
    a = _extract(solvated, shell_nm=0.35)["n_water"]
    b = _extract(solvated, shell_nm=0.50)["n_water"]
    c = _extract(solvated, shell_nm=0.80)["n_water"]
    assert a < b < c


def test_the_shell_is_a_small_fraction_of_the_cell(solvated):
    """The whole reason the shell is the default: it is the affordable view."""
    _ctx, sctx, _fo, _xf, _dna = solvated
    out = _extract(solvated, shell_nm=0.50)
    frac = out["n_water"] / sctx["n_waters_total"]
    assert 0.05 < frac < 0.60


# ── periodic imaging ─────────────────────────────────────────────────────────


def test_water_molecules_are_whole_after_imaging(solvated):
    """A molecule straddling the cell boundary must be re-imaged as a UNIT.
    TIP3P is rigid: O–H is 0.9572 Å and H–H 1.5139 Å by construction, so any
    departure means the molecule was torn across a periodic image."""
    out = _extract(solvated, shell_nm=0.50, atomistic=True)
    mol = out["water"].reshape(-1, 9)
    assert mol.shape[0] > 0
    oh1 = np.linalg.norm(mol[:, 3:6] - mol[:, 0:3], axis=1) * 10
    oh2 = np.linalg.norm(mol[:, 6:9] - mol[:, 0:3], axis=1) * 10
    hh = np.linalg.norm(mol[:, 6:9] - mol[:, 3:6], axis=1) * 10
    assert np.allclose(oh1, 0.9572, atol=0.02), (oh1.min(), oh1.max())
    assert np.allclose(oh2, 0.9572, atol=0.02), (oh2.min(), oh2.max())
    assert np.allclose(hh, 1.5139, atol=0.03), (hh.min(), hh.max())


def test_whole_cell_water_is_imaged_inside_the_drawn_cell(solvated):
    _ctx, _sctx, _fo, xf, _dna = solvated
    out = _extract(solvated, shell_nm=None)
    water = out["water"].reshape(-1, 3)
    corners = out["box"].reshape(8, 3)
    origin = corners[0]
    for k, L in zip((1, 2, 4), xf.box_nm):
        unit = (corners[k] - origin) / np.linalg.norm(corners[k] - origin)
        t = (water - origin) @ unit
        assert t.min() >= -1e-4
        assert t.max() <= L + 1e-4


# ── counts ───────────────────────────────────────────────────────────────────


def test_ion_counts_match_the_packages_own_charge_audit(solvated):
    """Independent oracle: the audit was written by the solvation builder, and
    the viewer reads the PSF. They must agree species by species."""
    _ctx, sctx, _fo, _xf, _dna = solvated
    audit = json.loads((PKG / "charge_audit.json").read_text())["ionization"]
    codes, counts = np.unique(sctx["ion_species"], return_counts=True)
    got = {MS.SPECIES[c]: int(n) for c, n in zip(codes, counts)}
    assert got.get("NA", 0) == audit["n_na"]
    assert got.get("CL", 0) == audit["n_cl"]
    assert got.get("MG", 0) == audit["n_mg"]


def test_hexahydrate_waters_count_as_water(solvated):
    """Each MGH contributes 6 waters on top of the audit's bulk TIP3 count —
    they ride the water toggle, which is what makes the Mg spheres look
    solvated on screen."""
    _ctx, sctx, _fo, _xf, _dna = solvated
    audit = json.loads((PKG / "charge_audit.json").read_text())["ionization"]
    expected = audit["n_waters"] + (
        6 * audit["n_mg"] if audit.get("mg_hexahydrate") else 0
    )
    assert sctx["n_waters_total"] == expected


def test_whole_cell_returns_every_molecule(solvated):
    _ctx, sctx, _fo, _xf, _dna = solvated
    assert _extract(solvated, shell_nm=None)["n_water"] == sctx["n_waters_total"]


def test_all_ions_are_drawn_regardless_of_the_shell(solvated):
    """Ions are never bounded — a 1 Å shell must still return all of them."""
    _ctx, sctx, _fo, _xf, _dna = solvated
    out = _extract(solvated, shell_nm=0.1)
    assert out["ions"].size // 3 == sctx["n_ions"]


# ── the cap ──────────────────────────────────────────────────────────────────


def test_the_cap_keeps_the_nearest_molecules_not_an_arbitrary_prefix(solvated):
    """A prefix would show one corner of the box and read as the whole thing."""
    from scipy.spatial import cKDTree

    _ctx, _sctx, _fo, _xf, dna = solvated
    full = _extract(solvated, shell_nm=0.80)
    capped = _extract(solvated, shell_nm=0.80, max_waters=2000)
    assert capped["capped"] and capped["n_water"] == 2000
    assert full["n_water"] > 2000

    tree = cKDTree(dna)
    d_full, _ = tree.query(full["water"].reshape(-1, 3), k=1)
    d_cap, _ = tree.query(capped["water"].reshape(-1, 3), k=1)
    # The kept 2000 are the closest 2000, so their worst distance is no worse
    # than the 2000th smallest of the full set.
    assert d_cap.max() <= np.partition(d_full, 1999)[1999] + 1e-9


# ── the cell ─────────────────────────────────────────────────────────────────


def test_the_drawn_cell_contains_the_dna(solvated):
    _ctx, _sctx, _fo, xf, dna = solvated
    corners = _extract(solvated, shell_nm=0.50)["box"].reshape(8, 3)
    origin = corners[0]
    for k, L in zip((1, 2, 4), xf.box_nm):
        edge = corners[k] - origin
        unit = edge / np.linalg.norm(edge)
        t = (dna - origin) @ unit
        assert t.min() >= 0.0
        assert t.max() <= L


def test_cell_edges_match_the_simulation_box(solvated):
    _ctx, _sctx, _fo, xf, _dna = solvated
    corners = _extract(solvated, shell_nm=0.50)["box"].reshape(8, 3)
    for k, L in zip((1, 2, 4), xf.box_nm):
        assert np.linalg.norm(corners[k] - corners[0]) == pytest.approx(L, abs=1e-4)


# ── the frame-to-frame property the overlay is built around ──────────────────


def test_the_shell_membership_changes_between_frames(solvated):
    """Water diffuses, so the molecule SET differs frame to frame. This is why
    the overlay snaps instead of interpolating, and why its meshes are
    capacity-allocated rather than sized to the count."""
    ctx, sctx, _fo, _xf, _dna = solvated
    counts = []
    for idx in (0, 2):
        fo: dict = {}
        MT._extract_md_atoms_frame(ctx, idx, frame_out=fo)
        xf = MS.DisplayXform.build(
            T_dyn=fo["T_dyn"],
            c_box=fo["c_box"],
            box_nm=fo["box_nm"],
            mob_c=fo["mob_c"],
            eq_centroid=fo["eq_centroid"],
            R=fo["R_align"],
        )
        counts.append(
            MS.extract_solvent_frame(
                ctx["universe"], sctx, fo["pos_raw"], fo["pos_pre"], xf, shell_nm=0.50
            )["n_water"]
        )
    assert counts[0] != counts[1], f"expected the shell to churn, got {counts}"
