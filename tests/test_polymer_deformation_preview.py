"""A routed periodic part must retain its native process through Bend creation."""
from uuid import uuid4
import pytest

from backend.api import headless_build as parts, part_deformation_preview as preview, state
from backend.api.routes_scaffold_routing import route_for_polymerization_endpoint
from backend.core.models import LatticeType
from backend.core.part_overlay_commands import command_input
from scripts.agent_structure_guard import audit


@pytest.mark.parametrize("length", [42, pytest.param(1236, marks=pytest.mark.slow)])
def test_periodic_prefix_can_prepare_evaluate_and_append_a_bend(length):
    with parts.scratch_session(LatticeType.HONEYCOMB):
        parts.create_bundle([[0,1],[1,1],[1,2],[1,3],[0,3],[0,2]], length, lattice=LatticeType.HONEYCOMB)
        parts.auto_scaffold()
        parts.full_autostaple()
        route_for_polymerization_endpoint()
        source = state.get_or_404().model_copy(deep=True)
    original = source.model_dump()
    clusters = [c.id for c in source.cluster_transforms]
    prepared = preview.prepare_creation_from_capture(source, feature_id=str(uuid4()),
        deformation_id=str(uuid4()), kind="bend",
        targets=[{"kind": "cluster", "id": cid} for cid in clusters], cluster_ids=clusters)
    seams = [f for f in source.forced_ligations if f.is_periodic_seam]
    span = sum(abs(f.three_prime_bp-f.five_prime_bp) for f in seams)/len(seams)
    patch = {
        "plane_a_bp": min(h.bp_start for h in source.helices),
        "plane_b_bp": max(h.bp_start+h.length_bp-1 for h in source.helices),
        "params": {"kind": "bend", "curvature_deg_per_bp": 360/(6*span),
                   "direction_deg": 0, "polymer_circle_count": 6},
    }
    if length == 1236:
        patch["params"].pop("polymer_circle_count")
        patch["params"]["curvature_deg_per_bp"] = 60.3229 / (patch["plane_b_bp"]-patch["plane_a_bp"])
    candidate = preview.evaluate(prepared, patch).design
    assert candidate.forced_ligations == source.forced_ligations
    result, _ = preview.prepare_creation_append(source, prepared, patch, lambda: None)
    assert [e.id for e in result.feature_log[:-1]] == [e.id for e in source.feature_log]
    assert [command_input(e) for e in result.feature_log[:-1]] == [command_input(e) for e in source.feature_log]
    assert len(result.deformations) == 1
    assert audit(result)["status"] == "verified"
    assert source.model_dump() == original
    if length == 1236:
        from backend.core.periodic_polymer import closure_residual
        angle, translation = closure_residual(result, 6)
        assert angle < .5 and translation < .5, (angle, translation)
