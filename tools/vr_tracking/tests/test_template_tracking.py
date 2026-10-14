"""Pure pixel fixtures: no headset, runtime, downloads or image averaging."""

import json
import unittest
from unittest.mock import patch

import numpy as np

from tools.vr_tracking.template_tracking import (
    SourceFrame, TrackConfig, make_template, track_landmark, track_landmarks,
)


def frame(rgb, *, space="final_swapchain_distorted", provenance=None):
    height, width = rgb.shape[:2]
    return SourceFrame(rgb, space,
                       {"left": (0, 0, width // 2, height),
                        "right": (width // 2, 0, width, height)},
                       provenance or {"capture": "synthetic", "present": 1})


def pixels(seed=1, shape=(13, 11, 3)):
    return np.random.default_rng(seed).integers(35, 190, shape, dtype=np.uint8)


def stamp(image, patch_rgb, x, y):
    height, width = patch_rgb.shape[:2]
    image[y:y + height, x:x + width] = patch_rgb


class TemplateTrackingTests(unittest.TestCase):
    def setUp(self):
        self.reference_rgb = np.zeros((100, 240, 3), dtype=np.uint8)
        self.patch = pixels()
        stamp(self.reference_rgb, self.patch, 35, 40)
        self.reference = frame(self.reference_rgb)
        self.template = make_template(self.reference, "terminus", "left", (35, 40, 46, 53))

    def test_known_translations_preserve_original_integer_positions_and_provenance(self):
        for dx, dy in ((0, 0), (17, -13), (-20, 25), (5, 1)):
            with self.subTest(delta=(dx, dy)):
                image = np.zeros_like(self.reference_rgb)
                stamp(image, self.patch, 35 + dx, 40 + dy)
                current = frame(image, provenance={"capture": "synthetic", "present": 72,
                                                   "raw_offset": 4096, "raw_sha256": "caller-kept"})
                match = track_landmark(current, self.template, (5, 10, 105, 95))
                self.assertEqual(match["status"], "tracked")
                self.assertEqual(match["position_xy"], [40 + dx, 46 + dy])
                self.assertEqual(match["translation_xy"], [dx, dy])
                self.assertAlmostEqual(match["score"], 1.0, places=10)
                self.assertEqual(match["source"]["provenance"], current.provenance)
                self.assertEqual(match["source"]["rgb_sha256"], current.rgb_sha256)
                self.assertEqual(match["template"]["reference_source"]["rgb_sha256"], self.reference.rgb_sha256)
                self.assertEqual(match["quantization_half_width_px"], .5)
                self.assertFalse(match["accuracy_calibrated"])
                self.assertFalse(match["confidence_is_probability"])
                json.dumps(match, allow_nan=False)

    def test_right_eye_returns_full_source_coordinates_and_excludes_left_distractor(self):
        reference = self.reference_rgb.copy()
        stamp(reference, self.patch, 160, 35)
        template = make_template(frame(reference), "right-terminus", "right", (160, 35, 171, 48))
        image = np.zeros_like(reference)
        stamp(image, self.patch, 43, 41)  # Exact opposite-eye match must not compete.
        stamp(image, self.patch, 170, 41)
        match = track_landmark(frame(image), template, (0, 10, 235, 90))
        self.assertEqual(match["status"], "tracked")
        self.assertEqual(match["position_xy"], [175, 47])
        self.assertEqual(match["translation_xy"], [10, 6])
        self.assertEqual(match["effective_search_rect"], [120, 10, 235, 90])
        self.assertTrue(match["search_clipped_to_eye"])

    def test_exact_target_beats_similar_and_color_permuted_distractors(self):
        image = np.zeros_like(self.reference_rgb)
        altered = self.patch.copy()
        altered[::2] = pixels(2)[::2]
        stamp(image, altered, 10, 18)
        stamp(image, self.patch[:, :, ::-1], 77, 18)
        stamp(image, self.patch, 55, 60)
        match = track_landmark(frame(image), self.template, (2, 2, 115, 98))
        self.assertEqual(match["status"], "tracked")
        self.assertEqual(match["position_xy"], [60, 66])
        self.assertGreater(match["peak_gap"], .1)

    def test_two_equal_shifted_candidates_are_ambiguous_and_have_no_trusted_position(self):
        image = np.zeros_like(self.reference_rgb)
        stamp(image, self.patch, 15, 30)
        stamp(image, self.patch, 75, 55)
        match = track_landmark(frame(image), self.template, (2, 2, 115, 98))
        self.assertEqual(match["status"], "ambiguous")
        self.assertEqual(match["near_equal_peak_count"], 2)
        self.assertAlmostEqual(match["peak_gap"], 0, places=10)
        self.assertIsNone(match["position_xy"])
        self.assertIsNone(match["translation_xy"])
        self.assertIsNotNone(match["candidate_position_xy"])

    def test_near_equal_distractor_is_ambiguous_even_if_best_is_exact(self):
        image = np.zeros_like(self.reference_rgb)
        similar = self.patch.copy()
        similar[1, 1] = [0, 255, 0]
        stamp(image, self.patch, 15, 30)
        stamp(image, similar, 75, 55)
        match = track_landmark(frame(image), self.template, (2, 2, 115, 98))
        self.assertEqual(match["status"], "ambiguous")
        self.assertGreater(match["peak_gap"], 0)
        self.assertLess(match["peak_gap"], .05)

    def test_blank_and_unrelated_pixels_are_not_found_not_occluded(self):
        for image in (np.zeros_like(self.reference_rgb),
                      pixels(99, self.reference_rgb.shape)):
            with self.subTest(blank=not image.any()):
                match = track_landmark(frame(image), self.template, (5, 10, 105, 95))
                self.assertEqual(match["status"], "not_found")
                self.assertIsNone(match["position_xy"])
                json.dumps(match, allow_nan=False)

    def test_rotated_texture_does_not_silently_become_a_translation(self):
        image = np.zeros_like(self.reference_rgb)
        stamp(image, np.rot90(self.patch, 2), 35, 40)
        match = track_landmark(frame(image), self.template, (5, 10, 105, 95))
        self.assertEqual(match["status"], "not_found")

    def test_positive_per_channel_gain_and_offset_preserve_match(self):
        image = np.zeros_like(self.reference_rgb)
        transformed = (self.patch.astype(float) * [1.05, 1.05, 1.05] + [10, 20, 30]).astype(np.uint8)
        stamp(image, transformed, 45, 47)
        match = track_landmark(frame(image), self.template, (5, 10, 105, 95))
        self.assertEqual(match["status"], "tracked")
        self.assertEqual(match["translation_xy"], [10, 7])
        self.assertGreater(match["score"], .999)

    def test_out_of_view_and_boundary_positions_are_not_accepted(self):
        for search, expected in (((121, 10, 230, 90), None),
                                 ((5, 10, 105, 95), (-1, 30)),
                                 ((5, 10, 10, 15), None)):
            with self.subTest(search=search, expected=expected):
                match = track_landmark(self.reference, self.template, search, expected_xy=expected)
                self.assertEqual(match["status"], "out_of_view")
                self.assertIsNone(match["position_xy"])
        match = track_landmark(self.reference, self.template, (35, 20, 100, 90))
        self.assertEqual(match["status"], "search_boundary")
        self.assertIsNone(match["position_xy"])

    def test_occluded_requires_explicit_full_source_mask_and_expected_position(self):
        mask = np.zeros(self.reference_rgb.shape[:2], dtype=bool)
        mask[40:53, 35:46] = True
        match = track_landmark(self.reference, self.template, (5, 10, 105, 95),
                               expected_xy=(40, 46), occlusion_mask=mask,
                               occlusion_provenance={"method": "synthetic-known-cover", "present": 1})
        self.assertEqual(match["status"], "occluded")
        self.assertEqual(match["explicit_occlusion_fraction"], 1)
        self.assertIsNone(match["position_xy"])
        self.assertIsNone(match["score"])
        with self.assertRaisesRegex(ValueError, "occlusion mask requires"):
            track_landmark(self.reference, self.template, (5, 10, 105, 95), occlusion_mask=mask)
        with self.assertRaisesRegex(ValueError, "occlusion mask requires"):
            track_landmark(self.reference, self.template, (5, 10, 105, 95), expected_xy=(40, 46),
                           occlusion_mask=mask.astype(np.uint8), occlusion_provenance={})

    def test_half_integer_anchor_is_patch_geometry_not_subpixel_fitting(self):
        template = make_template(self.reference, "even", "left", (35, 40, 45, 52))
        match = track_landmark(self.reference, template, (5, 10, 105, 95))
        self.assertEqual(match["position_xy"], [39.5, 45.5])
        self.assertEqual(match["translation_xy"], [0, 0])
        self.assertEqual(match["position_sampling"], "integer_translation")
        self.assertEqual(match["quantization_half_width_px"], .5)

    def test_source_and_template_pixels_and_provenance_are_owned(self):
        provenance = {"capture": {"file": "a", "byte_range": [1, 2]}}
        reference = frame(self.reference_rgb, provenance=provenance)
        template = make_template(reference, "one", "left", (35, 40, 46, 53))
        original_hash = reference.rgb_sha256
        self.reference_rgb[:] = 0
        provenance["capture"]["file"] = "changed"
        reference.provenance["capture"]["byte_range"].append(3)
        self.assertEqual(reference.rgb_sha256, original_hash)
        self.assertTrue(reference.rgb.any())
        self.assertTrue(template.rgb.any())
        self.assertEqual(reference.provenance["capture"], {"file": "a", "byte_range": [1, 2]})
        with self.assertRaises(ValueError):
            reference.rgb.flags.writeable = True
        with self.assertRaises(ValueError):
            template.rgb.flags.writeable = True

    def test_mismatched_space_dimensions_or_eye_layout_are_rejected(self):
        alternatives = (
            frame(self.reference_rgb, space="application_eye_undistorted"),
            frame(np.zeros((110, 240, 3), dtype=np.uint8)),
            SourceFrame(self.reference_rgb, "final_swapchain_distorted",
                        {"left": (0, 0, 115, 100), "right": (115, 0, 240, 100)}, {}),
        )
        for current in alternatives:
            with self.subTest(signature=current.layout_signature):
                with self.assertRaisesRegex(ValueError, "coordinate space"):
                    track_landmark(current, self.template, (5, 10, 105, 95))

    def test_blank_templates_and_invalid_eye_rectangles_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "contrast"):
            make_template(self.reference, "blank", "left", (1, 1, 12, 14))
        with self.assertRaisesRegex(ValueError, "inside its source eye"):
            make_template(self.reference, "cross-eye", "left", (115, 40, 126, 53))
        with self.assertRaisesRegex(ValueError, "overlap"):
            SourceFrame(self.reference_rgb, "final_swapchain_distorted",
                        {"left": (0, 0, 125, 100), "right": (120, 0, 240, 100)}, {})
        with self.assertRaisesRegex(ValueError, "anchor"):
            make_template(self.reference, "anchor", "left", (35, 40, 46, 53), anchor_xy=(34.5, 45))

    def test_search_budget_rejects_before_ncc_allocation(self):
        for config in (TrackConfig(max_working_bytes=4096), TrackConfig(max_search_pixels=100)):
            with self.subTest(config=config):
                with patch("tools.vr_tracking.template_tracking._ncc") as matching:
                    with self.assertRaisesRegex(ValueError, "budget"):
                        track_landmark(self.reference, self.template, (5, 10, 105, 95), config)
                    matching.assert_not_called()
        with self.assertRaisesRegex(ValueError, "hard resource"):
            TrackConfig(max_working_bytes=1024 ** 3)

    def test_explicit_gaussian_context_matches_known_translation_without_patch_border_artifact(self):
        original = pixels(17, self.reference_rgb.shape)
        reference = frame(original)
        config = TrackConfig(spatial_sigma_px=2, peak_exclusion_radius_px=6)
        template = make_template(reference, "blurred-for-matching", "left", (35, 40, 65, 70), config=config)
        shifted = np.roll(original, shift=(9, 13), axis=(0, 1))
        match = track_landmark(frame(shifted), template, (15, 15, 110, 95), config)
        self.assertEqual(match["status"], "tracked")
        self.assertEqual(match["translation_xy"], [13, 9])
        self.assertAlmostEqual(match["score"], 1, places=10)
        self.assertEqual(match["matching_filter"]["kernel_width_px"], 13)
        self.assertTrue(match["matching_filter"]["context_before_crop"])
        self.assertFalse(match["matching_filter"]["original_pixels_modified"])
        self.assertFalse(match["matching_filter"]["temporal_filtering"])
        self.assertEqual(template.metadata()["matching_context_rect"], [29, 34, 71, 76])
        self.assertTrue(np.array_equal(reference.rgb, original))
        self.assertTrue(np.array_equal(template.rgb, original[40:70, 35:65]))
        with self.assertRaises(ValueError):
            template.matching_rgb.flags.writeable = True

    def test_spatial_matching_handles_changed_fine_texture_without_averaging_frames(self):
        original = np.full_like(self.reference_rgb, 20)
        current = original.copy()
        y, x = np.mgrid[:36, :36]
        shape = np.stack((80 + x * 2, 80 + y * 2, 80 + np.minimum(x, y) * 2), axis=-1)
        fine = (((x + y) % 2) * 2 - 1)[:, :, None] * 48
        stamp(original, (shape + fine).astype(np.uint8), 35, 35)
        stamp(current, (shape - fine).astype(np.uint8), 48, 44)
        reference, target = frame(original), frame(current)
        raw = make_template(reference, "texture", "left", (30, 30, 76, 76))
        raw_match = track_landmark(target, raw, (10, 10, 110, 98))
        self.assertNotEqual(raw_match["status"], "tracked")
        config = TrackConfig(spatial_sigma_px=2, peak_exclusion_radius_px=6)
        template = make_template(reference, "texture", "left", (30, 30, 76, 76), config=config)
        match = track_landmark(target, template, (10, 10, 110, 98), config)
        self.assertEqual(match["status"], "tracked")
        self.assertEqual(match["translation_xy"], [13, 9])
        self.assertGreater(match["score"], .99)
        self.assertEqual(match["source"]["rgb_sha256"], target.rgb_sha256)

    def test_filtered_equal_candidates_remain_ambiguous_and_filter_mismatch_fails(self):
        original = np.zeros((160, 360, 3), dtype=np.uint8)
        block = pixels(91, (45, 45, 3))
        stamp(original, block, 40, 45)
        reference = frame(original)
        config = TrackConfig(spatial_sigma_px=2, peak_exclusion_radius_px=6)
        template = make_template(reference, "filtered", "left", (50, 55, 75, 80), config=config)
        current = np.zeros_like(original)
        stamp(current, block, 10, 15)
        stamp(current, block, 100, 95)
        result = track_landmark(frame(current), template, (2, 2, 178, 158), config)
        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(result["position_xy"])
        with self.assertRaisesRegex(ValueError, "matching filter"):
            track_landmark(frame(current), template, (2, 2, 178, 158))
        with self.assertRaisesRegex(ValueError, "four pixels"):
            TrackConfig(spatial_sigma_px=5)

    def test_filter_context_does_not_bleed_pixels_from_the_other_eye(self):
        original = pixels(26, self.reference_rgb.shape)
        reference = frame(original)
        config = TrackConfig(spatial_sigma_px=2, peak_exclusion_radius_px=6)
        template = make_template(reference, "eye-edge", "left", (98, 36, 119, 65), config=config)
        current = original.copy()
        current[:, 120:] = 255 - current[:, 120:]
        match = track_landmark(frame(current), template, (70, 15, 120, 90), config)
        self.assertEqual(match["status"], "tracked")
        self.assertEqual(match["translation_xy"], [0, 0])
        self.assertAlmostEqual(match["score"], 1, places=10)
        self.assertEqual(template.matching_context_rect[2], 120)
        self.assertEqual(match["matching_context_rect"][2], 120)


class ConsensusTests(unittest.TestCase):
    def scene(self, shifts):
        source = np.zeros((130, 500, 3), dtype=np.uint8)
        current = np.zeros_like(source)
        rectangles = []
        for index, (dx, dy) in enumerate(shifts):
            x, y = 20 + index * 52, 45
            patch_rgb = pixels(index + 20)
            stamp(source, patch_rgb, x, y)
            stamp(current, patch_rgb, x + dx, y + dy)
            rectangles.append((x, y, x + 11, y + 13))
        reference = frame(source)
        templates = [make_template(reference, f"p{index}", "left", rect)
                     for index, rect in enumerate(rectangles)]
        searches = {template.landmark_id: (2, 2, 248, 128) for template in templates}
        return frame(current), templates, searches

    def test_three_landmarks_consensus_rejects_an_independently_moving_distractor(self):
        current, templates, searches = self.scene([(4, 3), (4, 3), (4, 3), (-10, -15)])
        result = track_landmarks(current, templates, searches)
        self.assertEqual(result["status"], "tracked")
        self.assertEqual(result["translation_xy"], [4, 3])
        self.assertEqual(result["inlier_ids"], ["p0", "p1", "p2"])
        self.assertEqual(result["outlier_ids"], ["p3"])
        self.assertEqual(result["estimate_kind"], "per_eye_image_translation_not_6dof")

    def test_two_equal_motion_groups_stay_ambiguous(self):
        current, templates, searches = self.scene([(4, 3), (4, 3), (-10, -15), (-10, -15)])
        result = track_landmarks(current, templates, searches)
        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(result["translation_xy"])
        self.assertEqual(result["reason"], "multiple_equal_support_translation_groups")

    def test_inconsistent_and_single_matches_do_not_establish_consensus(self):
        current, templates, searches = self.scene([(4, 3), (-10, -15)])
        result = track_landmarks(current, templates, searches)
        self.assertEqual(result["status"], "ambiguous")
        result = track_landmarks(current, templates[:1], {"p0": searches["p0"]})
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertIsNone(result["translation_xy"])

    def test_nontransitive_motion_chain_is_not_false_consensus(self):
        current, templates, searches = self.scene([(0, 0), (2, 0), (4, 0)])
        result = track_landmarks(current, templates, searches, consensus_tolerance_px=2)
        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(result["translation_xy"])

    def test_duplicate_ids_missing_searches_and_resource_budgets_fail_before_matching(self):
        current, templates, searches = self.scene([(4, 3), (4, 3)])
        cases = (
            ([templates[0], templates[0]], {"p0": searches["p0"]}, TrackConfig()),
            (templates, {"p0": searches["p0"]}, TrackConfig()),
            (templates, searches, TrackConfig(max_landmarks=1)),
            (templates, searches, TrackConfig(max_template_bytes_total=1)),
        )
        for selected, regions, config in cases:
            with self.subTest(config=config, regions=regions):
                with patch("tools.vr_tracking.template_tracking.track_landmark") as matching:
                    with self.assertRaises(ValueError):
                        track_landmarks(current, selected, regions, config)
                    matching.assert_not_called()

    def test_consensus_refuses_mixing_eye_or_reference_image(self):
        current, templates, searches = self.scene([(4, 3), (4, 3)])
        another_reference = make_template(current, "p1", "left", (76, 48, 87, 61))
        with self.assertRaisesRegex(ValueError, "one reference source"):
            track_landmarks(current, [templates[0], another_reference], searches)


if __name__ == "__main__":
    unittest.main()
