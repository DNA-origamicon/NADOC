"""Version-aware Cycles sampling policy, usable with the supported 3.x runtime."""


def configure_sampling(scene, version):
    supported = hasattr(scene.cycles, "use_light_tree")
    if supported:
        scene.cycles.use_light_tree = True
    return {"blender_version": version, "light_tree_supported": supported,
            "light_tree_enabled": supported, "compact_em": True}


def configure_emission(material):
    cycles = material.cycles
    if hasattr(cycles, "emission_sampling"):
        # Preserve the existing two-sided, partially transparent markers.
        cycles.emission_sampling = "FRONT_BACK"
    elif hasattr(cycles, "use_multiple_importance_sampling"):
        cycles.use_multiple_importance_sampling = True


def configure_sample_chunk(cycles, data):
    """Disjoint sample subsets, with a stable sequence across viewport chunks."""
    count = data['samples']
    offset = data.get('sample_offset', 0)
    total = data.get('sample_total', count)
    if any(type(v) is not int for v in (count, offset, total)) or not 0 <= offset < total <= 512 or not 1 <= count <= total - offset:
        raise ValueError('Invalid OptiX sample subset')
    cycles.sample_offset = offset
    if hasattr(cycles, 'use_sample_subset'):
        cycles.samples = total
        cycles.use_sample_subset = True
        cycles.sample_subset_length = count
    else:
        cycles.samples = count
