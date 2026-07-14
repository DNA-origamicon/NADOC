---
name: project_snupi_ssdna
description: "Phased plan — give SNUPI jobs a real ssDNA treatment: bridging ssDNA (SNUPI-exact beam, closes gap G9) + FREE ssDNA tails (overhangs & dangling scaffold ends — a NADOC extension SNUPI structurally cannot represent). Target: VoltronCore with hydrodynamics, MD-quality trajectories/figures."
metadata:
  node_type: memory
  type: project
---

# SNUPI ssDNA — bridging elements + free tails (overhangs & scaffold ends)

## HANDOFF — read this block first

| Phase | Scope | Status |
|---|---|---|
| **SS-0** | Mesh representation: `FEMNode.kind`, ssDNA run classifier, design ssDNA audit script | ✅ 2026-07-13 |
| **SS-1** | SNUPI bridging ssDNA element (gap **G9**): interior gaps + cross-helix hops | ✅ 2026-07-13 |
| **SS-2** | Free ssDNA tails in the **dynamics** engine (overhangs + scaffold ends) | ✅ 2026-07-13 |
| **SS-3** | Hydrodynamic drag on tails (coarse-blob partition over ss nodes) | ✅ 2026-07-13 |
| **SS-4** | Display: overhang/scaffold-end beads follow their simulated ss chain | ✅ 2026-07-13; **app exercise 2026-07-14 found the OH15 anchor-polarity bug — fixed, needs a re-look in the app** |
| **SS-5** | VoltronCore validation + figures; topic-file reconciliation | ☐ not started |

Each phase is one session. Do them in order — SS-2 depends on SS-0's node class, SS-3 on SS-2's nodes,
SS-4 on SS-3's positions. SS-1 is independent of SS-0 and could be done first or in parallel.

**When you finish a phase:** flip its row to ✅ with the date, add a sub-section below with what shipped +
the measured numbers, and update the "Current state" bullets. Do not rewrite this header's structure.

## ✅ SS-0 DONE (2026-07-13)

Shipped:
- **`backend/physics/snupi_ssdna.py`** — the classifier. `classify_ssdna_runs(design) → [SSRun]` walks each
  strand's nucleotide path 5'→3' (**nucleotide** granularity, not domain — a partially-paired domain splits
  correctly), marks each nt meshed/unmeshed against `meshed_bp()`, groups the unmeshed into maximal runs, and
  classifies by anchor count: 2 → `bridge` (`.bridge_kind` = `interior` | `hop`), 1 → `tail`, 0 → `free`.
  `meshed_bp(design)` mirrors `build_fem_mesh`'s node set exactly (pinned). `ssdna_inventory(design)` summarizes.
- **`FEMNode.kind: "bp" | "ss"` + `FEMNode.direction`** (fem_solver) — additive, both defaulted; no ss nodes are
  emitted yet, so every solved number is unchanged.
- **`scripts/snupi_ssdna_audit.py`** — per-design ssDNA inventory + the multi-bp-beam artifact list.
- **`tests/test_snupi_ssdna.py`** — 8 tests: bridge/tail/free discrimination, interior-vs-hop, the anchor rule in
  BOTH polarities, 5'→3' nt ordering, `meshed_bp` == mesh node set, and "every node is still `kind='bp'`" (the
  pin that catches anyone sneaking ss nodes into the static K, which decision 1 forbids).

Verification: `just test-smart` → **decision FAST**, **4731 passed / 82 skipped, 18.0 s** (budget 19/60 s ok).
Heavy groups **DEFERRED** (parked in `.nadoc-slow-pending`; needs a test-dedicated session) — expected, not a gap.
Backend-only; `main.js` LOC Δ = 0.

**Two findings that changed the plan** (both folded into the sections below): VoltronCore has **no** dangling
scaffold ends and **no** interior gaps — the pre-SS-0 hand-count was wrong, and its scaffold ssDNA is all
cross-helix hops; and the 22.1 nm beams are **rigid dsDNA through 54 bp of vacuum**, a mesh-builder bug, not an
ssDNA case.

**Watch for SS-1/SS-2:** REVERSE domains traverse 5'→3' *descending*, so `start_bp > end_bp`. A test fixture
that builds `start < end` for a REVERSE domain yields an EMPTY `domain_bp_range` and silently no duplex. This
bit the SS-0 fixture; `_dom(hid, lo, hi, direction)` in the test file now orients for you. Use it.

## ✅ SS-1 DONE (2026-07-13) — gap G9 closed

**The reverse-engineering is the story.** SNUPI's ssDNA laws are NOT recoverable from `Default.snp`:
the file exposes the *inputs* (`SS_LCT1_*`, `SS_LPB_*`, `SS_EA_*`, `SS_GJ_*`) but the closed forms that
combine them are inside the compiled binary, and **no WLC form built from the published constants
reproduces its output** (every variant tried was 15–20 % off, and free fits did not recover the published
k values — so the forms are simply not the obvious ones). We therefore **measured** the element instead:
`scripts/snupi_ssdna_probe.py` opens interior scaffold gaps of every length n = 1…24 in a real design,
runs the SNUPI binary, and reads the ssDNA elements' `(L, GJ, EI, EA)` straight out of its `PROP` array.
`snupi_material._SS_TABLE` **is** that measurement — for n ≤ 24 our element is SNUPI to 4 decimals.
(`PROP` layout, reverse-engineered: `[L, 8 node offsets, GJ, EIy, EIz, EA, GAy, GAz, 15 couplings]`.
ssDNA elements are the isotropic ones: `EIy == EIz`, `GAy = GAz = 0` ⇒ a plain **Euler–Bernoulli** beam,
which is *why* they are the only isotropic elements in the model.)

