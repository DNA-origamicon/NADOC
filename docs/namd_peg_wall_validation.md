# Atomistic PEG with a repulsive wall and harmonic grafts

2026-09-12. Native qualification completed; persistent review and completed-job viewing are available. PEG-only managed fast relaxation is now available; general mixed-system launch wiring remains deferred.

## Model

The support is an infinite planar, half-harmonic repulsive barrier. For signed
distance `d` in Å toward the allowed side,

```
U_wall = k_wall * min(d, 0)^2
F_wall = -2 * k_wall * min(d, 0) * normal
U_graft = k_graft * |minimum_image(r - r_reference)|^2
```

Both stiffnesses use **kcal/mol/Å²**, with **no factor of 1/2**. The wall is a
finite-stiffness approximation to a hard surface: small penetration is expected.
There are no material atoms, adsorption terms, graphene or gold parameters.

Each chain's terminal methyl carbon is tethered to a stationary reference point
using NAMD's native `constraints` / `consref` / `conskfile` positional spring.
The mask contains beta=1 only at one selected carbon per chain;
`constraintScaling` supplies `k_graft`. This is a three-dimensional harmonic
point tether, not a chemical PEG–surface bond. No dummy atom or `fixedAtoms`
constraint is needed; all PEG atoms remain mobile.

The wall uses `TclForces` with one-based atom indices, acting on **every PEG and
water atom every step**, and reports its energy through `addenergy` (`MISC`).
Native graft energy appears in `BOUNDARY`. The implementation reuses
`SurfaceFrame` for orientation, distances and nm-to-Å conversion.

