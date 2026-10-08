"""Mg counterions plus requested added salt; independent charge-balance checks."""

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
_FEW_WATERS = 4_000  # ~120 nm³ solvent → one rounded MgCl2 unit at 12.5 mM


def _counts(q, *, waters=_FEW_WATERS, nacl=0.0, mgcl2=12.5, mgh=True, box=_SMALL_BOX):
    return ion_counts(
        waters, q, nacl_mM=nacl, mgcl2_mM=mgcl2, box_nm=box, mg_hexahydrate=mgh
    )


def test_magnesium_is_the_counterion_and_there_is_no_sodium():
    ions = _counts(-500.0)
    assert ions.counterion == "mg"
    assert ions.n_na == 0
    assert ions.n_mg == 251  # 250 neutralisers + one MgCl2
    assert ions.n_cl == 2  # chloride from the added MgCl2


def test_system_is_electrically_neutral():
    """2*n_mg + n_na - n_cl == |q_DNA|, which is the whole point of the recipe."""
    for q in (-1.0, -2.0, -501.0, -13_982.0):
        ions = _counts(q)
        assert 2 * ions.n_mg + ions.n_na - ions.n_cl == ions.dna_neg_charge


def test_odd_backbone_charge_adds_one_chloride_beyond_salt_pairs():
    ions = _counts(-501.0)
    assert ions.n_mg == 252  # 251 neutralisers + one MgCl2
    assert ions.n_cl == 3  # two salt chlorides + one for odd charge
    assert ions.n_na == 0


def test_bulk_magnesium_in_excess_is_balanced_by_chloride():
    """Requested salt remains additive even when it exceeds counterion demand."""
    ions = ion_counts(
        2_000_000, -100.0, nacl_mM=0.0, mgcl2_mM=12.5, box_nm=(40.0, 40.0, 40.0)
    )
    assert ions.n_mg_bulk > ions.n_mg_neutralising
    assert ions.n_mg == 50 + ions.n_mg_bulk
    assert ions.n_cl == 2 * ions.n_mg - 100
    assert ions.n_na == 0


def test_requested_salt_is_not_absorbed_by_neutralisation():
    ions = _counts(-5_000.0)
    assert ions.n_mg_neutralising == 2_500
    assert ions.n_mg_bulk < ions.n_mg_neutralising
    assert ions.n_mg == 2_501
    assert ions.n_cl == 2


def test_explicit_zero_magnesium_falls_back_to_sodium():
    """Asking for 0 mM Mg is a deliberate monovalent-screening experiment, not the
    origami protocol — it must still work, and must not silently add magnesium."""
    ions = _counts(-500.0, mgcl2=0.0, nacl=150.0)
    assert ions.counterion == "na"
    assert ions.n_mg == 0
    assert ions.n_na == 500 + ions.n_cl - 0  # neutralising Na+ plus the NaCl bath
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
    assert ions.n_mg == 251
    assert ions.n_na == ions.n_cl - 2 > 0  # NaCl plus one MgCl2
    assert 2 * ions.n_mg + ions.n_na - ions.n_cl == 500


def test_bulk_terms_use_solvent_volume_by_default():
    """Count-based solvent volume excludes solute and unfilled space."""
    waters = 1_000_000
    box = (60.0, 20.0, 76.0)  # 91,200 nm³ vs ~29,940 nm³ of water
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


def test_tutorial_census_can_be_reproduced_with_added_salt():
    # Direct PSF census: DNA -865 e, 516 MGH and 167 CLA. This chosen volume
    # encodes 83 added formula units, not a claim about the tutorial's molarity.
    volume = 83 / (12.5e-3 * _NA * 1e-24)
    ions = ion_counts(
        0, -865, nacl_mM=0, mgcl2_mM=12.5, box_nm=_SMALL_BOX, volume_nm3=volume
    )
    assert ions.as_tuple() == (0, 516, 167)


def test_salt_note_distinguishes_new_and_historical_packages():
    from backend.core.md_protocols import _salt_note

    historical = {
        "counterion": "mg", "dna_charge_used_e": -6982,
        "n_mg": 3491, "n_mg_neutralising": 3491, "n_mg_bulk": 84,
    }
    assert "legacy total-Mg convention" in _salt_note({"ionization": historical})
    current = {
        **historical, "n_mg": 3575, "n_cl": 168,
        "concentration_convention": "added_salt_after_neutralization",
    }
    note = _salt_note({"ionization": current})
    assert "3,491 neutralising + 84 added MgCl2" in note
    assert "168 Cl-" in note
