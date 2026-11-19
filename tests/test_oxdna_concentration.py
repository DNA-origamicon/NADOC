"""Concentration changes box metadata only; never scale or rewrite particle rows."""
import math
import pytest
from backend.core.oxdna_concentration import apply_concentration, box_edge_nm, configuration_box


def fixture_files(tmp_path):
    # Minimal numerical simulation-file fixture, not an authored NADOC document.
    (tmp_path/'topology.top').write_text('4 2\n1 A 1 -1\n1 T -1 0\n2 A 3 -1\n2 T -1 2\n')
    (tmp_path/'conf.dat').write_text('t = 0\nb = 58.699225 58.699225 58.699225\nE = 0 0 0\n' +
        '\n'.join(f'{i/2} 0 0 1 0 0 0 0 1 0 0 0 0 0 0' for i in range(4))+'\n')
    return tmp_path


def test_molarity_convention_and_coordinates(tmp_path):
    path=fixture_files(tmp_path); original=(path/'conf.dat').read_text().splitlines()
    config={};r=apply_concentration(path,config,12000)
    assert r['dna_strands']==2
    assert r['concentration_uM']==pytest.approx(12000)
    assert r['box_nm']==pytest.approx([6.5167733353]*3,abs=.0001)
    changed=(path/'conf.dat').read_text().splitlines()
    assert changed[:1]+changed[2:]==original[:1]+original[2:]
    assert config['dna_concentration_uM']==12000
    # Save/reopen/continuation inherits actual box even without a new override.
    assert configuration_box(path)[1]['concentration_uM']==pytest.approx(12000)
    inherited={};apply_concentration(path,inherited)
    assert (path/'conf.dat').read_text().splitlines()==changed


@pytest.mark.parametrize('value',[0,-1,math.inf,math.nan,1e9])
def test_bad_or_too_small_box_leaves_inputs_unchanged(tmp_path,value):
    path=fixture_files(tmp_path);before=(path/'conf.dat').read_bytes();config={}
    with pytest.raises(ValueError):apply_concentration(path,config,value)
    assert (path/'conf.dat').read_bytes()==before
    assert config=={}


def test_default_box_and_strand_not_nucleotide_count(tmp_path):
    path=fixture_files(tmp_path)
    assert configuration_box(path)[1]['concentration_uM']==pytest.approx(26.5686,abs=.0001)
    assert box_edge_nm(16,12000)==pytest.approx(2*box_edge_nm(2,12000))


def test_api_rejects_infinite_concentration():
    from pydantic import ValidationError
    from backend.api.routes_oxdna import RunRequest,CreateOxdnaJobRequest
    for cls in [RunRequest,CreateOxdnaJobRequest]:
        for value in [0,-1,float('inf'),float('nan')]:
            with pytest.raises(ValidationError):cls(dna_concentration_uM=value)


def test_protein_and_peg_do_not_count_as_dna_strands(tmp_path):
    path=fixture_files(tmp_path)
    # DNANM proteins have negative strand IDs; PEG has a numerical bead type.
    with (path/'topology.top').open('a') as f:
        f.write('-1 A -1 0\n-2 N -1 1\n3 100 -1 -1\n')
    assert configuration_box(path)[1]['dna_strands']==2


def test_resize_refuses_periodic_spanning_start_without_moving_it(tmp_path):
    path=fixture_files(tmp_path)
    text=(path/'conf.dat').read_text().replace('1.5 0 0','58 0 0')
    (path/'conf.dat').write_text(text)
    with pytest.raises(ValueError,match='periodic box boundary'):
        apply_concentration(path,{},.1)
    assert (path/'conf.dat').read_text()==text
