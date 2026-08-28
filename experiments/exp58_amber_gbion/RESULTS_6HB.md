# exp58 6HB scale result — stable short gate, production-performance failure

Final-audit note: this result is definitive for the nominal throughput of the exact
exp58 input, but it is **not** a measurement of effective curved-origami
equilibration. The run used a higher-friction and partly noncanonical parameter
variant rather than the published accelerated-sampling protocol. See
[`FINAL_ASSESSMENT.md`](FINAL_ASSESSMENT.md) before interpreting or reusing it.

Two bounded RTX 4090 runs tested the archived 656-nt `6hb_2xT` against its
GPU-resident NAMD reference. The first exposed an invalid raw CAD starting geometry;
the second seeded Amber from the relaxed NAMD production-start coordinates and produced
a numerically and structurally stable 0.1 ns trajectory. The relaxed GBION system was
nevertheless about five times slower than explicit NAMD in physical ns/day, so this
implementation is not a production acceleration path at 6HB scale.

## NAMD reference and comparison limits

- Archive: `/media/jojo/Archive/NADOC_archive/cb616816195f`
- Design: 9 strands, 656 nt, 252 intended base pairs, and 152 designed-unpaired
  crossover/terminal nucleotides
- Explicit system: 182,801 atoms; CHARMM36/CUFIX, TIP3P, Mg(H2O)6 counterions
- Engine/GPU: GPU-resident NAMD Git-2025-12-04 on an RTX 3080 Ti
- Actual trajectory: 7.0 ns (700 frames), stopped by the user despite the 10 ns name
- Measured throughput: 90.9034 ns/day with HMR and a 4 fs timestep
- NAMD C1' paired fraction declined from 0.960 to 0.859 over the archived run

The Amber comparison uses OL15, GBneck2/GBION-v3, explicit 150 mM NaCl, a 2 fs
timestep, and an RTX 4090. It is therefore a stability-envelope and throughput test,
not a coordinate-identical force-field comparison.

## Attempt 1: raw NADOC geometry

The raw Amber PDB and the raw NAMD PDB are geometrically identical. Each contains 105
heavy-atom pairs below 0.8 A (minimum 0.352 A), and the NAMD PSF identifies 136 bonds
outside 0.8-2.0 A. The successful NAMD run did not start from those coordinates:
`equilibrated.coor`, the reseed coordinate, and the production restart all have zero
heavy-atom pairs below 0.8 A and every one of the 184,082 full-system PSF bonds lies in
the standard range.

The first Amber protocol mistakenly applied 5 kcal/mol/A2 positional restraints to the
bad raw DNA during minimization, heating, and equilibration. LEaP reported 1,263
warnings and 1,091 close contacts, down to 0.096 A after hydrogen construction. The
one-step CPU/GPU energies were already inconsistent (approximately 1.34e18 versus
-7.45e9 kcal/mol). Production overflowed temperature and energy fields and generated
coordinates of order 1e10 A. It was stopped after five frames/10 ps.

This is a preparation-protocol failure, not evidence that relaxed OL15 6HB DNA must
fail. It also uncovered a build issue: Amber26's CUDA 12.8 branch hardcodes eight GPU
architectures. Two coarse-grid translation units exceeded 251 GiB when four `nvcc`
jobs overlapped. `amber26_cuda_sm89.patch` narrows the two allowed Ada RunPod GPUs to
SM8.9 before configuration; the clean four-way build then completes in minutes.

Attempt-1 archive:
`/media/jojo/Archive/nadoc_amber_exp58/origami_6hb_runpod/`.
`partial_analysis.json` SHA-256:
`467e4a9456f7fe4f87ffa924b7147591f9422c175cef915fe06eaf10b63b6bee`.

## Attempt 2: relaxed NAMD-matched seed

All 13,380 Amber heavy atoms were mapped from NAMD's reseed coordinate, including the
CHARMM `C5M` to Amber `C7` thymine alias. The mapped seed has no heavy-atom overlap
below 0.8 A. LEaP produced:

- 22,444 atoms and 22,403 covalent bonds
- solute charge -647 e
- 1,147 Na+ and 500 Cl- in a 126 A sphere at nominal 0.150 M
- 647 phosphorus atoms and all 647 expected consecutive-strand O3'-P links
- no inter-strand covalent bonds
- initial bond range 0.960-1.680 A, with none outside 0.8-2.0 A
- CPU/GPU parity energies -61,753 and -61,752 kcal/mol (relative delta 1.62e-5)

The ion wall used 32 phosphorus representatives instead of repeating all 647 atoms in
each of 1,647 restraints. That improved the clean timing from 7.27 ns/day in the
corrupted/all-P attempt to 18.28 wall-clock ns/day (Amber reported 18.99). It remains
only 0.201x the NAMD reference: about five times slower on a newer GPU. NAMD takes one
4 fs step in about 3.8 ms; this GBION system takes about 9 ms per 2 fs step, combining a
roughly 2.4x slower step with twice as many steps per physical nanosecond.

## Short structural gate

Over 50 frames/0.1 ns:

- mean intended C1' paired fraction (12 A): 0.9994; final: 1.0000
- mean absolute Watson-Crick fraction: 0.9752; final: 0.9802
- final aligned C1' RMSD: 0.4972 nm (gate <= 0.5 nm)
- axial p95-p05 length: 12.638 to 12.492 nm (-1.15%)
- radial RMS: 2.645 to 2.984 nm (+12.81%; gate <= 15%)
- radial p90: 3.021 to 3.449 nm (+14.17%)
- final bond range: 0.0960-0.1710 nm; all 22,403 bonds in 0.08-0.20 nm
- energies finite throughout

The preregistered overall gate remains failed. The original analyzer measured ions
from the all-647-P center even though the wall used the 32-P center. Corrected radii
give a maximum of 126.525 A and a final value of 126.145 A. This is a bounded thermal
excursion but exceeds the registered 126.5 A threshold by 0.025 A; the threshold was
not changed after observing it. `ion_wall_reanalysis.json` records the correction.

The 32-P selector's initial center error was 3.66 A. The worker now performs a
deterministic within-bin swap optimization, which reduces that seed error to 0.055 A;
this change was made after the measured run and is not retroactively applied to it.

Attempt-2 archive:
`/media/jojo/Archive/nadoc_amber_exp58/origami_6hb_relaxed_runpod/`.
`result.json` SHA-256:
`bdd921892ec07520fc0a12dbf9a6e1447ea674f7e73d84db1169a08cef346305`.

## Cost and decision

- raw-start attempt: $0.79810
- relaxed-start attempt: $0.24605
- earlier duplex gate: $0.69644
- cumulative exp58 spend: $1.74059 of the $5 hard cap
- both experiment pods were confirmed absent and their ledger rows closed
- the local NAMD production job was not modified or tested against

The relaxed 6HB result shows that OL15/GBION can run stably for a short gate, but this
specific method does not meet the nominal-throughput objective. A 10 ns 6HB sample
would take about 13.1 hours on the measured 4090 before replicas, versus about 2.64
hours for the archived NAMD rate. HMR/4 fs might recover roughly a factor of two, but
would still trail NAMD by about 2.5x and would require a separate stability validation.

This does not by itself establish wall time to conformational equilibrium: implicit
solvent can accelerate large motions per nominal nanosecond. exp58 used
`gamma_ln=1.0 ps^-1`, did not measure curvature convergence or effective sample size,
and sampled only one already-relaxed 6HB for 0.1 ns. Longer versions of this protocol
are therefore not justified. Any reconsideration must be a new effective-sampling
study under the conditions in `FINAL_ASSESSMENT.md`, not an extension of this run.
