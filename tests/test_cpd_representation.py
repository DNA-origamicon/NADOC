"""Full display resolves named landmarks from the current CPD conformation."""

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.atomistic import _SUGAR, _DT_BASE
from backend.core.cpd_representation import (
    project_cpd_residue,
    inject_cpd_representation,
)
from backend.core.nucleotide_landmarks import FULL_REP_BACKBONE_ATOM, PYRIMIDINE_RING
from backend.core.models import Design
from pathlib import Path


def test_projection_preserves_landmarks_under_independent_component_motion():
    sugar_r = Rotation.from_rotvec([0.4, -0.2, 0.7]).as_matrix()
    base_r = Rotation.from_rotvec([-0.3, 0.8, 0.2]).as_matrix()
    sugar_t, base_t = np.array([2.0, 3.0, 4.0]), np.array([-1.0, 4.0, 2.0])
    atoms = {}
    for template, rotation, translation in [
        (_SUGAR, sugar_r, sugar_t),
        (_DT_BASE, base_r, base_t),
    ]:
        atoms.update(
            {n: (rotation @ xyz + translation).tolist() for n, _, *xyz in template}
        )
    result = project_cpd_residue(atoms)
    np.testing.assert_allclose(
        result["backbone_position"], atoms[FULL_REP_BACKBONE_ATOM], atol=1e-12
    )
    centroid = np.mean([xyz for n, _, *xyz in _DT_BASE if n in PYRIMIDINE_RING], axis=0)
    np.testing.assert_allclose(
        result["base_position"], base_r @ centroid + base_t, atol=1e-12
    )
    np.testing.assert_allclose(
        Rotation.from_quat(result["frame_rotation"]).as_matrix(), base_r, atol=1e-12
    )


def test_old_cpd_save_projects_without_mutating_atoms_and_discards_stale_display_data():
    design = Design.from_json(Path("tests/fixtures/cpd_2hb_1xt.nadoc").read_text())
    original = design.to_json()
    payload = design.to_dict()
    inject_cpd_representation(payload)
    lesion = payload["photoproduct_junctions"][0]
    assert set(lesion["representation_geometry"]) == set(lesion["design_coordinates"])
    for key, geometry in lesion["representation_geometry"].items():
        assert geometry["backbone_position"] == lesion["design_coordinates"][key]["O5'"]
        # The base reference uses the six ring atoms, excluding O2/O4/C7.
        np.testing.assert_allclose(
            geometry["base_position"],
            np.mean(
                [lesion["design_coordinates"][key][name] for name in PYRIMIDINE_RING],
                axis=0,
            ),
            atol=1e-12,
        )
    assert design.to_json() == original
    restored = Design.from_dict(payload)
    assert restored.to_json() == original  # display projection is not authored state


def test_projection_tracks_o5_torsion_and_ignores_non_ring_substituents():
    atoms = {n: list(xyz) for n, _, *xyz in (*_SUGAR, *_DT_BASE)}
    before = project_cpd_residue(atoms)
    atoms["O5'"] = [2.0, -1.0, 3.0]  # independently moved phosphate arm
    for n in ("O2", "O4", "C7"):
        atoms[n] = [9.0, 8.0, 7.0]
    after = project_cpd_residue(atoms)
    assert after["backbone_position"] == atoms["O5'"]
    assert before["backbone_position"] != after["backbone_position"]
    assert after["base_position"] == before["base_position"]
    np.testing.assert_allclose(after["frame_rotation"], before["frame_rotation"])
