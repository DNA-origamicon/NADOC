"""Expected application-eye geometry, with explicit image/frame ownership.

Pure offline math; this module never connects to VR or reads/writes files. Eye
poses are OpenXR eye-to-tracking transforms, FOV angles are radians, source
points are nanometers, and tracking positions are meters. Arrays use top-left
pixel-center indices: pixel [y, x] is centered at (x, y), not (x+.5, y+.5).

Application projection is NOT final SteamVR output projection. Lens distortion,
chromatic channels, hidden-area visibility and per-refresh reprojection need
separate measured calibration/association; final-swapchain inputs are rejected.
Frustum inclusion does not establish visibility, occlusion, or pixel evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

import numpy as np

APPLICATION_EYE = "application_eye_undistorted"
FINAL_SWAPCHAIN = "final_swapchain_distorted"


def _array(value, shape, name, *, finite=True):
    result = np.array(value, dtype=np.float64, copy=True)
    if result.shape != shape or (finite and not np.isfinite(result).all()):
        raise ValueError(f"Invalid {name}: expected finite shape {shape}")
    result.setflags(write=False)
    return result


def _points(value, columns, name, *, finite=True):
    result = np.array(value, dtype=np.float64, copy=True)
    if result.ndim != 2 or result.shape[1] != columns:
        raise ValueError(f"{name} must be N by {columns}")
    if np.isinf(result).any() or (finite and not np.isfinite(result).all()):
        raise ValueError(f"Invalid nonfinite {name}")
    result.setflags(write=False)
    return result


def _integer(value, name, *, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < minimum:
        raise ValueError(f"Invalid {name}")


@dataclass(frozen=True)
class FrameIdentity:
    session: str
    frame: int
    predicted_display_time_ns: int

    def __post_init__(self):
        if not isinstance(self.session, str) or not self.session:
            raise ValueError("A nonempty viewer session is required")
        _integer(self.frame, "frame")
        # XrTime is signed int64; its epoch is not promised to be Unix/positive.
        _integer(self.predicted_display_time_ns, "predicted display time", minimum=-(1 << 63))
        if self.predicted_display_time_ns >= 1 << 63:
            raise ValueError("Predicted display time exceeds signed XrTime")


@dataclass(frozen=True)
class EyeCamera:
    eye: str
    width: int
    height: int
    position_m: object
    orientation_xyzw: object
    fov_left_right_up_down: object

    def __post_init__(self):
        if self.eye not in ("left", "right"):
            raise ValueError("Unknown eye")
        _integer(self.width, "image width", minimum=1)
        _integer(self.height, "image height", minimum=1)
        object.__setattr__(self, "position_m", _array(self.position_m, (3,), "eye position"))
        q = _array(self.orientation_xyzw, (4,), "eye quaternion")
        length = float(np.linalg.norm(q))
        if not math.isclose(length, 1., rel_tol=0, abs_tol=1e-4):
            raise ValueError("Eye quaternion must be unit length")
        object.__setattr__(self, "orientation_xyzw", _array(q/length, (4,), "eye quaternion"))
        angles = _array(self.fov_left_right_up_down, (4,), "eye FOV")
        if np.any(np.abs(angles) >= math.pi/2):
            raise ValueError("Eye FOV must be inside (-pi/2, pi/2)")
        left, right, up, down = np.tan(angles)
        if right <= left or up <= down:
            raise ValueError("Eye FOV has nonpositive extent")
        object.__setattr__(self, "fov_left_right_up_down", angles)

    @classmethod
    def from_metadata(cls, eye):
        return cls(eye["eye"], eye["width"], eye["height"], eye["position"],
                   eye["orientation_xyzw"], eye["fov_left_right_up_down"])


def source_to_tracking_matrix(presentation: Mapping):
    """Compose the viewer's source normalization and current model transform."""
    model = _array(presentation["model_to_tracking_rows"], (4, 4), "model matrix")
    if not np.allclose(model[3], [0, 0, 0, 1], atol=1e-12, rtol=0):
        raise ValueError("Model matrix must be affine")
    center = _array(presentation["source_center_nm"], (3,), "source center")
    offset = _array(presentation["normalized_offset_model"], (3,), "normalization offset")
    scale = float(presentation["normalization_model_per_nm"])
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("Source normalization scale must be positive")
    normalization = np.diag([scale, scale, scale, 1.])
    normalization[:3, 3] = offset-scale*center
    result = model @ normalization
    if not np.isfinite(result).all() or np.linalg.matrix_rank(result[:3, :3]) != 3:
        raise ValueError("Source-to-tracking matrix must be finite and invertible")
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class ApplicationFrame:
    """One eye and model sampled coherently in a successful application frame.

    Factories consume one native journal row or one existing live capture. They
    deliberately cannot combine a latest observation with an older image. A
    successful xrEndFrame is application submission, not compositor acceptance.
    """
    identity: FrameIdentity
    camera: EyeCamera
    source_to_tracking_rows: object

    def __post_init__(self):
        if not isinstance(self.identity, FrameIdentity) or not isinstance(self.camera, EyeCamera):
            raise ValueError("Typed frame identity and eye camera required")
        matrix = _array(self.source_to_tracking_rows, (4, 4), "source-to-tracking matrix")
        if not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-12, rtol=0) or np.linalg.matrix_rank(matrix[:3, :3]) != 3:
            raise ValueError("Source-to-tracking matrix must be invertible affine")
        object.__setattr__(self, "source_to_tracking_rows", matrix)

    @classmethod
    def from_journal(cls, header: Mapping, row: Mapping, eye: str):
        if row.get("source") != "application_projection":
            raise ValueError("Journal source is not application projection")
        if row.get("submitted") is not True or row.get("xr_end_frame_succeeded") is not True:
            raise ValueError("Journal frame was not successfully submitted")
        candidates = [item for item in row["eyes"] if item.get("eye") == eye]
        if len(candidates) != 1 or candidates[0].get("rendered") is not True:
            raise ValueError("One rendered matching eye is required")
        identity = FrameIdentity(header["session"], row["frame"], row["predicted_display_time_ns"])
        presentation = dict(row["presentation"])
        # New journals retain the exact model uniform at this eye's draw.
        # Normalization remains frame-owned; never substitute an observer pose.
        if "model_to_tracking_rows" in candidates[0]:
            presentation["model_to_tracking_rows"] = candidates[0]["model_to_tracking_rows"]
        return cls(identity, EyeCamera.from_metadata(candidates[0]), source_to_tracking_matrix(presentation))

    @classmethod
    def from_capture_evidence(cls, evidence: Mapping, eye: str):
        if evidence.get("source") != "application_swapchain" or evidence.get("xr_end_frame_succeeded") is not True:
            raise ValueError("Evidence is not a successfully submitted application-eye capture")
        candidates = [item for item in evidence["eyes"] if item.get("eye") == eye]
        if len(candidates) != 1:
            raise ValueError("One matching capture eye is required")
        state = evidence["state"]
        identity = FrameIdentity(state["session"], state["frame"], state["predicted_display_time"])
        return cls(identity, EyeCamera.from_metadata(candidates[0]), source_to_tracking_matrix(state["presentation"]))


