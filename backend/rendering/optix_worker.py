"""Persistent Blender/Cycles worker for display-only native preview and exports.

Launched by optix_service, never imports or writes a NADOC molecular document.
All input/output paths are supplied by the owning service in its temporary root.
"""
import base64
import json
import math
import os
from pathlib import Path
import sys
import time

import bpy
from mathutils import Euler, Matrix, Vector
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from optix_emitters import expand_cloud, cloud_update_kind, cloud_emission, cloud_illumination
from optix_sampling import configure_sampling, configure_emission, configure_sample_chunk
from optix_volumes import NativeVolumes


def unpack(value, dtype="<f4"):
    result = np.asarray(value, dtype=dtype) if isinstance(value, np.ndarray) else np.frombuffer(base64.b64decode(value, validate=True), dtype=dtype)
    if dtype == "<f4" and not np.isfinite(result).all():
        raise ValueError("Non-finite render attributes")
    return result


def material(spec, name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    shader = nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*spec["color"], 1)
    shader.inputs["Metallic"].default_value = spec["metalness"]
    shader.inputs["Roughness"].default_value = spec["roughness"]
    (shader.inputs.get("Coat Weight") or shader.inputs["Clearcoat"]).default_value = spec.get("clearcoat", 0)
    (shader.inputs.get("Coat Roughness") or shader.inputs["Clearcoat Roughness"]).default_value = spec.get("clearcoatRoughness", .03)
    shader.inputs["IOR"].default_value = spec.get("ior", 1.5)
    emission_socket = shader.inputs.get("Emission Color") or shader.inputs["Emission"]
    emission_socket.default_value = (*spec["emission"], 1)
    shader.inputs["Emission Strength"].default_value = 1
    vertex = nodes.new("ShaderNodeVertexColor")
    vertex.layer_name = "nadoc_color"
    multiply = nodes.new("ShaderNodeMixRGB")
    multiply.blend_type = "MULTIPLY"
    multiply.inputs[0].default_value = 1
    multiply.inputs[2].default_value = (*spec["color"], 1)
    links.new(vertex.outputs["Color"], multiply.inputs[1])
    links.new(multiply.outputs[0], shader.inputs["Base Color"])
    alpha = nodes.new("ShaderNodeMath")
    alpha.operation = "MULTIPLY"
    alpha.inputs[1].default_value = spec["opacity"]
    links.new(vertex.outputs["Alpha"], alpha.inputs[0])
    links.new(alpha.outputs[0], shader.inputs["Alpha"])
    if spec.get("palette") or spec.get("emitter"):
        configure_emission(mat)
        emission = nodes.new("ShaderNodeVertexColor")
        emission.layer_name = "nadoc_emission"
        multiply_emission = nodes.new("ShaderNodeMixRGB")
        multiply_emission.blend_type = "MULTIPLY"
        multiply_emission.inputs[0].default_value = 1
        multiply_emission.inputs[2].default_value = (*spec["emission"], 1)
        source = emission.outputs["Color"]
        if spec.get("normalized_em"):
            illumination = nodes.new("ShaderNodeVertexColor")
            illumination.layer_name = "nadoc_illumination"
            path = nodes.new("ShaderNodeLightPath")
            visible = nodes.new("ShaderNodeMixRGB")
            links.new(path.outputs["Is Camera Ray"], visible.inputs[0])
            links.new(illumination.outputs["Color"], visible.inputs[1])
            links.new(source, visible.inputs[2])
            source = visible.outputs[0]
        links.new(source, multiply_emission.inputs[1])
        links.new(multiply_emission.outputs[0], emission_socket)
    return mat


def report(stage, label, fraction=None):
    print("NADOC_PROGRESS " + json.dumps({"stage": stage, "label": label, "fraction": fraction}), flush=True)


