import hashlib
import json
from pathlib import Path

import pytest

from backend.parameterization.photoproduct_qm import (
    audit_electrostatic_properties,
    audit_water_scf_calibration,
    audit_water_interaction_series,
    audit_frequency_result,
    audit_optimized_model,
    build_qm_job_series,
    generate_geometry_retry_job,
    generate_psi4_job,
    generate_water_interaction_job,
    generate_torsion_scan_job,
    parse_xyz,
    parse_psi4_output,
    parse_electrostatic_properties_output,
    parse_vibrational_frequencies,
    parse_water_interaction_output,
    qm_protocol,
    reconcile_psi4_run,
    render_psi4_input,
    run_psi4_job,
    run_psi4_series,
)
from backend.core.photoproduct_chemistry import load_chemical_definition
from backend.core.photoproduct_chemistry import signed_tetrahedron_volume
from backend.parameterization.photoproduct_references import (
    ReferenceAssetError,
    fetch_verified_asset,
)


ROOT = Path(__file__).resolve().parents[1]


WATER_XYZ = """3
water smoke model
O 0.000 0.000 0.000
H 0.000 0.000 0.960
H 0.926 0.000 -0.240
"""

PROBE_WATER_XYZ = """3
translated CHARMM water probe
O 2.800 0.000 0.000
H 2.800 0.000 0.960
H 3.726 0.000 -0.240
"""


def test_protocol_pins_legacy_additive_charmm_target_methods():
    protocol = qm_protocol()
    assert protocol["engine"] == {"name": "Psi4", "version": "1.11"}
    assert protocol["jobs"]["geometry_optimization"]["method"] == "mp2"
    assert protocol["jobs"]["geometry_optimization"]["basis"] == "6-31G(d)"
    assert protocol["jobs"]["water_interaction"]["method"] == "hf"
    assert protocol["jobs"]["water_interaction"]["neutral_energy_scale"] == 1.16
    assert protocol["jobs"]["water_interaction"]["distance_offset_angstrom"] == -0.2
    assert protocol["version"] == "1.5.0"
    assert protocol["jobs"]["fixed_geometry_hessian"]["required_derivatives"] == [
        "gradient",
        "full_cartesian_hessian",
    ]
    assert protocol["jobs"]["electrostatic_properties"]["method"] == "hf"
    assert protocol["jobs"]["water_interaction"]["scf_type"] == "df"
    assert protocol["jobs"]["water_interaction"]["reference_scf_type"] == "direct"


def test_generic_fixed_geometry_job_requires_reviewed_plan(tmp_path: Path):
    xyz = tmp_path / "model.xyz"
    xyz.write_text("1\nfixture\nH 0.0 0.0 0.0\n")
    with pytest.raises(ValueError, match="reviewed coupled-conformer plan"):
        generate_psi4_job(
            product_id="fixture",
            model_id="fixture",
            xyz_path=xyz,
            output_dir=tmp_path / "job",
            job_kind="fixed_geometry_hessian",
            charge=0,
            multiplicity=1,
            atom_map=["H"],
        )


def test_original_protocol_is_immutable_historical_evidence():
    from pathlib import Path

    path = (
        Path(__file__).parents[1]
        / "backend/data/forcefield/photoproduct_qm_protocol_v1.0.0.json"
    )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "4e9e66cea4ddf80fb1d3a4ebb49e5a66d50df34cb1593feb6cd4d2f562b9107d"
    )


def test_v1_1_protocol_is_immutable_historical_evidence():
    from pathlib import Path

    path = (
        Path(__file__).parents[1]
        / "backend/data/forcefield/photoproduct_qm_protocol_v1.1.0.json"
    )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "806b2841b2f8770da2782db45e1c8913e2bc21251b11eb2ba2ae9f9a9a4d9f39"
    )


def test_v1_2_protocol_is_immutable_historical_evidence():
    from pathlib import Path

    path = (
        Path(__file__).parents[1]
        / "backend/data/forcefield/photoproduct_qm_protocol_v1.2.0.json"
    )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "0dd6948f8fb90c0d93927ee12cd514f09e2260d64cfbe3babe9501a43854f20a"
    )


def test_v1_3_protocol_is_immutable_historical_evidence():
    from pathlib import Path

    path = (
        Path(__file__).parents[1]
        / "backend/data/forcefield/photoproduct_qm_protocol_v1.3.0.json"
    )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "fe375ab813de8325455a1bfd7a7ad19e5204d27554afca159e7e921c63626a67"
    )


def test_xyz_and_psi4_render_are_deterministic_and_charge_aware():
    atoms, comment = parse_xyz(WATER_XYZ)
    assert len(atoms) == 3 and comment == "water smoke model"
    neutral, metadata = render_psi4_input(
        WATER_XYZ, job_kind="geometry_optimization", charge=0, multiplicity=1
    )
    assert "optimize('mp2'" in neutral
    assert "basis 6-31G(d)" in neutral
    assert "no_reorient" in neutral
    charged, charged_metadata = render_psi4_input(
        WATER_XYZ, job_kind="frequency", charge=-1, multiplicity=2
    )
    assert "basis 6-31+G(d)" in charged
    assert "wavefunction.hessian()" in charged
    assert "hessian_hartree_per_bohr2.txt" in charged
    assert charged_metadata["basis"] == "6-31+G(d)"
    assert metadata["atom_count"] == 3
    electrostatic, electrostatic_metadata = render_psi4_input(
        WATER_XYZ,
        job_kind="electrostatic_properties",
        charge=0,
        multiplicity=1,
    )
    assert "oeprop(wavefunction, 'DIPOLE')" in electrostatic
    assert "print_out('NADOC_DIPOLE_AU" in electrostatic
    assert "NADOC_DIPOLE_AU" in electrostatic
    assert electrostatic_metadata["method"] == "hf"


