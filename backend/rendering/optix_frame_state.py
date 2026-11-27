"""Retained display-scene protocol, independent of Blender and document state."""


def resolve_frame(data, previous):
    if "meshes" in data:
        return data, {key: data[key] for key in ("background", "transparent", "smoothEM") if key in data}, True
    if data.get("reuse_scene") is not True or previous is None:
        raise ValueError("OptiX requires a complete scene before camera-only frames")
    if "environment" in data:
        raise ValueError("An environment change requires a complete OptiX scene update")
    if ("lights" in data) != ("rotation" in data):
        raise ValueError("OptiX lights and rotation must be updated together")
    return {**previous, **data}, previous, False
