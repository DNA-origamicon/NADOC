from tools.vr_workflows.representation_tour import REPS, transitions
from tools.vr_workflows.tour_catalog import catalog, arguments


def test_every_supported_directed_transition_is_covered_once():
    from typing import get_args
    from backend.api.routes_vr import VRLaunchRequest

    assert set(REPS) == set(
        get_args(VRLaunchRequest.model_fields["representation"].annotation)
    )
    pairs = transitions()
    assert len(pairs) == 12 and len(set(pairs)) == 12
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