def test_electrostatic_property_parser_requires_explicit_vector_marker():
    parsed = parse_electrostatic_properties_output(
        "Dipole moment 99 99 99\nNADOC_DIPOLE_AU -0.5 0.25 0.0\n"
    )
    assert parsed["complete"] is True
    assert parsed["dipole_au"] == [-0.5, 0.25, 0.0]
    assert parsed["dipole_magnitude_au"] == pytest.approx(0.5590169944)


def test_electrostatic_audit_hash_links_passed_geometry(tmp_path):
    parent = tmp_path / "optimized_model_audit.json"
    parent.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-optimized-model-audit.v1",
                "status": "passed_identity_and_chirality",
                "product_id": "test-product",
                "model_id": "test-model",
            }
        )
    )
    job = {
        "schema": "nadoc.photoproduct-qm-job.v1",
        "product_id": "test-product",
        "model_id": "test-model",
        "job_kind": "electrostatic_properties",
        "method": "hf",
        "basis": "6-31G(d)",
        "parent_manifest": {
            "path": str(parent),
            "sha256": hashlib.sha256(parent.read_bytes()).hexdigest(),
        },
    }
    job_path = tmp_path / "job_manifest.json"
    job_path.write_text(json.dumps(job))
    output = tmp_path / "output.dat"
    output.write_text("NADOC_DIPOLE_AU -0.5 0.25 0.0\n")
    run = {
        "status": "completed_unreviewed",
        "job_manifest_sha256": hashlib.sha256(job_path.read_bytes()).hexdigest(),
        "outputs": {
            "output.dat": {"sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
        },
    }
    (tmp_path / "run_manifest.json").write_text(json.dumps(run))
    report = audit_electrostatic_properties(tmp_path)
    assert report["passed"] is True
    assert report["dipole_au"] == [-0.5, 0.25, 0.0]
    assert report["gate_effect"] == "none"


def test_generated_job_is_hashed_but_cannot_pass_a_gate(tmp_path):
    xyz = tmp_path / "model.xyz"
    xyz.write_text(WATER_XYZ)
    output = tmp_path / "job"
    manifest = generate_psi4_job(
        product_id="test-product",
        model_id="water",
        xyz_path=xyz,
        output_dir=output,
        job_kind="conformer_single_point",
        charge=0,
        multiplicity=1,
        atom_map=["O", "H1", "H2"],
        memory_gib=2,
        threads=2,
    )
    assert manifest["status"] == "generated_not_run"
    assert manifest["gate_effect"] == "none"
    assert len(manifest["input"]["sha256"]) == 64
    assert json.loads((output / "job_manifest.json").read_text()) == manifest
    assert "energy('mp2'" in (output / "input.dat").read_text()


def test_generated_job_accepts_hash_linked_stereo_candidate(tmp_path):
    xyz = tmp_path / "candidate.xyz"
    xyz.write_text(WATER_XYZ)
    atom_map_path = tmp_path / "atom_map.json"
    atom_map = ["O", "H1", "H2"]
    atom_map_path.write_text(json.dumps(atom_map))
    candidate = {
        "schema": "nadoc.tt-cpd-stereo-candidate.v1",
        "status": "candidate_not_reviewed",
        "product_id": "tt-cpd-cis-syn-ii",
        "model_id": "candidate-model",
        "outputs": {
            "xyz": {"sha256": hashlib.sha256(xyz.read_bytes()).hexdigest()},
            "atom_map": {
                "path": str(atom_map_path),
                "sha256": hashlib.sha256(atom_map_path.read_bytes()).hexdigest(),
            },
        },
    }
    candidate_path = tmp_path / "candidate_manifest.json"
    candidate_path.write_text(json.dumps(candidate))
    manifest = generate_psi4_job(
        product_id="tt-cpd-cis-syn-ii",
        model_id="candidate-model",
        xyz_path=xyz,
        output_dir=tmp_path / "job",
        job_kind="geometry_optimization",
        charge=0,
        multiplicity=1,
        atom_map=atom_map,
        model_manifest_path=candidate_path,
        memory_gib=2,
        threads=2,
    )
    assert manifest["model_manifest"]["evidence_status"] == "candidate_not_reviewed"
    assert manifest["expected_outputs"] == ["output.dat", "optimized.xyz"]


def test_generated_frequency_preserves_candidate_evidence_status(tmp_path):
    xyz = tmp_path / "optimized.xyz"
    xyz.write_text(WATER_XYZ)
    parent = {
        "schema": "nadoc.photoproduct-optimized-model-audit.v1",
        "status": "passed_candidate_identity_and_chirality",
        "product_id": "tt-cpd-cis-syn-ii",
        "model_id": "candidate-model",
        "optimized_xyz": {"sha256": hashlib.sha256(xyz.read_bytes()).hexdigest()},
    }
    parent_path = tmp_path / "optimized_model_audit.json"
    parent_path.write_text(json.dumps(parent))
    manifest = generate_psi4_job(
        product_id="tt-cpd-cis-syn-ii",
        model_id="candidate-model",
        xyz_path=xyz,
        output_dir=tmp_path / "frequency",
        job_kind="frequency",
        charge=0,
        multiplicity=1,
        atom_map=["O", "H1", "H2"],
        parent_manifest_path=parent_path,
        memory_gib=2,
        threads=2,
    )
    assert manifest["parent_manifest"]["evidence_status"] == (
        "passed_candidate_identity_and_chirality"
    )
    assert manifest["expected_outputs"] == [
        "output.dat",
        "hessian_hartree_per_bohr2.txt",
    ]


def test_generated_job_keeps_boundary_model_cap_review_gate(tmp_path):
    xyz = tmp_path / "boundary.xyz"
    xyz.write_text(WATER_XYZ)
    atom_map = ["O", "H1", "H2"]
    atom_map_path = tmp_path / "atom_map.json"
    atom_map_path.write_text(json.dumps(atom_map))
    model = {
        "schema": "nadoc.photoproduct-dna-boundary-model-candidate.v1",
        "status": "candidate_pending_cap_review",
        "product_id": "tt-cpd-cis-syn",
        "model_id": "boundary-model",
        "outputs": {
            "xyz": {"sha256": hashlib.sha256(xyz.read_bytes()).hexdigest()},
            "atom_map": {
                "path": str(atom_map_path),
                "sha256": hashlib.sha256(atom_map_path.read_bytes()).hexdigest(),
            },
        },
    }
    model_path = tmp_path / "model.json"
    model_path.write_text(json.dumps(model))
    manifest = generate_psi4_job(
        product_id="tt-cpd-cis-syn",
        model_id="boundary-model",
        xyz_path=xyz,
        output_dir=tmp_path / "job",
        job_kind="geometry_optimization",
        charge=-1,
        multiplicity=1,
        atom_map=atom_map,
        model_manifest_path=model_path,
    )
    assert manifest["model_manifest"]["evidence_status"] == (
        "candidate_pending_cap_review"
    )
    with pytest.raises(ValueError, match="approved cap/protonation review"):
        run_psi4_job(
            job_dir=tmp_path / "job",
            psi4_executable=Path("/bin/false"),
            scratch_dir=tmp_path / "scratch",
        )

    model["status"] = "human_cap_review_complete"
    model["cap_review"] = {
        "decision": "APPROVE",
        "reviewer": "Jojo Reviewer",
        "rationale": "Caps and phosphate protonation were visually checked.",
        "source_geometry_sha256": hashlib.sha256(xyz.read_bytes()).hexdigest(),
    }
    reviewed_model_path = tmp_path / "reviewed-model.json"
    reviewed_model_path.write_text(json.dumps(model))
    reviewed = generate_psi4_job(
        product_id="tt-cpd-cis-syn",
        model_id="boundary-model",
        xyz_path=xyz,
        output_dir=tmp_path / "reviewed-job",
        job_kind="geometry_optimization",
        charge=-1,
        multiplicity=1,
        atom_map=atom_map,
        model_manifest_path=reviewed_model_path,
    )
    assert reviewed["model_manifest"]["evidence_status"] == (
        "human_cap_review_complete"
    )


def test_series_runner_reuses_only_hash_validated_completed_children(tmp_path):
    jobs = []
    for index in range(2):
        job_dir = tmp_path / f"job-{index}"
        job_dir.mkdir()
        job_path = job_dir / "job_manifest.json"
        job_path.write_text(json.dumps({"schema": "nadoc.photoproduct-qm-job.v1"}))
        output = job_dir / "output.dat"
        output.write_text(f"completed {index}\n")
        run = {
            "status": "completed_unreviewed",
            "job_manifest_sha256": hashlib.sha256(job_path.read_bytes()).hexdigest(),
            "returncode": 0,
            "outputs": {
                "output.dat": {
                    "sha256": hashlib.sha256(output.read_bytes()).hexdigest()
                }
            },
        }
        (job_dir / "run_manifest.json").write_text(json.dumps(run))
        jobs.append(
            {
                "job_dir": str(job_dir),
                "job_manifest_sha256": hashlib.sha256(
                    job_path.read_bytes()
                ).hexdigest(),
            }
        )
    series_path = tmp_path / "series_manifest.json"
    series_path.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-water-probe-series.v1",
                "jobs": jobs,
            }
        )
    )
    report = run_psi4_series(
        series_manifest_path=series_path,
        psi4_executable=tmp_path / "not-needed-for-reuse",
        scratch_root=tmp_path / "scratch",
        max_parallel=2,
    )
    assert report["status"] == "completed_unreviewed"
    assert report["reused_count"] == 2
    assert report["completed_count"] == 2
    assert report["gate_effect"] == "none"


