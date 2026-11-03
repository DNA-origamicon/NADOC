# Phase 0 result — the weld does not form (161.8 ns unbiased, k=0) — supporting detail

[Topic head](../../project_cpd_umbrella_sampling.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Phase 0 result — the weld does not form (161.8 ns unbiased, k=0)

Job `ccdcdca7675a`, `2hb_1xT_01_production_500ns_k0` (+ `.cont1`), 62,677 atoms, 4 fs,
100 ps/frame, **1619 frames / 161.8 ns**, every frame measured.

| quantity | value |
|---|---|
| d_mid | mean **11.39 Å**, sd 1.38, **min 7.44 Å**, max 17.97 |
| η | mean +31.5°, sd **95.6°**, full ±180 range |
| frames d < 8 Å | 10 (0.62%) |
| frames d < 6 Å | **0** |
| **reactive corner** (d<4.5 Å ∧ \|η−η₀\|<45°) | **0 / 1619 = 0.000%** |
| stationarity, d_mid 1st/2nd half | 11.33 / 11.46 Å — equilibrated, no drift toward contact |

**Interpretation.**
1. The two extra Ts sit ~11.4 Å apart and never approach within 7.4 Å. The weld is not
   spontaneously accessible on this timescale.
2. **η is essentially free** (sd 95.6°, samples all ±180°). The torsional coordinate costs
   little at this separation — **the barrier lives in d, not η.** A 1D PMF in d with η as a
   passive observer may be nearly sufficient; η should still be a CV at close range.
3. This is the opposite of the AutoNAMD reference system, where ⟨k⟩ converged on unbiased MD.
   Here umbrella sampling is **required**, not a refinement.

**The as-built seed η (−178.5°) is meaningless** — the insert spin DOF is a free parameter
the joint solve is indifferent to ([[project_crossover_catenation]]). Only MD-relaxed η counts.

## 1xT vs 2xT — one T cannot reach, two can (suggestive, not yet conclusive)

Same measurement, `2hb_2xT` job `bfd050d2ce4c`. 2xT has 2 inserts per crossover → 4 pair
combinations.

| design / pair | frames | d mean | d min | η sd | reactive |
|---|---|---|---|---|---|
| **1xT** k0~k0 | 1619 / **161.8 ns** | 11.39 Å | 7.44 | 95.6° | **0.000%** |
| **2xT** k0~k0 | 115 / 11.4 ns | **6.38 Å** | **3.65** | **20.8°** | **6.96%** |
| 2xT k1~k1 | ″ | 6.11 Å | 3.63 | 128.4° | 0.000% |
| 2xT k0~k1 | ″ | 8.69 Å | 6.24 | 102.0° | 0.000% |
| 2xT k1~k0 | ″ | 9.60 Å | 7.15 | 155.7° | 0.000% |

**Reading.** The 2xT k0~k0 pair reaches reactive geometry ~7% of frames within 11.4 ns; 1xT
never does in 161.8 ns. Its η sd of 20.8° (vs 95.6° for 1xT) says that when the tips are in
contact they are *ordered* — π-stacked, near the [2+2] geometry — rather than diffusing.

**Caveat, important.** The 2xT run is only **11.4 ns** and was stopped early, and its seed
already started at d = 4.86 Å where 1xT's started at 11.18 Å. Part of the difference may be
seed memory rather than equilibrium. The 1xT half of the comparison IS solid (161.8 ns,
stationary). **To make this conclusive, run 2hb_2xT unbiased to ≥100 ns and re-measure.**
That is the cheapest high-value experiment available.

Only ONE of the four 2xT combinations is reactive — so "2xT works" is really "one specific
insert pairing works". Which k-index pairs with which is a design detail worth understanding.
