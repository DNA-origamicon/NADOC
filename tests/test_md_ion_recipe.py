"""The Aksimentiev ion recipe — Mg(H2O)6 neutralises the origami, Cl- balances it.

Yoo, Li, Slone, Maffeo & Aksimentiev, Methods Mol Biol 1811 (2018) §3.3: MGHH(2+) is
inserted to neutralise the DNA and Cl- is then added to neutralise the *system*.  No
Na+ is involved.  NADOC neutralised with Na+ until 2026-07-30 and treated Mg as a bulk
bath only, so the preset labelled "Standard (Aksimentiev)" ran a monovalent-screened
system with a trace of magnesium.

These pin the arithmetic.  See namd_solvate.ion_counts.
"""

from __future__ import annotations

import math

from backend.core.namd_solvate import (
    MGH_ATOMS,
    MGH_WATERS_CONSUMED,
    _NA,
    _WATER_NUMBER_DENSITY_NM3,
    ion_counts,
)

# A box big enough that the bulk term never dominates the neutralisation term.
_SMALL_BOX = (10.0, 10.0, 10.0)
_FEW_WATERS = 4_000          # ~120 nm³ of solvent → sub-unit bulk Mg at 12.5 mM


def _counts(q, *, waters=_FEW_WATERS, nacl=0.0, mgcl2=12.5, mgh=True, box=_SMALL_BOX):
    return ion_counts(waters, q, nacl_mM=nacl, mgcl2_mM=mgcl2, box_nm=box,
                      mg_hexahydrate=mgh)


def test_magnesium_is_the_counterion_and_there_is_no_sodium():
    ions = _counts(-500.0)
    assert ions.counterion == "mg"
    assert ions.n_na == 0
    assert ions.n_mg == 250          # ceil(500/2)
    assert ions.n_cl == 0            # exactly neutralising, nothing left to balance


def test_system_is_electrically_neutral():
    """2*n_mg + n_na - n_cl == |q_DNA|, which is the whole point of the recipe."""
    for q in (-1.0, -2.0, -501.0, -13_982.0):
        ions = _counts(q)
        assert 2 * ions.n_mg + ions.n_na - ions.n_cl == ions.dna_neg_charge


def test_odd_backbone_charge_leaves_exactly_one_chloride():
    ions = _counts(-501.0)
    assert ions.n_mg == 251          # ceil(501/2)
    assert ions.n_cl == 1            # 2*251 - 501
    assert ions.n_na == 0


def test_bulk_magnesium_in_excess_is_balanced_by_chloride():
    """The tutorial's own case: they add Cl- *because* Mg exceeds the DNA charge."""
    ions = ion_counts(2_000_000, -100.0, nacl_mM=0.0, mgcl2_mM=12.5,
                      box_nm=(40.0, 40.0, 40.0))
    assert ions.n_mg_bulk > ions.n_mg_neutralising
    assert ions.n_mg == ions.n_mg_bulk
    assert ions.n_cl == 2 * ions.n_mg - 100
    assert ions.n_na == 0


def test_neutralisation_wins_when_the_bulk_term_is_smaller():
    ions = _counts(-5_000.0)
    assert ions.n_mg_neutralising == 2_500
    assert ions.n_mg_bulk < ions.n_mg_neutralising
    assert ions.n_mg == 2_500


def test_explicit_zero_magnesium_falls_back_to_sodium():
    """Asking for 0 mM Mg is a deliberate monovalent-screening experiment, not the
    origami protocol — it must still work, and must not silently add magnesium."""
    ions = _counts(-500.0, mgcl2=0.0, nacl=150.0)
    assert ions.counterion == "na"
    assert ions.n_mg == 0
    assert ions.n_na == 500 + ions.n_cl - 0   # neutralising Na+ plus the NaCl bath
    assert 2 * ions.n_mg + ions.n_na - ions.n_cl == 500


def test_bare_ion_placement_also_falls_back_to_sodium():
    """Without hexahydrate placement there is no MGHH model, so Mg must not be
    asked to carry the counterion role."""
    ions = _counts(-500.0, mgh=False)
    assert ions.counterion == "na"
    assert ions.n_na >= 500


def test_requested_nacl_bath_rides_on_top_of_magnesium_neutralisation():
    ions = _counts(-500.0, nacl=150.0)
    assert ions.counterion == "mg"
    assert ions.n_mg == 250
    assert ions.n_na == ions.n_cl > 0        # a pure NaCl bath, added in pairs
    assert 2 * ions.n_mg + ions.n_na - ions.n_cl == 500


def test_bulk_terms_use_solvent_volume_by_default():
    """A rotation-sized cell is mostly empty corner; charging bulk salt for the box
    volume over-salts it."""
    waters = 1_000_000
    box = (60.0, 20.0, 76.0)                 # 91,200 nm³ vs ~29,940 nm³ of water
    ions = ion_counts(waters, 0.0, nacl_mM=150.0, mgcl2_mM=0.0, box_nm=box)
    expected_vol = waters / _WATER_NUMBER_DENSITY_NM3
    assert math.isclose(ions.volume_nm3, expected_vol)
    assert ions.n_cl == round(150.0 * 1e-3 * _NA * expected_vol * 1e-24)


def test_zero_water_falls_back_to_box_volume():
    """A dry estimate has no water count yet — it must not divide by zero or
    silently report no salt."""
    ions = ion_counts(0, -10.0, nacl_mM=150.0, mgcl2_mM=0.0, box_nm=(20.0, 20.0, 20.0))
    assert ions.volume_nm3 == 8000.0
    assert ions.n_cl > 0


def test_mgh_geometry_constants_are_consistent():
    """19 atoms in, 6 waters (18 atoms) out — each cluster is only ~+1 atom net,
    which is why the recipe change is not a VRAM event."""
    assert MGH_ATOMS == 1 + 6 * 3
    assert MGH_WATERS_CONSUMED == 6