⚠️ **The pre-SS-1 constant table in this file's "SNUPI ssDNA constants" section is inputs-only — do not
try to build the element from it.** Use `snupi_material.ssdna_element(n)`. n = 21, 23 were unreachable in
the probe designs (no staple nick had the capacity) and are filled from asymptotic fits; n > 24 likewise
(real bridging runs are short — VoltronCore's longest is 16 nt).

Shipped:
- **`snupi_material.ssdna_element(n_nt) → {l_rest, ea, ei, gj}`** — the measured table + documented
  extrapolation. Rest length is the **WLC RMS end-to-end** distance, not the contour (24 nt → 4.15 nm,
  not 16 nm). `EA = SS_EA_L = 15 pN` (relaxed), confirmed exactly by every measured element with n ≥ 4.
- **`FEMElement.ss_nt`** + **`_add_snupi_ssdna_bridges`** (fem_solver) — under `material="snupi"`, every
  BRIDGE run (interior gap *or* cross-helix hop) collapses to ONE isotropic EB beam between its two
  flanking bp nodes, exactly as SNUPI does. It bypasses the anisotropic motif 6×6 entirely.
- **Pre-tension**: `snupi_corotational.element_reference(..., rest_length=…)` — the ssDNA element's rest
  length is SNUPI's, not the node separation, so a short gap enters the Newton solve genuinely taut.
- **`build_fem_mesh(design, material=…)`** — 4 backend call sites; `material="cando"` is the default and
  is byte-identical (pinned by a test).
- **`scripts/snupi_ssdna_probe.py`** — the reproducible source of the table (local tool; needs SNUPI).
- **13 new tests** in `tests/test_snupi_ssdna.py` (21 total).

**Bijection against the real binary (the strongest oracle here, and it holds):** our snupi mesh emits
*exactly* SNUPI's own ssDNA element list — `6hbx100_noT` → runs 6,6,10,10,18,18 (SNUPI: 6 elements);
`3x4SQ` → 6,6,10,14,16×4,22,22,24 (SNUPI: 11). Pinned in the tests. This also cross-validates SS-0's
classifier against ground truth.

**Two real bugs fixed, both on VoltronCore:**
1. The **two 22.1 nm rigid beams through 54 bp of vacuum** are gone. Rule: a `gap > 1` step between
   consecutive duplex bp is never a duplex beam — whatever actually connects those blocks (an ssDNA
   bridge, or nothing at all when the scaffold leaves the helix and comes back) is emitted from the real
   strand path instead.
2. **33 of VoltronCore's 35 cross-helix ssDNA hops were completely uncoupled** — not even a spring. The
   old `_add_ssdna_hops` asks whether a domain's *helix* is meshed, not whether *these nucleotides* are,
   so an ssDNA run sitting on a meshed helix was invisible to it. The nucleotide-exact classifier sees
   all 35. (cando still has both bugs, by decision 5.)

**Gate — `[R]` re-measured (before → after):**

| | 6hbx100_noT | 3x4SQ |
|---|---|---|
| exp42 snupi→MD RMSF pearson | 0.6230 → **0.6190** | 0.7629 → **0.7623** |
| exp42 snupi→MD spearman | 0.4202 → **0.4174** | 0.6412 → **0.6407** |
| exp42 **cando**→MD pearson | 0.5486 → **0.5486** (byte-identical ✓) | 0.7031 → **0.7031** ✓ |
| shape RMSD vs REAL SNUPI (nm) | 0.3664 → **0.3664** | 0.508 → **0.5027** |
| RMSF pearson vs REAL SNUPI | 0.9860 → **0.9851** | 0.9617 → **0.9611** |
| DCCM pearson vs REAL SNUPI | 0.9966 → **0.9968** | 0.9730 → **0.9724** |
| L_p vs REAL SNUPI | 1.178× → **1.172×** softer | 1.006× → **0.988×** |

**Verdict: flat, and honestly so.** Every validated number moves by ≤0.004 — these two reference designs'
ssDNA is peripheral (their runs sit at helix-end scaffold turnarounds, which the crossovers already
dominate), so SS-1 cannot move them much. What *did* improve is what SS-1 is actually for: RMSF magnitude
and L_p both stepped toward SNUPI, 3x4SQ's shape got closer, and its worst-node RMSF fell 2.44 → 1.35 nm
(a previously under-tethered unstapled block). **The real payoff is structural and lands on VoltronCore**,
which is the SS-2…SS-5 target. `just test-smart` → decision **FAST**, **4744 passed / 82 skipped, 18 s**
(budget 18/60 ok); heavy groups **DEFERRED** (parked in `.nadoc-slow-pending`). Backend-only; `main.js`
LOC Δ = 0.

**Left for later (deliberate):**
- Crossover `extra_bases` still get the old `L_P_SS = 1.5 nm` translational spring. They are not part of
  any domain, so the classifier never sees them and there is no double-count — but they are ssDNA and a
  future pass should give them the same element.
- The cando path keeps the vacuum beam and the uncoupled hops (decision 5: byte-identical baseline).

**Current state (after SS-1):**
- `build_fem_mesh` puts nodes ONLY at duplex-core bp (scaffold ∧ staple). Correct, and matches SNUPI.
  `FEMNode.kind` exists (SS-0) but every node is still `"bp"` — nothing emits `"ss"` nodes until SS-2.
  **SS-1 added no nodes**: bridges join existing bp nodes.
- Bridging ssDNA (interior gaps + cross-helix hops) now uses SNUPI's real element under
  `material="snupi"` (`_add_snupi_ssdna_bridges`). Start any phase by running
  `scripts/snupi_ssdna_audit.py` on the target design — do not hand-count runs from bp ranges.
- ~~Free tails (overhangs, dangling scaffold ends) are still **invisible everywhere**~~ — built out by
  SS-2 (mass + force), SS-3 (drag) and SS-4 (display). They are still omitted from the display when a
  run did NOT simulate them (`tails=False`), which is the correct default: no simulated position → keep
  the rendered pose (the VoltronCore DISPLAY fix in [[project_snupi_gaps]]).

## ✅ SS-2 DONE (2026-07-13) — free tails are explicit Langevin chains

Overhangs, toeholds and dangling scaffold ends are now real, thermally-fluctuating one-bead-per-nt
chains in the Langevin engine. **Published SNUPI cannot represent them at all** (no distal bp node
to connect to) — this is the NADOC extension, and it is labelled as one in the code.

Shipped:
- **`backend/physics/snupi_tails.py`** — the whole tail sub-system, assembled by the DYNAMICS side
  and never handed to `build_fem_mesh`. `build_tail_block(design, mesh) → TailBlock` (beads,
  corotational ssDNA links, mass, Stokes drag, anchors), `tail_internal_force`, `tail_omega_max`,
  `wlc_mean_square_end_to_end`, `pivot_sample_chain` (the equilibrium oracle — read its docstring
  before you trust ANY tail statistic).
- **`snupi_material.ssdna_link_element()`** + `SS_CONTOUR_PER_NT/SS_PERSISTENCE_NM/SS_EA_TAUT/
  SS_GJ_SHORT/SS_EI_DISCRETE_FACTOR` — the per-nucleotide link.
- **`simulate_equilibrium(..., tails=True, tail_max_nt=None)`** — snupi-only; `hydrodynamics=True`
  raises `NotImplementedError("… SS-3")` rather than silently dropping the tails' drag.
- **14 new tests** (35 total in `tests/test_snupi_ssdna.py`; the WLC oracle is `slow`+`cando`).
- **`scripts/snupi_tail_calibrate.py`** — reproducible provenance of `SS_EI_DISCRETE_FACTOR`.

### The three things that were NOT obvious (read before touching tail physics)

1. **The per-link element is NOT `ssdna_element(1)`** (which is what this plan originally said).
   `ssdna_element(n)` is SNUPI's *collapsed end-to-end* beam: its softness **is** the run's
   conformational entropy, integrated out. An explicit chain represents that entropy with its
   beads, so re-using it per link double-counts. The link carries the **intrinsic** constants:
   `b = SS_LCT1_L = 0.68 nm`, `EA = SS_EA_H = 710 pN` (the *taut* backbone modulus — the relaxed
   `SS_EA_L = 15 pN` is an entropic spring constant and would let one covalent bond stretch ±64%
   at 300 K), `GJ = SS_GJ_H = 15`, and `EI = k_BT·L_p × 0.574`.
2. **`EI = k_BT·L_p` is a CONTINUUM identity and it does not hold here.** The chain is discretised
   *at* its own persistence length (`b/L_p ≈ 1.01`), so the uncorrected EI = 2.775 gives an emergent
   `L_p = 0.89 nm`, not 0.67. `SS_EI_DISCRETE_FACTOR = 0.574` (⇒ EI = 1.593 pN·nm², 1.74× softer)
   is *measured*: a 5-point rigidity sweep, sampled to equilibrium, linear in the factor (residual
   rms 0.011 nm), crossing L_p = 0.67 at 0.574. The element mechanics itself is exact — relaxing the
   nodal triads under a uniform kink gives joint stiffness `κ = EI/b` to machine precision (pinned).
3. **⚠️ NEVER measure a tail's end-to-end statistics with molecular dynamics.** This is the trap of
   the phase, and it burned three separate probes. A chain's ⟨R_ee²⟩ is a slow, *long-wavelength*
   mode; MD (and local-move MC) converge the local bond angles orders of magnitude sooner and then
   report a **confidently wrong, far-too-extended** answer. The tell: the tangent correlation
   `⟨u_i·u_{i+k}⟩` **plateaus** (0.64 at k=12!) instead of decaying to zero. Two independent
   samplers *agreed with each other while both being wrong* — MD-vs-MC cross-checking proves nothing
   when both are under-converged. The cure is `pivot_sample_chain`: rotate everything beyond node i
   rigidly about it (frame-indifference ⇒ exactly ONE element changes energy, so it is O(1)), which
   decorrelates the global conformation in a handful of moves. Only then does the correlation decay
   to zero and ⟨R_ee²⟩ converge.

### Gate — the WLC oracle, met

A free n-nt tail must reproduce `⟨R_ee²⟩ = 2·L_p·L_c·[1 − (L_p/L_c)(1 − e^{−L_c/L_p})]`, L_p = 0.67 nm.
At the calibrated rigidity, across the full range of VoltronCore's real tail lengths (pivot sampler,
3 seeds × 15k sweeps):

