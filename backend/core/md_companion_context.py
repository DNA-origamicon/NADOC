"""Bounded Full-trajectory ion/cell readers; display affine remains shared."""
import numpy as np


def companion_context(topology_path, seg_paths, coordinate_path, design, o):
    from backend.core.md_trajectory import _build_playback_ctx, _build_md_nadoc_ctx, _DcdPrefixChain
    from backend.core.md_solvent import build_solvent_ctx

    # Reuse cached PSF rows/species without constructing a whole-solvent Universe.
    # Older/synthetic mappings and water retain the original extraction context.
    include_dna = bool(o.get("include_dna"))
    lightweight = not include_dna and not bool(o.get("water", True))
    ctx = (_build_playback_ctx if lightweight else _build_md_nadoc_ctx)(
        topology_path, seg_paths, coordinate_path, design, with_atoms=True,
        atom_metadata=include_dna, alignment_only=lightweight,
    )
    u = ctx["universe"]
    companion_reader = None
    if ctx.get("playback_only"):
        sctx = ctx["solvent_ctx"]
        required = np.concatenate((sctx["ion_rows"], sctx["graphene_rows"]))
        companion_reader = _DcdPrefixChain(seg_paths, int(required.max()) + 1 if required.size else 1)
        # Match the existing alignment-only path: no heavy-coordinate anchors.
        ctx["heavy_idx"] = np.zeros(0, dtype=np.int64)
        ctx["direct_heavy_layout"] = None
    else:
        sctx = build_solvent_ctx(u, water=bool(o.get("water", True)))
    return ctx, u, sctx, companion_reader
