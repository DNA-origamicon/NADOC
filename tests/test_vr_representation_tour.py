from tools.vr_workflows.representation_tour import REPS, transitions
from tools.vr_workflows.tour_catalog import catalog, arguments


def test_every_supported_directed_transition_is_covered_once():
    from typing import get_args
    from backend.api.routes_vr import VRLaunchRequest

    assert set(REPS) == set(
        get_args(VRLaunchRequest.model_fields["representation"].annotation)
    )
    # Color masks use the native enum order; the API Literal only pins membership.
    from pathlib import Path
    import re

    header = (Path(__file__).resolve().parents[1] / "native/vr_viewer/src/representations.hpp").read_text()
    names = header.split("kRepresentationNames{", 1)[1].split("};", 1)[0]
    assert list(REPS) == re.findall(r'"([a-z-]+)"', names)
    pairs = transitions()
    assert len(pairs) == len(REPS)*(len(REPS)-1) and len(set(pairs)) == len(pairs)
    assert all(first[1] == second[0] for first, second in zip(pairs, pairs[1:]))
    for source in REPS:
        assert {target for start, target in pairs if start == source} == set(REPS) - {
            source
        }


def test_real_design_benchmark_registered_for_demo_and_validation():
    tour = next(t for t in catalog()["tours"] if t["id"] == "representations")
    assert tour["group"] == "right" and tour["runnable"]
    assert tour["title"] == "Visualization"
    assert arguments(tour, True) == [
        "-m",
        "tools.vr_workflows.representation_tour",
        "--validate",
    ]


def test_framing_rejects_empty_clipped_and_menu_obscured_design(tmp_path):
    import numpy as np
    import pytest
    from tools.vr_workflows.representation_tour import check_framing

    evidence = {'state': {'sidebars': [{'open': False}]}, 'eyes': [{'eye':'left','height':80,'width':100}]}
    pixels = np.zeros((80,100), dtype=np.uint8)
    pixels[20:50,20:40] = 1
    pixels[10:70,60:90] = 3
    path = tmp_path/'left.classes.u8'
    pixels.tofile(path)
    assert check_framing(evidence, tmp_path)['left']['menu_gap_px'] == 21
    for bad in ('empty', 'clipped', 'overlap'):
        changed = pixels.copy()
        if bad == 'empty': changed[changed == 1] = 0
        elif bad == 'clipped': changed[0:30,20:40] = 1
        else: changed[60:70,30:70] = 1
        changed.tofile(path)
        with pytest.raises(AssertionError): check_framing(evidence, tmp_path)


def test_fixed_color_preview_controls_are_disabled_and_unselected():
    import pytest
    from tools.vr_workflows.representation_tour import check_color_controls

    control = {"id": "repr-color-strand", "enabled": False, "active": False}
    evidence = {"state": {"representation": "mrdna-fine", "controls": [control]}}
    check_color_controls(evidence)
    control["active"] = True
    with pytest.raises(AssertionError):
        check_color_controls(evidence)
    control.update(enabled=True, active=True)
    evidence["state"]["representation"] = "vdw"
    check_color_controls(evidence)


def test_color_pixel_cycle_is_registered_without_replacing_full_matrix():
    tour = next(t for t in catalog()["tours"] if t["id"] == "representation-colors")
    assert tour["group"] == "right"
    assert arguments(tour, True)[-2:] == ["--cycle", "--validate"]
