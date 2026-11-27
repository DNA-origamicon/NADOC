from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException
from scipy.spatial.transform import Rotation

from backend.api.routes_oxdna import TorsionTest, _run_checkpoint, _torsion_checkpoints
from backend.core.oxdna_job import OxdnaJob, OxdnaStageStatus, OxdnaStatus
from backend.core.oxdna_torsion import (
    TORQUE_UNIT, TorsionFixture, _balanced_forces, forces_text, resolve_fixture,
)
from backend.core.oxdna_torsion_metrics import measure_frame


def test_finished_relaxation_and_production_are_separate_checkpoints(tmp_path):
    stages = [
        OxdnaStageStatus("2_md_relax", "md_relax", 1000, "done"),
        OxdnaStageStatus("3_equil", "equil", 1000, "done"),
        OxdnaStageStatus("4_production", "production", 2000, "done"),
        OxdnaStageStatus("5_production", "production", 2000, "pending"),
    ]
    job = OxdnaJob(job_id="fixture-parent", design_name="wheel", stages=stages,
                   status=OxdnaStatus.completed, created_at=0.0)
    for stage in stages[:3]:
        conf = job.stage_dir(tmp_path, stage.name) / "last_conf.dat"
        conf.parent.mkdir(parents=True)
        conf.write_text(stage.name)

    assert _torsion_checkpoints(job, tmp_path) == [
        {"stage": "3_equil", "kind": "relaxation"},
        {"stage": "4_production", "kind": "production"},
    ]
    for stage in ("3_equil", "4_production"):
        conf, name = _run_checkpoint(job, tmp_path, SimpleNamespace(checkpoint_stage=stage))
        assert name == conf.read_text() == stage
    assert _run_checkpoint(job, tmp_path, None)[1] == "4_production"
    with pytest.raises(HTTPException, match="Choose a saved"):
        _run_checkpoint(job, tmp_path, SimpleNamespace(checkpoint_stage="5_production"))


AXIS = np.array([0., 0., 1.])
CLAMP = np.array([[1., 0., 0.], [-1., 0., 0.], [0., 1., 0.]])
DRIVE = np.array([[8., 0., 0.], [-8., 0., 0.], [0., 8., 0.], [0., -8., 0.]])


def test_balanced_force_has_zero_resultant_and_signed_axial_moment():
    forces = _balanced_forces(DRIVE, AXIS, -80)
    np.testing.assert_allclose(forces.sum(axis=0), 0, atol=1e-12)
    np.testing.assert_allclose(
        np.cross(DRIVE, forces).sum(axis=0) * TORQUE_UNIT, -80 * AXIS, atol=1e-12,
    )
    with pytest.raises(ValueError, match="opposite sides"):
        _balanced_forces(DRIVE[[0, 2]], AXIS, 80)


def test_rotation_command_reaction_and_relative_twist_use_checkpoint_frame():
    images = [[0, 0, 0]] * len(CLAMP)
    load_images = [[40, 0, 0]] * len(DRIVE)
    fixture = TorsionFixture(
        mode="rotation", steps=2000, target=20, clamp_stiffness=20,
        drive_stiffness=5, checkpoint_sha256="unused", axis=AXIS.tolist(),
        center=[0, 0, 0], box=[40] * 3, clamp_indices=list(range(3)),
        drive_indices=list(range(3, 7)), clamp_positions=CLAMP.tolist(),
        drive_positions=DRIVE.tolist(), clamp_images=images,
        drive_images=load_images, drive_forces=[],
    )
    text = forces_text(fixture, banked_steps=1000)
    assert text.count("type = trap\n") == 3
    assert text.count("type = twist\n") == 4
    assert "center = 40,0,0" in text
    base = float(next(row.split(" = ")[1] for row in text.splitlines() if row.startswith("base = ")))
    assert base == pytest.approx(np.deg2rad(10))

    clamp = Rotation.from_rotvec(AXIS * np.deg2rad(1)).apply(CLAMP)
    drive = Rotation.from_rotvec(AXIS * np.deg2rad(8)).apply(DRIVE) + load_images
    row = measure_frame(fixture, 1000, np.vstack((clamp, drive)))
    assert row["command"] == pytest.approx(10)
    assert row["twist_deg"] == pytest.approx(7)
    assert row["applied_torque_pn_nm"] == pytest.approx(4 * 8**2 * 5 * np.sin(np.deg2rad(2)) * TORQUE_UNIT)
    assert row["clamp_reaction_pn_nm"] == pytest.approx(3 * 20 * np.sin(np.deg2rad(1)) * TORQUE_UNIT)


@pytest.fixture
def fixture_checkpoint(tmp_path, monkeypatch):
    from backend.core import oxdna_torsion as torsion

    landmarks = [[2, 2, 1], [2, 5, 5]]
    keys = [(f"h{i}", 0, "FORWARD") for i in range(9)]
    monkeypatch.setattr(torsion, "_strand_nucleotide_order", lambda design: keys)
    monkeypatch.setattr(torsion, "resolve_anchor_particles",
                        lambda design, refs: ([0, 1, 2] if refs[0]["id"] == "anchor-cluster"
                                              else [int(refs[0]["id"])], []))
    checkpoint = tmp_path / "conf.dat"
    body = ["t = 0", "b = 40 40 40", "E = 0 0 0"]
    body.extend(" ".join(map(str, [*p, 1, 0, 0, 0, 0, 1])) for p in np.vstack((CLAMP, DRIVE, landmarks)))
    checkpoint.write_text("\n".join(body) + "\n")
    return checkpoint, [{"kind": "strand", "id": str(i)} for i in range(9)]


