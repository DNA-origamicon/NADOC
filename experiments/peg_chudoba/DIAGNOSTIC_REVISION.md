# Authorized bounded diagnostic revision — 2026-09-10

The original BOUNDED_VALIDATION.md, physical model, 5% CPU/GPU equivalence
band, convergence criteria and production allocation caps remain frozen.
A difference interval wholly inside the band establishes equivalence; wholly
outside establishes resolved disagreement (conditional on adequate sampling);
an overlapping interval is inconclusive. The previous N36 2 fs result is
inconclusive. Statistical resolution alone does not diagnose timestep bias.

Execution: first N36 1 fs, 3 independent CPU origins × 20 ns. Existing N36
2 fs × 20 ns is reused. Only unresolved cohorts receive their already budgeted
80 ns continuation. N135 GPU checks are withheld unless N36 CPU and timestep
comparisons pass. One GPU job at a time. No physical kinetics claim.

Separate EOS proposal diagnostic: N135, 108 chains, 294 K, zero-tail model,
1/100/1000 kPa; baseline, 4× log-volume proposal width, or 4× pivot weight;
three matched origins per condition from completed production round 2.
27 × 2,000 sweeps = 54,000 new diagnostic sweeps, at most 12 CPU workers.
Preserve original volume-attempt rate, translation proposal and Hamiltonian.
Discard first half for exploratory volume/shape ESS, Rhat, drift and ESS per
worker-hour. These short continuations neither reset exhausted production caps
nor establish convergence, and cannot automatically promote a sampler.

Source audit: molecule_volume uses symmetric log(V) proposals, translates chain
centres without scaling internal bonds, recomputes energy and accepts with the
(N_molecules+1) log(Vnew/Vold) term appropriate to its proposal measure. No
obvious Jacobian mismatch was identified. This inspection is not an independent
ensemble proof; detailed balance, acceptance rates and slow collective mixing
remain diagnostic questions. Existing numerical verification hashes and endpoint
energy checks must pass before launch. No force-field refitting is authorized
by an unresolved sampling result.

Outputs: workspace/peg_chudoba/scheduling_294_20260910/diagnostics_revision.
The lease parks historical work during diagnostics and restores it afterward
or upon driver failure. Neither NAMD production nor paid GPU rental is launched.