def test_generic_series_hash_links_one_job_kind(tmp_path):
    job_dirs = []
    for index in range(2):
        job_dir = tmp_path / f"job-{index}"
        job_dir.mkdir()
        (job_dir / "job_manifest.json").write_text(
            json.dumps(
                {
                    "schema": "nadoc.photoproduct-qm-job.v1",
                    "product_id": f"product-{index}",
                    "job_kind": "geometry_optimization",
                }
            )
        )
        job_dirs.append(job_dir)
    output = tmp_path / "series.json"
    series = build_qm_job_series(job_dirs, output_path=output)
    assert series["job_kind"] == "geometry_optimization"
    assert len(series["jobs"]) == 2
    assert all(len(item["job_manifest_sha256"]) == 64 for item in series["jobs"])


def test_reconciliation_hashes_known_geometry_output_from_legacy_manifest(tmp_path):
    job = {
        "schema": "nadoc.photoproduct-qm-job.v1",
        "job_kind": "geometry_optimization",
        "expected_outputs": ["output.dat"],
    }
    job_path = tmp_path / "job_manifest.json"
    job_path.write_text(json.dumps(job))
    output = tmp_path / "output.dat"
    output.write_text("Optimizer: Optimization complete\nPsi4 exiting successfully\n")
    optimized = tmp_path / "optimized.xyz"
    optimized.write_text(WATER_XYZ)
    run = {
        "status": "completed_unreviewed",
        "returncode": 0,
        "job_manifest_sha256": hashlib.sha256(job_path.read_bytes()).hexdigest(),
        "outputs": {
            "output.dat": {"sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
        },
    }
    (tmp_path / "run_manifest.json").write_text(json.dumps(run))
    reconciliation = reconcile_psi4_run(tmp_path)
    assert reconciliation["status"] == "completed_unreviewed"
    assert (
        reconciliation["outputs"]["optimized.xyz"]["sha256"]
        == hashlib.sha256(optimized.read_bytes()).hexdigest()
    )
    assert json.loads((tmp_path / "run_manifest.json").read_text()) == run


def test_specialized_targets_cannot_be_generated_as_generic_jobs():
    with pytest.raises(ValueError, match="specialized generator"):
        render_psi4_input(WATER_XYZ, job_kind="torsion_scan", charge=0, multiplicity=1)


def test_water_interaction_generator_requires_reviewed_parent_and_tip3p(tmp_path):
    model = tmp_path / "model.xyz"
    model.write_text(WATER_XYZ)
    water = tmp_path / "water.xyz"
    water.write_text(PROBE_WATER_XYZ)
    parent = tmp_path / "optimized_model_audit.json"
    parent.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-optimized-model-audit.v1",
                "status": "passed_identity_and_chirality",
                "product_id": "test-product",
                "model_id": "water-model",
                "optimized_xyz": {
                    "sha256": hashlib.sha256(model.read_bytes()).hexdigest()
                },
            }
        )
    )
    manifest = generate_water_interaction_job(
        product_id="test-product",
        model_id="water-model",
        model_xyz_path=model,
        water_xyz_path=water,
        parent_manifest_path=parent,
        atom_map=["O", "H1", "H2"],
        probe_id="reviewed-O-acceptor-series-01",
        target_atom="O",
        probe_atom="O",
        output_dir=tmp_path / "water-job",
        memory_gib=2,
        threads=2,
    )
    rendered = (tmp_path / "water-job/input.dat").read_text()
    assert rendered.count("= energy('hf'") == 3
    assert manifest["distance_offset_angstrom"] == -0.2
    assert manifest["energy_scale"] == 1.16
    assert manifest["counterpoise_corrected"] is False
    assert manifest["scf_type"] == "df"
    assert manifest["scf_calibration_role"] == "production"
    assert "scf_type df" in rendered
    assert manifest["gate_effect"] == "none"

    bad_water = tmp_path / "bad-water.xyz"
    bad_water.write_text(PROBE_WATER_XYZ.replace("0.960", "1.300"))
    with pytest.raises(ValueError, match="O-H lengths"):
        generate_water_interaction_job(
            product_id="test-product",
            model_id="water-model",
            model_xyz_path=model,
            water_xyz_path=bad_water,
            parent_manifest_path=parent,
            atom_map=["O", "H1", "H2"],
            probe_id="bad",
            target_atom="O",
            probe_atom="O",
            output_dir=tmp_path / "bad-water-job",
        )


