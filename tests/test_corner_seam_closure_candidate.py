"""Diagnostic optimizer mathematics; does not authorize molecular promotion."""

import numpy as np
import pytest
from scipy.optimize._numdiff import approx_derivative

from backend.api import headless_build as hb, state
from backend.api.routes_corner import CreateCornerRequest, create_corner
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import LatticeType
from experiments.corner_seam_candidate import deferred_duplex_atoms
from experiments.corner_seam_closure import ComponentClosure, close_component
from experiments.corner_seam_lengths import junction_component


def test_candidate_derivatives_rigid_stamps_and_fixed_duplex_rings():
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle([[0, 0], [0, 1]], 84, lattice=LatticeType.HONEYCOMB,
                         separate_fresh_extrusions=False)
        hb.add_cluster('Closure diagnostic', [h.id for h in state.get_or_404().helices], log=True)
        source, revision = state.copy_for_persist()
        owner = next(c for c in source.cluster_transforms if c.name == 'Closure diagnostic')
        create_corner(CreateCornerRequest(cluster_id=owner.id, position_bp=42, angle_deg=90,
            direction_deg=15, expected_design_id=source.id, expected_revision=revision))
        design = state.get_or_404()
        before = design.model_dump_json()
        sites = {(r['helix_id'], r['bp_index'], r['direction']): r for r in _geometry_for_design(design)}
        component = junction_component(deferred_duplex_atoms(design), design.forced_ligations[0], sites, 3)
        first = component.atoms[-1]
        environment = [[first.x+.09, first.y+.04, first.z+.03]]
        problem = ComponentClosure(component, environment=environment)
        x = problem.x0 + .02*np.sin(np.arange(len(problem.x0)))
        numerical = approx_derivative(lambda v: problem.objective(v)[0], x).ravel()
        _, analytical = problem.objective(x)
        np.testing.assert_allclose(analytical, numerical, atol=2e-6, rtol=2e-5)
        initial = problem.original.copy()
        result = close_component(component, max_iterations=30)
        final = np.array([[a.x, a.y, a.z] for a in component.atoms])
        for ids in problem.rigid:
            np.testing.assert_allclose(np.linalg.norm(final[ids, None]-final[ids], axis=-1),
                np.linalg.norm(initial[ids, None]-initial[ids], axis=-1), atol=1e-12)
        mutable = set(problem.owners) | set(problem.free) | {i for _, i in problem.branches}
        fixed = [i for i in range(len(component.atoms)) if i not in mutable]
        np.testing.assert_array_equal(final[fixed], initial[fixed])
        assert np.isfinite(result['objective'])
        assert result['preserves_terminal_gamma'] is False
        from experiments.corner_review_projection import full_model
        projection = full_model(component)
        assert len(projection['residues']) == 5
        assert len(projection['backbone_edges']) == 4
        for row in projection['residues']:
            atom = next(component.atoms[i] for i in row['atom_serials'] if component.atoms[i].name == "O5'")
            assert row['backbone_position'] == [atom.x, atom.y, atom.z]
            assert np.linalg.det(row['slab_axes']) == pytest.approx(1, abs=1e-10)
        assert design.model_dump_json() == before
