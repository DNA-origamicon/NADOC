"""Production routing/policy boundary, without starting application services."""

from uuid import uuid4

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest
from starlette.routing import Match

from backend.api import main, part_publication_policy as policy, state
from backend.api import routes_part_deformation_preview as preview


PATH = "/api/design/features/deformation-preview"
ENDPOINTS = (
    ("", preview.prepare),
    ("/create", preview.create),
    ("/evaluate", preview.evaluate),
    ("/apply", preview.apply),
    ("/cancel", preview.cancel),
    ("/status", preview.status),
)


@pytest.fixture
def boundary(monkeypatch):
    previous = policy.current_configuration()
    identity = f"preview-registration-{uuid4()}"

    def forbidden(*args, **kwargs):
        pytest.fail("Refused production request reached body/native work")

    monkeypatch.setattr(preview, "_read_request", forbidden)
    monkeypatch.setattr(preview, "_respond", forbidden)
    # Deliberately do not enter TestClient: its context manager starts the real
    # lifespan (autosave, job supervision, CUDA, RunPod). Requests still traverse
    # the actual production router and middleware; no substitute app is built.
    http = TestClient(main.app)
    try:
        yield http, identity
    finally:
        http.close()
        state.configure_part_publication_policy(previous)
        assert identity not in state._sessions


@pytest.mark.parametrize("suffix,endpoint", ENDPOINTS)
def test_production_registration_has_one_unshadowed_post(suffix, endpoint):
    scope = {"type": "http", "method": "POST", "path": PATH + suffix}
    matches = [route for route in main.app.routes
               if isinstance(route, APIRoute) and route.matches(scope)[0] == Match.FULL]
    assert len(matches) == 1
    assert matches[0].endpoint is endpoint
    assert matches[0].methods == {"POST"}


def test_production_route_is_enabled():
    assert preview.DEFORMATION_PREVIEW_ENABLED is True


@pytest.mark.parametrize("suffix,endpoint", ENDPOINTS)
def test_disabled_gate_refuses_before_body_or_native(boundary, monkeypatch, suffix, endpoint):
    http, identity = boundary
    monkeypatch.setattr(preview, "DEFORMATION_PREVIEW_ENABLED", False)
    state.configure_part_publication_policy(policy.HostPolicyConfiguration())
    response = http.post(PATH + suffix, headers={"X-NADOC-Doc": identity}, content=b"not JSON")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "preview_disabled"


@pytest.mark.parametrize("suffix,endpoint", ENDPOINTS)
@pytest.mark.parametrize("binding", ["host", "document"])
def test_production_strict_refuses_even_with_local_preview_enabled(
    boundary, monkeypatch, suffix, endpoint, binding,
):
    http, identity = boundary
    monkeypatch.setattr(preview, "DEFORMATION_PREVIEW_ENABLED", True)
    configuration = (policy.HostPolicyConfiguration(default_mode="registered_only")
                     if binding == "host" else policy.HostPolicyConfiguration(
                         document_modes={identity: "registered_only"}))
    state.configure_part_publication_policy(configuration)
    response = http.post(PATH + suffix, headers={"X-NADOC-Doc": identity}, content=b"not JSON")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "construction_policy"
