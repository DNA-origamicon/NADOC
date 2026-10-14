"""Completed HF evidence must remain pinned when a failed allocation resumes."""
import json
import pytest

from experiments.cpd_anti_additive.corrected_core_stage1 import pin
from experiments.cpd_anti_additive.corrected_electrostatic_pilot_v2 import reused_result
from tests.test_cpd_electrostatic_native import TEXT,X


def fixture(tmp_path):
    old=tmp_path/'original';old.mkdir();new=tmp_path/'recovery';new.mkdir()
    taskdir=new/'water-df';taskdir.mkdir()
    inp=old/'input.json';inp.write_text(json.dumps(dict(elements=['O','H','H'],geometry_angstrom=X.tolist(),options={'scf_type':'df'})))
    native=old/'output.dat';native.write_text(TEXT)
    geometry=old/'geometry.npy';geometry.write_bytes(b'representative pinned geometry artifact')
    data=dict(input=pin(inp),native=pin(native),energy_hartree=-76.,dipole_au=[.2,.3,0.],returned_geometry=pin(geometry),grid=None)
    result=old/'result.json';result.write_text(json.dumps(data));(taskdir/'result.json').write_bytes(result.read_bytes())
    task=dict(label='water-df',input=pin(inp));plan=dict(reused_results={'water-df':pin(result)})
    return new,task,plan,old


def test_reuse_exact_evidence_and_skip_only_declared_tasks(tmp_path):
    root,task,plan,_=fixture(tmp_path)
    assert reused_result(root,task,plan)==pin(root/'water-df/result.json')
    assert reused_result(root,dict(label='1-O2-direct'),plan) is None


def test_reject_changed_copied_result(tmp_path):
    root,task,plan,_=fixture(tmp_path)
    (root/'water-df/result.json').write_text('{}')
    with pytest.raises(ValueError,match='Reused result changed'):
        reused_result(root,task,plan)


def test_reject_different_input_even_if_results_are_present(tmp_path):
    root,task,plan,_=fixture(tmp_path)
    task['input']={**task['input'],'sha256':'wrong'}
    with pytest.raises(ValueError,match='Reused input changed'):
        reused_result(root,task,plan)


def test_reject_modified_native_source(tmp_path):
    root,task,plan,old=fixture(tmp_path)
    (old/'output.dat').write_text(TEXT.replace('-76.000','-75.000'))
    with pytest.raises(ValueError):
        reused_result(root,task,plan)


def test_reject_modified_original_result(tmp_path):
    root,task,plan,old=fixture(tmp_path)
    (old/'result.json').write_text('{}')
    with pytest.raises(ValueError):
        reused_result(root,task,plan)