def test_water_scf_calibration_requires_three_paired_sites(tmp_path):
    from backend.parameterization.photoproduct_qm import QM_PROTOCOL_PATH

    protocol_hash = hashlib.sha256(QM_PROTOCOL_PATH.read_bytes()).hexdigest()
    job_dirs = []
    for site_index in range(3):
        for role, scf_type, energy in (
            ("candidate", "df", -2.0 - site_index),
            ("reference", "direct", -2.01 - site_index),
        ):
            job_dir = tmp_path / f"site-{site_index}-{role}"
            job_dir.mkdir()
            job = {
                "schema": "nadoc.photoproduct-qm-job.v1",
                "job_kind": "water_interaction",
                "product_id": "test-product",
                "model_id": "test-model",
                "method": "hf",
                "basis": "6-31G(d)",
                "charge": 0,
                "multiplicity": 1,
                "protocol_sha256": protocol_hash,
                "probe_id": f"site-{site_index}",
                "target_atom": f"1:O{site_index}",
                "probe_atom": "H1",
                "target_probe_distance_angstrom": 2.4,
                "source_xyz": {"sha256": "a" * 64},
                "water_xyz": {"sha256": f"{site_index + 1:064x}"},
                "scf_type": scf_type,
                "scf_calibration_role": role,
            }
            job_path = job_dir / "job_manifest.json"
            job_path.write_text(json.dumps(job))
            output = job_dir / "output.dat"
            output.write_text(
                f"NADOC_WATER_INTERACTION_HARTREE {energy / 627.5094740631:.14f}\n"
                f"NADOC_WATER_INTERACTION_KCAL_MOL {energy:.10f}\n"
                f"NADOC_WATER_TARGET_KCAL_MOL {energy * 1.16:.10f}\n"
            )
            run = {
                "status": "completed_unreviewed",
                "job_manifest_sha256": hashlib.sha256(
                    job_path.read_bytes()
                ).hexdigest(),
                "outputs": {
                    "output.dat": {
                        "sha256": hashlib.sha256(output.read_bytes()).hexdigest()
                    }
                },
            }
            (job_dir / "run_manifest.json").write_text(json.dumps(run))
            job_dirs.append(job_dir)
    report = audit_water_scf_calibration(
        job_dirs, output_path=tmp_path / "calibration.json"
    )
    assert report["passed"] is True
    assert report["distinct_site_count"] == 3
    assert report["maximum_observed_absolute_error_kcal_mol"] == pytest.approx(0.01)
    assert report["gate_effect"] == "none"


