"""The menu atlas must retain readable failure evidence and expose its limits."""

import json

from PIL import Image

from tools.vr_workflows.menu_render_audit import report
from tools.vr_workflows.tour_catalog import arguments, catalog


def test_atlas_preserves_failed_and_uninstrumented_states(tmp_path):
    rows = [
        dict(name="legacy-overlap", image="overlap.png", layout="invalid", layout_detail="text-overlap", texts=[]),
        dict(name="radial-hover", image="radial.png", layout="not-instrumented", layout_detail="", texts=[]),
    ]
    (tmp_path / "states.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
    for row in rows:
        Image.new("RGB", (120, 120), "#6688aa").save(tmp_path / row["image"])
    result = report(tmp_path)
    assert not result["passed"] and result["rendered_states"] == 2
    assert result["layout_failures"][0]["name"] == "legacy-overlap"
    assert result["uninstrumented_states"] == ["radial-hover"]
    assert (tmp_path / result["contact_sheets"][0]).is_file()
    assert 'href="overlap.png"' in (tmp_path / "index.html").read_text()
    assert (tmp_path / "overlap.png").is_file()


def test_atlas_empty_or_missing_capture_cannot_pass(tmp_path):
    assert not report(tmp_path)["passed"]
    row = dict(name="missing", image="missing.png", layout="valid", layout_detail="", texts=[])
    (tmp_path / "states.jsonl").write_text(json.dumps(row))
    result = report(tmp_path)
    assert not result["passed"] and result["missing_images"] == ["missing.png"]


def test_menu_atlas_registered_as_offscreen_workflow():
    tour = next(row for row in catalog()["tours"] if row["id"] == "menu-formatting")
    assert tour["group"] == "interaction"
    assert arguments(tour, True) == ["-m", "tools.vr_workflows.menu_render_audit", "--validate"]


def test_atlas_partial_or_blank_render_fails_after_retaining_report(tmp_path):
    row = dict(name="menu", image="menu.png", layout="valid", layout_detail="", texts=[], pixels_visible=True)
    (tmp_path / "states.jsonl").write_text(json.dumps(row))
    Image.new("RGB", (120, 120), "#6688aa").save(tmp_path / "menu.png")
    assert not report(tmp_path)["passed"]
    (tmp_path / "render-complete.json").write_text(json.dumps(dict(complete=True, rendered_states=1)))
    assert report(tmp_path)["passed"]
    assert not report(tmp_path, renderer_exit_code=1)["passed"]
    row["pixels_visible"] = False
    (tmp_path / "states.jsonl").write_text(json.dumps(row))
    result = report(tmp_path)
    assert not result["passed"] and result["pixel_failures"] == ["menu"]
    assert (tmp_path / "index.html").is_file() and (tmp_path / "menu.png").is_file()
