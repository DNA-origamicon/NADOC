# design-automation log — oracle catalog, lessons, difficulties

Sibling of `backend_router_extraction_log.md` / `issues_fix_log.md`. The four-file layout (split 2026-06-25
to keep each readable in one pass — see the ledger-audit note):
- **`design_automation_backlog.md`** — protocol + ranked backlog + the ≤8-line living handoff.
- **`design_automation_log.md`** (this file) — the per-loop durable state: the **oracle catalog** (validation
  building blocks to mirror), the **lessons** (anti-patterns banked), and the **difficulties ledger**.
- **`design_automation_harness.md`** — do-not-rebuild reference: shipped wrapper signatures + banked gotchas.
  Consult per-item, NOT per loop.
- **`design_automation_metrics.md`** — the per-item metrics rows + data fits. Append new rows there; read on demand.

---

## Conventions

- One AF item (or one phase) per session, per commit. Commit message: `feat(automation): <op> + <oracle>`.
- The pass criterion is the **validation augment**, never "a wrapper exists" (see the backlog's anti-shovel
  contract). Every row below ends with **"Validation gained, not just a passthrough: ___."**
- New code lands in `headless_build.py` / a new `headless_*_build.py` / `backend/core`. **Never** in
  `crud.py` / `assembly.py` / `main.js`. Cite the god-file LOC Δ (must be flat-or-lower) in the row.
- `backend/core` imports nothing from `backend/api`. Wrappers run the *same* service the route runs — they
  do not re-implement it.

## How to check headless coverage (the probe)

Before picking an item, see what's already wrapped vs. what has only a route:

```bash
# routes defined in the backend:
rg -n '@router\.(get|post|patch|put|delete)\("' backend/api/ | rg -o '"/[^"]+"' | sort -u
# wrappers that exist today:
rg -n '^def |^    def ' backend/api/headless_build.py
# is a given op UI-wired (worth wrapping) or dead (delete candidate)?
rg "<url-fragment>" frontend/src/api/
```

(AF-1 turns this into `headless_coverage_report()` so it stops being a manual grep.)

---

## Metrics rows + Data summaries → archived

Moved to **`design_automation_metrics.md`** (2026-06-25) so this file stays under the Read cap.
That archive holds one metrics row per shipped AF item (+ data fits). Append new rows THERE; read it on demand.

---

## Lessons (anti-patterns banked — read before building)

- **The handoff's named oracle is a HYPOTHESIS, not a spec — check it isn't already covered (AF-37).** The handoff
  had specified AF-37's augment as `assert_binding_locks_joint`. Building it would have been a passthrough: bind
  does topology relocation ONLY (the auto-relax was reverted **2026-05-14 at the user's request**, so
  `locked_angle_deg` stays `None` and `_apply_driver_to_joint` leaves the window alone), and what joint behaviour
  there is was already pinned at route level by three `test_overhang_bindings.py` tests. The oracle would have
  asserted a property the product deliberately doesn't have, over code already covered — a wrapper plus a redundant
  oracle, which is exactly what the anti-shovel contract forbids. **A handoff names the oracle its author expected
  to be missing; that expectation ages.** Before building the named augment, spend 60 seconds on `rg` in the area's
  existing test file and read the route's own comments for a reverted/locked decision — then ask what is *actually*
  unpinned. Here it was the **topological inverse** (bind relocates a domain + rewrites crossovers + deletes a
  helix; one test spot-checked 3 fields, a *separate* test proved the crossover rewrite, and NOTHING asserted the
  rewrite was reverted). Deviating from the handoff was the point, not a detour — but say so loudly in the row.
