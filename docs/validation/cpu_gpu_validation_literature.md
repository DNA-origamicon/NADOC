# CPU/GPU molecular-dynamics validation: literature assessment

Reviewed 2026-09-13. This assessment changes neither the recorded campaign results
nor the application's fixed-gold CPU restriction.

## Core numerical and physical checks

1. **Same-configuration energy and force agreement.** OpenMM compares analytical
   unit systems and its Reference platform against accelerated implementations.
   Its documentation reports per-particle symmetric relative force errors,
   `2 |F_ref - F_test| / (|F_ref| + |F_test|)`, summarized by medians.
   The historical Chodera validation-suite README describes a 90th-percentile
   relative force threshold of 1e-3 in single precision and 1e-4 in mixed/double.
   These are suite-specific examples, not universal oxDNA tolerances. Our global
   kick-response L2 error is a different statistic and cannot directly inherit
   those thresholds. For rigid bodies, torque must also be checked.
2. **Energy-force consistency.** The historical OpenMM suite compares computed
   forces with finite-difference derivatives of the potential. For this model,
   rotation derivatives provide the corresponding torque check. Include the
   nanoparticle external potential and attachment energies, not only DNA energy.
3. **Integrator conservation and convergence.** OpenMM evaluates total-energy
   drift in unthermostatted Verlet simulations. Merz and Shirts test the expected
   quadratic timestep dependence of energy fluctuations for second-order
   symplectic integration. Our short kick timestep test is not a replacement for
   a sustained NVE energy-conservation test. Static conservative external fields
   belong in the conserved energy; translational momentum need not be conserved
   when a fixed external gold/anchor field exerts a net force.
4. **Correct ensemble and equipartition.** Merz and Shirts compare kinetic-energy
   distributions with the analytically expected gamma distribution, including
   the mean, width, and subsets of degrees of freedom. Total-system temperature
   can hide incorrectly heated/cooled subsets. Correlation and equilibration
   must be accounted for. This is directly relevant to the Bussi point/rigid
   degree-of-freedom bug. CPU/GPU agreement alone can leave a shared error undetected.
5. **Supplementary physical observables.** Application observables can check for
   consequential sampling bias, but their uncertainty must be adequate. Agreement
   of a particular free DNA end within a chosen nanometre tolerance is not a
   general backend-validation standard identified in these sources.

## Reproducibility and oxDNA-specific evidence

LAMMPS documentation explicitly allows rapidly diverging trajectories from
round-off while requiring statistical properties to agree. Matching long-run
coordinates or random streams is not a general requirement. Our CUDA Bussi RNG
change improves controlled reproducibility; the offset itself was not evidence
of an incorrect ensemble.

Rovigatti et al. (2015), the oxDNA GPU parallelization paper, uses Lennard-Jones,
patchy particles and DNA to benchmark parallelization and employs mixed precision
(single force calculations, double position/momentum integration). Its main
text is primarily a performance study; it does not establish a gold–strep–DNA
end-position tolerance or validate our custom interaction/thermostat changes.

## Implication for NADOC

The extra ±0.5 nm free-end equivalence gate should be treated as an application
sampling diagnostic, not a literature-standard prerequisite for backend
correctness. The original failed intervals must remain visible. This does not
justify declaring the implementation validated simply by dropping that gate:
complete same-configuration energy/force/torque checks, sustained NVE
conservation/timestep scaling, and distribution-level thermometry are the more
appropriate remaining checks. The observed translational-energy uncertainty
should be investigated with the latter tests, not silently discarded.

## Primary sources

- [OpenMM testing and validation](https://docs.openmm.org/latest/userguide/library/07_testing_validation.html).
- [Historical OpenMM validation suite, README](https://github.com/choderalab/openmm-validation/blob/master/README.md), specifically “Old validation suite tests.” This is a work-in-progress repository; its energy-drift check is documented as not triggering regression failures.
- [Merz and Shirts (2018), Testing for physical validity in molecular simulations](https://doi.org/10.1371/journal.pone.0202764).
- [Rovigatti et al. (2015), A comparison between parallelization approaches in molecular dynamics simulations on GPUs](https://doi.org/10.1002/jcc.23763); [accessible manuscript](https://arxiv.org/html/1401.4350).
- [LAMMPS: Common issues often regarded as bugs](https://docs.lammps.org/Errors_common.html).
