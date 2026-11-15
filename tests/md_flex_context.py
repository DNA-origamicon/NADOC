"""Complete lightweight reader protocol for isolated flex-payload tests."""
from types import SimpleNamespace
import numpy as np


def complete_context(ctx):
    ctx.setdefault('p_order', [('h', 0, 'FORWARD')])
    ctx.setdefault('atom_meta', [{'serial': 0}])
    ctx.setdefault('heavy_bonds', np.empty((0, 2), int))
    ctx.setdefault('backbone_residues', [('A', i + 1) for i in range(len(ctx['p_order']))])
    ctx.setdefault('dcd_prefix', SimpleNamespace(frame=lambda _: None, close=lambda: None))
    ctx.setdefault('R_prev', None)
    ctx.setdefault('prev_frame_idx', -999)
    return ctx


def coarse_stub(ctx, index, **kwargs):
    n = len(ctx['p_order'])
    return np.zeros((n, 3)), None, None, None, None


def atom_stub(ctx, index, **kwargs):
    return np.zeros((len(ctx['atom_meta']), 3))
