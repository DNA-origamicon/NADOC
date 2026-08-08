# LESSONS — full entries

Split out of the index [LESSONS.md](LESSONS.md) on 2026-07-09 for context economy. The index carries a one-line symptom hook per lesson; open only the entry that matches your symptom. IDs/anchors are stable — other files (CLAUDE.md's Done checklist) cite them.

## A. DNA topology / geometry reasoning

<a id="a1"></a>
### A1. Geometric reasoning about crossover placement always produces wrong results
Multiple sessions have tried to reason about where crossovers "should" go from helix geometry, scaffold direction, or cell adjacency. Every time, the result was wrong and had to be reverted.

**How to avoid**: Use only the mechanical rules in `REFERENCE_CROSSOVER_AUTOBREAK.md` and existing functions. If a rule isn't documented, ask before inventing one.

<a id="a2"></a>
### A2. Strand polarity / direction confusion
Asking "which way does this strand go" without checking the topology graph repeatedly leads to errors. Polarity is not derivable from helix orientation alone.

**How to avoid**: Always check `Strand.domains[]` ordering and `Domain.direction` against the topology. If the domain list disagrees with what you expect from geometry, the geometry interpretation is wrong, not the domains.

<a id="a3"></a>
### A3. Helical phase constants are locked
`_PHASE_FORWARD`, `_PHASE_REVERSE`, `_SQ_PHASE_FORWARD`, `_SQ_PHASE_REVERSE` were tuned manually after long investigation. HC values landed at 322.2°/252.2° (forward/reverse), SQ at 337.0°/287.0°. Tweaking them to "fix" something else breaks every downstream system.

**How to avoid**: See `feedback_phase_constants_locked.md`. Never adjust without explicit user approval.

<a id="a4"></a>
### A4. `_frame_from_helix_axis` is NOT rotation-equivariant — world-aliasing a helix gives the wrong roll/phase (2026-05-21)
The radial frame for nucleotide geometry comes from `_frame_from_helix_axis(axis)` ([backend/core/geometry.py](backend/core/geometry.py)), which picks `x_hat = cross(ref, axis)` from a **fixed world `ref`** (`[0,0,1]`, or `[1,0,0]` when near-parallel). So `frame(R·axis) ≠ R·frame(axis)` for any rotation `R` that tilts the axis off world-Z. Consequence: a part's overhang is built in the part's *local* frame and then placed by the instance transform `T` (phase = `R·local`), but `GET /assembly/linker-geometry` built the overhang's complement ("binding domain") on a **world-space aliased helix** (`_world_axes_for_helix` copies only the axis endpoints) and re-derived the frame in world space → the complement rendered at the wrong roll for any tilted part (proven: 0 nm error untilted, 1.41 nm at 37°/90° tilt). The connector arcs anchored at the wrong spot too.

**Fix**: in `get_linker_geometry` ([backend/api/assembly.py](backend/api/assembly.py)), bake the roll difference `δ = signed_angle(frame(world_axis).x → R·frame(local_axis).x about world_axis)` into the aliased helix's `phase_offset`, so the world pass reproduces `R·(local geometry)`. δ=0 for untilted parts (no regression). Regression test: `test_linker_complement_phase_matches_tilted_overhang`.

**How to avoid**: any time you place a helix in world space by transforming only its axis endpoints and then run the geometry pipeline, the roll is re-derived from world-Z and won't match `T·(local geometry)`. Either compute in the local frame and apply `T`, or correct `phase_offset` by the frame-discrepancy angle. This is distinct from A3 (the constants are fine; the frame *reference* is the trap).

<a id="a5"></a>
### A5. Periodic-polymerize repeat transform must NOT register the radial/twist phase — it leaks into a spurious bend (2026-05-26)
`derive_periodic_delta` ([backend/core/periodic_polymer.py](backend/core/periodic_polymer.py)) fits the per-copy repeat transform by Kabsch-registering each seam's NEAR cross-section onto its FAR(+1bp) cross-section. The first version fed the full frame — origin + x/y/z axis tips — into the fit. The helical twist over one period is `period_bp · 34.3°`, generally **incommensurate** (teeth.nadoc: 251 bp → ~329°). A single rigid transform CANNOT reproduce a large radial rotation of OFF-CENTRE helices (rotating each helix about its own axis is non-rigid), so the radial x/y correspondences forced a least-squares compromise that **leaked the twist into a perpendicular TILT** → a per-copy bend → a visible spiral, even for a perfectly straight part (user repro: `workspace/Spiral.nass`, 6.8°/copy bend; the frame ORIGINS were clean — `far+1−near = (0,0,84.168)` for every seam — proving the geometry was straight and the bend was injected by the fit).

**Fix**: register AXIS GEOMETRY ONLY — origin + axis-tangent (z) tip, never the radial (`_axis_points`, not the old 4-point `_frame_points`). Straight part → pure translation (no bend); curved part → bend still recovered (it lives in the axis-tangent DIRECTION, captured by the z-tip); twist falls in the fit's null space → no spurious rotation. Post-fix teeth delta = pure 84.168 nm z-translation, 0.000°.

**Testing trap that hid it**: the original unit tests used L=21/42/84 — all within ~1° of a whole turn (near-commensurate), so the radial twist was ~0 and the bug didn't fire. The regression guard MUST use incommensurate periods (added L=30/55: ~51°/~28° from commensurate). When testing periodic/helical geometry, always include lengths whose twist-per-period is far from a multiple of 360°.

**How to avoid**: a rigid repeat transform for a polymer should encode position + axis ORIENTATION only. The internal helical twist continues through the ligated backbone topologically — it is not part of the rigid placement. Never put per-helix radial/roll into a single shared rigid fit for a multi-helix bundle.

---

<a id="a6"></a>
### A6. For twist correction, steer on SIGNED local twist (the twist-profile slope), NOT an unsigned deviation field (2026-06-28)
exp31 (`experiments/exp31_skip_twist_curvature_sweep/`) compared three skip-placement strategies for cancelling a square bundle's global twist. The "deviation-guided" arm — place skips where the per-nucleotide POSITIONAL deviation (`geometry_deviation_map`, unsigned nm) is largest — was predicted to be the adaptive winner. It was the WORST (max|cumulative twist| 68–95° vs incremental-gap's 5°). Root cause: unsigned positional deviation conflates bend, end-fraying, and twist and has NO SIGN, so it can't tell over-wound from under-wound and places deletions in the wrong segments. The signal that works is the SIGNED local twist — the slope of the per-position cumulative-twist profile (`measure_bundle_twist_profile`, differential sim−analytic): positive ⇒ over-wound ⇒ add a deletion here; negative ⇒ remove. And the placement that flattens rather than swinging the register is incremental largest-gap (keep existing marks, fill the widest gap). See [[project_regional_autorefine]]. (A6 fixes the SIGNAL; it does NOT license a wholesale profile controller — see A7 for why driving the whole budget off that signal still diverges.)

**How to avoid**: when an objective has a sign (twist handedness, over/under-wind), drive the controller with a SIGNED measurement of that exact quantity. A generic unsigned "error magnitude" (deviation/RMSD) is a different objective and steers placement wrong. Also judge straightness by max|cumulative twist| ALONG the profile (flatness), not the endpoint (front/back over/under-wind can cancel at the endpoint while the structure is kinked). NOTE: the shipped `greedy_finetune_skips`/`identify_finetune_edits` still violate A6 — they rank hotspots by unsigned `deviation_by_bp` and accept by `dev_max`. Use the signed-twist variant (rank by |detrended local-twist slope|, accept by Δ max|profile|) when fine-tuning twist.

---

<a id="a7"></a>
### A7. Do NOT drive a per-segment (MIMO) skip controller off the twist profile — it divides by noise and diverges (2026-06-28)
exp32 (`experiments/exp32_profile_guided_refine/`) tried to close exp31's loop: split the axis into 6 bins and run a per-bin secant that adds deletions to over-wound segments / removes from under-wound ones to flatten the signed twist profile (the A6-correct signal). Over 8 rounds on the 3×6×400 it DIVERGED — total skips oscillated 90↔1367, individual bins demanded 67–96 deletions/helix, and final flatness (52°) was WORSE than the period-48 seed (53°). Two compounding faults: (1) **divide-by-noise** — the secant estimates each bin's gain as `Δ(local twist)/Δ(count)` from a single round pair, but a one-deletion twist response (~1–3°) is far below the per-round sampling noise (≥±35°, the same noise the scalar loop pools 8M to beat), so the denominator is noise → `step = -gain·lt/slope` explodes (worked trace: a −1.2°/del noisy slope produced a target of 17 del/helix; later rounds wanted ~96). (2) **uncoupled bins on a coupled plant** — cumulative twist is a running integral, so editing one bin shifts every downstream bin; 6 independent SISO secants on a MIMO plant with dominant off-diagonal coupling can't be stabilized at any gain, and the deliberate `gain=1.3` overshoot grew the oscillation. This is the SAME wholesale-redistribution regime `project_regional_autorefine` §5.4 already ruled non-viable ("net twist is exquisitely register-sensitive; the local-shape signal is smaller than the placement-induced disturbance") — exp32 just re-proved it with a signed controller, expensively.

**How to avoid**: never let a skip optimizer re-place a large fraction of the budget for this plant, and never steer by dividing by a single-edit response measured against un-pooled sampling noise. The validated structure is: a single global count secant for the net-twist DOF (one well-conditioned pooled scalar, period 48→~24), then a SMALL (≤5) discrete fine-tune where each edit perturbs net twist <1° by construction and is accepted ONLY if a high-confidence re-sim improves flatness by more than the measured noise floor. ALWAYS characterize the per-round noise (repeat the converged design N times → σ) before acting on a signal, and check whether the "feature" you're chasing (e.g. the back-loaded profile) survives moving the route's nick before treating it as a real local target. exp34 tests this corrected algorithm — and finds the fine-tune itself is futile here (see A8): the per-edit effect is ~18× below the sampling noise.

---

<a id="a8"></a>
### A8. oxDNA global twist scatter on a long bundle is an EQUILIBRATION transient (~8M steps), NOT a slow stationary mode — discard burn-in, don't add seeds (2026-06-29)
exp34 (`experiments/exp34_finetune_validation/`) added a per-FRAME twist diagnostic (`oxdna_health.twist_series_stats` / `production_twist_series` / `detect_equilibration`). First read (8M runs): the 3×6×400 square bundle's global twist looked like a SLOW mode — τ_int≈100 frames, N_eff≈4/400, and the identical 222-skip design measured 5× scattered 7–32° (17.5±9.4°). The proposed fix was "~10× sampling / ~10 seeds." **An 80M run REFUTED that.** Its per-frame trace starts at +90° (the built/relaxed seed is badly over-wound) and RELAXES monotonically to ~−21° over the first ~80 frames (~8M steps), then rattles around −21° with NO autocorrelation beyond one 100k-step frame. So: (a) the global twist has a long ~8M-step EQUILIBRATION transient (the structure releasing its built-in over-wind); (b) AFTER equilibration the twist is FAST (τ_int=1 frame ⇒ τ_phys<100k steps). Dropping the first ~8M (burn-in) collapses τ 52→1, N_eff 15→720, **SEM 3.8°→0.4°, mean −21.2±0.4°**. The "slow mode / high τ" was a monotonic DRIFT masquerading as autocorrelation. The standard 8M autorefine production is ENTIRELY inside this transient → every prior twist number (exp31 "flat at +4", exp34 Gate 0/1) was measured mid-relaxation → BIASED (toward the positive start) AND scattered (±9°) by where the window landed. The "frozen vs drifting single-run τ" contradiction was just where in the transient each 8M window fell.

**How to avoid**: for the global twist of a big bundle the dominant error is INCOMPLETE EQUILIBRATION, not sampling. Run a burn-in of ≥~10M steps (or discard the first ~10M of production via `detect_equilibration`, Chodera-style N_eff maximisation) BEFORE measuring; after that the twist decorrelates fast (τ_phys<100k steps) so a short production gives SEM <1° — NO 10× compute, NO ensemble needed. Always look at the per-frame TRACE (`production_twist_series`): a monotonic ramp = unequilibrated (the autocorrelation-corrected SEM is then meaningless — it reads a drift as a long τ). Still true that `rmsf_confidence`/`std/√N_frames` is never the right error bar and a single under-equilibrated run is untrustworthy — but the cure is burn-in discard, not more seeds. With proper equilibration the measurement is ±0.4°, which REOPENS the ≤5-edit fine-tuner (its ~1°/edit signal was only "below noise" because the noise was an equilibration artifact). NOTE the separate ~±18° discreteness floor: one deletion per helix across ~18 helices moves net twist ~35°, so uniform integer-per-helix steps can only straddle twist-zero by ~±18° — landing tighter needs SUB-STEP (partial-round, non-uniform) placement, not a profile controller.

**CRITICAL CORRECTION (exp35, 2026-06-30) — `t0=0` from `detect_equilibration` does NOT certify equilibration; the "~8M transient / d+4=222→0°" numbers were measured on ALREADY-PRODUCED (warm-started) structures.** A FRESH cold-built d+4 (222 skips), relaxed with the shipped **10M equil** then 16M production, reads a FLAT, well-sampled twist of **+18.2 ± 0.7°** (t0=0, τ=2.9, N_eff 272; whole-mean == `detect_equilibration`-trimmed mean exactly) — NOT the exp34c warm-started −0.6°. So the 10M equil kills the FAST +90° ramp but the structure is still on a SLOW twist glide (+18° sits between exp34c's d+3=+36° and d+4=−0.6°, i.e. it relaxed *less* than the longer-history warm-start). `detect_equilibration` returned `t0=0` because a glide slower than the 16M production window has a per-frame slope far below the ±11° per-frame noise → it reads "flat" and CANNOT see a transient longer than the trajectory it's handed. So the burn-in remedy above has a hard caveat: **you cannot discard a burn-in longer than your whole run**, and apparent flatness at `t0=0` on a modest run is the SAME "low-τ doesn't certify sampling" trap one level up. Fix for a cold build = a twist-CONVERGENCE gate (keep equilibrating until the block-averaged twist slope ≈0 across a long run), not a fixed 10M equil. The exp34c "count was always right, d+4=net-zero" claim is UNCONFIRMED — a properly-equilibrated cold autorefine would still steer toward ~d+5 (240 skips). Open: continue the archived exp35 d+4 job ~64M more steps to see whether +18° glides to 0 (slow glide, exp34c right) or stays (metastable basin, hysteretic count). See `experiments/exp35_autorefine_equilibration_test/conclusion.md`.

<a id="a9"></a>
### A9. mrDNA `SegmentModel.simulate(coarse_steps=, fine_steps=)` SILENTLY runs a single 5 bp/bead coarse pass — the multiresolution fine (1 bp/bead + twist) stage never runs; use `multiresolution_simulation()` (2026-07-02)
Building "quick-check curvature" (loops one side / skips the other → Dietz bend) on the mrDNA panel: the CG sim came out ~straight (`6hb_curved.nadoc`, ±9 ins/del, analytic `loop_skip_calculator.predict_radius_nm` → **R≈36 nm / 88° bend**, relaxed to **~2°**). ROOT CAUSE (took a while): **`model.simulate(output_name, coarse_steps=…, fine_steps=…)` does NOT run mrDNA's multi-resolution pipeline.** `SegmentModel` inherits `ArbdModel.simulate(output_name, **kwargs)`, which recognises only a fixed set (`directory`, `binary`, `num_procs`, …) and shoves everything else — including `coarse_steps`/`fine_steps` — into `ArbdEngine(**engine_kwargs)` where they're ignored. So it ran ONE ARBD pass on whatever bead model was current (the 5 bp/bead coarse one from model build); the **fine 1 bp/bead + local-twist stage — where curvature develops — never executed.** (The original `/ws/mrdna-relax` had the same latent bug.) The real entry point is the module-level **`mrdna.multiresolution_simulation(model, output_name, directory, coarse_steps, fine_steps, coarse_output_period, fine_output_period, gpu)`** — it does coarse (5 bp/bead) → fine (`generate_bead_model(1,1, local_twist=True)`) → frozen-twist → atomic tail, writing numbered CG stages `{stem}-N.psf` (take the highest CG one = final fine). For a plain COARSE run the correct low-level call is `model.simulate(output_name, num_steps=…, timestep=200e-6, output_period=…, gpu=…)` — **`num_steps`, not coarse_steps**.

**But fixing it only gets ~18% of the designed bend, and that's a real CG limit.** With the true multiresolution pipeline the fine stage runs (1200 DNA beads = genuine 1 bp/bead) and the bend rises 2°→**~12–16°** — still far below 88°, and it PLATEAUS (12° at 5×10⁵ and 2×10⁶ fine steps ⇒ not equilibration). Parameterization matters and **T0 is the BEST we have**: `mrdna_model_from_nadoc_parameterized(…,"T0")` gives ~12°, mrDNA's **default** potentials give **1.3°** — so never drop T0 for curvature. Closing the remaining gap is the open [[project_crossover_parameterization]] / [[project_bundle_stiffness_params]] inter-helix-stiffness problem, not a panel fix. **Measurement gotcha:** a circle fit to the noisy CG centreline is NOT robust (swings R=20↔240 nm run-to-run — one lucky R=22 nm reading faked success); use the **end-to-end bend** (angle between first/last centreline segments) and derive R from it.

**How to avoid**: (1) never trust `model.simulate(coarse_steps=…)` did multi-res — check for numbered `{stem}-N` outputs / a 1 bp/bead (num_nt-scale) bead count; use `multiresolution_simulation`. (2) For curvature, the trustworthy number is the **analytic** Dietz value (instant, exact); the mrDNA sim is a directional/qualitative indicator (~18%) — the panel shows both + an amber caveat when sim/analytic<0.5. See [[project_mrdna_panel]].

---

<a id="a10"></a>
### A10. The scaffold is route OUTPUT; the STAPLES are the design (2026-07-13, ISSUE-9)

Autoscaffold was not idempotent: re-routing an already-routed design ratcheted it further out every time and
persisted the result to the `.nadoc`. Measured on a **plain 4HB honeycomb bundle** — no teeth, no sections, no
section router — helices grew `168 → 189 → 199 → 210` bp and crossovers `6 → 9 → 12` over three routes, on BOTH
the seamed and the seamless router. The ledger had filed it as a *teeth* bug for a month; it never was. Teeth is
merely where it was **visible** (the extension intrudes into the inter-tooth gaps). On a plain bundle it silently
lengthens your helices with no visual tell — which is why it survived so long.

**The general trap (this is the transferable part).** The near/far end-turn legitimately extends a helix a few bp
past the scaffold's terminal face, so the scaffold has ssDNA to turn around in (`MIN_SSDNA_MARGIN >= 3`; scaffold
crossovers live in extended ssDNA, never buried in a staple). But the router derived that face from
`_scaffold_coverage()` — **its own previous output**. On the second call the face is the already-extended
terminus, the search runs from `face - 3` strictly further out, and it extends again. The extenders are monotone
(`if new_lo >= helix.bp_start: return design`), so it is a **ratchet, not an oscillation** — it never converges
back. Worse, the extension rewrites `bp_start` / `length_bp` / `axis_start` / `phase_offset` **in place**,
destroying the very information needed to undo it.

> **Any mutation whose input is derived from its own prior output is non-idempotent by construction.** Ask, of
> every re-runnable operation: *what does it measure to decide what to do, and does it also write that thing?*
> If yes, it will ratchet. The fix is not to make the algorithm smarter — it is to **normalise the input against
> something the mutation cannot touch.**

**Here that invariant is the staples.** Autoscaffold never touches staple strands, so a helix's TRUE extent is
the bp span of its staple domains (including staple overhangs running past the scaffold). Verified: across three
re-routes the staple spans stayed at `[0,167]` while the helices ratcheted to `[-30,179]`. And in the real
multi-section fixtures the staple intervals ARE the scaffold sections, gaps and all — teeth
`[(0,41),(84,125),(168,209)]`, dumbbell `[(0,41),(126,167)]`. So the routing algorithm was left **completely
untouched**; only its input is normalised (`backend/core/scaffold_reset.py`): retract each helix + re-seed the
scaffold to the staple extent, then route. `reset(route(fresh)) == fresh`, field for field ⇒ N routes ≡ 1 route.

**Deliberately conservative:** the reset CLAMPS INTO the staple intervals and never GROWS a scaffold to fill them
(a scaffold left short of its staples was never routed there — growing it would silently edit an unrouted design;
this is what keeps the two-group seamless fixture working). Forced ligations bail out with a warning: a manual
fixed-edge topology is not derivable from the staples.

**Second bug, same neighbourhood — a "clear" that never cleared.** The seamed router stamps **three** different
`process_id`s on the crossovers it creates: `auto_scaffold_seamed:seam`, plus the bare `create_near_ends` and
`create_far_ends`. `_clear_auto_scaffold_route_for_seamed` matched only the `auto_scaffold_` prefix, so the
end-turn crossovers survived every clear — hence the accumulation, and it means that helper (relied on by
`auto_scaffold_matched`) had **never actually worked**. If you add a prefix-matched "owned by me" tag, enumerate
every id the subsystem actually emits; `section_router._is_scaffold_route_xover` had the full list all along.

**Method note:** the whole diagnosis came from a 40-line probe script that routed a bundle three times and printed
the helix/staple/scaffold extents after each. Reasoning about the router's control flow would not have shown the
ratchet; *running it twice* did, immediately. When asked "is bug X specific to design shape Y?", build the
simplest design that is NOT Y and run it.

---

## B. Three-Layer Law violations

<a id="b1"></a>
### B1. Physics writing back to topology
Several attempts have made XPBD/oxDNA results "stick" by writing relaxed positions into `Design.helices[].axis`. This corrupts the design and is invisible until much later. Physical layer is **display-only**.

**How to avoid**: If a fix tempts you to mutate topology from a relaxed-positions code path, stop. The fix is wrong.

<a id="b2"></a>
### B2. Re-centering native `.nadoc` files on load
`/design/load` previously called `_recenter_design`, which silently moved everyone's saved positions. Only caDNAno / scadnano *imports* may recenter.

**How to avoid**: See `feedback_native_files_preserve_positions.md`. Native loads preserve absolute positions.

---

## C. Stale state / API misuse

<a id="c1"></a>
### C1. uvicorn `--reload` keeps stale server state
Most-frequent debugging dead-end: a Python-level test passes, but the API returns wrong output. The cause is almost always residue from prior test/curl operations in `design_state`. Adding logging and diving deeper into Python is the wrong move.

**How to avoid**: First step when API output disagrees with Python-test output is restart the server (`just dev`). Only investigate as a real bug if it persists after restart.

<a id="c2"></a>
### C2. Wrong mutation path
`set_design_silent` does NOT push undo. Using it as a replacement for `mutate_and_validate` in a single-step op makes that op undoable. Multi-step ops require a `snapshot()` bracket; intermediates use `set_design_silent`; only the final step uses `mutate_and_validate`.

**How to avoid**: When in doubt, read the existing endpoint's pattern in `crud.py`.

<a id="c3"></a>
### C3. Wrong undo response shape
`/undo`, `/redo`, and `/features/seek` use the SAME shared response builder (`_design_replace_response`). Cluster-only ops return `diff_kind: 'cluster_only'` and skip geometry. Other seeks embed full geometry.

**How to avoid**: When adding a new mutation type, decide whether it's cluster-only or full and route accordingly. Don't introduce a third shape.

