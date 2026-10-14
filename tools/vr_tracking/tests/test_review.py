"""Review boundaries and provenance injection without requiring a browser."""

import json
from pathlib import Path
import tempfile
import unittest

from tools.vr_tracking.review import write_review


class ReviewTests(unittest.TestCase):
    def test_review_leaves_original_bytes_unchanged_and_escapes_script_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            original = output / "original.png"
            original.write_bytes(b"exact-original-fixture")
            report = {"coordinate_space": "final_swapchain_distorted",
                      "limits": "Originals only; no optical claim.",
                      "frames": [{"id": "</script><img src=x onerror=alert(1)>",
                                  "source": {"rgb_sha256": "retained"},
                                  "image_file": "original.png", "groups": {}, "expected": {}}]}
            page = write_review(output, report).read_text()
            self.assertEqual(original.read_bytes(), b"exact-original-fixture")
            self.assertNotIn("</script><img", page)
            self.assertIn("\\u003c/script\\u003e", page)
            embedded = page.split('<script id="report" type="application/json">', 1)[1].split('</script>', 1)[0]
            self.assertEqual(json.loads(embedded), report)
            self.assertIn('href="results.json"', page)
            self.assertIn('href="manifest.json"', page)
            self.assertIn('Native pixels (1:1)', page)
            self.assertIn("match.status==='tracked'", page)
            self.assertIn("measured[0]+.5", page)
            self.assertNotIn("drawImage", page)

    def test_images_cannot_escape_review_or_load_remote_urls(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            for name in ("../outside.png", "/absolute.png", "https://example.org/image.png",
                         "nested\\image.png", "missing.png", "not-a-png.svg"):
                with self.subTest(name=name):
                    with self.assertRaises(ValueError):
                        write_review(output, {"frames": [{"image_file": name}]})

    def test_nonfinite_metadata_and_empty_frames_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "original.png").write_bytes(b"original")
            with self.assertRaises(ValueError):
                write_review(output, {"frames": []})
            with self.assertRaises(ValueError):
                write_review(output, {"frames": [{"image_file": "original.png", "id": float('nan')}]})


if __name__ == "__main__":
    unittest.main()
