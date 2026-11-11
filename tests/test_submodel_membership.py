import json
import pytest
from backend.core.submodel_membership import membership, namd_membership, oxdna_membership


def test_membership_preserves_support_and_synthetic_identities(tmp_path):
    keys = [['h',0,'FORWARD',0], ['h',0,'FORWARD',1], ['__xb__','cross',0], ['__ext_e',2,'REVERSE']]
    (tmp_path/'submodel_plan.json').write_text(json.dumps(dict(source_keys=keys, retained_source_indices=[1,2,3])))
    result = oxdna_membership(tmp_path)
    assert result['omitted_keys'] == ['h:0:FORWARD']
    assert result['retained_keys'] == ['__ext_e:2:REVERSE','__xb__:cross:0','h:0:FORWARD:1']
    with pytest.raises(ValueError): membership(keys,[4])


def test_namd_uses_saved_residues_not_current_coordinates(tmp_path,monkeypatch):
    from backend.core import atomistic_to_nadoc as mapping
    (tmp_path/'submodel.json').write_text(json.dumps(dict(source_residues=[['D000','1'],['D000','2'],['D000','3']],retained_residues=[['D000','1'],['D000','3']])))
    monkeypatch.setattr(mapping,'load_segid_chain_map',lambda p:{'D000':'A'})
    monkeypatch.setattr(mapping,'build_namd_coarse_reference',lambda *a,**k:({('A',i):('h',i,'FORWARD') for i in range(1,4)},{}))
    assert namd_membership(tmp_path,object())['omitted_keys'] == ['h:2:FORWARD']


def test_missing_preparation_has_no_guessed_mask(tmp_path):
    assert namd_membership(tmp_path,None)['ready'] is False
    assert oxdna_membership(tmp_path)['ready'] is False


def test_namd_synthetic_residues_use_atom_identity_fallback(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from backend.core import atomistic_to_nadoc as mapping, atomistic
    (tmp_path/'submodel.json').write_text(json.dumps(dict(source_residues=[['D000','1'],['D000','2']], retained_residues=[['D000','2']])))
    monkeypatch.setattr(mapping,'load_segid_chain_map',lambda p:{'D000':'A'})
    monkeypatch.setattr(mapping,'build_namd_coarse_reference',lambda *a,**k:({('A',1):('h',1,'FORWARD')},{}))
    atoms=[SimpleNamespace(chain_id='A',seq_num=1,helix_id='h',bp_index=1,direction='FORWARD'),
           SimpleNamespace(chain_id='A',seq_num=2,extension_id='tail',ext_k=0,direction='FORWARD')]
    monkeypatch.setattr(atomistic,'build_atomistic_model',lambda d:SimpleNamespace(atoms=atoms))
    result=namd_membership(tmp_path,object())
    assert result['retained_keys']==['__ext_tail:0:FORWARD']
    assert result['omitted_keys']==['h:1:FORWARD']
