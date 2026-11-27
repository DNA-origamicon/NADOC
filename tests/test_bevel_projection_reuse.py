"""Certified cuts must match independent canonical Full and straight geometry."""
import gzip
import json
from pathlib import Path

import pytest

from backend.api import state
from backend.api.feature_recording import record_feature
from backend.api.part_bevel_commands import BevelCommand, build
from backend.api.corner_preview_projection import project_corner_preview
from backend.core.atomistic_cache import clear_atomistic_cache
from backend.core.corner_seam_cache import clear_fit_cache
from backend.core.corner_seam_projection import clear_projection_cache
from backend.core.models import Design


def clear():
    clear_atomistic_cache()
    clear_fit_cache()
    clear_projection_cache()


@pytest.mark.slow
def test_recorded_cut_reuses_exact_landmarks_and_fails_closed_for_changed_placement(monkeypatch):
    from backend.core.corner_projection_reuse import reuse_projection
    path = Path(__file__).parents[1] / 'frontend/src/ui/geometry_review_data/corner-closure.json.gz'
    with gzip.open(path, 'rt') as stream:
        source = Design.model_validate(json.load(stream)['controls']['hc2']['candidate_design'])
    clear()
    try:
        # Import/inspection can materialize atoms before Full is requested.
        # The dependency certificate must survive that cache handoff.
        from backend.core.atomistic_cache import build_atomistic_model_cached
        build_atomistic_model_cached(source)
        project_corner_preview(source)
        owner = next(c for c in source.cluster_transforms if c.helix_ids)
        params = BevelCommand(cluster_id=owner.id, position_bp=130,
            angle_deg=20, direction_deg=30, operation_id='certified-cut').model_dump(mode='json', by_alias=True)
        cut, _, _ = record_feature(state._DesignSession(design=source.model_copy(deep=True)),
            'bevel', 'Bevel validation', params, lambda d: build(d, params))
        assert reuse_projection(cut) is not None
        straight = cut.model_copy(update={'cluster_transforms': [], 'deformations': []})
        assert reuse_projection(straight) is not None
        from backend.core.bevel_geometry_cache import compact
        fast_wire = compact(cut)
        assert fast_wire is not None
        moved = cut.model_copy(deep=True)
        moved.cluster_transforms[0].translation[0] += 1
        assert reuse_projection(moved) is None
        with monkeypatch.context() as patch:
            def forbidden(*args, **kwargs):
                raise AssertionError('Certified Bevel recalculated retained geometry')
            patch.setattr('backend.core.atomistic_cache.build_atomistic_model_cached', forbidden)
            patch.setattr('backend.core.design_geometry.native_full_arrays_for_helix', forbidden)
            fast = project_corner_preview(cut)
            cached = project_corner_preview(cut)
            assert cached == fast
            cached['nucleotides'][0]['backbone_position'][0] += 1
            assert project_corner_preview(cut) == fast
            from backend.api.bevel_live import cached_display
            from backend.core.design_geometry import _compact_geometry_from_nucleotides
            live = cached_display(cut)
            assert fast_wire == live['nucleotides_compact']
            assert live['nucleotides_compact'] == _compact_geometry_from_nucleotides(fast['nucleotides'])
            assert live['display_topology'] == fast['display_topology']
            assert live['helix_axes'] == fast['helix_axes']
        clear()
        exact = project_corner_preview(cut)
        assert fast == exact
    finally:
        clear()


def test_capped_clearance_protects_prefix_and_primary_cell_owner():
    import numpy as np
    from backend.core.corner_seam_dependencies import capture_dependencies, trace_clearance
    # Serial zero owns the first pair's cell even though it is not a clash.
    xyz = np.array([[.001, 0, 0], [.002, 0, 0], [.003, 0, 0], [10, 0, 0]])
    with capture_dependencies() as trace:
        trace_clearance(xyz, {1, 2}, [{'serials': [1, 2]}], 1, .08)
    assert trace['complete']
    assert trace['protected'] == {0, 1, 2}
    assert len(trace['boxes']) == 1
