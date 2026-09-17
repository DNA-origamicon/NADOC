import json
import numpy as np
import pytest
from backend.core.models import Design, Nanoparticle
from backend.core.streptavidin import build_streptavidin_coating
from backend.core.gold_strep_dna import build_dna, pocket_geometry
from backend.core.oxdna_job import new_oxdna_job
from backend.core.oxdna_protocol import OxdnaStageSpec
from backend.core.oxdna_runner import prepare_oxdna_job
from backend.api.crud import _geometry_for_design
from backend.core.constants import NM_TO_OXDNA


def coated_design(mode='adsorption'):
    p = Nanoparticle(diameter_nm=10, coating=build_streptavidin_coating(
        10, count_override=1, mode=mode))
    r, h, s = build_dna(p, 'ACGTACGTACGTACGT')
    p.biotin_dna = [r]
    return Design(nanoparticles=[p], helices=[h], strands=[s])


@pytest.mark.parametrize('mode', ['adsorption', 'biotin_tether'])
def test_coating_is_mobile_and_grafted_at_authored_pocket(tmp_path, mode):
    d = coated_design(mode)
    stage = OxdnaStageSpec('relax', 'md_relax', 'MD', 10, 'CUDA')
    job = new_oxdna_job('coated gold', [stage.to_status()])
    info = prepare_oxdna_job(d, _geometry_for_design(d), job, tmp_path, [stage])
    m = info['mobile_gold']
    assert m['n_cores'] == 1 and m['dna_count'] == 16
    assert len(m['coating']) == 4 and len(m['grafts']) == 1
    g = m['grafts'][0]
    p = d.nanoparticles[0]
    anchor, _ = pocket_geometry(p, p.biotin_dna[0].chain)
    np.testing.assert_allclose(g['site'], anchor*NM_TO_OXDNA, atol=1e-9)
    assert g['dna'] == 0 and g['length'] == 2*NM_TO_OXDNA
    assert g['gold_strep'] == 'rigid' and g['strep_biotin'] == 'permanent'
    assert stage.interaction == 'DNA2GOLD'
    assert 'COATING_V1 4' in (job.job_dir(tmp_path)/'mobile_gold.dat').read_text()


def test_missing_strand_is_rejected(tmp_path):
    d = coated_design()
    d.nanoparticles[0].biotin_dna[0].strand_id = 'missing'
    stage = OxdnaStageSpec('relax', 'md_relax', 'MD', 10, 'CUDA')
    job = new_oxdna_job('invalid', [stage.to_status()])
    with pytest.raises(ValueError, match='terminus'):
        prepare_oxdna_job(d, _geometry_for_design(d), job, tmp_path, [stage])


def test_job_api_routes_coated_dna_to_mobile_cuda(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.api import routes_oxdna, state, doc_context
    from backend.api.main import app
    monkeypatch.setattr(routes_oxdna, '_WORKSPACE_DIR', tmp_path)
    monkeypatch.setattr(routes_oxdna, 'find_oxdna', lambda: '/test/oxDNA')
    monkeypatch.setattr(routes_oxdna, 'oxdna_supports_cuda', lambda _: True)
    monkeypatch.setattr(routes_oxdna, 'oxdna_supports_physics_v3', lambda _: True)
    doc_context.set_current_doc(None)
    state.set_design(coated_design())
    try:
        result = TestClient(app).post('/api/oxdna/jobs', json=dict(
            mc_steps=100, md_relax_steps=100, equil_steps=100, autostart=False))
        assert result.status_code == 200, result.text
        assert result.json()['backend'] == 'CUDA'
        manifests = list(tmp_path.rglob('mobile_gold.json'))
        assert len(manifests) == 1
        assert len(json.loads(manifests[0].read_text())['coating']) == 4
    finally:
        state.close_session()
