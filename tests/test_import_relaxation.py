"""Real caDNAno/scadnano import options and preserved image-import artifacts."""

import json
import pytest
from backend.api import state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.api.crud import (
    CadnanoImportRequest,
    ScadnanoImportRequest,
    import_cadnano_design,
    import_scadnano_design,
)
from backend.core.scadnano import import_scadnano
from backend.core.cadnano import export_cadnano
from backend.core.models import Design


def source():
    return {
        "version": "0.19.0",
        "grid": "square",
        "helices": [
            {"grid_position": [0, 0], "max_offset": 32},
            {"grid_position": [9, 0], "max_offset": 32},
        ],
        "strands": [
            {
                "is_scaffold": True,
                "domains": [
                    {"helix": 0, "forward": True, "start": 0, "end": 32},
                    {"helix": 1, "forward": False, "start": 0, "end": 32},
                ],
            }
        ],
    }


def cadnano_source():
    return export_cadnano(import_scadnano(source())[0])


@pytest.fixture
def session():
    token = set_current_doc("import-relaxation-test")
    try:
        yield
    finally:
        state.close_session()
        reset_current_doc(token)


@pytest.mark.parametrize("format", ["cadnano", "scadnano"])
@pytest.mark.parametrize("enabled", [False, True])
def test_import_option_is_explicit_and_applies_real_fit(
    session, monkeypatch, format, enabled
):
    from backend.core import import_relaxation

    fitted_geometry = []
    if enabled and format == "scadnano":
        from backend.core.design_geometry import _geometry_for_design
        original_fit = import_relaxation.relax_origami
        def observe_fit(design):
            candidate, report = original_fit(design)
            fitted_geometry.extend(_geometry_for_design(candidate))
            return candidate, report
        monkeypatch.setattr(import_relaxation, "relax_origami", observe_fit)
    if not enabled:

        def forbidden(*args, **kwargs):
            raise AssertionError("Default imports must not run the solver")

        monkeypatch.setattr(import_relaxation, "relax_origami", forbidden)
    fn, request, data = (
        (import_cadnano_design, CadnanoImportRequest, cadnano_source())
        if format == "cadnano"
        else (import_scadnano_design, ScadnanoImportRequest, source())
    )
    response = fn(request(content=json.dumps(data), relax_origami=enabled))
    assert len(state.get_or_404().helices) == 2
    if enabled:
        report = response["relaxation"]
        assert report["status"] == "applied"
        assert report["rigid_bundle_sizes"] == [1, 1]
        assert report["after"]["max_excess_nm"] < report["before"]["max_excess_nm"]
        assert report["clashes"]["after"]["overlapping_body_pairs"] == 0
    else:
        assert "relaxation" not in response
    if format == "scadnano":
        from scripts.agent_structure_guard import audit
        reopened = Design.model_validate_json(state.get_or_404().model_dump_json())
        audit(reopened)
        assert reopened.feature_log[0].op_kind == "scadnano-import"
        assert len(reopened.feature_log) > 1 if enabled else len(reopened.feature_log) == 1
        if enabled:
            import numpy as np
            actual = _geometry_for_design(reopened)
            assert len(actual) == len(fitted_geometry)
            assert np.allclose([r["backbone_position"] for r in actual],
                               [r["backbone_position"] for r in fitted_geometry], atol=1e-10, rtol=0)


@pytest.mark.parametrize("format", ["cadnano", "scadnano"])
def test_unsupported_relaxation_keeps_valid_import(session, monkeypatch, format):
    from backend.core import import_relaxation

    def unsupported(*args, **kwargs):
        raise ValueError("Unsupported layout for relaxation")

    monkeypatch.setattr(import_relaxation, "relax_origami", unsupported)
    fn, request, data = (
        (import_cadnano_design, CadnanoImportRequest, cadnano_source())
        if format == "cadnano"
        else (import_scadnano_design, ScadnanoImportRequest, source())
    )
    response = fn(request(content=json.dumps(data), relax_origami=True))
    assert response["relaxation"]["status"] == "skipped"
    assert any("Unsupported layout" in w for w in response["import_warnings"])
    assert len(state.get_or_404().helices) == 2


def test_image_workflow_preserves_original_and_refuses_overwrite(tmp_path):
    from tools.design_archive.relax_image_import import write_relaxed_image_import

    report = write_relaxed_image_import(cadnano_source(), tmp_path)
    assert report["status"] == "applied"
    original = Design.model_validate_json(
        (tmp_path / "image_imported.nadoc").read_text()
    )
    relaxed = Design.model_validate_json((tmp_path / "image_relaxed.nadoc").read_text())
    assert original.id != relaxed.id
    for field in ("helices", "strands", "crossovers", "forced_ligations"):
        assert getattr(original, field) == getattr(relaxed, field)
    assert (
        json.loads((tmp_path / "image_relaxation.json").read_text())["relaxation"]
        == report
    )
    before = (tmp_path / "image_relaxed.nadoc").read_bytes()
    with pytest.raises(FileExistsError):
        write_relaxed_image_import(cadnano_source(), tmp_path)
    assert (tmp_path / "image_relaxed.nadoc").read_bytes() == before


def test_image_workflow_retains_import_when_solver_skips(tmp_path, monkeypatch):
    from tools.design_archive.relax_image_import import write_relaxed_image_import
    from backend.core import import_relaxation

    def unsupported(*args, **kwargs):
        raise ValueError("Only one rigid cluster")

    monkeypatch.setattr(import_relaxation, "relax_origami", unsupported)
    assert write_relaxed_image_import(cadnano_source(), tmp_path)["status"] == "skipped"
    assert (tmp_path / "image_imported.nadoc").exists()
    assert not (tmp_path / "image_relaxed.nadoc").exists()


def test_recorded_import_fit_failure_keeps_active_document(session, monkeypatch):
    from backend.api import headless_build
    from fastapi import HTTPException

    initial = import_scadnano_design(ScadnanoImportRequest(content=json.dumps(source())))
    before = state.get_or_404().model_dump_json()
    def refuse(*args, **kwargs):
        raise HTTPException(409, detail="controlled group publication failure")
    monkeypatch.setattr(headless_build, "transform_cluster", refuse)
    with pytest.raises(HTTPException, match="controlled group publication failure"):
        import_scadnano_design(ScadnanoImportRequest(content=json.dumps(source()), relax_origami=True))
    assert state.get_or_404().id == initial["design"]["id"]
    assert state.get_or_404().model_dump_json() == before


def test_manual_relaxation_on_import_keeps_replay_and_single_undo(session):
    from backend.api.routes_origami_relax import relax
    from scripts.agent_structure_guard import audit

    import_scadnano_design(ScadnanoImportRequest(content=json.dumps(source())))
    before = state.get_or_404().model_dump_json()
    depth = state.undo_depth()
    response = relax()
    assert response["relaxation"]["after"]["max_excess_nm"] < response["relaxation"]["before"]["max_excess_nm"]
    after = state.get_or_404().model_dump_json()
    audit(Design.model_validate_json(after))
    assert state.undo_depth() == depth + 1
    state.undo()
    assert state.get_or_404().model_dump_json() == before
    state.redo()
    assert state.get_or_404().model_dump_json() == after
