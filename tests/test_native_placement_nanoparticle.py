"""Nanoparticle diagnostics and constraints use the canonical terminal O5′ bead."""
import numpy as np
import pytest
from types import SimpleNamespace
from scipy.spatial.transform import Rotation

from backend.api.routes_nanoparticles import _np_tether_measurements
from backend.core.design_geometry import fitting_geometry
from backend.core.models import Design, LatticeType, Mat4x4, Nanoparticle
from backend.core.nanoparticle import build_thiol_conjugation
from backend.core.native_full_placement import NativePlacementError

pytestmark = pytest.mark.native_placement


@pytest.mark.parametrize("lattice", [LatticeType.HONEYCOMB, LatticeType.SQUARE])
@pytest.mark.parametrize("attach_end", ["5p", "3p"])
def test_unbound_nominal_tether_matches_actual_canonical_o5_landmark(lattice, attach_end, native_placement_evidence):
    matrix = np.eye(4)
    matrix[:3, :3] = Rotation.from_rotvec([.3, -.4, .2]).as_matrix()
    matrix[:3, 3] = [4., -3., 2.]
    particle = Nanoparticle(id="gold", diameter_nm=10, pose=Mat4x4.from_array(matrix))
    conjugation, helices, strands = build_thiol_conjugation(
        particle, scheme="direct_thiol", sequence="ACGTAC", count=3, attach_end=attach_end, seed=17)
    design = Design(lattice_type=lattice, nanoparticles=[particle],
        nanoparticle_conjugations=[conjugation], helices=helices, strands=strands)
    geometry = fitting_geometry(design)
    flag = "is_three_prime" if attach_end == "3p" else "is_five_prime"
    endpoints = {record["strand_id"]: record for record in geometry if record[flag]}
    measurements = _np_tether_measurements(design, particle.id, geometry)
    assert len(measurements) == 3
    for measurement in measurements:
        endpoint = endpoints[measurement["strand_id"]]
        assert endpoint["placement_source"] == "native-full-o5-v1"
        expected = float(np.linalg.norm(np.asarray(endpoint["backbone_position"])
                                       - measurement["sulfur_position_nm"]))
        native_placement_evidence(identity={"strand_id": measurement["strand_id"], "attach_end": attach_end},
            lattice=lattice.value, expected_nm=expected, actual_nm=measurement["nominal_unbound_length_nm"])
        assert measurement["measured_length_nm"] == pytest.approx(expected, abs=1e-12)
        assert measurement["nominal_unbound_length_nm"] == pytest.approx(expected, abs=1e-12)
        assert measurement["stretch_from_nominal_nm"] == pytest.approx(0., abs=1e-12)


def test_missing_saved_attachment_never_guesses_a_radial_molecular_joint(monkeypatch):
    from backend.core.nanoparticle import constrained_nanoparticle_move
    from backend.core import protein, duplex_cluster

    particle = Nanoparticle(id="gold", diameter_nm=10)
    conjugation, helices, strands = build_thiol_conjugation(
        particle, scheme="direct_thiol", sequence="ACGTAC", count=1)
    design = Design(nanoparticles=[particle], nanoparticle_conjugations=[conjugation], helices=helices, strands=strands)
    version = SimpleNamespace(strand_id=strands[0].id, overhang_id="target")
    monkeypatch.setattr(protein, "resolve_overhang_anchor", lambda *_: (np.zeros(3), None))
    monkeypatch.setattr(duplex_cluster, "duplex_cluster_for", lambda *_: None)
    with pytest.raises(NativePlacementError, match="exact saved native backbone attachment"):
        constrained_nanoparticle_move(design, particle.id, version, [],
            pivot=[0, 0, 0], translation=[1, 2, 3], rotation=[0, 0, 0, 1])
