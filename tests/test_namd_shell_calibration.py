"""Small analytic tests only; no native engines or production trajectory scans."""

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from experiments.namd_shell_calibration.numerics import (
    KB,
    box_coordinates,
    moments,
    register,
    scalar_update,
)
from experiments.namd_shell_calibration.workflow import psf_atoms, fresh, check_images


def test_box_units_orientation_and_origin():
    rotation = Rotation.from_euler("z", 90, degrees=True)
    box = dict(min_corner=[0, 0, 0], max_corner=[2, 2, 2], rotation=rotation.as_quat())
    np.testing.assert_allclose(
        box_coordinates([[10, 20, 10]], box), [[10, 0, 0]], atol=1e-12
    )


def test_registration_removes_rigid_motion_but_preserves_core_deformation():
    ref = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [1, 1, 1]], float)
    changed = ref.copy()
    changed[3, 2] += 0.7
    moved = changed @ Rotation.from_euler(
        "xyz", [13, 22, 43], degrees=True
    ).as_matrix() + [3, -4, 9]
    aligned, residual = register(moved, ref, [0, 1, 2])
    np.testing.assert_allclose(aligned, changed, atol=1e-12)
    assert residual < 1e-12


def test_degenerate_alignment_refused():
    ref = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]], float)
    with pytest.raises(ValueError, match="degenerate"):
        register(ref, ref, [0, 1, 2])


def test_covariance_retains_anisotropy_and_block_drift():
    x = np.array([[-3, -6, 0], [-1, -2, 0], [1, 2, 0], [3, 6, 0]])[:, None, :]
    mean, cov, drift = moments(x)
    np.testing.assert_allclose(mean, 0)
    np.testing.assert_allclose(
        cov[0], [[20 / 3, 40 / 3, 0], [40 / 3, 80 / 3, 0], [0, 0, 0]]
    )
    np.testing.assert_allclose(drift, [np.sqrt(80)])


def test_update_uses_missing_stiffness_and_namd_factor_two():
    # Toy retained system k=0.2, trial adds 0.1, desired total k=0.25.
    temp = 300
    target = (np.eye(3) * KB * temp / (2 * 0.25))[None]
    trial = (np.eye(3) * KB * temp / (2 * 0.3))[None]
    result, raw = scalar_update(target, trial, 0.1, temp, gain=1)
    np.testing.assert_allclose(result, [0.05])
    np.testing.assert_allclose(raw, [0.05])
    unchanged, _ = scalar_update(target, target, 0.1, temp)
    np.testing.assert_allclose(unchanged, [0.1])


def test_fixed_atom_variance_cannot_be_calibrated():
    with pytest.raises(ValueError, match="zero-variance"):
        scalar_update(np.eye(3)[None], np.zeros((1, 3, 3)), 0.1, 300)


def test_scalar_clipping_is_reported():
    clipped, raw = scalar_update(
        np.eye(3)[None] * 100, np.eye(3)[None] * 0.001, 0.1, 300
    )
    assert raw[0] < 0
    assert clipped[0] == 0


def test_psf_identity_mapping_does_not_assume_solvent_order(tmp_path):
    p = tmp_path / "input.psf"
    p.write_text(
        "PSF\n\n 3 !NATOM\n"
        "1 WAT 1 TIP3 OH2 OT -0.8 16\n"
        "2 D001 7 THY P P 1.5 31\n"
        "3 D001 7 THY C1' CT -0.1 12\n\n 0 !NBOND\n"
    )
    count, atoms = psf_atoms(p)
    assert count == 3
    assert [a["index"] for a in atoms] == [1, 2]
    assert atoms[1]["key"] == ["D001", "7", "THY", "C1'"]


def test_no_overwrite_or_managed_output(tmp_path):
    with pytest.raises(ValueError, match="exists"):
        fresh(tmp_path)
    with pytest.raises(ValueError, match="managed"):
        fresh(tmp_path / "md_jobs" / "new")


def test_periodic_check_uses_connectivity_not_whole_region_extent():
    x = np.array([[0, 0, 0], [3, 0, 0], [6, 0, 0]], float)
    dims = np.array([10, 10, 10, 90, 90, 90])
    check_images(x, dims, [[0, 1], [1, 2]])
    x[1, 0] += 10
    with pytest.raises(ValueError, match="Split"):
        check_images(x, dims, [[0, 1], [1, 2]])


