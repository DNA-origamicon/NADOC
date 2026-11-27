"""Bulk native instance construction; no per-cell RNA notification queue."""
import numpy as np


def affine_transforms(points):
    p = np.stack(points, axis=1).astype(np.float64)
    matrices = np.tile(np.eye(4), (len(p), 1, 1))
    matrices[:, :3, :3] = np.transpose(p[:, :3] - p[:, 3:4], (0, 2, 1))
    matrices[:, :3, 3] = p[:, 3]
    return matrices


def _batch(owner, mesh, points, values, maximum, generation):
    import bpy
    count = len(values)
    scene = bpy.context.scene
    group = bpy.data.collections.new(f"em-field-{generation}")
    owner.collections.append(group)
    scene.collection.children.link(group)
    source = bpy.data.meshes.new(f"em-instance-seeds-{generation}")
    owner.meshes.append(source)
    source.vertices.add(count)
    seeds = np.zeros((count, 3), dtype=np.float32)
    seeds[:, 0] = np.arange(count)
    source.vertices.foreach_set("co", seeds.ravel())
    root = bpy.data.objects.new(f"em-instance-root-{generation}", source)
    owner.roots.append(root)
    group.objects.link(root)
    root.instance_type = 'VERTS'
    root.show_instancer_for_render = False
    child = bpy.data.objects.new(f"em-cell-{generation}", mesh)
    group.objects.link(child)
    child.parent = root
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    root.select_set(True)
    bpy.context.view_layer.objects.active = root
    bpy.ops.object.duplicates_make_real(use_base_parent=True, use_hierarchy=True)
    root.instance_type = 'NONE'
    bpy.data.objects.remove(child, do_unlink=True)
    cells = [obj for obj in group.objects if obj != root]
    owner.objects.extend(cells)
    # Capture the seed index before replacing the generated transforms.
    indices = [round(obj.location.x) for obj in cells]
    if sorted(indices) != list(range(count)):
        raise ValueError('Native volume instance indices are incomplete')
    matrices = affine_transforms(points)
    # foreach_set writes raw RNA arrays in one batch, avoiding O(n²) per-ID
    # notifier queues. The parent inverse retains full affine shear.
    ordered = list(group.objects)
    mapping = {obj.as_pointer(): i for obj, i in zip(cells, indices)}
    transforms = np.array([matrices[mapping[obj.as_pointer()]].T if obj != root else np.eye(4) for obj in ordered], dtype=np.float32)
    colors = np.array([values[mapping[obj.as_pointer()]] / maximum if obj != root else [1, 1, 1, 1] for obj in ordered], dtype=np.float32)
    group.objects.foreach_set('location', np.zeros(len(ordered)*3, dtype=np.float32))
    group.objects.foreach_set('matrix_parent_inverse', transforms.ravel())
    group.objects.foreach_set('color', colors.ravel())
    source.clear_geometry()
    root.hide_render = False
    scene.collection.children.unlink(group)
    return group


def instances(owner, mesh, points, values, maximum, generation, report):
    import bpy
    groups = []
    for start in range(0, len(values), 4096):
        end = start + 4096
        if start % 4096 == 0:
            report("geometry", f"Preparing reflected EM cells {start}/{len(values)}", start / len(values))
        groups.append(_batch(owner, mesh, [p[start:end] for p in points], values[start:end], maximum, f"{generation:09d}-{start:09d}"))
    collection = bpy.context.scene.collection
    for group in groups:
        collection.children.link(group)