def mesh_object(spec, index, retained, progress=lambda value: None):
    position = unpack(spec["position"]).reshape(-1, 3)
    indices = unpack(spec["index"], "<u4").reshape(-1, 3)
    if len(indices) and indices.max() >= len(position):
        raise ValueError("Invalid render mesh indices")
    progress(1 / 5)
    obj = retained.get(index)
    if obj is None or obj[1].shape != indices.shape or not np.array_equal(obj[1], indices) or len(obj[0].data.vertices) != len(position):
        if obj:
            old = obj[0].data
            bpy.data.objects.remove(obj[0], do_unlink=True)
            bpy.data.meshes.remove(old)
        mesh = bpy.data.meshes.new(f"display-{index}")
        mesh.from_pydata(position.tolist(), [], indices.tolist())
        obj = bpy.data.objects.new(f"display-{index}", mesh)
        bpy.context.scene.collection.objects.link(obj)
        retained[index] = (obj, indices.copy())
    else:
        obj = obj[0]
        mesh = obj.data
        mesh.vertices.foreach_set("co", position.ravel())
    progress(2 / 5)
    mesh.materials.clear()
    for j, spec_material in enumerate(spec["materials"]):
        mesh.materials.append(material(spec_material, f"material-{index}-{j}"))
    face_material = np.zeros(len(indices), dtype=np.int32)
    for group in spec["groups"]:
        start = group["start"] // 3
        face_material[start:start + group["count"] // 3] = group["materialIndex"]
    mesh.polygons.foreach_set("material_index", face_material)
    progress(3 / 5)
    colors = unpack(spec["color"]).reshape(-1, 4)
    attribute = mesh.color_attributes.get("nadoc_color") or mesh.color_attributes.new(name="nadoc_color", type="FLOAT_COLOR", domain="CORNER")
    attribute.data.foreach_set("color", colors[indices.ravel()].ravel())
    palettes = [m.get("palette") for m in spec["materials"]]
    if "emission" in spec:
        attribute = mesh.color_attributes.get("nadoc_emission") or mesh.color_attributes.new(name="nadoc_emission", type="FLOAT_COLOR", domain="CORNER")
        attribute.data.foreach_set("color", spec["emission"][indices.ravel()].ravel())
    if spec.get("illumination") is not None:
        attribute = mesh.color_attributes.get("nadoc_illumination") or mesh.color_attributes.new(name="nadoc_illumination", type="FLOAT_COLOR", domain="CORNER")
        attribute.data.foreach_set("color", spec["illumination"][indices.ravel()].ravel())
    if any(palettes):
        if len(palettes) != 1:
            raise ValueError("EM palettes require one material per cloud")
        palette = palettes[0]
        uv = unpack(spec["uv"]).reshape(-1, 2)
        x = np.clip((uv[:, 0] * palette["width"]).astype(int), 0, palette["width"] - 1)
        y = np.clip((uv[:, 1] * palette["height"]).astype(int), 0, palette["height"] - 1)
        emission = unpack(palette["data"]).reshape(-1, 4)[y * palette["width"] + x]
        attribute = mesh.color_attributes.get("nadoc_emission") or mesh.color_attributes.new(name="nadoc_emission", type="FLOAT_COLOR", domain="CORNER")
        attribute.data.foreach_set("color", emission[indices.ravel()].ravel())
    progress(4 / 5)
    normals = unpack(spec["normal"]).reshape(-1, 3)
    mesh.polygons.foreach_set("use_smooth", np.ones(len(indices), dtype=bool))
    mesh.normals_split_custom_set_from_vertices(normals.tolist())
    mesh.update()
    progress(1)


def world_scene(data):
    scene = bpy.context.scene
    world = scene.world
    world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    nodes.clear()
    env = data["environment"]
    image = bpy.data.images.get("environment")
    if image:
        bpy.data.images.remove(image)
    image = bpy.data.images.new("environment", env["width"], env["height"], float_buffer=True)
    image.colorspace_settings.name = "Non-Color"
    image.pixels.foreach_set(unpack(env["data"]))
    image.update()
    texture = nodes.new("ShaderNodeTexEnvironment")
    texture.image = image
    coords = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    mapping.name = "nadoc_rotation"
    rotate_world(data["rotation"])
    links.new(coords.outputs["Generated"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], texture.inputs["Vector"])
    background = nodes.new("ShaderNodeBackground")
    links.new(texture.outputs["Color"], background.inputs["Color"])
    output = nodes.new("ShaderNodeOutputWorld")
    links.new(background.outputs[0], output.inputs["Surface"])
    scene.render.film_transparent = True
    # Transparent film is composited over the exact NADOC background after readback.
    lights_scene(data["lights"])


def rotate_world(rotation):
    mapping = bpy.context.scene.world.node_tree.nodes["nadoc_rotation"]
    mapping.inputs["Rotation"].default_value = (
        Euler((math.pi / 2, 0, 0)).to_matrix() @ Euler(tuple(rotation)).to_matrix()
    ).to_euler()


def lights_scene(lights):
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        if obj.type == "LIGHT":
            light = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.lights.remove(light)
    for i, entry in enumerate(lights):
        kind = {"DirectionalLight": "SUN", "PointLight": "POINT", "SpotLight": "SPOT", "RectAreaLight": "AREA"}[entry["type"]]
        light = bpy.data.lights.new(f"light-{i}", kind)
        light.color = entry["color"]
        light.energy = entry["intensity"] * (4 * math.pi if kind in ("POINT", "SPOT") else 1)
        obj = bpy.data.objects.new(light.name, light)
        scene.collection.objects.link(obj)
        obj.location = entry["position"]
        if entry.get("target"):
            obj.rotation_euler = (Vector(entry["target"]) - obj.location).to_track_quat("-Z", "Y").to_euler()
        elif entry.get("quaternion"):
            x, y, z, w = entry["quaternion"]
            obj.rotation_mode = "QUATERNION"
            obj.rotation_quaternion = (w, x, y, z)
        if kind == "AREA":
            light.shape = "RECTANGLE"
            light.size, light.size_y = entry["width"], entry["height"]
        if kind == "SPOT":
            light.spot_size, light.spot_blend = 2 * entry["angle"], entry["penumbra"]


def render(data, output, retained, update_scene=True, emitter_retained=None, emitter_specs=None, volumes=None):
    bpy.context.scene.cycles.transparent_max_bounces = 160 if data.get("smoothEM") else 5
    emitter_retained = {} if emitter_retained is None else emitter_retained
    emitter_specs = {} if emitter_specs is None else emitter_specs
    emitter_updates = {"geometry": 0, "attributes": 0, "unchanged": 0}
    started = time.perf_counter()
    if any(type(data[k]) is not int or not 1 <= data[k] <= limit for k, limit in (("width", 2048), ("height", 2048), ("samples", 512))):
        raise ValueError("Invalid OptiX tile dimensions or samples")
    report("geometry" if update_scene else "acceleration", "Preparing OptiX geometry and materials" if update_scene else "Updating retained OptiX scene")
    scene = bpy.context.scene
    if update_scene:
        for i in list(retained):
            if i >= len(data["meshes"]):
                obj, _ = retained.pop(i)
                mesh = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                bpy.data.meshes.remove(mesh)
        # Weight mesh substeps by encoded attribute bytes, rather than counting
        # a million-atom mesh as equal to a small nanoparticle mesh.
        weights = [sum(len(mesh.get(key, "")) for key in ("position", "index", "normal", "color", "uv")) for mesh in data["meshes"]]
        total = max(1, sum(weights))
        completed = 0
        for i, mesh in enumerate(data["meshes"]):
            mesh_object(mesh, i, retained, lambda fraction: report(
                "geometry", f"Native mesh {i + 1}/{len(weights)} · step {round(fraction * 5)}/5",
                (completed + weights[i] * fraction) / total))
            completed += weights[i]
        for mat in list(bpy.data.materials):
            if mat.users == 0:
                bpy.data.materials.remove(mat)
        world_scene(data)
    elif "lights" in data:
        lights_scene(data["lights"])
        rotate_world(data["rotation"])
    if update_scene or "emitters" in data:
        clouds = data.get("emitters", [])
        for i in list(emitter_retained):
            if i >= len(clouds):
                emitter_specs.pop(i, None)
                obj, _ = emitter_retained.pop(i)
                mesh = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                bpy.data.meshes.remove(mesh)
        for i, cloud in enumerate(clouds):
            report("geometry", f"Updating EM cloud {i + 1}/{len(clouds)}", i / max(1, len(clouds)))
            kind = cloud_update_kind(cloud, emitter_specs.get(i))
            emitter_updates[kind] += 1
            if kind == "geometry":
                mesh_object(expand_cloud(cloud), i, emitter_retained)
            elif kind == "attributes":
                emission, opacity = cloud_emission(cloud)
                mesh = emitter_retained[i][0].data
                mesh.color_attributes["nadoc_emission"].data.foreach_set("color", emission.ravel())
                illumination = cloud_illumination(cloud)
                if illumination is not None:
                    mesh.color_attributes["nadoc_illumination"].data.foreach_set("color", illumination.ravel())
                # Retain mesh, connectivity, normals and shader graph.
                alpha = next(node for node in mesh.materials[0].node_tree.nodes if node.type == "MATH")
                alpha.inputs[1].default_value = opacity
                mesh.update()
            emitter_specs[i] = cloud
        for mat in list(bpy.data.materials):
            if mat.users == 0:
                bpy.data.materials.remove(mat)
    if volumes is not None and (update_scene or "volumes" in data):
        volumes.update(data.get("volumes", []), report)
    width, height = data["width"], data["height"]
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.render.resolution_percentage = 100
    configure_sample_chunk(scene.cycles, data)
    camera = scene.camera
    camera.matrix_world = Matrix(np.array(data["camera"]["matrix"]).reshape(4, 4).T.tolist())
    projection = data["camera"]["projection"]
    camera.data.type = "ORTHO" if data["camera"]["orthographic"] else "PERSP"
    camera.data.sensor_fit = "HORIZONTAL"
    camera.data.sensor_width = 36
    camera.data.lens = 18 * projection[0]
    camera.data.ortho_scale = 2 / projection[0]
    camera.data.shift_x = projection[8] / 2 if camera.data.type == "PERSP" else -projection[12] / 2
    camera.data.shift_y = (projection[9] if camera.data.type == "PERSP" else -projection[13]) / (2 * width / height)
    exr = str(Path(output).with_suffix(".exr"))
    scene.render.filepath = exr
    bpy.context.view_layer.update()
    report("acceleration", "Building OptiX acceleration structures")
    prepared = time.perf_counter()
    try:
        bpy.ops.render.render(write_still=True)
    finally:
        if volumes is not None:
            volumes.release_retired()
    rendered = time.perf_counter()
    report("readback", "Reading OptiX pixels", 0)
    image = bpy.data.images.load(exr, check_existing=False)
    pixels = np.empty(width * height * 4, dtype=np.float32)
    report("readback", "Loaded rendered EXR · copying pixels", 1 / 3)
    image.pixels.foreach_get(pixels)
    bpy.data.images.remove(image)
    Path(exr).unlink()
    rgba = pixels.reshape(-1, 4)
    stats = {"alpha_max": float(rgba[:, 3].max()), "color_max": float(rgba[:, :3].max()),
             "camera_z": float(camera.matrix_world.translation.z), "meshes": len(retained)}
    if not data["transparent"]:
        color = data["background"].lstrip("#")
        rgb = np.array([int(color[i:i+2], 16) / 255 for i in (0, 2, 4)])
        rgb = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
        rgba[:, :3] += (1 - rgba[:, 3:4]) * rgb
        rgba[:, 3] = 1
    report("readback", "Compositing complete · writing pixels", 2 / 3)
    pixels.tofile(output)
    report("readback", "Native pixel output ready", 1)
    stats["em_volume_cells"] = volumes.cell_count if volumes is not None else 0
    stats.update(em_updates=emitter_updates, scene_reused=not update_scene, em_clouds=len(emitter_retained), em_updated="emitters" in data, samples=data["samples"],
                 prepare_ms=(prepared-started)*1000, render_ms=(rendered-prepared)*1000,
                 readback_ms=(time.perf_counter()-rendered)*1000,
                 worker_ms=(time.perf_counter()-started)*1000)
    return stats


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from optix_frame_state import resolve_frame
    print("NADOC_PID " + str(os.getpid()), flush=True)
    if "--" in sys.argv:
        scratch = sys.argv[sys.argv.index("--") + 1]
        for key in ("TEMP", "TMP", "TMPDIR"):
            os.environ[key] = scratch
    # Keep driver-managed CUDA/OptiX caches across sessions (and honor explicit
    # cache environment overrides). Only frame scratch is session-owned.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.refresh_devices()
    devices = [d for d in prefs.devices if d.type == "OPTIX"]
    if not devices:
        raise RuntimeError("No OptiX GPU found. CPU fallback is disabled. On WSL, configure a native Windows Blender executable with NADOC_BLENDER.")
    for device in prefs.devices:
        device.use = device == devices[0]
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU"
    scene.cycles.max_bounces = 5
    scene.cycles.transparent_max_bounces = 5
    scene.cycles.use_denoising = False
    scene.cycles.use_adaptive_sampling = False
    scene.render.use_persistent_data = True
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 2
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "32"
    scene.view_settings.view_transform = "Raw"
    scene.world = bpy.data.worlds.new("NADOC studio")
    camera = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera.data.clip_start, camera.data.clip_end = .00001, 1e8
    capabilities = configure_sampling(scene, bpy.app.version_string)
    print("NADOC_READY " + json.dumps({"device": devices[0].name, "capabilities": capabilities}), flush=True)
    retained = {}
    emitter_retained = {}
    emitter_specs = {}
    volumes = NativeVolumes()
    scene_state = None
    for line in sys.stdin:
        try:
            command = json.loads(line)
            report("decode", "Reading / decoding transferred scene")
            data, next_state, update_scene = resolve_frame(json.loads(Path(command["input"]).read_text()), scene_state)
            stats = render(data, command["output"], retained, update_scene, emitter_retained, emitter_specs, volumes)
            stats.update(capabilities)
            scene_state = next_state
            print("NADOC_DONE " + json.dumps(stats), flush=True)
        except Exception as error:
            print("NADOC_ERROR " + str(error), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("NADOC_ERROR " + str(error), flush=True)
