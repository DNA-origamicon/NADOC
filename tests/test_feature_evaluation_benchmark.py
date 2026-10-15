"""A/B renderer adapter must retain the independent reconstruction oracle."""
import os

from backend.api import routes_feature_log as routes
from backend.core.lattice import make_bundle_design
from scripts import benchmark_feature_evaluation as benchmark


def test_current_response_contract_matches_for_independent_engines(monkeypatch):
    design = make_bundle_design([(0, 0)], length_bp=8)
    monkeypatch.setattr(routes.design_state, "get_or_404", lambda: design)
    body = routes.GeometryBatchBody(positions=[-1])
    before = design.model_dump()
    original_engine = routes._seek_feature_log
    original_mode = os.environ.get("NADOC_FEATURE_EVALUATION")
    baseline = benchmark.render_with_evaluator(routes, "geometry_batch", body, False)
    candidate = benchmark.render_with_evaluator(routes, "geometry_batch", body, True)
    assert baseline == candidate
    assert {"display_design", "cluster_transforms", "nucleotides_compact", "helix_axes"} <= baseline["-1"].keys()
    assert routes._seek_feature_log is original_engine
    assert os.environ.get("NADOC_FEATURE_EVALUATION") == original_mode
    assert design.model_dump() == before


def test_adapter_exposes_different_reconstructed_state(monkeypatch):
    design = make_bundle_design([(0, 0)], length_bp=8)
    monkeypatch.setattr(routes.design_state, "get_or_404", lambda: design)
    def altered_reference(source, position):
        copy = source.model_copy(deep=True)
        copy.metadata.name = "Independent reference difference"
        return copy
    monkeypatch.setattr(benchmark.reference_evaluator, "_seek_feature_log", altered_reference)
    body = routes.GeometryBatchBody(positions=[-1])
    baseline = benchmark.render_with_evaluator(routes, "geometry_batch", body, False)
    candidate = benchmark.render_with_evaluator(routes, "geometry_batch", body, True)
    assert baseline != candidate
    assert baseline["-1"]["display_design"]["metadata"]["name"] == "Independent reference difference"
