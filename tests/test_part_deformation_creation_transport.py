"""Real creation HTTP packets satisfy the browser's closed display contract.

Tiny native recipes travel through stdin; no browser, capture files or saved user
documents are created. The ordinary history packet grammar remains separate.
"""

import json
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest

from backend.api import part_group_organization_gate as gate, part_publication_policy as policy, state
from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import Design
from backend.core.part_history_contract import assess_part_history
from tests.test_named_deformation_preview import named_source
from tests.test_part_deformation_preview import native_source, patch
from tests.test_part_deformation_preview_routes import PATH, client as client, routes
from tests.test_part_deformation_preview_sessions import (
    cancellation, checkpoint, document as document, opening, unchanged, update,
)


@pytest.mark.parametrize("kind", ["bend", "twist"])
@pytest.mark.parametrize("selection", ["whole", "placement", "named_mixed"])
def test_actual_creation_http_display_receipt_reload_and_undo(client, monkeypatch, kind, selection):
    http, headers, _ = client
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", True)
    source = named_source(kind) if selection == "named_mixed" else native_source(kind, grouped=True)
    state.load_design(source)
    targets = None
    cluster_ids = [source.cluster_transforms[-1].id] if selection == "placement" else []
    if selection == "named_mixed":
        targets = [{"kind": "part_group", "id": "other"},
                   {"kind": "domain", "strand_id": source.strands[0].id, "domain_index": 0}]
    before = checkpoint()
    request = {**opening(feature_id=str(uuid4())), "mode": "create", "type": kind,
               "targets": targets, "cluster_ids": cluster_ids}
    prepared_response = http.post(PATH + "/create", headers=headers, json=request)
    assert prepared_response.status_code == 200, prepared_response.text
    prepared = prepared_response.json()
    assert prepared["candidate"] is None
    assert prepared["control_context"]["selected_operation"] is None
    assert prepared["awaiting_parameters"] is True
    draft = {key: value for key, value in patch(kind).items() if key != "type"}
    evaluated_response = http.post(PATH + "/evaluate", headers=headers,
                                   json=update(prepared, params=draft))
    assert evaluated_response.status_code == 200, evaluated_response.text
    evaluated = evaluated_response.json()
    feedback_response = http.post(PATH + "/evaluate", headers=headers,
                                  json={**update(prepared, sequence=2, params=draft), "include_geometry": False})
    assert feedback_response.status_code == 200, feedback_response.text
    feedback = feedback_response.json()
    assert evaluated["candidate"] is not None and feedback["candidate"] is None
    assert evaluated["selected_scope"] == feedback["selected_scope"]
    unchanged(before)
    response = http.post(PATH + "/apply", headers=headers,
                         json=update(prepared, sequence=3, params=draft))
    assert response.status_code == 200, response.text
    receipt = response.json()
    status = http.post(PATH + "/status", headers=headers, json=cancellation(prepared))
    assert status.status_code == 200, status.text
    checked = subprocess.run(["node", "--input-type=module", "-e", """
        import { validateDeformationPreviewDisplay } from './frontend/src/features/deformation_preview_display.js';
        import { previewPublicationReceipt } from './frontend/src/api/deformation_preview_endpoints.js';
        let input = ''; for await (const chunk of process.stdin) input += chunk;
        const { prepared, evaluated, feedback, receipt, status, context } = JSON.parse(input);
        validateDeformationPreviewDisplay(prepared, { prepare: true, requireEnvelope: true });
        for (const packet of [evaluated, feedback]) {
          validateDeformationPreviewDisplay(packet, { prepare: false, requireEnvelope: true });
        }
        const accepted = previewPublicationReceipt(receipt, context);
        previewPublicationReceipt(status, context, accepted);
        process.stdout.write(JSON.stringify({ feature_id: accepted.feature_id, checked: 5 }));
    """], input=json.dumps({"prepared": prepared, "evaluated": evaluated, "feedback": feedback,
        "receipt": receipt, "status": status.json(), "context": {
            "docId": headers["X-NADOC-Doc"], "designId": source.id,
            "revision": before["revision"], "loadoutId": None}}), text=True, capture_output=True,
        timeout=5, cwd=Path(__file__).resolve().parents[1])
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout) == {"feature_id": request["feature_id"], "checked": 5}
    current = state.get_or_404()
    assert len(current.feature_log) == len(source.feature_log) + 1
    assert current.feature_log[-1].id == request["feature_id"]
    assert current.deformations[-1].id == receipt["deformation_id"]
    assert current.deformations[-1].targets == targets
    assert current.deformations[-1].cluster_ids == cluster_ids
    assert state.undo_depth() == len(before["history"]) + 1
    loaded = Design.model_validate_json(current.model_dump_json())
    proof = assess_part_history(loaded, execute=execute, dependencies=dependencies)
    assert proof["status"] == "verified", proof
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["json"]


@pytest.mark.parametrize("strict", [False, True])
def test_creation_gate_refuses_before_body_or_host(client, monkeypatch, strict):
    http, headers, host = client
    before = checkpoint()
    if strict:
        monkeypatch.setattr(policy, "_configuration",
                            (policy.HostPolicyConfiguration(default_mode="registered_only"), 73))
    else:
        monkeypatch.setattr(routes(), "DEFORMATION_PREVIEW_ENABLED", False)
    monkeypatch.setattr(host, "prepare_create", lambda *_a: pytest.fail("Closed creation route reached host"))
    response = http.post(PATH + "/create", headers={**headers, "Content-Type": "application/json"},
                         content=b"not JSON")
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == ("construction_policy" if strict else "preview_disabled")
    unchanged(before)
