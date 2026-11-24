"""The unpromoted placement experiment cannot touch unrelated inserted joints."""

import pytest

from backend.api import crud, headless_build as hb, state
from backend.api.part_proof_commands import dependencies, execute
from backend.api.routes_corner import CreateCornerRequest, create_corner
from backend.core.models import Design, LatticeType, StrandType
from backend.core.part_history_contract import assess_part_history
from experiments.corner_seam_candidate import candidate_atoms
from experiments.corner_seam_scope import require_corner_only_inserts


def test_diagnostic_admits_recorded_corner_but_refuses_a_later_user_ligation(monkeypatch):
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle([[0, 0], [0, 1]], 84, lattice=LatticeType.HONEYCOMB,
                         separate_fresh_extrusions=False)
        hb.add_cluster('Corner scope', [h.id for h in state.get_or_404().helices], log=True)
        source, revision = state.copy_for_persist()
        owner = next(c for c in source.cluster_transforms if c.name == 'Corner scope')
        create_corner(CreateCornerRequest(cluster_id=owner.id, position_bp=42, angle_deg=90,
            direction_deg=15, expected_design_id=source.id, expected_revision=revision))
        corner = state.get_or_404()
        assert {link.id for link in require_corner_only_inserts(corner)} == {
            link.id for link in corner.forced_ligations}
        # Explicitly exercise the native user Join + insert commands. This is
        # a diagnostic rejection fixture, not an automatically proposed route.
        a, b = [s for s in corner.strands if s.strand_type == StrandType.SCAFFOLD]
        hb.force_ligate(a.id, b.id)
        link = state.get_or_404().forced_ligations[-1]
        crud.patch_forced_ligation_extra_bases(link.id, crud.CrossoverExtraBasesRequest(sequence='AC'))
        reopened = Design.model_validate_json(state.get_or_404().model_dump_json())
        proof = assess_part_history(reopened, execute=execute, dependencies=dependencies)
        assert proof['status'] == 'verified', proof
        before = reopened.model_dump_json()
        def forbidden(*args, **kwargs):
            raise AssertionError('Mixed source reached atom construction')
        monkeypatch.setattr('experiments.corner_seam_candidate.deferred_duplex_atoms', forbidden)
        with pytest.raises(ValueError, match='inserts from other ligations'):
            candidate_atoms(reopened)
        assert reopened.model_dump_json() == before
