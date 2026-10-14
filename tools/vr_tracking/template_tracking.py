"""Track explicit landmarks in original RGB pixels, without temporal filtering.

Rectangles are half-open (x0, y0, x1, y1), in FULL source-image coordinates.
Integer coordinates denote pixel centers; even-size patch centers can be half
integers. Only integer translations are searched. Correlation diagnostics are
not calibrated probabilities, and the half-pixel sampling bound is not an
accuracy guarantee. A failed visual match cannot establish occlusion.

No projection, eye-layout inference, distortion correction, resizing, adaptive
template updates, or averaging is performed here. Translation consensus is an
image-motion estimate, not a rigid-body pose or evidence of optical doubling.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from numbers import Integral
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.fft import next_fast_len
from scipy.ndimage import gaussian_filter
from scipy.signal import fftconvolve


COORDINATE_SPACES = frozenset({
    "application_eye_undistorted", "final_swapchain_distorted",
})
MAX_SOURCE_BYTES = 128 * 1024 * 1024
MAX_METADATA_BYTES = 64 * 1024
Rect = tuple[int, int, int, int]


def _json_copy(value: Mapping[str, Any]) -> str:
    if not isinstance(value, Mapping):
        raise ValueError("provenance must be a JSON object")
    try:
        encoded = json.dumps(dict(value), sort_keys=True, allow_nan=False,
                             separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise ValueError("provenance must contain finite JSON values") from error
    if len(encoded.encode("utf-8")) > MAX_METADATA_BYTES:
        raise ValueError("provenance exceeds bounded metadata size")
    return encoded


def _rect(value: Sequence[int], name: str) -> Rect:
    if len(value) != 4 or any(isinstance(v, bool) or not isinstance(v, Integral)
                              for v in value):
        raise ValueError(f"{name} must contain four integer bounds")
    x0, y0, x1, y1 = map(int, value)
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"{name} must have positive width and height")
    return x0, y0, x1, y1


def _contains(outer: Rect, inner: Rect) -> bool:
    return (outer[0] <= inner[0] and outer[1] <= inner[1]
            and inner[2] <= outer[2] and inner[3] <= outer[3])


def _intersection(first: Rect, second: Rect) -> Rect | None:
    result = (max(first[0], second[0]), max(first[1], second[1]),
              min(first[2], second[2]), min(first[3], second[3]))
    return result if result[2] > result[0] and result[3] > result[1] else None


def _point(value: Sequence[float], name: str) -> tuple[float, float]:
    if len(value) != 2 or any(isinstance(v, bool) for v in value):
        raise ValueError(f"{name} must contain two finite coordinates")
    try:
        point = float(value[0]), float(value[1])
    except (ValueError, TypeError) as error:
        raise ValueError(f"{name} must contain two finite coordinates") from error
    if not all(math.isfinite(v) for v in point):
        raise ValueError(f"{name} must contain two finite coordinates")
    return point


class SourceFrame:
    """Owned immutable original RGB pixels and caller-supplied provenance.

    Callers decode/reorder source channels without resizing before construction.
    Provenance should identify capture/session, source file and byte range,
    request, presentation and timing. The core retains those exact fields and
    adds an RGB SHA256; it cannot verify external claims of original provenance.
    Named eye rectangles must be explicit, non-overlapping and inside the image.
    """

    def __init__(self, rgb: np.ndarray, coordinate_space: str,
                 eyes: Mapping[str, Sequence[int]], provenance: Mapping[str, Any]):
        if (not isinstance(rgb, np.ndarray) or rgb.dtype != np.uint8
                or rgb.ndim != 3 or rgb.shape[2] != 3
                or min(rgb.shape[:2]) <= 0):
            raise ValueError("source must be a nonempty uint8 H×W×3 RGB array")
        if rgb.nbytes > MAX_SOURCE_BYTES:
            raise ValueError("source exceeds bounded original-image size")
        if coordinate_space not in COORDINATE_SPACES:
            raise ValueError("coordinate_space must explicitly name application or final pixels")
        if not isinstance(eyes, Mapping) or not 1 <= len(eyes) <= 2:
            raise ValueError("supply one or two explicit named eye rectangles")
        source_rect = (0, 0, rgb.shape[1], rgb.shape[0])
        checked = {}
        for eye, bounds in eyes.items():
            if eye not in ("left", "right"):
                raise ValueError("eye names must be left or right")
            bounds = _rect(bounds, f"{eye} eye")
            if not _contains(source_rect, bounds):
                raise ValueError("eye rectangle is outside the source")
            if any(_intersection(bounds, other) is not None for other in checked.values()):
                raise ValueError("eye rectangles overlap")
            checked[eye] = bounds
        # Immutable bytes backing also prevents writeable=True from undoing the
        # guard, and caller mutations cannot silently change the stored hash.
        pixels = rgb.tobytes(order="C")
        self.rgb = np.frombuffer(pixels, dtype=np.uint8).reshape(rgb.shape)
        self.coordinate_space = coordinate_space
        self.eyes = MappingProxyType(checked)
        self._provenance_json = _json_copy(provenance)
        self.rgb_sha256 = hashlib.sha256(pixels).hexdigest()

    @property
    def provenance(self) -> dict[str, Any]:
        return json.loads(self._provenance_json)

    @property
    def layout_signature(self) -> tuple:
        return (self.coordinate_space, tuple(self.rgb.shape), tuple(sorted(self.eyes.items())))

    def metadata(self) -> dict[str, Any]:
        return {"coordinate_space": self.coordinate_space,
                "width": self.rgb.shape[1], "height": self.rgb.shape[0],
                "eye_rectangles": {name: list(rect) for name, rect in self.eyes.items()},
                "pixel_coordinates": "full_source_top_left_pixel_centers",
                "rgb_sha256": self.rgb_sha256, "provenance": self.provenance}


@dataclass(frozen=True)
class TrackConfig:
    min_score: float = 0.80
    min_peak_gap: float = 0.05
    peak_exclusion_radius_px: int = 3
    min_template_std: float = 2.0
    spatial_sigma_px: float = 0.0
    occlusion_fraction: float = 0.5
    max_search_pixels: int = 1024 * 1024
    max_template_pixels: int = 256 * 256
    max_working_bytes: int = 128 * 1024 * 1024
    max_landmarks: int = 64
    max_template_bytes_total: int = 16 * 1024 * 1024

    def __post_init__(self):
        for key in ("min_score", "min_peak_gap", "min_template_std", "spatial_sigma_px", "occlusion_fraction"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{key} must be finite")
        if not 0 < self.min_score <= 1 or not 0 <= self.min_peak_gap <= 2:
            raise ValueError("invalid correlation acceptance thresholds")
        if self.min_template_std <= 0 or not 0 < self.occlusion_fraction <= 1:
            raise ValueError("invalid contrast or occlusion threshold")
        if not 0 <= self.spatial_sigma_px <= 4:
            raise ValueError("spatial_sigma_px must be between zero and four pixels")
        for key in ("peak_exclusion_radius_px", "max_search_pixels", "max_template_pixels",
                    "max_working_bytes", "max_landmarks", "max_template_bytes_total"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
                raise ValueError(f"{key} must be a positive integer")
        # Callers can lower these bounds, but cannot accidentally turn the core
        # into an unbounded allocation through a manifest.
        if (self.max_working_bytes > 512 * 1024 * 1024
                or self.max_search_pixels > 4 * 1024 * 1024
                or self.max_template_pixels > 512 * 512
                or self.max_landmarks > 256
                or self.max_template_bytes_total > 64 * 1024 * 1024):
            raise ValueError("tracking configuration exceeds hard resource limits")


def _filter_context(rect: Rect, eye: Rect, radius: int) -> Rect:
    return (max(eye[0], rect[0] - radius), max(eye[1], rect[1] - radius),
            min(eye[2], rect[2] + radius), min(eye[3], rect[3] + radius))


def _matching_pixels(frame: SourceFrame, bounds: Rect, eye: str, sigma: float) -> np.ndarray:
    """Filter original context first, then crop; never filter a bare patch edge."""
    x0, y0, x1, y1 = bounds
    if sigma == 0:
        return frame.rgb[y0:y1, x0:x1]
    radius = math.ceil(3 * sigma)
    cx0, cy0, cx1, cy1 = _filter_context(bounds, frame.eyes[eye], radius)
    context = frame.rgb[cy0:cy1, cx0:cx1].astype(np.float64)
    # The finite kernel only sees original pixels in this eye. Reflect padding
    # occurs at actual eye boundaries, never at the selected template/search
    # boundary; the halo supplies identical convolution support in both paths.
    filtered = gaussian_filter(context, sigma=(sigma, sigma, 0),
                               radius=(radius, radius, 0), mode="reflect")
    return filtered[y0 - cy0:y1 - cy0, x0 - cx0:x1 - cx0]


def _filter_metadata(sigma: float) -> dict[str, Any]:
    radius = math.ceil(3 * sigma)
    return {"method": "original_rgb" if sigma == 0 else "spatial_gaussian_for_matching_only",
            "sigma_px": sigma, "kernel_radius_px": radius,
            "kernel_width_px": 2 * radius + 1,
            "context_before_crop": True,
            "eye_boundary_mode": "reflect", "original_pixels_modified": False,
            "temporal_filtering": False, "position_accuracy_calibrated": False}


class LandmarkTemplate:
    """Exact fixed patch selected by the caller, associated with one source eye."""

    def __init__(self, frame: SourceFrame, landmark_id: str, eye: str,
                 template_rect: Sequence[int], anchor_xy: Sequence[float] | None,
                 config: TrackConfig):
        if not isinstance(landmark_id, str) or not landmark_id or len(landmark_id) > 128:
            raise ValueError("landmark_id must be a nonempty bounded string")
        if eye not in frame.eyes:
            raise ValueError("template eye is missing from explicit source layout")
        bounds = _rect(template_rect, "template_rect")
        if not _contains(frame.eyes[eye], bounds):
            raise ValueError("template must fit entirely inside its source eye")
        x0, y0, x1, y1 = bounds
        if (x1 - x0) * (y1 - y0) > config.max_template_pixels:
            raise ValueError("template exceeds pixel budget")
        reference = ((x0 + x1 - 1) / 2, (y0 + y1 - 1) / 2) if anchor_xy is None else _point(anchor_xy, "anchor_xy")
        if not (x0 <= reference[0] <= x1 - 1 and y0 <= reference[1] <= y1 - 1):
            raise ValueError("anchor must be inside the template's pixel centers")
        raw = frame.rgb[y0:y1, x0:x1].tobytes()
        rgb = np.frombuffer(raw, dtype=np.uint8).reshape(y1 - y0, x1 - x0, 3)
        floating = rgb.astype(np.float64)
        centered = floating - floating.mean(axis=(0, 1), keepdims=True)
        std = float(np.sqrt(np.mean(centered * centered)))
        if std < config.min_template_std:
            raise ValueError("template has insufficient within-channel spatial contrast")
        self.landmark_id = landmark_id
        self.eye = eye
        self.template_rect = bounds
        self.reference_xy = reference
        self.rgb = rgb
        self.rgb_sha256 = hashlib.sha256(raw).hexdigest()
        self.spatial_std = std
        matching = _matching_pixels(frame, bounds, eye, config.spatial_sigma_px) if config.spatial_sigma_px else rgb
        if config.spatial_sigma_px:
            # Derived floating point matching data is separate from the exact
            # original patch. Immutable backing protects both representations.
            matching = np.frombuffer(matching.tobytes(), dtype=np.float64).reshape(rgb.shape)
        self.matching_rgb = matching
        self.spatial_sigma_px = config.spatial_sigma_px
        self.matching_context_rect = _filter_context(bounds, frame.eyes[eye], math.ceil(3 * config.spatial_sigma_px))
        self.matching_spatial_std = float(np.sqrt(np.mean((matching.astype(np.float64) - matching.mean(axis=(0, 1))) ** 2)))
        if self.matching_spatial_std < config.min_template_std:
            raise ValueError("template has insufficient contrast after the explicit matching filter")
        self.layout_signature = frame.layout_signature
        self._source_json = json.dumps(frame.metadata(), sort_keys=True, allow_nan=False)

    def metadata(self) -> dict[str, Any]:
        return {"landmark_id": self.landmark_id, "eye": self.eye,
                "template_rect": list(self.template_rect),
                "reference_xy": list(self.reference_xy),
                "template_rgb_sha256": self.rgb_sha256,
                "spatial_std": self.spatial_std,
                "matching_filter": _filter_metadata(self.spatial_sigma_px),
                "matching_context_rect": list(self.matching_context_rect),
                "matching_spatial_std": self.matching_spatial_std,
                "reference_source": json.loads(self._source_json)}


def make_template(frame: SourceFrame, landmark_id: str, eye: str,
                  template_rect: Sequence[int], anchor_xy: Sequence[float] | None = None,
                  config: TrackConfig | None = None) -> LandmarkTemplate:
    return LandmarkTemplate(frame, landmark_id, eye, template_rect, anchor_xy,
                            config or TrackConfig())


def _window_sum(values: np.ndarray, height: int, width: int) -> np.ndarray:
    integral = np.zeros((values.shape[0] + 1, values.shape[1] + 1), dtype=np.float64)
    integral[1:, 1:] = values.cumsum(axis=0).cumsum(axis=1)
    return (integral[height:, width:] - integral[:-height, width:]
            - integral[height:, :-width] + integral[:-height, :-width])


def _ncc(region: np.ndarray, template: np.ndarray) -> np.ndarray:
    """Per-channel zero-mean normalized correlation, one channel at a time."""
    height, width = template.shape[:2]
    shape = (region.shape[0] - height + 1, region.shape[1] - width + 1)
    numerator = np.zeros(shape, dtype=np.float64)
    energy = np.zeros(shape, dtype=np.float64)
    template_energy = 0.0
    for channel in range(3):
        image = region[:, :, channel].astype(np.float64)
        patch = template[:, :, channel].astype(np.float64)
        patch -= patch.mean()
        template_energy += float(np.sum(patch * patch))
        numerator += fftconvolve(image, patch[::-1, ::-1], mode="valid")
        sums = _window_sum(image, height, width)
        energy += _window_sum(image * image, height, width) - sums * sums / (height * width)
    denominator = np.sqrt(np.maximum(energy, 0) * template_energy)
    scores = np.full(shape, -np.inf, dtype=np.float64)
    np.divide(numerator, denominator, out=scores, where=denominator > 1e-8)
    np.clip(scores, -1.0, 1.0, out=scores, where=np.isfinite(scores))
    return scores


def _working_bytes(height: int, width: int, patch_height: int, patch_width: int) -> int:
    # Conservative buffer allowance: sequential channel FFTs, integrals,
    # normalized-score arrays and temporary masks. This bounds the planned
    # arrays, not Python/SciPy process RSS or allocator overhead.
    fft_pixels = next_fast_len(height + patch_height - 1) * next_fast_len(width + patch_width - 1)
    return int(256 * fft_pixels + 96 * height * width + 32 * patch_height * patch_width)


def track_landmark(frame: SourceFrame, template: LandmarkTemplate,
                   search_rect: Sequence[int], config: TrackConfig | None = None,
                   *, expected_xy: Sequence[float] | None = None,
                   occlusion_mask: np.ndarray | None = None,
                   occlusion_provenance: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return a JSON-ready original-pixel match with explicit rejection states.

    search_rect specifies pixels containing candidate *whole patches*, rather
    than a range of anchor centers. It is clipped to the explicitly selected
    eye, and this clipping is recorded. A winning candidate at that search
    boundary is untrusted because an excluded candidate may be better.

    An optional full-source bool occlusion mask means True=externally known
    occluded. It requires expected_xy and provenance. It can establish an
    ``occluded`` status at that expected footprint; low NCC alone never can.
    """
    config = config or TrackConfig()
    if frame.layout_signature != template.layout_signature:
        raise ValueError("source coordinate space, dimensions or explicit eye layout changed")
    if config.spatial_sigma_px != template.spatial_sigma_px:
        raise ValueError("matching filter must be identical for reference and current image")
    if template.rgb.shape[0] * template.rgb.shape[1] > config.max_template_pixels:
        raise ValueError("template exceeds pixel budget")
    if template.matching_spatial_std < config.min_template_std:
        raise ValueError("template has insufficient contrast for this configuration")
    requested = _rect(search_rect, "search_rect")
    eye = frame.eyes[template.eye]
    effective = _intersection(requested, eye)
    result: dict[str, Any] = {
        "landmark_id": template.landmark_id, "eye": template.eye,
        "status": "not_found", "reason": None,
        "position_xy": None, "translation_xy": None,
        "candidate_position_xy": None, "candidate_template_rect": None,
        "score": None, "second_peak_score": None, "peak_gap": None,
        "near_equal_peak_count": 0,
        "position_sampling": "integer_translation",
        "quantization_half_width_px": 0.5,
        "accuracy_calibrated": False, "confidence_is_probability": False,
        "matching_filter": _filter_metadata(config.spatial_sigma_px),
        "search_rect": list(requested),
        "effective_search_rect": list(effective) if effective else None,
        "search_clipped_to_eye": effective != requested,
        "working_bytes_estimate": 0,
        "source": frame.metadata(), "template": template.metadata(),
        "config": {key: getattr(config, key) for key in config.__dataclass_fields__},
    }
    expected = _point(expected_xy, "expected_xy") if expected_xy is not None else None
    result["expected_xy"] = list(expected) if expected is not None else None
    if occlusion_mask is not None:
        if (expected is None or occlusion_provenance is None
                or not isinstance(occlusion_mask, np.ndarray)
                or occlusion_mask.dtype != np.bool_
                or occlusion_mask.shape != frame.rgb.shape[:2]):
            raise ValueError("occlusion mask requires full-source bool pixels, expected_xy and provenance")
        result["occlusion_provenance"] = json.loads(_json_copy(occlusion_provenance))
    elif occlusion_provenance is not None:
        raise ValueError("occlusion provenance requires an occlusion mask")
    if expected is not None and not (eye[0] <= expected[0] <= eye[2] - 1
                                     and eye[1] <= expected[1] <= eye[3] - 1):
        result.update(status="out_of_view", reason="explicit_expected_anchor_outside_eye")
        return result
    patch_height, patch_width = template.rgb.shape[:2]
    if effective is None or effective[2] - effective[0] < patch_width or effective[3] - effective[1] < patch_height:
        result.update(status="out_of_view", reason="search_contains_no_complete_template_in_eye")
        return result
    footprint = None
    if expected is not None:
        # Conservative footprint covers any fractional expected translation;
        # no masked-pixel reconstruction or correlation is substituted.
        dx, dy = expected[0] - template.reference_xy[0], expected[1] - template.reference_xy[1]
        footprint = (math.floor(template.template_rect[0] + dx),
                     math.floor(template.template_rect[1] + dy),
                     math.ceil(template.template_rect[2] + dx),
                     math.ceil(template.template_rect[3] + dy))
        if not _contains(eye, footprint):
            result.update(status="out_of_view", reason="explicit_expected_template_crosses_eye_boundary")
            return result
    if occlusion_mask is not None:
        x0, y0, x1, y1 = footprint
        fraction = float(np.mean(occlusion_mask[y0:y1, x0:x1]))
        result["explicit_occlusion_fraction"] = fraction
        if fraction >= config.occlusion_fraction:
            result.update(status="occluded", reason="explicit_occlusion_mask_at_expected_position")
            return result
    x0, y0, x1, y1 = effective
    height, width = y1 - y0, x1 - x0
    estimate = _working_bytes(height, width, patch_height, patch_width)
    if config.spatial_sigma_px:
        context = _filter_context(effective, eye, math.ceil(3 * config.spatial_sigma_px))
        estimate += 64 * (context[2] - context[0]) * (context[3] - context[1])
        result["matching_context_rect"] = list(context)
    result["working_bytes_estimate"] = estimate
    if height * width > config.max_search_pixels or estimate > config.max_working_bytes:
        raise ValueError("search exceeds pixel or working-memory budget")
    scores = _ncc(_matching_pixels(frame, effective, template.eye, config.spatial_sigma_px), template.matching_rgb)
    finite = np.isfinite(scores)
    if not finite.any():
        result["reason"] = "no_candidate_with_spatial_contrast"
        return result
    peak_y, peak_x = np.unravel_index(np.argmax(scores), scores.shape)
    score = float(scores[peak_y, peak_x])
    near_equal = int(np.count_nonzero(finite & (scores >= score - 1e-6)))
    local_x = template.reference_xy[0] - template.template_rect[0]
    local_y = template.reference_xy[1] - template.template_rect[1]
    candidate = [float(x0 + peak_x + local_x), float(y0 + peak_y + local_y)]
    candidate_rect = [int(x0 + peak_x), int(y0 + peak_y),
                      int(x0 + peak_x + patch_width), int(y0 + peak_y + patch_height)]
    result.update(score=score, candidate_position_xy=candidate,
                  candidate_template_rect=candidate_rect, near_equal_peak_count=near_equal)
    radius = config.peak_exclusion_radius_px
    scores[max(0, peak_y - radius):peak_y + radius + 1,
           max(0, peak_x - radius):peak_x + radius + 1] = -np.inf
    second = float(np.max(scores))
    gap = score - second if math.isfinite(second) else None
    result.update(second_peak_score=second if math.isfinite(second) else None, peak_gap=gap)
    if score < config.min_score:
        result["reason"] = "score_below_threshold"
    elif near_equal > 1 or (gap is not None and gap < config.min_peak_gap):
        result.update(status="ambiguous", reason="multiple_indistinguishable_or_near_equal_candidates")
    elif peak_x in (0, scores.shape[1] - 1) or peak_y in (0, scores.shape[0] - 1):
        result.update(status="search_boundary", reason="best_candidate_at_search_boundary")
    else:
        result.update(status="tracked", reason="unique_above_threshold_match", position_xy=candidate,
                      translation_xy=[candidate[0] - template.reference_xy[0],
                                      candidate[1] - template.reference_xy[1]])
    return result


