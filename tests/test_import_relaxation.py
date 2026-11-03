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