def test_water_scf_override_is_explicitly_role_checked(tmp_path):
    model = tmp_path / "model.xyz"
    model.write_text(WATER_XYZ)
    water = tmp_path / "water.xyz"
    water.write_text(PROBE_WATER_XYZ)
    parent = tmp_path / "optimized_model_audit.json"
    parent.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-optimized-model-audit.v1",
                "status": "passed_identity_and_chirality",
                "product_id": "test-product",
                "model_id": "water-model",
                "optimized_xyz": {
                    "sha256": hashlib.sha256(model.read_bytes()).hexdigest()
                },
            }
        )
    )
    manifest = generate_water_interaction_job(
        product_id="test-product",
        model_id="water-model",
        model_xyz_path=model,
        water_xyz_path=water,
        parent_manifest_path=parent,
        atom_map=["O", "H1", "H2"],
        probe_id="reference-site",
        target_atom="O",
        probe_atom="O",
        output_dir=tmp_path / "reference-job",
        scf_type_override="direct",
        scf_calibration_role="reference",
    )
    assert manifest["scf_type"] == "direct"
    assert manifest["scf_calibration_role"] == "reference"
    with pytest.raises(ValueError, match="candidate water job must use df"):
        generate_water_interaction_job(
            product_id="test-product",
            model_id="water-model",
            model_xyz_path=model,
            water_xyz_path=water,
            parent_manifest_path=parent,
            atom_map=["O", "H1", "H2"],
            probe_id="bad-role",
            target_atom="O",
            probe_atom="O",
            output_dir=tmp_path / "bad-role-job",
            scf_type_override="direct",
            scf_calibration_role="candidate",
        )


def test_water_output_parser_uses_only_explicit_markers():
    parsed = parse_water_interaction_output(
        "SCF total energy = -100.0\n"
        "NADOC_WATER_INTERACTION_HARTREE -0.01000000000000\n"
        "NADOC_WATER_INTERACTION_KCAL_MOL -6.2750947406\n"
        "NADOC_WATER_TARGET_KCAL_MOL -7.2791098991\n"
    )
    assert parsed["complete"] is True
    assert parsed["interaction_hartree"] == pytest.approx(-0.01)
    assert parsed["scaled_target_kcal_mol"] == pytest.approx(-7.2791098991)


def test_water_series_audit_requires_bracketed_dense_curve(tmp_path):
    job_dirs = []
    energies = (0.5, -1.0, -2.0, -1.2, 0.2)
    for index, (distance, energy) in enumerate(
        zip((2.0, 2.2, 2.4, 2.6, 2.8), energies, strict=True)
    ):
        job_dir = tmp_path / f"p{index}"
        job_dir.mkdir()
        job = {
            "schema": "nadoc.photoproduct-qm-job.v1",
            "job_kind": "water_interaction",
            "product_id": "test-product",
            "model_id": "test-model",
            "probe_id": "acceptor-O2",
            "target_atom": "1:O2",
            "probe_atom": "H1",
            "protocol_sha256": "a" * 64,
            "target_probe_distance_angstrom": distance,
        }
        job_path = job_dir / "job_manifest.json"
        job_path.write_text(json.dumps(job))
        raw = (
            f"NADOC_WATER_INTERACTION_HARTREE {energy / 627.5094740631:.14f}\n"
            f"NADOC_WATER_INTERACTION_KCAL_MOL {energy:.10f}\n"
            f"NADOC_WATER_TARGET_KCAL_MOL {energy * 1.16:.10f}\n"
        )
        raw_path = job_dir / "output.dat"
        raw_path.write_text(raw)
        run = {
            "status": "completed_unreviewed",
            "job_manifest_sha256": hashlib.sha256(job_path.read_bytes()).hexdigest(),
            "outputs": {
                "output.dat": {
                    "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest()
                }
            },
        }
        (job_dir / "run_manifest.json").write_text(json.dumps(run))
        job_dirs.append(job_dir)
    report = audit_water_interaction_series(
        job_dirs, output_path=tmp_path / "water_audit.json"
    )
    assert report["passed"] is True
    assert report["minimum_point_index"] == 2
    assert report["gate_effect"] == "none"


def test_psi4_output_parser_requires_optimization_completion():
    incomplete = parse_psi4_output(
        "DF-MP2 Total Energy = -123.456\nPsi4 exiting successfully",
        "geometry_optimization",
    )
    assert incomplete["passed_execution_checks"] is False
    complete = parse_psi4_output(
        "Optimizer: Optimization complete\n"
        "DF-MP2 Total Energy = -123.456\n"
        "Psi4 exiting successfully",
        "geometry_optimization",
    )
    assert complete["passed_execution_checks"] is True
    assert complete["final_energy_hartree"] == pytest.approx(-123.456)
    incomplete_scan = parse_psi4_output(
        "DF-MP2 Total Energy = -123.456\nPsi4 exiting successfully",
        "torsion_scan",
    )
    assert incomplete_scan["passed_execution_checks"] is False


def test_psi4_output_parser_accepts_psi4_111_final_geometry_marker():
    parsed = parse_psi4_output(
        "Final optimized geometry and variables\n"
        "Final Energy: -2235.2109495572236\n"
        "Psi4 exiting successfully\n",
        "geometry_optimization",
    )
    assert parsed["optimization_complete"] is True
    assert parsed["passed_execution_checks"] is True


def test_protocol_170_caps_optking_step_without_changing_qm_target():
    protocol = (
        ROOT
        / "backend/data/forcefield/photoproduct_qm_protocol_v1.7.0.json"
    )
    rendered, metadata = render_psi4_input(
        WATER_XYZ,
        job_kind="geometry_optimization",
        charge=-1,
        multiplicity=1,
        maximum_geometry_iterations=400,
        protocol_path=protocol,
    )
    assert metadata["protocol_version"] == "1.7.0"
    assert metadata["method"] == "mp2"
    assert metadata["basis"] == "6-31+G(d)"
    assert metadata["optimizer_settings"] == {
        "intrafrag_step_limit": 0.1,
        "intrafrag_step_limit_max": 0.25,
    }
    assert "g_convergence gau_tight" in rendered
    assert "intrafrag_step_limit 0.1" in rendered
    assert "intrafrag_step_limit_max 0.25" in rendered
    assert "geom_maxiter 400" in rendered


