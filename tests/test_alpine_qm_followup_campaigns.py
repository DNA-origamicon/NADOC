from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load(relative: str, name: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_relative_energy_alignment_uses_proper_rotation() -> None:
    module = _load(
        "scripts/alpine_qm_relative_energy_campaign/build_campaign.py",
        "relative_energy_campaign_builder",
    )
    reference = np.asarray(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.2, 1.1, 0.0], [0.1, 0.2, 0.8]]
    )
    rotation = np.asarray([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    candidate = reference @ rotation + np.asarray([5.0, -2.0, 3.0])
    aligned = module._align(reference, candidate)
    assert aligned == pytest.approx(reference, abs=1e-12)


def test_relative_energy_alignment_does_not_reflect() -> None:
    module = _load(
        "scripts/alpine_qm_relative_energy_campaign/build_campaign.py",
        "relative_energy_campaign_builder_reflection",
    )
    reference = np.asarray(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.2, 1.1, 0.0], [0.1, 0.2, 0.8]]
    )
    reflected = reference * np.asarray([-1.0, 1.0, 1.0])
    aligned = module._align(reference, reflected)
    assert not np.allclose(aligned, reference, atol=1e-8)


def test_water_cross_clash_excludes_only_target_atom(tmp_path: Path) -> None:
    module = _load(
        "scripts/alpine_qm_water_campaign/build_campaign.py",
        "water_campaign_builder",
    )
    model = tmp_path / "model.xyz"
    water = tmp_path / "water.xyz"
    model.write_text("2\nmodel\nO 0 0 0\nC 0 0 2\n")
    water.write_text("3\nwater\nO 0 0 0.1\nH 0 0 1.9\nH 1 0 0.1\n")
    # The target oxygen is excluded, but the carbon/H contact remains and is severe.
    assert module._cross_clash_ratio(model, water, target_index=0) < 0.7


def test_alternate_water_probe_planes_are_distinct_and_deterministic() -> None:
    module = _load(
        "scripts/alpine_qm_water_campaign/build_campaign.py",
        "water_campaign_alternate_planes",
    )
    original = [
        {"id": "endpoint1-o2-acceptor", "plane_atom": "1:N1"},
        {"id": "endpoint1-o4-acceptor", "plane_atom": "1:N3"},
        {"id": "endpoint2-h3-donor", "plane_atom": "2:C2"},
    ]
    alternate = module._alternate_plane_sites(original)

    assert original[0]["id"] == "endpoint1-o2-acceptor"
    assert [item["id"] for item in alternate] == [
        "endpoint1-o2-acceptor-alt-plane",
        "endpoint1-o4-acceptor-alt-plane",
        "endpoint2-h3-donor-alt-plane",
    ]
    assert [item["plane_atom"] for item in alternate] == ["1:N3", "1:C5", "2:C4"]


def test_water_azimuth_variant_is_explicit_and_deterministic() -> None:
    module = _load(
        "scripts/alpine_qm_water_campaign/build_campaign.py",
        "water_campaign_azimuth_variant",
    )
    original = [{"id": "endpoint1-o2-acceptor", "plane_atom": "1:N1"}]
    rotated = module._azimuth_rotated_sites(original, azimuth_degrees=120.0)
    assert rotated == [
        {
            "id": "endpoint1-o2-acceptor-azimuth-+120",
            "plane_atom": "1:N1",
            "azimuth_degrees": 120.0,
        }
    ]
    assert original == [{"id": "endpoint1-o2-acceptor", "plane_atom": "1:N1"}]


def test_boundary_campaign_is_three_pinned_independent_optimizations() -> None:
    module = _load(
        "scripts/alpine_qm_boundary_campaign/build_campaign.py",
        "boundary_campaign_builder",
    )
    assert module.PRODUCTS == (
        "tt-cpd-cis-syn-ii",
        "tt-cpd-trans-syn-i",
        "tt-cpd-trans-syn-ii",
    )
    script_root = ROOT / "scripts/alpine_qm_boundary_campaign"
    sbatch = (script_root / "campaign_64.sbatch").read_text()
    runner = (script_root / "run_case.sh").read_text()
    assert "#SBATCH --array=0-2" in sbatch
    assert "#SBATCH --cpus-per-task=64" in sbatch
    assert "#SBATCH --time=24:00:00" in sbatch
    assert "Psi4 exiting successfully" in runner
    assert "Optimization is complete" in runner
    assert "failed_preserved" in runner


