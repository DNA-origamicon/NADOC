# Gate — the WLC oracle, met — supporting detail

[Topic head](../../project_snupi_ssdna.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
