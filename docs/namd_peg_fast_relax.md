# Managed PEG fast relaxation

The atomistic PEG review now creates a prepared **fast relax child job**. Open
`workspace/NAMD_PEG8_wall_review.nadoc`, choose **Create fast relax job**, then
**Simulations → NAMD → Run**. The ordinary Stop/Resume controls and skip-acceleration
toggle apply. Select the child to inspect its PEG frames; **Refresh frames** loads
newly completed chunks and **PEG relaxation stage** selects older chunks.

## Physical protocol

- Fresh 4,800-iteration minimization on the original physical masses.
- 25 ps at 2 fs, rigid hydrogen bonds, GPU-resident integration.
- One 4.8 ns relaxation rung at 4 fs with the shared hydrogen mass repartitioning
  writer (threefold non-water hydrogen masses, conserved total mass, water unchanged).
- Standard p10/p50/p100 chunk fractions (10%, 40%, 50% of the rung). Velocities are
  reinitialized at the physical-to-HMR mass transition. Later chunks retain velocities.
- Fixed orthorhombic NVT slit; source temperature (294 K in the prepared case),
  original repulsive walls and permanent harmonic grafts throughout.

This adapts the standard fast integrator and chunk/skip mechanism to PEG. It does
not apply the DNA protocol's three ENM-release rungs to a system with no DNA ENM.
It does not enable NPT, which would change the fixed-wall geometry. General DNA/PEG
mixtures, different cells and production promotion remain separate qualifications.
The source document, source job and molecular topology remain unchanged.

## Safety and skipping

Every completed chunk checks native completion/resident integration, finite
energies, sampled wall penetration below 1 Å, anchor excursion below 1.5 Å, and
agreement between the logged wall/graft energies and an independent analytic
calculation. Missing evidence fails the validation. RATTLE failure does not silently
soften this protocol. Stop/resume uses the normal restart machinery; validation
includes continuation trajectories and logs.

Skip acceleration additionally requires the existing energy plateau test **and**
a plateau of each chain's radius of gyration and height. At least 20 structural
samples are needed; two disjoint trailing ten-frame windows and their between-window mean drift
must pass: drift below 5% and fluctuations below 10%. These are provisional operational thresholds, not a validated proof of
brush equilibrium. Solvent-dominated energy alone cannot authorize skipping.
The 2 fs warm-up is never skipped. A skip preserves restart lineage through the
standard alias mechanism, and skipped chunks remain explicitly marked in the job.

A native completion marker is required; the last energy print need not coincide
with the final integration step. This fixed a false failure at step 12,500 when the
last energy record was at 12,400.

## MC initialization assessment

Keep graft positions fixed and randomize **chain conformations**, unless a different
surface graft distribution is itself the experimental variable. A reproducible
configurational-bias/torsion Monte Carlo initializer with bond geometry, PEG torsion
energies, inter-chain excluded volume and the same slit would remove the artificial
symmetry of identical extended seeds. Merely assigning random atomic positions is
not a viable initializer. Dense brushes can require regrowth moves rather than
local torsional moves to explore conformations efficiently.

Use MC as an optional seed generator, followed by atomistic solvation, minimization
and MD relaxation. A coarse-grained or implicit-solvent MC ensemble is not the same
ensemble as explicit-water atomistic PEG. Compare independent MC seeds and the
current extended seed using chain dimensions, density profiles and overlap checks;
convergence between initial ensembles matters more than a low initial energy.
MC generation is not implemented in this change; it must first produce an isolated
review artifact before replacing the current molecular initialization.

Relevant primary literature: [configurational-bias MC for dense polymer brushes](https://arxiv.org/abs/1710.03256),
[all-atom PEG brush structure and dynamics](https://pubs.acs.org/doi/10.1021/acs.macromol.5c00733).

## Native validation (2026-09-12)

Completed job `ab217dbdf612` used the identical integrators, forces and chunk runner,
with the 4 fs rung shortened to 100 ps: 25 ps warm-up + 10/40/50 ps chunks. All
four chunks passed wall/graft/native-completion checks. No chunk qualified for
skipping; all ran. Maximum sampled penetration was 0.4701 Å and maximum sampled
graft displacement 0.9169 Å. This validates the execution path; it does not claim
that a 4.8 ns relaxation or thermodynamic equilibration has completed.

Full-length job `48c1995afbd5` retains its successful minimization and 25 ps warm-up.
Its original false health failure (energy-print cadence) was corrected without
changing the molecular configuration or the native outputs.

The measured 4 fs stage throughput on this small case is about 73 ns/day. Tcl wall
evaluation still requires CPU work and host/device transfers; GPU-resident
integration does not imply a GPU-native wall implementation.

## Software verification

- New fast-relax tests: **4 passed** (timing, non-energy skip criteria, native package
  HMR/mass/force continuity, input tamper rejection and final-step completion).
- Frontend: **402 files / 6,267 tests passed**.
- `just smoke`: **23 passed**; temporary designs and report artifacts were removed.
- Playwright: **1 passed**, exercising actual child preparation, NAMD job selection,
  enabled Run controls, completed warm-up/4 fs stage selection and trajectory scrubbing.
  Exact temporary child jobs were deleted in failure-safe teardown and absence verified.
- `just test-smart`: **FULL**, **8,666 passed, 143 skipped, 1 xfailed, 15 failed**.
  The same 12 unavailable BigO/smallO fixtures, two oxDNA PEG-live bonded-distance
  errors and SNUPI RPY RMSF tolerance failure remain; see the prior wall validation
  notes. No full-suite deferral.
- New/changed PEG and runner files pass Ruff; `git diff --check` passes. Repository
  `just lint` retains its two existing findings (`routes_oxdna.py` unused `seq`,
  `test_oxdna_peg.py` unused `Path`). This turn adds **0 lines to main.js**.

The actual development API successfully started, stopped and resumed full-length
job `48c1995afbd5`. Stop preserved the 10,000-step 4 fs checkpoint; resume wrote
`peg_relax_p10.resume1.conf` and a new `peg_relax_p10.cont1.dcd`. At handoff the
job is **running**, with no error, in the p10 chunk. The 4.8 ns maximum-duration
run has not completed. The completed 125 ps validation job remains available.

The later continuation-parsing failure and its fix are documented in [skip verification](namd_peg_skip_validation.md), including precise failure messages and positive/negative runner tests.
