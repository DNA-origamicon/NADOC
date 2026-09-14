# Fixed-gold streptavidin/DNA CPU–GPU pilot

Measured locally on 2026-09-13. **Pilot completed; full validation has not been
launched.** The application's CPU-only guard remains enabled. No remote resources
were used and no engine code was changed.

## Model and hardware

One 10 nm gold sphere (external fixed repulsion), one 1STP tetramer (484 Cα
DNANM beads), and one 16-base biotinylated ssDNA strand: 500 simulated beads.
Both backends used the same topology, coordinates, ANM parameters, three protein
anchors and symmetric protein–DNA tether. Gold itself is not a bead.

- CPU: Ryzen 5 3600, 6 cores / 12 threads; sequential runs, OMP_NUM_THREADS=1.
- GPU: RTX 2080 SUPER, 8 GiB; mixed precision, edge-based CUDA interactions.
- Environment: WSL, 23 GiB RAM, NVIDIA driver 596.49, CUDA runtime 12.
- Engine: NADOC's installed oxDNA, source HEAD
  `8028cf33b3cba12992b771156085fa54879f50cd`, with local modifications.
  Executable and shared-library hashes are retained in the raw report.
- MD: dt=0.0001, 296 K, salt=0.5 M, Bussi thermostat, seed=123,
  fix_diffusion=false. Equal seeds do not imply identical CPU/GPU stochastic paths.

## Timings

| Steps per backend | CPU wall time | GPU wall time | Wall speedup |
|---|---:|---:|---:|
| 1,000 | 3.14 s | 1.07 s | 2.9× |
| 10,000 | 28.16 s | 2.95 s | 9.6× |

For the 10,000-step run, engine-reported integration/output time was 28.0449 s
CPU versus 2.45643 s GPU: approximately 357 versus 4,071 steps/s. Output cadence
was 1,000 steps for energy and 10,000 for configuration. GPU startup accounts for
about 0.49 s. The CUDA engine reported 3.09 MB allocated; this excludes context,
display and other applications, and is not a peak process-VRAM measurement.

The timing runs used the current generated equilibration backbone caps (50/100).
Separate 1,000-step runs **without either backbone cap**, both starting from the
same CPU-relaxed configuration, also succeeded: CPU 3.22 s, GPU 1.06 s.

## Checks completed

- Both backends accepted the complete DNANM topology and every external force.
- All timing/uncapped outputs contained 500 finite particle records.
- After 10,000 steps, minimum bead-center radius was 5.68766 nm CPU and
  5.68770 nm GPU, outside the nominal 5 nm gold radius. The unstressed structure
  does not significantly exercise the core's repulsive shell.
- Tether rest length was 2.03414 nm. Final distances were 2.12640 nm CPU and
  2.16005 nm GPU. These are individual stochastic samples, not an equivalence
  test of their distributions.
- An additional deliberately displaced configuration activated gold repulsion,
  protein anchors, ANM and the DNA tether. It put the nearest bead center at
  5.09087 nm. A single NVE step at dt=1e-6, from identical small velocities and
  angular momenta (1e-8), gave a relative L2 difference of **7.074e-5 (0.00707%)**
  in CPU/GPU linear velocity increments across all beads. Maximum absolute
  difference was 7.343e-10 in engine velocity units. This is an indirect
  force/integrator check, not exhaustive raw-force parity or a calibrated
  acceptance threshold.
- Attempting the standard `force_and_torque` observable gave zero-valued CUDA
  particle-force records despite nonzero dynamics. They cannot be used as a
  raw GPU-force comparison. Full validation should use verified device-force
  export or timestep-converged deterministic kick tests. A zero-velocity NVE
  attempt was rejected by both backends; identical tiny nonzero initial
  velocities/angular momenta were used instead.

## Proposed validation budgets — not yet run

These are **compute-time projections for this 500-bead scale**, not promises of
completion or projections for dense coatings/whole origami. Geometry variants
would cover 5 nm adsorption, 10 nm adsorption and 10 nm biotin-tethered gold, each
with one tetramer and one DNA; three independent seeds per variant.

| Scope | Work per backend | Projected sequential CPU + GPU compute | Reserve locally |
|---|---|---:|---:|
| Initial engineering validation | 9 cases × (100k MD relaxation + 100k uncapped MD) | ~92 minutes | 2–3 hours |
| Extended stability comparison | 9 cases × (100k relaxation + 1M uncapped MD) | ~8.4 hours | 9–12 hours |

The reserve allows short MC initialization, force probes, extra output and
hardware variability. It excludes engineering/debugging time if a discrepancy
requires instrumenting or rebuilding the engine. Stage transitions, translated
particle reference frames, force activation, timestep sensitivity, protein spring
extensions, pocket-tether distance distributions and core penetration must all be
checked. Longer trajectories should be compared statistically, not by demanding
matching coordinates. These runs assess numerical/model implementation; they do
not validate adsorption energies or biotin-binding chemistry experimentally.

**Recommendation:** run the initial 2–3-hour suite locally. This small system fits
comfortably; the CPU reference runs dominate the time. Remote hardware becomes
more useful for many parallel CPU reference cases, larger systems, or avoiding
an overnight local run. No remote speed or cost has been measured here.

## Raw artifacts

Inputs, configurations, trajectories, logs, hashes, report JSON and reproduction
scripts are retained under:
`workspace/validation/oxdna_cpu_gpu_pilot_20260913/`.
This is a local ignored result directory, separate from application jobs.
The helper scripts can be run from the repository root with `PYTHONPATH=.` and
`.venv/bin/python`; run `run.py`, `followup.py`, `probe.py`, then `uncapped.py`.
