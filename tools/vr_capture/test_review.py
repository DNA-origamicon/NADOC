"""Small offline fixtures; no compositor, browser, or headset required."""
import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from tools.vr_capture.review import build_review, frame_index


def fixture():
    start = 10_000_000_000
    rows = [
        {'event': 'swapchain', 'swapchain': 1, 'width': 2, 'height': 2,
         'format': 44, 'mode': 2, 'direct_display': True, 'test_surface': False},
        {'event': 'capture_start', 'request': 7, 'start_ns': start,
         'end_ns': start + 60_000_000},
    ]
    for number, milliseconds in ((1, 0), (2, 11), (3, 22), (4, 55)):
        rows.append({'event': 'present', 'request': 7, 'swapchain': 1,
                     'present': number, 'present_id': 100 + number,
                     'enter_ns': start + milliseconds * 1_000_000,
                     'armed': True, 'copied': number != 3, 'result': 0})
    # Compressor completion order deliberately differs from presentation order.
    for number in (4, 1, 2):
        rows.append({'event': 'frame_saved', 'request': 7, 'swapchain': 1,
                     'present': number, 'file': f'frame-{number}.bgra.z',
                     'width': 2, 'height': 2, 'format': 44})
    rows.extend([
        {'event': 'capture_interval_end', 'request': 7},
        {'event': 'capture_complete', 'request': 7, 'active_presents': 4,
         'copied_frames': 3, 'saved': 3, 'pixel_drops': 1, 'event_drops': 0},
    ])
    for row in rows:
        row['_source'] = 'events-1.jsonl'
    return rows, {'request': 7, 'complete_present_capture': False,
                  'direct_display_provenance': True}


class ReviewTests(unittest.TestCase):
    def test_actual_timestamps_join_source_and_present_not_write_order(self):
        rows, report = fixture()
        foreign = copy.deepcopy(rows[2:])
        for row in foreign:
            row['_source'] = 'events-other.jsonl'
        images, frames, metadata = frame_index(rows + foreign, report)
        self.assertEqual([r['present'] for r in images], [1, 2, 4])
        self.assertEqual([f['source_elapsed_ms'] for f in frames], [0, 11, 55])
        self.assertEqual(frames[-1]['present_gap_ms'], 33)
        self.assertEqual(frames[-1]['saved_frame_gap_ms'], 44)
        self.assertEqual(frames[-1]['unsaved_presents_before'], 1)
        self.assertTrue(frames[-1]['long_present_gap'])
        self.assertEqual(metadata['median_present_interval_ms'], 11)
        self.assertEqual(metadata['present_gaps'][0]['duration_ms'], 33)
        self.assertEqual(metadata['unsaved_presents'][0]['present'], 3)
        self.assertTrue(metadata['timestamp_playback_available'])
        self.assertFalse(metadata['complete_present_capture'])
        self.assertFalse(metadata['refresh_mapping_verified'])
        self.assertFalse(metadata['optical_output_verified'])

    def test_limit_keeps_capture_scope_and_original_timing(self):
        rows, report = fixture()
        _, frames, metadata = frame_index(rows, report, limit=2)
        self.assertEqual([f['present'] for f in frames], [1, 2])
        self.assertEqual(metadata['total_saved_frames'], 3)
        self.assertEqual(metadata['exported_frames'], 2)
        self.assertTrue(metadata['limited_export'])
        self.assertEqual(metadata['capture_duration_ms'], 60)
        self.assertEqual(len(metadata['present_gaps']), 1)
        with self.assertRaises(ValueError):
            frame_index(rows, report, limit=-1)

    def test_packed_frames_retain_distinct_ranges_in_the_same_original_file(self):
        rows, report = fixture()
        saved = {r['present']:r for r in rows if r['event'] == 'frame_saved'}
        saved[1].update(file='capture-1-7.frames.zst', file_offset=0, compressed_bytes=100)
        saved[2].update(file='capture-1-7.frames.zst', file_offset=100, compressed_bytes=240)
        saved[4]['compressed_bytes'] = 70  # Legacy file has no packed range.
        _, frames, _ = frame_index(rows, report)
        self.assertEqual([f['original_file_offset'] for f in frames], [0, 100, None])
        self.assertEqual([f['compressed_frame_bytes'] for f in frames], [100, 240, None])
        self.assertEqual(frames[0]['original_file'], frames[1]['original_file'])
        self.assertNotEqual(frames[0]['file'], frames[1]['file'])
        self.assertEqual([f['present'] for f in frames], [1, 2, 4])

    def test_missing_or_ambiguous_present_disables_timed_playback(self):
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate):
                rows, report = fixture()
                if duplicate:
                    rows.append(dict(rows[2]))
                else:
                    rows.pop(2)
                _, frames, metadata = frame_index(rows, report)
                frame = next(f for f in frames if f['present'] == 1)
                self.assertIsNone(frame['host_present_enter_ns'])
                self.assertFalse(metadata['timestamp_playback_available'])

    def test_ambiguous_request_across_logs_is_rejected(self):
        rows, report = fixture()
        other = dict(rows[1], _source='events-other.jsonl')
        with self.assertRaisesRegex(ValueError, 'unambiguous'):
            frame_index(rows + [other], report)

    def test_build_keeps_exact_panel_pixels_and_embeds_safe_metadata(self):
        rows, _ = fixture()
        # Complete capture for this fixture; gap detection remains independent.
        rows = [r for r in rows if not (r['event'] == 'present' and r['present'] == 3)]
        complete = rows[-1]
        complete.update(active_presents=3, copied_frames=3, pixel_drops=0)
        raw = bytes([0, 0, 255, 255, 0, 255, 0, 255,
                     255, 0, 0, 255, 0, 255, 255, 255])
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for row in rows:
                if row['event'] == 'frame_saved':
                    (directory / row['file']).write_bytes(zlib.compress(raw))
            (directory / 'events-<capture>.jsonl').write_text(
                ''.join(json.dumps(row) + '\n' for row in rows))
            output = directory / 'review'
            page = build_review(directory, output)
            metadata = json.loads((output / 'review.json').read_text())
            frames = json.loads((output / 'frames.json').read_text())
            self.assertTrue(metadata['complete_present_capture'])
            self.assertEqual(metadata['default_playback_rate'], .25)
            self.assertFalse(metadata['headset_identity_verified'])
            self.assertEqual(metadata['eye_crop_assumption'],
                             'equal_side_by_side_halves_unverified')
            html = page.read_text()
            self.assertNotIn('__CAPTURE_DATA__', html)
            self.assertIn('events-\\u003ccapture>.jsonl', html)
            self.assertIn('not physical headset output', html)
            self.assertIn('value="0.25" selected', html)
            self.assertIn('Left half / eye area', html)
            png = (output / frames[0]['file']).read_bytes()
            self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack('>II', png[16:24]), (2, 2))
            cursor, payload = 8, b''
            while cursor < len(png):
                size = struct.unpack('>I', png[cursor:cursor + 4])[0]
                if png[cursor + 4:cursor + 8] == b'IDAT':
                    payload += png[cursor + 8:cursor + 8 + size]
                cursor += size + 12
            self.assertEqual(zlib.decompress(payload),
                             bytes([0, 255, 0, 0, 0, 255, 0,
                                    0, 0, 0, 255, 255, 255, 0]))


if __name__ == '__main__':
    unittest.main()
