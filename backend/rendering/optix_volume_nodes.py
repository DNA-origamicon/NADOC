"""Compact procedural tetrahedron instances (Blender 3.4+)."""
import numpy as np
try:
    from .optix_volume_instances import affine_transforms
except ImportError:
    from optix_volume_instances import affine_transforms


def rotation_eulers(matrix):
    """XYZ Euler angles for proper rotation matrices, including gimbal lock."""
    cy = np.hypot(matrix[:, 0, 0], matrix[:, 1, 0])
    return np.column_stack((np.where(cy > 1e-7, np.arctan2(matrix[:, 2, 1], matrix[:, 2, 2]), np.arctan2(-matrix[:, 1, 2], matrix[:, 1, 1])),
                            np.arctan2(-matrix[:, 2, 0], cy), np.where(cy > 1e-7, np.arctan2(matrix[:, 1, 0], matrix[:, 0, 0]), 0)))


def instance_transforms(points):
    matrices = affine_transforms(points)
    left, scale, right = np.linalg.svd(matrices[:, :3, :3])
    signs = np.where(np.linalg.det(left) < 0, -1, 1)
    left[:, :, 2] *= signs[:, None]; scale[:, 2] *= signs
    signs = np.where(np.linalg.det(right) < 0, -1, 1)
    right[:, 2, :] *= signs[:, None]; scale[:, 2] *= signs
    return rotation_eulers(right), scale, rotation_eulers(left), matrices[:, :3, 3]


def instances(owner, mesh, points, values, maximum, generation, report):
    import bpy
    group = bpy.data.collections.new(f'em-volume-{generation}')
    owner.collections.append(group)
    bpy.context.scene.collection.children.link(group)
    prototype = bpy.data.objects.new(f'em-tetra-{generation}', mesh)
    owner.objects.append(prototype); group.objects.link(prototype)
    prototype.hide_render = True
    seeds = bpy.data.meshes.new(f'em-seeds-{generation}')
    owner.meshes.append(seeds)
    seeds.vertices.add(len(values))
    seeds.vertices.foreach_set('co', np.zeros(len(values)*3, dtype=np.float32))
    obj = bpy.data.objects.new(f'em-instances-{generation}', seeds)
    owner.objects.append(obj); group.objects.link(obj)
    report('geometry', f'Preparing {len(values)} compact reflected EM cells', 0)
    rotations, scales, rotations_after, offsets = instance_transforms(points)
    for name, data in [('em_before', rotations), ('em_scale', scales), ('em_after', rotations_after), ('em_offset', offsets)]:
        attr = seeds.attributes.new(name, 'FLOAT_VECTOR', 'POINT')
        attr.data.foreach_set('vector', np.asarray(data, dtype=np.float32).ravel())
    for i in range(4):
        attr = seeds.attributes.new(f'em_i{i}', 'FLOAT', 'POINT')
        attr.data.foreach_set('value', np.asarray(values[:, i] / maximum, dtype=np.float32))
    tree = bpy.data.node_groups.new(f'em-cell-instances-{generation}', 'GeometryNodeTree')
    owner.node_groups.append(tree)
    if hasattr(tree, 'interface'):
        tree.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
        tree.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    else:
        tree.inputs.new('NodeSocketGeometry', 'Geometry'); tree.outputs.new('NodeSocketGeometry', 'Geometry')
    nodes, links = tree.nodes, tree.links
    source = nodes.new('NodeGroupInput')
    output = nodes.new('NodeGroupOutput')
    geometry = nodes.new('GeometryNodeObjectInfo')
    geometry.inputs['Object'].default_value = prototype
    geometry.inputs['As Instance'].default_value = False
    def attribute(name):
        node = nodes.new('GeometryNodeInputNamedAttribute'); node.data_type = 'FLOAT_VECTOR'
        node.inputs['Name'].default_value = name
        return node.outputs['Attribute']
    instance = nodes.new('GeometryNodeInstanceOnPoints')
    links.new(source.outputs['Geometry'], instance.inputs['Points'])
    links.new(geometry.outputs['Geometry'], instance.inputs['Instance'])
    links.new(attribute('em_before'), instance.inputs['Rotation'])
    last = instance.outputs['Instances']
    for kind, socket, name in [('Scale', 'Scale', 'em_scale'), ('Rotate', 'Rotation', 'em_after'), ('Translate', 'Translation', 'em_offset')]:
        node = nodes.new(f'GeometryNode{kind}Instances')
        node.inputs['Local Space'].default_value = False
        links.new(last, node.inputs['Instances'])
        links.new(attribute(name), node.inputs[socket])
        last = node.outputs['Instances']
    links.new(last, output.inputs['Geometry'])
    modifier = obj.modifiers.new('Adaptive EM cells', 'NODES'); modifier.node_group = tree