<a id="c4"></a>
### C4. Repeated E2E build-cycles wedge the shared `--reload` dev backend; 41% CPU is a RED HERRING (2026-05-22)
Running an E2E spec many times where each test does New Part → `helix-at-cell` → `auto-scaffold`/`load`
against the shared dev backend accumulated in-memory `design_state` until `/design/load` and
`/design/geometry` stopped responding (HTTP 000, 60 s) — the event loop was blocked by a long sync
computation, so ALL endpoints hung. Misdiagnosis trap: the uvicorn `--reload` worker sat at ~41% CPU
the WHOLE time (fresh OR wedged) — that's the **watchfiles** filesystem watcher on WSL2, NOT a wedge
signal. The real wedge signal is **unresponsive endpoints**, not CPU%. A fresh backend loaded the same
`teeth.nadoc` in 10 ms (geometry 0.48 s) and stayed responsive — proving it was stale state, not a
teeth-specific bug.

**How to avoid**: when API calls hang mid-E2E, check responsiveness (`curl -m 3 /`), not CPU%. Restart
`just dev` to clear state (extends [[#C1. uvicorn `--reload` keeps stale server state]]). In specs,
don't fixed-wait for a rebuild after the `nadoc-design` broadcast — POLL (`page.waitForFunction`) for
the target mesh (e.g. `backboneSpheres.count>0`); fixed waits were flaky under a busy server.

<a id="c7"></a>
### C7. NEVER load a user's REAL `workspace/*.nadoc` in a mutating/app-loading E2E — the app autosaves back and CORRUPTS it (2026-07-04)
Ran throwaway Playwright specs that `loadDesign('workspace/6hb_curved.nadoc')` (a gitignored USER fixture)
to screenshot the CanDo deform display + drive the autorefine panel. While it was the active design, the
app persisted extra `apply-loop-skips` + routing ops back to the SOURCE file (feature-log entries stamped
with the session's date, pre/post loop-skip counts jumping 18/18 → 38/36). This silently changed the file
`tests/test_mrdna_jobs.py::test_analytic_curvature_from_marks` hard-codes (expects analytic n_loops=18,
n_skips=18, R≈36 nm) → the test began failing with NO code reason. The file is gitignored (no `git checkout`
restore).

**Recovery that worked (definitive, not a guess):** the `.nadoc` feature-log entries carry gzip'd pre/post
Design snapshots (`design_snapshot_gz_b64` / `post_state_gz_b64`, decode via
`backend.api.state.decode_design_snapshot`) AND timestamps. Decoding each showed entries 0–7 dated the
ORIGINAL day (ending 18/18) and 8–9 dated the session (the corruption). Restored = `decode(fl[7].post_state)`
for the active state + `model_copy(update={'feature_log': orig.feature_log[:8]})` to KEEP the user's history
(the snapshot itself decodes with an EMPTY feature_log — must graft the original entries back). Backed up the
corrupted file first.

**How to avoid:** never point an app-loading E2E at a real user workspace file — copy it to a
`workspace/playwright_tests/__e2e__*.nadoc` first ([[feedback_playwright_fixtures_location]] +
`main-init.md` `__e2e__` cleanup), or build a throwaway design via `File>New`. Also: a headless build
(`hb.scratch_session`) is isolated and never touches the source — prefer it over app-loading for geometry
checks. And tests should not depend on a MUTABLE gitignored fixture's exact mark counts (fragile) — but
that's a separate cleanup.

<a id="c5"></a>
### C5. Rapid edits → out-of-order response clobber ("changes disappear a moment later") (2026-05-25)
Fast successive mutations (e.g. clicking several nicks quickly) fire CONCURRENT requests. The backend
serializes them correctly (`mutate_with_minor_log` under `_lock`), but the client had no ordering guard,
so an earlier response arriving LATE overwrote `currentDesign` with stale topology — later nicks
"disappeared", undo misbehaved, and the panel's feature_log desynced from the backend (→ `Feature index
N out of range (log has 1 entries)` on revert). Symptom looks like a backend bug but the backend is
correct; it's a frontend async-ordering bug. Adding latency to mutations (e.g. extra per-op encoding)
amplifies it.

**How to avoid**: design responses carry a monotonic `revision` (per-doc, bumped on EVERY state change
incl. undo/redo, captured atomically at mutation time via the `doc_context` ContextVar reset per request
by `DocContextMiddleware`). The client (`client.js` `_isStaleDesignResponse`) drops any design response
older than the newest applied (`_lastAppliedRevision`), at the top of `_syncFromDesignResponse` + both
fast-path syncs. When adding a new design-sync path or a response builder, include `revision` and run it
through the guard. Don't reach for a request queue (adds latency); the revision watermark is latency-free.
**CRUCIAL: reset the watermark on the connection-monitor `restarted` event** (`resetRevisionWatermark`) —
a backend restart resets the per-session revision LOW, so post-restart responses would otherwise be
dropped as "stale" and freeze the UI. Wired in 3D `_recoverAfterRestart` and the editor's restart handler.

<a id="c6"></a>
### C6. The cadnano EDITOR has a SEPARATE API client — fixes to `client.js` don't reach it (2026-05-25)
The 2D editor (`frontend/src/cadnano-editor/`) uses its own `api.js` (`_request`, `mutate`), NOT the 3D
`src/api/client.js`. Two editor-only bugs caused "editor feature-log can't revert (Feature index N out of
range, log has 1 entries) but 3D revert works":
1. The editor's feature-log shim (`_flMutate` in editor `main.js`) used a BARE `fetch('/api/...')` with NO
   `docHeaders()` → revert/delete/seek hit the DEFAULT doc instead of the editor's document (which has a
   different, often 1-entry design) → index out of range. The 3D client always sends the doc header, hence
   "3D works, editor doesn't". Also dropped `subIndex` (per-sub-step ops acted on the whole cluster).
2. The editor's `mutate` had no stale-response guard → same rapid-edit clobber as C5.

**How to avoid**: editor feature-log ops now live in editor `api.js` (`seekFeatures`/`deleteFeature`/
`revertToBeforeFeature`/`editFeature`) routed through `mutate`→`_request` (carries `docHeaders()` +
skip-geometry + the guard) and forward `subIndex`. ANY editor backend call must carry `docHeaders()` — grep
the editor for bare `fetch('/api` without it. Debug tools: `window.__nadocSyncDebug.sync()` (watermark /
in-flight / dropped / decision log) and `.backend()` (compares editor store ⇄ backend doc: revision,
feature_log length, `IN_SYNC` flag) — the fastest way to confirm a frontend↔backend desync.

<a id="c7-2"></a>
### C7. Autosave→SSE→sibling-tab reload clobbers in-progress edits (DEFEATS the revision guard) (2026-05-25)
With the editor + 3D view open on the SAME backend doc, fast edits showed only the LAST edit of each type
surviving; the rest reverted ~1s later. Mechanism: the editor autosaves `*.nadoc` → watchfiles → SSE
`file-changed` (`/api/library/events`) → the **3D tab reloads that file into the shared backend doc**
(`_handleLibraryEvent`, `_workspacePath===path` → `importDesign`). `_selfSavedPaths` is PER-TAB, so the 3D
tab didn't recognize the EDITOR's save as "ours" and reloaded a STALE autosave snapshot. The reload uses
`set_design` → revision bumps HIGHER, so the C5/C6 revision guard CANNOT catch it (verified: nicks flog=2
rev=6 → after stale reload flog=1 rev=7). Tell-tale in the editor sync panel: a flood of `BC-RX
design-changed` from the 3D tab right after editing.

**How to avoid**: self-saved paths must be CROSS-TAB. On autosave, emit `nadocBroadcast.emit('file-saved',
{path})` (editor `_runAutosave` + 3D design-autosave); the 3D `file-changed` handler adds broadcast
`file-saved` paths to `_selfSavedPaths` (5s window) so it skips the SSE reload echo of a sibling's save.
Same-doc cross-tab sync is via `design-changed` broadcasts + the backend being authoritative — NEVER reload
the open doc's file into the backend just because a sibling tab saved it. The revision guard can't help once
a reload has bumped the revision; prevent the reload. **CAVEAT: the `file-saved` broadcast is timing-fragile**
— a heavy 2D re-render (≈1 s on a 346-strand/1252-xover design; the render, NOT the backend ligate which is
~50 ms, is what makes a ligate "take a second") blocks the editor main thread and can delay the broadcast
past the SSE. The ROBUST guard is a same-doc-activity window: 3D tracks `_lastSameDocActivityMs` (set on every
received same-doc `design-changed`) and skips the open-doc reload within `_RELOAD_SUPPRESS_MS` (10 s).
`design-changed` is emitted by the editor BEFORE its debounced autosave writes the file, and everything
serializes on the editor's main thread, so design-changed always reaches the 3D before the SSE — making the
window robust regardless of render lag. (Separate open perf item: the cadnano pathview full-rebuilds on every
mutation — that's the real ~1 s, not the backend.)

<a id="c8"></a>
### C8. A mutation that writes a build-fingerprint field but skips the feature log silently breaks seek/staleness (2026-06-24)
Reported as "the oxDNA out-of-date ⚠ won't clear after seeking the Feature Log back to the relax run state"
(on `6hb_sim_tests.nadoc`). It was NOT the AF-25 overhang-membership bug (that was real but a separate, earlier
cause). Root cause: assigning an overhang sequence went through two paths that called `replace_with_reconcile`
(`PATCH /design/overhang/{id}` sequence branch) / bare `set_design` (`POST /design/overhang/{id}/generate-random`)
and recorded **no feature-log entry** — while every sibling op (`overhang-extrude`, `overhang-bulk`,
`assign-*-sequences`) used `mutate_with_feature_log`. `overhangs`/`strands` are in `design_build_fingerprint`, so the
live (sequenced) design and the timeline diverged: the relax froze the live overhang seq (`ATACTCGCTC`), but the
entry's stored post-state snapshot had it `None`; seeking back faithfully restored the snapshot → fingerprint never
re-matched → ⚠ unclearable. Diagnosis that nailed it: decode each `feature_log[i]` post-state snapshot and diff its
fingerprint fields against the job dir's frozen `design.json` — the mismatch was a single overhang `sequence`
field. **Fix:** route both writes through `mutate_with_feature_log(op_kind='overhang-sequence', …)`.

**How to avoid**: any route that mutates a field in `oxdna_staleness._FINGERPRINT_FIELDS` (helices, strands,
crossovers, deformations, extensions, overhangs, overhang_connections, forced_ligations, photoproduct_junctions)
MUST go through `mutate_with_feature_log` (or another snapshot-appending path), NOT bare `set_design` /
`replace_with_reconcile`. If a fingerprint field can change without a snapshot, seek can't reproduce that state and
job staleness can never reconcile. Audit probe: `rg "set_design\(|replace_with_reconcile\(" backend/api/crud.py` and
check each hit doesn't write a fingerprint field. A new `op_kind` need NOT be in `_edit_dispatch_run` — slider-seek
uses the baked post-state snapshot directly (like `overhang-bulk`/`assign-*`); the edit-replay loop falls back to the
baked snapshot for unknown kinds gracefully. Related: [[#C5. Rapid edits → out-of-order response clobber]] (also a
"live vs recorded state diverge" class). Note migration is NOT automatic — files already in the broken state need the
sequence re-applied once to write the missing entry.

<a id="c9"></a>
### C9. `glob("*.psf")[0]` picks the derived `_hmr.psf` sibling non-deterministically → prep fails on a phantom `{stem}_hmr.pdb` (2026-07-03)
An MD solvated package ships BOTH `{stem}.psf` and the fast-mode `{stem}_hmr.psf` (heavy-hydrogen topology, written unconditionally by `build_namd_solvated_package`). `prepare_mgh_slow_release` derived `name_stem = list(package_dir.glob("*.psf"))[0].stem` — but `Path.glob` order is filesystem-dependent (os.scandir order, NOT sorted). When it returned the `_hmr` file first, `name_stem` became `"{stem}_hmr"` and the very next step (`write_restraints_pdb(package_dir/f"{name_stem}.pdb", …)`) opened a nonexistent `{stem}_hmr.pdb` → `Preparation failed: [Errno 2] No such file or directory: …_hmr.pdb`. **Intermittent** — same code passed on machines/runs where scandir happened to order the base psf first; surfaced during an Alpine submit only because that run's glob ordering flipped (execution target is irrelevant — prep is identical for local/remote). Fix: `_base_name_stem()` filters out any `*_hmr.psf` before picking. Same latent bug lived in `benchmark_runner.py`; `md_import.py` was safe because it used `sorted()` (base `"{stem}."` sorts before `"{stem}_"` since `.`=0x2E < `_`=0x5F). **Lesson:** never index an unsorted `glob()` when a package can contain a derived same-extension sibling — filter by the naming convention or `sorted()`, and prefer a named helper so every call site agrees.

---

<a id="c10"></a>
### C10. Deleting a placed crossover in the 3D editor by NICKING only leaves the record behind → the arc is redrawn from the record ("colors change but the connection stays") (2026-07-10)
A crossover here is **nick + ligate + record** (`place_crossover`): a single strand routed across both helices PLUS a `Crossover` entry in `design.crossovers`. The 3D arc is drawn from *whichever exists* — [helix_renderer.js](frontend/src/scene/helix_renderer.js) `getCrossHelixConnections()` first emits an arc for each real strand-topology cross-helix cone, then **adds an arc for every crossover RECORD whose site isn't already covered by a cone**. So a record with no ligated strand across it still draws an arc. The 3D-editor Delete handler ([keyboard_shortcuts.js](frontend/src/ui/keyboard_shortcuts.js), `type==='crossover'`/`'cone'` + the multi-arc path) called `api.addNick` only. Nicking splits the strand (and `_build_nick` palette-colors the new fragment → **"strand colors change"**) but never touches the record → the record's arc is redrawn → **"the connection isn't deleted."** After that first click the crossover is left *unligated* (record present, strand split); a second Delete nicks at what is now a 3′ terminus → 400, nothing happens → "stuck." User symptom was on a copy/pasted cluster, but the paste was a red herring: the design had exactly ONE unligated record — the one they'd already tried to delete. Fix: when the selected arc carries a real `crossover_id`, route Delete through `DELETE /design/crossovers/{id}` (`deleteCrossover`, which desplices the strand AND drops the record) instead of a nick; keep the nick only as the fallback for record-less crossovers (pure strand topology, e.g. imported scaffold routing). Required adding `deleteCrossover`/`batchDeleteCrossovers` to the **main** `api/client.js` — they existed only in the separate cadnano-editor `api.js` (cf. [[C6]] — the editor has its own client). **Lesson:** when one concept has two representations (strand routing + a record) and rendering falls back to the record, a delete must clear BOTH; a mutation that only touches one representation looks half-done. Grep for other "unplace by nick" spots that assume nicking removes a recorded relationship.

---

## D. Rendering / scene state

<a id="d1"></a>
### D1. Beads flash to 3D for one frame after a cadnano/unfold mutation
A subscriber registered AFTER `cadnanoView`'s reapply subscriber called `revertToGeometry()` and overwrote cadnano positions. The classic culprit is FEM "stale results" subscribers.

**How to avoid**: Any function that calls `_helixCtrl?.revertToGeometry()` must guard:
```js
const { cadnanoActive, unfoldActive } = storeRef.getState()
if (!cadnanoActive && !unfoldActive) { _helixCtrl?.revertToGeometry() }
```

<a id="d2"></a>
### D2. Hiding the design requires touching all four scene-owning modules
Hiding requires `designRenderer` + `bluntEnds` + `endExtrudeArrows` + `jointRenderer`. Crossover arcs and extra-base beads need explicit `_crossoverGroup` handling.

**How to avoid**: See `feedback_design_renderer_visibility_rule.md`. There is no single visibility toggle.

<a id="d11"></a>
### D11. Display overlays MUST emit a loop-`copy` index, or loop-insert beads strand (2026-07-04)
A loop insertion places several nucleotides at ONE `(helix, bp, direction)`. `helix_renderer`
distinguishes them by a **`copy` index** (`_copySeenBB` = appearance order) and addresses every
bead/slab/cone position (`applyFemPositions`) and scalar colour (`applyScalarColors`) by the 4-part
key `helix:bp:dir:copy` — **there is no 3-part fallback for beads/slabs/cones**. Any overlay that
emits positions/colours keyed only by `(helix,bp,dir)` (or with no `copy`) aliases every loop
copy>0 onto copy 0 → the extra loop bases are never moved OR coloured and strand at their native
position. Hit the CanDo deform/flex/deviation toggles (`fem_solver.deformed_positions` had no
`copy`); **mrDNA `mrdna_runner._display_positions` still has this latent gap**; oxDNA's health/RMSF
path got it right (carries `copy`).

**The trap that hid it:** a coverage test asserting `{(helix,bp,dir)} == expected_set` COLLAPSES the
loop copies → passes while copies strand (false confidence). Assert over `(helix,bp,dir,COPY)` tuples
AND `len(positions) == total_nucleotides`.

**How to avoid**: emit `copy` = per-`(helix,bp,dir)` running counter over `nucleotide_positions`
order (verified identical to the geometry-endpoint order → matches `_copySeenBB`); frontend colour
keys use `helix:bp:dir:copy` (+3-part alias only for copy 0). See `project_cando_fem.md` (loop-copy fix).

<a id="d3"></a>
### D3. Plan B (lean fast paths) skips backend geometry
Cluster commits and seeks now skip the full backend geometry recompute and rebuild only what's affected. Anything derived from live anchors (e.g. ds-linker bridges) must be re-emitted explicitly via `/design/refresh-bridges`. Forgetting this leaves bridges stuck at their old positions.

**How to avoid**: When adding any anchor-derived geometry, wire it into `_confirmTranslateRotateTool` and `_applyClusterUndoRedoDeltas`.

<a id="d4"></a>
### D4. Bounding-box / centroid math silently inflated by zero-count InstancedMesh + hidden subtrees
`_computeGroupBox` in `assembly_renderer.js` had two bounding-box leaks that pulled the assembly selection BoxHelper (and the gizmo centroid, via `getInstanceCenters`) far past the visible part:

1. **InstancedMesh with `count === 0` fell through to the regular-mesh branch.** Three.js's `InstancedMesh` extends `Mesh`, so `obj.isMesh` is true even when `count === 0`. Code that only special-cases `count > 0` falls through to the `isMesh` branch and unions the **template** geometry's bounding box (e.g. an un-positioned fluorophore sphere at the instance origin). Visible as a minZ/maxZ pulled to the instance origin even when no instances exist.
2. **Visibility checked only on the leaf, not the parent chain.** Hidden parent groups (e.g. `_curvedCylGroup` with `visible=false` in straight-LOD mode) still had `visible=true` children whose own `visible` flag passed the check. The renderer correctly skips them (it walks the parent chain), but `traverse((obj) => { if (!obj.visible) return })` doesn't.

**How to avoid**:
- For InstancedMesh, bail explicitly when `count === 0`. Don't rely on falling through to the `isMesh` branch.
- Visibility filters that mirror the renderer must walk the parent chain (helper: `_isVisibleUnder(obj, stopAt)` in `assembly_renderer.js`). Same fix applied in `scene_inspector.js _allHittables` (`_isVisibleChain`).
- Same bug pattern likely lurks anywhere else iterating a subtree for spatial info (snapping, picking heuristics, label placement). Audit any `traverse` + per-leaf-`visible` combo.

Diagnostic: `window.__nadocBoxAudit(instanceId?)` (in `assembly_renderer.js`) dumps every mesh contribution sorted by extent and flags outliers reaching the global min/max along each axis. Use it any time the BoxHelper looks too big.

<a id="d6"></a>
### D6. Crossover arc-line visibility is driven by TWO decoupled concerns that overwrite each other (2026-05-26)
Crossover arc LINES live in `unfold_view._arcGroup` (toggled via `setArcsVisible`). Their visibility is set from two unrelated places in `main.js`: (a) **LOD** — `_setRepresentation`/the per-tick LOD handler call `setArcsVisible(lvl < 2)` so arcs hide in the coarse cylinders/sticks rep; (b) **design-visibility** — `_setCGVisible`/`_setDesignGeometryVisible` called `setArcsVisible(visible)` unconditionally whenever CG geometry is shown/hidden (assembly enter/exit, atomistic toggle, periodic-MD, re-entering a rep). The (b) calls ignored LOD, so ANY path that re-showed CG geometry while in cylinder rep re-showed the arcs — they then poked through the empty domain gaps of a gapped design (teeth.nadoc) which the cylinders used to occlude. The LOD-gated re-hide (`if (lvl !== _lastDetailLevel)`) is skipped on a same-level re-entry, so (b) won. SEPARATELY, the crossover extra-base **beads/slabs** are children of `_helixCtrl.root` and are NOT part of the helix LOD meshes, so `setDetailLevel(2)` never hid them either (irrelevant on teeth — 0 extra-base crossovers — but a real gap for loop/skip designs).

**Fix**: gate (b) on LOD too — `setArcsVisible(visible && _lastDetailLevel < 2)` in both `_setCGVisible` and `_setDesignGeometryVisible`. For beads/slabs, `design_renderer` now tracks `_detailLevel` and `_applyXoverExtrasLod()` hides the two InstancedMeshes at level ≥ 2, reapplied after every `_rebuild`. Verified in-app: re-entering cylinders kept arcs hidden (`afterReentry:false`); confirmed the bug reproduced un-fixed (`afterReentry:true`).

**How to avoid**: when a scene object's visibility depends on more than one piece of state (LOD × design-visibility × mode), compute it from ALL of them at every site that can change any one — don't let each concern blindly overwrite the flag. A toggle gated on "only when X changes" silently loses to an unconditional setter on the same flag.

<a id="d7"></a>
### D7. Curved-helix cylinders are open-ended TubeGeometry — uncapped ends read as dark holes / "disappear at angles" (2026-05-26)
In the cylinder LOD rep, STRAIGHT helices use `GEO_UNIT_CYL` (a capped `CylinderGeometry`, looks solid), but CURVED (deformed) helices render as individual `TubeGeometry` meshes in `_curvedCylGroup` (`helix_renderer.js _buildDomainTubeGeo`). `TubeGeometry` has **no end caps** — its open ends, with the non-overhang `FrontSide` material, show the unlit interior / see straight through to the background, so helix tips look like dark voids and curved-away ends "disappear at certain angles". This only manifests on DEFORMED designs (teeth.nadoc bent) — the straight path is fine. NOT a frustum-culling bug (those instanced meshes already set `frustumCulled=false`, and the tube geo is in world coords so its bounding sphere is correct). DoubleSide only half-fixes (the inner wall renders but is unlit → still dark).

**Fix**: cap full tubes — build two `CircleGeometry` discs oriented to the curve's start/end tangents (outward normals) and `mergeGeometries([tube, capA, capB])`. Keep `FrontSide` (caps occlude the interior like the straight cylinders). Half-tube overhangs (openAngle<2π) stay uncapped + DoubleSide. Verified in-app on bent teeth: tips render as solid colored discs.

**How to avoid**: `TubeGeometry`/`TorusGeometry`/open swept geometry never has end caps. If it represents something that should look solid, cap it or it'll read as hollow/see-through. Match the closed-geometry sibling's appearance (here the straight capped cylinder).

<a id="d8"></a>
### D8. opacity-0 transparent mesh with depthWrite:true is an INVISIBLE OCCLUDER → voids (2026-05-26)
The "portions of the cylinder disappear at certain angles" on bent designs was NOT the open-tube/caps issue (D7) — it was the deform cross-fade's **straight-proxy** cylinders. The renderer keeps two reps per curved helix: bent `TubeGeometry` meshes (`_curvedCylGroup`) and a straight-proxy `InstancedMesh` (`iCurvedHelixCylinders`), cross-faded by opacity (`reapplyLerp`/`applyDeformLerp` in `helix_renderer.js`). In the deformed view the proxy is faded to `opacity:0` — but its material still had `transparent:true, depthWrite:true`, so it kept **writing the depth buffer at the un-bent positions while being invisible**, z-rejecting the bent tubes behind it → angle-dependent voids. (The probe that nailed it: proxy `visible:true, opacity:0, depthWrite:true`. Toggling Help→Debug→Force-Opaque revealed the proxies as solid straight cylinders — opacity 0 is ignored once a material is opaque.) The bent tubes ALSO had the mirror smell: `transparent:true` at `opacity:1` → depth-sort artifacts among 100s of overlapping tubes.

**Fix**: `_fadeMat(mat, opacity)` sets `transparent = opacity < ~1` and `depthWrite = opacity >= ~1` at every cross-fade site (+ creation defaults: proxy `depthWrite:false` at opacity 0, tube `transparent:false` at opacity 1). So a faded-out mesh never occludes, and a fully-faded-in mesh is opaque (correct sorting). Verified: deformed rest proxy `{op0, depthWrite:false}` tube `{op1, opaque}`; straight view swaps; round-trip byte-identical.

**How to avoid**: whenever you fade a mesh with opacity, `depthWrite` MUST track it — opacity-0 + depthWrite-true is invisible-but-occluding. For any "geometry disappears behind nothing" artifact, suspect an invisible depth-writer in front. Classify fast with Force-Opaque (reveals opacity-0 meshes) — see [[#H5]].

<a id="d5"></a>
### D5. Shader-chunk variable redefinition when patching stock materials via onBeforeCompile (2026-05-22)
Sphere-impostor work (`impostor_material.js`, see `project_sphere_impostors.md`) patches a
MeshPhongMaterial by `.replace('#include <normal_fragment_begin>', ...)` to feed the impostor's
per-pixel sphere normal into Phong lighting. The first cut declared `vec3 geometryNormal = normal;`
inside that replacement → `ERROR: 0:895: 'geometryNormal' : redefinition`, VALIDATE_STATUS false,
beads didn't render. In the bundled Three.js version `geometryNormal` is declared by
`<lights_fragment_begin>` (which runs AFTER normal_fragment_begin), NOT by normal_fragment_begin
itself. The stock `<normal_fragment_begin>` defines only `normal` + `nonPerturbedNormal`.

**How to avoid**: when replacing a built-in shader chunk, define EXACTLY the variables the stock
chunk defines — no more. Don't assume `geometryNormal`/`nonPerturbedNormal` live in a particular
chunk; they migrate between Three.js versions. Diagnose by capturing console errors in a Playwright
test (`page.on('console', ...)`) — THREE dumps `Material Type` + the numbered shader + the GLSL
`ERROR: 0:LINE:` line, which pinpoints the offending injected line. The MeshPhysical chunk noise
(clearcoat/iridescence `#ifdef`s) in the dump is shared boilerplate, not evidence the wrong material
failed — check `Material Type:` at the top of the dump.

<a id="d9"></a>
### D9. Shared-renderer selection box built from mid-LOD CHORDS collapses for BENT parts (2026-06-10)
The SHARED assembly renderer (default since 2026-05-20) set each source's `instBoundingBox` from
`_computeLodLocalBox(midLod, overhangLod)` — the mid-LOD body cylinders. `_buildMidLodMesh` draws
**one straight cylinder per helix run, endpoint-to-endpoint** (the "farthest-apart endpoint pair").
For a part bent by a `bend` deformation (e.g. `Robot Arm/Arm_pulley_v1.nadoc`, ~167° arc → half-ring
torus) that chord cuts ACROSS the arc, throwing away the entire arc-bulge axis. Symptom: the Group-1
(or any part) selection box was a thin vertical slab that didn't bound the torus — drawn Z ≈ 6 nm vs
real ≈ 83 nm (proven via `_geometry_for_design` on the file: per-helix-chord box Z=4.5 nm vs full
nucleotide cloud Z=43 nm, 10×). The user suspected route-for-polymerization; it was INNOCENT (its 22
connector/bridge strands sit inside the part envelope) — the pre-existing bend was the cause. The
**per-instance** path (`?shared=0`) was NOT affected: its `getInstanceCenters`/`_computeGroupBox`
unions the real per-bp meshes, which follow the bend. So this was shared-path-only.

**Fix**: build `instBoundingBox` from the real per-nucleotide backbone cloud (`nucleotideLocalBox` in
`selection_bbox.js`, which FOLLOWS the bend), UNIONed with the LOD box (keeps the radial cylinder/
overhang poke + the "drawn slots only, no empty end padding" property that motivated the move off
`_computeSourceLocalBox`). Pure helpers + the geometry-fits-box validator `nucleotideBoxOverflow`
are unit-tested in `selection_bbox.test.js` (incl. a synthetic half-arc whose chord box collapses).

**How to avoid**: a selection/bounds box must be derived from the SAME geometry layer the user sees,
not a coarser LOD proxy. Any box built from per-helix or per-domain *chord* segments is wrong for
bent/curved parts even though it's fine for straight ones (which is why it shipped). When a box looks
too THIN (not too big — that's D4), suspect a chord/endpoint approximation missing mid-span curvature.
Validate with `nucleotideBoxOverflow(nucleotides, box)` — >0 means geometry escapes the box.

<a id="d10"></a>
### D10. Blunt-end rings float PAST the tip of a BENT helix — `physLen` from the chord, not `length_bp` (2026-06-12)
`domain_ends.js` positions each blunt-end ring by mapping its `diskBp` to a parametric `t` along the
(deformed) axis samples: `t = (diskBp − bp_start) / (physLen − 1)`. `_axisPoint`/`_axisDir` computed
`physLen = round(‖axis_end − axis_start‖ / RISE) + 1` — i.e. from the straight-line **chord** between
the endpoints. For a bent helix the chord is much shorter than the **arc** the samples trace (soup.nadoc:
chord 114 nm vs arc 140 nm for a 420-bp helix), so `physLen` read 343 instead of 421 → the far-end disk
`t = 420/342 = 1.23` overshot → the ring extrapolated **26 nm past the real bent tip** (the near-end ring,
`t ≈ 0`, was unaffected, so only the far/bent ends looked detached). The stored topology + the deformed
axes were CORRECT; only the disk→t mapping was wrong. PRE-EXISTING — the user reported it right after the
E6 deformation fix, but E6 only touches non-canonical helices and this design is all-canonical (verified:
my guard's deviation = 0 nm here).

**Fix**: `_physLen(h, dLen)` prefers the topological `h.length_bp + 1` (falls back to the chord estimate
only when length_bp is missing). For a straight helix chord == arc so the value is unchanged; only bent
helices are corrected. `t = 420/420 = 1.0` now lands the far disk exactly on `samples[-1]` (the tip),
error 0. Pinned by `frontend/src/scene/domain_ends.test.js` (`_physLen`, `_axisPoint` on a synthetic
90° L-arc whose chord-derived count would overshoot).

**How to avoid**: any bp↔position mapping along a helix axis must use the **bp count** (`length_bp` /
sample-index), NOT a distance/`RISE` derived from the endpoint chord — the chord ≠ arc the moment the
helix is bent. Same family as D9 (chord approximations are silently fine for straight, wrong for bent).

---

<a id="d11-2"></a>
### D11. Moving a cluster: the AXIS follows but BEADS/SLABS snap back — an inactive display overlay's `stopAndRestore` reverts geometry on every `nadoc:design-changed` (2026-07-08)
Symptom: drag/commit a cluster (Move/Rotate tool) → the helix **axis** moves to the new pose but the
**beads + slabs** stay at the un-posed position. Backend is CORRECT (geometry + `cluster_transforms`
reflect the move); the live *drag* is correct (`applyClusterTransform` moves beads); only the **commit**
reverts them. Root cause was NOT in the cluster/commit code at all: the LAMMPS display panel
(`lammps_jobs_panel.js`) subscribes to `window.addEventListener('nadoc:design-changed', …)` and calls
`_viewsOff()` → `lammps_display.stopAndRestore()`. That fired on the cluster commit (which broadcasts
`nadoc:design-changed` via `_signalDesignChanged`), and `stopAndRestore()` **unconditionally** ran
`_restore()` → `designRenderer.applyFemPositions(null)` → `helixCtrl.revertToGeometry()`, which resets
EVERY backbone bead to `currentGeometry.backbone_position`. With Plan-B `skipGeometry`, that array is the
STALE pre-move geometry → beads snapped to the un-posed position. The axis survived because it's rebaked
separately (`_rebakeHelixAxesForClusterDelta` / `currentHelixAxes`), and `design_renderer`'s own
visual-only-design-change early-return DID fire (so no full `_rebuild`) — the clobber came from a
*different* subscriber, a fired-later display overlay, not the renderer's rebuild path.

**Fix**: guard `stopAndRestore()` to no-op when nothing is displayed (`if (_mode === null) return`) —
matching the sibling displays that already had it (`oxdna_display` `!_active`, `cando_display`
`_mode===null`, `mrdna_display` `_deformJobId===null`). `lammps_display` was the ONE missing the guard.
Pinned by `frontend/src/ui/lammps_display.test.js` (stopAndRestore no-ops when inactive, reverts when
active — proven red without the guard).

**How to avoid**: any display/physical-layer overlay teardown that calls `applyFemPositions(null)` /
`revertToGeometry()` (the "restore the model" path) MUST be gated on the overlay actually being active.
An unconditional restore is a silent global-position clobber: it reverts EVERY bead to
`currentGeometry`, wiping any legitimate live pose (cluster move, drag preview) the renderer is holding.
Diagnosis technique that nailed it: a temporary `console.log(new Error().stack)` inside `revertToGeometry`
during the failing gesture pointed straight at the caller chain — do that BEFORE theorizing about the
cluster/commit code. Same family as the "late subscriber calls `revertToGeometry` and wins" rendering rule.

---

<a id="d12"></a>
### D12. Live Display-MD: a few crossover extra bases render a full box away — the design-eq PBC snap reused `rigid_mask`, which correctly excludes extra bases from Kabsch but wrongly excluded them from the wrap-snap (2026-07-11)
Symptom: toggle **Display MD** on a live NAMD run (small transverse box — e.g. 6hb, box x≈8 nm) and a
handful of nucleotides (4 on the 6hbx100_2xT job) sit ~41 nm (one full box in z) away from the structure,
every frame. The whole bundle is aligned correctly; only these few float off. They are all `__xb__` —
crossover **extra-base** inserts.

Root cause is in `_seek_sync`'s PBC pipeline (`backend/api/ws.py`). Step 1 sequential-unwrap
(`_unwrap_min_image`) makes strands whole but **resets to raw wrapped coords at each strand boundary**, so
the first atom of a segment can land in the wrong periodic image. Step 2 fixes that by snapping each atom
to the nearest periodic image of its **design-eq** position — but it applied this only to `rigid_mask`
atoms (`bp≥0`). `md_rigid_reference` deliberately keeps extra bases OUT of `rigid_mask` because they're
flexible and would bias the **Kabsch/centroid** rigid-body fit. That exclusion is right for Kabsch but was
silently reused as the **snap** membership, so extra bases (which DO have a valid, spatially-constrained
design eq) got no wrap correction and stayed wherever the unwrap reset dropped them.

**Fix**: split the two roles. New pure helper `md_snap_mask(p_order, eq_valid, rigid_mask) = (rigid | is_xb)
& eq_valid` in `atomistic_to_nadoc.py`; `_seek_sync` (both the bead and ballstick paths) uses `snap_mask`
for the design-eq snap membership while `rigid_mask` still drives the centroid median + Kabsch. Genuinely
free ssDNA tails (`bp<0` integer) stay OUT of the snap — their transverse swing can exceed the ~4 nm
half-box, so a whole-box snap would over-correct them onto the wrong image (the original reason ssDNA was
excluded — still valid, just doesn't apply to constrained extra bases). Verified on the live job through
the shipped helper: wraps>5 nm 4→0 every frame, max deviation 412 Å→22 Å (real thermal). Pinned by
`tests/test_atomistic_to_nadoc.py::TestMdSnapMask`.

**How to avoid**: a mask named for one purpose (here "rigid, for the rotation fit") is not automatically
the right filter for a different physical operation (here "has a trustworthy reference to snap wraps
against"). When a PBC/alignment step reuses an existing boolean mask, check that BOTH its inclusions and
exclusions are correct for the new use — extra bases and dsDNA share "constrained near design eq" (snap
both) but differ on "should drive the rigid fit" (Kabsch only dsDNA).

---

## E. Cluster / deformation edge cases

<a id="e1"></a>
### E1. Restricting arm-helices to a cluster broke deformation geometry (April 2026)
Branch `feature/cluster-default-split-deform` tried isolating cross-section arm helices to a cluster's subset. Tests passed but visuals broke because `arm_min_bp_start` shifted with the filter, placing deformation planes at wrong bp positions.

**How to avoid**: If revisiting cross-cluster deform isolation, do NOT filter the arm; instead override `relevant_ops` inside `_frame_at_bp` with explicit allowed-ops. Keeps centroid/frame from full arm; stops cross-cluster bleeding.

<a id="e2"></a>
### E2. ds-linker bridge offset disagreement (May 2026)
`_make_virtual_linker_helix` and `_emit_bridge_nucs` silently disagreed on bridge axis offset. The constant `_BRIDGE_PHASE_OFFSET = π` MUST match in both `_bridge_boundary_radials` and `_emit_bridge_nucs`.

**How to avoid**: When changing bridge-axis math, grep for `_BRIDGE_PHASE_OFFSET` and update every site.

<a id="e3"></a>
### E3. Relax loss with bridge offset baked in produces degenerate minima
Folding the bridge boundary offset into the relax loss creates a chord≈0 minimum that the optimizer prefers to the real solution. Loss must be chord-magnitude only.

**How to avoid**: See `project_overhang_connections.md`. Don't add offsets to the relax loss objective.

<a id="e4"></a>
### E4. Overhang rotation didn't reach the linker complement domain (May 2026, Bug 06)
`apply_overhang_rotation_if_needed` builds a synthetic ClusterRigidTransform whose `domain_ids` mask filters by the OH domain's *direction*. The Watson-Crick complement on the same helix has the OPPOSITE direction, so the mask excluded it. The OH backbone rotated correctly but the linker complement nucs (used as the bridge anchor in `_emit_bridge_nucs`) stayed at un-rotated positions — the bridge appeared at the pre-rotation location with no console error.

**How to avoid**: Any same-helix Watson-Crick partner (LINKER strand domains overlapping the OH bp range with opposite direction) MUST be added to `domain_ids` of the synthetic transform. See `apply_overhang_rotation_if_needed` in `deformation.py` and `tests/test_overhang_linker_rotation.py` for the regression net.

<a id="e5"></a>
### E5. patch_overhang's extrude resize assumed +Z helices (Bug 06)
`patch_overhang` has separate code paths for inline and extrude overhangs. The extrude path comment said "junction is at bp 0 of the dedicated helix" and resized `start_bp + new_length - 1` (FORWARD) or `end_bp + new_length - 1` (REVERSE). For −Z extrudes the axis is flipped to +Z but the junction is at the helix's HIGH bp end (local bp L−1). The old math grew the junction-side bp instead of the tip and the helix's `axis_end` migrated away from the junction, producing the doubled-crossover symptom on the user's screenshot.

**How to avoid**: Look up the junction bp from `design.crossovers` (the unique crossover whose half_a/half_b is on this helix); the tip is the other domain endpoint. Don't reason from `is_fwd` and `start_bp`/`end_bp` alone.

<a id="e6"></a>
### E6. A FREE-POSED helix with a `h_XY_{r}_{c}` id gets `grid_pos` back-filled → the geometry pipeline canonicalises its axis → a bend re-applies → it collapses to a 45° sheet (2026-06-11)
Symptom: placing a primitive (18hb) onto a BENT end via deformed continuation rendered the new bundle collapsed onto a single 45° row. Root cause chain: (1) `make_bundle_deformed_continuation` stores the new helices' axes at their *deformed* pose (along the bent direction, e.g. +X); (2) the **continuation** helices got `_N`-suffixed ids (cell already existed) → `grid_pos` stays None → fine; the **fresh** helices got clean `h_XY_{r}_{c}` ids → `Helix._recover_grid_pos` (model validator, runs on every load) **back-filled `grid_pos`**; (3) `effective_helix_for_geometry` → `_normalize_helix_for_grid` sees `grid_pos` and rewrites the axis to the canonical straight-along-+Z lattice pose (`z = bp_start·rise`), discarding the bent pose; (4) the active bend then re-applies on top → all fresh helices land on the same diagonal → "single 45° row". The data (helix `axis_start/end`) was CORRECT all along — only the deformed GEOMETRY derivation was wrong, because the normalizer assumed `grid_pos ⇒ canonical straight axis`, which is false for a deliberately-posed helix.

**Fix**: `_normalize_helix_for_grid` now compares the would-be canonical Z to the stored Z; if either endpoint deviates > 1 nm, it returns the helix UNCHANGED (the pose is authoritative). Canonical lattice helices store exactly that Z (deviation ~0) so they normalise as before — verified by the full backend suite staying green (2010). Pinned by `tests/test_deformed_continuation_pose.py`.

**How to avoid / diagnose**: when a deformed/posed structure renders wrong but the stored `axis_start/end` look right, suspect `effective_helix_for_geometry`/`_normalize_helix_for_grid` canonicalising a posed helix. `grid_pos` is NOT proof a helix is at its canonical straight lattice position — the id-pattern back-fill makes it lie. The 3-layer tell: topology/geometry data fine, deformed-geometry derivation wrong.

<a id="e7"></a>
### E7. Direct-overhang relax is UNDER-CONSTRAINED — the hinge is a free null-space DOF that the optimizer drifts / overshoots (2026-07-01)
Symptom: "Relax" on a direct (root-to-root / end-to-root) overhang connection rotated the cluster hinge too far / the wrong way, and wasn't idempotent (each click rotated the hinge further even though the tip↔root bond was already closed at 0.67 nm). Root cause: the solve has 3 DOF (2-DOF overhang swing about the driver root + 1-DOF cluster hinge) but ONE constraint (chord=target). A sweep proved the 2-DOF swing ALONE closes the chord at EVERY hinge angle (residual 0.0000 across ±40°), so the hinge θ is a null-space direction. The weak reg (`_THETA_REG_LAMBDA=1e-3`) couldn't pin it, and bounded scipy Powell drifted θ — it even returned a point with loss `2.6e-5` when its x0 (params=0) was `1.2e-9` (i.e. WORSE than where it started). The chord was always closed, so the visible artifact was pure hinge drift.

**Fix** (`backend/core/direct_relax.py`): don't trust a single Powell result on an under-constrained loss. Collect every seed's result PLUS the do-nothing `params=0`, then pick **lexicographically**: (1) least chord residual (within `_CHORD_ACCEPT_BAND_NM=0.02` nm of the best achievable), then (2) least total motion `Σparams²`. Makes it idempotent (already-closed bond → params=0 selected → no drift) and closes a fresh bond with the LOCAL swing, hinge ≈ still.

**Second overshoot (2026-07-01), the target itself**: even with min-motion, the solve drove the gap TO 0.67 nm (one backbone bond). But the gap can go BELOW 0.67 (closest approach ~0.2 nm here), and a two-sided `(chord−target)²` pulls a too-close bond back APART to 0.67 — rotating the hinge past closest approach. User intent is "minimize, floored at 0.67": only CLOSE a stretched bond, never back off a close one. **Fix**: one-sided strain `_stretch = max(0, chord − target)`; `_loss` and the selection residual both use it. chord ≤ target ⇒ zero strain ⇒ min-motion leaves it put (no back-off) and, closing a stretched bond, stops at the NEAR-side floor (first time it reaches target) instead of over-rotating to the far side. Also floor the 0-DOF translate branch (`chord_mag > target_nm`). Pinned by `test_relax_does_not_back_off_an_already_close_bond` (fixture `relax_2x2_closebond.nadoc`, chord 0.38).

**How to avoid / diagnose**: before tuning a relax that "moves too much", COUNT dof vs constraints. If a subset of DOF already satisfies the objective, the rest are null-space and a plain minimizer will leave them anywhere — no reg weight reliably pins them (too weak → drift, too strong → breaks the objective). Resolve redundancy explicitly (lexicographic min-motion / min-norm), and always include the do-nothing candidate so the solve is idempotent. Diagnostic that nails it: sweep the suspect DOF and check whether the objective residual stays ~0 across its whole range (flat null space). Shares the shared solver with `relax_overhang_binding` + `relax_duplex`.

**SUPERSEDED 2026-07-01 — the swing DOF is GONE.** `relax_direct_binding` was rewritten to the dsDNA-linker-bridge method (see `project_overhang_duplex_foundation.md`): NO overhang swing at all — only cluster kinematics (joint about its own axis / translate) bring the two roots to the duplex's natural span, then the duplex re-seats at the oriented midpoint, then a clash-avoidance rotation of the DUPLEX ONLY (driver `OverhangSpec.rotation`) about the root→root axis. With the swing removed the under-constrained null-space this lesson is about no longer exists (the joint maps 1:1 to the chord). The `swing_*` fields, `_stretch`/`_CHORD_ACCEPT_BAND_NM` min-motion machinery, and the one-sided floor are all gone; the method is TWO-SIDED (opens an over-compressed bond back to 0.67). Idempotent via re-seat-from-scratch + smallest-|θ|. The clash spin is DUPLEX-only (a prior attempt that spun the whole driven CLUSTER about the overhang axis was rejected by the user).

---

## F. Length / index conventions

<a id="f1"></a>
### F1. caDNAno `length_bp` is NOT physical extent
`length_bp` is the FULL caDNAno array length. `bp_start + length_bp - 1` lies hundreds of bp past the actual axis end. Code that divides or indexes into the active helix using `length_bp` is wrong.

**How to avoid**: Use `physical_length_bp` (or compute from axis), not `length_bp`. `resize_strand_ends` still has this bug — port the physical-RISE rebuild fix from `shift_domains`. See `project_domain_shift_feature.md`.

<a id="f2"></a>
### F2. bp_start has three conventions
Native, caDNAno, and hybrid each have different `bp_start` interpretations. Inline conversion math is error-prone.

**How to avoid**: Use `backend/core/bp_indexing.py` exclusively. Never re-derive these in caller code.

<a id="f3"></a>
### F3. `OverhangSpec.sequence` length can be shorter than the strand domain length (2026-05-13)
`patch_overhang` resizes the OH's *sub-domain* tiling when a new sequence length is assigned (last sub-domain absorbs Δ), but does NOT shrink the strand's overhang DOMAIN endpoints. So an OH can legitimately have `strand_domain.length_bp = 10` while `len(spec.sequence) == 8`: the user "filled" 8 of 10 positions and the remaining 2 (at the 3' end, since `sub_domain.start_bp_offset = 0` by convention) are unsequenced.

Symptom that bit us: the Connection Types tab's Sequence column rendered the linker complement as N×L even though the bound overhang clearly had a `sequence`. The renderer used `targetSeq.length >= length` as an all-or-nothing gate.

**How to avoid**: Don't treat OH `sequence` length as authoritative for strand-domain spans. Pad-then-RC: `seq.slice(0, length).padEnd(length, 'N')` then reverse-complement. The N's land at the 5' end of the antiparallel partner, which is correct. See `_linkerStrandSegments` in `frontend/src/ui/overhangs_manager_popup.js`.

<a id="f4"></a>
### F4. Overhang autodetect used per-HELIX scaffold coverage, missing cross-over tails (2026-05-19)
`autodetect_overhangs` (`backend/core/lattice.py`) skipped a staple terminal domain whenever `term_dom.helix_id in scaf_cov` — a per-HELIX membership test. But `_scaffold_coverage_by_helix` merges a helix's scaffold into ONE `(lo,hi)` range, so a staple free tail that crosses over onto a scaffold-bearing helix at a bp range *away* from the scaffold (e.g. `stap_36_331` in *Ultimate Polymer Hinge*: 5′ tail at bp 320–331 on a helix whose scaffold is at 116–127) was treated as "scaffold-covered, handled elsewhere" and never tagged. The two-pass design left a gap: Pass 1 (autodetect) = scaffold-FREE helices; Pass 2 (`_reconcile_inline_overhangs`) = terminals STRADDLING the boundary (its split branches only fire on partial overlap, guarded against fully-outside domains). A tail entirely outside scaffold on a partially-scaffolded helix fell between them.

**How to avoid**: Test scaffold coverage **per-bp**, not per-helix — does the terminal domain's `[lo,hi]` actually overlap the helix's scaffold range? Fixed by: (1) Pass 1 tags a terminal that's entirely outside the scaffold range (whole-domain overhang, no split); (2) Pass 2 skips entirely-outside terminals so its merge step doesn't strip Pass 1's tag. Also: detection (Pass 1) historically ran only on cadnano/scadnano IMPORT, not `.nadoc` load — `/design/load` + `/design/import` now run the full `autodetect_all_overhangs` (idempotent) so existing files self-correct. Regression: `test_autodetect_overhangs_tags_crossover_tail_outside_scaffold_range` + `_keeps_..._through_pass2` in `tests/test_lattice.py`.

<a id="f5"></a>
### F5. bp indices CAN be negative — a `\d+` regex silently drops negative-bp elements ("nothing happens") (2026-06-08, ISSUE-7)
Helices start as low as `bp_start = -17`, so a domain/end/crossover/loop-skip can sit entirely in the negative region. The cadnano editor encodes selectable elements as string keys (`line:{helix}_{lo}_{hi}_{dir}`, `end:`, `xo:`, `ls:`) and parses them back with regexes. Five parsers in `cadnano-editor/main.js` (the Delete path `onDeleteElements`, the extra-bases menu) used `(\d+)`, which does NOT match a leading `-`. So selecting a fully-negative-bp scaffold stub (e.g. `line:h_XY_0_0_-17_-6_FORWARD`) and pressing Delete parsed to `null` → the domain-selector set stayed empty → **no API call, no error, the strand just stayed**. The user reported it as "I can't delete these segments, nothing happens." Multi-factor: the same stubs were ALSO drawn off the left edge by `_fitToContent` (negative bp drawn at negative world-x with no `bp0` offset) — a real but secondary visibility bug fixed separately. NOTE the `erase` tool the symptom *looks* like is dead UI (no toolbar button / keybinding); the real delete gesture is select-tool → Delete key.

**How to avoid**: any regex extracting a bp/index from a string in this codebase must use `(-?\d+)`, never `(\d+)` — bp is signed. The fix extracted ALL build+parse of these keys into one tested module (`cadnano-editor/element_keys.js`, round-trip unit-tested with negative + zero-crossing cases) so the format and its parser can't drift and the negative case is pinned. When you see a "delete/edit silently no-ops on some elements but works on others," suspect a value-range the parser rejects (negative, zero, very large) before suspecting the API. `pathview.js` already had two CORRECT `-?\d+` parsers (drag handlers) with comments — the bug was the other parsers never got the same treatment.

---

<a id="h13"></a>
### H13. Believing a failing spec's NAME instead of reading its error (2026-07-13, ISSUE-14)

ISSUE-14 sat open for a week, ranked #2 in the queue and described as *"a console error fires while exiting
assembly mode; a prior partial fix (`d5be41c`) didn't cover this path; suspected stale-subscription /
dispose-order."* Every word of that diagnosis was invented, because the spec is *called*
`exiting assembly mode tears down cleanly (no console error)`. Nobody had read the failure.

**What was actually happening:** the spec died in the shared e2e harness (`scene_harness.js`) during **setup**,
at `design.helices[0].id` with the design undefined. It never reached assembly mode at all, so the
console-error assertion it was blamed for never executed. The teardown code — where the dossier explicitly
told a future session to go looking — was never broken; `d5be41c` had fixed it properly.

Two root causes, both in the harness, both trivial once seen:
1. **A fixed sleep pretending to be a wait.** `await page.waitForTimeout(500)` after File→New. The welcome
   screen hides as soon as the *page* has a design, but the creating POST may still be in flight; on a cold
   smoke backend it lands later than 500 ms. `page.request` then hit the doc before it had a design →
   **404 "No active design."** → every downstream call collapsed. Fixed with `expect.poll` on
   `GET /design` == 200. **A fixed duration is never a wait for backend state — poll the backend's own view.**
2. **A dead route 405-ing into its fallback for a month.** `POST /design/auto-scaffold` was consolidated into
   `-seamed`/`-seamless`/`-matched` by `e9d6750` (2026-06-08), which never updated the harness. It had been
   returning **405 Method Not Allowed** ever since, silently falling through to a `scaffold-domain-paint`
   fallback that happens to work — so nothing looked wrong. Removed; the fallback is now the primary path.

**The two tells that were on the page and got ignored:** (a) it surfaced during a **backend-only** CanDo change
— a frontend teardown bug *cannot* be caused by a backend-only diff, which alone should have redirected the
search; (b) a partial fix already existed, which made "incomplete fix" the comfortable, available story. A
plausible narrative beat the evidence.

**How to avoid:** open `test-results/<spec>/error-context.md`, or just re-run the single spec, **before**
writing any diagnosis into a dossier. If you haven't, write "not diagnosed" — an invented root cause is worse
than none, because it aims the next session at the wrong file and lends the wrong file false credibility. The
whole real diagnosis here took ~5 minutes with an instrumented probe spec that printed each API call's status.

**Second-order finding (same session):** with the harness fixed, the heavy browser specs *still* timed out —
because a production NAMD job was eating ~5.5 of 12 cores (load ~10). The failure **moved between specs**
run-to-run, which reads as a flaky app but is pure CPU starvation. `just smoke` now refuses to run under a live
sim (`scripts/sim_guard.py`, reusing `hardware.heavy_sim_running()` — the same detector as the pytest guard).
It fails **loud** rather than skipping: smoke is a *commit* gate, and a silent skip is no gate at all.
Override with `NADOC_IGNORE_SIM_GUARD=1`. **A red gate on a loaded box tells you about the box, not the code.**

---

## I. Assembly FK propagation in resolve / multi-mate chains

<a id="i1"></a>
### I1. Rigid-group BFS expansion preempts per-joint snap in a chain (2026-05-16)
`resolve_assembly`'s rigid-snap branch in `backend/api/assembly.py` originally called `_fk_expand_rigid_group(child_id, snap_T, fk_vis, [])` after snapping `inst_b`. That helper BFS-walks the rigid-joint graph from `child_id` and applies `snap_T` to every rigid neighbour, adding them to `visited`. In a chain of `N` rigid mates (e.g. `Hinge Polys.nass`'s polymer of 17 hinges with shared connectors), this added instances 3..N to `visited` after processing the first joint, and the main BFS then skipped every subsequent rigid joint via `if child_id in visited: continue` — only the first snap ever happened. User-visible symptom: clicking Resolve adjusted the assembly "slightly" but did not snap every mate.

**How to avoid**: in a per-joint constraint loop (not a "this is one rigid body" group-move), DON'T expand the rigid group. Snap `inst_b` alone, update its `base_transform` for downstream revolute children, and only call `_fk_propagate` (which walks non-rigid joints only). Each successive rigid joint in the chain then snaps independently with its own residual.

---

<a id="f7"></a>
### F7. Crossover extra bases render on their neighbour's coordinates — insert index vs arc direction (2026-08-01)

SYMPTOM: during a live NAMD run (`2hb_2xT`), the backbone beads + slabs of a yellow staple's extra bases sat visibly wrong compared to the ball-and-stick view of the *same frame*. Only some crossovers; the rest of the structure was fine.

NOT the backend. Replaying `ws.py::_seek_sync`'s bead path against the live DCD and diffing each `__xb__` bead against the same P atom in the ball-and-stick path gave **0.0000 nm** — the server sends exactly the atomistic coordinate. `p_order` mapped 95/95 with 0 unmapped and no duplicate design keys, and both paths shared one Kabsch rotation. When a CG overlay disagrees with atomistic, prove the *server* frame first; it collapses the search space by half in one script.

ROOT CAUSE: two conventions for "insert k", never reconciled.
- **Emitters** number a run **5′→3′ from `src`** — the half sitting at a domain END (`domain_end_to_strand`; `atomistic.py:2795-2802`, `oxdna_interface.py:394-403`). `src` is `half_b` whenever the strand enters that junction from the B side.
- **Renderer** lays beads along the Bézier `half_a → half_b` and wrote sim-k straight into `beadStartIdx + k` (`crossover_connections.js`, `design_renderer.js`).

They agree only for A→B strands. `2hb_2xT` has one crossover of each direction — the A→B one looked perfect, which is exactly why this survived: a design where every crossover runs the same way shows nothing. On the reversed one each TT bead landed ~0.63 nm off (≈2 bp rises) and the connector cones crossed. The `__xb__` **RMSF/scalar colours** were swapped by the same assumption. `forced_ligations` were always immune — their wrapper assigns `half_a = 3′ side` by construction, which is the fix, applied at build time.

**How to avoid**: an insert index is meaningless without its direction convention. When one module numbers a run and another positions it, the ordering rule must be *stamped on the shared record* (here: `simReversed` on `arcData`), not re-derived independently at each site — there were **three** k↔bead sites and all three were wrong the same way. Prove the chain from the artifact, not from the design: the PSF's own `O3'→P` bonds settled the traversal in one query where domain arithmetic would only have been an argument. See [[project-oxdna-extra-bases]] ("THE INSERT-ORDERING LAW"), and D12/F6 for the two earlier bugs in this same key-convention family.

---

## G. Disabled / deferred functionality

<a id="g1"></a>
### G1. Advanced staple router is disabled
The thermodynamic global optimizer (`staple_routing.optimize_staples_for_scaffold`) was too slow and caused timeouts. `auto_staple_route` (`backend/api/crud.py:5853`) falls back to `make_nicks_for_autostaple` when `algo='advanced'` is requested. The module + `build_scaffold_index_map` are intact — only the call site is bypassed.

**How to avoid**: Don't re-enable until the optimizer's perf is fixed. Don't delete `staple_routing.py` thinking it's dead code.

---

## H. Anti-patterns I've fallen into

<a id="h1"></a>
### H1. Guessing at the user's intent without asking
The user has corrected this repeatedly. When a request is ambiguous, the right move is one short clarifying question, not a plausible implementation.

**How to avoid**: See `feedback_interrupt_before_doubting_user.md`. Especially: do not preemptively "fix" something the user has just observed.

<a id="h5"></a>
### H5. Don't screenshot-guess camera angles for 3D rendering bugs — use the in-app debug toggles (2026-05-26)
Diagnosing an angle-dependent "weird mesh" artifact by blindly orbiting a Playwright camera and screenshotting burns many round-trips and usually can't reproduce the user's exact view. Built **Help → Debug** render diagnostics (`main.js`, ids `menu-debug-{wireframe,doubleside,opaque,inspect,copy-camera}`): **Wireframe** (geometry vs shading), **Force Double-Side** (back-face culling vs not), **Force Opaque** (transparent depth-sort vs not), **Inspect Mesh** (click → console.table of material.side/transparent/opacity/depthWrite/geometry/frustumCulled), **Copy Camera** (pos.xyz,target.xyz → clipboard). Toggles save originals in `material.userData._dbgOrig` and restore; reset on a full rebuild. The probe instantly confirmed the curved-tube `transparent:true @ opacity:1` smell.

**How to avoid**: for any rendering artifact, FIRST classify with these toggles (one click each rules out a whole cause-class), and ask the user for **Copy Camera** output to reproduce their exact view — don't iterate screenshots at guessed angles. To reproduce a pasted camera in Playwright: `__NADOC_DBG__.camera.position.set(...)`, `__NADOC_DBG__.controls.target.set(...)`, `controls.update()`. Load a design through the UI (`.lib-file-row` click), NOT `api.loadDesign` alone — the latter populates the store/scene but leaves the landing page covering the canvas so screenshots show the file browser.

<a id="h2"></a>
### H2. Searching the codebase for ages instead of asking
Open-ended exploration ("investigate why X is happening") burns context and often misses the real cause. Better: ask the user for the specific symptom or repro, then narrow.

**How to avoid**: Default to focused grep / Read with a hypothesis, not breadth-first exploration.

<a id="h3"></a>
### H3. Restating diffs after editing
The user can read the diff. End-of-turn summary should be one or two sentences max — what changed, what's next.

**How to avoid**: One sentence per update. Stop talking when the work's described.

<a id="h4"></a>
### H4. Blur-commits race click-handlers (2026-05-13)
An input that commits on `blur` via `await patchOverhang(...)` and a button whose click handler does `await api.createOverhangConnection(...)` are independent async chains. Clicking the button while the input is focused fires `blur` *and* `click` in quick succession; both fetches go in flight and the response resolution order is non-deterministic.

Symptom: user types into a side input, clicks Generate Linker without Tab-ing out. The linker is created against not-yet-committed overhang sequences and downstream renders see stale state.

**How to avoid**: when a button-click handler depends on the latest value from a still-focused input, force-commit BEFORE the action — read `input.value`, diff against the stored value, and `await patchOverhang(...)` synchronously inside the click handler. Trusting the browser's blur-first order isn't enough because the two promises still race.

<a id="h6"></a>
### H6. Async-commit list rebuild steals focus from a number box → typed digit leaks to global hotkeys (2026-05-30)
Symptom the user reported: "number hotkeys (1–6: autoscaffold/autobreak/…) fire while I'm entering numbers for keyframe trans/hold values." Both guards on the digit shortcuts were already correct — the dispatcher's `blockedInInput` (`shortcuts.js`) AND `_numInput`'s `e.stopPropagation()` — so a *focused* `<input type=number>` never leaks (proven with a Playwright synthetic repro: `docDigit=0`). The leak needs the box to NOT be focused. Real cause: `animation_panel.js` rebuilds its whole keyframe list on every `design`-slice change (`store.subscribeSlice('design', … _rebuildSelect)`). Editing trans/hold commits via **async** `updateKeyframe` → store update → `_rebuildKfList` recreates every `<input>`. Editing boxes in sequence (commit box A by clicking box B) lands A's async rebuild a moment later, **destroys the focused box B**, drops focus to `<body>`, and the next digit hits the routing menu (proven: `docDigit=1`, `activeElement=BODY`). Drag-scrub was a **red herring** — removed at user request, but its `setPointerCapture`/click-`preventDefault` did NOT break focus (synthetic test: click still focuses). Fix: defer the list rebuild while `kfListEl.contains(document.activeElement)`, flush it on `focusout` once focus leaves the list.

**How to avoid**: any panel that (a) recreates input DOM on a store/`subscribeSlice` change and (b) commits a focused field via an async round-trip can silently steal focus mid-edit. Treat "global keyboard shortcut fires during text/number entry" as a **focus-loss** symptom (check `document.activeElement` at the keypress), not a missing input-guard — the guard is usually already there. Sibling of H4 (blur-commit races); same root, different surface.

<a id="h7"></a>
### H7. Do NOT try to verify 3D pointer-selection by simulating canvas clicks in Playwright (2026-05-31)
Burned a long session trying to confirm a new click-to-select drill feature (cluster→strand→domain→bead) by driving the 3D canvas with Playwright. It cannot be done in this app's headless setup, and each path fails for a *different* reason, so it looks like a feature bug when it isn't: (1) `page.mouse.move/down/up` does **not** emit `pointerdown`/`pointerup` — the `selection_manager` listens for **pointer** events, so a probe listener on `#canvas` counted `down:0, up:0`; (2) a synthetic `PointerEvent` dispatched to `#canvas` **does** fire the listener (probe counted 5), but the handler's internal `raycaster.setFromCamera(...).intersectObjects(beadMeshes)` still resolves **no hit** headlessly — even though an identical raycast I ran in-page at the same pixel **did** hit a bead. Net: even pre-existing basic strand-selection can't be driven this way, confirming it's a harness limitation, not the code. I should have pivoted after the first 1–2 null results instead of running ~10 diagnostics.

**How to avoid**: never verify a 3D click-selection feature via simulated canvas clicks. Two real options: (a) drive selection through the exposed programmatic API — `window._nadocDebug.selectionManager.selectStrand(id)` / `.selectNucleotide(nuc)` (this is what the passing `dsdna_linker_selection.spec.js` does), asserting on `store.selectedObject`; or (b) hand the user a numbered manual smoke test (per `feedback_user_todo_smoke_tests`). Only the *non-interactive* surface (button DOM/placement, store wiring, projection math) is Playwright-verifiable. Concrete env facts in `REFERENCE_PLAYWRIGHT.md` ("3D-canvas interaction" pitfalls).

<a id="h8"></a>
### H8. A NEW autoscaffold return-path shipped tests-green but regressed the seamed contract (no seams, no end-extension) (2026-06-26)
Wired a `route_hinge` path into `auto_scaffold_seamed` to route one strand through forced-ligation hinge gap-bridges. Full suite stayed green (3219) and a dedicated `test_hinge_router.py` passed, yet the USER caught a major regression in-app: the "seamed" option produced a **seamless single-pass raster** — zero mid-helix seam (double) crossovers AND zero scaffold-end extension, so crossovers sat at the bare staple edge, violating the hard-won "≥3 unpaired ssDNA bases beyond the staple-domain bound before any crossover" invariant. Root causes the regression slipped through:
- **`validate_design` does NOT encode routing-quality invariants** (no seam check, no end-extension check, no ssDNA-margin check). So "validator passes" — which my tests leaned on — proves topology sanity, NOT convention compliance.
- **The invariants are pinned only in PATH-SPECIFIC tests** (`test_seamed_router`, `test_section_router`). There is NO property test asserting "every autoscaffold ENTRY POINT's output has seams + extended ends + ssDNA margin", so a brand-new return path had no guardrail.
- **The existing FL guardrails passed vacuously**: `test_seamed_autoscaffold_preserves_hinge_forced_scaffold_anchors` / `..._does_not_place_hinge_xovers_on_manual_anchor_strands` only passed because `route_hinge` returned `None` on THEIR fixtures (not clean hinge pairings) → the OLD path ran. The new path triggered only on designs no test fed it.
- **My new tests asserted EXISTENCE** (1 strand, full coverage, FLs traversed, validator passes) **not the seamed CONTRACT**. Tests confirmed the code did what I designed — not that the design was correct.
- Shipped behind a self-declared "NOT VERIFIED IN APP" caveat. For routing (a known *tests-pass-but-visually-wrong* area) that caveat is a BLOCKER, not a footnote.

**How to avoid**: (1) Treat scaffold-routing invariants as a reusable, asserted contract — a `scaffold_routing_invariants(design)` checker (seams present for seamed; every scaffold crossover has ≥3 ssDNA beyond the abutting staple bound; no exposed staple ssDNA at scaffold ends) reused by a property test **parametrized over EVERY autoscaffold entry point** (seamed/matched/seamless/section/+any new path). A new path must be added to that test before merge. (2) Never accept `validate_design().passed` as sufficient for routing quality — it's a topology sanity check. (3) For any change that adds a new return path to an existing entry point, find the entry point's existing contract tests and confirm they actually EXERCISE the new path (not fall back). (4) Honor the in-app gate for routing — don't ship behind "NOT VERIFIED IN APP". Reverted same day; see [[project_hinge_autoscaffold]].

### H11. 1-nt-strand end-selection: same "which end is 5′/3′" defect lived in THREE parallel code paths — fixing one and claiming done left the user still stuck (2026-07-10)
A 1-nt strand's single nucleotide is **both** the 5′ and 3′ terminus (`is_five_prime && is_three_prime`), so any "which end did the user grab?" logic that derives the end from bp-position resolves it to 5′ — and a stub pinned on its 5′ side (by a crossover / design edge) becomes unresizable. The user asked to pick the *resizable* end. I added `oneNtResizableEnd` and wired it into the **3D end-extrude arrows** ([end_extrude_arrows.js](frontend/src/scene/end_extrude_arrows.js)) — tests green, declared done. But the user resizes in the **cadnano 2D editor**, a completely separate path, where the same defect existed in *two* places: `_hitTest` (`(isFwd && bp===lo)||(!isFwd && bp===hi) ? '5p':'3p'` → always 5′ when lo===hi) **and** `_resolveEndDragEntries`, which *re-derives* the end from bp-position and silently **overrode** any upstream choice (the end-key is bp-based and can't encode 5′-vs-3′ when both coincide). Fixing only `_hitTest` would still fail because `_resolveEndDragEntries` runs last and wins.

**What cost the cycle**: (1) assumed one UI == one code path — there are two resize UIs (3D arrows + 2D editor) with independent end-picking, plus the 2D path itself splits hit-test vs drag-entry resolution. (2) Verified the pure helper + the 3D path, not the surface the user actually uses. (3) Didn't grep for **all** sites that convert (domain, bp) → 5′/3′.

**How to avoid**: (1) When a concept ("which terminus") is computed in more than one place, `grep` every site (`is_five_prime`, `bp === lo`, `? '5p' : '3p'`, `endWhich`, `end: '5p'`) and fix/route them all through the one shared helper — put it in `shared/` so both the scene and cadnano-editor import the SAME function. (2) A bp-based end-key can't distinguish coincident ends — the disambiguation must happen wherever the end is (re)derived, including any late "resolve entries" step that recomputes it. (3) For a resize/drag fix, verify against the UI the user names, not the first one you find. Fix: `oneNtResizableEnd` in [shared/strand_end_resize.js](frontend/src/shared/strand_end_resize.js), used by the 3D arrows AND pathview `_hitTest` + `_resolveEndDragEntries`.

## J. Algorithmic search hangs

<a id="j1"></a>
### J1. Unbudgeted recursive Hamiltonian-path DFS hangs on large bundles — "autoscaffold never completes, no error" (2026-06-01)
Symptom the user reported: applying autoscaffold to a 66-helix design (`workspace/Robot Arm/Shaft_v1.nadoc`) hangs forever with no error output. The "Autoscaffold" menu opens the seamed/seamless picker whose **default** is Seamed → `auto_scaffold_seamed`, whose first step is `_hamiltonian_path` ([backend/core/seamed_router.py](backend/core/seamed_router.py)). That DFS (and seamless's `_ham_path_ending`, and `_advanced_hamiltonian_path`) had **no time/visit budget and no pruning** — on a sparse ~66-node honeycomb-tube graph the search tree is exponential, so it never returns. The request never completes → no HTTP response → frontend progress spinner sits forever. The plain `/design/auto-scaffold` CSP router was fine (it has `max_backtracks`); only the seamed/seamless Hamiltonian step hung. Diagnosed with `faulthandler.dump_traceback_later(25, repeat=True)` around the call — the stack dump pinned the process inside the recursive `dfs`.

The structure was actually **routable** (single Hamiltonian path → single scaffold strand). The naive DFS just wandered through astronomically many dead branches before it could reach the valid path. Fix: shared budgeted + **admissibly-pruned** DFS `_ham_path_search` (connectivity check: remaining subgraph must be connected and reachable from the current end; degree check: ≤2 remaining nodes may have a single unvisited neighbour). Pruning only cuts branches with provably no completion, so for solvable graphs the first path found is identical (teeth.nadoc / 10-6-10 golden tests unchanged). After the fix the Shaft routes in 0.3 s.

**Trap that cost a cycle**: the connectivity/degree prune must special-case `len(remaining) == 1`. The single last node has remaining-degree 0 (no other remaining nodes), so a blanket `if deg == 0: return False` rejects the **final step of every path** → the search concludes "no Hamiltonian path" for *every* graph. I had the same bug in my throwaway feasibility-check script, which made me briefly (and wrongly) conclude the Shaft had no Hamiltonian path at all. If a pruned Ham-path search reports "no path" on a graph you expect to be routable, suspect the `|remaining| == 1` terminal case first.

**How to avoid**: any recursive exhaustive search over a backtracking tree (Hamiltonian path/cycle, CSP, etc.) needs a visit/time budget so a hopeless or pathological instance fails gracefully instead of hanging — mirror the CSP router's `max_backtracks`. Treat "operation hangs with no error" on a large design as an **unbounded-search** symptom; confirm with a `faulthandler` stack dump rather than guessing.

<a id="j2"></a>
### J2. Full-autostaple "No complete legal breakpoint path" 422 on large/dense designs = crossover-break gating, not a real dead-end (2026-06-02)
Symptom: `POST /design/full-autostaple` 422s with "No complete legal breakpoint path for precursor(s): ..." on a 66-helix (6×11 HC) design, while 18HB works. Reproduced identically for seamed AND matched scaffold routing (so it's NOT the scaffold router). Root cause is a constraint conflict in the Aksel breaker ([backend/core/staple_scoring.py](backend/core/staple_scoring.py)): auto-crossover packs crossovers at the dense HC lattice spacing (~7 nt), so along the giant serpentine staple precursors most inter-crossover runs are <14 nt; `_candidate_break_offsets` forbids an internal break within `min_segment_nt`(=7) of a crossover on BOTH sides, so runs <14 nt yield ZERO legal internal breaks. That leaves long stretches (measured 84 nt) with no legal break — but max staple = 60 nt — so no legal tiling exists. Diagnosis tool: `build_precursor_graph` + `_top_k_paths` per precursor; count inter-crossover run lengths and gaps between legal break offsets (a gap >60 is fatal). **Fix:** break AT crossovers — `allow_crossover_breaks=True` flips 8/87 unroutable precursors to 0/87. `apply_precursor_breaks`' `make_nick` at the crossover boundary correctly splits the staple, and the existing `_prune_circularizing_crossovers` + `_assert_no_circular_staples` keep it clean (validate passes, 0 unligated, no circular). Done for full-autostaple only (forced `allow_crossover_breaks=True` in `full_autostaple_endpoint`); the `_validate_aksel_break_body` gate still rejects it for the standalone auto-break/route-aksel endpoints (the gate's "not yet supported by topology" comment is now stale — make_nick handles it). **Separate finding:** matched-ends scaffold + full-autostaple yields 4–8 staple length violations (seamed yields 0) — an interaction between matched's ragged extended ends and the 21–60 nt staple window, NOT caused by the crossover-break fix. Stale tests: `test_staple_scoring.py::{test_auto_break_aksel_completes_after_autocrossover_on_18hb, test_auto_route_aksel_completes_on_18hb}` assert 18HB should 422 — it now routes (200); `test_precursor_graph_..._honeycomb_segment_minimums` similarly stale.

<a id="j3"></a>
### J3. Auto-crossover edge margin was 21 nt (min STAPLE), should be min SEGMENT — and must be measured vs the staple's true coverage, not the helix end (2026-06-02)
Symptom: auto-crossover + full-autostaple leave ~14-20 bp at each helix end uncrossed. Cause is ingrained, not a parameter: a hardcoded `21` (min staple length) edge margin in TWO places — the standalone `auto_crossover` endpoint and `_build_auto_crossover_design` ([backend/api/crud.py](backend/api/crud.py), the `_terminal_fragment_too_short` / `_MIN_AUTOCROSSOVER_*` checks). It skipped any site whose terminal fragment was <21 nt. Correct rule (user): place all crossovers except those creating a sub-lattice-min SEGMENT (7 HC / 8 SQ). **Trap:** naively lowering 21→7 measuring against the HELIX END (`helix.bp_start..bp_start+length-1`) creates 3-4 nt arms, because near the bundle caps the SCAFFOLD occupies the last bp, so the staple strand ends BEFORE the helix does (e.g. staple ends at bp 387 while helix runs to 396) — a crossover that looks ≥7 from the helix end can isolate a 3 nt arm vs the true staple end. The old 21 margin masked this. **Fix:** measure the arm against the STAPLE STRAND's actual coverage interval from `build_strand_ranges(...)` (`sr[(helix_id, staple_dir)]`, the interval containing `lower_bp`), not the helix range — skip only if a side is `0 < len < min_seg`. Result: crossovers placed right up to true 7/8 nt arms, min_segment=7 exactly, zero sub-7 arms; short STAPLES (<21 nt total) still appear and are accepted (per user) — distinct from short SEGMENTS. Tests asserting `length_violation_count==0` were relaxed to "short staples OK, but `min(segment_lengths) >= 7`". Side effect: denser crossovers made standalone auto-break/route-aksel (crossover-breaks OFF) 422 on 18hb again, so `test_auto_*_aksel_completes_on_18hb` (which expect 422) pass again; `test_precursor_graph_..._honeycomb_segment_minimums` still stale (asserts 18hb has incomplete precursors; all 167 now route).

<a id="j4"></a>
### J4. Staple breaks must clear interior (seam) scaffold crossovers by 7/8 bp — breaker had no scaffold awareness (2026-06-02)
The Aksel breaker's `_candidate_break_offsets` only keeps breaks >= min_segment from STAPLE crossovers/termini (the staple route's own nodes); scaffold crossovers live on the opposite strand and were invisible, so nicks landed 1-6 bp from scaffold seam crossovers (29 such on the Shaft). Fix in `backend/core/staple_scoring.py`: `interior_scaffold_crossover_positions(design, min_seg)` returns per-helix bp of scaffold crossovers that sit > min_seg INSIDE the scaffold coverage on that helix (position-based "interior" = seam/mid-helix, excludes near/far-end CAP crossovers which sit at the coverage extremes — user chose position over process_id for routing-robustness). `build_precursor_graph` takes `scaffold_block=` and drops any internal break offset whose `route[off-1].bp` is within `rule.min_segment_nt` of a blocked position (precursor termini at offset 0/n are kept — they're fixed, not breaker choices). Threaded from `apply_precursor_breaks` + `build_precursor_graphs`. Result on Shaft: 29 -> 1 breaker-chosen violations eliminated; the lone remainder is a PRECURSOR TERMINUS (a staple's natural 5'/3' end, at dist 6) forced by the scaffold's seam coverage-split + the `scaf_margin=7` that keeps staple crossovers off the seam — not a breaker decision, would need auto-crossover/precursor-gen changes to remove. Regression test `test_full_autostaple_keeps_breaks_clear_of_seam_crossovers` (fresh 18HB-seamed, asserts 0 internal breaks within min_seg of an interior scaffold xover). No new suite failures (1695 pass / 3 pre-existing).

<a id="j5"></a>
### J5. A scaffold-router test that flaps pass/fail run-to-run is hash-seed set-iteration order, NOT a cross-test state leak (2026-06-08, ISSUE-6)
`tests/test_seamless_router.py::test_teeth_closing_zig` was a long-standing "known flake" (carried in REFACTOR_AUDIT.md's `KNOWN_FLAKES`); the ledger had diagnosed it as a cross-test global-state leak and prescribed a reset fixture. **Wrong.** The tell: it fails/passes in a *single fresh pytest process with no other test running* — pin/fail is deterministic for a fixed `PYTHONHASHSEED` and varies across seeds (≈30% gave 4 scaffold strands, ≈70% gave 5). A state leak would be order-dependent *across tests*, not seed-dependent *within one process*. **Root cause:** the shared `_hamiltonian_path` ([backend/core/seamed_router.py](backend/core/seamed_router.py)) sorted candidate helices by degree only — `sorted(ids, key=lambda n: len(adj[n]))` — with no tiebreaker, so equal-degree helices fell out in `set`-iteration (hash-seed) order → different Hamiltonian path → different scaffold-strand count. (A 2026-06-01 refactor — see [[J1]] — routed teeth through this shared search and dropped the `(len(adj[n]), n)` tiebreaker that `seamless_router._ham_path_ending` already had; a standing FIXME named it.) **Fix:** add the `(len(adj[n]), n)` lex tiebreaker to BOTH the starter sort and the neighbor key. Verified deterministic across 13 seeds. **Second, subtler trap:** the tiebreaker alone made it deterministic at **5** strands — the test asserted **4**, so "just add the tiebreaker" still left it red. The real defect was the *assertion*: `auto_scaffold_seamless` is an INTERMEDIATE stage (it places crossovers; a fully-routed scaffold is later ligated to 1 strand), so the count of leftover scaffold pieces is a path-ordering artifact, never an invariant. The test is named for the *closing-zig crossover event*, which I confirmed fires in BOTH the 4- and 5-piece orderings — so the count never even measured the intent. Re-pinned the test to the topological events (`bridge_xovers==6`, no warnings, closing-zig crossover `h_XY_2_2↔h_XY_2_3` present), matching the process-count style of every other test in the file. **How to avoid:** (1) any code that iterates a `set`/`dict`-keys and the *order* affects the output (path choice, "pick first", tie resolution) must sort with a total-order tiebreaker — degree/score-only keys are a latent hash-seed flake. (2) When a test flaps, run it ALONE in a fresh process across a few `PYTHONHASHSEED` values *before* assuming a cross-test leak — single-process seed-variance ⇒ algorithmic nondeterminism; cross-test-order-variance ⇒ state residue. (3) Don't assert absolute counts of an intermediate-stage artifact; assert the topological event the stage is responsible for.

<a id="j6"></a>
### J6. Autostaple starves crossovers at INTERIOR ssDNA loops — a staple's global coverage *span* is not a terminus test (2026-07-13, `workspace/teeth.nadoc`)
**Symptom:** after full-autostaple on a comb/"teeth" design, the 4-row-thick teeth have ~60% of the spine's crossover density; whole neighbour pairs sit at 2 crossovers where 6 sites are legal. **The design is correct** — the teeth are defined by *interior* ssDNA scaffold loops (bp 32–39, 96–103, … on the lower-row helices), which are deliberate anti-blunt-end-stacking features. **Root cause:** `_place_auto_crossovers._coverage_hole` ([crud.py](../backend/api/crud.py)) asked whether an unstapled bp fell inside the slot's **global `[min, max]` staple span**; inside ⇒ "accidental hole" ⇒ reject, outside ⇒ "5'/3' terminus at the bundle cap" ⇒ allow. That heuristic is only sound when every ssDNA loop is at a helix end. With interior loops the span straddles them, so every loop read as an accident — while the *identical* physical site at a bundle cap was allowed (pair (2,0)–(2,1) got its bp-159 crossover but not its bp-31 one; same bow, same ssDNA neighbour, opposite verdict). **Fix:** replace the span test with the bow-side rule manual placement already uses (`_build_place_crossover`): a crossover connects material on the side its bow points — bow-right (`min(nick) < index`) toward `index+1`, bow-left toward `index-1` — and *that* bp must carry staple on **both** helices. A nick landing in the loop is a harmless no-op (`_nick_if_needed` finds no strand). Restored teeth pairs 2→6, 2→6, 2→5; spine unchanged; zero staple laid over previously-unstapled bp. **Second, independent starvation in the same design (same fix session):** a hand-routed staple carrying a `process_id="manual"` crossover was classified **locked**, and the placer's `protected_pos` gate then blanked *every bp of it* — 32 bp × 2 helices — so six neighbour pairs lost their bp 0–31 crossovers. But a manual crossover is an ordinary crossover placed by hand; it changes only how staples are *connected*, never where they sit. Locking is now **forced ligations only** (joins autostaple cannot re-derive). The manual crossover is already safe three ways over without the lock — `nick_all_major_ticks` skips recorded crossover bps, the placer seeds `occupied` from every existing crossover half, and the closing `ligate_crossover_chains` rebuilds the junction. Teeth pairs then reached full 6/6 density (150 → 172 crossovers total across both fixes). **Generalisation:** a staple's LOCATION is user intent; its CONNECTIVITY is autostaple's job. Assert on coverage, never on strand identity. **How to avoid:** never infer that missing staple coverage is an accident — see [[feedback_staples_are_user_intent]]. Direct descendant of [[J3]] (which correctly moved the edge margin off the *helix* end and onto the *staple's* coverage boundary, but then reused the coverage **span** as a proxy for "where the staple legitimately ends" — the same mistake one level up).

## K. Environment / GPU / toolchain

<a id="k1"></a>
### K1. Every CUDA GPU job segfaults (`rc=-11`) after a LAMMPS/CUDA apt install = a native Linux NVIDIA driver shadowing the WSL passthrough, NOT a bad design/params/driver-downgrade (2026-07-09)
Symptom: oxDNA relax `md_relax` (and every GPU job — incl. a previously-PASSING 6hb_curved and oxDNA's OWN shipped `CUDA_EXAMPLE`) died `rc=-11` (SIGSEGV) at the FIRST force step, right after `INFO: Initial kinetic energy: …`. **Wrong hypotheses I burned time on first** (all disproven): a bad folded-corner config; mutual traps; `max_backbone_force`; the CUDA verlet neighbor-list overflowing on a dense fold; precision; a Windows driver *downgrade*. The tell that it's environmental, not the design: **CPU backend runs the identical input fine**, and the failure is design-INDEPENDENT (oxDNA's own example crashes too). **Root cause:** a LAMMPS setup ran `apt install nvidia-cuda-toolkit`, which pulled in `libnvidia-compute-535` — a *native Linux* NVIDIA driver userspace package. In WSL the GPU is reachable ONLY via the Windows-driver passthrough libs in `/usr/lib/wsl/`. That package dropped `/lib/x86_64-linux-gnu/libnvidia-ptxjitcompiler.so.535` (+ `libcuda.so.535`) and registered it in the ldconfig cache. oxDNA (built with a newer CUDA than the driver's ceiling) JIT-compiles its embedded PTX at the first kernel launch and grabbed that version-mismatched 535 JIT compiler instead of the driver-matched one in `/usr/lib/wsl/drivers/<inf>/` (that dir is NOT on the ldconfig path) → SIGSEGV. **How to diagnose fast:** (1) reproduce on CPU (`backend = CPU`) — if it runs, it's the GPU env; (2) run oxDNA's shipped `~/oxDNA/examples/CUDA_EXAMPLE` — if THAT segfaults, it's machine-wide, not your design; (3) `LD_DEBUG=libs LD_DEBUG_OUTPUT=… <binary> …` then grep `calling init` for `ptxjitcompiler`/`libcuda` — a `/lib/x86_64-linux-gnu/libnvidia-*` line instead of a `/usr/lib/wsl/…` one is the shadow; (4) `nvidia-smi` "CUDA Version" is the driver ceiling, `ldd <binary> | grep cudart` is the binary's runtime — compare. **Fix (shipped, no sudo):** `oxdna_runner.oxdna_subprocess_env()` prepends the active WSL driver dir (`/usr/lib/wsl/drivers/*/` containing `libnvidia-ptxjitcompiler.so.1`) to `LD_LIBRARY_PATH` for the oxDNA child so the driver-matched libs win. **Trap:** `apt remove libnvidia-compute-535` does NOT fully clear it — the `libnvidia-compute-535-server` variant ships the same files and often stays installed, so bare GPU still segfaults and the env fix stays load-bearing. **Never install Ubuntu's `nvidia-cuda-toolkit` / native `libnvidia-*` driver packages in WSL** — use the `cuda-toolkit-XX-Y` packages + the WSL passthrough driver only. Full write-up: [[project_oxdna_relaxation]] §"UPDATE 2026-07-09", [[project_lammps_oxdna]].

<a id="k2"></a>
### K2. NAMD-GPU `buildTileLists` illegal-memory-access on a large *flat* origami = the design's big lateral footprint (huge patch grid), NOT VRAM / atoms / water / clashes (2026-07-11)
Symptom: `FATAL ERROR: CUDA error cudaStreamSynchronize(stream) in src/CudaTileListKernel.cu, buildTileLists, line 1141 ... an illegal memory access` at the FIRST minimize step (seen on **GT_corner_v2**, a ~121×121 nm single-layer plate; also **VoltronCore**). Startup completes; crash is on the first force eval. **Two independent bugs here — don't stop at the first.** (1) A real solvation frame bug put DNA atoms outside the cell — fixed (see [[project_namd_solvate]] bug #5). (2) The GPU crash PERSISTED after that fix. **Everything I ruled out, each with a decisive test:** atoms-outside-cell (all inside, still crashes); VRAM (100 ms nvidia-smi sampling peaked **2.6 GB of 8 GB**, ~5.5 GB free at crash); thin box / too-few-patches (forced 12 Y-patches, still crashes); NaN/inf coords (none — the `*****` in the PDB is just >99999 atom-serial label overflow, harmless); multi-PE GPU race (`+p1` still crashes); extreme initial clashes (crashes even from CPU-relaxed coords); atom count / water / PME / periodicity (DNA-only 445k, water-free, PME-off, non-periodic vacuum — ALL still crash); reduced cutoff (still crashes). **The tell:** the **CPU-only NAMD build** (`~/Applications/NAMD_3.0.2_Linux-x86_64-multicore/namd3`) minimizes the IDENTICAL input fine, and compact designs (6hb 226k, 2x3x100_Sq 253k) run on this exact GPU. ~~**Root cause:** the tile-list kernel fails when the **patch grid is large in ≥2 dimensions** … It is the design's physical SIZE/shape, not its atom/water count, so shrinking atom count does NOT help.~~ **← SUPERSEDED 2026-07-11 (see "ROOT CAUSE FOUND" below). The patch-grid story was a correlation, not the cause: it is neither monotonic in patch count nor a function of the patch grid at all.** (The observation that *shrinking* the system didn't help was right; the inference that size/shape was therefore the cause was wrong — *growing* it also fixes it.) Card: RTX 2080 SUPER 8 GB, Turing sm_75, NAMD 3.0.2 CUDA 11.8. VoltronCore (comparable scale) DID run on the other machine's 12 GB RTX 3080 Ti (Ampere) — so a bigger/newer GPU or the CPU build are the only paths for large flat origami on this setup. **How to diagnose fast:** run the same conf on the CPU `namd3` build — if it runs, it's this GPU-kernel limit, stop trying to shrink the system. For large floppy designs, the completed **oxDNA CG relax** is the appropriate local relaxation (GT_corner's finished at 94% bp retention). Related: [[project_water_shell_carve]] documents a DIFFERENT buildTileLists trigger (a large `margin` keyword) — same kernel, unrelated cause. **PRODUCTIONISED (2026-07-11):** this CPU escape hatch is now a first-class **Compute: GPU/CPU** selector in the job runner (`resolve_namd_launch`) — re-confirmed on the identical 1.72M-atom explicit GT_corner (CUDA crashes, multicore minimizes). Benchmark on a fitting 103k-atom system: GPU 12 s vs CPU 116 s (~9.7×) for a 1200-step min — GPU when it fits, CPU as the fallback. See [[project_md_job_system]] §Compute selector.

**ROOT CAUSE FOUND + PRODUCTIONISED (2026-07-11).** Localised with `compute-sanitizer` (memcheck + initcheck) on a minimal repro (a 16×140 square-lattice plate, 380k atoms, patch grid 26×3×34, crashes 5/5).

*The bug.* In `buildTileListsBBKernel`, NAMD counts tile lists **twice**: the CPU sizes the kernel's loop (`calcNumTileLists()` → `numTileListsPrev`, `CudaComputeNonbonded.C:1686`) while the GPU fills the array (`updatePatchesKernel` → a device prefix sum). When the CPU count comes out **larger**, the tail of `tileLists[]` is never written. The kernel reads those **zeroed** entries → `icompute=0` → `tileListPos[0]=0` → `i = itileList` (a huge value) → `patchInd=(0,0)` → `atomStart=0` → it reads `boundingBoxes[itileList]`. Measured: `boundingBoxes[184320]` in an array of **13,166** valid entries (allocation 26,332 = 2×, NAMD's `OVERALLOC=2.0`); faulting byte offset is exactly `24×184320 + 4`. `boundingBoxes` has **no bounds check** in that kernel — only `tileJatomStart` does.

*The predictive rule — and why the obvious one is WRONG.* **It is NOT a function of the patch grid.** Decisive test: hold the box byte-identical (grid pinned at 26×3×34, P=2652) and vary only the water shell → 0.5 nm / **380k atoms = CRASH**, 1.0 nm / 611k = RUN, 1.5 nm / 782k = RUN. Same geometry, opposite verdicts — so **`patch_grid_is_gpu_safe(Px,Py,Pz)` cannot exist**, and *adding* atoms can fix it. The real variable is the **tile-list count** ≈ `14·P·⌈atoms/(32·P)⌉`, and it fails in **BANDS**, not above a threshold: safe <~183k · **CRASH ~186k–250k** · safe ~251k–333k · **CRASH ~360k+** (separates 34/35 measured configs; it mispredicts carved-shell systems where per-patch density is very uneven, so it can flag risk but **cannot certify safety**). Deterministic and razor-sharp at the edge: Pz=45 CRASH 3/3, Pz=46 RUN 3/3.

*Fix #1 (shipped, still useful).* `namd_runner.gpu_tilelist_probe()` runs ONE minimization cycle on the GPU (~5–15 s, cached in the package as `.gpu_tilelist_probe.json`) and `run_job` auto-routes an unsafe package to the CPU build. Fails **open**; skipped for Compute=CPU/GBIS. Tests: `tests/test_namd_gpu_probe.py`, `tests/test_md_runner_proceeds.py::test_gpu_{un,}safe_geometry_*`. **Keep it** — the second computer still runs stock NAMD until the patched build is rebuilt there.

---

### ✅ K2 SOLVED (2026-07-12) — it is a ONE-LINE NAMD BUG. Real 3.0.2 source obtained; patched build validated.

**Root cause.** NAMD counts nonbonded tile-lists TWICE and the formulas disagree for an **empty patch**:

| | where | formula | patch with 0 atoms |
|---|---|---|---|
| host | `CudaComputeNonbonded.C:1596` (`calcNumTileLists`) | `(numAtoms-1)/32 + 1` | **1** |
| device | `CudaTileListKernel.cu:351`, `:385` | `computeNumTiles()` = `(numAtoms+31)/32` | **0** |

Identical for every patch with ≥1 atom; they diverge **only at n==0**, because C truncates `-1/32` toward zero. So each compute whose i-patch is empty makes the host over-count `numTileLists` by one. `updatePatchesKernel` never writes those trailing entries; `buildTileListsBBKernel` still loops over them, reads the **uninitialised tail** → `icompute=0`, `patchInd=(0,0)` → `i = itileList` → `boundingBoxes[itileList]` (~184,000 into a 13,166-entry array) → illegal address. `boundingBoxes` is unguarded.

**Why origami.** Empty patches exist only where there is VACUUM. A carved 0.5 nm shell around a flat plate in a rectangular box leaves vacuum at the **box corners** (measured: exactly the 4 corners `(0|25, 2, 0|33)`). Fill it (1.0 nm shell → 0 empty patches) and the SAME grid runs. This is the "correlates with high vacuum content" observation posted to namd-l in 2017 and never diagnosed.

**Why it looked banded/non-monotonic.** The uninit tail exists in *every* carved case, but `cudaMalloc` doesn't zero memory — whether the garbage indexes OOB depends on allocation history. Deterministic per system, erratic across sizes.

**Upstream.** ⚠️ I earlier wrote "NAMD 3.1 does NOT fix this" — **WRONG**. Dev/3.1 routes the host count through `computeNumTiles()` too, which silently fixes it. (A subagent called the versions "functionally identical" and missed the n==0 case. Don't trust that claim.)

**Fix #2 (the real one).** `tools/namd_tilelist_fix/` — a 1-line patch + build script producing `~/Applications/NAMD_3.0.2p1_Linux-x86_64-multicore-CUDA/`, which `find_namd()` prefers automatically (reverse-sort of `~/Applications/NAMD_*`; `3.0.2p1` > `3.0.2_`). **No NADOC code change needed.** Needs CUDA **12.x** — CUDA 13 cannot compile 3.0.2 (`cub::Min/Max/ShuffleDown/TransformInputIterator` removed in CCCL 3). Build gotcha: NAMD's prebuilt static FFTW2 is non-PIC and modern g++ defaults to PIE → link fails; charmc swallows `-no-pie` inside its quoted `-ld++-option`, so the script injects it via a `g++` shim.

**Validation (causality, not correlation).** stock 3.0.2 → 13/13 CRASH. Rebuilt from source **unpatched**, same CUDA 12.6 toolchain → **13/13 still CRASH** (so it is not the toolchain/rebuild). Rebuilt **patched** → **13/13 RUN**, 3/3 controls still RUN. Patched GPU agrees with the CPU build to **~0.02%** total energy on a system stock NAMD cannot run at all → correct, not just non-crashing.

**Do NOT "fix" it with `margin`** — a large margin trips the SAME kernel on a carved box (pinned by `test_md_water_shell::test_no_explicit_margin_in_configs`); in the sweep margin only "worked" by making patches big enough to have no empty ones, and it silently drops Py 3→2.

<a id="k3"></a>
### K3. NAMD-seed ~N× "explosion" of a copy-pasted/rotated origami = design cluster_transforms applied TWICE (FIXED) (2026-07-11)
Symptom: a NAMD run seeded from an oxDNA job dies at startup with `FATAL ERROR: Duplicate bond from atom 89094 to atom 89103` (seen seeding GT_corner_v2, a Tikhomirov Mona-Lisa quadrimer built by cluster copy-paste + 90°/180° rotations + forced ligations). **The duplicate bond is a red herring** — the two atoms are a purine ring-closure (ADE N9–C4) present once in the PSF. Real symptom chain: the reconstructed all-atom PDB is ~3–5× too big → coords OVERFLOW the PDB 8-char fields (`-1637.208`) → columns shift → segid corrupts → the ENM base-ring parser (`md_protocols._parse_base_ring_residues`, groups by segid contiguity) splits a residue → re-bonds its own ring-closure atoms as "inter-residue" → duplicates the covalent PSF bond → NAMD rejects. So the bond error just MEANS "the seed exploded."

**TRUE root cause (found, fixed):** `build_atomistic_model` places atoms in straight per-helix geometry, then runs a FINAL pass `apply_deformations_to_atoms(atoms, design)` that applies the design's deformations AND `cluster_transforms` (the copy-paste rotations/translations). But an oxDNA SEED's CG override already carries each nucleotide's FINAL world position — deformed, cluster-transformed, then relaxed. Re-applying the design transforms DOUBLES them → the ~N× blow-up (GT_corner 102 nm CG → 367 nm all-atom). It only bit cluster/deformed designs; plain wide-flat origami has identity transforms so double×identity looked fine (that "isolation" misled me toward a traversal/labelling theory — WRONG; the frame↔atom decoupling I thought I saw was an artifact of the doubled transform, not mislabelling).

**Fix:** `build_atomistic_model(..., apply_design_geometry: bool = True)`; the seed path (`build_atomistic_model_from_cg_spline`) passes `apply_design_geometry=False`, so the deformation/cluster pass is skipped and the seed becomes a PURE function of the oxDNA frames. Validated: GT_corner 3.60×→1.01×, reproducer trans-50nm 1.05×, 6hb 1.02×, WC-C1' pairs intact (~0.94 nm). Regression pin: `tests/test_cg_seed_cluster_transform.py` (cluster rotation + translation + multi-cluster reconstruct at ~1×).

**Diagnose fast:** compare reconstructed all-atom bbox span to the CG backbone span — ≫1× means a transform was double-applied; do NOT chase the "duplicate bond" or PBC (the oxDNA structure is whole; unwrap is a no-op). A guard in `build_atomistic_model_from_cg_spline` still raises early on any >2× explosion as a safety net. See [[project_oxdna_relaxation]] §NAMD-seed. (GT_corner may still hit the separate NAMD-GPU `buildTileLists` footprint limit at minimize — that's K2, hardware.)

<a id="k4"></a>
### K4. GBIS implicit solvent is CPU-only on NAMD 3 — it crashes the CUDA buildTileLists kernel even at low atom count (FIXED: runner auto-routes to CPU build) (2026-07-11)
Symptom: an `implicit_gbis_namd` NAMD job dies at the FIRST minimization step with the SAME `FATAL ERROR: CUDA error cudaStreamSynchronize(stream) in … CudaTileListKernel.cu … buildTileLists … illegal memory access` as an explicit-solvent GT_corner run. **Decisive clue:** the GBIS package is DNA-only — the log shows **445,277 atoms** (down from ~1.87M explicit) and **"0 MB of memory in use"** — so it is categorically NOT a VRAM/atom-count problem (this also settles [[#k2]]'s "not VRAM"). The real tell in the log: `Warning: Always using force tables for GPU nonbonded kernel due to unsupported config parameters` immediately before `GBIS GENERALIZED BORN IMPLICIT SOLVENT ACTIVE`. **Root cause:** NAMD 3.0.x's CUDA nonbonded kernel does not support GBIS; it limps onto force tables and then the tile-list build does an illegal GPU memory access. **Proof:** the identical GBIS package (`GT_corner_v2_namd_gbis`) run with the `~/Applications/NAMD_3.0.2_Linux-x86_64-multicore/namd3` (CPU, non-CUDA) binary minimizes cleanly — GBIS active, bad-contact count falls (16751→14859→12537), GBIS solvent energy goes finite; the `…-multicore-CUDA` binary crashes. **Fix:** `namd_runner.find_namd(prefer_cpu=True)` returns the first non-CUDA (`-multicore`) build (skips CUDA via `namd_is_cuda_build`), raising a clear error if only a CUDA build is installed; `run_job` selects it AND passes `run_devices=""` (omit `+devices`) whenever `job.protocol == IMPLICIT_GBIS_PROTOCOL`. Both binaries ship in the standard NAMD tarball set. **Caveat:** CPU GBIS is slow — good for minimize/declash + short relax (early-stop tier), NOT the full 12-segment ×2.4M-step ladder. Tests: `tests/test_namd_discovery.py` (prefer_cpu picks non-CUDA / raises when only CUDA). See [[project_md_job_system]] §GBIS.

<a id="k5"></a>
### K5. A "heavy tests auto-skip while a sim runs" guard that NEVER fired — NAMD's comm is `NAMD masterPe`, and pgrep matched case-sensitively (2026-07-12)
Symptom: ran the full suite as a pre-push gate while a real 1.44M-atom GT_corner_v2 NPT job was live. Two heavy real-NAMD tests **failed** (`test_namd_benchmark_completes_end_to_end_on_a_6hb`, `test_real_namd_run_holds_anchor…`) with `FATAL ERROR: CUDA error cudaHostAlloc(pp, sizeofT*(*curlen), flag) in src/CudaUtils.C, reallocate_host_T` — a **pinned-host/GPU exhaustion**, i.e. pure resource contention with the production job. It reads like a regression in whatever you just changed. It is not.

ROOT CAUSE: `hardware.heavy_sim_running()` ran `pgrep -l "namd|oxDNA|arbd|gmx"`, which matches the process **name** (comm) **case-sensitively**. A running NAMD renames its comm to **`NAMD masterPe`** — capitals, and containing a space — so `namd` never matched. The guard returned `(False, "")` for every NAMD job that has ever run on this machine, and `pytest_runtest_setup`'s `slow`-marker skip never engaged. `pgrep -l namd3` also returns nothing; only `pgrep -af namd` finds it. (oxDNA/arbd/gmx do NOT rename their comm, so the guard *did* work for them — which is why this went unnoticed.)

FIX: `pgrep -il`. Do **NOT** switch to `-f` (full cmdline): pytest's own argv contains "namd" whenever you run `tests/test_namd_*.py`, so `-f` self-trips the guard and skips everything. Pinned by `test_parse_pgrep_l_handles_namds_real_comm` + `test_sim_guard_pgrep_is_case_insensitive_and_matches_comm_not_cmdline`. Verified live: guard → `(True, "simulation process(es) running: NAMD")`, and the two tests now **skip** instead of failing; full suite 4635 passed / 236 skipped (was 67 skipped).

**How to avoid**: a guard/diagnostic that can only ever say "no" is indistinguishable from a working one until the day it matters. When a protective check exists, **assert it actually fires** at least once against the real thing (here: one live-process test), don't just unit-test its pure parser. And when heavy tests fail with an *allocation* error rather than a wrong value, suspect contention before suspecting your diff. See [[project_test_parallelization]], [[project_md_job_system]].

<a id="k6"></a>
### K6. NAMD dies at segment START on `cudaMallocHost` = GPU-resident exhausted the host's PINNED-memory pool (not VRAM, not RAM) (2026-07-12)
Symptom: a relaxation ladder runs the gentle `_p10` warmup for 8 hours, then the very next segment (`_p50`) dies **before step 0** with
`FATAL ERROR: CUDA error cudaMallocHost(pp, sizeofT*len) in file src/CudaUtils.C, function allocate_host_T, line 88`, stack `Sequencer::integrate_CUDA_SOA`. NADOC then reports "*stopped with no usable checkpoint*", which describes the aftermath, not the cause.

**Root cause.** `_p50` is where NADOC switches to **fast mode**: HMR psf + `rigidBonds all` + **4 fs** + **`GPUresident on`**. GPU-resident (CUDASOAintegrate) pins a large host buffer. A host's **pinned** pool is NOT its free RAM: this WSL2 box pins a maximum of **1.00 GB** while showing 15 GB free (measured directly with a `cudaMallocHost` loop; `ulimit -l` is only 64 MB yet CUDA still pinned 1 GB, so RLIMIT_MEMLOCK is *not* the binding constraint — it's the WSL2 driver's pool, and it can't be raised). Reproduced on a fully idle machine → a hard ceiling, not contention.

**Measured GPU-resident ceiling (this box):** 380k atoms RUN · 541k RUN · 756k RUN · **971k FAILS**. GT_corner_v2's relax package is **1.44M atoms** → fails outright. So NADOC was emitting a conf that *cannot* run here.

**The trap in the obvious fix.** Setting `GPUresident off` alone does NOT work — it dies instantly with `ERROR: Constraint failure in RATTLE algorithm for atom N`. The 4 fs timestep survives only under GPU-resident's GPU constraint solver; the CPU RATTLE path can't hold it. (`md_protocols.strip_gpu_resident`'s docstring used to claim "HMR + 4 fs + rigidBonds all still run on CPU, just slower" — **that was wrong**; corrected.) Measured from a real p10 checkpoint: 4 fs → RATTLE fail; **2 fs → runs**.

**Fix.** `namd_runner.gpu_resident_probe()` — one pairlist cycle of the first fast conf (~60 s, cached in the package as `.gpu_resident_probe.json`), exactly the pattern of the tile-list probe. The ceiling is a property of the **host**, not the design, so it is not predictable from atom count across machines (the other computer has a different pinned pool) — probe it, don't fit a threshold. When it fails, `downgrade_gpu_resident_confs()` rewrites every fast conf via `md_protocols.downgrade_gpu_resident()`: drop `GPUresident`, halve the timestep (4→2 fs), and **multiply `run` + `dcdFreq`/`restartfreq`/`xstFreq`/`outputEnergies` by 2** so the segment covers the **same simulated time and writes the same number of frames**. HMR, `rigidBonds all`, PSF, PME, cutoffs and barostat are untouched — physics unchanged, only integrator throughput. Originals kept as `<name>.conf.gpuresident`. Tests: `tests/test_md_gpu_resident.py`.

**How to avoid**: a CUDA allocation failure is not automatically "out of VRAM" — `cudaMallocHost`/`cudaHostAlloc` are **host pinned** allocations with their own, much smaller ceiling. Check which allocator failed before blaming the GPU or the design size. And when a throughput switch (`GPUresident`) is coupled to a stability assumption (4 fs), you cannot disable one without the other. See [[project_md_job_system]].

**This-box note (2026-07-12, the 3080 Ti computer).** Independently re-hit K2 on `6hbx100_90deg` (a 90° bent 6hb, carved 1.2 nm shell → vacuum corners) and re-derived the same conclusion the harder way (the `+p1` tell converts the illegal-access into `Low global CUDA exclusion count! (209304 vs 241531)`; structure was healthy — bonds ≤1.73 Å, all 1-2/1-3/1-4 exclusions ≤4.24 Å; mgh restraints correct). The canonical fix (patched `NAMD_3.0.2p1_*` build) is **not yet compiled on this machine** — as a stopgap `~/.local/bin/namd3` symlinks to the CUDA-12.0 git build (`~/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/namd3`), which runs the failing conf clean because that Dec-2025 source post-dates the fix. NOTE this symlink shadows `find_namd()`'s auto-prefer of `NAMD_3.0.2p1_*` (PATH `namd3` is checked before the install-dir glob) — **once the patched build is compiled here, remove the symlink** so the probes + canonical build take over. It works *not* because of CUDA 12 (see K2: unpatched CUDA-12.6 rebuild still crashes) but because the git source already has the one-line fix.

<a id="k10"></a>
### K10. A containment-less outside-click dismissal makes every menu item dead to a real mouse (2026-07-27)
`frontend/src/ui/spreadsheet.js` armed its context menu with
`setTimeout(() => document.addEventListener('pointerdown', _removeCtxMenu, { once: true }), 0)`
— **no check for whether the press landed inside the menu**. A real mouse click is
pointerdown → mouseup → click. The pointerdown on an *item* therefore removed the menu
from the DOM, and because `click` only fires on a node still connected at mouseup, the
item's handler never ran. Every item in that menu had been dead since it was written
("Clear sequence", "Set binder sequence…", "Go to strand").

**Why nothing caught it.** jsdom dispatches `click` to a detached node without complaint,
and `element.click()` skips pointerdown entirely — so both a unit test and a hand-written
synthetic-click probe pass. It reproduces only under a real browser driver. I hit it while
verifying a new "Edit sequence…" item in Playwright: the menu opened, the item was visible,
Playwright clicked it, and nothing happened — with no console error, no network request,
and no toast (my own error path swallowed a no-op). The tell was that a `page.evaluate`
`target.click()` DID work while `locator.click()` did not: **that asymmetry means the real
event sequence is being interrupted, not that the handler is wrong.**

**How to avoid**: any dismiss-on-outside-click handler must be
`if (!menuEl.contains(e.target)) close()` — the rule `ui/primitives/context_menu.js`
already implements; prefer that primitive over a bespoke menu. And do not use
`{once: true}` for it: an inside press consumes the listener and the menu can then never
be dismissed by a later outside click (that half IS jsdom-testable, and is what
`spreadsheet.test.js` pins). Generally: when a UI element does nothing on click and the
console is clean, suspect the element was detached between mousedown and mouseup before
suspecting the handler.

<a id="k7"></a>
### K7. Right-drag-to-pan pops the app context menu on native Linux but not on Windows/WSL — the browser fires `contextmenu` on button PRESS, not release (2026-07-23)
Symptom: on the native-Linux machine every right-click-drag opened the app's own context menu instead of panning; identical build on the WSL/Windows machine panned fine.

**Root cause — not a code bug, a platform difference.** All four canvas `contextmenu` handlers (selection_manager 3D-design menu, protein-conjugate menu, assembly part menu, slice-plane cell menu) told a right-CLICK from a right-drag-PAN by measuring pointer movement between right-button-down and the `contextmenu` event. That only works if `contextmenu` fires on button **release**: Windows/macOS browsers do (drag already moved the pointer → move check suppresses the menu). Linux GTK browsers (Firefox AND Chromium) fire `contextmenu` on button **press**, before any movement → the move check always reads ~0 → every pan is mistaken for a click and the menu pops, blocking the pan. The native menu itself was already suppressed everywhere by OrbitControls' own contextmenu handler, so the user only ever saw the *app* menu.

**Fix.** `frontend/src/scene/right_click_menu.js` → `deferrableContextMenu(canvas, body, {capture})`. It preventDefaults, then checks `e.buttons & 2` (right button still held): if held, the event is press-time (Linux) and a `pointerup` is still coming → defer `body` to that pointerup (by then the pan has moved the pointer, so the body's existing move check works); if released (`buttons` has no right bit, Windows/mac) → run `body` now, behavior byte-identical to before. All four handlers wrapped with it; the deferred listener registers in the same phase (capture for the protein handler, so a protein hit still preempts the strand menu via `stopPropagation`). Tests: `right_click_menu.test.js`.

**How to avoid**: any NEW canvas `contextmenu` handler that discriminates click-from-pan by movement MUST go through `deferrableContextMenu` — deciding at contextmenu time is unreliable cross-platform. `e.buttons & 2` on the contextmenu event is the clean press-vs-release discriminator (held ⇒ press-time/Linux ⇒ pointerup is coming).

### H14. Two independent samplers AGREED with each other — and both were wrong. A polymer's end-to-end distance is a long-wavelength mode; MD converges the local angles first, then reports a confidently wrong answer (2026-07-13, SNUPI SS-2)
Building the free-ssDNA-tail model, the gate was the WLC oracle: a free n-nt tail must reach `⟨R_ee²⟩ = 2·L_p·L_c·[1 − (L_p/L_c)(1 − e^{−L_c/L_p})]`. Three probes in a row said the chain was ~3.5× too stiff, and each "explanation" was plausible and wrong:

1. **First probe** (GJF Langevin, 400k steps from a straight start): every bending rigidity from EI = 2.775 down to 1.0 gave the *same* effective persistence length (~1.9–2.3 nm). A chain that ignores its own bending stiffness is impossible — that flat response was the tell, and I nearly "fixed" it by tuning EI.
2. **Ruled out the obvious suspects the right way**, which is what made the diagnosis stick: (a) *is the element wrong?* No — imposing a uniform kink and relaxing the nodal triads gives joint stiffness `κ = EI/b` to **machine precision**, so `L_p,eff = EI/k_BT` exactly. (b) *is the corotational force non-conservative?* (a real worry — `f = TᵀK d` omits the EICR projector, and a non-conservative force samples no Boltzmann distribution at all). No — it matched `−∇U` to 0.5% small / 2.4% at large amplitude.
3. **So the energy, the force and the element were all right, and the simulation still disagreed with its own energy function.** That isolates it to *sampling*. I cross-checked with Metropolis MC — no integrator, no mass, no friction — and it **agreed with the MD** (⟨cos θ⟩ 0.750 vs 0.736). Which felt like vindication and was the opposite: **both samplers were under-converged in the same way.**

ROOT CAUSE: a chain's local bond angles relax in picoseconds; its **long-wavelength bending modes** relax orders of magnitude more slowly. Langevin *and* local-move MC both converge `⟨cos θ⟩` almost instantly and then leave the global conformation frozen near wherever it started — so ⟨R_ee²⟩ was still remembering the initial condition after 232 ns. The signature, once you look for it: the tangent correlation `⟨u_i·u_{i+k}⟩` **PLATEAUS** at a finite value (0.64 at k = 12!) instead of decaying to zero. A WLC's must decay to zero. Locally floppy but globally rigid = not equilibrated. The cure was the **pivot move** (rotate everything beyond node i — positions *and* triads — rigidly about it; frame-indifference ⇒ exactly ONE element changes energy, so it is O(1) and decorrelates the whole chain in a handful of moves). With it the correlation decayed properly, ⟨R_ee²⟩ converged, and the real answer appeared: the chain is only **1.74×** stiffer than `EI = k_BT·L_p`, because it is discretised *at* its own persistence length (b/L_p ≈ 1.01), far from the continuum limit that identity assumes.

**How to avoid**: (1) **Agreement between two samplers is not convergence** — if both are under-converged in the same mode, they agree *and* are wrong. Cross-validate against a sampler with a *different failure mode* (here: a global move), not merely a different algorithm. (2) For any polymer/chain observable, check the **tangent correlation decays to zero**. A plateau means unequilibrated, always; it is a cheap, unambiguous convergence assertion and it is now pinned in the oracle test. (3) Separate FAST/local observables (bond stretch, ⟨cos θ⟩) from SLOW/global ones (⟨R_ee²⟩, R_g) and never validate the latter with MD run-lengths sized for the former. (4) A response that is *flat* in a parameter the physics says it must depend on (EI here) is a convergence bug, not a material property — do not calibrate against it. See [[project_snupi_ssdna]] (SS-2) and `snupi_tails.pivot_sample_chain`.

---

# L. Rented-GPU runs / cost safety (RunPod)

All from the 3x6x400 production run (2026-07-14): 1.94M atoms, full ladder + 5.5 ns
production, $13 of a $15 cap. **Eleven bugs. Nine produced no error of any kind.**

## L1
**On a rented pod, "fails safe" can mean "fails expensive."**

Tier-A relaxation early-stop decides whether a chunk has plateaued. When it cannot decide
— missing MDAnalysis, too few frames, an unreadable log — it reports **HOLD**: run
everything. That is unambiguously the right default *for the science*. On a rented GPU it
is the single most expensive thing it can do: the un-accelerated ladder is ~35 h and ~$26
against ~4.6 h and ~$4.

Two subsystems were *documented* as fail-safe (`cell_shrink` "self-heals"; the evaluator
"fails safe to run") and both did exactly what the docs said — into the most expensive
possible behaviour. Neither raised anything.

**How to avoid**: (1) For every fail-safe path, ask **safe for whom — the science or the
bill?** and make the expensive branch *loud*. (2) `runpod_executor._ensure_mdanalysis()` is
now a **hard gate**: a pod that cannot import MDAnalysis REFUSES to launch rather than
quietly running the expensive path. (3) Anything whose failure mode is "costs 4x with no
error" belongs in `preflight.py`, not in a comment.

## L2
**`fast=True` silently disabled relaxation early-stop — a 4x cost bug with zero errors.**

`outputEnergies`/`dcdFreq` were a hardcoded **9600 STEPS**. Chunk step-counts are derived
from a target simulated *TIME*, so enabling `fast` (2 fs → 4 fs) HALVES every chunk's step
count for identical physics — while a step-denominated print interval keeps firing just as
often *per step*, i.e. **half as often per nanosecond**. A `p10` chunk fell from 25 ENERGY
frames to **12**, under the evaluator's `min_frames = 20`. `energy_plateaued` therefore
returned False for every `p10` in the ladder, no `p10` could ever bridge, and the
accelerator's ceiling collapsed from ~10x to ~2x.

The accelerator was still emitted, still ran, and still answered — it just answered HOLD
every single time. Nothing errored. The only symptom was the bill. On the live pod it
turned a ~4 h / ~$3 ladder into a ~15 h / ~$11 one that could not finish inside its own
kill-switch. Found only by reading `min_frames` against the conf's actual cadence.

The live run then cleared the bar by **one frame** (`n_energy_frames: 21` vs a threshold of
20) — and only because it happened to cell-shrink *early*. **The same bug has a second
trigger**: a resume runs `total - restart_step`, so a shrink at step 44,000 leaves
76,000/4,000 = **19 frames** and starves the chunk all over again.

**How to avoid**: **Any step-denominated cadence is a latent bug the moment the timestep
becomes a variable.** Derive cadences from the chunk's own length (`md_protocols._output_freq`)
and, on a resume, from the **remaining** steps (`remote_resume_conf._output_freq`). Pinned by
`tests/test_md_cutoff.py::TestEarlyStopFrameBudget` and
`tests/test_remote_resume_conf.py`, both proven can-go-red. `preflight.py` refuses a package
whose chunks are starved.

## L3
**`cell_shrink` was never self-healing on a pod: "bounded retry" meant "fails four times".**

"Periodic cell has become too small" is an NPT box relaxing ~3% to equilibrium density and
crossing NAMD's fixed patch grid. The memory said *"self-healing on restart; bounded retry
in the chain script."* The first half was an assumption and it was **false**: the chain
script's retry simply re-ran the **original conf**, whose `extendedSystem` points at the
*previous* segment's `.xsc` — i.e. the **ORIGINAL** cell. NAMD rebuilt the same patch grid,
the box shrank into the same wall, and all four retries died at the identical step. This
path had evidently never been exercised.

Measured live (the soft chunk shrank at step 4000):

    conf (original) : 156.636 x  89.136 x 1436.190
    restart @ 4000  : 151.972 x  86.482 x 1393.426    (-3.0% on EVERY axis)

**How to avoid**: `backend/core/remote_resume_conf.py` (stdlib-only, vendored, drop-list
pinned in lockstep with `md_protocols._RESUME_DROP`) rebuilds the conf against the segment's
**own** `restart.{coor,vel,xsc}`, which carry the shrunken cell, and runs only the remaining
steps. It deliberately keeps writing the **SAME** `.dcd` (not a `.cont<k>.dcd`): Tier A reads
its WC series off `output/<seg>.dcd`, so a continuation written elsewhere would leave that
series holding only the few PRE-shrink frames and **silently report HOLD forever**.
Confirmed firing on a live pod. **A documented "self-healing" behaviour is worthless until
something has watched it heal.**

## L4
**A transient DNS blip orphaned a billing pod — and its id had never been persisted.**

A routine status poll hit `[Errno -3] Temporary failure in name resolution`. `_request`
turned that blip into a **fatal** `RunpodError`; it propagated out of the poll loop and
killed the launcher — and the launcher's `finally` is the **only** thing that destroys the
pod. NAMD, being `setsid`-detached with output on the network volume, carried on perfectly
happily, so the ladder kept advancing while nothing was left alive to turn the meter off.

**And worse:** `runpod_executor` **never called `job.save()`**. Nothing about the pod was
persisted, so a crashed launcher left an orphaned, billing pod that no later process could
even **name**, let alone reap or resume.

⚠️ **The on-pod kill-switch CANNOT stop the billing.** It runs on the pod with no API key: it
can `pkill` NAMD, never destroy the pod.

**How to avoid**: (1) `_request` retries the network layer and 5xx/429 with backoff; **never
a 4xx** (a bad payload or rejected key fails identically forever and hammering it just burns
pod-time). (2) The pod id is saved the **instant** it exists, and again after launch.
(3) `experiments/exp43_runpod_bench/supervise.py` re-attaches to an orphaned pod (poll →
fetch → destroy). (4) `reap.py --kill` is the panic button; it reads `~/.runpod_key` so it
works with no environment. **Finish every run by confirming `0 pods`.**

## L5
**The spend ledger FROZE while a real GPU billed on.**

The ledger exists **because** the in-code kill-switch is per-POD and has no memory (two pods
each get the full budget) — and then it grew the same class of hole. A pod bills
continuously from creation to destruction, no matter how many processes watch it. The
launcher opened the pod, died (its `finally` **closed** the row), and a supervisor
re-adopted it, writing a second, **open** row for the SAME pod. `_all_rows` deduped by
keeping the **first** row seen — the closed one — so the live, still-accruing row was
discarded and `spent()` **froze at $0.95** while the GPU billed on for another 25 minutes.
True spend: **$1.35**. The budget guard reads that number; it could never have fired.

Two sibling bugs in the same teardown: `supervise.py` called `job.save()` **before**
interpreting the poll verdict, so a finished ladder was recorded as `"running"`; and
`reap.py` destroyed pods without **closing** them in the ledger, so a reaped pod accrued
forever.

**How to avoid**: collapse rows per pod (`started` = earliest sighting; `ended = None` if ANY
observer still has it open); `close_pod()` closes the pod in **every** job's file; save
**after** deciding, not before; the panic button must not corrupt the accounting it protects.
**A ledger that under-reports is worse than no ledger, because it is trusted.** Pinned by
`tests/test_spend_ledger.py`.

## L6
**You pay GPU rates to download your results — and the price table lied.**

Three cost traps, none of which errors:

1. **The network volume is reachable only through a LIVE pod**, so `fetch_outputs` runs while
   the GPU bills, idle. The relaxation produced **5.2 GB**; at domestic downlink (~48 MB/min)
   that is **~100 min ≈ $1.20** — a quarter of what the science itself cost ($3.99), spent
   moving files. **Fetch selectively**: the final checkpoint is ~140 MB and is all production
   needs; the DCDs are the bulk and they **persist on the volume** (pull them later, or on
   the next pod, which is billing anyway).
2. **`GPU_TYPES` carried COMMUNITY prices** while Community cloud is excluded in code (no card
   in EU-RO-1, where the volume pins us). Every estimate — `plan_execution`, `POST
   /runpod/estimate` — was **~2.2x low**. A "$5" overnight ladder is really $11. The live
   kill-switch was never affected (it reads the pod's *actual* rate).
3. **The per-Matom throughput fit does NOT transfer across GPU architectures.** The 4090's
   measured 11.2 ms/step/Matom predicted **20.9** ms/step for 1.94M atoms; the RTX PRO 4500
   Blackwell actually does **26.4** (1.26x slower). **Re-measure on any new card before
   costing a run off it** — and take the measurement from the live ladder's own log rather
   than renting a throwaway benchmark pod.

**How to avoid**: `preflight.py` costs the run at the **measured** rate and prints both the
best case (every stage bridges) and the worst (no bridge ever), so a run that only fits in
the optimistic branch is visible before a cent is spent.

## L7
**Production is not as fast as the relaxation — and two hardcoded I/O cadences were burning 29%.**

Two distinct problems, found only because production ran at **50.0 ms/step** against the
relaxation's **26.4** on the same card and the same system.

**(a) The physics difference is REAL and permanent.** `build_production_conf` deliberately
runs a more expensive integrator than the relaxation's fast chunks:

    fullElectFrequency 1  (relax: 2)   PME EVERY step. At 4 fs that is PME every 4 fs,
                                       matching the Aksimentiev reference. fullElect 2
                                       here would be PME every 8 fs — past the r-RESPA
                                       resonance-stability limit (~4 fs). NOT negotiable.
    stepspercycle      10 (relax: 20)  40 fs pairlist rebuild. Deliberate.

`launch_production.py` had sized the run from the relaxation's ms/step and even *claimed in
its docstring* that "production runs the SAME integrator as the relaxation's fast chunks."
It does not. The 5.5 ns run was therefore costed at 10.1 h / $7.5 when it was really
19 h / $14 — unaffordable, and the kill-switch would have truncated it.

⚠️ **Note the corollary:** the RELAXATION runs 4 fs with `fullElect 2` = PME every **8 fs**,
which by this same argument is past the resonance limit. It is ENM-restrained throughout so
it probably does not matter, but it is an unexamined inconsistency.

**(b) `outputEnergies 100` and `restartfreq 1000` were HARDCODED** in the production
template. Perfectly reasonable for a 250k-atom local run; ruinous for 1.9M atoms in
GPU-resident mode:

  * `outputEnergies 100` forces a **GPU→host energy reduction every 100 steps**. The entire
    point of GPU-resident is that the data never leaves the card; this drags it back 13,750
    times over a 1.375M-step run and prints 13,750 energy frames nobody reads.
  * `restartfreq 1000` writes **~90 MB of restart files (coor+vel, 1.9M atoms) every 1000
    steps — to a NETWORK filesystem.** At 50 ms/step that is 90 MB every 50 seconds,
    sustained, for the whole run.

Neither has **any** effect on the trajectory. Scaling them to the run
(`md_protocols._production_output_freqs`: ~400 energy frames, ~50 restarts) took production
from **50.0 → 35.5 ms/step — a 29% speedup for zero physics.**

**How to avoid**: (1) **Never size production from a relaxation rate.** `launch_production.py`
now applies an explicit `PRODUCTION_PENALTY` when only a relaxation measurement exists, and
says so in the log. (2) **Any hardcoded I/O cadence is a latent bug at scale** — the same
shape as L2's step-denominated cadence. Ask what it costs at 10x the atoms on a network
filesystem. (3) When a run is slower than expected, **diff its conf against the one that was
fast** before assuming the hardware changed.

## L8

### L8. Extra crossover bases silently VETO the fast integrator — so every 0xT-vs-NxT MD comparison is confounded, and costs 4x (2026-07-14)

Symptom: **none.** Prepped the 24hb campaign's three variants (0xT / 1xT / 2xT) with an
identical `prepare_equilibrium_aware_namd(..., fast=True)` call. All three prepped fine, all
three passed the degeneracy gate. But the segment step-counts came out **120k/480k/600k for
0xT and 240k/960k/1.2M for 1xT and 2xT** — 2x, for designs that differ only in `extra_bases`.

ROOT CAUSE — deliberate, undocumented at the call site, and it fires twice:

```
md_protocols.py:1618   declash = declash or design_has_extra_bases(design)
md_protocols.py:1641   soft_ladder = declash or force_soft
md_protocols.py:1642   fast = fast and not soft_ladder        # <- fast dies HERE (ladder)
routes_md.py:834       fast = relaxed_fast and not declash    # <- and AGAIN (production)
routes_md.py:835       timestep_fs = 4.0 if fast else 1.0
```

Any design carrying extra crossover bases is auto-routed to the **declash protocol** and
comes out at **1 fs, `rigidBonds none`, plain PSF, no GPUresident**, with the HMR PSF written
but referenced by nothing. The rationale is sound (extra T's are unpaired ssDNA; `rigidBonds
all` at 4 fs is said to crash RATTLE on them) and it is a **permanent** property of the
design, not a build transient that a relaxation ladder anneals away.

**Two silent consequences:**

1. **THE COMPARISON IS CONFOUNDED.** The 0xT control samples with 4 fs + HMR + `rigidBonds
   all`; the 1xT/2xT variants with 1 fs + flexible hydrogens. Any inter-helix stiffness
   difference you then extract is part extra-base, part integrator — and measuring that
   difference *is the whole campaign*. **A multi-variant study that does not force a MATCHED
   integrator is partly measuring its own protocol.**
2. **4x the money and wall-clock**, on exactly the two variants that carry the independent
   variable. Measured, 24hb @ 1.32M atoms, 50 ns, RTX PRO 6000: 0xT **$87 / 1.8 d**;
   1xT and 2xT **$348 / 7.3 d each**. Budget said $196-262; truth was **~$784**.

`preflight.py` caught the COST half (it refuses a package that lost `fast` — "segments use
GPUresident + 4 fs: 0/12; HMR PSF written but referenced by nothing") before a cent was
spent. **Nothing catches the CONFOUND half.** Only a cross-variant conf diff does.

**How to avoid:** before ANY multi-variant MD comparison, diff the **prepped confs** — not
the designs — across variants on `timestep`, `rigidBonds`, `GPUresident`, and `structure`
(HMR vs plain). *Designs that differ in one field do not imply protocols that differ in one
field.* ⚠️ The existing `6hbx100_noT/_1xT/_2xT` and `2hb_noT/_2xT` results go through this
same code path and should be re-checked for the same confound.

## L9

### L9. RunPod GraphQL 403 "error code: 1010" is CLOUDFLARE, not a bad key — and believing it produced a 26x error in the balance (2026-07-14)

Symptom: `myself { clientBalance }` returns **HTTP 403** for every auth style (`?api_key=`,
`Authorization: Bearer`, raw header), while the same key works perfectly against the REST API.

ROOT CAUSE: `api.runpod.io` sits behind Cloudflare, which blocks **`Python-urllib`'s client
fingerprint** — 403 with body **`error code: 1010`**. Nothing to do with the key. The identical
request via **`httpx` returns 200 instantly** (the codebase already uses httpx in
`runpod_preflight.py`; the kickoff doc's own snippet uses httpx too — it would have worked).

What it cost: I read the *status code* and not the *body*, concluded the key was a "modern
scoped REST key that the legacy GraphQL API rejects", built a coherent and completely false
story on top of it (REST genuinely has no billing endpoint — `/billing`, `/account`, `/me` all
400 — so I declared the balance structurally unreadable), and told the user to mint a new key.
The user said the key already had GraphQL access. It did.

The real damage was not the hour. The balance came back **$207.53** — against the **$7.96**
the task brief asserted. **A 26x error in the single number the entire go/no-go decision rested
on**, and my "diagnosis" had been actively defending the wrong figure.

**How to avoid:** (1) **Read the BODY of a 403 before believing it** — `error code: 1010` is
Cloudflare, not auth; a bare status code is not a diagnosis. (2) Use **httpx** for anything at
`api.runpod.io`, never urllib. (3) Balance lives ONLY on the legacy GraphQL API; the public
REST API has no billing endpoint — that part was true. (4) `balance.py` now wraps this and
**fails loud**: `--require N` exits non-zero rather than warning and proceeding, because on a
rented GPU "fail-safe" means "fail-expensive" (L1).

## L10

### L10. The runbook told me to attach `supervise.py` to a healthy launcher — and it destroyed my own pod 62 seconds in (2026-07-14)

Symptom: launched the 24hb_0xT ladder; pod `aq6ri6d53kd6v0` came up and the launcher began
SFTP-ing the 739 MB package. Per **the runbook's own §2**, attached `supervise.py`. One minute
later the launcher died with `RunpodSSHError: upload failed (24hb_0xT.pdb): Connection not
open` — because the supervisor had **terminated the pod underneath it.**

ROOT CAUSE: `supervise.py` ADOPTS a pod and applies `run_job_on_pod`'s done-test to it. During
STAGING, NAMD has not started yet, so the pod honestly reports
`state=unknown segment=None alive=False stale=True`. The supervisor interprets that as
**"ladder finished: MdStatus.paused — fetching results"** and destroys the pod. It is not
wrong about what it sees; it is wrong about *when it is allowed to look*. Its own docstring is
explicit — *"RE-ATTACH to a pod whose launcher **died**"* — and the runbook's §2
(`nohup launch_relax.py & ; nohup supervise.py <job> &`) contradicted it. **I followed the
document that was authoritative-looking rather than the one that was correct.**

Damage: $0.01, no science lost. Only because it fired during staging rather than at hour 30 of
a production run — the same race at the end of a 3.7-day run destroys the trajectory.

Two things that DID hold, and should be kept: the supervisor reaped **only its own pod**
(`leaving 1 pod(s) alone (not mine): ['wel852jxxb1w1t']`) — the blast-radius fix works; and the
spend ledger booked the pod **once** despite `_on_pod` firing twice.

**How to avoid:** (1) **A supervisor must never share a pod with a live launcher.**
`supervise.py` is standby-only; attach it if and only if the launcher process is gone.
(2) **An "is it finished?" test that cannot distinguish NOT-STARTED-YET from FINISHED is a
destroy-your-own-work bug** — absence of a running job is not evidence of a completed one. Any
done-test whose false-positive branch is *destructive* must require positive evidence of
completion (a final `.coor`, a `completed` sentinel), never the mere absence of life.
(3) When a runbook and a module's own docstring disagree about who owns a resource, **believe
the code**, and fix the runbook.
### H15. A last-ULP "identical" speedup silently moved backbone geometry 0.8 Å — because it feeds an optimizer; and it wasn't even the bottleneck (2026-07-14, atomistic display rebuild)
Task: "build topology once, stream coordinates per frame" — the research-flagged big win for the slow all-atom display rebuild. The plan started as a safe sub-step: cache the frame-invariant template geometry and stamp each nucleotide with ONE batched matmul (`local_stack @ R.T + origin`) instead of ~23 per-atom `origin + R @ local`. Micro-bench looked great (150 ms → 4.5 ms for 70k atoms) and the small crossover designs (6hb_test, Con4, 2hb_xover_val) came out **byte-identical**. Then the golden check on skip-bearing designs FAILED: U6hb (240 xovers + 72 skips) and multi_domain_test3_bend90 (216 skips + bend) diverged.

Measured the divergence: **660 coords differ, up to 0.78 Å (mean 0.1 Å)** — not cosmetic. Root cause: `local_stack @ R.T` (BLAS gemm) accumulates the 3-term dot products differently from per-atom `R @ local` (gemv) at the last ULP (~5e-17). Those stamped O3′/P/O5′ atoms are the ANCHORS fed into `atomistic_minimisers._minimize_backbone_bridge` — a scipy **L-BFGS-B** solve run once per crossover and per skip. That objective has **near-degenerate minima** (many bridge conformations of ~equal bond-length/angle error), so a 1e-16 change in the start/anchor tips it into a *different* valid minimum ~0.1–0.8 Å away. A per-row shim (`R @ stack[i]`) reproduced the golden hash exactly, proving the batched matmul was the sole cause.

Then profiled U6hb (16.7 s under cProfile): **`_minimize_backbone_bridge` = 86%** (264 solves, numerical-gradient finite differences, 11 852 objective evals), `_atom_frame` stamp < 1 s. So for the designs that are actually slow (many crossovers/skips), the atom stamp the whole optimization targeted is a rounding error in the budget — the bridge OPTIMIZER is the cost, and it is frame-dependent (can't be cross-frame cached) and ULP-chaotic (can't be sped by any float-changing rewrite without moving geometry). Reverted the batch entirely; kept the per-atom stamp. The real backend win for re-visits is the per-frame OUTPUT cache already shipped (each frame builds once); the win for huge designs is frontend impostors, not this.

Shipped instead: `tests/test_atomistic_geometry_lock.py` — golden-hash byte-lock on `atomistic_positions_flat` (the 5-dp display wire format) for crossover designs (fast) + skip/deformation designs (slow). It is the artifact that caught this and now guards the locked geometry.

**How to avoid**: (1) A speedup that changes floats "only at the ULP" is NOT safe if its output feeds a numerical optimizer / root-finder / eigensolver — those amplify ULP to macroscopic differences near degenerate solutions. Byte-identity through such a stage is the only safe contract; prove it on inputs that exercise the solver (here: skips + crossovers), not just the easy path. (2) PROFILE before optimising a "known" hot spot — the research premise (per-atom stamp dominates) was true only for crossover-free designs; the slow designs are optimizer-bound. (3) A per-frame OUTPUT cache beats making the per-frame build faster when re-visits dominate. See [[project_photo_mode]], [[REFERENCE_ATOMISTIC]].

### D14. A green suite while the feature is DEAD in the app — an adapter unit-tested in isolation against a contract its caller had already left (2026-07-16)

Symptom: NAMD trajectory scrub + flexibility map do nothing / error, while `just test-frontend` is 100%
green and every `md_viz_adapter` test passes.

Root cause: `align` was inserted BEFORE `signal` in the client viz fetchers
(`getOxdnaTrajectory(id, align = true, signal)`). `oxdna_display.js` — the controller — was updated to
`api.getOxdnaTrajectory(jobId, align, signal)`. `md_viz_adapter.js`, which maps the oxDNA-named controller
calls onto the `/md/` routes, was NOT: it still declared `(id, signal) => api.getMdTrajectory(id, signal)`.
So `align` (`true`) bound to the adapter's `signal` param, the REAL AbortSignal fell off the end of the
arg list, and `_oxdnaJSON`'s `if (signal) opts.signal = signal` waved the boolean through to
`fetch(url, { signal: true })` → `TypeError: RequestInit: Expected signal ("true") to be an instance of
AbortSignal`. Not an AbortError, so `_oxdnaJSON`'s abort catch rethrew it.

**Why the tests didn't catch it — the actual lesson.** `md_viz_adapter.test.js` poked the adapter
directly: `a.getOxdnaTrajectory('J1', sig)`. That pins the contract the test AUTHOR remembered, not the
one the caller uses. The seam's whole job is to match `oxdna_display`, and no test ever wired the two
together, so the suite could not observe the drift. A seam tested only against a hand-written stand-in
proves the stand-in agrees with itself.

Fix (three layers):
1. `(id, { align, signal })` options object for all ten viz fetchers — no positional boolean to mis-bind.
2. `_vizOpts(opts, fn)` tripwire: throws on a positional boolean/AbortSignal, a non-boolean `align`, or a
   non-AbortSignal `signal`, naming the function.
3. `_oxdnaJSON` type-checks `signal` (`if (signal)` → `instanceof AbortSignal`) and throws naming the
   route — the backstop for the ~15 fetchers still on the unambiguous `(id, signal)` shape.
Plus contract tests in `md_viz_adapter.test.js` that build a REAL `initOxdnaDisplay` over the adapter and
assert `getMdTrajectory`/`getMdRmsf` receive an actual `AbortSignal` (and that `cancelPendingLoad()`
aborts it). All five fail against the old adapter — verified by reverting it.

Generalise:
- **Positional booleans next to optional callbacks/signals are a trap.** Adding a param in the middle is
  invisible to every existing caller. Use an options object.
- **Truthiness checks (`if (signal)`) launder type errors.** Type-check at choke points.
- **Every adapter/seam needs ≥1 test driven by its real caller.** Isolation tests are necessary but they
  cannot see contract drift — that is precisely the failure they must catch.


## H16

**Fix the PATH IN USE, not the leaf — three times in one session (2026-07-28).**

Three separate bugs, one shape: a change was correct and unit-tested at the function it touched,
and absent from the code path the UI actually runs.

1. **GPU-resident size gate.** Added to `build_production_conf`, with tests. The panel's Start
   Production calls `/production-run` → `md_ensemble.build_replica_package`, a *different*
   `build_production_conf` call site that passed no `n_atoms`. Two user retries showed no change.
2. **Production timestep.** Removed the declash conflict, but left
   `fast = (timestep_fs == 4.0) and not declash` — the same coupling in another variable. The
   replica builder reads `fast` as "may I use HMR", so a requested 4 fs silently emitted 1 fs and
   measured ~80 ns/day (exactly the 1 fs rate).
3. **PBC snap.** Fixed `reassemble_to_posed_reference`, verified 0 broken bonds on the trajectory
   path, shipped. `ws.py`'s ballstick branch — the *live* display, which is what the user was
   looking at — had its own inlined copy of the older per-atom snap and never called the shared
   function. The user hard-reset the browser; the artefact stayed.

**Why unit tests did not help:** every one of them called the leaf directly. Nothing exercised the
route the button takes, so a fix could be complete at the leaf and absent on the path.

**How to avoid:**
- Before claiming a fix, ask **"what does the button actually call?"** and trace it. `grep` every
  call site of the function you changed and check each one passes the new argument.
- Prefer an **API-level integration test** (drive the route against a temp workspace, assert on the
  artefact that lands on disk) over another unit test of the helper. No browser needed; runs in the
  fast suite.
- For a shared helper, add a **structural guard** that fails if anything re-implements it — the
  duplicate is what defeats the fix. Example: `test_no_display_path_reimplements_the_pbc_snap`.
- A shared helper is only shared **if every caller actually calls it**.

## H17

**A rejected request must never mutate the completed job it was launched from.**

A production-timestep conflict handler set `status = failed` on the job production was launched
FROM — which is the completed relaxation. Refusing a 2 fs production therefore flipped a finished
12/12 ladder to "failed" in the job list ("NAMD · failed · 12/12 segments · 100% · 9,600,000 /
9,600,000 steps"), discarding the record of hours of successful work. Nothing was lost on disk, but
the status was destroyed by a `save()`.

Root design error: the plan was "fail as a job so the standard Fix popup can explain it" — but for a
*rejection* there is no production job yet. The only job in hand was one that had already succeeded.

**How to avoid:** a route that refuses to start something must reject the REQUEST (HTTP 4xx), not
edit existing state. Treat any completed upstream job as read-only. If a failure genuinely needs a
job row to hang off, create the new job first and fail THAT. Pin the invariant by re-reading
`job.json` from disk, not just checking the in-memory object — the damage is the save.

## K11

**A fast-suite budget "violator" that MOVES between runs is a shared cache warming, not a heavy test.**

Four junction topology/winding tests were relegated to the slow suite on readings of 41 s / 28.8 s /
11.4 s, then un-relegated the same day: measured serially on an idle machine the slowest is **2.32 s**
and both files together are ~10 s. Two compounding artifacts —
`atomistic_minimisers._XB_CACHE` is a **module-level in-memory** cache, so under `-n auto` every xdist
worker starts cold and whichever test lands first pays the entire one-time minimisation; and the
sweep also ran while a +p16 NAMD job owned all 16 cores with pytest niced below it.

The tell was visible and missed: the violator named a **different test on every run**
(T-12 → TT → `test_repaired_build_is_deterministic` → `test_repair_does_not_degrade_geometry`).
Four heavy tests do not take turns; one shared setup cost does.

**How to avoid:** before relegating anything, re-run the file **alone, serially, on an idle box**:
`uv run pytest <file> -m "" --durations=0 -p no:randomly`. A first-test-pays-the-cache cost is not
test weight, and relegating for it is exactly the ratchet the scale-free per-test gate exists to
prevent. (The guard now suppresses the budget check entirely while a production sim is running.)
### E8. Co-motion keyed on the record that only ONE of two forks produces (2026-07-30)

Symptom: rotate an overhang whose direct connection joins two **different-length** overhangs and
the partner stays behind (WC pair distance 1.93 → 5.25 nm through a 90° driver rotation). Dragging
the duplex cluster moves the driver alone. The **equal-length** case works perfectly — which is why
this survived: the existing regression test
(`test_relocated_direct_binding_partner_follows_rotated_driver`) pins the equal-length path and
passes, so the area looked covered.

Root cause: applying a direct connection has **two forks by LENGTH**. Equal-length →
`crud._cv_create_bound_binding` materializes a bound `OverhangBinding`. Different-length → that
function returns early (`crud.py:7652`) and the pair is carried by a bound `Duplex`, relocated by
`core.duplex.relocate_duplex` — whose `__duplex_reloc__` binding is **transient and never
persisted** (`duplex.py:311`). Three separate co-motion sites all built their driver/driven map
from `design.overhang_bindings` alone: `driven_to_driver` (partner refs), `driven_bound_oh_ids`
(the driven-side self-rotation skip), and transitively `_duplex_domain_refs` →
`materialize_duplex_cluster` (the gizmo-drag scope). One missing map, three broken behaviours.
Worse, the cluster then lists only the driver domain on the driver helix, making it a
PARTIAL-coverage "bridge" helix where **only listed domains move** (`deformation.py:2232-2242`) —
so the omission is silently self-reinforcing rather than erroring.

Fix: `deformation._bound_driver_driven_pairs(design)` — one helper returning `driven → driver` from
**both** bound bindings and bound duplexes (bindings win on conflict; they agree anyway because
`_propagate_driver_to_binding` syncs duplex→binding). Both call sites use it; the cluster scope is
fixed transitively. Pinned by `test_diff_length_duplex_partner_follows_rotated_driver` (geometry)
and `test_diff_length_duplex_cluster_contains_the_driven_domain` (structure), both of which assert
the no-binding precondition first so they fail loudly if the fork ever moves.

**How to avoid / diagnose**: when a feature can be represented by **either of two records**, every
lookup keyed on one of them is a latent half-feature. Grep the discriminating field
(`design.overhang_bindings`) and ask of each hit "what happens on the fork that doesn't produce
this?" The tell that hid it here: the two test suites were **disjoint by construction** —
apply-path tests assert bindings and never inspect duplexes, connect-path tests do the reverse, and
nothing exercised the sequence the UI actually performs. A green suite over two record types proves
nothing about the pair. Related: [[overhang-duplex-foundation]] (the coexistence truth table),
[[overhang-connections-panel]]. Same shape as E4 ("the other overhang doesn't track") — this is
that bug reintroduced through the path that has no binding.

---

## H19

**A byte-exact golden over an optimizer's output is machine-specific — it pinned the CPU, not the
geometry (2026-07-31, `test_atomistic_geometry_lock.py`).**

Symptom: two atomistic geometry goldens failed on one computer and passed on the other, with a
clean tree. Five commits in a row tried to settle it by *regenerating the hashes*
(`77663ba → 91a8eed → 0cbbc9f → 3093b83 → ce1ef35`), each one flipping the values to whichever
box ran last and breaking the other. The final commit asserted "no reachable code state produces
these values"; the real answer was that a code state *did* — just not on that CPU.

Cause: `build_atomistic_model` stamps atoms from locked templates (bit-reproducible) and then
closes the backbone at crossover/skip steps with an L-BFGS-B bridge solve whose basin is nearly
flat. A last-ULP difference in a BLAS dot product walks that solve to a different converged
point. This box (Ryzen 9 9950X) dispatches OpenBLAS `SkylakeX` AVX-512 kernels; the goldens were
made where it dispatched non-AVX-512 ones. `OPENBLAS_CORETYPE=Haswell` reproduced all four stale
goldens exactly, at HEAD. Thread COUNT is neutral (1 vs N is byte-identical, which is what the
conftest note actually measured) — kernel dispatch is not.

Diagnostic that settled it in one command: rebuild under `OPENBLAS_CORETYPE=Haswell` /
`Nehalem`. If the stale golden reappears, the code never changed. A worktree bisect confirmed the
build emits the same values at *every* commit back through `77663ba^`, so no commit was ever the
culprit — including the catenation fix (e810dd8) that two sessions blamed.

Scale of the amplification: only the 5 atoms per junction that the solver places (O3′ of the
outgoing residue, P/OP1/OP2/O5′ of the incoming one) move — 0.25 Å on Con4, 0.70 Å on
2hb_xover_val, 1.30 Å on U6hb — while every other atom is bit-identical. That overlaps the
0.1–0.8 Å band [[#h15]] identifies as a *real* regression, so no single tolerance over all atoms
can separate signal from noise either.

Fix: split the oracle by provenance. Hash the **stamped** atoms byte-exactly (98–99% of the
model, verified identical across three kernel dispatches) and pin the **solver-placed** ones on
tolerance — the junction SET exactly, plus O3′–P bond lengths, which are stable to 1.7e-4 Å where
the positions are not, because the linker swings inside the flat basin without stretching.

Two traps found while building it, both worth reusing:
- **Walk the strand, not `model.bonds`.** At a skip the display emits no O3′–P bond at all, so a
  bond-walk misses those junctions entirely and silently leaves 205 solver-placed atoms inside
  the "byte-exact" half. Use `strand_id` + `seq_num` adjacency.
- **Band the tolerance.** Junction lengths are bimodal with an empty gap at 3.17–3.48 Å: below it
  the solve closed the step and the length reproduces to 1.7e-4 Å; above it the step is open
  (4.9–44 Å, not a bond) and floats up to 0.213 Å. One tolerance is either blind on the closed
  band or permanently red on the open one.

**How to avoid:** never hash the output of an iterative solver as a cross-machine golden. Hash
what is deterministic by construction and put a tolerance on what a solver placed. Before
regenerating any golden that "no code change explains", rule out BLAS kernel dispatch
(`OPENBLAS_CORETYPE`) first — regenerating is what turns a one-machine bug into a permanent
two-machine ping-pong. See [[#h15]] for the same amplification via a ULP-level speedup.

---

## L12

### L12. A repair that optimises against ONE measured defect manufactured a different one it does not measure — a phosphate bond built through a ribose ring (2026-07-31, 2hb_2xT)

Symptom: in the relaxed `2hb_2xT` display (job `c8c4a87e2033`), a phosphate bond visibly runs
through the ribose ring of another extra crossover base.

The catenation repair ladder ([[project_crossover_catenation]]) is a deterministic search: it
re-seeds the extra-base solve until the pair's Gauss linking number comes out 0, ranking the
unlinked rungs by linker geometry then by clash count. On this design the raw build was
**catenated and unpierced**; the rung that unlinked it was **unpierced-of-catenation and
pierced**. Measured on the exact shipped design.json:

- raw build (repair OFF): 1 catenated pair, 0 ring piercings
- shipped build (repair ON): 0 catenated, **1 ring piercing**
- and rung 16 of the same ladder was unlinked, unpierced, with *fewer* clashes (11 vs 17) — the
  early exit stopped at rung 12 because it was already sound and clash-improving.

**Neither of the ladder's two acceptance measures can see a threaded ring, for structural
reasons.** (a) The connector polyline walks `P, O5', C5', C4', C3', O3'` — the direct C4'→C3'
step — so the sugar ring, which closes through C4'-O4'-C1'-C2'-C3', is entirely off-curve and
threading it changes no linking number. (b) A sugar ring is ~4.6 Å across, so a bond through its
centre leaves every ring atom 2.2–2.6 Å away — above the 0.30 nm clash threshold for part of the
ring. In the ladder's own score the pierced rung looked like an *improvement*, 34 → 17 clashes.

**Nothing downstream caught it either, and the reason is instructive:** the defect is permanent,
so minimisation converted it into a *different* symptom instead of removing it — the impaled
covalent bond was stretched 1.60 Å → 3.08 Å and stayed at 2.98 Å (~250 kcal/mol) through the
whole 4 fs ladder, the longest heavy-atom bond in the DNA. That value sits just *under*
`atomistic_validation.BACKBONE_STRETCH_NM` (3.0 Å), and `audit_bonds` is not wired into the NAMD
path at all. Prevalence before the fix was overwhelmingly on 2-insert designs and the repair pass
*multiplied* it: 24hb_2xT went 51 raw piercings → **131** repaired.

**How to avoid:** when a search accepts on a measured criterion, enumerate what the criterion is
*blind* to before trusting its winner — a defect that a fix cannot see is a defect the fix is free
to create. Two concrete rules from this one: (1) a topological measure defined on a *reduced*
curve (here, backbone-only) says nothing about the parts of the molecule you reduced away — every
ring you skipped is a hole something can be threaded through; (2) when a defect is permanent,
downstream detectors will report its *consequence* (a strained bond, a stiff junction), not the
defect, so the check has to live at build time. Fixed by `backend/core/ring_piercing.py` +
a `(pierced, penalty, clashes, n_try)` rung score + a build gate; see
[[project_crossover_catenation]] §2026-07-31.

### D15 — Per-STRAND resolution of a per-nucleotide property

**Symptom.** In atomistic (vdw / ball-and-stick), a segment of scaffold sitting inside
Cluster 3 rendered with Cluster 4's colour. The CG bead view showed it correctly, which
is what makes this hard to spot: two representations of the same design disagreeing,
with no error anywhere.

**Cause.** `color_util.js` resolved a strand's cluster by scanning its domains and taking
the FIRST one any cluster claimed, then applying that cluster's colour to the whole
strand. That is fine for a staple, which lives in one place. It is wrong for the
scaffold, which by definition threads the entire structure: on `workspace/VoltronCoreScad.nadoc`
the scaffold has 97 domains across 50 helices, domain 0 falls in Cluster 4, and so all
979 of its nucleotides inside Cluster 3 were painted Cluster 4's colour. The logic
predated per-cluster styling — it was written when cluster colour was the only consumer
and nobody had a scaffold spanning two coloured clusters.

**Why it was not obvious.** Atoms carry no `domain_index`, so per-strand looked like the
only option. It is not: atoms carry `helix_id` + `bp_index` + `direction`, and walking the
design's domains once recovers the (strand, domain_index) for every nucleotide —
`buildNucClusterIndex`, keyed `helix:bp:dir` (the app's canonical nucleotide key).

**How to avoid.** When a property belongs to a *nucleotide*, never key it by strand
because the strand id is the field you happen to have. Ask what the finest identity
reachable from the data is. Check the scaffold specifically — it is the one strand that
crosses every partition, so any per-strand approximation shows up there first and only
there. Surface is the genuine exception: its vertices carry a strand id and nothing else,
so it stays per-strand until the backend payload grows helix/bp.


---

### D16 — Sharing a singleton controller makes a previously-DEAD teardown live (2026-08-02)

**Symptom.** After trajectory keyframes were rewired to drive the jobs panels' `oxdnaDisplay`
controller instead of the animation player's own pipeline: go to the Animations tab, play a
trajectory keyframe, jump to Photomode and back — the model snaps to **NADOC native positions**
instead of holding the trajectory frame. No console error. Photo mode itself was innocent (it
only swaps materials, and `_leaveAnimationsTabUnlessPhoto` deliberately *defers* the leave).

**Cause.** `ui/display_tab_policy.js` said only `'photo'` preserves a display, so *arriving* on
the Animations tab (`'scene'`) satisfied `shouldTearDownDisplays` and
`oxdna_jobs_panel.js`'s `left-tab-change` listener ran `_allDisplaysOff()` →
`oxdnaDisplay.stopAndRestore()`. That code had been there all along and had always been a
**no-op**, because the animation player used a private pipeline and never made
`oxdnaDisplay.isActive()` true. The moment the animation started driving the shared controller,
a dormant branch became the thing that undid its work — and `stopAndRestore()` also discarded the
trajectory cache, so the next Play re-downloaded it.

**The general shape:** when you make subsystem A drive subsystem B's shared object, every
`if (B.isActive())` in the codebase is a branch that just changed meaning. Grep for the
predicate, not just the object. A teardown that was unreachable is not the same as a teardown
that is absent.

**How to avoid.** Before routing a feature through an existing singleton controller, enumerate
its `isActive()` / `mode()` guards repo-wide and ask which ones now fire. Where the answer is
"this tab is now a legitimate home for the display", widen the policy — but split the predicate
if some consumers need the old, stricter answer: here `shouldStopLiveSession()` keeps oxDNA Live
and "Display MD" stopping on the Animations tab (a stream keeps *writing* the same beads and
would fight playback), while `shouldTearDownDisplays()` now preserves the painted frame.
Related: **D11** (`#d11-2`) is the mirror image — an *inactive* overlay's `stopAndRestore`
reverting geometry on `design-changed`.

---

## L13

### L13. A ground-up rewrite left a feature "missing" when what it dropped was one function its own caller still asks for by name (2026-08-02, photo-mode video export)

Symptom (as reported): "in our complete redo of photomode, we failed to include a video export."

That framing is what makes this worth banking, because it was **wrong in a specific, useful way**.
Nothing had to be written. `frontend/src/scene/export_video.js:91 exportPhotoVideo()` — the whole
animation→video export, frame loop, WebM + GIF branches, text-overlay compositing, `AbortSignal`,
progress callbacks, download — was **still in the tree, complete**, and had been since v1. It was
unreachable for exactly two reasons:

1. its first executable line is
   `if (typeof photoRenderer.beginFrameSession !== 'function') throw`, and photo mode v2's public
   API (`photo_mode.js`) exports `renderToBlob` and **not** `beginFrameSession`. The only
   implementation left in the repo was `frontend/archive/photo_mode_v1/photo_renderer.js:1640`;
2. nothing imported it — `main.js` imported only its sibling `exportVideo`.

**Why every normal check missed it.** Grep-for-callers of the *retired* module (`photo_renderer.js`)
came back clean, because the caller was in a third file that survived the rewrite untouched. The
test suite was silent because `export_video.js` had zero tests. The rewrite's own topic file
documented the new Export card honestly as "tiled PNG" and simply never mentioned video, so the
docs were not wrong either — just silent.

**The check that would have caught it:** after replacing a subsystem, diff the OLD module's exported
API against the new one, and for each **dropped** name grep the whole of `src/` — not just "does
anything still import the old module". A dropped export is a contract break even when no import of
the old file remains, because callers reach it through the *new* object.

**The second half of the lesson — offline render paths lose everything the render loop did for
free.** Photo mode keeps its material swap and shadow frustum current in two places, and *neither*
runs when frames are stepped by hand:

- `store.subscribe` on design/assembly/staples/isolated-strand, and
- a geometry fingerprint inside `_perFrameSync`, which only ticks from the render-loop override
  installed via `setRenderFn`.

An export bypasses the loop entirely. Meanwhile `animation_player._applyAt` genuinely *replaces
meshes* mid-timeline (trajectory keyframes swap the heavy atomistic/surface rep in and out;
pre-baked geometry frames rebuild beads), and every fresh mesh arrives with the EDITOR's materials
and shadow flags. **Symptom shape to recognise: a render that starts correct and degrades partway
through, with no error.** Fix was `_syncForOfflineFrame()` at the top of each frame — fingerprint →
`resync()`, plus a `followMotion` flag for the case the fingerprint *cannot* see (cluster rotation
moves the bounding box while the mesh set is identical).

**And a performance trap inside that fix.** The obvious call for "refit to moved geometry" is
`_rebuildRig()` — but it routes through `applyLighting`, which clears the light group and constructs
fresh lights, **discarding the key light's 2048² shadow map**. Correct once on a settings change;
a texture reallocation per frame at 30 fps. Split out `_refitBounds()`, which recomputes bounds,
slides the rig, re-lengths each light along its existing direction, and refits the frustum + floor —
keeping the light objects, and their shadow maps, alive. Pinned by asserting light **object
identity** survives a `followMotion` frame (the test fails against `_rebuildRig`).

Related: the same rewrite is why `beginFrameSession` exists at all rather than a `renderToBlob`
loop — browsers block new WebGL contexts after ~30, so a per-frame context dies mid-export.

## L14 — The login node is not a compute node (Alpine, 2026-08-07)

**Context.** Building a CUDA/GPU-resident NAMD on Alpine and wiring NADOC to submit to it.

**Three failures, one root cause: I probed the cluster from the login node and treated the
answer as universal.**

1. `list_namd_modules` ran a bare `module -t avail namd` and returned **empty** — right after
   SLURM 30948986 died on an unknown module `namd/3.0.1_gpu`. Alpine's Lmod is **hierarchical**:
   `namd` is invisible to `avail` until a compiler is loaded. The tool was useless at exactly the
   moment it was needed. Fix: load a compiler first, then fall back to `module spider`, which
   searches every branch regardless of what is loaded.

2. A submit pre-flight built on `module load … && command -v <namd>` **failed on the login node**
   with `These module(s) exist but cannot be loaded as requested: "gcc/11.2.0"` — while the build
   job had loaded that same module successfully inside `acpu`, and `module spider gcc/11.2.0`
   reported *"This module can be loaded directly"*. Adding `module purge` (mirroring the sbatch)
   did not help. The login node simply has a different module environment.

3. The build's own artifact check ran `namd3 --version` on an `acpu` node and **segfaulted** — a
   `-DNAMD_CUDA` binary can crash during CUDA init where no device exists. Worse, the check ended
   in `|| true`, so the script printed `BUILD OK` over a core dump.

**Why it matters.** A false negative here blocks work that would have succeeded; a false positive
(the `BUILD OK`) is worse, because it certifies an artifact nobody validated.

**How to apply.** From a login node, verify only what does not vary between nodes:
- **existence** of a module → `module spider <name>` (never `module load`)
- **existence/executability** of a binary → `test -x <absolute path>`
- **never** infer "it runs" — a GPU binary cannot be exercised on a CPU node; that is what a short
  job on the target partition is for.

Mirror the *job's* environment when you must load (`module purge` then load), and remember that
even then the login node may refuse. See [[alpine-cluster-submission]].


### H16. Four ways a check lied to me in one session (2026-08-07, helical-site work)

All four produced a confident, wrong statement that I had to retract to the owner. They are
one family: **the check ran, so I believed the answer, without asking whether the check
could have failed.**

**(a) Measuring the wrong artefact.** `workspace/oxdna_jobs/<id>/design_ref.dat` is an
unconverted REFERENCE; the seed oxDNA actually runs is `conf.dat`. Measuring the former, I
told the owner "every oxDNA/LAMMPS seed NADOC has ever written has base pairs ~0.9 nm too
wide" — a sweeping claim about a shipping pipeline. `conf.dat` was 1.0514 nm against an
equilibrium of 1.0222: essentially correct, because `oxdna_native_seed_map` exists and every
production caller passes `oxdna_native_seed=True`. **Before concluding a pipeline is broken,
find the artefact that pipeline actually consumes.**

**(b) A pin that cannot fail.** Three in one session: an exact-equality assertion where the
two producers legitimately differ by 1 ULP (the measured producer subtracts a tiny axial
component before normalising); a test that `pytest.skip`ped when its fixture produced nothing
to assert on; and a deformation test whose fixture — `Examples/multi_domain_test3_bend90`,
named for a 90° bend — stores `curvature_deg_per_bp = 0.0` and therefore deforms nothing.
**Break the thing on purpose and watch the test go red.** Two of the three survived review
only because I did that; the cluster-transform pin fired when I reverted the helper, the
extended-loop pin did not and had to be rebuilt around a bend the test constructs itself.

**(c) "Byte-identical" as an acceptance bar that would have preserved a bug.** Phase 2's
scope said the mrDNA refactor must produce a byte-identical seed. It could not: the code it
replaced read `phase_offset`/`twist` straight off the stored helix while every other
representation goes through `effective_helix_for_geometry`, so byte-identity would have
preserved the pre-TD-29 twist ramp on every honeycomb design and a 175° phase error (19.99 Å,
a full helix diameter) on `6hb_test`. **When the acceptance criterion is "nothing changes",
check first that nothing SHOULD.** The tell was that the control — square lattice — moved
0.000 Å while honeycomb moved in proportion to helix length.

**(d) A pipeline whose exit code cannot reach you.** `just test | tee log | tail` reports
`tail`'s status, so a guard refusal (`NADOC_TEST_CONFIRM=1` not set — the full-suite recipe
asks for an explicit opt-in) surfaced as "completed, exit code 0" and I nearly reported a
suite pass for a suite that never ran. **`set -o pipefail` on any piped command whose result
you are going to state as fact.**