def test_fixture_validates_frozen_checkpoint_and_overlap(fixture_checkpoint):
    checkpoint, refs = fixture_checkpoint
    request = TorsionTest(target=5, clamp=refs[:3], drive=refs[3:7])
    fixture = resolve_fixture(SimpleNamespace(), checkpoint, request, 2000)
    assert fixture.clamp_indices == [0, 1, 2]
    assert fixture.drive_indices == [3, 4, 5, 6]
    np.testing.assert_allclose(fixture.axis, AXIS, atol=1e-12)
    request.checkpoint_sha256 = "0" * 64
    with pytest.raises(ValueError, match="checkpoint changed"):
        resolve_fixture(SimpleNamespace(), checkpoint, request, 2000)
    request.checkpoint_sha256 = None
    request.drive.append(request.clamp[0])
    with pytest.raises(ValueError, match="overlap"):
        resolve_fixture(SimpleNamespace(), checkpoint, request, 2000)


@pytest.mark.parametrize("kind", ["selections", "coordinates"])
def test_axis_can_be_offset_from_both_grips_and_reuse_structure_anchors(fixture_checkpoint, kind):
    from backend.core.constants import OXDNA_LENGTH_UNIT

    checkpoint, refs = fixture_checkpoint
    point = np.array([2, 2, 1])
    axis = ({"kind": kind, "start": refs[7:8], "end": refs[8:]} if kind == "selections"
            else {"kind": kind, "point_nm": point * OXDNA_LENGTH_UNIT, "direction": [0, 3, 4]})
    request = TorsionTest(target=20, axis=axis, clamp_anchors=[{"kind": "cluster", "id": "anchor-cluster"}],
                          drive=refs[3:7])
    fixture = resolve_fixture(SimpleNamespace(), checkpoint, request, 2000)
    assert fixture.clamp_indices == [0, 1, 2]
    np.testing.assert_allclose(fixture.center, point)
    np.testing.assert_allclose(fixture.axis, [0, 0.6, 0.8])
    assert "center = 2,2,1" in forces_text(fixture)
    assert "axis = 0,0.6,0.8" in forces_text(fixture)
    rotated = Rotation.from_rotvec(np.asarray(fixture.axis) * np.deg2rad(10)).apply(DRIVE - point) + point
    row = measure_frame(fixture, 1000, np.vstack((CLAMP, rotated)))
    assert row["twist_deg"] == pytest.approx(10)
    assert row["applied_torque_pn_nm"] == pytest.approx(0, abs=1e-8)


@pytest.mark.parametrize(("axis", "error"), [
    ({"kind": "selections", "start": [{"kind": "strand", "id": "7"}],
      "end": [{"kind": "strand", "id": "7"}]}, "coincident centers"),
    ({"kind": "coordinates", "point_nm": [0, 0, 0], "direction": [0, 0, 0]}, "nonzero direction"),
])
def test_axis_rejects_undefined_direction(fixture_checkpoint, axis, error):
    checkpoint, refs = fixture_checkpoint
    request = TorsionTest(target=5, axis=axis, clamp=refs[:3], drive=refs[3:7])
    with pytest.raises(ValueError, match=error):
        resolve_fixture(SimpleNamespace(), checkpoint, request, 2000)


def test_pose_is_registered_to_checkpoint_and_can_drive_without_anchors(fixture_checkpoint, tmp_path, monkeypatch):
    from backend.core import oxdna_torsion
    from backend.core.constants import OXDNA_LENGTH_UNIT

    reference, _ = fixture_checkpoint
    checkpoint = tmp_path / "rotated.dat"
    transform = Rotation.from_euler("Y", 45, degrees=True)
    offset = np.array([2, 3, 1])
    records = reference.read_text().splitlines()
    points = np.array([list(map(float, row.split()[:3])) for row in records[3:]])
    moved = transform.apply(points) + offset
    records[3:] = [" ".join(map(str, [*p, 1, 0, 0, 0, 0, 1])) for p in moved]
    checkpoint.write_text("\n".join(records) + "\n")
    monkeypatch.setattr(oxdna_torsion, "unwrap_align_to_reference", lambda posed, *args, **kwargs: posed)

    request = TorsionTest(target=10, axis={"kind": "pose", "position_nm": [0, OXDNA_LENGTH_UNIT, 0],
                                         "rotation_deg": [30, 0, 0]})
    fixture = resolve_fixture(SimpleNamespace(), checkpoint, request, 2000, design_reference=reference)
    assert fixture.clamp_indices == []
    assert fixture.drive_indices == list(range(len(points)))
    expected_axis = transform.apply(Rotation.from_euler("X", 30, degrees=True).apply([0, 0, 1]))
    np.testing.assert_allclose(fixture.axis, expected_axis)
    np.testing.assert_allclose(fixture.center, [2, 4, 1])
    assert "type = trap\n" not in forces_text(fixture)
    assert forces_text(fixture).count("type = twist") == len(points)
    sample = measure_frame(fixture, 0, moved)
    assert sample["twist_deg"] == pytest.approx(0)
    assert sample["clamp_reaction_pn_nm"] is None
    assert sample["clamp_max_displacement_nm"] is None
