"""Corner atom construction must not recursively ask for extension display slabs."""

import numpy as np
import pytest

from backend.api import headless_build as hb, routes_extensions, state
from backend.api.routes_corner import CreateCornerRequest, create_corner
from backend.api.part_proof_commands import dependencies, execute
from backend.core import atomistic_cache
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design, LatticeType
from backend.core.part_history_contract import assess_part_history


@pytest.mark.slow
def test_corner_with_native_terminal_extension_has_finite_independent_slabs(monkeypatch):
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle([[0, 0], [0, 1]], 84, lattice=LatticeType.HONEYCOMB,
                         separate_fresh_extrusions=False)
        hb.add_cluster('Corner with a terminal extension',
                       [h.id for h in state.get_or_404().helices], log=True)
        source, revision = state.copy_for_persist()
        owner = source.cluster_transforms[-1]
        build = atomistic_cache.build_atomistic_model_cached
        building = False

        def bounded_build(*args, **kwargs):
            nonlocal building
            assert not building, 'Extension slabs recursively entered Corner atom construction'
            building = True
            try:
                return build(*args, **kwargs)
            finally:
                building = False

        monkeypatch.setattr(atomistic_cache, 'build_atomistic_model_cached', bounded_build)
        create_corner(CreateCornerRequest(cluster_id=owner.id, position_bp=42,
            angle_deg=90, direction_deg=15, expected_design_id=source.id, expected_revision=revision))
        routes_extensions.add_strand_extension(routes_extensions.StrandExtensionRequest(
            strand_id=state.get_or_404().strands[0].id, end='five_prime', sequence='AC'))
        result = state.get_or_404()
        assert result.feature_log[-2].op_kind == 'corner'
        assert result.feature_log[-1].op_kind.startswith('extension-')
        before = result.model_dump_json()
        records = _geometry_for_design(result)
        assert any(row.get('corner_inserts') for row in records)
        tails = [row for row in records if row.get('extension_id')]
        assert len(tails) == 2
        for row in tails:
            assert np.isfinite(row['slab_position']).all()
            assert np.linalg.norm(row['slab_quaternion']) == pytest.approx(1)
        assert result.model_dump_json() == before
        reopened = Design.model_validate_json(before)
        assert assess_part_history(reopened, execute=execute, dependencies=dependencies)['status'] == 'verified'
