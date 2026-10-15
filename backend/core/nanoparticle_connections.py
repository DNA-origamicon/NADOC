"""Pure existing endpoint and naming rules for nanoparticle candidates."""

from backend.core.overhang_ops import overhang_free_end_polarity


def connection_attaches(owner, direct_variant):
    """Map NP chemical ends to the existing canonical 5'/3' endpoint model."""
    surface = "root" if owner.attach_end == "5p" else "free_end"
    free = "free_end" if owner.attach_end == "5p" else "root"
    if direct_variant == "root-to-root":
        return surface, "root"
    if direct_variant == "end-to-root":
        return free, "root"
    raise ValueError(f"Unsupported nanoparticle connection type {direct_variant!r}.")


def polarity_error(design, owner, target_overhang_id, direct_variant):
    """Return the unchanged legacy error and its authored selector, or None."""
    target_free = overhang_free_end_polarity(design, target_overhang_id)
    if target_free is None:
        return ("Target overhang polarity is unknown; its physical 5'/3' free end "
                "must be defined before creating a nanoparticle connection.", "overhang_id")
    nanoparticle_free = "3p" if owner.attach_end == "5p" else "5p"
    forbidden = (nanoparticle_free != target_free if direct_variant == "end-to-root"
                 else nanoparticle_free == target_free)
    if forbidden:
        np_root = owner.attach_end
        target_root = "3p" if target_free == "5p" else "5p"
        return (f"{direct_variant} is forbidden for a {np_root} thiol-bound NP root "
                f"and a {target_root} target root: the duplex would be parallel, not "
                "reverse-complementary. Choose the other direct connection type.", "direct_variant")
    return None


def next_version_name(design, nanoparticle_id, strand_id, overhang_id):
    used = {version.name for version in design.nanoparticle_connection_versions
            if version.nanoparticle_id == nanoparticle_id
            and version.strand_id == strand_id and version.overhang_id == overhang_id}
    index = 1
    while f"V{index}" in used:
        index += 1
    return f"V{index}"
