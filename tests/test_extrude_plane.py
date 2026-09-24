from backend.core.extrude_plane import resolve_extrude_plane, extrude_plane_record
from backend.core.models import Design, Helix, Vec3
from backend.core.vr_scene_contract import parse_scene_contract


def helix(name, end):
    return Helix(
        id=name,
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=end[0], y=end[1], z=end[2]),
        length_bp=21,
    )


def test_loaded_axis_and_source_precedence():
    for plane, axis in [("XY", (0, 0, 7)), ("XZ", (0, -7, 0)), ("YZ", (7, 0, 0))]:
        assert resolve_extrude_plane(Design(helices=[helix("imported", axis)])) == (
            plane,
            "geometry",
        )
        assert resolve_extrude_plane(
            Design(helices=[helix(f"h_{plane}_0_0", (1, 2, 3))])
        ) == (plane, "geometry")


def test_mixed_and_oblique_are_explicit_fallbacks():
    assert resolve_extrude_plane(
        Design(helices=[helix("a", (0, 0, 7)), helix("b", (7, 0, 0))]), "XZ"
    ) == ("XZ", "mixed")
    assert resolve_extrude_plane(Design(helices=[helix("a", (1, 2, 3))])) == (
        "XY",
        "unknown",
    )
    assert resolve_extrude_plane(Design(), "invalid") == ("XY", "empty")


def test_scene_metadata_survives_expanded_bundle_and_validates():
    from backend.api.routes_vr import _bundle_expanded_scene, _parse_tool_config

    scene = (
        "NADOCVR 13 full strand\n"
        + extrude_plane_record(Design(helices=[helix("x", (0, 7, 0))]))
        + "\nR full\n"
    )
    merged = _bundle_expanded_scene(scene, scene)
    assert merged.count("F XZ HONEYCOMB geometry") == 1
    from pathlib import Path

    fixture = Path("native/vr_viewer/examples/tool_scope_v12.nadocvr").read_text()
    upgraded = fixture.replace("NADOCVR 12", "NADOCVR 13", 1).splitlines()
    upgraded.insert(1, "F XZ HONEYCOMB geometry")
    assert parse_scene_contract("\n".join(upgraded)) == parse_scene_contract(fixture)
    draft = dict(
        mode="extrude",
        target_identity=None,
        target_kind="none",
        target_owner_tokens=[],
        length_bp=21,
        direction_sign=1,
        strand_filter="both",
        ligate_adjacent=True,
        footprint_state="unresolved",
        extrude_from="YZ",
    )
    assert _parse_tool_config(draft, 1)["extrude_from"] == "YZ"
    import pytest

    with pytest.raises(ValueError):
        _parse_tool_config(dict(draft, extrude_from="freeform"), 1)
