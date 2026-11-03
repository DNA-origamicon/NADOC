# ✅ SS-4 DONE (2026-07-13) — the tails reach the screen (⚠ live-app exercise still owed) — supporting detail

[Topic head](../../project_snupi_ssdna.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## ✅ SS-4 DONE (2026-07-13) — the tails reach the screen (⚠ live-app exercise still owed)

The simulated tail beads are now emitted in the display payload and in every trajectory frame, so
the overhangs wave in the player instead of standing frozen at their rendered pose. Everything below
is measured on VoltronCore; **the one thing not yet done is the in-app visual check** (the user is
driving it — load `workspace/VoltronCore.nadoc`, Simulate ▸ SNUPI ▸ Advanced ▸ **Langevin dynamics** +
**Free ssDNA tails**, then the **Trajectory** toggle). Flip this heading's caveat when it passes.

<a id="shipped-1"></a>

### Shipped

- **`fem_solver._tail_bead_entries` + `deformed_positions_with_axis(..., tail_positions=, tail_nodes=)`**
  — tail beads are emitted at their simulated positions, carried through the core-only Kabsch. Their
  slab frame is rebuilt geometrically (tangent along the chain, rendered normal orthogonalised against
  it) because the trajectory keeps translational DOF only.
- **`_dynamics_trajectory_payload`** passes each frame's `tail_frames[fi]`, so the tails move frame to
  frame; **`_predict_shape_dynamics(tails=, tail_max_nt=)`** and **`predict_shape(...)`** plumb it, and
  `predict_shape` **raises** if `tails=True` without `dynamics=True` (decision 1, never silently drop).
- **Job/API/UI**: `SnupiJob.tails`/`.tail_max_nt` (+ stage label `dynamics+tails`, ETA ×2.1),
  `CreateSnupiJobRequest.tails`/`.tail_max_nt` with three 400s (needs dynamics; snupi-only; with
  hydrodynamics needs `hydro_coarse_bp`), a **Free ssDNA tails** checkbox in the SNUPI Advanced card,
  and `solverLabel` naming it "+ ssDNA tails" (it is a NADOC extension and must read as one).
- **Advanced-card guards** (`advancedGuards()`, 2026-07-14): the dependent options are disabled AND
  unticked when their prerequisite is off, so a box can never sit ticked while its flag is dropped from
  the request (the original rough edge: ticking tails without dynamics looked armed, then quietly ran a
  static solve). Tails need dynamics + `material="snupi"`; hydrodynamics needs dynamics; the coarse-bead
  select needs both; and **"Exact" friction is not offerable with tails** (an ssDNA bead's smaller radius
  only exists in the blob model). Each mirrors a backend 400 — the UI just stops you reaching it.
- **10 new tests** (`test_snupi_ssdna.py` → 56; +1 in `test_snupi_job.py`), incl. the load-bearing pin:
  shove the tails 1000 nm away and the duplex core comes back **byte-identical** — they never enter
  the Kabsch.

### ⚠ The mean of a coil is not a coil

`positions` (the static/deform payload) reports the tails from the **last frame**, not the time-mean.
Averaging a freely-fluctuating chain over its conformations shrinks it toward its anchor, so a
mean-of-beads payload draws every overhang as a collapsed stub with sub-bond-length bonds. The duplex
core still reports its time-mean (it fluctuates about ONE equilibrium shape, so its mean IS that
shape); a tail has no such mean. Pinned by the emitted bond length (0.696 nm mean vs the 0.68 contour).

### Separate bug found and fixed: 47% of every frame was beads that are never drawn

`nucleotide_positions` emits a bead at **every bp of a helix, strand or no strand**, and a helix is
routinely declared far longer than the strands on it (VoltronCore has a 288-bp helix carrying 48 bp of
duplex). The renderer draws only nucleotides with a `strand_id` (`_geometry_for_helices` / helix_renderer's
`assignedGeometry`), so **12 921 of VoltronCore's 27 687 emitted beads could not be addressed at all** —
and being the beads furthest outside the meshed bp range, the winding extrapolated them wildly (4.5 nm
mean / 19 nm max motion across a trajectory vs 0.26 nm for a real duplex bead) **while sitting in the
Kabsch fit**. Same class of bug as the overhang beads in [[project_snupi_gaps]] DISPLAY fix #1.

Fix: emit only strand-covered beads. Payload **27 687 → 14 766** (−47%), and the fit got measurably
better — u=0 FEM-display vs the rendered pose went **0.40 → 0.241 nm mean / 0.67 → 0.565 max**.
`test_predict_shape_covers_every_nucleotide_including_each_loop_copy` had **enshrined the dead payload**
(its oracle was the raw lattice, though its docstring claimed "every nucleotide the renderer draws");
it now asserts a **bijection** with `_geometry_for_helices` — 1134 emitted == 1134 drawn, zero dead,
zero stranded. Shared cando+snupi path; fully strand-covered designs (ordinary bundles) are unchanged.

### Gate — VoltronCore (3000-step dynamics+tails run, 60 s)

Internal motion in the played trajectory (frames aligned to each other, so global rocking is out):

| bead class | n | motion |
|---|---|---|
| duplex, meshed | 13 908 | 0.257 nm |
| bridging ssDNA (rides along its nearest bp) | 287 | 0.383 nm |
| **free ssDNA tails — SIMULATED** | **571** | **0.275 nm**, 0.514 → 0.572 nm anchor→tip (the cantilever gradient) |

All 55 tails recovered from the payload with intact chains (bond 0.696 nm mean, range 0.53–0.87 —
thermal); `dt` unchanged at 0.152 ps; tails cost ~2× the per-step force, so a 60k-step VoltronCore
run is ~20 min without hydro. Verification: `just test-smart` → decision **FAST**, **4774 passed /
82 skipped, 18.1 s** (budget 19/60 ok); heavy groups **DEFERRED** (parked in `.nadoc-slow-pending`).
`just test-frontend` **2773 passed**. `main.js` LOC Δ = **0**.

### 🐞 The OH15 bug (found by the user in the app, 2026-07-14) — the anchor is NOT always the 5' end

**Symptom:** two overhangs sitting side by side on one helix (VoltronCore h_XY_3_2: OH3 at bp 55→40,
OH15 at bp 71→56, anchored through crossovers at adjacent bp 55 / 56 of h_XY_2_2) read as one strand,
and OH15's bond to its anchor was visibly overstretched.

**Cause:** `build_tail_block` chained every tail from `run.nts[0]` — its **5'** end. But the anchor is
whichever end crosses back into the embedded staple (the user's rule, which the SS-0 classifier already
honours in both polarities via `anchor_5`/`anchor_3`). For an overhang at the strand's **5' terminus**
the anchor is on its 3' side, so `nts[0]` is the FREE TIP: the chain got bonded to the anchor by the
wrong end, and the nucleotide covalently continuous with the staple was placed at the far end of the
coil. The drawn backbone bond was then stretched by **the tail's whole end-to-end distance** — so the
error GREW with tail length, the signature that identified it. It also mis-seeded `_tail_direction`
(which reads `nts[0]` as "the nucleotide out of the anchor") and made `max_nt` truncate from the tip.

**Measured on VoltronCore (anchor → the nucleotide that adjoins it, in the emitted display):**

| | tails | before | after |
|---|---|---|---|
| `anchor_5` (was already right) | 31 | mean 0.93 / max 1.21 nm | unchanged |
| `anchor_3` (built backwards) | **24 of 55** | mean **2.75** / max **8.18** nm (a 28-mer) | mean **0.97** / max **1.21** nm |
| OH15 / OH3 specifically | | **3.78** / 0.40 nm | **0.40** / 0.40 nm |

**Fix:** order each run **anchor-outward** once (`nts = run.nts if run.anchor_5 else reversed(run.nts)`);
`index_in_run` now means "distance from the anchor", explicitly NOT 5'→3'.

⚠️ **Why it survived SS-2 and SS-3: every fixture was 3'-terminal (`anchor_5`).** The classifier was
pinned in both polarities from SS-0, but the *chain builder* never saw the other one. `_tail_design_5p_terminal`
is now its mirror, and `test_the_fixture_pair_really_does_cover_both_anchor_polarities` guards the pair
from drifting back to the same polarity. Any new tail test should be `@parametrize`d over both.
