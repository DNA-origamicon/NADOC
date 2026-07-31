"""Solvent topology selection — which atoms are water, which are ions.

Pure numpy over name/resname arrays, so these run without MDAnalysis or a real
topology. The synthetic arrays reproduce the atom-name pattern read out of the
real solvated PSFs (workspace/md_jobs/8bcec48cf042):

    TIP3 → OH2, H1, H2
    MGH  → MG, then six contiguous OHx, H1x, H2x triples (x = A…F)
    SOD  → SOD          CLA → CLA
"""

import numpy as np
import pytest

from backend.core.md_solvent import (
    SPECIES,
    WATER_ISH_RESNAMES,
    ion_rows,
    water_triplets,
)


def _topology(*residues):
    """(names, resnames, resindices) for a list of (resname, [atom names])."""
    names, resnames, resindices = [], [], []
    for i, (rn, atoms) in enumerate(residues):
        for a in atoms:
            names.append(a)
            resnames.append(rn)
            resindices.append(i)
    return names, resnames, resindices


TIP3 = ("TIP3", ["OH2", "H1", "H2"])
MGH = ("MGH", ["MG"] + [f"{p}{s}" for s in "ABCDEF" for p in ("OH", "H1", "H2")])
PROTEIN = ("ALA", ["N", "CA", "C", "O", "CB"])


class TestWaterTriplets:
    def test_finds_tip3_water(self):
        o, h1, h2 = water_triplets(*_topology(TIP3, TIP3))
        assert o.tolist() == [0, 3]
        assert h1.tolist() == [1, 4]
        assert h2.tolist() == [2, 5]

    def test_finds_all_six_hexahydrate_waters_and_excludes_the_mg(self):
        # The MG atom is the ION, not water — it must not appear here (ion_rows
        # claims it). Its six waters are ordinary water and DO appear.
        o, h1, h2 = water_triplets(*_topology(MGH))
        assert o.size == 6
        assert 0 not in o.tolist()             # index 0 is the MG atom
        names = _topology(MGH)[0]
        assert [names[i] for i in o] == ["OHA", "OHB", "OHC", "OHD", "OHE", "OHF"]
        assert [names[i] for i in h1] == ["H1A", "H1B", "H1C", "H1D", "H1E", "H1F"]
        assert [names[i] for i in h2] == ["H2A", "H2B", "H2C", "H2D", "H2E", "H2F"]

    def test_ignores_dna_and_protein_oxygens(self):
        dna = ("DA", ["P", "O1P", "O2P", "O5'", "C5'", "O4'"])
        o, _, _ = water_triplets(*_topology(dna, PROTEIN, TIP3))
        assert o.size == 1                     # only the TIP3 oxygen

    def test_empty_topology(self):
        o, h1, h2 = water_triplets([], [], [])
        assert o.size == h1.size == h2.size == 0

    # The wire format ships water as bare coordinates with no identity table,
    # which is only sound because each molecule is a contiguous O,H,H run. When
    # that does not hold the code must fall back, not emit a neighbour's atom.
    def test_falls_back_when_the_molecule_is_not_contiguous(self):
        scrambled = ("TIP3", ["OH2", "XX", "H1", "H2"])
        o, h1, h2 = water_triplets(*_topology(scrambled))
        assert o.tolist() == [0]
        assert h1.tolist() == [2]              # skipped the interloper
        assert h2.tolist() == [3]

    def test_drops_a_molecule_whose_hydrogens_are_missing(self):
        lone = ("TIP3", ["OH2"])
        o, _, _ = water_triplets(*_topology(lone, TIP3))
        assert o.size == 1                     # only the intact molecule
        assert o.tolist() == [1]

    def test_a_trailing_oxygen_cannot_read_past_the_end(self):
        o, _, _ = water_triplets(*_topology(TIP3, ("TIP3", ["OH2"])))
        assert o.tolist() == [0]

    def test_hydrogens_must_belong_to_the_same_residue(self):
        # Two single-atom waters back to back: the first O's "next two atoms" are
        # in a DIFFERENT residue, so it must not adopt them.
        o, _, _ = water_triplets(*_topology(("TIP3", ["OH2"]), TIP3))
        assert o.tolist() == [1]

    def test_mgh_is_treated_as_water_bearing(self):
        assert "MGH" in WATER_ISH_RESNAMES
        assert "TIP3" in WATER_ISH_RESNAMES


class TestIonRows:
    def test_maps_charmm_names_to_species(self):
        names, resn, _ = _topology(("SOD", ["SOD"]), ("CLA", ["CLA"]), ("POT", ["POT"]))
        rows, codes = ion_rows(names, resn)
        assert rows.tolist() == [0, 1, 2]
        assert [SPECIES[c] for c in codes] == ["NA", "CL", "K"]

    def test_hexahydrate_contributes_exactly_one_magnesium(self):
        names, resn, _ = _topology(MGH)
        rows, codes = ion_rows(names, resn)
        assert rows.tolist() == [0]
        assert [SPECIES[c] for c in codes] == ["MG"]

    # Selecting ions by NAME alone would read every protein alpha-carbon as
    # calcium; by RESNAME alone it would sweep in the six MGH waters. It is
    # qualified by both.
    def test_a_protein_alpha_carbon_is_not_a_calcium_ion(self):
        names, resn, _ = _topology(PROTEIN)
        rows, codes = ion_rows(names, resn)
        assert rows.size == 0
        assert codes.size == 0

    def test_amber_style_bare_names(self):
        names, resn, _ = _topology(("NA", ["NA"]), ("CL", ["CL"]), ("MG", ["MG"]))
        rows, codes = ion_rows(names, resn)
        assert [SPECIES[c] for c in codes] == ["NA", "CL", "MG"]

    def test_no_ions(self):
        rows, codes = ion_rows(*_topology(TIP3)[:2])
        assert rows.size == 0

    def test_species_codes_index_the_species_table(self):
        names, resn, _ = _topology(("SOD", ["SOD"]), MGH, ("CLA", ["CLA"]))
        _rows, codes = ion_rows(names, resn)
        assert all(0 <= int(c) < len(SPECIES) for c in codes)

    # The frontend keys its colour/radius table off the species CODE, so the
    # order of SPECIES is a wire contract: append only, never reorder.
    def test_species_table_order_is_pinned(self):
        assert SPECIES[:3] == ("NA", "CL", "MG")


class TestBuildSolventCtxShape:
    def test_ctx_reports_totals(self):
        from backend.core.md_solvent import build_solvent_ctx

        class _Atoms:
            names = np.array([a for a in (TIP3[1] + MGH[1] + ["SOD"])], dtype="U8")
            resnames = np.array(
                ["TIP3"] * 3 + ["MGH"] * 19 + ["SOD"], dtype="U8")
            resindices = np.array([0] * 3 + [1] * 19 + [2], dtype=np.int64)

            def __len__(self):
                return len(self.names)

        class _U:
            atoms = _Atoms()

        ctx = build_solvent_ctx(_U())
        assert ctx["n_waters_total"] == 7      # 1 TIP3 + 6 hexahydrate waters
        assert ctx["n_ions"] == 2              # the MG core + the Na+
        assert ctx["water_o"].size == ctx["n_waters_total"]


@pytest.mark.parametrize("resname", ["TIP3", "HOH", "WAT"])
def test_all_water_resnames_are_recognised(resname):
    o, _, _ = water_triplets(*_topology((resname, ["OH2", "H1", "H2"])))
    assert o.size == 1