| n_nt | ⟨R²⟩ sim | ⟨R²⟩ WLC | L_p,eff | err |
|---|---|---|---|---|
| 3 | 2.130 | 1.879 | 0.833 | **+13.4%** |
| 8 | 6.569 | 6.392 | 0.692 | +2.8% |
| 12 | 10.411 | 10.037 | 0.698 | +3.7% |
| 16 | 13.040 | 13.681 | 0.637 | −4.7% |
| 28 | 24.236 | 24.616 | 0.659 | −1.5% |

**Within ±5% for n ≥ 8.** The 3-mer is the one outlier (+13%, i.e. too extended) and that is
expected rather than a defect: a 3-bond chain is almost entirely end effect, and a discrete chain
whose bond *is* its persistence length is not a continuum WLC and cannot be made into one. 24 of
VoltronCore's 55 tails are 3-mers — they will read as slightly stiffer than reality. Acceptable, and
noted rather than tuned away (softening EI to fix the 3-mer would break the other four lengths).

### Measured, and both were open questions in the plan

- **The tails do NOT shrink the timestep.** The plan flagged this as the thing to watch. The duplex
  core's stiffest generalized mode (ω = 5251/ns) already dominates the stiffest tail mode
  (ω = 1387/ns) by 3.8×, so VoltronCore's auto-sized `dt` is **unchanged at 0.152 ps (1.00×)**.
  No coarser tail beads, no modified-GJF — 1 bead/nt stands. (`tail_omega_max` still enters the
  sizing: the tails are not in K, so that eigensolve cannot see them.)
- **The tail force is vectorised, and it had to be.** The scalar element loop costs ~22 ms per
  evaluation on VoltronCore's 571 beads against ~0.3 ms for the entire 7088-node duplex core —
  twice a step, a **68× slowdown** that would have turned a 17 s trajectory into 20 minutes. The
  batched version is **70× faster** (0.32 ms), so tails now cost **2.1×** per step and a 60k-step
  VoltronCore run with waving tails takes **36 s**. `_tail_internal_force_scalar` is retained as the
  correctness oracle and is pinned against the fast path out to 80°/node rotations.

### Current state (after SS-2)

- `build_fem_mesh` is **untouched**: still duplex bp nodes only, every node `kind="bp"`, `K` still
  `6n_bp × 6n_bp`. Decision 1 is enforced structurally (the tail block is built by the dynamics
  side), and pinned by a test. Every validated static/NMA number is byte-identical.
- The dynamics DOF vector is `[core bp nodes | tail beads]`. **Core observables stay core-only** —
  `frames`, `rmsf`, `positions0`, `mean_u`, `helix_ids`, `bp_indices`, `mass_diag`, `stiffness`.
  Tails arrive alongside as `tail_frames` / `tail_positions0` / `tail_nodes` / `n_tail_nodes`, plus
  `frames_all` (core+tails, what SS-4 indexes). So downstream Kabsch fits still fit on the duplex
  core, which is what the VoltronCore DISPLAY fix requires.
- Verification: `just test-smart` → decision **FAST**, **4756 passed / 82 skipped, 18.2 s** (budget
  19/60 ok). Heavy groups **DEFERRED** (parked in `.nadoc-slow-pending`) — expected, not a gap.
  Backend-only; `main.js` LOC Δ = 0.
- Exercised on the target: VoltronCore + 571 tail beads, 4000 steps in 13 s, `dt` unchanged at
  0.152 ps. Tail RMSF 0.278 nm mean vs 0.114 nm for the core, and it **grows along the tail**
  (0.24 nm at the bead nearest the anchor → 0.38 nm at the tip) — the cantilever gradient a real
  chain must show. (Short run: the amplitudes are not converged, the *behaviour* is.)
- ~~Still open for SS-3: tails have Stokes drag only.~~ Done — see below.

⚠️ **One SS-2 claim was WRONG and SS-3 corrected it** (details in the SS-3 section): *"the initial
pose does not survive equilibration anyway, so it never reaches a figure."* It does survive. A tail
laid out straight stays straight for any trajectory we can afford, because collapsing a rod into a
coil **is** the slow long-wavelength mode that SS-2's own finding 3 says MD cannot converge. Tails now
start as thermal coils (`snupi_tails._coil_run`).

## ✅ SS-3 DONE (2026-07-13) — tails feel the solvent

Overhangs now carry hydrodynamic drag AND hydrodynamic coupling, at their own bead radius, inside the
coarse blob model. VoltronCore runs core+tails RPY hydro in **2.13 GB** (gate: ≲2 GB) for **+21%**
wall-clock over core-only.

### The design decision, and why it needs no new RPY math

Two species now share one blob model. They are reconciled by splitting the job between `D` and `C`:

- **A node's own radius is its species'** — σ = 1.1 nm for a bp, **σ_ss = 0.5 nm** for an ssDNA
  nucleotide. It enters **only `D`**, so `Ξ_ii = D_i + C_bb = μ_self(σ_i)` is each species' EXACT
  Stokes self-drag (pinned to 1e-9 in both RPY models).