def test_geometry_retry_uses_last_hash_linked_geometry_and_keeps_convergence(tmp_path):
    source = tmp_path / "source.xyz"
    source.write_text(WATER_XYZ)
    failed_dir = tmp_path / "failed"
    original = generate_psi4_job(
        product_id="tt-cpd-cis-syn",
        model_id="retry-test",
        xyz_path=source,
        output_dir=failed_dir,
        job_kind="geometry_optimization",
        charge=0,
        multiplicity=1,
        atom_map=["O", "H1", "H2"],
        memory_gib=2,
        threads=2,
    )
    raw = failed_dir / "output.dat"
    raw.write_text(
        "Geometry (in Angstrom), charge = 0, multiplicity = 1:\n\n"
        "O  0.100 0.000 0.000\n"
        "H  0.100 0.000 0.960\n"
        "H  1.026 0.000 -0.240\n\n"
        "PsiException: Could not converge geometry optimization in 50 iterations.\n"
    )
    run = {
        "schema": "nadoc.photoproduct-qm-run.v1",
        "status": "failed",
        "job_manifest_sha256": hashlib.sha256(
            (failed_dir / "job_manifest.json").read_bytes()
        ).hexdigest(),
        "stdout_tail": (
            "OptimizationConvergenceError: Could not converge geometry optimization "
            "in 50 iterations."
        ),
        "parsed": {"final_energy_hartree": -76.0},
        "outputs": {
            "output.dat": {"sha256": hashlib.sha256(raw.read_bytes()).hexdigest()}
        },
    }
    (failed_dir / "run_manifest.json").write_text(json.dumps(run))

    retry = generate_geometry_retry_job(
        failed_job_dir=failed_dir,
        output_dir=tmp_path / "retry",
        maximum_iterations=100,
    )

    assert retry["retry_policy"]["convergence_criterion_unchanged"] is True
    assert retry["retry_parent"]["failed_final_energy_hartree"] == -76.0
    assert retry["protocol_sha256"] == original["protocol_sha256"]
    assert retry["maximum_geometry_iterations"] == 100
    assert "geom_maxiter 100" in (tmp_path / "retry/input.dat").read_text()
    atoms, _ = parse_xyz((tmp_path / "retry/restart.xyz").read_text())
    assert atoms[0][1:] == pytest.approx((0.1, 0.0, 0.0))


def test_torsion_generator_requires_hashed_reviewed_point_geometry(tmp_path):
    xyz = tmp_path / "point.xyz"
    xyz.write_text("4\n90 degree point\nC 0 0 0\nC 1 0 0\nC 1 1 0\nC 1 1 1\n")
    graph = tmp_path / "model_graph.json"
    graph.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-model-graph.v1",
                "atoms": [{"key": key} for key in ("A", "B", "C", "D")],
                "bonds": [
                    {"atoms": ["A", "B"], "order": 1.0},
                    {"atoms": ["B", "C"], "order": 1.0},
                    {"atoms": ["C", "D"], "order": 1.0},
                ],
            }
        )
        + "\n"
    )
    plan = tmp_path / "scan_plan.json"
    plan.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-torsion-scan-plan.v2",
                "product_id": "test-product",
                "model_id": "test-model",
                "reviewed_by": "unit-test reviewer",
                "review_rationale": "explicit synthetic geometry",
                "charge": 0,
                "multiplicity": 1,
                "atom_map": ["A", "B", "C", "D"],
                "torsion_atoms": ["A", "B", "C", "D"],
                "model_graph": {
                    "path": str(graph),
                    "sha256": hashlib.sha256(graph.read_bytes()).hexdigest(),
                },
                "points": [
                    {
                        "id": "p090",
                        "target_degrees": 90.0,
                        "xyz_sha256": hashlib.sha256(xyz.read_bytes()).hexdigest(),
                    }
                ],
            }
        )
    )
    manifest = generate_torsion_scan_job(
        scan_plan_path=plan,
        point_id="p090",
        xyz_path=xyz,
        output_dir=tmp_path / "job",
        memory_gib=2,
        threads=2,
    )
    rendered = (tmp_path / "job/input.dat").read_text()
    assert 'frozen_dihedral = ("' in rendered
    assert "1 2 3 4" in rendered
    assert manifest["starting_degrees"] == pytest.approx(90.0)
    assert manifest["central_bond_context"]["central_bond_in_cycle"] is False
    assert manifest["gate_effect"] == "none"

    changed = json.loads(plan.read_text())
    changed["points"][0]["target_degrees"] = 120.0
    plan.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="differs from target"):
        generate_torsion_scan_job(
            scan_plan_path=plan,
            point_id="p090",
            xyz_path=xyz,
            output_dir=tmp_path / "bad-job",
        )


