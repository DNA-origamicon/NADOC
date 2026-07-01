# exp31 — Skip count vs twist & curvature sweep (3×6×400 SQ)

**Date launched:** 2026-06-27
**System:** freshly generated 3×6×400 seamless square-lattice bundle (18 helices, 400 bp),
routed + autostapled + sequenced, oxDNA2 (CUDA).

## Question

The autorefine loop starts from the published analytical skip spacing (period 48) and tunes a
single uniform period to cancel global twist, but struggles to "find a route" beyond the
analytical start. We do not know:

1. the **shape of the total-skips → total-twist response curve** around the analytical baseline;
2. whether a result that cancels twist also stays **straight** (a zero-twist but highly-curved
   bundle is just as useless), so we add an **integrated-curvature** guard metric; and
3. whether **where** the added/removed skips go (placement strategy) matters as much as **how
   many** — i.e. is there a strategy that reaches lower twist with less curvature?

## Design

Sweep the total skip count by ±18 (exactly one deletion per helix) per step, **±4 steps** from
the analytical baseline (9 skip-count points). At each point run a full relaxation + **8M-step**
production (no early-reject; abort only on a falling-apart structure), and measure, against the
design's OWN analytic geometry (differentially, sim − analytic):

- **net twist** (`measure_bundle_twist`, deg) — the signal skips control;
- **integrated curvature** (`measure_bundle_curvature`, deg/nm) — the new bending guard, which
  unlike end-to-end bend captures S-bends and local kinks.

Three placement strategies for the ±1-skip-per-helix delta (all share the Δ=0 baseline sim and
sit on the same total-skip x-grid):

- **A · uniform restagger** — re-place `base_count + Δ` deletions evenly + staggered (every skip
  moves register each step; the textbook approach).
- **B · incremental largest-gap** — keep the baseline marks; add at each helix's widest gap /
  remove the one bordering the narrowest. Minimal register disturbance.
- **C · deviation-guided** — adaptive feedback: each step places/removes each helix's deletion at
  the prior simulation's local deviation hotspot.

25 simulations total (1 shared baseline + 8 points × 3 strategies).

## Hypotheses / predictions

Grounded in prior square-lattice findings (`project_skip_twist_selfconsistency.md`,
`project_regional_autorefine.md`): square lattice is underwound enough that the twist-zero sits
near period ~24 — roughly **2× the analytical-48 density**, i.e. about +8 steps of +18 skips
beyond baseline. So:

1. **Within the ±4 window, net twist descends monotonically as skips are added** (toward, but not
   necessarily crossing, zero). At the analytical baseline the differential twist is expected to
   be large and positive (prior live monitoring read +69–80° at period ~50), NOT near zero — so
   the analytical spacing is **not** at the twist minimum, which is the gap the experiment maps.
2. **Curvature stays low and near strategy-independent** across the sweep — skips are placed to
   cancel twist, not to bend; a well-staggered deletion pattern should not induce net curvature.
   (Falsifiable: if a strategy trades twist for curvature, the guard will show it.)
3. **Placement strategy shifts the twist curve materially** — prior work measured ~±30° net-twist
   swing from the deletion register alone at equal count. We therefore expect the three strategies
   to give visibly different twist at the same total-skip count, with **uniform restagger (A) the
   smoothest/flattest** and most predictable, and **deviation-guided (C) the noisiest** (it chases
   a single stochastic deviation field, which prior regional experiments showed is dominated by
   register sensitivity rather than real local signal).
4. **No clear winner among B/C over A is the likely outcome** — if A is both lowest-curvature and
   most monotonic, the practical recommendation is that the uniform restagger remains near-optimal
   and the search difficulty is about COUNT (needing ~2× the analytical density), not placement.

## Disproven-expectation policy

Any prediction the data contradicts (e.g. C reaching lower twist than A, or curvature tracking a
strategy, or twist NOT being monotonic in skip count) is recorded in `conclusion.md` and promoted
to a `memory/LESSONS.md` entry under the relevant failure-mode category.

## Outputs

- `results/skip_twist_curvature.png` — live two-panel plot (twist + curvature vs total skips, one
  series per strategy), regenerated after each sim.
- `results/results.json` / `results.csv` — per-simulation records.
- `MONITOR_LOG.md` — driver + watchdog event log.
- `conclusion.md` — written after the series completes.
