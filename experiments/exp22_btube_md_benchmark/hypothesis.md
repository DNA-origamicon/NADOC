# Exp22 — B_tube MD Benchmark: GROMACS vs NAMD

## Hypothesis

GROMACS with GPU-offloaded PME will outperform NAMD3 GBIS for B_tube at
production scale, but NAMD's implicit solvent (GBIS) may offer faster wall-clock
per-ns at the cost of physical accuracy (no explicit water).

## Design under test

**B_tube.nadoc** — 24 helices × ~300 bp, HONEYCOMB lattice
- ~14,420 nucleotides, ~303 k DNA heavy atoms
- Tube geometry: 102 nm long × 12 nm cross-section
- Solvated (TIP3P): estimated ~888 k total atoms (DNA + water + ions)

## Benchmark panel

| ID  | Engine   | Solvent        | Protocol            | Threads/GPU    |
|-----|----------|----------------|---------------------|----------------|
| A1  | GROMACS  | vacuum PME     | nstlist=20, 2 fs    | 28 ntomp + GPU |
| A2  | GROMACS  | vacuum PME     | nstlist=40, 2 fs    | 28 ntomp + GPU |
| A3  | GROMACS  | vacuum PME     | nstlist=80, 2 fs    | 28 ntomp + GPU |
| B1  | NAMD3    | GBIS implicit  | cutoff 16 Å, 1 fs   | +p8            |
| B2  | NAMD3    | GBIS implicit  | cutoff 16 Å, 1 fs   | +p16           |
| B3  | NAMD3    | GBIS implicit  | cutoff 16 Å, 1 fs   | +p28           |

Plus extrapolated estimate for GROMACS solvated TIP3P (~888 k atoms).

## Reference baselines

| System                        | Atoms   | ns/day | Engine  |
|-------------------------------|---------|--------|---------|
| 10hb bundle (exp runs/10hb*)  | 239,555 | ~48    | GROMACS |
| Holliday jct (AutoNAMD bench) | 35,254  | ~150   | NAMD3   |

## Expected outcome

- GROMACS vacuum A2/A3 (nstlist=40-80): ~6-10 ns/day (PME on 303 k DNA atoms)
- NAMD GBIS B3 (+p28): ~8-15 ns/day (no water, but 1 fs timestep, CPU-only GBIS)
- GROMACS solvated ~888 k atoms: ~4-7 ns/day (PME N^(4/3) scaled from 10hb)

## Physics notes

- GROMACS vacuum PME: no dielectric screening — helices interact as charged
  rods. Fast for validation but not production-accurate for flexible dynamics.
- NAMD GBIS: implicit solvation, faster per-atom than explicit water but
  GB approximates rather than resolves the hydration shell.
- For production-quality 1 µs of B_tube: GROMACS solvated is recommended
  (explicit screening, NPT ensemble, compatible with OL15 force field).
- At ~5 ns/day for solvated, 1 µs ≈ 200 days → requires either GPU cluster
  or reduced design scope (single helix ring, ~5,000 nt subsystem).
