import numpy as np
import pytest

from backend.api import headless_build as hb
from backend.api import state
from backend.api.part_corner_commands import preflight
from backend.api.corner_junction_evaluation import evaluate_corner_junctions
from backend.api.routes_deformation import AddDeformationBody, add_deformation
from backend.core.models import LatticeType
from tests.conftest import SIX_HB_CELLS


@pytest.mark.parametrize('lattice,cells', [
    (LatticeType.SQUARE, [[0, i] for i in range(8)]),
    (LatticeType.HONEYCOMB, SIX_HB_CELLS),
])
def test_preflight_is_read_only_and_plans_both_strand_types(lattice, cells):
    with hb.scratch_session(lattice):
        hb.create_bundle(cells, 168, lattice=lattice, separate_fresh_extrusions=False)
        hb.add_cluster('Corner source', [h.id for h in state.get_or_404().helices], log=True)
        design = state.get_or_404()
        cluster = next(c for c in design.cluster_transforms if c.name == 'Corner source')
        before = design.model_dump()
        guide, routes = preflight(design, dict(cluster_id=cluster.id, position_bp=84,
                                               angle_deg=90, direction_deg=0))
        assert len(guide['cuts']) == len(cells)
        assert {j.strand_type for j in routes.junctions} == {'scaffold', 'staple'}
        assert len(routes.junctions) == 2 * len(cells)
        assert design.model_dump() == before
        assert design.feature_log


def test_twisted_source_controls_the_corner_direction():
    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle([[0, i] for i in range(8)], 168, lattice=LatticeType.SQUARE,
                         separate_fresh_extrusions=False)
        hb.add_cluster('Corner source', [h.id for h in state.get_or_404().helices], log=True)
        design = state.get_or_404()
        cluster = next(c for c in design.cluster_transforms if c.name == 'Corner source')
        args = dict(cluster_id=cluster.id, position_bp=84, angle_deg=90, direction_deg=0)
        before, _ = preflight(design, args)
        add_deformation(AddDeformationBody(type='twist', plane_a_bp=0, plane_b_bp=42,
            cluster_ids=[cluster.id], params={'kind': 'twist', 'total_degrees': 90}))
        after, _ = preflight(state.get_or_404(), args)
        normal = np.asarray(after['plane_normal'])
        assert abs(normal[0]) < 1e-6
        assert abs(normal[1]) == pytest.approx(abs(before['plane_normal'][0]), abs=1e-6)


def test_native_seam_search_has_actual_progress_and_preserves_source():
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 168, lattice=LatticeType.HONEYCOMB,
                         separate_fresh_extrusions=False)
        hb.add_cluster('Corner source', [h.id for h in state.get_or_404().helices], log=True)
        design = state.get_or_404()
        cluster = next(c for c in design.cluster_transforms if c.name == 'Corner source')
        before = design.model_dump()
        progress = []
        guide, routes, seams = evaluate_corner_junctions(design,
            dict(cluster_id=cluster.id, position_bp=84, angle_deg=90, direction_deg=15),
            on_progress=lambda done, total: progress.append((done, total)))
        assert len(seams) == len(routes.junctions) == 12
        assert progress == [(i, 96) for i in range(97)]
        assert all(len(s.candidates) == 8 for s in seams)
        assert all(np.isfinite(c.backbone_lengths_nm).all() for s in seams for c in s.candidates)
        assert design.model_dump() == before


def test_zero_angle_is_topological_identity_and_search_cancels_without_mutation():
    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle([[0, i] for i in range(8)], 168, lattice=LatticeType.SQUARE,
                         separate_fresh_extrusions=False)
        hb.add_cluster('Corner source', [h.id for h in state.get_or_404().helices], log=True)
        design = state.get_or_404()
        cluster = next(c for c in design.cluster_transforms if c.name == 'Corner source')
        args = dict(cluster_id=cluster.id, position_bp=84, angle_deg=0, direction_deg=0)
        _, routes, seams = evaluate_corner_junctions(design, args)
        assert not seams and not routes.junctions
        assert all(d.side == 'unchanged' for s in routes.strands for d in s.domains)
        before = design.model_dump()
        progress = []
        def cancel():
            if len(progress) >= 3:
                raise RuntimeError('cancelled')
        with pytest.raises(RuntimeError, match='cancelled'):
            evaluate_corner_junctions(design, {**args, 'angle_deg': 90}, check_cancel=cancel,
                on_progress=lambda done, total: progress.append((done, total)))
        assert progress == [(0, 128), (1, 128), (2, 128)]
        assert design.model_dump() == before


def test_cancelled_preview_does_not_begin_plane_or_tip_calculation(monkeypatch):
    from backend.api import part_corner_commands

    monkeypatch.setattr(part_corner_commands, 'corner_guide',
        lambda *_args: pytest.fail('Cancelled work reached the geometry calculation.'))

    def cancel():
        raise RuntimeError('cancelled')

    with pytest.raises(RuntimeError, match='cancelled'):
        evaluate_corner_junctions(None, {}, check_cancel=cancel)
