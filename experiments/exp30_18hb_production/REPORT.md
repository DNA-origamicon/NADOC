# exp30 — 18hb production MD run: FINAL REPORT

**Outcome: FULL PRODUCTION SUCCESS.** The 224-strand 18-helix-bundle origami relaxed
through the complete Aksimentiev ENM slow-release ladder to **true k=0 (no restraint)**
and passed every health gate — no melt. Job `e29d1e5d5ace`.

## Result

- **12/12 health gates passed.** C1' base-pairing held **99–100% across the entire ladder
  including true k=0**; WC ref-relative stepped down gently and stayed above every
  threshold (incl. the relaxed 75% at k=0).
- Final production state: `output/18hb_04_300K_NPT_MGHH_only_p100.{coor,vel,xsc}` (the
  relaxed, unrestrained 18hb at 300 K in explicit MGH/CUFIX + 50 mM NaCl).
- This confirms the exp29 prediction: a large salted bundle (no inserted-base strain)
  survives true k=0 where 2hb/6hb melted.

## Health curve (C1' / WC ref-relative, per gate)

| stage | p10 | p50 | p100 |
|---|---|---|---|
| k=0.5  | 100.0 / 94.8 | 100.0 / 94.8 | 100.0 / 95.2 |
| k=0.1  | 99.8 / 88.9  | 99.8 / 88.3  | 99.7 / 88.0  |
| k=0.01 | 99.7 / 83.2  | 99.7 / 82.1  | 99.6 / 81.4  |
| **k=0**| **99.4 / 77.9** | **98.9 / 77.9** | **99.0 / 78.0** |

C1' moved only 100→99.0 over the whole release; WC 95→78. The structural change is at the
discrete k-steps (WC drops), not within stages — see ANALYSIS.md.

## Run facts

- Solvated system **2,979,096 atoms** (290k DNA heavy → 450k all-H + water/ions).
- Buffer 50 mM NaCl + 12.5 mM Mg-hexahydrate/CUFIX; min 24 000 steps; ladder
  k=0.5→0.1→0.01→k=0, 12 segments, 9.6M dynamics steps (19.2 ns).
- Wall-clock **2026-06-14 12:58 → 2026-06-20 14:44 ≈ 6.1 days**; ~3.0–3.6 ns/day
  (GPU-resident, RTX 3080 Ti). Trajectory 39 GB DCD.
- **0 NAMD crashes / 0 watchdog relaunches** across the run.

## Engineering fixes that made this run possible

1. **psfgen topology at scale** (`namd_topology.py`): hybrid-36 atom serials (>99999
   overflow) + unique 4-char segids (224 strands no longer collide). Without these the
   build FATALed (`patch DEO5 … no residue 1`).
2. **ENM residue grouping** (`md_protocols._parse_base_ring_residues`): contiguity-based,
   so ~half of 14172 residues no longer merge under cycled chain keys → correct restraints
   + correct MDAnalysis health pairing.
3. **Resume conf** (`namd_runner._write_resume_conf`): `run <remaining>` instead of the
   unsupported `run upto` (NAMD 3.0.2 Tcl fatals "first arg not norepeat").
4. **GPU-resident** (`CUDASOAintegrate on`): 1.38→2.97 ns/day (2.2×), physics identical;
   elongated-box PME is the ceiling, not the integrator.

## Incidents (handled, no data loss)

- A two-computer `git clean` during a rebase wiped the untracked tooling + this dir
  mid-run; the run survived (gitignored `workspace/`); tooling was recreated. **Action:
  commit `scripts/*_18hb.*` + `experiments/exp30…` so a future clean can't wipe them.**

## Carry-forward (next runs)

1. **Compress the restrained ladder ~5–10×** and reallocate to a long k=0 production —
   restrained stages plateau by ~10% (ANALYSIS.md Q1).
2. **ML surrogate:** log per-nucleotide CG state per frame + run an ensemble weighted to
   the k→0 transition (ANALYSIS.md Q2).
3. Make `GPUresident` a conf-generator default; optional offline PME/PE throughput tune.
