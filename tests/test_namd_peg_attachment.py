from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api import state
from backend.core.models import Design


def test_coating_and_visibility_persist_and_can_be_removed_without_topology_changes():
    from fastapi import HTTPException
    try:
        previous=state.get_or_404()
    except HTTPException:
        previous=None
    try:
        state.set_design(Design())
        client=TestClient(app)
        record={'id':'surface1','spec':{'name':'coating'},'preview':{'graft_sites_nm':[[1,2,3]]}}
        response=client.put('/api/design/metadata',json={'namd_peg_coating':record,'namd_peg_visible':False})
        assert response.status_code==200
        design=Design.model_validate(response.json()['design'])
        restored=Design.model_validate_json(design.model_dump_json())
        assert restored.metadata.namd_peg_coating==record
        assert restored.metadata.namd_peg_visible is False
        assert not restored.helices
        response=client.put('/api/design/metadata',json={'namd_peg_coating':None})
        assert response.status_code==200
        assert response.json()['design']['metadata']['namd_peg_coating'] is None
        assert response.json()['design']['metadata']['namd_peg_visible'] is False
    finally:
        state.set_design(previous)


def test_explicit_wizard_salt_survives_backend_preset_defaults():
    from backend.api.routes_md import CreateJobRequest,_apply_relax_preset
    for preset in ['literature','design_speed']:
        body=CreateJobRequest(relax_preset=preset,graphene_nanopore=True,graphene_only=True,
            graphene_pore_diameter_nm=0,graphene_charge_density_C_m2=-.02,
            salt_mode='custom',ion_conc_mM=175,mg_conc_mM=0)
        effective=_apply_relax_preset(body)
        assert (effective.salt_mode,effective.ion_conc_mM,effective.mg_conc_mM)==('custom',175,0)