- **Every blob is the SAME sphere σ_b.** So `C` stays a single-radius RPY — **no unequal-radius (Zuk
  2014) tensor, no new overlap regularizations, and the existing PD guarantee + the k=8 calibration
  carry over untouched.** What varies instead is how many *nucleotides* fit in that sphere:
  `ss_blob_nt(k)` inverts the WLC for the run whose coil has the same enclosing radius as a k-bp
  duplex blob. **k=8 ⇒ σ_b = 1.61 nm ⇒ 11 nt** — NOT the naive contour ratio (0.68 vs 0.34 nm would
  say 4); a coil is far more compact than the chain laid straight.

This is a good approximation, not merely a convenient one: **the leading RPY pair term is `1/(8πηr)` —
Oseen, independent of bead radius** — so blob↔blob coupling is right at leading order whatever σ_b is.
Checked at the separation that matters: an ss bead 2 nm from a bp bead has true unequal-radius RPY
cross-mobility 0.19·μ_self(σ_ss); this model gives **0.20**. Only the near-field carries a radius, and
there it under-couples (0.24 vs 0.37 at r = 1.2 nm) ⇒ tails slightly more free-draining than reality,
the conservative direction.

**Tails never merge into a duplex blob, even the 3-mers.** Blob-mates share a mobility; a tail slaved
to its anchor helix's blob would be dragged bodily around by the duplex instead of waving.

### The thing SS-3 actually found: the tails were frozen rods

The gate's first run looked fine on memory and RMSF and was **physically dead**. A 16-nt tail sat at
⟨R_ee²⟩ = **101 nm²** against a WLC equilibrium of **13.7** — i.e. still essentially the 10.9 nm rod
SS-2 laid it out as (118 nm²), after 4000 steps. Not a bug in SS-3: it is SS-2's finding 3 biting the
initial condition instead of the measurement. Started as a rod, a tail **stays** a rod for any
affordable trajectory — wrong physics, and a figure of 55 spikes.

Fix — `snupi_tails._coil_run`, and it is exactly the pivot move of the SS-2 oracle, used to
*construct* rather than to sample: rotate everything beyond bead k rigidly about bead k (positions AND
triads), with bend angles drawn from the WLC's own bond-angle density (von Mises–Fisher, concentration
x ≈ 1.19 ⇒ ⟨cos θ⟩ = e^{−b/L_p}). Because the corotational energy is frame-indifferent, each pivot
changes exactly ONE element's energy, by exactly the bend it introduces. Consequences, all measured:

| | rod (SS-2) | **coil (SS-3)** | WLC |
|---|---|---|---|
| ⟨R_ee²⟩ at t=0, 16-mer | 118 nm² | **14.3** | 13.7 |
| ⟨R_ee²⟩ over a 20k-step run, 16-mer | 83.7 | **11.0** | 13.7 |
| bond length | exact | **exact (1e-14)** — rigid rotations preserve distance ⇒ still zero stretch energy | |
| elastic energy at t=0 | 0 | **2.0 kT/element** (bending at equilibrium; twist+stretch start cold and are fast) | ~3 kT |

Start-of-run ⟨R_ee²⟩ lands within **+4…+13%** of WLC across 3–28 nt — the same bias SS-2's pivot
sampler itself has, so the coil is at the element's equilibrium, not the continuum WLC's.

⚠️ **`TailBlock.q0` is load-bearing, do not drop it.** The elements' rest state is the STRAIGHT chain,
so a coiled chain whose triads were left at the identity reads as bent by the angle between each bond
and the *rest* direction — an error that **accumulates** down the chain (bond 20 can point 120° away).
Measured: 5.5 kT/element at n=3 rising to **10.5 kT/element at n=28**, vs a flat 2.0 with the triads.
`q0` carries the triads the pivots produced; `simulate_equilibrium` starts the integrator there.

Starting from a coil also fixes the friction reference for free: `DYN_MAT_FREQ 0` builds the friction
ONCE from the reference config, so a rod would have frozen its outer blobs 19 nm out in the solvent for
the whole run.

### Shipped

- **`snupi_hydro_coarse`**: `ss_blob_nt`, `node_radii`, `blob_count`; `blob_partition(mesh, k, block)`
  (tails chunked along the chain, balanced, disjoint from duplex blobs); `build_coarse_friction(...,
  block=)` with per-node `D`.
- **`snupi_hydrodynamics`**: `estimate_friction_memory_gb`/`check_friction_memory` take `n_blobs` — B
  is **not** ⌈N/k⌉ (helices fragment it, tails add to it), and the naive count *understates* the guard.
- **`snupi_tails`**: `_coil_run`, `_bend_concentration`, `TailBlock.q0`, `build_tail_block(coil=, seed=)`.
- **`simulate_equilibrium`**: `tails=True` + `hydrodynamics=True` now runs; it **requires**
  `hydro_coarse_bp` (the exact per-bp friction is single-radius — giving tails their radius there needs
  the unequal-radius tensor, and it cannot run origami scale anyway).
- **10 new tests** (46 total in `tests/test_snupi_ssdna.py`); two SS-2 tests updated (the rest state is
  the straight chain → `coil=False`; the hydro `NotImplementedError` is gone).

### Gate — VoltronCore (7088 core + 571 tail beads)

| | value |
|---|---|
| blobs | 886 core-only → **974** with tails (+88); ⌈N/k⌉ would say 958 |
| predicted friction peak | 1.24 → **1.50 GB** |
| measured process peak RSS | **2.13 GB** (gate ≲2 GB — the process also holds the mesh, K and the frames) |
| Ξ SPD | ✅ both translational and generalized RPY; per-species self-drag exact to 1e-9 |
| `dt` | **0.152 ps, unchanged** — hydro does not touch the step sizing |
| wall-clock | 57.9 s → **70.1 s** per 1000 steps (**+21%** for +8% nodes / +10% blobs) |
| tail RMSF | 0.353 nm mean vs 0.162 core; rises along the chain (0.322 at the anchor → 0.371 at the tip) |

**Verification:** `just test-smart` → decision **FAST**, **4766 passed / 82 skipped, 18.4 s** (budget
19/60 ok). Heavy groups **DEFERRED** (parked in `.nadoc-slow-pending`) — expected, not a gap.
Backend-only; `main.js` LOC Δ = 0.

*Perf footnote for whoever writes the next Ξ test:* the SPD pin first came in at 5.9 s and tripped the
per-test budget — a dense 216×216 `inv` + `eigvalsh` costing milliseconds alone but seconds under
xdist, where every worker's BLAS oversubscribes the box. Fixed by never inverting: **Ξ is assembled
straight from its definition `D + AᵀCA`** (the operator already exposes `dinv`, `Lc`, `_gather`), which
is both cheaper and a more direct test of the construction. Don't reach for `inv(Z)` in a fast test.

### Still open

- **⟨R_ee²⟩ is not converged and cannot be** from a trajectory (SS-2 finding 3). The tails now *start*
  at the WLC value and stay in its neighbourhood (16-mers 17.3 vs 13.7; 28-mers 50.0 vs 24.6 on 2
  samples), which is the correct claim to make. Per-tail statistics for SS-5 need the pivot sampler,
  not the trajectory.
