import json
import numpy as np
import pytest
from backend.core.models import Design, Nanoparticle
from backend.core.streptavidin import build_streptavidin_coating
from backend.core.gold_strep_dna import build_dna_set
from backend.core.strep_biotin_namd import write_preparation, resolve_psf_identity
from backend.core.biotin_teg_chemistry import chemical_definition


def example():
    p = Nanoparticle(diameter_nm=10, coating=build_streptavidin_coating(10, count_override=1))
    entries = build_dna_set(p, 'ACGTACGT', linker_nm=1.8)
    p.biotin_dna = [r for r, _, _ in entries]
    return Design(nanoparticles=[p], helices=[h for _, h, _ in entries],
                  strands=[s for _, _, s in entries])


def test_preparation_keeps_phosphate_and_distinct_component_identity(tmp_path):
    d = example(); original = d.model_dump_json()
    m = write_preparation(d, tmp_path/'review')
    assert d.model_dump_json() == original
    assert not m['simulation_ready']
    assert len(m['proteins']) == 4
    assert sum(a['component'] == 'protein' for a in m['identity']) == 3604
    assert sum(a['component'] == 'biotin_teg' for a in m['identity']) == 28
    keys = [(a['segid'], a['resid'], a['atom_name']) for a in m['identity']]
    assert len(keys) == len(set(keys))
    text = (tmp_path/'review/build_psfgen.tcl').read_text()
    assert 'segment D000 {\n  first NONE' in text
    assert 'patch DEOX D000:1' in text and 'patch DEO5 D000:1' not in text
    assert 'patch BTE5 L000:1 D000:1' in text
    assert 'BTE5 P' not in text
    assert m['covalent_links'][0]['bond_nm'] == pytest.approx(.160, abs=.002)
    assert sum(l.startswith('ATOM') for l in (tmp_path/'review/complex_heavy.pdb').read_text().splitlines()) == len(m['identity'])
    lines = (tmp_path/'review/complex_heavy.pdb').read_text().splitlines()
    serials = [int(l[6:11]) for l in lines if l.startswith('ATOM')]
    assert len(serials) == len(set(serials))
    assert sum(l.startswith('CONECT') for l in lines) == 30
    # Biotin C7 must not inherit the thymine C7 -> C5M alias.
    expected = {a['name'] for a in chemical_definition()['atoms']}
    ligand_lines = (tmp_path/'review/inputs/L000.pdb').read_text().splitlines()
    assert {l[12:16].strip() for l in ligand_lines if l.startswith('ATOM')} == expected
    assert {l[12:16].strip() for l in lines if l.startswith('ATOM') and l[17:20] == 'BTE'} == expected


def test_unreachable_linker_does_not_emit_a_package(tmp_path):
    d = example(); d.nanoparticles[0].pose.values[3] += 20
    with pytest.raises(ValueError, match='unconnected'):
        write_preparation(d, tmp_path/'bad')
    assert not (tmp_path/'bad').exists()


def test_chemical_graph_retains_carbonyls_rings_and_phosphate_valence():
    definition = chemical_definition()
    assert len(definition['atoms']) == 28 and len(definition['bonds']) == 29
    assert sum(a['hydrogen_count'] for a in definition['atoms']) == 32
    assert next(a for a in definition['atoms'] if a['name'] == 'O4T')['hydrogen_count'] == 0
    assert sum(b['order'] == 2 for b in definition['bonds']) == 2
    assert not definition['forcefield_parameters_present']


def test_mapping_uses_final_psf_indices_and_rejects_missing_atoms():
    psf = 'PSF\n\n 3 !NATOM\n 1 P000 13 ALA HT1 H 0.1 1.008\n 2 P000 13 ALA N NH3 -0.3 14.0\n 3 L000 1 BTE O4T O -0.5 16.0\n'
    identities = [dict(segid='L000', resid=1, atom_name='O4T'), dict(segid='P000', resid=13, atom_name='N')]
    assert [a['psf_index'] for a in resolve_psf_identity(psf, identities)] == [3, 2]
    with pytest.raises(ValueError, match='Missing mapped atom'):
        resolve_psf_identity(psf, [dict(segid='D000', resid=1, atom_name='P')])
