import unittest

import cv2 as cv
import numpy as np

from tools.vr_qr.geometry import marker_spec, solve_marker, StableAnchor


class GeometryTests(unittest.TestCase):
    def test_meeting_width_and_rejected_inputs(self):
        url = 'https://example.test/viewer.html#room=default&entry=qr&invite=' + 'a' * 64
        self.assertEqual(marker_spec(url)[0], .04)
        self.assertEqual(marker_spec(url + '&qrmm=150')[0], .15)
        for bad in ['other', url + '&qrmm=nan', url + '&role=presenter', 'NADOC-CUBE:1:6:150:150:3.6']:
            self.assertIsNone(marker_spec(bad))

    def test_all_faces_recover_same_cube_origin(self):
        cube = np.eye(4); cube[:3, 3] = [.2, 1.3, -.9]
        for face in range(6):
            width, marker_from_cube = marker_spec(f'NADOC-CUBE:1:{face}:150:150:3.6')
            self.assertEqual(width, .15)
            world_from_marker = cube @ np.linalg.inv(marker_from_cube)
            np.testing.assert_allclose(world_from_marker @ marker_from_cube, cube, atol=1e-9)
            self.assertAlmostEqual(np.linalg.det(marker_from_cube[:3, :3]), 1)

    def test_pose_from_known_camera_projection(self):
        intrinsic = np.array([[280., 0, 307.4], [0, 280., 236.6], [0, 0, 1.]])
        half = .15 * 29 / 37 / 2
        obj = np.array([[-half, half, 0], [half, half, 0], [half, -half, 0], [-half, -half, 0]])
        rotation = cv.Rodrigues(np.array([.13, -.1, .03]))[0] @ np.diag([1., -1., -1.])
        rvec = cv.Rodrigues(rotation)[0]; translation = np.array([.02, -.01, .4])
        pixels = cv.projectPoints(obj, rvec, translation, intrinsic, None)[0]
        pose = solve_marker(cv, pixels, 29, .15, intrinsic)
        self.assertIsNotNone(pose)
        np.testing.assert_allclose(pose[:3, 3], [.02, .01, -.4], atol=1e-6)
        np.testing.assert_allclose(pose[:3, :3], np.diag([1., -1., -1.]) @ rotation, atol=1e-6)
        self.assertIsNone(solve_marker(cv, np.zeros((4, 2)), 29, .15, intrinsic))

    def test_no_snap_on_single_frame_loss_movement_or_switched_marker(self):
        gate = StableAnchor(); pose = np.eye(4); head = np.eye(4)
        for i in range(11):
            self.assertIsNone(gate.update('a', pose, head, i * .1))
        self.assertIsNone(gate.update('a', None, head, 1.2))
        for i in range(11):
            self.assertIsNone(gate.update('a', pose, head, 2 + i * .1))
        self.assertIsNone(gate.update('b', pose, head, 3.2))
        head[0, 3] = .02
        self.assertIsNone(gate.update('b', pose, head, 3.3))
        result = None
        for i in range(12):
            result = gate.update('b', pose, head, 3.4 + i * .1)
            if result is not None:
                break
        self.assertIsNotNone(result)

    def test_fast_duplicate_samples_cannot_satisfy_time_gate(self):
        gate = StableAnchor()
        for i in range(20):
            self.assertIsNone(gate.update('a', np.eye(4), np.eye(4), i * .001))


if __name__ == '__main__':
    unittest.main()