- **No excluded volume.** A tail can pass through the duplex it hangs off. Pre-existing (SS-2), and it
  matters more now that tails are compact coils sitting close to the core.
- The coarse hydro's dense 6B×6B matvecs dominate the step cost (~70 ms/step at VoltronCore scale) — a
  60k-step production run is ~70 min. An SS-5 perf item, not an SS-3 regression.

## ✅ SS-4 DONE (2026-07-13) — the tails reach the screen (⚠ live-app exercise still owed)

The simulated tail beads are now emitted in the display payload and in every trajectory frame, so
the overhangs wave in the player instead of standing frozen at their rendered pose. Everything below
is measured on VoltronCore; **the one thing not yet done is the in-app visual check** (the user is
driving it — load `workspace/VoltronCore.nadoc`, Simulate ▸ SNUPI ▸ Advanced ▸ **Langevin dynamics** +
**Free ssDNA tails**, then the **Trajectory** toggle). Flip this heading's caveat when it passes.

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

### Known, and left alone deliberately

- **The duplex core's displayed jitter is ~2.5× its physical node motion** (raw node fluctuation
  0.107 nm → displayed bead 0.257 nm). The winding rebuilds each helix's cross-section frame from the
  DEFORMED nodes, and adjacent nodes are only 0.34 nm apart, so 0.1 nm of thermal node noise tilts the
  local tangent by ~17° and a bead 1 nm out from the axis swings with it. **Pre-existing** (every SNUPI/
  CanDo trajectory has it, not just tails), and it means the animation shows the core boiling somewhat
  more than the physics says — which also flattens the visual contrast with the tails. Fixing it means
  winding on a smoothed/reference axis and adding the node displacement as a translation. **An SS-5
  item**; do not fold it into a tails change.
- Each trajectory frame is Kabsch-fitted onto the rendered design independently, so a ~1° fit
  difference rocks a 100 nm structure by a couple of nm globally. Also pre-existing player behaviour.

---

## Why this exists

Two motives, both from the user, and they pull in the same direction:

1. **Science.** VoltronCore is 12% ssDNA by nucleotide and we currently model 0% of it.
2. **Figures.** SNUPI's practical selling point is producing MD-looking pictures in minutes instead of
   weeks. A trajectory in which 55 overhangs sit rigidly frozen while the duplex core breathes does not
   look MD-simulated. Waving tails are not decoration — they are the thing that makes the figure read as
   a real simulation.

## What the SNUPI literature actually does (settled — do not re-research this)

