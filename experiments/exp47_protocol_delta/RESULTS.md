# exp47 results — NADOC → Aksimentiev, one knob at a time (2 ns each, 4 fs throughout)

Twelve 2 ns arms, all from the same structure: the released (k=0 / MGHH-only) endpoint of
the 2hb_1xT ENM ladder (`c8bcf4c1406f`) in its **pre-collapse** cell
44.147 × 66.635 × 113.568 Å — the exact state the original 2 ns production started from.
`timestep` is 4 fs + HMR in every arm by instruction.

Starting cell = 334.1 nm³. Contents = 6093 waters + DNA + ions ≈ **211 nm³**, so the cell
is **37 % vacuum** (`water_shell_nm = 1.2` carve). Predicted equilibrium volume
**61.8 %** of the start.

| arm | knob moved to the tutorial value | outcome | died at | final vol | ns/day | min DNA–image d |
|---|---|---|---|---|---|---|
| A0_baseline | — (control) | patch grid | 0.95 ns | 67.0 % | 353.6 | 5.05 Å |
| A1_piston | period/decay 200/100 → 1000/500 | patch grid | 0.98 ns | 66.4 % | 353.7 | 4.63 Å |
| A2_cutoff | 10/12/14 → 8/10/12 | patch grid | 1.01 ns | 71.6 % | **419.5** | 4.11 Å |
| A3_pmegrid | PMEGridSpacing 1.0 → 1.5 | patch grid | 0.93 ns | 66.7 % | 362.4 | 7.26 Å |
| A4_fullelect | fullElectFrequency 1 → 2 | patch grid | 1.00 ns | 66.5 % | 396.2 | 4.37 Å |
| A5_cycle | stepspercycle 10 → 12 | patch grid | 1.01 ns | 67.2 % | 371.4 | 5.71 Å |
| A6_grouppress | useGroupPressure yes → no | patch grid | **1.17 ns** | 66.9 % | 368.0 | 8.03 Å |
| A7_wrap | wrapAll/wrapWater on → off | patch grid | 1.00 ns | 66.6 % | 363.7 | 4.71 Å |
| A8_all | all of the above at once | patch grid | 1.07 ns | 71.7 % | **484.2** | 3.77 Å |
| **B1_nvt** | barostat OFF (NVT) | **completed** | — | **100.0 %** | 359.1 | 5.18 Å |
| B2_fixdna | NPT + `fixedAtoms` on the DNA (tutorial Note 4) | patch grid | **1.83 ns** | 66.8 % | 389.4 | 1.16 Å |
| **B3_margin30** | baseline + `margin 30` | **completed** | — | **61.7 %** | 320.3 | 9.51 Å |

`PATCH GRID` = `FATAL ERROR: Periodic cell has become too small for original patch grid!`

## 1. No configuration knob prevents the failure

Nine of nine conf-level arms died the same way inside a 0.93–1.17 ns window at 66–72 % of
the starting volume. The barostat period — the obvious suspect, and the tutorial's own
suggested mitigation — moves the crash by 7 500 steps. `useGroupPressure no` buys the most
(1.17 ns) and still dies.

The reason is arithmetic, not tuning: the crash sits at ~67 % of the starting volume and
the water's equilibrium volume is **61.8 %**, so the cell *must* cross the patch-grid limit
on the way to equilibrium. With 37 % vacuum the failure is guaranteed, not unlucky.

**This is not a new failure.** The original 2 ns production hit it too — `auto_resumes: 1`
in its job record and 32 copies of the fatal string in its log — and NADOC's runner
silently auto-resumed past it (a restart rebuilds the patch grid for the smaller cell).
That is how the 200 ns run inherited a collapsed 37.6 Å box.

## 2. `margin 30` survives it, and lands exactly where predicted

B3 completed 2 ns and finished at **61.7 %** of the starting volume against **61.8 %**
predicted from the water count. That closes the mechanism: the shrink is the barostat
correctly expelling the vacuum, and the crash is only NAMD's patch decomposition being
sized for the original cell. Cost: 9 % throughput (320 vs 354 ns/day).

## 3. But surviving ≠ succeeding

Every arm — **including both that completed** — ends with the DNA within one hydration
shell of its own periodic image (3.8–9.5 Å; clean would be > 24 Å = 2 × cutoff):

- **B3 succeeded *into* the bad state.** It reached the equilibrium volume, and that volume
  is simply too small for this solute.
- **B1 (NVT) held the cell at 100 %** and still ends at 5.18 Å, because the box was already
  too small before any pressure was applied. Its scaffold fragment's x-extent reaches
  72 Å in a 44 Å cell.
- **B2 (fixed DNA — the tutorial's preferred remedy) got furthest of the NPT arms**
  (1.83 ns, nearly 2× the baseline) but still hit the patch grid, and ends in hard contact
  with its image (1.16 Å).

All arms keep **100 % of designed base pairs intact** (median C1′–C1′ 10.7 Å), so the large
spans are real geometry — the intact bundle sprawling, by hinge-opening at its single
Holliday junction or whole-body rotation (not distinguished here) — not melting and not an
unwrapping artifact.

## 4. Throughput, as a side effect

| change | ns/day | vs baseline |
|---|---|---|
| baseline (cutoff 12, PME 1.0, fullElect 1) | 353.6 | — |
| cutoff 8/10/12 | 419.5 | **+19 %** |
| fullElectFrequency 2 | 396.2 | +12 % |
| PMEGridSpacing 1.5 | 362.4 | +2 % |
| **all tutorial electrostatics together** | **484.2** | **+37 %** |
| margin 30 | 320.3 | −9 % |

NADOC currently declines all of these in favour of the more conservative Markvoort/ACS Nano
values. The price of that choice is measured here: **~37 %**.

One caution: A2 and A8 crashed at a *larger* cell volume (71.6 / 71.7 %) than every other
arm. A smaller cutoff makes a finer initial patch grid, so less shrinkage is tolerated —
adopting the tutorial's cutoff without fixing the box makes this failure *more* frequent.

## What this implies

1. **`langevinPiston` must be off for a carved cell in production**, not just in the ladder
   — the guard at `md_protocols.py:2105` never reaches `build_production_conf`.
2. **`margin` deserves to be set** on any NPT run whose cell may move; it converts a hard
   crash into a completed run. It is a NAMD-side mitigation, *not* a tutorial setting, and
   it does not make the resulting cell correct.
3. **Neither fixes the real defect**, which is box sizing. Every remedy here still ends with
   the solute touching its image. That is the padding rule, not the ensemble.
4. **The auto-resume should not silently absorb `Periodic cell has become too small`.** It
   converted a hard, diagnostic failure into a 200 ns run in a bad cell.

## Deferred

`padding_nm 1.2 → 2.0` and `water_shell_nm 1.2 → 0` need a re-solvation, not a conf change,
so they are not in this series. They are the two that address §3.
