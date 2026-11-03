import pytest
from backend.core.namd_atom_counts import canonical_dna_atoms
from backend.core.pdb_export import export_coordinate_pdb
from backend.core.namd_topology import build_charmm_psfgen_topology,find_psfgen
from tests.conftest import make_6hb_design


def test_canonical_count_matches_real_psfgen_preparation():
    try:find_psfgen()
    except RuntimeError:pytest.skip('psfgen is not installed')
    design=make_6hb_design(8)
    predicted=canonical_dna_atoms(export_coordinate_pdb(design))
    topology=build_charmm_psfgen_topology(design)
    actual=next(int(line.split()[0]) for line in topology.psf_text.splitlines() if '!NATOM' in line)
    assert predicted==actual


def test_reused_chain_names_remain_separate_across_ter_records():
    pdb=export_coordinate_pdb(make_6hb_design(8))
    # Concatenation reuses every PDB chain/residue label, but repeats the atoms.
    assert canonical_dna_atoms(pdb+'\nTER\n'+pdb)==2*canonical_dna_atoms(pdb)


def test_noncanonical_solute_requires_the_existing_allowance():
    pdb=export_coordinate_pdb(make_6hb_design(8))
    line=next(line for line in pdb.splitlines() if line.startswith('ATOM'))
    protein=line[:17]+'ALA'+line[20:]
    assert canonical_dna_atoms(pdb+'\n'+protein) is None