def test_torsion_generator_rejects_a_cyclic_central_bond(tmp_path):
    xyz = tmp_path / "ring.xyz"
    xyz.write_text("4\nring\nC 0 0 0\nC 1 0 0\nC 1 1 0\nC 1 1 1\n")
    graph = tmp_path / "ring_graph.json"
    graph.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-model-graph.v1",
                "atoms": [{"key": key} for key in ("A", "B", "C", "D")],
                "bonds": [
                    {"atoms": ["A", "B"], "order": 1.0},
                    {"atoms": ["B", "C"], "order": 1.0},
                    {"atoms": ["C", "D"], "order": 1.0},
                    {"atoms": ["D", "A"], "order": 1.0},
                ],
            }
        )
        + "\n"
    )
    plan = tmp_path / "ring_plan.json"
    plan.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-torsion-scan-plan.v2",
                "product_id": "test-product",
                "model_id": "test-model",
                "reviewed_by": "unit-test reviewer",
                "review_rationale": "exercise the cyclic-bond fail-closed gate",
                "charge": 0,
                "multiplicity": 1,
                "atom_map": ["A", "B", "C", "D"],
                "torsion_atoms": ["A", "B", "C", "D"],
                "model_graph": {
                    "path": str(graph),
                    "sha256": hashlib.sha256(graph.read_bytes()).hexdigest(),
                },
                "points": [
                    {
                        "id": "p090",
                        "target_degrees": 90.0,
                        "xyz_sha256": hashlib.sha256(xyz.read_bytes()).hexdigest(),
                    }
                ],
            }
        )
        + "\n"
    )
    with pytest.raises(ValueError, match="forbidden for cyclic central bonds"):
        generate_torsion_scan_job(
            scan_plan_path=plan,
            point_id="p090",
            xyz_path=xyz,
            output_dir=tmp_path / "ring-job",
        )


def test_frequency_parser_preserves_imaginary_mode_sign():
    parsed = parse_vibrational_frequencies(
        "  Freq [cm^-1]          12.3456i    44.0000  100.5\n"
    )
    assert parsed[0]["imaginary"] is True
    assert parsed[0]["value_cm_inverse"] == pytest.approx(-12.3456)
    assert [item["value_cm_inverse"] for item in parsed[1:]] == [44.0, 100.5]


def test_frequency_audit_requires_all_3n_minus_6_modes_and_no_imaginary(tmp_path):
    parent = tmp_path / "optimized_model_audit.json"
    parent.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-optimized-model-audit.v1",
                "status": "passed_identity_and_chirality",
                "product_id": "test-product",
                "model_id": "water-model",
            }
        )
    )
    job = {
        "schema": "nadoc.photoproduct-qm-job.v1",
        "product_id": "test-product",
        "model_id": "water-model",
        "job_kind": "frequency",
        "atom_count": 3,
        "expected_outputs": ["output.dat", "hessian_hartree_per_bohr2.txt"],
        "hessian_units": "hartree/bohr^2",
        "parent_manifest": {
            "path": str(parent),
            "sha256": hashlib.sha256(parent.read_bytes()).hexdigest(),
        },
    }
    job_path = tmp_path / "job_manifest.json"
    job_path.write_text(json.dumps(job))
    output = tmp_path / "output.dat"
    output.write_text("  Freq [cm^-1]       100.0  200.0  300.0\n")
    hessian = tmp_path / "hessian_hartree_per_bohr2.txt"
    hessian.write_text("\n".join(" ".join(["0.0"] * 9) for _ in range(9)) + "\n")
    run = {
        "status": "completed_unreviewed",
        "job_manifest_sha256": hashlib.sha256(job_path.read_bytes()).hexdigest(),
        "outputs": {
            "output.dat": {"sha256": hashlib.sha256(output.read_bytes()).hexdigest()},
            "hessian_hartree_per_bohr2.txt": {
                "sha256": hashlib.sha256(hessian.read_bytes()).hexdigest()
            },
        },
    }
    (tmp_path / "run_manifest.json").write_text(json.dumps(run))
    report = audit_frequency_result(tmp_path)
    assert report["status"] == "passed_harmonic_minimum"
    assert report["parsed_mode_count"] == 3
    assert report["imaginary_mode_count"] == 0
    assert report["cartesian_hessian"]["status"] == "passed"
    assert report["cartesian_hessian"]["dimension"] == 9
    assert report["gate_effect"] == "none"

    # A durable frequency job may outlive the originally declared optimized-model path.
    # Only the byte-identical, job-bound provenance copy is accepted in that case.
    (tmp_path / "frequency_audit.json").unlink()
    provenance_dir = tmp_path / "provenance"
    provenance_dir.mkdir()
    parent_copy = provenance_dir / "optimized_model_parent.json"
    parent_copy.write_bytes(parent.read_bytes())
    (tmp_path / "frequency_job_provenance.json").write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-frequency-job-provenance-copy.v1",
                "status": "materialized_byte_identical",
                "gate_effect": "none",
                "product_id": job["product_id"],
                "model_id": job["model_id"],
                "frequency_job_manifest": {
                    "path": "job_manifest.json",
                    "sha256": hashlib.sha256(job_path.read_bytes()).hexdigest(),
                },
                "references": {
                    "parent_manifest": {
                        "original_path": str(parent),
                        "sha256": hashlib.sha256(parent.read_bytes()).hexdigest(),
                        "copy": {
                            "path": "provenance/optimized_model_parent.json",
                            "sha256": hashlib.sha256(
                                parent_copy.read_bytes()
                            ).hexdigest(),
                        },
                    }
                },
            }
        )
        + "\n"
    )
    parent.unlink()
    relocated_report = audit_frequency_result(tmp_path)
    assert relocated_report["status"] == "passed_harmonic_minimum"
    assert relocated_report["parent_optimized_model_audit"]["relocated"] is True
    assert relocated_report["parent_optimized_model_audit"]["effective_path"] == str(
        parent_copy.resolve()
    )


