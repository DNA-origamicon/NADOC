import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from tools.vr_qr.cube import CubeMapping, load_mapping, mapped_marker_spec
from tools.vr_qr.geometry import marker_spec


class CubeMappingTests(unittest.TestCase):
    def fixtures(self):
        # Deliberately permute every label; rotate each printed QR in its plane.
        cube = np.eye(4)
        cube[:3, 3] = [.25, 1.2, -.7]
        poses = {}
        for face, slot in enumerate([4, 0, 3, 1, 2]):
            data = f'NADOC-CUBE:1:{face}:150:150:3.6'
            pose = np.linalg.inv(marker_spec(f'NADOC-CUBE:1:{slot}:150:150:3.6')[1])
            angle = face * np.pi / 2
            rotation = np.eye(4)
            rotation[:2, :2] = [[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]]
            poses[data] = cube @ pose @ rotation
        return cube, poses

    def test_permuted_and_rotated_plates_recover_one_center_and_persist(self):
        cube, poses = self.fixtures()
        mapping = CubeMapping()
        for count, (data, pose) in enumerate(poses.items(), 1):
            self.assertTrue(mapping.accept(data, pose))
            self.assertEqual(mapping.states().count(1), count)
        self.assertTrue(mapping.complete)
        self.assertEqual(mapping.states().count(-1), 1)
        np.testing.assert_allclose(mapping.stage_from_cube[:3, 3], cube[:3, 3])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'map.json'
            mapping.save(path)
            saved = load_mapping(path)
            self.assertIsNotNone(saved)
            self.assertNotIn('stage_from_cube', saved)
            for data, pose in poses.items():
                spec = mapped_marker_spec(data, saved)
                np.testing.assert_allclose(pose @ spec[1], mapping.stage_from_cube, atol=1e-9)
                # Stored marker transforms remain usable after moving the cube.
                moved = np.eye(4); moved[:3, 3] = [1, 0, -.5]
                np.testing.assert_allclose(moved @ pose @ spec[1], moved @ mapping.stage_from_cube, atol=1e-9)
            self.assertIsNone(mapped_marker_spec('NADOC-CUBE:1:0:200:200:3.6', saved))

    def test_movement_invalidates_progress_and_incomplete_map_cannot_save(self):
        _, poses = self.fixtures()
        mapping = CubeMapping()
        data, pose = next(iter(poses.items()))
        mapping.accept(data, pose)
        moved = pose.copy(); moved[0, 3] += .05
        self.assertFalse(mapping.accept(data, moved))
        self.assertEqual(mapping.states(), [0] * 6)
        self.assertIsNone(mapping.stage_from_cube)
        with self.assertRaises(ValueError):
            mapping.save('/unused')

    def test_rotating_a_known_plate_invalidates_the_session(self):
        _, poses = self.fixtures()
        mapping = CubeMapping()
        data, pose = next(iter(poses.items()))
        mapping.accept(data, pose)
        rotation = np.eye(4); rotation[:2, :2] = [[0, -1], [1, 0]]
        self.assertFalse(mapping.accept(data, pose @ rotation))
        self.assertEqual(mapping.states(), [0] * 6)

    def test_packet_carries_mapping_without_requesting_scene_registration(self):
        from tools.vr_qr.worker import packet
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            image = np.arange(24, dtype=np.uint8).reshape(2, 3, 4)
            packet(folder, 4, '1/5 faces calibrated', image, np.eye(4),
                   {'edge': .15, 'states': [1, 0, 0, 0, 0, 0]})
            with (folder / 'frame.bin').open('rb') as frame:
                self.assertEqual(frame.readline(), b'NADOCQR2\n')
                self.assertEqual(frame.readline().split()[:4], [b'4', b'3', b'2', b'2'])
                self.assertEqual(len(frame.readline().split()), 16)
                self.assertEqual(frame.readline(), b'1/5 faces calibrated\n')
                self.assertEqual(frame.readline().split(), [b'0.15', b'1', b'0', b'0', b'0', b'0', b'0'])
                self.assertEqual(frame.read(), image.tobytes())

    def test_duplicate_physical_face_and_wrong_size_rejected(self):
        _, poses = self.fixtures()
        mapping = CubeMapping()
        data, pose = next(iter(poses.items()))
        self.assertTrue(mapping.accept(data, pose))
        self.assertFalse(mapping.accept('NADOC-CUBE:1:1:150:150:3.6', pose))
        self.assertFalse(mapping.accept('NADOC-CUBE:1:1:200:200:3.6', pose))
        self.assertEqual(len(mapping.faces), 1)

    def test_bad_maps_do_not_override_conventional_geometry(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'map.json'
            self.assertIsNone(load_mapping(path))
            for bad in ['', '{}', '{', json.dumps({'version': 1, 'dimensions': [], 'faces': {}})]:
                path.write_text(bad)
                self.assertIsNone(load_mapping(path))
            mapping = CubeMapping()
            for data, pose in self.fixtures()[1].items():
                mapping.accept(data, pose)
            mapping.save(path)
            bad = json.loads(path.read_text())
            bad['faces']['0']['marker_from_cube'][0][3] += 10
            path.write_text(json.dumps(bad))
            self.assertIsNone(load_mapping(path))
        data = 'NADOC-CUBE:1:0:150:150:3.6'
        np.testing.assert_array_equal(mapped_marker_spec(data, None)[1], marker_spec(data)[1])


if __name__ == '__main__':
    unittest.main()
