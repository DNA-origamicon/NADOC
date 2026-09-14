"""Read-only trajectory extraction must preserve bonds across periodic images."""
import numpy as np
from experiments.peg_chudoba.export_viewer import sample_trajectory


def test_saved_frame_subsampling_and_periodic_bonds(tmp_path):
    trajectory = tmp_path/'trajectory.dat'
    frames = []
    for step in (0, 10, 20):
        frames.append(f't = {step}\nb = 10 10 10\nE = 0 0 0\n9.9 0 0\n0.1 0 0\n')
    original = ''.join(frames)
    trajectory.write_text(original)
    xyz, steps, boxes, radii, total = sample_trajectory(trajectory, 2, 1, 2)
    assert total == 3
    assert steps == [0, 20]
    assert xyz.shape == (2, 2, 3)
    np.testing.assert_allclose(xyz.mean(axis=1), 0, atol=1e-7)
    np.testing.assert_allclose(xyz[:,1,0]-xyz[:,0,0], .2*.8518, rtol=1e-6)
    np.testing.assert_allclose(radii, [.1*.8518]*2)
    np.testing.assert_allclose(boxes, [[8.518]*3]*2)
    assert trajectory.read_text() == original
