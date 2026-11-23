"""Measured extension slabs preserve atoms, coarse arcs and authoring history."""
import numpy as np
import pytest
from types import SimpleNamespace
from scipy.spatial.transform import Rotation

from backend.api import crud, routes_extensions, state
from backend.core.atomistic_cache import build_atomistic_model_cached
from backend.core.design_geometry import _geometry_for_design, _compact_geometry_from_nucleotides
from backend.core.native_slab_placement import authoritative_slab_poses
from backend.core.nucleotide_landmarks import PURINE_RING, PYRIMIDINE_RING
from backend.core.extension_slabs import project_extension_slabs
from backend.core.native_full_placement import NativePlacementError
from tests.test_part_transform_preview_sessions import document, verified  # noqa: F401


def test_extension_slabs_follow_actual_atomic_rings(document):  # noqa: F811
    crud.create_bundle(crud.BundleRequest(cells=[[0, 0]], length_bp=8, ligate_adjacent=False,
                                          name='__e2e__extension-slabs'))
    source = state.get_or_404()
    for strand in source.strands:
        for end in ('five_prime', 'three_prime'):
            routes_extensions.add_strand_extension(routes_extensions.StrandExtensionRequest(
                strand_id=strand.id, end=end, sequence='ACGT', modification='cy3'))
    design = state.get_or_404()
    verified(design)
    before = design.model_dump_json()
    model = build_atomistic_model_cached(design, fast_bridges=True)
    atoms_before = [(a.x, a.y, a.z) for a in model.atoms]
    geometry = _geometry_for_design(design)
    coarse = _geometry_for_design(design, extension_slabs=False)
    tails = [r for r in geometry if r.get('extension_id') and not r['is_modification']]
    assert len(tails) == 16
    for record, arc in zip(geometry, coarse, strict=True):
        for field in ('backbone_position', 'base_position', 'base_normal', 'axis_tangent'):
            assert record[field] == arc[field]
    for record in tails:
        atoms = {a.name: np.array([a.x, a.y, a.z]) for a in model.atoms
                 if a.extension_id == record['extension_id'] and a.ext_k == record['bp_index']}
        ring = np.array([atoms[n] for n in (PURINE_RING if 'N9' in atoms else PYRIMIDINE_RING)])
        np.testing.assert_allclose(record['slab_position'], ring.mean(axis=0), atol=1e-12)
        frame = Rotation.from_quat(record['slab_quaternion']).as_matrix()
        _, _, axes = np.linalg.svd(ring - ring.mean(axis=0))
        assert abs(frame[:, 1] @ axes[-1]) > 1 - 1e-12
        span = atoms['C6'] - atoms['N9'] if 'N9' in atoms else atoms['C4'] - atoms['N1']
        span -= frame[:, 1] * (span @ frame[:, 1])
        assert frame[:, 2] @ (span / np.linalg.norm(span)) > 1 - 1e-12
    assert all(r['slab_position'] is None for r in geometry if r.get('is_modification'))
    authoritative_slab_poses(geometry)
    compact = _compact_geometry_from_nucleotides(geometry)
    assert compact
    assert design.model_dump_json() == before
    assert [(a.x, a.y, a.z) for a in model.atoms] == atoms_before
    purine = next(r for r in tails if r['nucleobase'] == 'A')
    for missing in ("N9", "C8", "O5'"):
        incomplete = SimpleNamespace(atoms=[a for a in model.atoms if not (
            a.extension_id == purine['extension_id'] and a.ext_k == purine['bp_index'] and a.name == missing)])
        with pytest.raises(NativePlacementError, match='Incomplete atomistic extension ring'):
            project_extension_slabs([dict(purine)], incomplete)
