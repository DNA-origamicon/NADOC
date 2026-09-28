"""Dimensions share a document with desktop, and VR journals cannot cross documents."""
import json
import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.api import state, assembly_state
from backend.api.main import app
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.api.vr_dimensions import DimensionBinding
from backend.core.models import Design, Assembly
from backend.core.dimensions import Dimension
from backend.core.assembly_polymer import _design_dump_for_identity
from backend.core.atomistic import atomistic_reference_topology_hash


def entry(id='m1', **kw):
    return dict(id=id,name='Dimension 1',a=[1,2,3],b=[4,6,3],visible=True,**kw)


@pytest.fixture(autouse=True)
def isolated():
    token=set_current_doc('__test_dimensions__')
    state.set_design(Design())
    assembly_state.set_assembly(Assembly())
    yield
    state.drop_doc('__test_dimensions__')
    assembly_state.drop_doc('__test_dimensions__')
    reset_current_doc(token)


@pytest.mark.parametrize('kind,model,module',[('design',Design,state),('assembly',Assembly,assembly_state)])
def test_save_file_roundtrip_and_mutations(kind,model,module):
    client=TestClient(app,headers={'X-NADOC-Doc':'__test_dimensions__'})
    document=module.get_or_404()
    url=f'/api/{kind}/dimensions'
    result=client.patch(url,json={'document_id':document.id,'upsert':[entry()]} )
    assert result.status_code==200, result.text
    saved=model.from_json(module.get_or_404().to_json())
    assert saved.dimensions[0].a==(1,2,3)
    assert saved.dimensions[0].b==(4,6,3)
    assert saved.dimensions[0].visible
    assert model.model_validate({}).dimensions==[]
    wrong=client.patch(url,json={'document_id':'other','delete':['m1']})
    assert wrong.status_code==409
    hidden=entry();hidden['visible']=False
    assert client.patch(url,json={'document_id':document.id,'upsert':[hidden]}).json()['dimensions'][0]['visible'] is False
    assert client.patch(url,json={'document_id':document.id,'delete':['m1']}).json()['dimensions']==[]


def test_native_journal_rotation_ack_replay_and_document_binding(tmp_path):
    document=state.get_or_404()
    document.dimensions=[Dimension(**entry('desktop'))]
    rotation=np.array([[0,0,1],[0,1,0],[-1,0,0]],float)
    binding=DimensionBinding(tmp_path/'event','design',rotation)
    assert 'desktop' in (tmp_path/'event.dimensions-seed').read_text()
    native=entry('vr_test');native['a']=(rotation@native['a']).tolist();native['b']=(rotation@native['b']).tolist()
    path=tmp_path/'event.dimensions-pending'
    path.write_text(json.dumps([{'sequence':1,'upsert':native}]))
    token=set_current_doc('other-tab')
    try: binding.consume()
    finally: reset_current_doc(token)
    assert len(document.dimensions)==2
    assert document.dimensions[-1].a==tuple(entry()['a'])
    revision=state.revision();binding.consume();assert state.revision()==revision
    assert (tmp_path/'event.dimensions-ack').read_text()=='1'
    path.write_text(json.dumps([{'sequence':1,'upsert':native},{'sequence':2,'delete':'vr_test'}]))
    binding.consume();assert [d.id for d in document.dimensions]==['desktop']
    state.set_design(Design())
    path.write_text(json.dumps([{'sequence':3,'upsert':native}]))
    with pytest.raises(HTTPException): binding.consume()
    assert not state.get_or_404().dimensions


def test_dimensions_do_not_change_geometry_identity():
    design=Design()
    identity=_design_dump_for_identity(design)
    topology=atomistic_reference_topology_hash(design)
    design.dimensions=[Dimension(**entry())]
    assert _design_dump_for_identity(design)==identity
    assert atomistic_reference_topology_hash(design)==topology


def test_invalid_coordinates_rejected_atomically():
    client=TestClient(app,headers={'X-NADOC-Doc':'__test_dimensions__'})
    data=entry();data['a']=[1e30,2,3]
    result=client.patch('/api/design/dimensions',json={'document_id':state.get_or_404().id,'upsert':[data]})
    assert result.status_code==422
    assert not state.get_or_404().dimensions