def test_boundary_recovery_cycle_is_prioritized_and_checkpointed() -> None:
    module = _load(
        "scripts/alpine_qm_boundary_recovery_campaign/build_campaign.py",
        "boundary_recovery_campaign_builder",
    )
    assert module.COMPUTE_CASES == (
        ("tt-cpd-cis-syn", "fresh_screened_seed"),
        ("tt-cpd-cis-syn-ii", "last_preserved_optimizer_geometry"),
        ("tt-cpd-cis-anti-i", "fresh_screened_seed"),
    )
    assert module.RECOVERED_PRODUCT == "tt-cpd-trans-syn-i"
    root = ROOT / "scripts/alpine_qm_boundary_recovery_campaign"
    sbatch = (root / "campaign_32.sbatch").read_text()
    runner = (root / "run_case.sh").read_text()
    submitter = (root / "submit_from_local.sh").read_text()
    collector = (root / "collect_campaign.py").read_text()
    watcher = (root / "watch_and_collect.sh").read_text()
    assert "#SBATCH --partition=amem" in sbatch
    assert "#SBATCH --qos=mem-long" in sbatch
    assert "#SBATCH --cpus-per-task=32" in sbatch
    assert "#SBATCH --time=72:00:00" in sbatch
    assert "#SBATCH --signal=B:USR1@600" in sbatch
    assert "extract_checkpoint.py" in runner
    assert "Final optimized geometry and variables" in runner
    assert "failed_preserved" in runner
    assert 'array_range="0-$((case_count - 1))"' in submitter
    assert "audit_optimized_model" in collector
    assert "passed_first_wave_optimization_identity_audits" in collector
    assert "Do not launch all-eight Hessians" in collector
    assert "rsync -a --partial" in watcher


def test_boundary_recovery_policy_does_not_equate_designs_to_parameter_fits() -> None:
    policy = json.loads(
        (
            ROOT
            / "backend/data/forcefield/photoproduct_qm_cycle_policy_v2.0.1.json"
        ).read_text()
    )
    assert policy["catalog_policy"]["preserve_all_eight_ordered_product_identities"]
    assert policy["catalog_policy"]["automatic_parameter_equivalence"] is False
    assert policy["simulation_ready"] is False
    assert policy["alpine_pilot_resources"]["slurm_memory_gib"] == 240
    assert len(policy["first_wave"]) == 4
    assert len(policy["deferred_independent_full_boundary"]) == 3
    assert "Do not launch all-eight" in policy["expansion_rule"]


def test_boundary_submitter_derives_array_range_from_case_inventory() -> None:
    submitter = (
        ROOT / "scripts/alpine_qm_boundary_campaign/submit_from_local.sh"
    ).read_text()
    assert 'cases="$archive_root/bundle/cases.tsv"' in submitter
    assert 'array_range="0-$((case_count - 1))"' in submitter
    assert "'slurm_array':sys.argv[4]" in submitter
    assert "'slurm_array':'0-2'" not in submitter


def test_boundary_screen_accepts_hash_pinned_exact_cis_syn_policy(
    tmp_path: Path,
) -> None:
    module = _load(
        "scripts/alpine_qm_boundary_campaign/build_campaign.py",
        "boundary_campaign_exact_screen",
    )
    xyz = tmp_path / "candidate.xyz"
    xyz.write_text("1\ncandidate\nH 0 0 0\n")
    atom_map = tmp_path / "atom_map.json"
    atom_map.write_text('["1:H"]\n')
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-parameter-acceptance.v2",
                "version": "2.1.0",
                "automated_qm_input_gates": {
                    "dna_boundary_model": {
                        "policy": "exact-dtpdt-boundary-and-replicates-v1"
                    }
                },
            }
        )
    )
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    screen = tmp_path / "screen.json"
    screen.write_text(
        json.dumps(
            {
                "schema": "nadoc.photoproduct-dna-boundary-model-candidate.v1",
                "status": "quantitatively_screened_boundary",
                "product_id": "tt-cpd-cis-syn",
                "atom_count": 63,
                "formal_charge": -1,
                "simulation_ready": False,
                "gate_effect": "none",
                "quantitative_screening": {
                    "status": "passed_qm_input_screen",
                    "policy": "exact-dtpdt-boundary-and-replicates-v1",
                    "policy_source": {"path": str(policy), "sha256": sha(policy)},
                    "authorizes": "boundary_qm_evidence_generation_only",
                    "releases_parameters": False,
                },
                "outputs": {
                    "xyz": {"path": str(xyz), "sha256": sha(xyz)},
                    "atom_map": {"path": str(atom_map), "sha256": sha(atom_map)},
                },
            }
        )
    )
    payload, resolved_xyz, resolved_map = module._screened_boundary(
        screen, "tt-cpd-cis-syn"
    )
    assert payload["product_id"] == "tt-cpd-cis-syn"
    assert resolved_xyz == xyz
    assert resolved_map == atom_map


