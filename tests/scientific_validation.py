"""Explicit inventory of opt-in scientific campaigns (never ordinary regression debt).

Keys are module, class, or function node IDs without parameter suffixes.
Keep algebra, topology, startup/configuration and bounded engine smoke tests in
software validation. Add physical sampling/production/convergence campaigns here.
"""

CAMPAIGNS = {
    "test_skip_twist_tuning_production": "Multi-million-step production and iterative physical twist convergence",
    "test_oxdna_extra_base_production": "Relaxation retention and five-million-step extra-base production",
    "test_openmm_checker::TestOpenMMFullMD": "Full MD physical drift thresholds",
    "test_headless_oxdna_build::test_field_specimen_reanneals_and_equilibrates_real_engine": "Reannealing, field alignment and melting timescales",
    "test_fixed_gold_validation::test_real_dnanm_thermostat_cpu_cuda": "Independent CPU/CUDA thermostat equilibrium sampling",
    "test_chudoba_engine::test_molecular_volume_ideal_gas_distribution": "NPT equilibrium volume distribution",
    "test_chudoba_hmc::test_hmc_npt_ideal_volume": "HMC equilibrium volume distribution",
    "test_chudoba_hmc::test_hmc_harmonic_bond_distribution": "HMC equilibrium radial distribution",
    "test_cando_autorefine_validation": "Full FEM density sweep and physical twist relief",
}

_GROUPS = {
    "test_snupi_dynamics": (
        "Equilibrium sampling, physical flexibility and dynamical response",
        """test_gjf_harmonic_oscillator_position_equipartition
        test_gjf_linear_network_covariance_matches_kT_Kinv
        test_trajectory_rmsf_matches_nma_on_real_bundle
        test_matrix_gjf_samples_kT_Kinv_with_full_friction
        test_rpy_equilibrium_rmsf_matches_stokes_on_real_bundle
        test_breathing_pca_mode_tracks_rmsf_on_real_bundle
        test_dccm_and_mode_kinetics_primitives_on_real_bundle
        test_simulate_equilibrium_nonlinear_force_runs_and_tracks_flexibility
        test_modified_gjf_samples_boltzmann_harmonic
        test_modified_gjf_stable_where_plain_diverges
        test_modified_gjf_extends_stable_step_on_real_bundle
        test_field_with_anchor_deflects_free_region_along_field""",
    ),
    "test_snupi_ssdna": (
        "Langevin thermalisation and WLC equilibrium distribution",
        "test_tail_langevin_thermalises_its_bonds_to_kt test_free_tail_reproduces_the_wlc_end_to_end_distribution",
    ),
    "test_cando_autorefine": (
        "Physical shape optimisation and twist-relieving density sweeps",
        """test_refine_honeycomb_shape_hits_bend_and_places_marks_off_forbidden
        test_sweep_skip_period_finds_a_twist_relieving_minimum
        test_refine_plain_square_strut_nulls_twist_where_greedy_kept_zero""",
    ),
}
for _module, (_reason, _names) in _GROUPS.items():
    CAMPAIGNS.update({f"{_module}::{name}": _reason for name in _names.split()})


def campaign_reason(nodeid):
    """Match complete components, never substrings or parameter values."""
    key = nodeid.split("/test_")[-1] if "/test_" in nodeid else nodeid
    if not key.startswith("test_"):
        key = "test_" + key
    key = key.replace(".py::", "::").removesuffix(".py").split("[", 1)[0]
    parts = key.split("::")
    for length in range(len(parts), 0, -1):
        if reason := CAMPAIGNS.get("::".join(parts[:length])):
            return reason
    return None