def track_landmarks(frame: SourceFrame, templates: Sequence[LandmarkTemplate],
                    search_rects: Mapping[str, Sequence[int]], config: TrackConfig | None = None,
                    *, consensus_tolerance_px: float = 2.0,
                    min_consensus_landmarks: int = 2) -> dict[str, Any]:
    """Track distinct landmarks and require a unique translation-consensus group.

    One call is restricted to one eye and one reference image. Medians combine
    numeric translation estimates only; source pixels are never combined.
    Individual ambiguous/not-found landmarks are retained as failures, not
    rescued by an expected pose. Equal-support motion groups stay ambiguous.
    """
    config = config or TrackConfig()
    if not 1 <= len(templates) <= config.max_landmarks:
        raise ValueError("landmark count exceeds budget or is empty")
    ids = [template.landmark_id for template in templates]
    if len(set(ids)) != len(ids):
        raise ValueError("landmark IDs must be unique")
    if set(search_rects) != set(ids):
        raise ValueError("each landmark must have exactly one search rectangle")
    if sum(template.rgb.nbytes + (template.matching_rgb.nbytes if template.spatial_sigma_px else 0)
           for template in templates) > config.max_template_bytes_total:
        raise ValueError("combined templates exceed memory budget")
    references = {(template.eye, template._source_json) for template in templates}
    if len(references) != 1:
        raise ValueError("translation consensus requires one eye and one reference source")
    if (isinstance(consensus_tolerance_px, bool) or not isinstance(consensus_tolerance_px, (int, float))
            or not math.isfinite(consensus_tolerance_px) or consensus_tolerance_px < 0):
        raise ValueError("consensus tolerance must be finite and nonnegative")
    if (isinstance(min_consensus_landmarks, bool) or not isinstance(min_consensus_landmarks, Integral)
            or min_consensus_landmarks < 2 or min_consensus_landmarks > config.max_landmarks):
        raise ValueError("translation consensus requires at least two landmarks within the count bound")
    matches = [track_landmark(frame, template, search_rects[template.landmark_id], config)
               for template in templates]
    accepted = [match for match in matches if match["status"] == "tracked"]
    result: dict[str, Any] = {
        "status": "insufficient_evidence", "translation_xy": None,
        "estimate_kind": "per_eye_image_translation_not_6dof",
        "coordinate_space": frame.coordinate_space, "eye": templates[0].eye,
        "quantization_half_width_px": 0.5, "accuracy_calibrated": False,
        "consensus_tolerance_px": consensus_tolerance_px,
        "min_consensus_landmarks": min_consensus_landmarks,
        "inlier_ids": [], "outlier_ids": [], "matches": matches,
    }
    if len(accepted) < min_consensus_landmarks:
        result["reason"] = "too_few_unique_matches"
        return result
    deltas = np.array([match["translation_xy"] for match in accepted], dtype=np.float64)
    distances = np.linalg.norm(deltas[:, None, :] - deltas[None, :, :], axis=2)
    # A cluster is a mutually consistent set, not a chain connecting two
    # distinct motions. Seed neighborhoods failing that check are rejected.
    clusters = set()
    for row in distances:
        indices = tuple(map(int, np.flatnonzero(row <= consensus_tolerance_px)))
        if len(indices) >= min_consensus_landmarks and np.all(distances[np.ix_(indices, indices)] <= consensus_tolerance_px):
            clusters.add(indices)
    if not clusters:
        result.update(status="ambiguous", reason="matched_landmarks_have_inconsistent_translations",
                      limitation="perspective_depth_rotation_or_deformation_can_invalidate_shared_translation")
        return result
    support = max(map(len, clusters))
    best = sorted(cluster for cluster in clusters if len(cluster) == support)
    if len(best) != 1:
        result.update(status="ambiguous", reason="multiple_equal_support_translation_groups")
        return result
    chosen = best[0]
    center = np.median(deltas[list(chosen)], axis=0)
    result.update(status="tracked", reason="unique_translation_consensus",
                  translation_xy=center.tolist(),
                  inlier_ids=[accepted[index]["landmark_id"] for index in chosen],
                  outlier_ids=[match["landmark_id"] for index, match in enumerate(accepted) if index not in chosen],
                  max_inlier_residual_px=float(np.max(np.linalg.norm(deltas[list(chosen)] - center, axis=1))))
    return result
