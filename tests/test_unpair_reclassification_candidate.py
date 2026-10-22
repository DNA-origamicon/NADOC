"""Candidate must preserve the authored 3D structure when changing cadnano rows."""
from uuid import UUID

import numpy as np
import pytest

from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import StrandType
from tests.test_part_member_motion_order import _source, _nucleotide, D, M, _owner
from tools.unpair_reclassification_candidate import relocate_segments


@pytest.mark.parametrize("bps", [[0, 1], [3, 4], list(range(8))])
@pytest.mark.parametrize("helix_index", [0, 1])
@pytest.mark.parametrize("owned", [False, True])
def test_cadnano_relocation_preserves_sequence_backbone_and_3d(bps, helix_index, owned):
    source = _source()
    source = source.copy_with(strands=[s.model_copy(update={"sequence": "ACTGTCAG"}) for s in source.strands])
    staple = next(s for s in source.strands if s.strand_type == StrandType.STAPLE
                  and s.domains[0].helix_id == source.helices[helix_index].id)
    if owned:
        source = _owner(source, staple)
    domain = staple.domains[0]
    for bp in bps:
        source = _nucleotide(source, {"kind": "base", "helix_id": domain.helix_id,
            "bp_index": bp, "direction": domain.direction.value, "copy_k": 0}, M if owned else D, f"move-{bp}")
    locked = source.model_dump_json()
    result = relocate_segments(source, [(domain.helix_id, bp, domain.direction.value, 0) for bp in bps],
                               identity_seed=str(UUID(int=32001)))
    assert source.model_dump_json() == locked
    assert result.find_strand(staple.id).sequence == staple.sequence
    assert [s for s in source.strands if s.strand_type == StrandType.SCAFFOLD] == [
        s for s in result.strands if s.strand_type == StrandType.SCAFFOLD]
    assert len(result.helices) == len(source.helices) + 1
    assert result.overhangs[-1].auxiliary_endpoint == (len(bps) == 8)
    assert result.helices[-1].grid_pos not in {h.grid_pos for h in source.helices}
    old, new = (_geometry_for_design(d) for d in (source, result))
    def frames(rows):
        return {(r['strand_id'], r['bp_index'], r['direction'], r.get('copy_k', 0)):
                [r[field] for field in ('backbone_position', 'base_position', 'base_normal', 'axis_tangent')]
                for r in rows}
    old, new = frames(old), frames(new)
    assert old.keys() == new.keys()
    for key in old:
        np.testing.assert_allclose(old[key], new[key], rtol=0, atol=1e-12)
    old_atoms, new_atoms = (build_atomistic_model(d, fast_bridges=True) for d in (source, result))
    assert old_atoms.bonds == new_atoms.bonds
    assert [(a.name, a.residue, a.strand_id) for a in old_atoms.atoms] == [
        (a.name, a.residue, a.strand_id) for a in new_atoms.atoms]
    np.testing.assert_allclose([[a.x, a.y, a.z] for a in old_atoms.atoms],
                               [[a.x, a.y, a.z] for a in new_atoms.atoms], rtol=0, atol=1e-12)
