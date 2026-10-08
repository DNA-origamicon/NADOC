"""Centerlines of desktop helix_renderer axis tubes, retaining domain gaps."""
import numpy as np

from backend.core.vr_scene_projection import _centripetal_catmull_rom


def axis_line_paths(axis, helix=None):
    samples = axis.get('samples') or [axis.get('start'), axis.get('end')]
    segments = axis.get('segments')
    curved = len(samples) > 2

    def smooth(points):
        return [p.tolist() for p in _centripetal_catmull_rom(
            tuple(np.asarray(p, dtype=float) for p in points),
            segments=max(len(points)*4, 16), arc_length=True)]

    # Desktop uses one full sampled tube when there is at most one domain.
    if curved and (segments is None or len(segments) == 1):
        yield smooth(samples), segments[0] if segments else None, 'curve'
        return
    if segments is None:
        yield samples, None, 'samples'
        return
    for index, segment in enumerate(segments):
        points = [segment['start'], segment['end']]
        source = segment.get('samples') or samples
        if curved and len(source) > 2 and helix is not None:
            # Same inclusive/exclusive bp bounds and sampling grid as desktop.
            lo = segment.get('bp_lo', helix.bp_start)-helix.bp_start
            hi = segment.get('bp_hi', helix.bp_start+helix.length_bp-1)-helix.bp_start
            step = 1 if getattr(helix, 'native_residues', None) else 7
            interior = [p for i, p in enumerate(source)
                        if lo < (helix.length_bp-1 if i == len(source)-1 else i*step) <= hi]
            if interior:
                points = smooth([segment['start'], *interior, segment['end']])
        yield points, segment, str(index)