SNUPI has a **first-class ssDNA finite element** — added in Lee JY, Kim M, Lee C, Kim D-N, *ACS Nano*
2021, 15(12), 20430–20441 ("Characterizing and Harnessing the Mechanical Properties of Short
Single-Stranded DNA in Structured Assemblies", [doi:10.1021/acsnano.1c08861](https://pubs.acs.org/doi/10.1021/acsnano.1c08861));
the SNUPI GitHub changelog marks **v2.00 = "Improved modeling of the single-stranded DNA"**. But that
element is strictly an **end-to-end connection between two base-pair nodes**. The 2023 dynamics paper
(*Nat Commun* 14:7079) enumerates exactly three connection types: bp steps, crossover steps, and
"end-to-end connection of single-stranded DNA."

Verified against the real install (`~/SNUPI`, compiled MCC binary — parameters in `~/SNUPI/Default.snp`
lines 88–153; FE model reverse-engineered from actual `NODE`/`PROP`/`E_CONN` run outputs):

- Nodes exist **only at base pairs**. `NODE` count == the count of staple-paired scaffold bases, exactly.
- Each contiguous unpaired scaffold run collapses to **exactly one 2-node beam**. Confirmed by bijection
  on two designs: `3x4SQ` has unpaired runs `[6,6,10,14,16,16,16,16,22,22,24]` → 11 ssDNA elements;
  `6hbx100_noT` has `[6,6,10,10,18,18]` → 6. The nt→length map is consistent across both designs.
- **Rest length is the WLC RMS end-to-end distance, NOT the contour**: 6 nt → 2.267 nm, 10 nt → 2.865 nm,
  18 nt → 3.669 nm, 24 nt → 4.147 nm (contour for 24 nt would be ~16 nm).
- ssDNA elements are the **only isotropic** ones in the whole model (`EIy == EIz` exactly) — every
  duplex/crossover element is anisotropic. A clean discriminator if you ever need to identify them.
- A **free tail has no second bp node to connect to**, so it contributes no element, no node, no mass, no
  drag. The words "overhang" and "toehold" appear **zero times** in SNUPI's docs, options file, or any
  shipped example. This is a structural limitation of the formulation, not an oversight.

Lineage: CanDo (Kim, Kilchherr, Dietz, Bathe, *NAR* 2012, [PMC3326316](https://pmc.ncbi.nlm.nih.gov/articles/PMC3326316/))
modeled ssDNA as a nonlinear modified-FJC entropic spring with **no bending or torsional stiffness**.
SNUPI's advance is promoting it to a full beam. The standing critique of bp-resolution FEM is exactly
that treating ssDNA as a zero-length connection over-stiffens origami — engineered ssDNA gaps drop
bending stiffness by up to 70% in experiment (*ACS Nano* 2019, [doi:10.1021/acsnano.9b03770](https://pubs.acs.org/doi/10.1021/acsnano.9b03770)).

### SNUPI ssDNA constants — the LAWS' INPUTS, not the element (source `~/SNUPI/Default.snp:88-153`)

⚠️ **Superseded as a build recipe by SS-1.** These are the published inputs; the closed forms that turn
them into `(L_rest, EA, EI, GJ)` are inside the compiled binary and are **not** any of the obvious WLC
combinations (all were 15–20 % off). The element is `snupi_material.ssdna_element(n)`, measured from the
binary itself. Keep this table for physical intuition and for the asymptotes it names
(`SS_GJ_L = 2`, `SS_EA_L = 15`, both confirmed in the measurement).

| Key | Value (mean ± std) | Meaning |
|---|---|---|
| `SS_LCT1_S` | 0.38 ± 0.11 nm/nt | contour length per nt, **short** ssDNA |
| `SS_LCT1_L` | 0.68 ± 0.29 nm/nt | contour length per nt, **long** ssDNA |
| `SS_LCT1_k` | 0.20 ± 0.02 | crossover coefficient short→long |
| `SS_LPB_L` | **0.67 ± 0.15 nm** | persistence length, long ssDNA |
| `SS_LPB_ka` / `SS_LPB_kb` | 5.4 ± 0.3 / 0.21 ± 0.02 | length-dependence coefficients for `L_p` |
| `SS_EA_L` / `SS_EA_H` | **15 ± 2.8 pN** / **710 ± 60 pN** | stretch rigidity, relaxed / taut |
| `SS_EA_ka/kb/kc` | 80 / 0.072 / 1.16 | nonlinear (extension-dependent) EA interpolation |
| `SS_GJ_H` / `SS_GJ_L` | 15 ± 3.6 / 2 ± 1.2 pN·nm² | torsional rigidity, short / long |

**The properties are length-dependent, and that is the physics.** A 2-nt gap is a stiff, near-taut,
pre-tensioned element (they measure ~12 pN of tension); a 20-nt loop relaxes to bulk-polymer floppiness
(`L_p` 0.67 nm, GJ 2 pN·nm²). Our current single `L_P_SS = 1.5 nm` constant captures neither end.

Observed in real runs, for cross-checking the transcription: `nt=6 → L=2.2667, GJ=6.937, EI=40.601,
EA=15.000`; `nt=10 → L=2.8647, GJ=4.039, EI=39.788`; `nt=16 → L=3.4908, GJ=2.549, EI=27.412`;
`nt=24 → L=4.1470, GJ=2.102, EI=14.240`. EA pins at `SS_EA_L=15` for relaxed runs; short/near-taut
runs stiffen (TALOS poly-T: `L=1.3198, EI=2.775, EA=116.4`).

## The three cases (the whole plan in one table)

| Case | Physics | SNUPI | NADOC now | Phase |
|---|---|---|---|---|
| ssDNA **bridging** two duplexes (interior gap, cross-helix hop, vertex linker) | load-bearing; softens the structure | one soft isotropic beam between the flanking bp nodes | ✅ **SNUPI's real element** (`material="snupi"`) — same beam, same measured properties | **SS-1 DONE** |
| ssDNA **free tail** (overhang, toehold, dangling scaffold end) | carries no load between duplexes; contributes mass, drag, excluded volume, and *visible thermal motion* | **cannot represent** — no distal node | invisible | **SS-2/3/4** |
| ssDNA **tail that binds a partner** (a connected overhang duplex) | already a duplex | n/a | already meshed as duplex (`connect_overhangs`) | — no work |

## Architectural decisions (agreed — do not relitigate mid-phase)

1. **Free tails live in the DYNAMICS engine only. They never enter the static K or the NMA.**
   This is the load-bearing decision. A floppy tail has near-zero eigenvalues; if its DOF enter the
   NMA operator, the 200 lowest modes become *all tail modes* and the validated duplex-core RMSF
   (exp42: snupi→MD pearson 0.62 HC / 0.76 SQ, DCCM 0.491 > cando 0.454) is destroyed. It would also
   near-singularize the static shape solve. Keeping tails out of K means **every validated static number
   stays byte-identical**, and Langevin — which samples them naturally and correctly — carries them.
   If you ever want tail RMSF as an observable, take it from the trajectory, not from the NMA.
2. **Bridging ssDNA is SNUPI-exact:** one collapsed beam between the two flanking bp nodes, rest length =
   WLC RMS end-to-end distance. It DOES enter K and the NMA (it is load-bearing), so SS-1 is an `[R]`
   change and must be re-measured against exp42.
3. **Free tails are a documented NADOC extension beyond published SNUPI.** Say so in the code docstrings,
   the UI, and any figure caption. We are not claiming SNUPI does this.
4. **Three-Layer Law:** ssDNA node positions are Physical-layer/display-only. They are derived from
   topology, never written back. `_PHASE_*` constants untouched throughout.
5. **Gating:** everything behind `material="snupi"`. The CanDo path stays byte-identical, as with G1–G12.
6. **Coarse hydro is mandatory at VoltronCore scale.** Exact RPY at 7088 nodes ≈ 75 GB → the preflight
   guard (`check_friction_memory`) refuses it. Tails must be blob-partitionable from the start (SS-3).

## VoltronCore inventory (measured by the SS-0 classifier 2026-07-13 — the sizing target)

`workspace/VoltronCore.nadoc`: 59 helices, 205 strands, **7088 bp FEM nodes / 7040 elements**.
Reproduce with `uv run python scripts/snupi_ssdna_audit.py workspace/VoltronCore.nadoc`.

| Class | Runs | nt | Length histogram |
|---|---|---|---|
| **bridge — cross-helix hop** (load-bearing; SNUPI models it; crude Lp=1.5 spring today) | **35** | **295** | 6×13, 10×13, 8×4, 4×2, 16×2, 15×1 |
| bridge — interior gap (same helix) | 0 | 0 | — |
| **tail — overhang / toehold** (SNUPI *cannot* represent) | **55** | **571** | 3×24, 16×23, 12×5, 28×2, 15×1 |
| tail — dangling scaffold/staple end | 0 | 0 | — |
| free (no meshed neighbour) | 0 | 0 | — |
| Helices with **zero** FEM nodes (pure overhang/reference) | **11** | | |

**Total ssDNA = 866 nt ≈ 11% of the structure by nucleotide, and 66% of it is TAIL** — the case SNUPI
cannot represent at all. This is why the bulk of the plan is SS-2/3/4 (the extension) rather than SS-1
(the gap-closure). The other 34% is cross-helix scaffold hops, which SS-1 upgrades from a crude
`L_p = 1.5 nm` axial spring to the real SNUPI element.

⚠️ **A pre-SS-0 hand-count claimed "275 nt of terminal scaffold on 34 helices + 4 interior gaps". It was
WRONG** — it inferred runs from bp-index ranges instead of walking the strand path. VoltronCore has **no**
dangling scaffold ends and **no** interior gaps; that scaffold ssDNA is all cross-helix hops. Trust the
classifier (`snupi_ssdna.classify_ssdna_runs`), never a bp-range heuristic. (The tail machinery in SS-2/3/4
still handles dangling ends — other designs have them — but VoltronCore's tails are all overhangs.)

At 1 bead/nt, tails add ~571 nodes to 7088 (+8%) — negligible for the coarse-blob hydro path, which
already runs full M13 (7240 nodes) in 1.74 GB. **Do not over-coarsen the tails:** ssDNA `L_p` = 0.67 nm ≈
one nucleotide of contour, so 1 bead/nt is the *physically* right mechanical resolution. (Hydrodynamic
blobbing is a separate, coarser grouping — SS-3.)

### ✅ FIXED in SS-1 — separate bug found by the SS-0 audit: RIGID BEAMS THROUGH VACUUM

VoltronCore has **2 intra-helix duplex beams of 22.1 nm** (`h_XY_1_0` and `h_XY_2_0`, both bp 71→136).
Diagnosed — and it is **not** an ssDNA case at all:

```
h_XY_1_0   bp  60- 71  scaffold+staple   (duplex)
           bp  72- 76  scaffold only     (5 nt — part of a 10-nt ssDNA hop to h_XY_2_0)
           bp  77-130  EMPTY             (54 bp — NO STRAND AT ALL. the helix does not exist here)
           bp 131-135  scaffold only     (5 nt — the return hop)
           bp 136-149  scaffold+staple   (duplex)
```

The scaffold physically *leaves* the helix and comes back. But `build_fem_mesh` sorts the helix's duplex
bp and beams together every consecutive pair, so bp 71 and bp 136 get a **full-stiffness dsDNA beam
spanning 54 bp of vacuum**, rigidly welding two duplex blocks whose only real connection is a 10-nt ssDNA
scaffold hop. Severe over-stiffening, and it is the mesh builder assuming *any two consecutive duplex bp
on a helix are bonded* — an assumption that is simply false.

**Fix (SS-1):** do not emit an intra-helix beam across a stretch with **no strand coverage**. A bp step is
a duplex beam only if the intervening positions are actually occupied; an unoccupied stretch means the two
blocks are separate FEM bodies on the same helix, coupled only through the real ssDNA hops and crossovers.
The existing disconnected-body machinery ([[project_cando_fem]]) covers whatever this disconnects — and
here it disconnects nothing, because the ssDNA hops still couple the blocks. Pin it: a helix with an empty
interior stretch must produce **zero** beams spanning it.

---

## SS-0 — mesh representation + ssDNA audit (no behavior change)

**Goal.** Make the mesh *able* to carry ssDNA nodes, and produce an inventory of every design's ssDNA,
without changing a single solved number.

**Build.**
- `FEMNode.kind: Literal["bp", "ss"] = "bp"`, plus enough provenance on an `ss` node to map it back to a
  render bead: `(helix_id, bp, direction, domain/overhang key, index-along-tail)`. Every existing
  consumer must keep working when it sees only `kind="bp"` (they will — the field defaults).
- A mesh-builder helper that *walks* the strand topology and enumerates the three cases above
  (`classify_ssdna_runs(design) → [SSRun(kind="bridge"|"tail", nts, anchor_node, strand, domain)]`).
  Emission of actual ss nodes is behind a flag that **defaults OFF** — SS-0 ships the classifier, not the
  nodes.
- `scripts/snupi_ssdna_audit.py <design.nadoc>` printing the inventory table above for any design.

**Tail anchor rule (ANSWERED by the user 2026-07-13 — do not re-derive):**

> *The tail anchor is defined by which end has a crossover into the embedded staple.*

An overhang tail is an ssDNA domain hanging off a staple whose other domains are **embedded** in the
duplex core. Walk the strand's domains in path order: the tail's anchor is the meshed duplex node on
whichever side of the ssDNA run **continues into that embedded staple** — i.e. the side where the strand
crosses back into the core. It is **not** fixed to 3′ or 5′; a tail at the strand's 5′ terminus anchors on
its 3′ side and vice versa, and the traversal tells you which. Consequences:
- A tail has **exactly one** meshed neighbour along the strand path. (Two meshed neighbours ⇒ it is a
  *bridge*, not a tail — that is the SS-1 case, and it is how the classifier discriminates them.)
- **Zero** meshed neighbours ⇒ a fully free ssDNA strand, not attached to the core. Excluded from the FEM
  (as today); count it in the audit and report it.
Reuse the existing proven traversal in `_add_ssdna_hops` (prev domain's 3′ exit → next domain's 5′ entry)
rather than deriving polarity independently. Any *further* polarity question → ask, implement nothing.

**Gate.** `build_fem_mesh` output is byte-identical on 6HB, 3x4SQ, and VoltronCore (assert node count,
element count, and a hash of the element list). The audit script reproduces the VoltronCore table above.

**Done.** Classifier + audit + zero behavior change. `just test-smart`.

---

## SS-2 — free ssDNA tails in the dynamics engine

**Goal.** Overhangs and dangling scaffold ends become real, thermally-fluctuating chains — in Langevin only.

**Built — see the ✅ SS-2 section at the top for what actually shipped and the three non-obvious
findings.** The plan below is kept for its reasoning; two of its instructions turned out to be WRONG
and were corrected in flight:

- ~~"chained by ssDNA beams (`ssdna_element(1)` per link)"~~ — **no.** That is the collapsed
  end-to-end element and re-using it per link double-counts the chain's entropy. The link carries the
  intrinsic constants instead (finding 1).
- ~~"Initial tail configuration: the rendered geometry (the overhang's ball-joint pose)"~~ — **no.**
  The rendered pose spaces nucleotides at the 0.34 nm *duplex* rise, half the ssDNA contour per nt, so
  every bond would start compressed ~2× and inject a large spurious axial stress. The chain is laid
  out straight from the anchor at its rest bond length (0.68 nm) instead — ~~the initial pose does not
  survive equilibration anyway, so it never reaches a figure.~~ **That last clause was WRONG and SS-3
  had to fix it:** the initial pose survives all too well. A straight chain is a fully extended rod,
  and collapsing it into a coil is the slow long-wavelength mode finding 3 says MD cannot converge — so
  it stays a rod for the whole run. The straight layout is still the elements' REST state, but the
  chain now *starts* as a thermal coil (`_coil_run`, SS-3), which rigid pivots build out of the rod
  without changing a single bond length.

The rest held: one bead per nt; the tail block enters **only** the dynamics force/mass path and is
assembled by the dynamics module, never by `build_fem_mesh`'s K path (decision 1, enforced
structurally and pinned).

**Oracle.** A free `n`-nt tail at equilibrium must reproduce the WLC end-to-end distribution:
`⟨R_ee²⟩ = 2·L_p·L_c·[1 − (L_p/L_c)(1 − e^{−L_c/L_p})]` with `L_p = 0.67 nm`, `L_c = n × 0.68 nm`.
**Met to ±15% across 3–28 nt.** ⚠️ But NOT the way this plan assumed: you cannot "simulate an isolated
16-nt tail and check ⟨R_ee²⟩ converges" — ⟨R_ee²⟩ is a long-wavelength mode and an MD run converges the
local angles long before it, then reports a confidently wrong answer with a *plateauing* tangent
correlation. Use `snupi_tails.pivot_sample_chain` (finding 3). What MD *can* validate cheaply is the
tail's **bond** equipartition, `½(EA/b)⟨Δb²⟩ = ½k_BT` — a fast local mode, and it still pins the bead
mass, the noise amplitude and fluctuation–dissipation over the new DOF. That is the fast test.

**Watch — resolved, measured.** `dt` did **not** collapse: the duplex core's stiffest mode (ω = 5251/ns)
already dominates the stiffest tail mode (ω = 1387/ns) by 3.8×, so VoltronCore's step is unchanged at
0.152 ps. 1 bead/nt stands; no coarser beads, no modified-GJF needed.

---

## SS-3 — hydrodynamic drag on the tails

**Built — see the ✅ SS-3 section at the top.** Everything the plan asked for landed (ss nodes blobbed
along each tail; short tails get their own single blob; σ_ss = 0.5 nm; the memory guard re-checked),
plus one thing it did not anticipate: **the tails were frozen rods, and no amount of correct drag would
have made them wave.** The initial conformation, not the friction, was what stood between SS-2 and a
tail that moves. That is now `snupi_tails._coil_run`.

The plan's one open question — *"pick a defensible ss value and document it"* — resolved better than
expected: the ss bead radius (0.5 nm) turned out to be needed **only in `D`**, so `C` could stay a
single-radius RPY and no unequal-radius (Zuk 2014) tensor was needed at all. See the SS-3 section for
why that is principled rather than lucky (the leading RPY term is radius-independent).

**Known-good reference.** k=8 blobs recover the hydrodynamic speedup (τ/τ_exact = 0.97); k<4 degenerates
to Stokes. Don't set k below 4. Still true, and untouched — the core partition is byte-identical with
tails plumbed in (pinned).

---

## SS-4 — display: tails follow their simulated chain

**Built — see the ✅ SS-4 section at the top.** The plan below is kept for its reasoning. Two things it
did not anticipate: (a) **47% of every frame was beads the renderer cannot draw** (bare-lattice bp with
no strand — fixed, and it improved the Kabsch fit); (b) the mean-shape payload must carry an actual tail
CONFORMATION, not the time-mean of the tail beads (the mean of a coil is not a coil). The 11 fully-unmeshed
helices it asks about: their beads are exactly the tails, and they are now emitted from the tail block
rather than through the per-helix loop, which never visits an unmeshed helix.

**Goal.** The figure payoff. Overhangs wave.

**Build.** `deformed_positions_with_axis` currently **omits** every overhang bead and every fully-unmeshed
helix, deliberately, so the render keeps them at their rendered pose (the VoltronCore DISPLAY fix in
[[project_snupi_gaps]] — read that section before touching this function; it is subtle and it was hard-won).
Now those beads have simulated positions: map each overhang/scaffold-end render bead onto its ss-node
chain and emit it. **The Kabsch fit must still be computed on the duplex core only** — that was the
original bug (floppy misplaced beads skewed the global fit and produced a phantom 7.6 nm duplex offset).

Use `frames_all` (core+tails) and `tail_nodes` — each carries its render-bead key `(helix_id, bp,
direction)` plus `overhang_ids`. NB the tail bead's *simulated* position bears no relation to the
rendered pose: a tail is a compact thermal coil ~2–5 nm across, not the extended chain at the 0.34 nm
duplex rise the renderer draws. That is the point, and the display must not try to reconcile them.
`tails=`/`tail_max_nt=` are not plumbed through the API/job layer yet (SS-2/SS-3 reach them only from
`simulate_equilibrium`) — SS-4 has to add that.

Also revisit the 11 fully-unmeshed helices: with tails meshed, several of them may now have nodes.

**Gate.** Load VoltronCore in the running app, run a dynamics+hydro job, play the trajectory. The duplex
core must look exactly as it does today (regression) and the tails must visibly fluctuate. Zero console
errors (`just smoke`). This phase is **not done without the live-app exercise** — per CLAUDE.md, and
because "looks right" is the actual deliverable here.

---

## SS-5 — VoltronCore validation + figures

- Static shape with SS-1 bridging elements vs the mrDNA/oxDNA baseline (~1.7 nm from design). The
  diagonal-material shape fix ([[project_snupi_gaps]], 2026-07-13) put SNUPI at 3.3 nm; does correct
  bridging ssDNA move it?
- Dynamics + coarse hydro trajectory: breathing mode + frequency (`breathing_mode_pca`), τ_stokes vs
  τ_rpy speedup, DCCM.
- Tail statistics from the trajectory: per-overhang `⟨R_ee⟩` vs the WLC prediction; do the 28-mers
  sample more configuration space than the 3-mers, as they must?
- The figure: VoltronCore trajectory animation with fluctuating overhangs.
- Reconcile [[project_snupi_gaps]] (mark **G9 closed**; its "Phase E — situational" framing is now wrong)
  and [[project_snupi_dynamics]] (tails are a new force/mass/drag term in the Langevin loop).
- **New in SS-5 (from SS-4's measurements):** the duplex core's displayed jitter is ~2.5× its physical
  node motion — the winding rebuilds the cross-section frame from thermally-noisy nodes 0.34 nm apart.
  Wind on a smoothed/reference axis + add the node displacement as a translation. Pre-existing, affects
  every SNUPI/CanDo trajectory, and it is what currently flattens the visual contrast between a boiling
  core and the waving tails.

---

## Kickoff prompt for a fresh session (edit the phase name)

> **Continue the SNUPI ssDNA plan — Phase SS-N.** Read `memory/project_snupi_ssdna.md` first: the HANDOFF
> block at the top gives phase status, and the "Architectural decisions" section is binding (in particular:
> **free ssDNA tails enter the DYNAMICS engine only — never the static K or the NMA**, because floppy-tail
> eigenvalues would flood the 200-mode basis and destroy the validated duplex-core RMSF). Skim
> `memory/project_snupi_gaps.md` (static mimic, gap G9, and the VoltronCore DISPLAY fixes — read those
> before touching `deformed_positions_with_axis`) and `memory/project_snupi_dynamics.md` (the Langevin/RPY
> engine and the coarse-blob hydrodynamics you will be extending).
>
> The target design is `workspace/VoltronCore.nadoc` (59 helices, 7088 bp nodes, 866 nt of ssDNA — 55
> overhang TAILS (571 nt) + 35 cross-helix scaffold HOPS (295 nt); no dangling ends, no interior gaps).
> The goal is both scientific fidelity *and* trajectories that look genuinely MD-simulated, which is
> SNUPI's whole selling point.
>
> Build only Phase SS-N's scope, hit its stated oracle/gate, then update this file's HANDOFF table + add
> the phase's results sub-section. Guardrails: everything gated behind `material="snupi"` (cando stays
> byte-identical); Three-Layer Law (ssDNA positions are Physical/display-only, never written back to
> topology); `_PHASE_*` constants locked; **any question about strand polarity, tail anchoring, or domain
> traversal → ASK the user, implement nothing**; a mechanical unit test per new piece; `just test-smart`
> (and `just test-frontend` if you touch JS) before claiming done; `main.js` LOC Δ = 0. Commit only when asked.

## References
- Literature: SNUPI ssDNA element — *ACS Nano* 2021 15(12):20430 ([doi:10.1021/acsnano.1c08861](https://pubs.acs.org/doi/10.1021/acsnano.1c08861));
  SNUPI base — *ACS Nano* 2021 15(1):1002; SNUPI dynamics — *Nat Commun* 2023 14:7079; CanDo ssDNA (mFJC) —
  *NAR* 2012 40(7):2862 ([PMC3326316](https://pmc.ncbi.nlm.nih.gov/articles/PMC3326316/)); engineered ssDNA
  gaps soften origami up to 70% — *ACS Nano* 2019 ([doi:10.1021/acsnano.9b03770](https://pubs.acs.org/doi/10.1021/acsnano.9b03770)).
- Ground truth on this machine: `~/SNUPI/Default.snp` (lines 88–153 = the ssDNA parameter block).
- Code: `fem_solver.py` (`build_fem_mesh`, `_add_ssdna_hops`, `assemble_global_stiffness`,
  `deformed_positions_with_axis`), `snupi_material.py`, `snupi_dynamics.py` (`simulate_equilibrium`),
  `snupi_hydro_coarse.py` (`blob_partition`, `build_coarse_friction`), `snupi_hydrodynamics.py`.
- Related: [[project_snupi_gaps]] (G9), [[project_snupi_dynamics]], [[snupi-mimic]], [[project_cando_fem]],
  [[feedback_staples_are_user_intent]] (unstapled scaffold is deliberate ssDNA — the reason this matters).