def test_reference_fetch_is_atomic_hash_checked_and_reuses_cache(tmp_path):
    payload = b"reviewed structural bytes"
    digest = hashlib.sha256(payload).hexdigest()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return payload

    calls = []

    def opener(url, timeout):
        calls.append((url, timeout))
        return Response()

    target = tmp_path / "reference.dat"
    first = fetch_verified_asset(
        url="https://example.invalid/reference",
        expected_sha256=digest,
        destination=target,
        opener=opener,
    )
    second = fetch_verified_asset(
        url="https://example.invalid/reference",
        expected_sha256=digest,
        destination=target,
        opener=opener,
    )
    assert first["cache"] == "downloaded"
    assert second["cache"] == "reused"
    assert len(calls) == 1
    target.write_bytes(b"changed")
    with pytest.raises(ReferenceAssetError, match="cached reference digest mismatch"):
        fetch_verified_asset(
            url="https://example.invalid/reference",
            expected_sha256=digest,
            destination=target,
            opener=opener,
        )


def test_optimized_model_audit_preserves_identity_and_signed_chirality(tmp_path):
    definition = load_chemical_definition("TT-CPD", "cis-syn")
    coordinates = definition["source_ring_coordinates_angstrom"]
    atom_map = list(coordinates)
    xyz_lines = [str(len(atom_map)), "test optimized geometry"]
    xyz_lines.extend(
        f"C {coordinates[key][0]} {coordinates[key][1]} {coordinates[key][2]}"
        for key in atom_map
    )
    optimized = tmp_path / "optimized.xyz"
    optimized.write_text("\n".join(xyz_lines) + "\n")
    job = {
        "schema": "nadoc.photoproduct-qm-job.v1",
        "product_id": "tt-cpd-cis-syn",
        "model_id": "test-model",
        "job_kind": "geometry_optimization",
        "atom_map": atom_map,
    }
    job_path = tmp_path / "job_manifest.json"
    job_path.write_text(json.dumps(job))
    run = {
        "status": "completed_unreviewed",
        "job_manifest_sha256": hashlib.sha256(job_path.read_bytes()).hexdigest(),
        "parsed": {"final_energy_hartree": -983.25},
        "outputs": {
            "optimized.xyz": {
                "sha256": hashlib.sha256(optimized.read_bytes()).hexdigest()
            }
        },
    }
    (tmp_path / "run_manifest.json").write_text(json.dumps(run))
    report = audit_optimized_model(tmp_path)
    assert report["status"] == "passed_identity_and_chirality"
    assert report["chirality_audit"]["passed"] is True
    assert report["final_energy_hartree"] == pytest.approx(-983.25)
    assert len(report["product_ring_bond_distances"]) == 4
    assert report["minimum_confirmation"].startswith("not_run")


def test_optimized_model_audit_keeps_unreleased_candidate_gate_neutral(tmp_path):
    coordinates = {
        "1:C5": [0.0, 0.0, 0.0],
        "1:C4": [1.0, 0.0, 0.0],
        "1:C6": [0.0, 1.0, 0.0],
        "1:C7": [0.0, 0.0, 1.0],
        "1:N1": [1.0, 1.0, 0.0],
        "1:H6": [0.0, 1.0, 1.0],
        "2:C5": [3.0, 0.0, 0.0],
        "2:C4": [4.0, 0.0, 0.0],
        "2:C6": [3.0, 1.0, 0.0],
        "2:C7": [3.0, 0.0, 1.0],
        "2:N1": [4.0, 1.0, 0.0],
        "2:H6": [3.0, 1.0, 1.0],
    }
    reference_atoms = {
        "1:C5": ["1:C4", "1:C6", "1:C7"],
        "1:C6": ["1:N1", "1:C5", "1:H6"],
        "2:C5": ["2:C4", "2:C6", "2:C7"],
        "2:C6": ["2:N1", "2:C5", "2:H6"],
    }
    records = []
    for atom, references in reference_atoms.items():
        value = signed_tetrahedron_volume(coordinates, atom, references)
        records.append(
            {
                "atom": atom,
                "reference_atoms": references,
                "expected_sign": "positive" if value > 0 else "negative",
            }
        )
    atom_map = list(coordinates)
    optimized = tmp_path / "optimized.xyz"
    optimized.write_text(
        "\n".join(
            [str(len(atom_map)), "candidate optimized geometry"]
            + [
                f"C {coordinates[key][0]} {coordinates[key][1]} {coordinates[key][2]}"
                for key in atom_map
            ]
        )
        + "\n"
    )
    candidate = {
        "schema": "nadoc.tt-cpd-stereo-candidate.v1",
        "status": "candidate_not_reviewed",
        "product_id": "tt-cpd-cis-syn-ii",
        "model_id": "candidate-model",
        "model_signed_volume_stereochemistry": records,
    }
    candidate_path = tmp_path / "candidate_manifest.json"
    candidate_path.write_text(json.dumps(candidate))
    job = {
        "schema": "nadoc.photoproduct-qm-job.v1",
        "product_id": "tt-cpd-cis-syn-ii",
        "model_id": "candidate-model",
        "job_kind": "geometry_optimization",
        "atom_map": atom_map,
        "model_manifest": {
            "schema": "nadoc.tt-cpd-stereo-candidate.v1",
            "path": str(candidate_path),
            "sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
        },
    }
    job_path = tmp_path / "job_manifest.json"
    job_path.write_text(json.dumps(job))
    run = {
        "status": "completed_unreviewed",
        "job_manifest_sha256": hashlib.sha256(job_path.read_bytes()).hexdigest(),
        "outputs": {
            "optimized.xyz": {
                "sha256": hashlib.sha256(optimized.read_bytes()).hexdigest()
            }
        },
    }
    (tmp_path / "run_manifest.json").write_text(json.dumps(run))
    report = audit_optimized_model(tmp_path)
    assert report["status"] == "passed_candidate_identity_and_chirality"
    assert report["chemical_definition_status"] == "candidate_only"
    assert report["gate_effect"] == "none"
