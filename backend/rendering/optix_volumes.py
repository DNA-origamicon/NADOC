"""Native reflected-ray emission on original tetrahedra; no document authoring.

Linked unit tetrahedra share geometry and a shader per field. Object-space
coordinates are barycentrics; four instance attributes store source values.
Blender 3.3 compatibility uses per-object RGBA instead.
No contour extraction, voxel resampling, absorption, or scattering is involved.
"""
import math
import numpy as np
try:
    from .optix_emitters import array
except ImportError:  # Standalone Blender worker.
    from optix_emitters import array


def decode_volume(spec):
    points = [array(p).reshape(-1, 3) for p in spec["positions"]]
    values = array(spec["values"]).reshape(-1, 4)
    palette = array(spec["palette"]).reshape(256, 4)
    if len(points) != 4 or any(len(p) != len(values) for p in points):
        raise ValueError("Invalid adaptive EM volume dimensions")
    scalars = [float(spec[k]) for k in ("minimum", "colorLow", "colorHigh", "weight")]
    if not all(math.isfinite(v) for v in scalars) or not 0 < scalars[1] < scalars[2] or not 0 <= scalars[3] <= 1 or np.any(values < 0):
        raise ValueError("Invalid adaptive EM volume transfer")
    return points, values, palette


class NativeVolumes:
    def __init__(self):
        self.objects, self.meshes, self.materials = [], [], []
        self.roots, self.retired, self.collections = [], [], []
        self.generation = 0
        self.node_groups = []
        self.cell_count = 0

    def clear(self):
        import bpy
        if self.objects or self.roots or self.collections:
            bpy.data.batch_remove(self.objects + self.roots + self.collections)
        self.collections.clear()
        if self.node_groups:
            bpy.data.batch_remove(self.node_groups)
        self.node_groups.clear()
        for data, collection in [(self.meshes, bpy.data.meshes), (self.materials, bpy.data.materials)]:
            for item in data:
                collection.remove(item)
            data.clear()
        self.objects.clear()
        self.roots.clear()
        self.cell_count = 0
        self.release_retired()

    def release_retired(self):
        for previous in self.retired:
            previous.clear()
        self.retired.clear()

    def update(self, specs, report=lambda *args: None):
        import bpy
        # Allocate the replacement while prior datablocks are still alive.
        # Cycles' persistent ID maps must not see recycled object/material
        # pointers as unchanged resources on a warm frame.
        collection = bpy.context.scene.collection
        previous = NativeVolumes()
        previous.node_groups, self.node_groups = self.node_groups, []
        previous.cell_count, self.cell_count = self.cell_count, 0
        previous.objects, previous.meshes, previous.materials = self.objects, self.meshes, self.materials
        previous.roots, self.roots = self.roots, []
        previous.collections, self.collections = self.collections, []
        self.objects, self.meshes, self.materials = [], [], []
        self.generation += 1
        try:
            for field, spec in enumerate(specs):
                points, values, palette = decode_volume(spec)
                if not len(values):
                    continue
                maximum = max(1, float(values.max()))
                mat = self.material(spec, palette, maximum)
                mesh = bpy.data.meshes.new(f"em-unit-tetra-{self.generation}-{field}")
                self.meshes.append(mesh)
                vertices = np.array([(1, 0, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)], dtype=float)
                # Separate coincident boundaries; shader membership below keeps
                # emission inside the unexpanded cell (no energy overlap).
                vertices = (vertices - .25) * 1.001 + .25
                mesh.from_pydata(vertices.tolist(), [], [(0, 1, 2), (0, 3, 1), (0, 2, 3), (1, 3, 2)])
                mesh.materials.append(mat)
                try:
                    if bpy.app.version >= (3, 4, 0):
                        from .optix_volume_nodes import instances
                    else:
                        from .optix_volume_instances import instances
                except ImportError:
                    if bpy.app.version >= (3, 4, 0):
                        from optix_volume_nodes import instances
                    else:
                        from optix_volume_instances import instances
                instances(self, mesh, points, values, maximum, self.generation * 1000 + field, report)
                # Shadow paths cannot receive this reflection-only emission.
                # Keep other visibility: Cycles needs their volume stack when a
                # subsequent reflection starts inside an emitting cell.
                for group in self.collections:
                    group.objects.foreach_set('visible_shadow', np.zeros(len(group.objects), dtype=bool))
                self.cell_count += len(values)
        except Exception:
            self.clear()
            self.objects, self.meshes, self.materials = previous.objects, previous.meshes, previous.materials
            self.roots = previous.roots
            self.collections = previous.collections
            self.node_groups = previous.node_groups
            self.cell_count = previous.cell_count
            raise
        # Keep retired IDs alive until Cycles has synchronized their removal.
        # Releasing them before render can alias cached Cycles resource IDs.
        for group in previous.collections:
            if group.name in collection.children:
                collection.children.unlink(group)
        self.retired.append(previous)

    def material(self, spec, palette, maximum):
        import bpy
        mat = bpy.data.materials.new(f"EM reflected volume {self.generation}")
        self.materials.append(mat)
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        nodes.clear()

        def node(kind):
            return nodes.new("ShaderNode" + kind)

        def connect(value, socket):
            if isinstance(value, (int, float)):
                socket.default_value = value
            else:
                links.new(value, socket)

        def math_node(operation, a, b=0):
            n = node("Math"); n.operation = operation
            connect(a, n.inputs[0]); connect(b, n.inputs[1])
            return n.outputs[0]

        def separate(vector):
            n = node("SeparateXYZ"); links.new(vector, n.inputs[0])
            return list(n.outputs)

        coords = node("TexCoord")
        if bpy.app.version >= (3, 4, 0):
            source = []
            for i in range(4):
                attr = node("Attribute")
                attr.attribute_type = "INSTANCER"
                attr.attribute_name = f"em_i{i}"
                source.append(attr.outputs["Fac"])
        else:
            info = node("ObjectInfo")
            source = separate(info.outputs["Color"]) + [info.outputs["Alpha"]]
        source = [math_node("MULTIPLY", v, maximum) for v in source]
        xyz = separate(coords.outputs["Object"])
        # I = I3 + x*(I0-I3) + y*(I1-I3) + z*(I2-I3).
        intensity = source[3]
        for j in range(3):
            intensity = math_node("ADD", intensity, math_node("MULTIPLY", xyz[j], math_node("SUBTRACT", source[j], source[3])))
        low = math_node("MINIMUM", math_node("MINIMUM", source[0], source[1]), math_node("MINIMUM", source[2], source[3]))
        high = math_node("MAXIMUM", math_node("MAXIMUM", source[0], source[1]), math_node("MAXIMUM", source[2], source[3]))
        intensity = math_node("MINIMUM", high, math_node("MAXIMUM", low, intensity))
        fraction = math_node("LOGARITHM", math_node("MAXIMUM", 1e-30, math_node("DIVIDE", intensity, spec["colorLow"])), spec["colorHigh"] / spec["colorLow"])
        fraction = math_node("MINIMUM", 1, math_node("MAXIMUM", 0, fraction))
        # Nine bounded ramps reproduce all 256 LUT entries exactly. Native
        # shader constants avoid stale generated-image caches on warm updates.
        color = None
        for start in range(0, 255, 31):
            end = min(255, start + 31)
            ramp = node("ValToRGB")
            ramp.color_ramp.interpolation = "LINEAR"
            elements = ramp.color_ramp.elements
            elements[0].position = start / 255
            elements[0].color = tuple(palette[start])
            elements[1].position = end / 255
            elements[1].color = tuple(palette[end])
            for index in range(start + 1, end):
                elements.new(index / 255).color = tuple(palette[index])
            links.new(fraction, ramp.inputs["Fac"])
            if color is None:
                color = ramp.outputs["Color"]
            else:
                mix = node("MixRGB")
                links.new(math_node("GREATER_THAN", fraction, start / 255), mix.inputs[0])
                links.new(color, mix.inputs[1])
                links.new(ramp.outputs["Color"], mix.inputs[2])
                color = mix.outputs[0]
        path = node("LightPath")
        reflected = math_node("MULTIPLY", path.outputs["Is Reflection Ray"], math_node("MAXIMUM", path.outputs["Is Glossy Ray"], path.outputs["Is Singular Ray"]))
        strength = math_node("MULTIPLY", math_node("MAXIMUM", 0, math_node("SUBTRACT", intensity, 1)), .2 / 99 * spec["weight"])
        strength = math_node("MULTIPLY", strength, math_node("GREATER_THAN", intensity, max(1, spec["minimum"])))
        membership = math_node("LESS_THAN", math_node("ADD", math_node("ADD", xyz[0], xyz[1]), xyz[2]), 1)
        for coordinate in xyz:
            membership = math_node("MULTIPLY", membership, math_node("GREATER_THAN", coordinate, 0))
        strength = math_node("MULTIPLY", strength, membership)
        emission, output = node("Emission"), node("OutputMaterial")
        links.new(color, emission.inputs["Color"])
        links.new(strength, emission.inputs["Strength"])
        # A zero closure branch lets Cycles skip the full interpolation/palette
        # shader. Multiplying strength by zero evaluates that work anyway.
        gate = node("MixShader")
        links.new(reflected, gate.inputs[0])
        links.new(emission.outputs[0], gate.inputs[2])
        links.new(gate.outputs[0], output.inputs["Volume"])
        mat.cycles.homogeneous_volume = False
        mat.cycles.volume_step_rate = 1.0
        # Reflection-only emission cannot be sampled as a regular light: its
        # shadow-ray value is deliberately zero. MIS would otherwise downweight
        # BSDF hits without a matching light-sampled contribution (biased dark).
        if hasattr(mat.cycles, "emission_sampling"):
            mat.cycles.emission_sampling = "NONE"
        else:
            mat.cycles.use_multiple_importance_sampling = False
        return mat