def test_offline_pipeline_profiles_and_compares_without_engine(tmp_path):
    from backend.core.dcd_fast import write_trajectory
    from experiments.namd_shell_calibration.workflow import (
        compare,
        digest,
        profile,
        read_json,
        write_json,
    )

    # Analytic coordinates, not a molecular model. Source files remain byte-identical.
    xyz = np.array(
        [
            [0, 0, 0],
            [3, 0, 0],
            [0, 3, 0],
            [1, 0, 1],
            [0.5, 0.9, 1],
            [-0.5, 0.9, 1],
            [-1, 0, 1],
            [-0.5, -0.9, 1],
            [0.5, -0.9, 1],
            [0, 0, 2],
        ],
        float,
    )
    np.savez_compressed(tmp_path / "reference.npz", coordinates_A=xyz)
    plan = dict(
        reference_npz_sha256=digest(tmp_path / "reference.npz"),
        alignment_indices=[0, 1, 2],
        image_edges=[[0, 1]],
        inserts=[dict(c1_index=9, ring_indices=list(range(3, 9)))],
        wc_pairs=[[2, 9]],
        shell_indices=list(range(3, 9)),
        fixed_indices=[0, 1, 2],
        core_indices=[9],
        atoms=[
            dict(
                index=i,
                key=["D000", "1", "THY", f"X{i}"],
                atom_type="CT",
                charge=0.0,
                mass=12,
            )
            for i in range(10)
        ],
        baseline_k=0.1,
        limitations=[],
        box=dict(min_corner=[-1] * 3, max_corner=[1] * 3, rotation=[0, 0, 0, 1]),
    )
    paths = {}
    plan["source_hashes"] = {}
    for kind, scale in [("reference", 1), ("control", 0.5)]:
        package = tmp_path / kind
        package.mkdir()
        (package / "trial.conf").write_text("wrapAll off\nlangevinTemp 300\n")
        topology = package / "trial.psf"
        topology.write_text("Synthetic topology identity sentinel\n")
        plan["source_hashes"][str(topology)] = digest(topology)
        paths[kind] = package / "trial.dcd"
        frames = []
        for i in range(16):
            x = xyz.copy()
            x[3:, 2] += scale * np.sin(i)
            frames.append(x)
        write_trajectory(paths[kind], len(xyz), frames, len(frames))
        plan[f"{kind}_natoms"] = len(xyz)
        plan[f"{kind}_indices"] = list(range(len(xyz)))
        plan[f"{kind}_package"] = str(package)
    plan_path = tmp_path / "plan.json"
    write_json(plan_path, plan)
    initial = {path: digest(path) for path in paths.values()}
    for kind in paths:
        profile(
            plan_path, paths[kind], kind, tmp_path / f"{kind}-profile", max_frames=16
        )
    compare(
        plan_path,
        tmp_path / "reference-profile/profile.json",
        tmp_path / "control-profile/profile.json",
        300,
        tmp_path / "proposal",
    )
    candidate = read_json(tmp_path / "proposal/candidate.json")
    assert candidate["status"] == "UNVALIDATED_PROPOSAL_NOT_NATIVE_INPUT"
    assert np.all(np.array(candidate["proposed_k"]) < 0.1)
    np.testing.assert_allclose(candidate["holdout_rmsf_ratio"], 0.5, rtol=1e-5)
    assert {path: digest(path) for path in paths.values()} == initial
    with pytest.raises(ValueError, match="share this plan"):
        compare(
            plan_path,
            tmp_path / "control-profile/profile.json",
            tmp_path / "reference-profile/profile.json",
            300,
            tmp_path / "wrong",
        )
    with pytest.raises(ValueError, match="temperature"):
        compare(
            plan_path,
            tmp_path / "reference-profile/profile.json",
            tmp_path / "control-profile/profile.json",
            310,
            tmp_path / "wrong-temp",
        )
    # The production child can use its own verified package without changing
    # the immutable calibration plan or accidentally accepting another box.
    child = tmp_path / "child"
    child.mkdir()
    package = child / "package"
    package.mkdir()
    write_json(child / "job.json", dict(package_subdir="package", name_stem="trial"))
    write_json(
        package / "submodel.json",
        dict(
            box=plan["box"],
            retained_source_indices=list(range(10)),
            mobile_output_indices=[9],
            shell_boundary=dict(
                kind="uniform",
                coefficient_kcal_mol_A2=0.1,
                fixed_output_indices=[0, 1, 2],
                restrained_output_indices=list(range(3, 9)),
            ),
        ),
    )
    (package / "trial.psf").write_text(
        "PSF\n\n10 !NATOM\n"
        + "".join(f"{i + 1} D000 1 THY X{i} CT 0.0 12\n" for i in range(10))
    )
    (package / "trial.conf").write_text("wrapAll off\nlangevinTemp 300\n")
    (package / "trial.dcd").write_bytes(paths["control"].read_bytes())
    profile(
        plan_path,
        package / "trial.dcd",
        "control",
        tmp_path / "child-profile",
        trial_job=child,
    )
    recipe = read_json(package / "submodel.json")
    recipe["shell_boundary"]["coefficient_kcal_mol_A2"] = 0.2
    write_json(package / "submodel.json", recipe)
    with pytest.raises(ValueError, match="boundary selection"):
        profile(
            plan_path,
            package / "trial.dcd",
            "control",
            tmp_path / "invalid-child",
            trial_job=child,
        )
    (tmp_path / "reference/trial.psf").write_text("changed")
    with pytest.raises(ValueError, match="PSF identity changed"):
        profile(plan_path, paths["reference"], "reference", tmp_path / "changed-source")
