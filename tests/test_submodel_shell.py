"""Simulation export subset tests; no NADOC structures are authored."""
import numpy as np
import pytest
from experiments.oxdna_submodel.shell import box_distance, crop

BOX = dict(min_corner=[-.1, -.1, -.1], max_corner=[.1, .1, .1], rotation=[0,0,0,1])


def test_euclidean_shell_includes_faces_not_expanded_box_corners():
    assert box_distance([[1.1,.1,.1],[1.1,1.1,.1]], BOX) == pytest.approx([1,2**.5])


def test_minimum_shell_keeps_bonds_and_reindexes_only_export():
    topology = "7 1\n" + "\n".join(f"1 A {i-1 if i else -1} {i+1 if i<6 else -1}" for i in range(7))+"\n"
    configuration = "t = 0\nb = 10 10 10\nE = 0 0 0\n"+"\n".join(str(i) for i in range(7))+"\n"
    points = [[i-3,0,0] for i in range(7)]
    top, conf, recipe = crop(topology, configuration, points, BOX, 0)
    assert recipe["retained_source_indices"] == [2,3,4]
    assert recipe["mobile_output_indices"] == [1]
    assert recipe["cut_bonds_source_indices"] == [[2,1],[4,5]]
    assert top == "3 1\n1 A -1 1\n1 A 0 2\n1 A 1 -1\n"
    assert conf.splitlines()[3:] == ["2","3","4"]
    assert crop(topology, configuration, points, BOX, None)[:2] == (topology,configuration)
    with pytest.raises(ValueError, match="Invalid shell"):
        crop(topology, configuration, points, BOX, np.nan)