[NAMD's GPU-resident documentation](https://www-s.ks.uiuc.edu/Research/namd/3.0/ug/node102.html)
supports harmonic restraints and Tcl forces. Tcl callbacks require host/device
transfers and CPU work: resident **integration** remains enabled, but the wall is
not an entirely GPU-native force calculation. No throughput advantage is claimed.
The local Dec-2025 NAMD source also implements both paths; the prepared package now confirms native resident compatibility without offload fallback.

## Periodicity and ensemble

The initial qualification uses a fixed orthorhombic NVT cell, origin `L/2`, and a
Z-normal slit. There is a lower wall at 0.2 nm and an opposing upper wall at
`Lz - 0.2 nm`. The second wall prevents escape around the first through the normal
periodic boundary. Wall distances use coordinates modulo the cell length; wrapping
a molecule cannot disable the force. The forbidden slab straddles the periodic
seam. The force implementation supports all three Cartesian axes; this first
chain/solvent builder only supports Z-normal geometry.

NPT, tilted periodic planes, pores and finite patches require separate treatment.
In particular, a fixed wall/reference file must not silently follow a barostat.
This is a periodic slit with 3D PME, not an isolated electrostatic slab correction.

## PEG parameter provenance and chemistry

The builder accepts the unmodified additive ether release from the
[MacKerell distribution](https://mackerell.umaryland.edu/charmm_ff.shtml), associated
with Vorobyov et al. (2007) and Lee et al. (2008). Downloaded assets stay in the
workspace; their provenance and exact hashes are recorded in each package.

| Asset | SHA-256 |
| --- | --- |
| `toppar_ether.tgz` | `c19923a72df861be2e1198ff9a894add2b9a427e2bfb356045edae9368493d17` |
| `top_all35_ethers.rtf` | `cce86e705c2cf9e0339f7123b4470b48525d7539393b4778f8641b412c4b6761` |
| `par_all35_ethers.prm` | `f5da0b0b1c24160ae5a6a38003132956ec27b1438f664b5feffc078b6f4b701d` |

The topology's `PEGM` residue with `HYD1` and `HYD2` caps produces
**CH3–O–(CH2–CH2–O)n–CH3**. This requires **n+1 PEGM residues** for n EO repeats,
not n residues. For n=8 the molecule is C18H38O9, 65 atoms, net charge zero.
These are methyl-capped PEO/PEG-model chains; they are not hydroxyl- or thiol-capped.
No terminal charges or bonded parameters were invented or fitted.

The source explicitly labels the polymer construction entries as not rigorously
tested. Published provenance does not establish this package's correctness or
brush thermodynamics. Native parameter coverage, chain behavior, solvent density,
PEG–water interactions and cap sensitivity remain qualification requirements.

## Prepared case and commands

The prepared case is `workspace/peg_wall_validation/peg8_g2_v1`:
four chains, eight EO repeats each, **260 PEG atoms + 2,944 TIP3P waters = 9,092
atoms**. The 4.8 nm cubic cell gives 0.1736 chains/nm². Graft references are 0.2 nm
above the lower wall. Initial chains are extended, equivalent conformations;
their positions are not independent equilibrated replicas.

Preparation ran VMD/psfgen and solvate, checked net charge, atom/anchor counts,
bond lengths, wall clearance and severe minimum-image heavy-atom overlaps.
Whole solvent molecules outside the permitted cell/slit are removed; whole waters
with severe periodic O/O contacts are also removed. PEG topology is preserved.
The saved `prepared_review.png` was visually inspected. This is unminimized input,
not a simulated result.

```bash
# The user opens the required compute window in their own terminal:
just test-session

# From the repository root, with downloaded official assets:
.venv/bin/python -m experiments.peg_wall.build \
  --assets workspace/peg_wall_validation/assets/toppar_ether \
  --output workspace/peg_wall_validation/peg8_g2_new

.venv/bin/python -m experiments.peg_wall.validate \
  workspace/peg_wall_validation/peg8_g2_new --stage minimize \
  --namd "$HOME/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/namd3"
.venv/bin/python -m experiments.peg_wall.validate \
  workspace/peg_wall_validation/peg8_g2_new --stage resident \
  --namd "$HOME/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/namd3"
```

Construction never launches NAMD. Execution goes through `scripts/test_guard.sh`,
requires a user-opened test session, rejects a busy simulation host, preserves
existing outputs, checks input hashes and bounds each engine stage to 180 seconds.
The resident stage requires successful minimization with the same binary and
unchanged minimized coordinates. Binary hash, command, exit status and elapsed
time are recorded. Native minimization uses GPU offload; the subsequent MD stage
explicitly requires `GPUresident on` and the validator checks the engine banner.

The default is 1,000 minimization iterations followed by **1,000 steps at 1 fs**,
294 K, Langevin NVT. This is a short relaxation/compatibility probe, not a production
protocol or a change to NADOC's production timestep/HMR policy.

## Configuration contract for future UI wiring

| Parameter | First-case value / meaning |
| --- | --- |
| `repeat_units` | 8; EO units, distinct from the 9 topology residues |
| End chemistry / force field | Explicit methyl caps; pinned additive ether/TIP3P assets |
| `grid` | 2 → four chains on a square lattice; record achieved graft density |
| `box_nm` | `[4.8, 4.8, 4.8]`; fixed periodic cell |
| Wall geometry | Z-normal planes, `inset_nm=0.2`; Cartesian axes supported by force module |
| `wall_k` | 10 kcal/mol/Å²; repulsion acts on all atoms |
| `graft_k` | 5 kcal/mol/Å²; native harmonic point tether |
| `graft_offset_nm` | 0.2; reference height above the repulsion onset |
| Graft atom | `C1` of residue 1 in each PEG segment; explicit final PSF index mapping |
| `temperature_K`, `seed` | 294 K, 17 |
| Qualification length | 1,000 steps at 1 fs; builder accepts 200–100,000 in multiples of 100 |
| Engine | Explicit binary, GPU device and CPU threads; fail rather than silently disable resident mode |

The ordinary surface draft/UI/API remains unchanged. It must not advertise these
isolated packages as ready-to-launch managed jobs.

## Validation and remaining barriers

Fast tests execute the generated Tcl against a stubbed NAMD callback interface,
compare its energy/force with the analytic oracle, differentiate energy numerically,
check all Cartesian normals and periodic images, and test protocol invariants,
package integrity, trajectory metrics and the execution guard.

The native validator requires finite logged energy records, all requested steps,
the GPU-resident banner, nonzero PEG motion, sampled wall penetration below 1 Å,
and sampled anchor displacement below 1.5 Å. It independently compares NAMD's
`MISC` and `BOUNDARY` energies with the analytic wall and graft energies from DCD
coordinates. Coordinates are sampled every 100 steps, so penetration thresholds
do not establish a bound on every intervening timestep.

Remaining barriers before frontend launch wiring:

1. Native compatibility is established for this package only. Extend the qualification
   matrix before exposing general surface creation and launch controls.
2. Measure solvent density and relax the initial packing. Whole-water trimming and
   excluded PEG volume mean counts divided by total box volume are not bulk density.
3. Check longer chains, denser brushes, thermalization and wall/tether stiffness
   sensitivity; initial straight chains and a 1 ps run do not establish equilibrium.
4. Qualify production HMR/4 fs stages separately; this module does not promote them.
5. Measure Tcl-wall overhead before scaling; a native GPU wall implementation may
   be needed for useful throughput even though resident integration is compatible.
6. Qualify DNA/ions, different end groups, surface chemistry and ensemble changes
   explicitly when those enter scope. They are absent from this mechanical probe.

## Native results and persistent review (2026-09-12)

The user opened the required test session. Both native stages exited zero:

| Retained job | Stage | Result |
| --- | --- | --- |
| `94d4b96fd8d7` | PEG wall minimize | 1,000 iterations completed; 10 saved frames |
| `654049290521` | PEG wall resident | 1,000 steps / 1 ps completed; 10 saved frames; all 10 checks passed |

Open **NAMD_PEG8_wall_review.nadoc** from the workspace Library, then use its
**PEG qualification job** selector or **Simulations → NAMD** job list. The saved
file contains the real 9,092-atom coordinates, PSF bonds, wall planes and graft
indices. It has no fabricated DNA strands. The review provides trajectory playback,
frame scrubbing, optional water oxygens and a Fit surface control. Successful jobs
retain copies of native inputs, logs, trajectories, execution receipts and validation
results under `workspace/md_jobs/`. Failed stages are not imported as completed jobs.
The qualification cannot be promoted through the normal production checkpoint path.

Resident sampled metrics: maximum all-atom wall penetration **0.2583 Å** (PEG:
**0 Å**); maximum graft displacement **0.9305 Å**; graft RMS displacement
**0.4838 Å**; PEG motion RMS **1.3703 Å**. Wall/graft analytic energies agree with
native logged energies to **0.0000502 kcal/mol** over all 10 saved frames.
This confirms a short physics-approximate mechanical coating run, not equilibrium,
production timestep suitability or wall throughput. Minimization frame numbers
represent iterations, not physical time.

The prepared case has **9,092 atoms**, not 90,920. Original package evidence remains
in `workspace/peg_wall_validation/peg8_g2_v1/validation.json` and stage receipts.

Verification results for persistent review work:

- Four new backend review tests passed; the 21 wall/qualification tests passed earlier.
- `just test-frontend`: **402 files, 6,266 tests passed**.
- `just smoke`: **23 passed**, including app boot, real-design rendering and teardown.
- `just test-smart` selected **FULL** in the open session: **8,658 passed, 143 skipped,
  1 xfailed, 15 failed**. Twelve failures require unavailable BigO/smallO workspace
  fixtures. Two real oxDNA PEG-live worker tests reject a bonded-neighbor distance
  of 1.026613. One SNUPI RPY equilibrium RMSF test narrowly exceeds its 15% tolerance
  (0.404151 versus expected 0.351144). These failures remain separate barriers;
  this run does not establish that all are pre-existing. No full-suite deferral remains.
- Playwright exercised Library opening, both completed entries in the visible unified
  NAMD jobs list, real trajectory retrieval, scrubbing, playback and water visibility:
  **1 passed**. The rendered PEG, water and wall planes were visually inspected.
  The running development backend also serves the resident review endpoint (HTTP 200).
- Browser startup also exposed an unrelated concurrent mrDNA status-save race
  (`job.json.<pid>.tmp` missing during replacement). It did not prevent PEG review;
  catalogue it for job persistence follow-up.
- New backend files pass Ruff; `git diff --check` passes. Review integration adds only
  an import and initializer to `main.js` (**+2 lines** this turn; +4 including the
  prior direct-surface UI work).

Managed continuation: see [PEG fast relaxation](namd_peg_fast_relax.md) for the NVT/HMR protocol, PEG-aware skip criteria, MC initialization assessment and retained validation jobs.
