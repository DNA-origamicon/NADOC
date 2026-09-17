"""Exercise import guards using the real DMEP control, not guessed biotin values."""
import json
from pathlib import Path
import shutil

import parmed
import pytest

from experiments.strep_biotin_namd.audit_assignment import audit


@pytest.fixture
def package(tmp_path):
    reference = Path(__file__).parent / 'ws/parameterization_final'
    if not reference.exists():
        pytest.skip('Isolated parameterization reference package is not present')
    shutil.copytree(reference / 'reference_forcefield', tmp_path / 'reference_forcefield')
    shutil.copyfile(reference / 'reference_forcefield.json', tmp_path / 'reference_forcefield.json')
    ff = tmp_path / 'reference_forcefield'
    residue = parmed.charmm.CharmmParameterSet(str(ff / 'top_all36_cgenff.rtf')).residues['DMEP']
    identity = [dict(name=a.name, index_1based=i+1) for i, a in enumerate(residue.atoms)]
    (tmp_path / 'atom_mapping.json').write_text(json.dumps(identity))
    ids = {a['name']: a['index_1based'] for a in identity}
    (tmp_path / 'BTMP.mol2').write_text('@<TRIPOS>BOND\n' + '\n'.join(
        f'{i+1} {ids[b.atom1.name]} {ids[b.atom2.name]} 1' for i, b in enumerate(residue.bonds)) + '\n')
    text = (ff / 'top_all36_cgenff.rtf').read_text()
    block = 'RESI DMEP' + text.split('RESI DMEP', 1)[1].split('RESI MP_0', 1)[0]
    stream = tmp_path / 'control.str'
    stream.write_text('* For use with CGenFF version 5.0\n*\nread rtf card append\n'
                      '* DMEP control only, not biotin\n*\n36 1\n' +
                      block.replace('RESI DMEP', 'RESI BTMP', 1) + 'END\n')
    return tmp_path, stream


def test_real_phosphate_control_has_complete_coverage(package):
    root, stream = package
    result = audit(root, stream, root / 'audit.json')
    assert result['parameters_resolved']
    assert result['atoms'] == 13
    assert result['charge'] == pytest.approx(-1)
    assert result['simulation_ready'] is False
    assert not list(root.glob('assignment_audit_*'))


def test_current_server_version_header(package):
    root, stream = package
    stream.write_text(stream.read_text().replace('For use with CGenFF version',
                                               'For use with CGenFF topology and parameter files version'))
    result = audit(root, stream, root / 'audit.json')
    assert result['cgenff_library'] == '5.0'
    assert result['parameters_resolved']


@pytest.mark.parametrize('change,reason', [('version', 'version'), ('charge', 'charge'), ('graph', 'connectivity')])
def test_invalid_assignment_is_rejected_without_report(package, change, reason):
    root, stream = package
    text = stream.read_text()
    if change == 'version':
        text = text.replace('version 5.0', 'version 4.6')
    elif change == 'charge':
        text = text.replace('1.50', '1.60', 1)
    else:
        text = text.replace('BOND P1   O1', 'BOND P1   C1', 1)
    stream.write_text(text)
    with pytest.raises(ValueError, match=reason):
        audit(root, stream, root / 'audit.json')
    assert not (root / 'audit.json').exists()
