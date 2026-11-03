# ⚡ Optimize button (Advanced card) — `backend/core/md_optimize.py` — supporting detail

[Topic head](../../project_water_shell_carve.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## ⚡ Optimize button (Advanced card) — `backend/core/md_optimize.py`

Automates the carve-vs-GPU-resident decision, because getting it wrong costs either ~35 %
throughput or a crash 40 min into a run. `GET /md/optimize-advanced` → `{recommended,
rationale, warnings, facts}`; the UI (`frontend/src/ui/md_advanced_optimize.js`) shows a
diff + caveat gate and applies only on Proceed.

**Flow:** pre-flight popup (opt out BEFORE the wait) → 3 staged calls with a progress bar
under the Advanced card title → proposal + caveat gate → apply only on Proceed.

**It runs NO simulation and NO benchmark** — say so in any UI copy. It (1) reads GPU/RAM/CPU
(~0.5 s, `GET /md/optimize-advanced/hardware`), (2) builds the design's heavy-atom model and
grid-measures its hydration volume (**~26 s** on a 6hb — the whole reason a pre-flight and a
progress bar exist; scales with design size), (3) scores candidate shells against the STORED
benchmarks above. The two backend calls are split precisely so the progress bar reports a
**real** stage boundary rather than a fabricated animation. The progress element lives
*outside* the collapsible drawer body so it stays visible when the drawer is shut.

⚠️ The busy latch must be set **synchronously, before the first `await`** — the pre-flight is
itself async, so a guard set after it lets rapid clicks stack up several pre-flight popups
(caught by a test; `rapid clicks cannot stack up multiple pre-flight popups`).

**The model.** Throughput ≈ K / N_atoms, with K per code path, anchored on two real
2080-Super runs: GPU-resident 12.8 ns/day @ 747,262 atoms; offload 18.8 ns/day @ 196,606.
⇒ GPU-resident is **~2.6× faster per atom**, so a carve only pays when it removes
> `CARVE_BREAKEVEN` (=K_gr/K_off ≈ 2.6×) the atoms. K is machine-specific; the RATIO — all
the decision depends on — is a property of NAMD, not the card. It reproduces both anchors
and picks correctly by shape: bent 6hbx100_90deg → 12 Å carve, offload, est 18.1 (measured
18.8); straight 6hb_sim_v2 → full box, GPU-resident, est 41.3 (measured 42).

**Shell thickness is PHYSICS, not a speed knob.** Throughput rises monotonically as the
shell thins, so an optimiser told to maximise ns/day will shave the hydration layer to
nothing. First cut of this module did exactly that (picked 8 Å every time). It now FIXES
the shell at `DEFAULT_SHELL_NM` = 1.2 nm and thins it *only* when memory forces it, never
below `MIN_SHELL_NM` = 0.8. Pinned by `test_never_thins_the_shell_for_speed_alone`.

**Audit of the Advanced card (what was missing).** `stepspercycle`/`pairlistdist` are the
knobs that mattered (+12 %) but are now correct defaults and are deliberately NOT exposed —
exposing them invites the `margin` footgun. What WAS missing and is now added: a read-only
**run-path readout** (`#md-jobs-path`, `describeRunPath()`) — GPU-resident on/off was the
single most consequential derived setting and was completely invisible; and the Threads
default was a hardcoded 16 on a 12-logical-core box.

**E2E gotcha (cost an hour).** Backend design state is **per-document**, keyed by the
`X-NADOC-Doc` header that `client.js` stamps on every call. A Playwright `request.post()`
carries no such header → lands in the `__default__` doc → the design loads fine and the
panel still sees *"No active design"* (404). Load the design **through the page** (`await
import('/src/api/client.js'); api.loadDesign(path)`), not via the `request` fixture. Several
existing e2e specs hardcode `:8000` (the user's server) instead of the throwaway `:8002` —
latent, works only because they don't need the design.

ROOT CAUSE — see [[LESSONS]] K2 / **K2b**. The `buildTileLists` illegal access IS fixed
by the patched `NAMD_3.0.2p1_*` build (`tools/namd_tilelist_fix/`, auto-preferred by
`find_namd()`). **But the patch does NOT make `GPUresident` usable on a carved cell.**

## ⚠️ 2026-07-12: A CARVE AND `GPUresident` ARE MUTUALLY EXCLUSIVE (enforced in code)

The p1 build no longer crashes, but the same empty-patch pathology still corrupts the
exclusion accounting: NAMD dies at step 0 with **"Low global CUDA exclusion count!"**
(241926 vs 276956 on the 12 Å-carved 6hbx100_90deg). The structure is *healthy* (all
377919 implicit exclusions ≤ 4.24 Å, max bond 1.7 Å), so the un-found pairs would have
been summed **without** their exclusion ⇒ wrong forces. **NAMD is right to abort; never
force it through** (the check is a `Controller.C` checksum, and `forgiving` mode would
just silently run bad physics).

Ruled out by experiment (RTX 2080 Super, 6hbx100_90deg): the ENM (no effect), HMR (fails
with the base PSF too), coordinates (`wrapAll on` → *identical* count; fails from minimised
coords), the local build (official 3.0.2 binary fails identically), and
cutoff/pairlistdist/margin/stepspercycle (the deficit only closes asymptotically —
pairlistdist 20 still short). **Only water fill fraction moves it:**

| shell | atoms | water fill | GPUresident |
|---|---|---|---|
| 1.2 nm | 196,606 | 22% | fail |
| 2.0 nm | 286,498 | 32% | fail |
| 3.5 nm | 440,965 | 52% | fail |
| 6.5 nm | 655,453 | 80% | **still fail** |
| none (full) | 747,262 | 92% | **pass**, 12.8 ns/day |

Control: `6hb_sim_v2` (uncarved, 90% fill, 225k atoms) runs GPU-resident at 42 ns/day on
the same GPU — so the GPU/driver/build are fine. A carve only ever *saves* atoms on a
**concave** design (a straight bundle already fills its bounding box), and that is exactly
when it creates the vacuum that breaks GPU-resident.

**Consequence (implemented):** `_segment_conf(carved=...)` omits `GPUresident` for any
carved package; it keeps HMR + `rigidBonds all` + 4 fs and runs the standard CUDA-offload
path (nonbonded + PME still on GPU). Because the carve removes ~3.8× the atoms, offload on
the carved cell (**18.8 ns/day**) still beats GPU-resident on the fully-solvated cell
(**12.8 ns/day**). `namd_solvate._render_solvated_fast_namd_conf` does the same for
`namd_fast.conf`.
(Later refined — the blanket "carved ⇒ offload" became `fill_fraction >= _RESIDENT_MIN_FILL`
(0.90), so a TIGHT carved box that the structure still fills keeps GPUresident.)
