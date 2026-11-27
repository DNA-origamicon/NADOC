"""Compact EM display clouds; no molecular documents or authoring operations."""
import base64

import numpy as np


def cloud_update_kind(cloud, previous):
    """Compare compact wire data, retaining only one prior cloud per renderer."""
    if previous is None or ("power" in cloud) != ("power" in previous) or any(cloud[key] != previous[key] for key in ("centers", "radii", "template")):
        return "geometry"
    return "unchanged" if cloud == previous else "attributes"


def cloud_emission(cloud):
    radii = array(cloud["radii"], "<f8").reshape(-1)
    colors = array(cloud["colors"]).reshape(-1, 3)
    opacity = float(cloud["opacity"])
    if len(colors) != len(radii) or not np.isfinite(opacity) or not 0 <= opacity <= 1:
        raise ValueError("Invalid compact EM cloud")
    emission = np.ones((np.count_nonzero(radii ** 3 >= 1e-14) * 60, 4), dtype=np.float32)
    emission[:, :3] = np.repeat(colors[radii ** 3 >= 1e-14], 60, axis=0)
    return emission, opacity


def cloud_illumination(cloud):
    if "power" not in cloud:
        return None
    radii = array(cloud["radii"], "<f8").reshape(-1)
    power = array(cloud["power"]).reshape(-1, 3)
    if len(power) != len(radii) or np.any(power < 0):
        raise ValueError("Invalid EM illumination power")
    template = array(cloud["template"]["position"]).reshape(-1, 3, 3).astype(np.float64)
    area = np.linalg.norm(np.cross(template[:, 1] - template[:, 0], template[:, 2] - template[:, 0]), axis=1).sum() / 2
    if not np.isfinite(area) or area <= 0:
        raise ValueError("Invalid EM emitter surface area")
    valid = radii ** 3 >= 1e-14
    # Two emitting sides, Lambertian integral pi, material emission strength 2.
    radiance = power[valid] / (4 * np.pi * area * radii[valid, None] ** 2)
    result = np.ones((np.count_nonzero(valid) * 60, 4), dtype=np.float32)
    result[:, :3] = np.repeat(radiance, 60, axis=0)
    if not np.isfinite(result).all():
        raise ValueError("EM illumination exceeds float32 range")
    return result


def array(value, dtype="<f4"):
    result = np.asarray(value, dtype=dtype) if isinstance(value, np.ndarray) else np.frombuffer(base64.b64decode(value, validate=True), dtype=dtype)
    if not np.isfinite(result).all():
        raise ValueError("Non-finite EM emitter attribute")
    return result


def expand_cloud(cloud):
    """Expand the supplied Three.js template, retaining legacy float rounding."""
    centers = array(cloud["centers"], "<f8").reshape(-1, 3)
    radii = array(cloud["radii"], "<f8").reshape(-1)
    colors = array(cloud["colors"]).reshape(-1, 3)
    template = array(cloud["template"]["position"]).reshape(-1, 3)
    normals = array(cloud["template"]["normal"]).reshape(-1, 3)
    opacity = float(cloud["opacity"])
    if (len(centers) != len(radii) or len(colors) != len(radii)
            or template.shape != (60, 3) or normals.shape != template.shape
            or not np.isfinite(opacity) or not 0 <= opacity <= 1 or np.any(radii <= 0)):
        raise ValueError("Invalid compact EM cloud")
    # Match the legacy snapshot's degenerate-transform rejection.
    valid = radii ** 3 >= 1e-14
    centers, radii, colors = centers[valid], radii[valid], colors[valid]
    count = len(radii)
    position = (centers[:, None, :] + radii[:, None, None] * template[None, :, :]).astype(np.float32).reshape(-1, 3)
    normal = np.tile(normals, (count, 1))
    rgba = np.ones((count * 60, 4), dtype=np.float32)
    emission = np.ones_like(rgba)
    emission[:, :3] = np.repeat(colors, 60, axis=0)
    illumination = cloud_illumination(cloud)
    return dict(position=position, normal=normal, color=rgba, emission=emission, illumination=illumination,
                index=np.arange(count * 60, dtype=np.uint32), groups=[],
                materials=[dict(color=[0, 0, 0], emission=[2, 2, 2], roughness=1,
                                metalness=0, opacity=opacity, emitter=True, normalized_em=illumination is not None)])
