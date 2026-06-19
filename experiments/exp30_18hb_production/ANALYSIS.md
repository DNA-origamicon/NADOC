# exp30 — stage-usefulness & ML-surrogate feasibility (2026-06-18, mid-run)

Data: NAMD energy logs (ENERGY every 9600 steps) + C1'/WC health gates + DCD
C1'-atom Rg/axial-extent, segments k0.5/k0.1/k0.01 (k=0 not yet run).

## Q1 — Does usefulness plateau well before each stage completes? YES, strongly.

**Fast modes (thermo + base-pairing).** Settle% = fraction of segment after which the
observable stays within tol of its final value; Δ = first-10% → last-10% change.

| segment      | nsteps  | settle%(POT) | settle%(VOL) | ΔVOL   | ΔPOT   |
|--------------|---------|--------------|--------------|--------|--------|
| k0.5 p10*    | 86 400  | 22%          | 33%          | −7.48% | +13.6% |
| k0.5 p50     | 960 000 | 0%           | 16%          | +0.20% | −0.02% |
| k0.5 p100    | 1.2M    | 0%           | 0%           | +0.08% | ~0     |
| k0.1 p10     | 240 000 | 0%           | 4%           | +0.11% | −0.05% |
| k0.1 p50/100 | 0.96/1.2M | 0%         | 0%           | ~0     | ~0     |
| k0.01 p10    | 240 000 | 0%           | 4%           | +0.10% | ~0     |
| k0.01 p50    | 960 000 | 0%           | 0%           | −0.02% | ~0     |

\*first dynamics segment after minimization — the ONLY one doing macroscopic work
(box contracts 7.5% to physical density; settles by ~1/3). **Every later segment is at
its equilibrium energy & volume from step 0** (Δ < 0.2%).

**Base-pairing (health gates, p10/p50/p100 per stage):** C1' pinned 99.7–100% the whole
run. WC ref-relative steps ONLY at k-transitions and is flat within a stage:
k0.5 = 94.8/94.8/95.2 · k0.1 = 88.9/88.3/88.0 · k0.01 = 83.2/82.1/—. The structural
response to a new k is complete by the 10% checkpoint (≈0.5 ns of 4.8 ns).

**Slow modes (global C1' Rg & axial extent, per p100/p50 segment):**

| segment    | Rg(start→end) | ΔRg    | axial-ext Δ |
|------------|---------------|--------|-------------|
| k0.5 p100  | 380.5→380.3   | −0.04% | −0.09%      |
| k0.1 p100  | 381.2→381.1   | −0.03% | −0.20%      |
| k0.01 p50  | 381.8→382.4   | +0.17% | +0.49%      |

Across stages Rg creeps 380.5→381.2→382.4 (+0.5% total) — a small monotonic expansion
**at the k-steps**, not within holds. The faint within-segment drift that first appears
at k0.01 (+0.2–0.5%) is the leading edge of slow-mode motion as restraint vanishes.

**Conclusion.** Under restraint (k≥0.1) every measured observable — energy, volume,
base-pairing, gross shape — is at its plateau by the 10% sub-segment; ~90% of each
restrained stage's wall-clock is post-plateau. The useful change happens *at the
discrete k-transitions*, not during the 4.8 ns holds. The restrained ladder is ~5–10×
over-provisioned for equilibration; compute should be reallocated to the k=0
(unrestrained) stage, where the slow modes finally sample (and the melt risk lives).
Caveat: "plateau" is of the measured observables; a rigorous claim should add per-residue
RMSF convergence + a slow-mode PCA (local joints / ion atmosphere not captured here).
Note exp29's "protective-in-time" finding still holds — the holds aren't for equilibration
but to avoid a too-fast restraint removal; my data says they can be much shorter and still
serve that purpose, as long as the *approach* to k=0 stays gradual.

## Q2 — Enough data for an ML start→end map between stages? Not from one run; the workflow yes.

**What each transition gives:** start `.coor` (full atomistic), end `.coor`, the in-between
DCD (~100–125 frames), and the control (k_from→k_to, ENM ref geometry, T, salt).

- **n = 1 per k-transition** (3 here). A *generalizable* surrogate needs many independent
  (design, k, start)→end examples; this run is grossly insufficient alone.
- **The restrained transitions are near-identity** (start≈end; ΔRg<0.2%, WC flat) → low
  information. The high-value, high-variance target is **k0.01→k=0** (slow modes finally
  move; melt vs survive) — exactly where you have the least data (1, hardest) example.
- **The end point is a distribution, not a point.** The plateau finding is the key
  enabler: post-plateau frames ARE equilibrium samples, so each stage already yields the
  equilibrium ensemble (mean+covariance) for that (design,k) — good for fluctuation
  statistics, still one point in conditioning space.
- **Representation:** raw 3M-atom coords are too high-D and not SE(3)/permutation
  invariant. Use NADOC's native reduced space — per-nucleotide rigid frames (6-DOF) or
  helix-axis CG, conditioned on the strand+crossover graph (a GNN target). The DCD→CG
  reduction is what the existing layers already do.

**Verdict.** Insufficient from this single production run; **the workflow can generate
sufficient data cheaply** *because* of Q1: equilibration is ~0.5 ns not 4.8 ns, so a
library of thousands of (topology, k_from→k_to, start_CG, end_CG_ensemble) tuples across
many designs/seeds is ~10× cheaper than the production ladder. To make it ML-ready: (1)
log per-nucleotide CG state per frame (not just C1'/WC scalars); (2) snapshot start/end CG
per transition; (3) run an ensemble (seeds × designs) weighted toward the k→0 transition;
(4) train a GNN-over-topology predicting the equilibrated CG ensemble conditioned on k.
