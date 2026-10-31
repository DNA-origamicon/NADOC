"""Chemical and rigid-motion controls for the isolated internal-tail candidate."""

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.ring_piercing import segment_pierces_ring
from experiments.terminal_extension_bridge_candidate import fixed_native_exit


def defect_fragment():
    # Actual smallO ext2 -> ext1 fragment from the failing FULL test. Ring order:
    # C1', C2', C3', C4', O4'. Coordinates in nm; neither sugar may move.
    ring = np.array([
        [-.058306754114205106, .7631681700575188, -2.859515638373332],
        [-.014802637129666008, .7353067249028117, -2.717599530481075],
        [-.05486952703150236, .5896030100796826, -2.7058062349139145],
        [-.18388656112037505, .5809063841769777, -2.7875197809930015],
        [-.1825475193505855, .6961254097646224, -2.875528150536883],
    ])
    current_o3 = np.array([-.050350634690292904, .7258164161267897, -2.749101173865846])
    c5 = np.array([.14641013147447135, .6575214121727229, -2.529697119979025])
    native_o3 = np.array([.054746613733174326, .5004487024039961, -2.6837878083868527])
    initial = np.array([.0880577364015493, .8055634500898369, -2.7399628699915937,
                       .18319139793170003, .7063100230897242, -2.660092016729325])
    return ring, current_o3, c5, native_o3, initial


def test_existing_own_sugar_piercing_clears_without_c3_epimer_or_stretched_bond():
    ring, current_o3, c5, native_o3, initial = defect_fragment()
    snapshot = [a.copy() for a in (ring, c5, native_o3, initial)]
    assert segment_pierces_ring(current_o3, initial[:3], ring)[0]
    result = fixed_native_exit(ring[2], c5, native_o3, initial)
    assert result is not None
    o3, phosphate, o5 = result
    assert not segment_pierces_ring(o3, phosphate, ring)[0]
    assert np.dot(np.cross(ring[1] - ring[2], ring[3] - ring[2]), o3 - ring[2]) < 0
    np.testing.assert_allclose(
        [np.linalg.norm(a - b) for a, b in
         ((ring[2], o3), (o3, phosphate), (phosphate, o5), (o5, c5))],
        [.143, .160, .159, .144], atol=1e-7, rtol=0,
    )
    for actual, expected in zip((ring, c5, native_o3, initial), snapshot):
        np.testing.assert_array_equal(actual, expected)


def test_rigid_pose_does_not_choose_a_different_linker_branch():
    ring, _, c5, native_o3, initial = defect_fragment()
    reference = fixed_native_exit(ring[2], c5, native_o3, initial)
    rotation = Rotation.from_euler('xyz', [17, -31, 67], degrees=True).as_matrix()
    shift = np.array([2.1, -.9, 3.4])
    pose = lambda p: np.asarray(p) @ rotation.T + shift
    actual = fixed_native_exit(pose(ring[2]), pose(c5), pose(native_o3),
                               pose(initial.reshape(2, 3)).ravel())
    assert actual is not None
    np.testing.assert_allclose(actual, pose(reference), atol=1e-5, rtol=0)


def test_unreachable_fixed_sugars_refuse_instead_of_stretching_the_linker():
    ring, _, c5, native_o3, initial = defect_fragment()
    assert fixed_native_exit(ring[2], c5 + [100, 0, 0], native_o3, initial) is None