def test_canonical_cis_syn_boundary_campaign_is_single_pinned_job() -> None:
    module = _load(
        "scripts/alpine_qm_cis_syn_boundary_campaign/build_campaign.py",
        "cis_syn_boundary_campaign_builder",
    )
    assert module.PRODUCT_ID == "tt-cpd-cis-syn"
    root = ROOT / "scripts/alpine_qm_cis_syn_boundary_campaign"
    sbatch = (root / "campaign_64.sbatch").read_text()
    runner = (root / "run_case.sh").read_text()
    assert "#SBATCH --array=0" in sbatch
    assert "#SBATCH --cpus-per-task=64" in sbatch
    assert "#SBATCH --time=24:00:00" in sbatch
    assert "shared_run_case.sh" in runner


def test_boundary_collector_records_failed_remote_case(tmp_path: Path) -> None:
    module = _load(
        "scripts/alpine_qm_boundary_campaign/collect_campaign.py",
        "boundary_campaign_collector_failure",
    )
    campaign_root = tmp_path / "campaign"
    remote = tmp_path / "remote"
    product = "tt-cpd-trans-syn-i"
    local_case = campaign_root / "bundle/cases" / product
    local_job = local_case / "job"
    local_job.mkdir(parents=True)
    (local_job / "job_manifest.json").write_text("{}\n")
    (local_job / "input.dat").write_text("input\n")
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    case = {
        "job_manifest_sha256": sha(local_job / "job_manifest.json"),
        "input_sha256": sha(local_job / "input.dat"),
    }
    case_path = local_case / "case_manifest.json"
    case_path.write_text(json.dumps(case) + "\n")
    case_hash = sha(case_path)
    campaign = {
        "schema": "nadoc.photoproduct-alpine-boundary-optimization-campaign.v1",
        "product_count": 1,
        "products": [{"product_id": product, "case_manifest_sha256": case_hash}],
    }
    (campaign_root / "campaign_manifest.json").write_text(json.dumps(campaign) + "\n")
    remote_case = remote / product / "1_0/case"
    (remote_case / "job").mkdir(parents=True)
    for source, target in (
        (case_path, remote_case / "case_manifest.json"),
        (local_job / "job_manifest.json", remote_case / "job/job_manifest.json"),
        (local_job / "input.dat", remote_case / "job/input.dat"),
    ):
        target.write_bytes(source.read_bytes())
    completion = {
        "schema": "nadoc.photoproduct-alpine-boundary-optimization-case-completion.v1",
        "status": "failed_preserved",
        "product_id": product,
        "case_manifest_sha256": case_hash,
        "returncode": 1,
        "outputs": {},
    }
    (remote_case.parent / "case_completion.json").write_text(
        json.dumps(completion) + "\n"
    )

    report = module.collect(campaign_root=campaign_root, remote_results=remote)

    assert report["status"] == "incomplete_or_failed"
    assert report["passed_product_count"] == 0
    assert report["products"] == [
        {
            "product_id": product,
            "status": "optimization_failed_preserved",
            "returncode": 1,
            "completion": {
                "path": str(remote_case.parent / "case_completion.json"),
                "sha256": sha(remote_case.parent / "case_completion.json"),
            },
        }
    ]


def test_boundary_frequency_campaign_is_pinned_and_failure_preserving() -> None:
    root = ROOT / "scripts/alpine_qm_boundary_frequency_campaign"
    sbatch = (root / "campaign_64.sbatch").read_text()
    runner = (root / "run_case.sh").read_text()
    collector = (root / "collect_campaign.py").read_text()
    assert "#SBATCH --array=0-7" in sbatch
    assert "#SBATCH --cpus-per-task=64" in sbatch
    assert "#SBATCH --time=24:00:00" in sbatch
    assert "hessian_hartree_per_bohr2.txt" in runner
    assert "failed_preserved" in runner
    assert "audit_frequency_result" in collector


def test_boundary_esp_campaign_is_pinned_and_failure_preserving() -> None:
    root = ROOT / "scripts/alpine_qm_boundary_esp_campaign"
    sbatch = (root / "campaign_16.sbatch").read_text()
    runner = (root / "run_case.sh").read_text()
    builder = (root / "build_campaign.py").read_text()
    collector = (root / "collect_campaign.py").read_text()
    submitter = (root / "submit_from_local.sh").read_text()
    handoff = (root / "wait_build_submit_collect.sh").read_text()
    assert "#SBATCH --array=0-7" in sbatch
    assert "#SBATCH --cpus-per-task=16" in sbatch
    assert "#SBATCH --time=04:00:00" in sbatch
    assert "grid_esp.dat" in runner
    assert "failed_preserved" in runner
    assert "generate_esp_job" in builder
    assert "photoproduct_qm_protocol_v1.6.0.json" in builder
    assert '["GRID_ESP", "DIPOLE"]' in builder
    assert "audit_esp_job" in collector
    assert 'array_range="0-$((case_count - 1))"' in submitter
    assert "all three passed optimization collections" in handoff
    assert "watch_and_collect.sh" in handoff