- **Fixtures: build on the REAL op, not a hand-built model (AF-37, applying AF-39/42).** The ds relax fixture spent
  ~3 weeks silently on a fallback path because it hand-built its inputs. AF-37's fixture instead drives the actual
  chain (`create_bundle → auto_scaffold → auto_break → overhang_extrude ×2 → add_cluster ×2 → patch_sub_domain →
  create_overhang_binding → bind`), and **probing it first paid twice**: (1) a hand-built `OverhangSpec` with
  `sequence=None` backfills a **`length_bp=1`** sub-domain (`models.py:303` — `len(seq) if seq else 1`; the model
  can't see the backing domain), so every `sequence_override` 422s — while a real `overhang_extrude` writes
  `sub_domains` explicitly and is fine, i.e. the hand-built shortcut would have *invented* a problem the app
  doesn't have; (2) extruding into an **occupied** neighbour cell silently *shares* that helix, landing both
  overhangs on one rigid body, which bind refuses (422) — caught only because the fixture asserted distinct
  helices instead of assuming. **Assert your fixture's preconditions; a fixture that can quietly build the wrong
  shape will.**
- **Check a derived-facts block against its OWN numbers before trusting it (AF-42).** AF-39 banked, in a fixture-facts
  comment, both "the reachable chord range is [2.773, 6.759] nm" and "the ds span (6.346 nm) is out of reach entirely"
  — two sentences apart, and the second is refuted by the first by inspection. It survived because a derived-facts block
  *reads* as authority: it cites a method, so the arithmetic goes unaudited. No test caught it (the ss tests use
  reachable bins either way) and it under-sold a real pin — the "ss target ≠ ds span" proof looked vacuous when it isn't.
  **The fix is 10 seconds of arithmetic, not a probe.** When you inherit a facts block, re-check its conclusions against
  its own stated premises *first*; only then reach for the expensive empirical re-derivation. Corollary to the AF-39
  "chase the number" lesson: a contradiction *inside* one comment is the cheapest tell there is.
- **A "synthetic fixture" fallback can silently downgrade the path your test thinks it pins (AF-39).** Production code
  that degrades gracefully for test fixtures will do so *silently*, and a green test cannot tell you which branch it
  took. `_anchor_pos_and_normal` resolves the linker anchor from the `__lnk__` bridge strand, but falls back to the
  overhang's own backbone nuc when no bridge exists (`linker_relax.py:712`, comment: "Fallback for synthetic fixtures").
  The ds relax fixture never calls `generate_linker_topology`, so for ~3 weeks the ds pin was exercising the *fallback*
  anchor — not the complement anchor the app uses — and the harness had banked the inverse claim as fact ("the geometry
  layer emits the `__lnk__` bridge from the connection metadata"; it does not). The tell was cheap and I nearly missed
  it: the two fixtures reported *different starting chords* (4.327 vs 3.186 nm) for what was supposedly the same
  geometry. **When a fixture and the app disagree on a number that should match, chase it — don't normalize it.** Probe
  which branch your fixture actually takes (print the resolved anchor / assert the bridge exists) before trusting a pin,
  and be suspicious of any banked "X is a valid fixture shortcut" that you did not personally verify.
- **Derive the degenerate, don't fish for it (AF-39).** The can-go-red for a 1-DOF relax has a *closed form*: the
  moving anchor must lie ON the joint axis. Solve for it (anchor `[2.0,0.866,0]`, axis dir `[0,1,0]` → origin
  `[2.0,0,0]`) rather than trying origins until one goes red — a fished value is indistinguishable from a false
  degenerate (see the AF-38 lesson below) and rots the moment the anchor moves. Corollary: **compute the reachable
  range before picking a target.** The moving anchor rides a circle, so the chord is bounded
  `[|r_fix − r_move|, r_fix + r_move]` (⊕ the axial offset); a target outside it is unsatisfiable and one within
  ~eps of the *start* chord is vacuous — n_bp=20's default FJC bin sat 0.007 nm from the start chord, under the
  oracle's own eps=1e-3 margin, and would have shipped a near-meaningless "pass".
- **1-DOF relax fixtures can be FALSE-DEGENERATE (AF-38).** A strain-reduction relax test only proves anything if
  the joint can actually reduce the chord. A single revolute joint sweeps the moving anchor on a circle in the plane
  ⊥ to its axis; if that plane is orthogonal to the chord's reducible direction (or the chord is already at the
  circle's closest approach), rotation changes nothing and the relax correctly no-ops — your "passing" test is
  vacuous, and your "can-go-red" degenerate is indistinguishable from a real no-op. AF-38's binding fixture hit this
  with a Y-axis joint (the two whole-overhang sub-domain anchors carried a y-offset rotation couldn't close); the fix
  was a **Z-axis joint** so rotation acts in the anchors' z=0 plane (chord 2.735→1.89 nm, genuine). NOT a product bug
  — the relax is right to do nothing. When you build a relax fixture: pick the joint axis so the chord's gap lies IN
  the rotation plane, and print chord-before/after to confirm a real reduction before trusting the green.

_(Candidates the audit already suggests:)_
- **Passthrough smell.** If your wrapper's body is one `requests`/service call and your "test" only asserts
  HTTP 200, you shipped a passthrough. The oracle must assert a *property of the result*, not that the call
  returned.
- **The route may be dead.** The audit found routes with no live frontend caller (e.g. parts of `/md/*`).
  Re-derive UI-wiring (protocol step 3) before wrapping — a dead route is a `issues_ledger.md` delete
  candidate, not an AF item.
- **Deformation is a three-layer minefield.** AF-6 touches bend/twist sign + frame conventions — `CLAUDE.md`
  says ASK FIRST on topology/geometry/directionality. Don't reason it out; confirm with the user.

## Difficulties ledger (genuinely-stuck items + why)

**2026-06-23 — Tier 6 physics is mock-validated, not engine-validated (the AF-24 gap).** Tier 6 (AF-18..AF-23)
ships complete CODE + ORACLES + live-engine PLUMBING, but the only real-engine confirmation is AF-21's
`test_run_live_field_real_oxpy_steers` (live `F0`/`dir` re-aim steers a real specimen — confirmed PASSING in 13s
this session). AF-19 (τ), AF-20 (|E|↔τ sweep), AF-23 (cross-design campaign) are pinned ONLY against hand-built
mock binaries (`mock_oxdna_field_traj`/`_sweep`/`_campaign`) whose τ/melt signatures are coded to satisfy the
oracle (campaign mock: `k=clamp((4.5−12·F0)·(540/N))`, melt at `F0≥0.4`). So the oracles prove their MEASUREMENT
code is correct given a right-shaped trajectory — NOT that the real engine produces alignment-τ, the τ↓-as-|E|↑
law, a non-destructive window, or distinguishable per-design τ (the user's actual goal). **Why it stayed open:**
a meaningful real run needs a PROPERLY-relaxed duplex (short relaxations give bp_retained≈0, under-formed — see
`project_oxdna_efield`), i.e. real GPU runtime, deliberately deferred during the build loops. **De-risked this
session (so it's no longer stuck, just queued):** oxpy imports, the F0/dir binding patch is live, the binary
resolves at `/home/joshua/oxDNA/build/bin/oxDNA`, an RTX 2080 SUPER is present, and the real gated path RUNS not
skips. → **Diverted to AF-24** (real-engine gated validation, staged P1 τ → P2 sweep → P3 campaign/melt), now the
backlog's `▶ NEXT` ahead of the AF-12/13 stragglers. Each AF-24 phase reuses an EXISTING asserter unchanged and
ships no wrapper (coverage FLAT 37) — the augment is the real-engine gated test that retires the mock-only caveat.

**2026-06-23 (later) — AF-24 ROOT-CAUSED + the fix is known: the automation ran a MOCK-TUNED relaxation (10⁴× too
few steps) on the real engine, so the duplex never RE-ANNEALED.** NOT the field oracle, NOT the retention metric,
NOT the export, and NOT a "relaxation melts" artifact (an earlier draft of this entry concluded that — it was WRONG,
corrected below). User domain insight cracked it: *oxDNA drops base-pairing initially, then re-anneals over the long
md_relax stage.* Investigated on CUDA (RTX 2080 SUPER) with oxDNA's OWN `HBList` (`oxdna_interface.count_hbonds` →
`DNAnalysis`) as ground truth. Findings:
- **The oxDNA EXPORT is flawless** (still true): at t=0, HBList = **42/42**; every pair COM–COM 1.05 nm, base-site
  0.37 nm, `a1·a1 = a3·a3 = −1.00`; backbone bonds 0.785 units (FENE eq. 0.7564). Export geometry is correct.
- **`base_pair_retention` is SOUND** (still true): tracks oxDNA's energy-based HBList (the "diagnose metric first"
  call — answered, not a metric bug).
- **THE BUG — mock-tuned step counts reached the real engine.** `headless_oxdna_build.create_job` defaults to
  **mc=100 / md_relax=100 / equil=100**, `min_bp_retained=0.0`, `max_relax_retries=0` — EXPLICITLY tuned for the
  identity mock (its docstring says a real run "should raise [the gate] back to ~0.5" and "pass a positive [retry]
  budget"). The STANDARD relax (`oxdna_protocol` / `routes_oxdna` defaults) is **mc=1000 / md_relax=1_000_000 /
  equil=100_000**. The AF Tier-6 builders (`build_field_specimen`/`run_field`) + every probe inherited the mock
  defaults → gave the real engine 10⁴× too few md_relax steps → it dropped pairing and never had time to re-anneal.
  My "melts monotonically with steps (100→40 … 50000→0)" sweep was an artifact of scaling ALL stages to small EQUAL
  counts — it truncates before the re-anneal AND over-runs a trap-free equil; it never ran the real protocol.
- **PROOF the protocol is correct (user's working case `workspace/test343.nadoc`, a 42 bp duplex + 7 nt overhang
  anchor, headless STANDARD relax mc=1000/md=1e6/equil=1e5, 217 s on GPU):** HBList **mc 35 → md 39 → equil 42/42**.
  It DROPS then RE-ANNEALS to a perfect 42/42, and `3_equil` (mutual traps OFF) HOLDS 42/42 → the annealed structure
  SELF-SUSTAINS. Exactly the user's description; the protocol works.
- **Secondary (separate) issue:** the bare `make_minimal_design(1 helix, 42 bp)` duplex CRASHES at md=1e6 with an
  oxDNA cell-list overflow (`a cell contains more than _max_n_per_cell (42)` — "box too large for the simulation":
  `box_nm_for_positions` gives a sparse 50 nm box, and `render_stage_input` doesn't set `cells_auto_optimisation =
  false` / `max_density_multiplier`). test343 (a real app design) relaxes fine, so use a real-design fixture; OR add
  those cell keys for sparse small systems. Not the main blocker.
- **`write_mutual_traps` docstring is WRONG** (claims backbones start ~1.9 nm apart / unformed; reality 1.05 nm,
  fully bonded) — fix when touched.
- **THE FIX (now well-understood, NOT ASK-FIRST — just use documented standard params; no topology reasoning):**
  the AF Tier-6 real-engine path must run a STANDARD-grade relaxation (mc≈1000, md_relax≈1e6, equil≈1e5,
  `min_bp_retained≈0.5`, `max_relax_retries>0`) on a real-design fixture (test343-style), NOT the mock defaults.
  Then build AF-24 P1 (gated real test) on that: the annealed 42/42 specimen → field stage → `assert_equilibration_
  timeline`. The field stage is unbiased MD, but the equil result shows the annealed duplex self-sustains, so it
  should hold pairing under a field (the remaining empirical check is τ_align < τ_melt — now likely fine). Repro:
  scratchpad `af24_standard.py` (test343 standard relax), `af24_duplex.py`, the t=0 HBList/orientation probes.
- **Status — AF-24 P1 SHIPPED 2026-06-23.** The fix landed: `headless_oxdna_build.STANDARD_RELAX_PARAMS`
  (mc=1000 / md_relax=1e6 / equil=1e5 / `min_bp_retained=0.5` / `max_relax_retries=3`) — a REAL Tier-6 specimen
  build passes `**STANDARD_RELAX_PARAMS` explicitly (the mock-tuned `build_field_specimen` defaults stay the default
  so the GPU-free mock suite — whose mock cost scales with step count — stays fast). The gated test
  `test_field_specimen_reanneals_and_equilibrates_real_engine` (opt-in `NADOC_RUN_OXDNA_SLOW=1`; `@pytest.mark.slow`)
  builds `tests/fixtures/test343.nadoc`, asserts re-anneal (retention ≥ 0.9), runs an anchored field (pN=2, 20k
  steps), and reuses `assert_equilibration_timeline` UNCHANGED → **PASSED on real CUDA, 252 s** (converged + finite
  τ + not melted; τ_align < τ_melt confirmed). The `write_mutual_traps` docstring was corrected. Remaining: AF-24
  P2 (real |E|↔τ sweep) + P3 (real cross-design campaign) — same pattern, slower (multi-cell). See
  `project_oxdna_relaxation`.

---


## Oracle catalog — index (MIRROR THESE; don't reinvent)

61 proven oracles. Full table (Pins / File(s) / Reuse for) is in the archive's
`## Oracle catalog` section.

- `_canonical_topology(design)` — id/order-independent design fingerprint (helices by grid_pos; strands by grid_p…
- `validate_design(design)→ValidationReport` — no unresolved nicks, strand-position consistency, domain count
- `derive_periodic_delta(design)` — rigid repeat transform (Kabsch on axis geom; pure axial translate, no spiral); …
- `solve_closing_curvature` / `closure_residual` — κ that closes an N-copy ring to <0.5°/<0.5 nm
- circle circularity oracle (`circularity_spread`, `column_lengths`, `fit_radius`) — disc profile spread <0.5 nm; even symmetric trim; ≥16 bp floor
- `derive_placement_spec(design)` — footprint cells + per-cell bp + anchor from feature log
- section-router gap metrics (`intertooth_gap_extension`, `min_per_gap_clearance`, `_scaffold_coverage`) — multi-section routing geometric clearance
- scaffold invariants (`_active_scaffolds`, matched-ends far-translate, seamless N−1 crossovers) — single active scaffold; polymerization-ready junctions
- cadnano round-trip (`import_cadnano` ↔ export; helix-id encodes row/col) — external-format parity
- atomistic round-trip (CG↔all-atom, RMSD<0.005 Å) — coarse→atom fidelity
- feature-log round-trip — log entry shape/params/revertability survive JSON
- conftest builders (`make_teeth/6hb/18hb/mini_hinge_design`) — feature-log replay reconstructs a fixture's canonical topology
- `overhang_candidate_error` / `valid_overhang_sites` — geometric feasibility of an overhang placement
- design-geometry kernel (`_geometry_for_design`, `_strand_nucleotide_info`) — nucleotide position + 5′/3′ terminus convention
- `assert_binding_resolves` (AF-9) — a metadata-only cross-part relation's endpoints resolve to live targets (surviv…
- `assert_instances_on_grid` / `assert_instances_on_ring` (AF-10) — placed instance origins form an exact regular lattice (grid: count + even pitch…
- `assert_spec_matches_calls` (AF-11) — a declarative build-spec is lowered to the SAME canonical structure as the equi…
- `assert_cluster_translated` (AF-15) — a cluster's DISPLAY-layer rigid-TRANSLATION pose actually shifts the cluster's …
- `assert_edges_collinear` (AF-15 P2) — a cluster's OBB edge shares one infinite line with a target edge/world line aft…
- OBB equivariance `OBB(g·design)=g·OBB(design)` (AF-15 P2) — the cluster OBB frame rotates WITH the cluster (half preserved, axes rotate, ce…
- `assert_joint_on_hull_corner` (AF-14 P1) — a revolute joint's world axis (re-derived from cluster-LOCAL storage via _local…
- `assert_range_of_motion` (AF-14 P2) — a revolute joint's collision-free swing about a world axis equals the expected …
- `assert_parallelogram_linkage` + `grubler_mobility` (capstone) — an ASSEMBLED multi-cluster mechanism is a valid parallelogram four-bar linkage:…
- `assert_cluster_in_feature_log` (AF-16) — a logged cluster-creation is recorded: exactly one cluster_create feature-log e…
- `assert_recommended_hinge` (AF-14 P3) — the #1 of a cluster's ranked hinge-edge recommendations is NOT parallel to the …
- `assert_fully_sequenced` (full-sequencing feature) — a design carries a complete, correct sequence: zero undefined bases (same count…
- `assert_relaxed_geometry_recovered` (AF-13 P1) — a headless oxDNA relaxation reached completed AND its relaxed last frame reads …
- `measure_end_to_end` + `assert_relaxed_measurement` (AF-13 P2) — the first STOCHASTIC-class oracle: a measured geometric property of the relaxed…
- `measure_segment_angle` (segment_angle measure) — the first ANGULAR + first 3-landmark relaxed-structure measure: the interior be…
- `measure_inter_helix_spacing` (inter_helix_spacing measure) — the first measure needing helix-axis grouping (vs the point-landmark measures):…
- `parse_constraint_spec` + `check_relaxed_constraint` (AF-13 P3) — a declarative relaxed-structure constraint {measure, landmarks, target_nm, tol_…
- `assert_relax_honors_hardware_default` (AF-17) — a benchmarked hardware default reaches the simulation: a headless relaxation tu…
- `iterate_to_constraint` + `assert_converges_to_constraint` (AF-13 P4) — the Tier-5 capstone: a CLOSED build→relax→production→measure→adjust loop conver…
- `assert_spec_constraints_reported` (AF-13 P5 — grammar `constraints` block) — a design spec's declarative constraints block is lowered to the SAME per-constr…
- `assert_periodic_chain_tiles` (`polymerize_periodic` straggler) — a SINGLE-part periodic polymer's AUTO-DERIVED repeat unit tiles the chain seaml…
- `assert_part_from_primitive` (AF-12 Phase 2 — `from_primitive` catalog-by-name) — a {"from_primitive": "<name>"} part instance resolves to exactly the catalog pr…
- `assert_part_is_circular_disc` (AF-12 Phase 2b — `from_primitive` PARAMETRIC circle) — a {"from_primitive": "<circle>", "params": {"radius_nm": R}} part instance is a…
- `assert_field_ready_specimen` (AF-18 — Tier 6 specimen spine) — the FIRST composite physical-layer oracle: an end-to-end-built design is ready …
- `measure_field_equilibration` + `assert_equilibration_timeline` (AF-19 — Tier 6 time-resolved) — the FIRST TIME-RESOLVED physical oracle: where measure_field_response (AF-18) i…
- `assert_field_sweep_map` (AF-20 — Tier 6 response surface) — the FIRST MULTI-config physical oracle: where every prior physical oracle (AF-1…
- `field_equilibrium_observables` + `assert_oxpy_equilibrium_parity` (AF-21 — Tier 6 interactive engine) — the FIRST oracle over a SECOND engine: every prior physical oracle (AF-13/18/19…
- `assert_live_field_following` (AF-22 — Tier 6 interactive control loop) — the FIRST oracle over a STEERED PATH of field changes: where assert_oxpy_equili…
- `assert_field_campaign` (AF-23 — Tier 6 CAPSTONE, cross-design study) — the FIRST MULTI-DESIGN physical oracle: where every prior physical oracle (AF-1…
- `assert_linker_connects` (AF-27 P1 — overhang-linker tie) — an overhang LINKER connection wires the two named overhangs at the requested co…
- `assert_flexible_segments_relaxed` (AF-29 — hinge ssDNA scaffold-tether relax) — a headless flexible-segment relax reached the SAME physical rest state the in-a…
- `assert_forced_ligation` (AF-32 — forced-ligation tie) — a forced ligation merged the named 3'/5' strand ends into ONE strand, recorded …
- `assert_matches_primitive` (AF-33 — hinge golden-equality) — a code-built hinge primitive is byte-for-byte the validated hand-built golden w…
- `assert_crossover_joins` (AF-31 — manual crossover place) — a manually-placed crossover RECORDED the two named half-sites AND (when ligated…
- `assert_scaffold_routing_compliant` (AF-34 — autoscaffold routing compliance) — a headless autoscaffold output is routing-compliant origami — a real seamed (or…
- `assert_primitive_placed` (AF-35 — multi-op primitive placement) — a whole pre-built primitive (a hinge: two rigid leaves + cross-gap forced-ligat…
- `_rail_faces_toward` (AF-36 — hinge phase-paired short/long routing) — which of a hinge's cross-gap rungs is SHORT vs LONG ssDNA, from helical PHASE n…
- seek-fidelity restore (AF-36 — `_topology_substitute` ← cluster_joints + flexible marks/connections) — a feature-log SEEK reconstructs the FULL state at a position INCLUDING joints +…
- `assert_linker_relaxed_pose` (AF-27 P2 — overhang-linker relax pose) — a headless "Relax Linker" pose pulled the linker toward its natural span, moved…
- `assert_bond_relaxed_pose` (AF-27 P2 — generic backbone-bond relax pose) — the assert_linker_relaxed_pose analog for the generic relax_bond (crossover / f…
- `assert_binding_relaxed_pose` (AF-38 — direct root-to-root BINDING relax pose) — the assert_linker_relaxed_pose analog for the DIRECT-binding relax (relax_overh…
- `assert_end_to_root_relaxed_pose` (AF-38 — end-to-root relax pose) — the end-to-root analog: strain =
- `assert_extension_present` (Phase 5 — terminal fluorophore/modification extension) — a terminal StrandExtension (added ACGTN sequence and/or a fluorophore/quencher/…
- `assert_duplex_relocated` (Phase 4b — different-length duplex relocation) — a DIFFERENT-length Duplex (no equal-length binding) relocated the DRIVEN overha…
- `assert_end_to_root_binder` (end-to-root direct binding — regenerate B as A's RC binder) — applying an end-to-root ConnectionVersion is a TOPOLOGICAL splice, not a metada…
- `assert_corner_folded` (CORNER — mitred-corner primitive + phase-aware optimizer, 2026-07-08) — a headless mitred 90° corner is correct across ALL THREE layers — the FIRST ora…
- `assert_bind_unbind_inverse` (AF-37 root-to-root half — direct-binding create/bind/unbind) — the FIRST oracle over the direct binding's TOPOLOGICAL half (every prior binding oracle — `assert_binding_relaxed_pose`, `assert_direct_binding_applied` — is pose-layer or apply-only): a bind→unbind cycle is a clean inverse pair. 4 clauses — non-vacuous (bind MOVED `canonical_topology`, guarding the AF-38/39 false-degenerate trap) / inverse (unbind restored it exactly) / overhang mounts moved-then-restored (`_overhang_placement_set` — `canonical_topology` is BLIND to `OverhangSpec` records, the same load-bearing-complement role `_fl_endpoint_set` plays for FLs) / record lifecycle (`bound` T→F, `prior_driven_topology` set→cleared). Reuse for: any op that RELOCATES a strand domain between helices under a snapshot+revert contract, and as the regression net for `synthesize_duplexes_from_bindings` when Proposal-B Phase 6 retires `OverhangBinding`. File: `tests/automation_harness.py`.

## Lessons (anti-patterns banked) — index

29 banked lesson blocks; full text in the archive's matching `### Banked from …` heading.
(The two AF-39 lessons — silent synthetic-fixture fallbacks + derive-don't-fish the degenerate — and the two
AF-37 lessons — the handoff's named oracle is a hypothesis + build fixtures on the real op — are in the
`## Lessons` section above, not the archive.)

- Banked from AF-2
- Banked from AF-3
- Banked from AF-1
- Banked from AF-4
- Banked from AF-5
- Banked from AF-6
- Banked from AF-7
- Banked from AF-8
- Banked from AF-9
- Banked from AF-9 belts
- Banked from AF-9 polymerize
- Banked from AF-9 overhang-bindings
- Banked from AF-10
- Banked from AF-11
- Banked from AF-11 Phase 2 (grammar growth — bend/twist)
- Banked from AF-11 Phase 2 (grammar growth — loop_skip)
- Banked from AF-11 Phase 2 (grammar growth — circle_segment)
- Banked from AF-11 Phase 2 (grammar growth — gear)
- Banked from the capstone (the 4-bar parallelogram)
- Banked from AF-18 (Tier 6 — field-specimen builder)
- Banked from AF-25 (feature-log seek)
- Banked from AF-12 Phase 2b (parametric `from_primitive` circle)
- Banked from `crossover_extra_bases` (design op — extra bases at crossover junctions)
- Banked from AF-31 (manual crossover place/delete)
- Banked from AF-32 (forced-ligation place/delete)
- Banked from AF-30 (strand end-resize)
- Banked from AF-33 (hinge-primitive builder, P1)
- Banked from AF-33 P2 (2x4/2x6 hinges)
- Banked from AF-36 (end-to-end hinge generation + phase-paired routing + seek fidelity)

> **History.** Oracle detail, full lesson blocks, per-loop entries + the ledger audit log live in [design_automation_log_archive.md](design_automation_log_archive.md). Read on demand only — never in a routine loop.