@dataclass(frozen=True)
class ImagePoints:
    xy: object
    coordinate_space: str
    eye: str
    width: int
    height: int
    frame: FrameIdentity

    def __post_init__(self):
        if self.coordinate_space not in (APPLICATION_EYE, FINAL_SWAPCHAIN):
            raise ValueError("Unknown image coordinate space")
        if self.eye not in ("left", "right") or not isinstance(self.frame, FrameIdentity):
            raise ValueError("Explicit eye and frame identity required")
        _integer(self.width, "image width", minimum=1)
        _integer(self.height, "image height", minimum=1)
        object.__setattr__(self, "xy", _points(self.xy, 2, "image points", finite=False))

    @property
    def ownership(self):
        return self.coordinate_space, self.eye, self.width, self.height, self.frame


@dataclass(frozen=True)
class ProjectedPoints:
    image: ImagePoints
    forward_depth_m: np.ndarray
    in_front: np.ndarray
    inside_image: np.ndarray


@dataclass(frozen=True)
class UnprojectedPoints:
    source_nm: np.ndarray
    valid: np.ndarray


def _rotation(camera):
    x, y, z, w = camera.orientation_xyzw
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def _image(xy, frame):
    c = frame.camera
    return ImagePoints(xy, APPLICATION_EYE, c.eye, c.width, c.height, frame.identity)