def test_boundary_water_campaign_is_all_form_charged_and_pinned() -> None:
    root = ROOT / "scripts/alpine_qm_boundary_water_campaign"
    builder = (root / "build_campaign.py").read_text()
    sbatch = (root / "campaign_64.sbatch").read_text()
    handoff = (root / "wait_build_submit_collect.sh").read_text()
    submitter = (
        ROOT / "scripts/alpine_qm_water_campaign/submit_from_local.sh"
    ).read_text()
    assert '"charge": -1' in builder
    assert "len(records) != 8" in builder
    assert 'int(item["job_count"]) != 54' in builder
    assert "#SBATCH --array=0-7" in sbatch
    assert "#SBATCH --cpus-per-task=64" in sbatch
    assert "#SBATCH --time=04:00:00" in sbatch
    assert "all three passed optimization collections" in handoff
    assert 'array_range="0-$((case_count - 1))"' in submitter


def test_boundary_charge_fit_handoff_waits_for_all_evidence() -> None:
    handoff = (
        ROOT
        / "scripts/alpine_qm_boundary_frequency_campaign/wait_fit_boundary_charges.sh"
    ).read_text()
    assert "passed_fit_input_materialization" in handoff
    assert "passed_esp_import_and_audits" in handoff
    assert "passed_import_and_curve_audits" in handoff
    assert "fit-boundary-charge-campaign" in handoff
    assert "par_all36_na.prm" in handoff


def test_boundary_bonded_response_handoff_is_full_boundary_and_corrected() -> None:
    handoff = (
        ROOT / "scripts/alpine_qm_boundary_frequency_campaign/"
        "wait_build_boundary_bonded_responses.sh"
    ).read_text()
    assert "boundary_charge_fit_campaign.json" in handoff
    assert "photoproduct_bonded_refit_policy_v2.json" in handoff
    assert "fixed_qm_reference" in handoff
    assert "angle-urey-bradley-mode omit" in handoff
    assert "build-openmm-linear-response" in handoff
    assert "audit-openmm-fit-identifiability" in handoff
    assert "fit-boundary-bonded-response" in handoff


def test_boundary_candidate_smoke_handoff_uses_real_2fs_namd_and_continues_failures() -> (
    None
):
    handoff = (
        ROOT / "scripts/alpine_qm_boundary_frequency_campaign/"
        "wait_run_boundary_candidate_smokes.sh"
    ).read_text()
    assert "photoproduct_candidate_assembly_policy_v3.json" in handoff
    assert "/home/jojo/Applications/NAMD_3.0.2/psfgen" in handoff
    assert "/home/jojo/Applications/NAMD_3.0.2/namd3" in handoff
    assert "build-candidate-context-topology" in handoff
    assert "--fixture reciprocal-crossover-1xt" in handoff
    assert "--dynamics-steps 50000" in handoff
    assert "failed closed; continuing" in handoff


def test_boundary_solution_smoke_handoff_is_explicit_periodic_and_gate_neutral() -> (
    None
):
    handoff = (
        ROOT / "scripts/alpine_qm_boundary_frequency_campaign/"
        "wait_run_boundary_solution_smokes.sh"
    ).read_text()
    assert "run-candidate-solution-smoke" in handoff
    assert "toppar_water_ions_cufix.str" in handoff
    assert "par_stub_ions_nbfix.str" in handoff
    assert "--ion-conc-mm 150" in handoff
    assert "--heat-steps 10000" in handoff
    assert "--dynamics-steps 50000" in handoff
    assert "failed closed; continuing" in handoff


def test_boundary_context_precondition_handoff_uses_qm_release_and_real_namd() -> None:
    handoff = (
        ROOT / "scripts/alpine_qm_boundary_frequency_campaign/"
        "wait_run_boundary_context_preconditions.sh"
    ).read_text()
    assert "qm_reference_report.json" in handoff
    assert "model/model_manifest.json" in handoff
    assert "run-candidate-context-precondition" in handoff
    assert "photoproduct_context_precondition_policy.json" in handoff
    assert "/home/jojo/Applications/NAMD_3.0.2/psfgen" in handoff
    assert "/home/jojo/Applications/NAMD_3.0.2/namd3" in handoff
    assert (
        "reciprocal-crossover-1xt adjacent-intrastrand antiparallel-interstrand"
        in handoff
    )
    assert '--fixture "$fixture"' in handoff
    assert "24 context preconditions complete" in handoff
    assert "run-candidate-context-solution-smoke" in handoff
    assert "toppar_water_ions_cufix.str" in handoff
    assert "--dynamics-steps 5000" in handoff
    assert "failed closed; continuing" in handoff
