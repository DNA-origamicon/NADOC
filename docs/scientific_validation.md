# Scientific validation (explicit opt-in only)

`just test`, `test-all`, `test-smart`, `test-slow`, and ordinary pytest run software
validation only. Scientific campaigns are deselected centrally even when selecting
a file or using `-m slow`; `NADOC_RUN_OXDNA_SLOW` no longer enables them.
A FULL smart-test decision means the full **software** suite. Scientific campaigns
are never automatic change-based debt.

List individual collected cases without executing fixtures or simulations:

```sh
just test-scientific-list
```

Only when scientific validation is specifically requested, open a test session and
name the desired module or node:

```sh
just test-session
just test-scientific tests/test_skip_twist_tuning_production.py::test_proxy_loop_mechanics_2x3x40
```

This uses `pytest --scientific`, which selects scientific tests exclusively. The
session/resource guards remain in force. Existing assertions and physical
thresholds remain unchanged. Some campaigns require installed native engines.

Software validation retains known-run configuration, topology, bounded native
startup/execution, decoding, job lifecycle, deterministic numerical/reference and
geometry regression checks. Long tests are not automatically scientific: e.g.
the small NAMD benchmark lifecycle smoke remains software validation. The legacy
mrDNA zero-step accuracy failure is still a software regression to resolve.
CPD tests were not audited or changed in this pass.

The former serial run spent 81% of its 6h19 runtime in just the two production
modules. This separation does not establish a new full-suite runtime; the remaining
software slow suite needs a fresh measured run.

## Inventory

The executable source of truth is `tests/scientific_validation.py`. New physical
campaigns must be registered there or explicitly marked `pytest.mark.scientific`.
A rename/deletion check protects the registry against stale selectors.

| Module / class / test (all parameterizations) | Purpose |
| --- | --- |
| `test_cando_autorefine::test_refine_honeycomb_shape_hits_bend_and_places_marks_off_forbidden` | Physical shape optimisation and twist-relieving density sweeps |
| `test_cando_autorefine::test_refine_plain_square_strut_nulls_twist_where_greedy_kept_zero` | Physical shape optimisation and twist-relieving density sweeps |
| `test_cando_autorefine::test_sweep_skip_period_finds_a_twist_relieving_minimum` | Physical shape optimisation and twist-relieving density sweeps |
| `test_cando_autorefine_validation` | Full FEM density sweep and physical twist relief |
| `test_chudoba_engine::test_molecular_volume_ideal_gas_distribution` | NPT equilibrium volume distribution |
| `test_chudoba_hmc::test_hmc_harmonic_bond_distribution` | HMC equilibrium radial distribution |
| `test_chudoba_hmc::test_hmc_npt_ideal_volume` | HMC equilibrium volume distribution |
| `test_fixed_gold_validation::test_real_dnanm_thermostat_cpu_cuda` | Independent CPU/CUDA thermostat equilibrium sampling |
| `test_headless_oxdna_build::test_field_specimen_reanneals_and_equilibrates_real_engine` | Reannealing, field alignment and melting timescales |
| `test_openmm_checker::TestOpenMMFullMD` | Full MD physical drift thresholds |
| `test_oxdna_extra_base_production` | Relaxation retention and five-million-step extra-base production |
| `test_skip_twist_tuning_production` | Multi-million-step production and iterative physical twist convergence |
| `test_snupi_dynamics::test_breathing_pca_mode_tracks_rmsf_on_real_bundle` | Equilibrium sampling, physical flexibility and dynamical response |
| `test_snupi_dynamics::test_dccm_and_mode_kinetics_primitives_on_real_bundle` | Equilibrium sampling, physical flexibility and dynamical response |
| `test_snupi_dynamics::test_field_with_anchor_deflects_free_region_along_field` | Equilibrium sampling, physical flexibility and dynamical response |
| `test_snupi_dynamics::test_gjf_harmonic_oscillator_position_equipartition` | Equilibrium sampling, physical flexibility and dynamical response |
| `test_snupi_dynamics::test_gjf_linear_network_covariance_matches_kT_Kinv` | Equilibrium sampling, physical flexibility and dynamical response |
| `test_snupi_dynamics::test_matrix_gjf_samples_kT_Kinv_with_full_friction` | Equilibrium sampling, physical flexibility and dynamical response |
| `test_snupi_dynamics::test_modified_gjf_extends_stable_step_on_real_bundle` | Equilibrium sampling, physical flexibility and dynamical response |
| `test_snupi_dynamics::test_modified_gjf_samples_boltzmann_harmonic` | Equilibrium sampling, physical flexibility and dynamical response |
| `test_snupi_dynamics::test_modified_gjf_stable_where_plain_diverges` | Equilibrium sampling, physical flexibility and dynamical response |
| `test_snupi_dynamics::test_rpy_equilibrium_rmsf_matches_stokes_on_real_bundle` | Equilibrium sampling, physical flexibility and dynamical response |
| `test_snupi_dynamics::test_simulate_equilibrium_nonlinear_force_runs_and_tracks_flexibility` | Equilibrium sampling, physical flexibility and dynamical response |
| `test_snupi_dynamics::test_trajectory_rmsf_matches_nma_on_real_bundle` | Equilibrium sampling, physical flexibility and dynamical response |
| `test_snupi_ssdna::test_free_tail_reproduces_the_wlc_end_to_end_distribution` | Langevin thermalisation and WLC equilibrium distribution |
| `test_snupi_ssdna::test_tail_langevin_thermalises_its_bonds_to_kt` | Langevin thermalisation and WLC equilibrium distribution |

## Validation of the separation (2026-09-20)

- Non-CPD collection: 35 scientific cases, 8,963 other cases deselected in scientific mode.
- Six gate/registry tests passed. Collection of production + OpenMM modules selected
  4 scientific cases explicitly; ordinary collection with the old environment flag
  selected 34 software cases and deselected all 4 scientific cases.
- `just test-smart` chose FAST: 8,432 passed, 6 skipped, pytest 81.41 seconds.
  `DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.`
- Guarded wall time was 96 seconds, exceeding the 90-second aggregate backstop.
  Triage found no per-test violators (largest 4.26 seconds); expensive cases were
  distributed across packing, assembly, topology preparation and lifecycle tests.
  No single shared slowdown was established. Do not reclassify these as scientific
  or raise budgets to suppress this outstanding aggregate performance warning.
- Ruff and whitespace checks passed. No scientific campaigns were executed.
  Full software slow-suite runtime remains unmeasured after separation.
