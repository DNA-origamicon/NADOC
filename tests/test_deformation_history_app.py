"""Boundary/recipe checks for S03; these are not browser acceptance."""

import pytest
from uuid import uuid4
from fastapi.testclient import TestClient

from tests.deformation_history_app import create_app, fixture
from tests.extrude_matrix_fixture import FAMILIES


@pytest.mark.parametrize("kind,count", [("bend", 1), ("twist", 1), ("bend-nick", 1), ("twist-nick", 1), ("bend-chain", 4), ("bend-sweep", 2), ("twist-sweep", 2), ("sweep-extrude", 5), ("sweep-independent", 4), ("sweep-start", 5), ("sweep-detached", 5), ("extrude-chain", 2),
                                        ("bend-limit", 16), ("bend-over-limit", 17),
                                        *[(kind, 8 if kind == "overhang-extrude" else 3) for kind in FAMILIES]])
def test_fixture_has_native_helices_and_independent_proof(kind, count):
    from backend.api.part_proof_commands import dependencies, execute
    from backend.core.part_history_contract import assess_part_history

    source = fixture(kind)
    assert len(source.helices) == count
    assert source.metadata.name.startswith("__e2e__")
    assert assess_part_history(source, execute=execute, dependencies=dependencies)["status"] == "verified"


def test_test_app_restores_gate_and_preserves_production_app():
    from backend.api import main, state, routes_part_deformation_preview as routes
    from backend.api import routes_part_sweep_preview as sweep_routes

    production_routes = tuple(main.app.routes)
    production_lifespan = main.app.router.lifespan_context
    assert routes.DEFORMATION_PREVIEW_ENABLED is False
    assert sweep_routes.SWEEP_PREVIEW_ENABLED is False
    headers = {"X-NADOC-Doc": "__e2e__history-bend"}
    with TestClient(create_app()) as client:
        assert routes.DEFORMATION_PREVIEW_ENABLED is True
        assert sweep_routes.SWEEP_PREVIEW_ENABLED is True
        assert client.post("/api/__e2e__/history/seed/bend", headers=headers).status_code == 200
        before = client.get("/api/__e2e__/history/checkpoint", headers=headers).json()
        assert len(before["redo"]) == 1
        assert client.get("/api/__e2e__/history/proof", headers=headers).json()["status"] == "verified"
        resources = client.get("/api/__e2e__/history/resources", headers=headers).json()
        assert resources["sessions"] == resources["document_sessions"] == 0
        assert client.get("/api/__e2e__/history/checkpoint", headers=headers).json() == before
        for endpoint in ("proof", "resources"):
            assert client.get(f"/api/__e2e__/history/{endpoint}",
                              headers={"X-NADOC-Doc": "ordinary"}).status_code == 403
        body = {"preview_id": str(uuid4()), "expected_design_id": before["design"]["id"],
                "expected_revision": before["revision"], "feature_id": "edited-feature"}
        opened = client.post("/api/design/features/deformation-preview", headers=headers, json=body)
        assert opened.status_code == 200, opened.text
        cancelled = client.post("/api/design/features/deformation-preview/cancel", headers=headers,
                                json={**body, "lease_id": opened.json()["lease_id"]})
        assert cancelled.status_code == 200
        assert client.get("/api/__e2e__/history/checkpoint", headers=headers).json() == before
        assert client.post("/api/__e2e__/history/seed/bend",
                           headers={"X-NADOC-Doc": "ordinary"}).status_code == 403
    assert routes.DEFORMATION_PREVIEW_ENABLED is False
    assert sweep_routes.SWEEP_PREVIEW_ENABLED is False
    assert headers["X-NADOC-Doc"] not in state._sessions
    assert tuple(main.app.routes) == production_routes
    assert main.app.router.lifespan_context is production_lifespan


def test_test_app_restores_gate_after_failure():
    from backend.api import routes_part_deformation_preview as routes
    from backend.api import routes_part_sweep_preview as sweep_routes

    with pytest.raises(RuntimeError, match="fixture failure"):
        with TestClient(create_app()):
            raise RuntimeError("fixture failure")
    assert routes.DEFORMATION_PREVIEW_ENABLED is False

    assert sweep_routes.SWEEP_PREVIEW_ENABLED is False


@pytest.mark.parametrize('fail', [False, True])
def test_sealed_mode_restores_policy_gates_and_preserves_dispatch(monkeypatch, fail):
    from backend.api import state, main, part_publication_policy as policy
    from backend.api import part_immutable_geometry_publication as gate
    from backend.api import routes_part_deformation_preview as preview
    from backend.api.part_immutable_revision import StrictPartRevision
    before_policy = policy.current_configuration()
    before_routes = tuple(main.app.routes)
    monkeypatch.setenv('NADOC_HISTORY_E2E_SEALED', '1')
    doc = '__e2e__history-bend'
    headers = {'X-NADOC-Doc': doc}
    def run():
        with TestClient(create_app()) as client:
            assert gate.ENABLED and preview.DEFORMATION_PREVIEW_ENABLED and policy.resolve(doc).strict
            assert client.post('/api/__e2e__/history/seed/bend', headers=headers).json()['sealed']
            assert type(state._sessions[doc].design) is StrictPartRevision
            checkpoint = client.get('/api/__e2e__/history/checkpoint', headers=headers).json()
            assert checkpoint['sealed'] and len(checkpoint['redo']) == 1
            assert client.get('/api/design', headers=headers).status_code == 200
            assert client.post('/api/design/clear', headers=headers).status_code == 403
            assert client.get('/api/__e2e__/history/checkpoint', headers={'X-NADOC-Doc': 'ordinary'}).status_code == 403
            assert tuple(main.app.routes) == before_routes
            if fail:
                raise RuntimeError('sealed test failure')
            assert client.delete('/api/__e2e__/history/close', headers=headers).status_code == 200
            assert doc not in state._sessions
    if fail:
        with pytest.raises(RuntimeError, match='sealed test failure'): run()
    else:
        run()
    assert not gate.ENABLED and not preview.DEFORMATION_PREVIEW_ENABLED
    assert policy.current_configuration() == before_policy and doc not in state._sessions


@pytest.mark.parametrize("kind", ["bend", "twist"])
def test_downstream_nick_fixture_cold_replay_identity(kind):
    from tests.deformation_history_app import cold_replay
    from tests.test_part_deformation_preview import authoring
    from backend.core.design_geometry import _geometry_for_design

    prefix, source = fixture(kind), fixture(f"{kind}-nick")
    assert len(source.strands) == len(prefix.strands) + 1
    from backend.core.models import Design
    source = Design.model_validate_json(source.model_dump_json())
    expected = cold_replay(source)
    assert authoring(source) == authoring(expected)
    assert _geometry_for_design(source) == _geometry_for_design(expected)
    assert source.feature_log[0].post_state_gz_b64 == "poisoned-after"