def project_source_points(points_nm, frame: ApplicationFrame) -> ProjectedPoints:
    """Project source points, without claiming fragment/hidden-area visibility."""
    points = _points(points_nm, 3, "source points")
    c = frame.camera
    matrix = frame.source_to_tracking_rows
    tracking = points @ matrix[:3, :3].T + matrix[:3, 3]
    eye = (tracking-c.position_m) @ _rotation(c)
    depth = -eye[:, 2]
    front = depth > 0
    xy = np.full((len(points), 2), np.nan)
    left, right, up, down = np.tan(c.fov_left_right_up_down)
    u = (eye[front, 0]/depth[front]-left)/(right-left)
    v = (up-eye[front, 1]/depth[front])/(up-down)
    xy[front] = np.column_stack((u*c.width-.5, v*c.height-.5))
    inside = np.zeros(len(points), dtype=bool)
    inside[front] = (u >= 0) & (u < 1) & (v >= 0) & (v < 1)
    for value in (depth, front, inside): value.setflags(write=False)
    return ProjectedPoints(_image(xy, frame), depth, front, inside)


def projection_residuals(expected: ProjectedPoints, measured: ImagePoints):
    """Measured minus expected pixels; never snap or silently cross image spaces."""
    if expected.image.ownership != measured.ownership or expected.image.xy.shape != measured.xy.shape:
        raise ValueError("Image/frame ownership or point correspondence mismatch")
    if expected.image.coordinate_space != APPLICATION_EYE:
        raise ValueError("Expected projection ownership must be application-eye")
    result = measured.xy-expected.image.xy
    result.setflags(write=False)
    return result


def unproject_application_depth(pixels: ImagePoints, window_depth, frame: ApplicationFrame,
                                *, near_m: float, far_m: float) -> UnprojectedPoints:
    """Unproject captured OpenGL window depth to source-nm surface samples.

    Depth must already be sampled at these same top-left pixels; native .f32
    files are bottom-up and must be flipped when read. Depth=1 is background.
    This math does not identify the model: callers must independently require
    the design class/RGB evidence and exclude UI, controllers and markers.
    """
    if pixels.ownership != _image(np.empty((0, 2)), frame).ownership:
        raise ValueError("Application image/frame ownership mismatch")
    if not (np.isfinite(near_m) and np.isfinite(far_m) and 0 < near_m < far_m):
        raise ValueError("Invalid near/far depth range")
    depth = np.asarray(window_depth, dtype=np.float64)
    if depth.shape != (len(pixels.xy),):
        raise ValueError("Depth samples must correspond one-to-one to image points")
    c = frame.camera
    uv = (pixels.xy+.5)/[c.width, c.height]
    valid = np.isfinite(depth) & np.isfinite(pixels.xy).all(axis=1)
    valid &= (depth >= 0) & (depth < 1) & (uv >= 0).all(axis=1) & (uv < 1).all(axis=1)
    forward = near_m*far_m/(far_m-depth[valid]*(far_m-near_m))
    left, right, up, down = np.tan(c.fov_left_right_up_down)
    eye = np.column_stack(((left+uv[valid, 0]*(right-left))*forward,
                           (up-uv[valid, 1]*(up-down))*forward, -forward))
    tracking = eye @ _rotation(c).T + c.position_m
    inverse = np.linalg.inv(frame.source_to_tracking_rows)
    source = np.full((len(depth), 3), np.nan)
    source[valid] = tracking @ inverse[:3, :3].T + inverse[:3, 3]
    source.setflags(write=False); valid.setflags(write=False)
    return UnprojectedPoints(source, valid)
