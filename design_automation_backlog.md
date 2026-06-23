# design-automation backlog — UI-only / API-less operations → programmatic + validated

**Purpose.** NADOC has many operations a user can *only* perform with the mouse, and many more that
have a REST route but **no programmatic/headless entry point**. That gap blocks two goals at once:
**(1) automated correctness validation** (you can't pin what you can't drive headlessly) and
**(2) eventual text-to-DNA-origami** (an AI/script can only build what's reachable without a canvas).
This loop closes those gaps **one feature per session**, the same disciplined way the god-file carve-ups
(`backend_router_carveup.md`, `main_js_carveup.md`) and the fix loop (`issues_ledger.md`) work:
a ranked backlog, a per-session protocol, a metrics row in `design_automation_log.md`, a living handoff,
and **cross-loop intake** into the bug ledger + manual-validation debt.

It is a *feature-development* loop, so it is governed by **`FEATURE_DEVELOPMENT.md`** (the module-first
anti-backslip law). The carve-ups *shrink* god-files; this loop must not *re-grow* them. Read that file
before writing any feature.

> **⚠ THIS MAP IS SEQUENCING-ONLY.** Line numbers and route names drift. The audit below was taken
> 2026-06-16; before claiming any item, **re-derive its real surface** — does the REST route still exist,
> is it still UI-wired, what's the actual coupling. Fix the entry you touched on your way out.

---

## The two goals, and why validation comes first

The user chose **validation-first ranking**: rank by which missing API most unblocks *automated
correctness checks*, with text-to-DNA enablement as the tiebreaker. The logic: every headless wrapper we
add is only trustworthy if it ships with a way to *prove* it does the right thing. The validation harness
(Tier 0) and the per-feature oracles are therefore the spine — text-to-DNA (Tier 4) is built *on top of*
a validated wrapper library, not before it. A wrapper with no oracle is a liability, not an asset.

Tiers 0–4 pin the **topological + geometric** layers (deterministic — exact fingerprints, analytic
geometry). **Tier 5** extends the spine to the **physical layer**: drive oxDNA headlessly, *measure*
properties of the relaxed structure, and eventually iterate the design until a user constraint is met
("make these two ends 50 nm ± 5 nm apart"). That introduces a new, *stochastic* oracle class — a measured
property within tolerance, **gated by the confidence metric** (frames pooled / RMSF SE), not exact
equality — and is the concrete bridge from Tier 4's text-to-DNA grammar to *constraint-driven* design.

**Tier 6** extends Tier 5's physical-layer spine from *static* relaxed-structure properties to **time-resolved
electric-field response**: build a design end-to-end (route + sequence + overhang + anchor), subject it to an
E-field, and *measure how it aligns over time* — extracting an **equilibration timeline** (τ to plateau) and a
**non-destructive operating window** (aligns without melting), then **automatically sweeping field intensity ×
direction across many origami designs**. Same stochastic, confidence-gated oracle class as Tier 5, now over a
*trajectory* not a single mean structure. The capstone (AF-23) is the user's stated goal: automated cross-design
exploration of which fields align which structures, on what timescale, without ripping them apart. A parallel
sub-track (AF-21/22, gated on an **oxpy rebuild**, `-DPython=ON`) adds a persistent in-process engine for *live*
field steering — the "play with it in real time" capability — proven equivalent to the validated batch engine.

---

## Target shape (where new code lands — NOT the god-files)

Three shapes, and deciding which one an item wants is the first move:

1. **Headless wrapper** — a REST-backed design operation that has no programmatic entry → a thin function
   in **`backend/api/headless_build.py`** (the existing mouse-free construction module — the seed for
   AI-driven design). Mirror its existing wrappers (`create_bundle`, `extrude`, `auto_scaffold`,
   `overhang_extrude`, `full_autostaple`). It runs the *same* service the route runs; it does **not**
   duplicate logic. **Never** add the logic to `crud.py`/`assembly.py`.

2. **New headless module** — when a whole subsystem has no programmatic builder. The flagship case:
   **assembly has no headless builder** → a NEW `backend/api/headless_assembly_build.py` mirroring
   `headless_build.py` (scratch-session context manager + fluent ops). New module, not a god-file block.

3. **Service + oracle push** — when the operation's *logic* (not just its HTTP shell) belongs in a pure,
   testable place → a pure HTTP-free fn in **`backend/core/<area>.py`** + a **validation oracle** that
   pins its contract. `backend/core` may import nothing from `backend/api`.

Whichever shape: the **mandatory deliverable is a validation augment** (next section). A wrapper without
one does not ship.

---

## Improvement metric — the anti-shovel contract (this is the point)

The carve-up's failure mode was *LOC-shoveling*. This loop's failure mode is **passthrough-shipping:**
adding a `headless_build.foo()` that just forwards to `POST /design/foo` and calling it done — when it
added *no new validation power* and can't be trusted by an automated builder. That is not closing the
automation gap; it's lengthening the call chain.

So **"a wrapper exists" is never the pass criterion.** The pass criterion is:

### Primary metric — a reusable **validation augment** shipped with the feature
Every AF item ships **≥1 new automated oracle/pin** that proves the operation is correct, and that is
**reusable** by later items. Acceptable forms (mirror an existing pattern — see `design_automation_log.md`
"Oracle catalog"):
- **Round-trip equality** — build via the new wrapper → export `.nadoc`/`.nass` → import → assert
  `_canonical_topology` equal (the id/order-independent fingerprint from `test_section_router.py`).
- **Inverse-pair invariant** — op then its inverse → topology unchanged (e.g. nick→ligate, add→delete).
- **Geometric oracle** — the result's geometry matches an analytic expectation (mirror
  `derive_periodic_delta`, the circle circularity oracle, the section-router gap-clearance metrics).
- **`validate_design` gate** — the built design passes the topological validator (no unresolved nicks,
  consistent strand positions, correct domain count).
- **JS↔Python parity** — if the op has a frontend preview, its JS logic and the Python build pin to the
  same numeric oracle (mirror `circle_primitive_logic.js` ↔ `core/circle_primitive.py`).

### Secondary metrics (log the ones that moved)
- **Headless coverage** — REST design/assembly routes that now have a headless wrapper, before→after.
  (Tier 0 builds the automated coverage report so this number can't go stale.)
- **God-file LOC Δ** — `crud.py` / `assembly.py` / `main.js` must end **flat or lower**. A rise means
  logic crept into a god-file instead of `headless_build`/`backend/core` — extract before committing.
- **Cohesion** — the new wrapper/module's *one reason to change* in a sentence.

### The required justification line
Every metrics row ends with: **"Validation gained, not just a passthrough: ___"** naming the oracle
shipped and what it now proves that nothing proved before. If you can't write it honestly, you shipped a
passthrough — add the oracle or revert.

---

## Per-session loop protocol

A fresh session keeps token cost low. Per session:

1. **Read** this map (start with `## Next-session handoff`) + `design_automation_log.md` (conventions +
   oracle catalog + lessons + difficulties). Read `FEATURE_DEVELOPMENT.md` (module-first law). Skim the
   relevant `memory/project_*.md` for the area (e.g. `headless_build`, `assembly_overhaul`).
2. **Pick ONE item** — the handoff's `▶ NEXT`, or the topmost unchecked backlog entry, or one the user
   names. One AF item (or one phase of a multi-phase item) per session.
3. **Re-derive the surface (cheap, do it):** confirm the REST route still exists and what it expects
   (`rg "<url-fragment>" backend/api/`), and that it's still UI-wired (`rg "<fn>" frontend/src/api/`).
   A dead route is a *delete* candidate, not a wrap candidate — route it to `issues_ledger.md`.
4. **Decide the shape** (wrapper / new module / service+oracle push) and **pick the validation form**
   from the primary-metric list BEFORE writing code. The oracle is the acceptance test — write it first
   where practical (it should fail until the wrapper works).
5. **Build:** the wrapper in `headless_build.py` (or the new headless module / `backend/core` fn) +
   the validation augment (a direct unit/integration test in `tests/`). No god-file growth.
6. **Gate:** `just test` green — cite pass count, flag any *drop*. `just lint` clean on touched files.
   A feature without its validation augment does not ship.
7. **One item per commit** (`feat(automation): headless <op> + <oracle>`). Commit only when the user asks.
8. **Update the ledgers:** check the box here, add a metrics row to `design_automation_log.md` **with the
   mandatory justification line**, and **overwrite** `## Next-session handoff` (≤8 lines).
9. **Route what you found:** a bug → `issues_ledger.md` dossier. A genuinely UI-only op that can't be
   headless'd (pure pixel-gesture, no coord route) → push an `MV-N` row to `manual_validation_debt.md`
   (it's validated by hand, not automated). A stuck item → the log's difficulties ledger with *why*.

**Don't:** add operation logic to `crud.py`/`assembly.py`/`main.js`. Touch `_PHASE_*` or the mutation
contract (`mutate_and_validate`/`set_design_silent`/`snapshot`). Reason geometrically about crossover
placement (mechanical rules only — `feedback_crossover_no_reasoning`). Change a route URL.

---

## Single-line invocation

- **Slash command:** `/automate-feature` (optionally `/automate-feature AF-3` to name an item).
  Skill at `.claude/skills/automate-feature/SKILL.md` — loads this map + the log, picks the handoff's
  next item, re-derives its surface, and runs the protocol.
- **Plain prompt:** *"Run a design-automation feature loop"* / *"Work the next AF item."*

---

## Next-session handoff

> **■ LEDGER AUDIT 2026-06-21 (validity + goal-alignment sweep).** Every backlog item was re-checked against
> its REST route / harness fn (all exist — see the probes in `design_automation_log.md`) and against the two
> stated goals (automated validation testing; eventual text-to-design). **Findings:**
> 1. **No item is dead or off-goal.** Every open item still maps to a live route/function AND to a goal.
>    `routes_primitives.py` confirms AF-12's premise (GET-only catalog, no placement route → the gap is real);
>    `periodic_polymer.py` backs the AF-9 straggler; `headless_spec_build.py` has constraints attach+report but
>    NO knob clause yet (AF-13 P5 knob = genuinely open).
> 2. **Stale checkboxes fixed:** AF-14, AF-15, AF-PHOTO were fully shipped but left `[ ]` → now `[x]`. AF-9 has
>    all four sub-ops shipped; only the `polymerize_periodic` straggler is open.
> 3. **Handoff pruned:** ~5 superseded `▶ NEXT`/capstone pointers that directed the next session to
>    ALREADY-SHIPPED work (AF-13 P4, AF-16, the 4-bar capstone, AF-14 P2) were removed — they contradicted the
>    shipped state. The `▶ HARNESS NOW AVAILABLE` do-not-rebuild reference blocks (with banked gotchas) were KEPT.
> 4. **Genuinely-open, validated work, priority order:** (a) **AF-13 P5 KNOB clause** — lower a constraint+knob
>    spec to `iterate_to_constraint`; the constraint-driven text-to-design bridge, highest goal value. (b) **AF-12
>    primitives in the build-spec** (`from_primitive`/`from_file`) — reference saved validated parts by name; the
>    other text-to-design rung. (c) **`polymerize_periodic`** straggler (niche). (d) Assembly-level `constraints`
>    + the `bind_overhangs` spec op — both correctly DEFERRED (no assembly headless-oxDNA path; overhang-binding
>    not yet firmed). Nothing below needs deleting; the loop is healthy and converging on the two goals.

> **★ NEW PRIORITY TRACK 2026-06-22 — Tier 6: time-resolved E-field response (user request).** Scoped this session
> into six ranked loops (see `### Tier 6` below), capstone last. **Goal:** automate build→route→sequence→overhang→
> anchor → subject to an E-field → measure helical alignment + base-pairing *over time* → automatically sweep field
> intensity × direction across many origami, finding which fields align which structures on what timescale WITHOUT
> melting them. **This is the new top priority** — work it ahead of the AF-12/13 stragglers below. **Order + why
> validation-first:** **AF-18** (full-pipeline anchored field-specimen builder) → **AF-19** (equilibration-timeline
> τ + non-melt oracle — the key new physical observable) → **AF-20** (field sweep + |E|↔τ correlation map) → then the
> oxpy *interactive* sub-track **AF-21** (persistent in-process engine — **oxpy ✅ BUILT + venv-wired 2026-06-23**,
> `import oxpy` ready; see the Tier 6 as-built note) → **AF-22** (live field-steering + field-following oracle) →
> **AF-23 CAPSTONE** (cross-design
> automated campaign). **De-risk note:** AF-18→20 + AF-23's batch path ride the ALREADY-SHIPPED field child-job +
> `_FIELD_MOCK_OXDNA` (no GPU, no oxpy) — only AF-21/22 need the oxpy build. Each loop ships one reusable oracle per
> the anti-shovel contract. **AF-18 + AF-19 + AF-20 + AF-23 (CAPSTONE) SHIPPED 2026-06-23. ▶ START: AF-21** (oxpy
> persistent interactive engine — oxpy IS built + venv-wired, `import oxpy` ready; PARITY half is GPU-free against
> `_FIELD_MOCK_OXDNA`, the live-mutation half needs the real engine → gate with `pytest.importorskip("oxpy")`).
> **AF-22** (live field-steering, builds on AF-21) follows. The Tier-6 BATCH spine (AF-18→20→23) is now COMPLETE — the
> remaining Tier-6 work is the oxpy *interactive* sub-track (AF-21/22) only; everything else open is the AF-12/13
> text-to-design stragglers below (lower priority than finishing the interactive engine).

_Living pointer — each session overwrites this (step 8). **AF-23 CAPSTONE: cross-design automated field-response campaign —
SHIPPED 2026-06-23.** The user's stated goal: automatic exploration of which E-field intensities × directions align which
DNA structures, on what equilibration timescale, without ripping them apart, for VARIOUS designs. The first MULTI-design
physical experiment (AF-20 measured one response surface; this measures + compares a surface PER design).
`hox.run_field_campaign(specimens, intensities_pN, directions, ws, *, field_steps=2000, melt_floor=0.5, min_confidence=10,
timeout=30, anchor_stiff=…, **relax_params) → {"sweeps": {name: sweep}, "skipped": [(name, reason)], "names": […],
"intensities_pN": […], "directions": […], "melt_floor": …}` in `backend/api/headless_oxdna_build.py`. `specimens` = a list of
`{"name", "design": Design|build-spec, "anchor": {kind,id,…}, "overhang"?, "sequence"?}`; per design it runs
`build_field_specimen` (build→overhang→sequence→relax→anchor) then `sweep_field_response` in its OWN `ws/campaign/<i>_<name>`
subdir (so per-design job trees never collide). A design whose build/sweep raises is recorded in `skipped` (NOT dropped).
NEW oracle `assert_field_campaign(campaign, *, benign_range, destructive_range, expect_distinguishable=True, melt_floor=0.5,
min_tau_separation_steps=1.0, repro=None, tau_tol_steps=1e-6, min_tau_drop_steps=1.0)`: (1) no design dropped (skipped empty +
sweeps non-empty), (2) every design passes `assert_field_sweep_map` (a reported non-destructive window per design), (3)
**DISTINGUISHABILITY** — ≥2 designs differ at a shared responsive `(|E|,dir)` cell by ≥`min_tau_separation_steps` τ (the
load-bearing NEW assertion over AF-20: AF-20 pins ONE surface, this proves the campaign produces design-DISCRIMINATING
surfaces), (4) **reproducible** — if `repro` (a 2nd run) given, every shared design+cell τ matches within `tau_tol_steps`. Net
+4 tests (suite 3024→3028). Coverage FLAT 37 (no new route — composes `build_field_specimen` + `sweep_field_response`).
**ASK-FIRST honoured:** field dir + |E| + anchor are spec inputs, cells measure magnitudes (τ, projection, retention)._

**▶ HARNESS NOW AVAILABLE (AF-23 campaign, use it — do NOT rebuild):**
- `from backend.api import headless_oxdna_build as hox` → `hox.run_field_campaign(specimens, intensities_pN, directions, ws,
  *, field_steps=2000, melt_floor=0.5, min_confidence=10, **relax_params) → {"sweeps", "skipped", "names", …}`. Each
  `specimens` entry is the AF-18 `build_field_specimen` kwargs as a dict (`design` + `anchor` + optional `overhang`/`sequence`)
  + a `name`. Reuses the de-risked AF-20 batch path entirely; transparently swaps to the AF-21/22 oxpy fast path once built.
- **Augment = NEW `from tests.automation_harness import assert_field_campaign`** — `(campaign, *, benign_range,
  destructive_range, expect_distinguishable=True, melt_floor=0.5, min_tau_separation_steps=1.0, repro=None)`. Returns
  `{n_designs, n_distinguishing_cells, n_repro_cells, per_design}`. The distinguishability predicate recomputes each design's
  τ signature from raw `aligned ∧ bp_min ≥ melt_floor` (anti-echo, NOT `cell["destructive"]`).
- **GOTCHAS banked (read before AF-21):** (1) the AF-20 `_FIELD_SWEEP_MOCK` has a **design-INDEPENDENT** τ → two designs swept
  through it are IDENTICAL → it CANNOT exercise the distinguishability clause. AF-23 added a NEW
  `_FIELD_CAMPAIGN_MOCK_OXDNA`/`mock_oxdna_field_campaign` where `k = clamp((4.5−12·F0)·(540/N))` — N=particle count, so a
  bigger design → smaller k → shorter τ → DISTINGUISHABLE, while the melt threshold stays design-independent (`s_max=2.0 if
  F0≥0.4`) so the SAME benign/destructive bands hold for every design. (2) distinguishability shows at LOW |E| (2–4 pN): at
  high benign |E| both designs' k floor at 1.0 (shared) → equal τ there; the oracle only needs ONE differing shared cell, so
  this is fine, but a hand-built distinguishability check should read a low-|E| cell. (3) **the distinguishable fixture is 6hb
  vs 18hb** (`make_6hb_design`/`make_18hb_design`, both at `length_bp=42` → N≈528 vs 1536, a clean ~3× lever) each anchored on
  a REAL extruded ssDNA overhang via `_campaign_entry` (mirrors AF-20's `_sweep_specimen`: `extrude_valid_overhang` +
  `_define_overhang_bases`, `sequence=False`). (4) the indistinguishable RED test uses TWO IDENTICAL 6hb (different `name`s,
  same topology→same N→same τ). (5) the skipped RED test uses an anchor id that doesn't resolve → `build_field_specimen`
  raises → recorded in `skipped` (not dropped) → clause 1 fires. (6) coverage stays FLAT 37 — campaign wraps NO route.

**▶ HARNESS NOW AVAILABLE (AF-20 field sweep, use it — do NOT rebuild):**
- `from backend.api import headless_oxdna_build as hox` → `hox.sweep_field_response(specimen, intensities_pN, directions,
  ws, *, field_steps=2000, melt_floor=0.5, min_confidence=10) → {"map", "skipped", "intensities_pN", "directions",
  "melt_floor"}`. `specimen` = an AF-18 `build_field_specimen` result (`design`+relaxed `job`+`anchor`+`anchor_keys`). Each
  cell keyed `(pN_float, dir_tuple)`. Raises if the specimen's parent job is not `completed`.
- **Augment = NEW `from tests.automation_harness import assert_field_sweep_map`** — `(sweep, *, benign_range,
  destructive_range, melt_floor=0.5, tau_tol_steps=1e-6, min_tau_drop_steps=1.0)`. `*_range` are inclusive `(lo_pN, hi_pN)`.
  Returns `{n_cells, n_benign_safe, n_destructive, n_directions_checked}`. The non-destructive predicate is RECOMPUTED from
  `aligned ∧ bp_min ≥ melt_floor` (do not trust `cell["destructive"]`).
- **GOTCHAS banked (read before AF-21/23):** (1) the AF-19 `_FIELD_TRAJ_MOCK` has a **field-independent k** (flat τ) and
  **never melts** → it CANNOT exercise the AF-20 green path. AF-20 added a NEW `_FIELD_SWEEP_MOCK_OXDNA`/`mock_oxdna_field_sweep`
  where `k = max(1.3, 4.5 − 12·F0)` (stronger field → smaller k → smaller τ) AND, above `F0 ≥ 0.4`, dilates the free cloud
  about its own centroid by `(1+s)` with `s = 2·factor` → every free base-pair separation scales by (1+s) → melt. The dilation
  is centroid-symmetric so it **cancels in the MEAN along-field projection** (alignment still saturates ∝F0 and plateaus) —
  only `bp_min` drops. (2) `F0 = field_pN / 48.63` (`pn_to_oxdna_force`); the `F0≥0.4` melt threshold ≈ **19.5 pN**, so the
  green test uses intensities `[2,4,8,16,32]` → 16 pN benign, 32 pN destructive; `benign_range=(0,20)`,
  `destructive_range=(24,1e9)`. (3) the **flat-τ can-go-red can't use a mock** (a no-melt mock can't satisfy clause 3's
  non-vacuity) → it's pinned on a HAND-BUILT sweep dict with equal τ + one melted cell (mirrors AF-19's hand-built melt test).
  (4) coverage stays FLAT 37 — `sweep_field_response` reuses `append_field`; no route is wrapped. (5) **the sweep fixture
  anchors a REAL extruded ssDNA overhang, not a tagged internal domain** (an internal bundle domain is NOT a valid field
  anchor): `conftest.extrude_valid_overhang(design, length_bp=12)` (delegates to the `overhang_candidate_error` geometry
  oracle — no site reasoning) → `{"kind":"overhang","id":ovhg_id}` resolves to the WHOLE 12-nt overhang domain.
  **`make_6hb_design` is MULTI-scaffold** → `hb.full_sequence` (single active scaffold) leaves ~210 staple bases undefined;
  sequence with `_sequence_for_oxdna` (per-(helix,bp) WC across all scaffolds) instead. The ssDNA overhang has no WC partner
  → fill its bases via a domain-order slice splice (`_define_overhang_bases`, fixed-seed random ACGT); do **NOT** use the
  `POST /design/generate-overhang-sequences` route here — on a `_sequence_for_oxdna`-assigned 5′-overhang strand its resplice
  CORRUPTED the 42-bp body (defined the 12 overhang, undefined the body). `build_field_specimen`'s `overhang=` param can't
  mint the anchor id, so extrude FIRST then pass `overhang=None` + the overhang-id anchor + `sequence=False`.

**▶ HARNESS NOW AVAILABLE (AF-19 equilibration timeline, use it — do NOT rebuild):**
- `from backend.core.oxdna_health import measure_field_equilibration` — PURE `(frames, field_dir, anchor_keys, *,
  design, steps_per_frame=1.0, melt_floor=0.0, plateau_frac=1−1/e, plateau_slope_frac=0.3, min_rise_nm=0.5,
  monotone_tol_frac=0.15) → dict`. `frames` = the list `read_trajectory_frames_full(traj, design)` returns (maps keyed
  by `(helix,bp,dir)` with `backbone_position`+`a1`); frame 0 is the field-off reference. Anchored keys are EXCLUDED from
  the free-body projection. Needs `design` (for `base_pair_retention` per frame). Raises on <2 frames / zero field dir.
- **Augment = `from tests.automation_harness import assert_equilibration_timeline`** — `(job, ws, field_dir,
  anchor_keys, *, design, melt_floor=0.5, min_confidence=10)`. Locates the `kind=="field"` stage's `trajectory.dat`,
  reads frames, confidence-gates, runs the measure, asserts `converged` + finite positive `tau_steps` + `not melted`.
- **GOTCHAS banked (read before AF-20):** (1) `FieldRequest.steps` has a **1000 minimum** (pydantic 422 below it) — the
  field mock writes `max(2, steps//100)` frames, so `field_steps=2000`→20 frames clears `min_confidence=10`; to force an
  INCONCLUSIVE red-path call the oracle with `min_confidence=15` on a 1000-step (10-frame) run, don't pass steps<1000.
  (2) The existing `_FIELD_MOCK_OXDNA` writes ONLY `last_conf.dat` (no trajectory) — AF-19 added a NEW
  `_FIELD_TRAJ_MOCK_OXDNA`/`mock_oxdna_field_traj` fixture in `test_headless_oxdna_build.py` that emits a multi-frame
  field `trajectory.dat` with a SATURATING ramp `shift_i = sc·F0·(1−exp(−i/k))` (sc=100, k=n/4) — plateau ∝ F0 (reuse
  it for AF-20's |E|-sweep). (3) the mock's free beads translate TOGETHER so designed pairs stay formed (no melt) — the
  melt/non-converge can-go-red cases are pinned on HAND-BUILT frames against the pure measure, not the mock. (4) τ in
  STEPS needs `steps_per_frame` = stage.steps / n_frames; the oracle computes it from the field stage; the pure measure
  defaults to 1.0 (τ in frame units). (5) coverage stays FLAT 37 — the oracle reads the field trajectory the shipped
  child-job already writes; no route is wrapped.

**▶ HARNESS NOW AVAILABLE (AF-18 field-specimen builder, use it — do NOT rebuild):**
- `from backend.api import headless_oxdna_build as hox` → `hox.build_field_specimen(spec_or_design, ws, *, anchor,
  overhang=None, sequence=True, scaffold_name="M13mp18", timeout=30.0, **relax_params) → {design, job, anchor_keys,
  anchor}`. `spec_or_design` = a ready `Design` (deep-copied) OR a build-spec dict (lowered via `hs.build_design` — same
  grammar AF-11/12 use). `anchor` is the SAME descriptor `append_field`/`resolve_anchor_particles` take
  (`{"kind":"overhang","id":…}` / `{"kind":"cluster","id":…}` / `{"kind":"domain","strand_id":…,"domain_index":…}`).
  Raises `ValueError` if the anchor resolves to no nucleotides. Pass `min_bp_retained=0.0` for the mock binary.
- **Augment = NEW `from tests.automation_harness import assert_field_ready_specimen`** — `(result, design, ws, *,
  field_pN=4.0, field_dir=(0,0,1), …)`: composes fully-sequenced + relaxed-geometry-recovered + a PROBE field child
  (branched off `result["job"]`, anchoring `result["anchor"]`) that holds the anchor while the free part deflects along
  the field. Run under the **deflecting** mock (`mock_oxdna_field`/`_FIELD_MOCK_OXDNA`), not the plain `mock_oxdna`.
- **GOTCHAS banked (read before AF-19):** (1) `assert_relaxed_geometry_recovered`'s key-set-equality is EXACT only for
  DENSELY-populated bundles — a routed `auto_scaffold`+`full_autostaple` 6hb has geom 756 ⊃ oxDNA-order 630 (126
  strand-less lattice slots), so the FULL composite oracle is green on `_sequence_for_oxdna(make_6hb)` (504==504) but
  fails on a routed design; prove other build branches with `assert_fully_sequenced` + `canonical_topology` equality and
  skip the geometry clause. (2) tagging a domain `overhang_id` makes `full_sequence` SKIP it (no WC partner → `'N'`) →
  field 400s on undefined; when `sequence=True` use a `domain`/`cluster` anchor (no tag), or tag AFTER sequencing. (3)
  you can't build a specimen from an UNSEQUENCED design (relax 400s on undefined) — exercise the oracle's clause-1
  red-path by handing it a raw design as the `design` arg. (4) coverage is FLAT 37 — `build_field_specimen` is pure
  composition; the value is the chain + composite oracle, not a route.

**▶ HARNESS NOW AVAILABLE (AF-12 P2 `from_primitive`, use it — do NOT rebuild):**
- `from backend.api import headless_spec_build as hs` → `hs.build_assembly(spec, *, primitives_dir=None)` with a part
  defined as `{"from_primitive": "<catalog name>"}` instances a curated catalog primitive by name. `primitives_dir`
  overrides the catalog folder (default = the live workspace `Primitives` dir); pass an absolute `tmp_path` containing
  `<name>.nadoc` files for tests. Resolves NAME → `.nadoc` via `primitive_catalog.design_path`, then lowers through the
  EXACT `from_file` path (placeable by `add_part` / `place_grid` / `place_ring`; the instance is file-backed). An
  unknown name → `BuildSpecError` at BUILD time (parser is catalog-agnostic).
- **Augment = NEW `from tests.automation_harness import assert_part_from_primitive`** — `(assembly, instance_id,
  primitive_name, primitives_dir)`: independently re-resolves the catalog name through `primitive_catalog.design_path`,
  loads that primitive's `.nadoc`, and delegates to `assert_part_from_file`. The new load-bearing piece over `from_file`
  is the **name→catalog-path RESOLVER** (a name mapped to the wrong/renamed primitive is invisible to
  `canonical_assembly`). Compose with `assert_instances_from_file` + `assert_instances_on_grid` for a from_primitive
  layout. Can-go-red: wrong name → "DIFFERENT topology"; unknown name → "catalog has no primitive".
- **GOTCHAS banked:** (1) the catalog NAME is the file STEM (`6hb_primitive.nadoc` → `"6hb_primitive"`); names must pass
  `primitive_catalog.is_safe_id` (alnum + underscore, leading digit OK). (2) save a catalog `.nadoc` with
  `design.to_json()` (symmetric to the loader's `Design.from_json`). (3) coverage stays FLAT at 37 — `from_primitive`
  folds into `file_paths` and reuses `add_file_instance`/`place_file_*`, wrapping no new route. (4) only STATIC
  (file-backed) catalog primitives — a `metadata.primitive_kind` (parametric, e.g. circle) part is NOT yet supported
  (the resolver returns a static `.nadoc` path; a parametric kind needs a generative build path, deferred).

**▶ HARNESS NOW AVAILABLE (`polymerize_periodic` straggler, use it — do NOT rebuild):**
- `from backend.api import headless_assembly_build as hab` → `hab.polymerize_periodic(instance_id, count, *,
  direction="forward")` grows a periodic polymer from a SINGLE seed instance (no hand-defined mate — the repeat is
  auto-derived from the part's `is_periodic_seam` ligations via `derive_periodic_delta`). Route 422s without a
  resolvable seam, 400s on `count<2`. Seed fixture is light: `make_bundle_design([(0,0),(0,1)], L, HONEYCOMB,
  strand_filter="both")` + `forced_ligations=[_seam_for(h0,L), _seam_for(h1,L)]` (the `_seam_for` helper lives in
  `tests/test_headless_assembly_build.py` and `test_periodic_polymer.py`).
- **Augment = NEW `from tests.automation_harness import assert_periodic_chain_tiles`** — `(assembly, *, tol_nm=0.05,
  step_tol_nm=0.05, angle_tol_deg=0.5, min_step_nm=0.5) → {n_junctions, max_gap_nm, step_nm, angle_deg}`. Over the
  chain's rigid `seam0:*` junctions: (1) ≥1 junction (non-emptiness), (2) seamless tiling — copy-k `seam0:3p` world
  ≈ copy-(k+1) `seam0:5p` world via `_get_connector_world` (the resolver's machinery), (3) single repeat unit —
  every junction's `T_high@inv(T_low)` shares one translation length + rotation angle (magnitudes → direction-
  agnostic, holds for `both`), (4) step>min non-vacuity guard. **Load-bearing because `canonical_assembly` is blind
  to the placed geometry** — it sees the chain's structure survive `.nass` but not whether the derived delta tiles.
  Distinct from `assert_polymer_chain` (mate-seeded). Can-go-red: shove a copy → "open"; lone seed (no chain) →
  "nothing was polymerized".
- **GOTCHAS banked:** (1) the synthesized junctions are `joint_type=="rigid"` with `seam0:3p`/`seam0:5p` labels;
  filter on BOTH the type and the label prefix. (2) `seam0:*` connectors resolve LIVE from the design geometry (the
  frozen-chain fix), so `_get_connector_world` recomputes the seam each call — pass the instance-overridden design.
  (3) the 2-seam HC bundle's delta is a LEAST-SQUARES Kabsch fit, so use `tol_nm=0.05` (route test's atol), not 0.01.
  (4) flipping `polymerize_periodic_assembly` → covered bumps the hardcoded coverage count in THREE tests
  (`test_oxdna_coverage_report...`, `test_cluster_obb::...adds_no_coverage`, `test_headless_spec_build::...adds_no_coverage`)
  36→37 — grep `covered"] == 36` before committing any future coverage flip.

**▶ HARNESS NOW AVAILABLE (AF-12 follow-up — file-backed layout, use it — do NOT rebuild):**
- `from backend.api import headless_assembly_build as hab` → `hab.place_file_grid(path, rows, cols, *, pitch,
  row_pitch=None, plane="XY", center=False, name="Part")` / `hab.place_file_ring(path, n, *, radius, plane="XY",
  start_angle_deg=0.0, center=(0,0,0), name="Part")` — the file-backed twins of `place_grid`/`place_ring`: identical
  per-slot translations, but each slot drives `add_file_instance(path)` (one path reference per copy, not embedded
  designs). Via the grammar: a `{"from_file": …}` part placed by a `place_grid`/`place_ring` op now parses + builds
  (the rejection was removed); the interpreter dispatches on `part in file_paths`.
- **Augment = NEW `from tests.automation_harness import assert_instances_from_file`** — `(assembly, expected_topology,
  *, instance_ids=None)`: loads the design behind EVERY selected slot and asserts each is file-backed and resolves to
  `expected_topology` (pass `canonical_topology(saved)`), with a non-vacuity guard. **Layout-agnostic source pin** —
  compose it with `assert_instances_on_grid`/`_on_ring` (lattice) for the full file-backed-layout proof. It's the
  plural of `assert_part_from_file`: a one-slot check misses a layout that file-backed slot 0 and embedded inline copies
  for the rest. Can-go-red: inline slot anywhere → "not file-backed"; wrong topology → "DIFFERENT topology"; empty
  selection (`instance_ids=[]`) → "selected no instances".
- **GOTCHAS banked:** (1) use an ABSOLUTE `tmp_path` .nadoc — resolves for both the from_file load AND the `.nass`
  round-trip flatten (`_PROJECT_ROOT / abs == abs`). (2) the can-go-red "inline slot" red-test builds a MIXED assembly
  (`place_file_grid` + an `add_inline_instance`) in a scratch session, not via `build_assembly`. (3) coverage stays flat
  — `place_file_*` wrap no new route (they loop the already-covered `add_file_instance`).

**▶ HARNESS NOW AVAILABLE (AF-12 P1, use it — do NOT rebuild):**
- `from backend.api import headless_spec_build as hs` → `hs.build_assembly(spec)` with a part defined as
  `{"from_file": "<path>"}` in `spec["parts"]` instances a saved validated `.nadoc` by reference. The path resolves the
  way the assembly routes resolve it (`_load_design_from_source`: absolute, or relative to workspace / assembly parent /
  project root); an absolute `tmp_path` file works for both the oracle AND the round-trip flatten (`_PROJECT_ROOT / abs
  == abs`). File parts may be placed by `add_part` (one reference) OR by `place_grid`/`place_ring` (per-slot references,
  AF-12 follow-up above).
- **Augment = NEW `from tests.automation_harness import assert_part_from_file`** — `(assembly, instance_id,
  expected_topology)`: loads the design the file instance actually references and asserts its `canonical_topology` ==
  `expected_topology` (pass `canonical_topology(saved_design)`), after asserting the instance is genuinely file-backed.
  **Load-bearing because `canonical_assembly` keys a file source by `("file", path, sha256)` ONLY — it never loads the
  design** — so `assert_spec_matches_calls` is blind to whether the path resolves to the intended topology. Can-go-red:
  wrong-topology substitute → "DIFFERENT topology"; pointed at an inline instance → "not file-backed".
- **GOTCHAS banked:** (1) discriminate file-vs-inline part by the `from_file` KEY (an inline part is also a dict but
  carries `ops`); a half-inline/half-file dict (`from_file` + `lattice`) is rejected by the `_FILE_PART_KEYS` whitelist.
  (2) `build_assembly` opens its OWN `assembly_scratch_session`, so the augment test calls it directly (no outer
  session); the roundtrip test needs the outer session like the other `assert_assembly_roundtrip_stable` callers.
  (3) save a part with `design.to_json()` (symmetric to the loader's `Design.from_json`). (4) Phase 2 (`from_primitive`
  catalog-by-name) is the remaining text-to-design rung — the design-level catalog has NO headless instancing path yet
  (only the circle disc), so it needs a name→part resolver, not just a grammar branch.

**▶ HARNESS NOW AVAILABLE (AF-13 P6, use it — do NOT rebuild):**
- `from backend.api import headless_spec_build as hs` → `hs.build_and_optimize_design(spec, workspace, *,
  max_iterations=8, production_steps=6000, tuned=False, **relax_params) →` the `hox.iterate_to_constraint` result
  (`{status, knob, job, iterations, verdict}`). Spec needs an `optimize` block (a spec WITHOUT one → `BuildSpecError`
  at parse time — that's the attach+report path `build_and_check_design`). The optimized op list must build a
  FULLY-SEQUENCED design EACH iteration (e.g. `bundle → bend → auto_scaffold → full_autostaple`; the bend survives the
  routing — it's a geometric overlay). `knob.response` is the spec author's declared monotonicity ("decreasing" = the
  measure FALLS as the knob rises, e.g. bend curvature ↑ → end-to-end ↓), lowered to the bisection direction in
  `_synth_bisection` — the grammar never reasons about bend sign.
- **Augment = reuse `from tests.automation_harness import assert_converges_to_constraint`** (the AF-13 P4 oracle):
  `(result, *, target_nm, tol_nm, min_confidence)`. Load-bearing because `assert_spec_matches_calls` is BLIND both to
  the bend overlay AND to a physical-layer convergence — the fingerprint can't see whether the knob hit target.
  Can-go-red: unreachable target → exhausted ("did not converge"); initial knob on-target → vacuous ("FIRST attempt").
- **GOTCHAS banked:** (1) a 2-helix bundle does NOT fully sequence via `full_autostaple` (84/168 undefined) — use the
  6hb (`SIX_HB_CELLS`) for an optimize fixture, NOT the 2-helix bend fixture. (2) the monotone profile must be checked
  per-landmark-PAIR: a single-helix bp0→bp41 end-to-end on the 6hb is NON-monotone (off-axis swing); `h_XY_1_2`
  bp0-fwd→bp41-rev IS monotone-decreasing (κ 2.0→12.68, 2.5→12.06, 3.0→11.32 nm), so target 12.0/tol 0.5/initial κ=2.0
  converges `2.0→3.0→2.5` in 3 deterministic bisection steps. Probe a candidate profile with
  `measure_end_to_end(_geometry_for_design(build(κ)), a, b)` (mock is identity → geometry == relaxed mean). (3) reuse
  `_MOCK_OXDNA_TRAJ` + the `mock_oxdna_traj` fixture; `production_steps=6000`→60 frames clears `min_confidence=50` in one
  round.

**▶ HARNESS NOW AVAILABLE (AF-13 P5, use it — do NOT rebuild):**
- `from backend.api import headless_spec_build as hs` → `hs.build_and_check_design(spec, workspace, *, steps=6000,
  tuned=False, **relax_params) → {"design": Design, "verdicts": [verdict,…]}`. Spec must build a FULLY-SEQUENCED
  design for the relaxation (e.g. `bundle → auto_scaffold → full_autostaple`; verified 0 undefined bases). With NO
  `constraints` block → `verdicts == []` and **no oxDNA run** (workspace untouched). `tuned=True` relaxes on the
  benchmarked hardware default (AF-17). Lower-level: `hs.check_design_constraints(design, parsed.constraints, ws, …)`.
- `from tests.automation_harness import assert_spec_constraints_reported` — `(spec_result, hand_verdicts, *,
  measured_tol=1e-6)`: asserts the grammar reports the SAME per-constraint verdict (status + `met` + `measured_nm`) a
  hand-driven `check_relaxed_constraint` yields, with non-vacuity + count-mismatch guards. **Load-bearing because
  `assert_spec_matches_calls` is BLIND to a physical-layer verdict** (the fingerprint can't see a constraint at all).
  Can-go-red: status mismatch, measured divergence (wrong-helix resolution), count mismatch, empty-list vacuity.
- **GOTCHAS banked:** (1) a constraint landmark is `{helix:[r,c], bp_index, direction}` (grid_pos, like nick/ligate),
  NOT a runtime id — the driver resolves it; `radius_of_gyration` takes NO landmarks. (2) The cell is normalised to a
  `(r,c)` TUPLE before handing to `parse_constraint_spec` so the `(hid,bp,dir)` triple stays hashable (it dedups
  landmarks with `set()` — a raw `[r,c]` list would `TypeError`). (3) The mock relaxation is identity, so the relaxed
  mean reproduces the DESIGN geometry → the spec and hand verdicts are deterministic + equal; use wide `tol` to get a
  clean `met` for the augment. (4) Reuse `_MOCK_OXDNA_TRAJ` (multi-frame; `steps=6000`→60 frames clears the
  confidence gate); import the CONSTANT not the fixture (F811).

**▶ NEXT — pick one (design `constraints` + `optimize`/knob loop wired; AF-12 `from_file` + file-backed layout +
`from_primitive` STATIC catalog-by-name shipped; remaining work + stragglers):**
- **AF-12 Phase 2b — `from_primitive` for the PARAMETRIC circle disc [the next text-to-design rung]:** a `parts` entry
  `{"from_primitive": "small_circle", "radius_nm": 12}` resolving against a catalog primitive flagged
  `metadata.primitive_kind="circle"`. **The static name→path resolver SHIPPED** (`_resolve_primitive_path`); this rung
  needs a *generative* branch instead — detect `primitive_kind` (read it off the catalog `.nadoc`'s metadata), and for a
  circle build the disc headlessly via `hb.circle_segment(radius)` rather than file-referencing the saved disc. The part
  is then NOT file-backed → `assert_part_from_primitive` (file-source pin) won't apply; reuse `assert_circular_disc`
  (the AF-4 geometric oracle) to prove the placed disc has the requested radius. Likely an ASK-FIRST call on how a
  parametric primitive carries its param into an assembly part (a design-level circle is a single-design op, but an
  assembly `add_part` instances a whole Design — decide whether the disc is built as its own part-Design first).
- **AF-12 Phase 2c — hinge / assembly-template primitives:** a catalog primitive that is an assembly-level *template*
  (leaves + a revolute mate recipe), not just geometry — parts carrying small mate recipes. Bigger architecture call;
  defer until a concrete hinge primitive exists in the catalog.
- **Multi-knob / richer knob shapes (optional grammar growth):** `optimize` today varies ONE numeric op param via
  bisection. A vector knob (two params) would need a non-bisection `adjust_fn` (e.g. coordinate descent) the grammar
  synthesises — only worth it when a real two-DOF constraint shows up. A `loop_skip count` or `length` knob also works
  today (any numeric op param), only the bend was fixture-proven; pick a monotone landmark pair per the P6 GOTCHA.
- **Assembly `constraints`** — `build_and_check_design`/`build_and_optimize_design` are design-only; an assembly spec's parts could carry
  constraints (parsed today, IGNORED by the assembly driver). Wire an assembly-level relaxed constraint if/when an
  assembly headless oxDNA path exists (none yet).
- **Stragglers:** `polymerize_periodic` SHIPPED 2026-06-22 (`hab.polymerize_periodic` + `assert_periodic_chain_tiles`).
  Remaining: `bind_overhangs` ASSEMBLY spec op (DEFERRED pending overhang-binding firming).

**▶ HARNESS NOW AVAILABLE (AF-13 P4, use it — do NOT rebuild):**
- `from backend.api import headless_oxdna_build as hox` → `hox.iterate_to_constraint(...)`. `build_fn(knob)→Design`
  must return a FULLY-SEQUENCED design (oxDNA 400s on undefined bases). `adjust_fn(knob, verdict)→next_knob` is the
  caller's domain knowledge of how the knob maps to the measure — only ever called on `unmet`. `constraint` is a raw
  AF-13 P3 spec (validated once up-front via `parse_constraint_spec`, so a malformed spec raises `ConstraintSpecError`
  before any run — pinned by `test_iterate_rejects_bad_constraint`).
- `from tests.automation_harness import assert_converges_to_constraint` — `(result, *, target_nm, tol_nm,
  min_confidence=RMSF_PRELIM_FRAMES)`. Asserts status=="met" + winning verdict confidence-gated + NO step flipped
  `met` below `min_confidence` + final within tol + **first attempt NOT already met** (non-vacuity). Can-go-red:
  exhausted run (`test_iterate_oracle_fires_on_exhaustion`, unreachable target), vacuous (`..._on_vacuous_convergence`,
  initial knob on-target).
- **The augment fixture (reuse this for any mock-binary convergence demo):** a **bend-curvature knob** on a 2-helix
  HONEYCOMB bundle (`_build_bent_bundle`/`_bisect_kappa` in `test_headless_oxdna_build.py`). KEY INSIGHT: the identity
  mock can't move atoms, so the relaxed mean reproduces the DESIGN geometry — therefore a **topology** knob (the bend)
  is what moves the measured end-to-end, *not* the relaxation. Probed monotone profile (deg/bp→nm): 0→13.74, 2.0→12.64,
  2.5→12.04, 3.0→11.33; **landmarks stay stable across curvatures because a bend is a deformation overlay, not a
  topology change** (fixed `(helix_id, bp_index, direction)` keys). Bisection converges in ~3 iterations.
- **GOTCHAS banked:** (1) the inner production-growth loop relies on the rmsf route pooling EVERY production stage's
  frames — `append_production(steps=1000)` adds 10 frames/round (`_MOCK_OXDNA_TRAJ`, `max(1,steps//100)`), so
  `min_confidence=25` needs ≥3 rounds (`test_iterate_grows_production_on_inconclusive`). (2) The oracle's non-vacuity
  guard means a convergence demo MUST start off-target — for the `met`-on-attempt-0 case (the inconclusive test) assert
  on `result` fields directly, NOT via `assert_converges_to_constraint`. (3) NO ASK-FIRST was needed: the loop is
  direction-AGNOSTIC end-to-end — curvature is a magnitude, end-to-end is Euclidean, the bend wrapper is AF-6's cleared
  machinery; zero frame/sign reasoning entered the driver or the fixture.

**▶ REFERENCE (the Tier-5 oxDNA spine is COMPLETE; all four planned `measure_*` kinds — `end_to_end`,
`radius_of_gyration`, `segment_angle`, `inter_helix_spacing` — DONE; the design `constraints` block is now WIRED, AF-13
P5 above — the live ▶ NEXT is the top-of-file handoff):**
- **Adding any further `measure_*` is now fully templated.** Point-landmark measure = name + arity +
  `_dispatch_measure` arm + `assert_relaxed_measurement` branch + analytic pins (reuse segment_angle as template).
  An axis/helix-grouping measure = same tail + a `_fit_helix_axis`-style grouping core (reuse inter_helix_spacing).
  No remaining measure needs new arity machinery.
- **Stragglers:** `polymerize_periodic` SHIPPED 2026-06-22 (`hab.polymerize_periodic` + `assert_periodic_chain_tiles`).
  Remaining: `bind_overhangs` ASSEMBLY spec op (DEFERRED pending overhang-binding firming).

**▶ HARNESS NOW AVAILABLE (AF-17, use it — do NOT rebuild):**
- `from backend.api import headless_oxdna_build as hox`. **Auto-tune a relaxation:** `hox.run_relaxation_tuned(
  design, ws, *, hostname=None, **relax_params) → terminal OxdnaJob` — resolves `metadata.hardware_defaults[host]`
  → backend/device and relaxes on it (CPU/"0" fallback when none). Explicit `backend=`/`device=` in `**params`
  override. **This is what AF-13 P4 should call per iteration** instead of `run_relaxation` (which is hard-coded
  CPU by the caller). **Run a benchmark headlessly:** `hox.run_oxdna_benchmark(design, ws, *, steps=, configs=,
  runner=) → result dict` (carries `["recommendation"] = {backend, device, steps_per_s, proxy_nucleotides}`,
  `["note"]`, `["state"]`). **Persist it:** `hox.apply_oxdna_benchmark(design, recommendation, *, hostname=) →
  new Design` (a COPY; original untouched). Pure read side: `from backend.core.benchmark import
  resolve_oxdna_relax_config` `(HardwareBenchmark | None) → {backend, device}`.
- `from tests.automation_harness import assert_relax_honors_hardware_default` — `(design, ws, *, backend,
  device="0", **params) → tuned OxdnaJob`: pass a design with NO `hardware_defaults` for this host and a NON-CPU
  config; it proves the baseline falls back to CPU AND the applied default reaches the job's `backend`/`device`.
- **GOTCHAS banked:** (1) `run_oxdna_trials` rmtree's its workdir on exit, so `run_oxdna_benchmark` runs in a
  `ws/benchmark_runs/<id>` SUBDIR — never hand it the bare workspace or it wipes a sibling relaxation's job dir.
  (2) `run_oxdna_trials` calls `find_oxdna()` BEFORE the injected `runner`, so even a stub-runner test needs
  `$OXDNA_BIN` set (the `mock_oxdna` fixture). (3) the per-trial label passed to `runner` is `bench-<id>-<i>`
  (config INDEX, not the config label) — key any stub timing off the trailing index. (4) **this dev box HAS a
  GPU** (RTX 2080 SUPER), so the real `oxdna_config_grid` includes a CUDA trial and `pick_best_oxdna` returns
  CUDA on the mock (tie-break prefers CUDA) — a producer test must be backend-agnostic (`in {"CPU","CUDA"}`), not
  assume CPU. (5) the mock binary ignores the declared backend, so requesting CUDA headlessly completes GPU-free —
  that's what makes the bridge oracle testable without a real device.

**▶ HARNESS NOW AVAILABLE (AF-13 P3, use it — do NOT rebuild):**
- `from backend.core.oxdna_health import parse_constraint_spec, check_relaxed_constraint, ConstraintSpecError`.
  `parse_constraint_spec(spec)` → normalised `{measure, landmarks:[(hid,bp,dir),…], target_nm, tol_nm,
  min_confidence}` (landmarks → tuples, direction enum→str; **idempotent** on its own output; `min_confidence`
  defaults to `RMSF_PRELIM_FRAMES`=50). `check_relaxed_constraint(constraint, relaxed_output)` takes a RAW or
  parsed constraint (it re-parses) + the dict `hox.read_flexibility_map` returns (`{ready, positions,
  confidence:{n_frames,…}}`) → the verdict dict. **It is PURE — `backend/core` takes the already-read dict and
  never imports `headless_oxdna_build`** (the api read-wrapper); the *caller* fetches the map then hands it in.
- **The three statuses:** `met` (n_frames ≥ min_confidence AND |measured−target| ≤ tol), `unmet` (enough frames,
  out of tol), `inconclusive` (too few frames OR no production mean structure yet). `measured_nm` is still
  reported when positions exist (so a loop watches convergence) but `met` follows `status` strictly.
- **GOTCHAS banked:** (1) the confidence gate is the whole point — AF-13 P4's iterate loop MUST branch on
  `status`, never on `measured_nm` alone, or it will converge on a noisy low-frame estimate. (2) tolerance
  boundary is inclusive (`<=`); float-exact test values (target 4.5/tol 0.5 on a 5.0 nm measurement) avoid the
  `4.6 → 0.40000…036 > 0.4` trap. (3) adding the next `measure_*` kind = add a `measure_*` fn next to
  `measure_end_to_end`, add the name to `_CONSTRAINT_MEASURES`, and add a dispatch arm in `check_relaxed_constraint`
  (currently it calls `measure_end_to_end` directly since parse pins the only measure). (4) the checker is now
  wired into `build_spec.py` by AF-13 P5 — a design `constraints` block lowers to `hs.build_and_check_design`.

**▶ HARNESS NOW AVAILABLE (full-sequencing feature, use it — do NOT rebuild):**
- `from backend.api import headless_build as hb` → `hb.full_sequence(scaffold_name="M13mp18", *, custom_sequence=,
  strand_id=)` fully sequences a **routed single-scaffold** origami (assigns the scaffold sequence to every scaffold
  strand, then WC-complements every staple → zero undefined bases, export/oxDNA ready). `hb.assign_staple_sequences()`
  is the bare WC-complement-staples wrapper (422s without a scaffold sequence). **Needs `auto_scaffold` first** on a
  raw bundle (one scaffold strand per helix won't cover the staples — the staple complement is taken from the single
  *active* scaffold). Coverage **35 → 36** (`assign_staple_sequences` flipped).
- `from tests.automation_harness import assert_fully_sequenced` — `(design, *, require_wc=True) → n_WC_checked`:
  zero undefined bases (the `create_oxdna_job` / export gate) AND every scaffold-paired staple base is the WC
  complement of its scaffold base (checked independently of the assignment code). This is the cleaner way to get a
  sequenced design for the AF-13 oxDNA fixture than the `_sequence_for_oxdna` test helper. Can-go-red: unsequenced →
  "undefined"; wrong base → "WC complement".

**▶ HARNESS NOW AVAILABLE (AF-13 P1, use it — do NOT rebuild):**
- `from backend.api import headless_oxdna_build as hox`. **One-call:** `hox.run_relaxation(design, workspace, *,
  timeout=30.0, min_bp_retained=0.0, backend="CPU", mc_steps/md_relax_steps/equil_steps=100, …) → terminal
  OxdnaJob` (create no-autostart → start → poll). **Lower-level:** `create_job` (returns dict, read `["job_id"]`)
  / `start_relaxation(job_id, ws)` / `append_production(job_id, ws, *, steps)` / `read_relaxed_positions(job_id,
  ws)` (drives the display route → `{ready, positions, n_positions}`) / `wait_for_terminal(job_id, ws, *,
  timeout)`. Each route wrapper temporarily redirects `routes_oxdna._WORKSPACE_DIR` (a `_use_workspace` cm) and
  `create_job` binds the design into a scratch doc (`_scratch_design`) so nothing touches the real workspace /
  active design. Route handlers are `async` → driven via `asyncio.run`.
- `from tests.automation_harness import assert_relaxed_geometry_recovered` — `(job, design, workspace, *,
  expected_count=None)`: status `completed` + display reads back exactly one finite position per design
  nucleotide, every key a real `(helix_id, bp, dir)`. Returns the display dict. Can-go-red: non-completed job →
  "did not reach completed"; wrong count → "expected …".
- **GOTCHAS banked:** (1) **the design must be FULLY SEQUENCED** — `create_oxdna_job` 400s on any undefined base;
  reuse `_sequence_for_oxdna` (M13 + WC complements) from `test_oxdna_relaxation.py`. (2) **The mock binary does
  NOT relax** (it copies conf→last_conf), so pass `min_bp_retained=0.0` or the bp-retention gate fails the job
  (mirrors `test_runner_end_to_end`). Real GPU runs raise it back to ~0.5. (3) `get_oxdna_display` is a **GET**
  (read-only) → correctly absent from the *mutation* coverage audit; it's pinned instead by the
  import-identity test. (4) Reuse the `mock_oxdna` fixture by copying its 6-line body from `_MOCK_OXDNA` (a
  cross-module pytest fixture import trips ruff F811).
- **The Three-Layer Law is the spine of the rest of Tier 5:** oxDNA output is read back as a Physical-layer
  position map and **never written into `Design`**. AF-13 P1 exposes ONLY the read path. Phase 4's iterate loop
  will EDIT topology (a knob) and RE-RELAX — it must never write the relaxed coords back.

**▶ HARNESS NOW AVAILABLE (AF-13 P2, use it — do NOT rebuild):**
- `from backend.core.oxdna_health import measure_end_to_end` — pure `(positions, landmark_a, landmark_b) →
  distance_nm`. `positions` = the per-nucleotide list from `production_rmsf` (mean structure) OR the display
  readback; each landmark = a `(helix_id, bp_index, direction)` tuple (direction may be the `Direction` enum or
  its string value — normalised). Raises on empty map / identical landmarks / absent landmark (no silent 0/NaN).
  This is the reusable `measure_*` primitive — add `measure_radius_of_gyration` / `measure_inter_helix_spacing`
  / `measure_segment_angle` here the same way for the other constraint kinds.
- `from backend.api import headless_oxdna_build as hox` → `hox.read_flexibility_map(job_id, ws)` drives the REAL
  `GET /oxdna/jobs/{id}/rmsf` → `{ready, positions (mean backbone xyz per nuc), confidence:{n_frames, rel_error,
  preliminary}, …}`. **Needs a prior `append_production` run** (returns `{ready:False}` until production frames
  exist). The mean cancels thermal noise; prefer it over `read_relaxed_positions` (single frame) for measurement.
- `from tests.automation_harness import assert_relaxed_measurement` — `(job, measure_spec, target_nm, tol_nm, *,
  workspace, min_confidence=RMSF_PRELIM_FRAMES)`: status-completed + reads the mean structure + **confidence gate**
  (≥ `min_confidence` pooled frames else "INCONCLUSIVE"-raise) + measured ∈ [target±tol]. `measure_spec =
  {"measure":"end_to_end","landmarks":[a,b]}`. Returns `{measured_nm, target_nm, tol_nm, n_frames, confidence}`.
- **GOTCHAS banked:** (1) **The shared `_MOCK_OXDNA` writes NO `trajectory.dat`** → the rmsf route has no frames
  → `{ready:False}`. AF-13 P2's tests use a purpose-built `_MOCK_OXDNA_TRAJ` (in `test_headless_oxdna_build.py`)
  that also emits a multi-frame `trajectory.dat` (frames = `max(1, steps//100)`, the input conf repeated). Reuse
  it for any oxDNA test needing a mean structure. (2) **`ProductionRequest.steps` has a 1000 minimum** — to get a
  *few*-frame (preliminary/low-confidence) run pass `steps=1000` (→10 frames), not <1000 (pydantic 422). (3) The
  mock is identity (last_conf == input conf), so the relaxed mean reproduces the **design's own** end-to-end
  (~0.002 nm gap) — the absolute target in the test is `measure_end_to_end(_geometry_for_design(design), a, b)`;
  a real GPU run moves atoms so the target would be the user's desired distance. (4) `get_oxdna_rmsf` is a GET →
  pinned by `hox._route_get_rmsf is routes_oxdna.get_oxdna_rmsf`, NOT the mutation-coverage count.

_[AUDIT 2026-06-21: removed the superseded "▶ NEXT — AF-13 Phase 4" pointer here — P4 SHIPPED 2026-06-19. The
live open work is the top-of-file handoff (P5 knob clause + stragglers).]_

**▶ HARNESS NOW AVAILABLE (AF-16, use it — do NOT rebuild):**
- `from backend.api import headless_build as hb` → `hb.add_cluster(name, helix_ids, *, domain_ids=(), log=False)`.
  `log=True` appends a `ClusterCreateLogEntry` (`feature_type="cluster_create"`, fields `cluster_id`/`name`/
  `helix_ids`/`domain_ids`) to `design.feature_log` with the same cursor-truncation as `update_cluster`'s commit+log.
  Default `log=False` — backward-compatible, so the capstone + all existing cluster tests are unaffected.
- `from tests.automation_harness import assert_cluster_in_feature_log` — `(design, cluster_id, *,
  expect_helix_ids=None)`: exactly one `cluster_create` entry for `cluster_id`, helix set == the live cluster's
  (or `expect_helix_ids`), name matches. **canonical_topology is BLIND to clusters** (the loop/skip / deformation /
  pose blind-spot, 4th time), so this entry is the ONLY proof a grouping persisted — call it on a `roundtrip_nadoc`
  result to pin `.nadoc` survival. Can-go-red: unlogged build → no entry → raises.
- **GOTCHA banked:** `add_cluster` uses `design_state.set_design` (undo-pushing), NOT `mutate_and_validate` — the
  log append rides inside the single `copy_with(...)` that already builds `cluster_transforms`, so it's one undo
  step. The cursor truncation (`feature_log[:cursor+1]`) matters only if a logged `add_cluster` follows an undo;
  mirror `update_cluster` exactly and it's correct.
- **Follow-up (optional):** the capstone `build_parallelogram` clusters its 4 bars with `log=False`; switching to
  `log=True` would make its generated feature log truly complete (the AF-16 motivating use case) — cosmetic, the
  linkage oracle doesn't read the log.

**▶ HARNESS NOW AVAILABLE (AF-14 P3, use it — do NOT rebuild):**
- `from backend.core.cluster_obb import recommend_hinge_joints` — `(design, cluster_id, *, anchor="corner",
  axial_tol_deg=20.0, target_rom_deg=None, …) →` all 12 OBB edges ranked best-first
  (`{edge, edge_length, angle_to_axis_deg, is_axial, rom_deg, axis_origin, axis_direction}`). Priority:
  **non-axial first → longest edge → ROM tiebreak.** `axis_origin` honours `anchor`; axial (`w`) edges demoted
  to the tail but still present (so a caller can see them / a red-test can find one).
- `hull_prism_axis(…, edge=key, anchor="corner")` + `hb.place_cluster_joint(cid, edge=key, anchor="corner")` —
  `anchor` defaults to `"midpoint"` (backward-compatible; the capstone + all existing tests use it). `"corner"`
  stores the edge's `−axis` endpoint as the anchor; **same hinge line** (so `assert_joint_on_hull_corner(…,
  edge=key)` still passes — proven by `test_place_cluster_joint_corner_anchor_stays_on_edge`).
- `from tests.automation_harness import assert_recommended_hinge` — `(design, cluster_id, *,
  recommendations=None, axial_tol_deg=20, tol_nm=0.05, length_tol_nm=0.1)`. Re-measures on the independent OBB
  that the #1 hinge is non-axial + longest-non-axial + corner-anchored; pass `recommendations=` a hand-built
  list to drive the can-go-red guards.
- **GOTCHA banked:** for a real edge a corner and the midpoint are half-an-edge-length apart, so the
  corner-anchor check (`d_corner < tol_nm`) ALSO catches a midpoint anchor (it's far from every corner) — there
  is no separate "is it the midpoint" assertion (it would be unreachable). On a 2×6 SQUARE bar the wide `u`-edge
  (6 cols) is the top hinge; `v` (2 rows) second; the 4 axial `w`-edges last.
- **Follow-up (optional, not blocking):** the capstone's `build_parallelogram` still hinges on the axial
  `w`-edge (`_SIDE_EDGE` in `test_parallelogram_linkage.py`) — a barrel-roll. Re-pointing it at the recommended
  cross-section edge would make the demo use the AF-14-P3 rule, but it's cosmetic (the linkage oracle is
  direction-agnostic).

_[AUDIT 2026-06-21: removed the superseded "▶ AF-16" NEXT pointer here — AF-16 SHIPPED 2026-06-18.]_

**▶ AF-11 P2 design grammar DONE — the bulk-routing + apply_loop_skips ops are built + validated.** 4 new design
ops in `build_spec.py` (`auto_scaffold {op,seamless}` / `auto_crossover {op}` / `full_autostaple
{op,scaffold_name,custom_sequence,strand_id}` / `apply_loop_skips {op}`, all NON-primordial) + 4 dispatch branches
in `headless_spec_build.py` driving the real `hb.*` wrappers. **Oracle split (the AF-11-P2 lesson again):**
`assert_spec_matches_calls` is LOAD-BEARING for the 3 routing ops (they add strands the fingerprint sees — a dropped
op diverges from the hand build) but BLIND to `apply_loop_skips`' baked marks (outside the strand graph), so that op's
load-bearing pin is the AF-3 per-helix `geometric_nucleotide_count` conservation (`Δgeom == 2 × net marks`).
**GOTCHA banked:** `auto_crossover` ALONE leaves staples nicked at crossovers → `validate_design` FAILS → you cannot
`assert_roundtrip_stable` on a scaffold+crossover-only design; the round-trip target must be the COMPLETE
`full_autostaple` build (which breaks+merges into a valid design). `apply_loop_skips` needs SQUARE + crossovers
(`auto_crossover` provides them); a bare-bundle `apply_loop_skips` 400s (pinned by a red-test).

_[AUDIT 2026-06-21: removed the superseded "▶ NEXT — pick one" pointer here (recommended AF-13 Phase 4, SHIPPED
2026-06-19). Current open work = top-of-file handoff.]_

**▶ HARNESS NOW AVAILABLE (AF-14 P2, use it — do NOT rebuild):**
- `from backend.core.cluster_obb import obb_sweep_rom, cluster_range_of_motion, rank_joint_candidates`.
  `cluster_range_of_motion(design, cluster_id, axis, *, obstacles=None, min_angle_deg=-180, max_angle_deg=180,
  pad=HELIX_RADIUS, step_deg=2.0) → ROM_deg` — the anchored cluster swings (others static); ROM = total
  two-sided free swing (θ⁺+θ⁻) about the world `axis=(origin,direction)` (use `hull_prism_axis(...,edge=…)`),
  clamped to the limits, OBBs padded by helix radius so contact is rim-to-rim. `obb_sweep_rom(...)` is the pure
  OBB-only core (no design — hand it synthetic `OBB`s). `rank_joint_candidates(design, cluster_id, *,
  target_rom_deg=None)` → the 12 OBB **edges** ranked by ROM desc (door-jamb: interface edge swings least,
  away-facing edge swings free), optional `target_rom_deg` filter.
- `from tests.automation_harness import assert_range_of_motion` — `(design, cluster_id, axis, expected_deg, *,
  tol_deg=2.0, min_angle_deg, max_angle_deg, pad=None, step_deg)`. Direction-AGNOSTIC magnitude; physical-bound
  guard + can-go-red on a wrong angle.
- **GOTCHA banked:** SQUARE bars are LONG+THIN (a 2×3 bar OBB ≈ u-half 2.25 / v-half 1.12 / w-half 5.34 nm).
  Hinging about a vertical `("w",…)` edge sweeps only the small u–v cross-section, so the swing *reach* is ~the
  u-width (~4.5 nm) — an obstacle must be within that to register contact (an 8 nm gap reads 360°). The
  contact-sensitive hinge is the edge **nearest** the neighbour (`_near_w_edge` in the test): one swing sense
  drives A's bulk straight into B, ROM grows monotonically with the gap (≈156°→275° over gaps 1–4 nm).

_[AUDIT 2026-06-21: removed the superseded "▶ NEXT — THE CAPSTONE 4-bar parallelogram" pointer — SHIPPED
2026-06-17 (`tests/test_parallelogram_linkage.py`, AF-15 P2 sub-item).]_

**▶ HARNESS (AF-14 P1, use it — do NOT rebuild):**
- `from backend.api import headless_build as hb` → `hb.place_cluster_joint(cluster_id, *, edge=(axis,s1,s2) |
  corner=(su,sv,sw)+face=(axis,sign), name=…, min_angle_deg=…, max_angle_deg=…)` — places a revolute joint
  anchored on a named OBB feature; drives the real `add_joint` route (covered). Read the new id from
  `design.cluster_joints[-1].id`.
- `from backend.core.cluster_obb import hull_prism_axis` — pure `(design, cluster_id, *, edge | corner+face) →
  (origin, direction)`. EDGE mode = hinge along the OBB edge (origin=midpoint, dir=edge line). CORNER mode =
  point pivot at the corner, dir=`OBB.face_normal((axis,sign))` (NEW method on `OBB`). The corner must lie on the
  named face (it validates). REUSES `cluster_obb` so the axis tracks any pose.
- `from tests.automation_harness import assert_joint_on_hull_corner` — `(design, joint_id, *, edge | corner+face,
  tol_nm=0.05, tol_deg=1.0)`. Re-derives the joint's world axis from its cluster-LOCAL storage +
  `_local_to_world_joint` (so it survives the route's world→local→world trip on a POSED cluster — the local-frame
  round-trip test proves this), recomputes the OBB, asserts collinear-with-edge / through-corner.
  Direction-AGNOSTIC. Can-go-red on a different edge/corner.

_[AUDIT 2026-06-21: removed the superseded "▶ NEXT — AF-14 Phase 2" and "▶ THEN the capstone" pointers — AF-14 P2
SHIPPED 2026-06-17 and the 4-bar capstone SHIPPED 2026-06-17.]_

**▶ GOTCHAS BANKED from AF-14 Phase 1 (read before Phase 2):**
- `cluster_obb` RAISES on a square footprint (ambiguous u/v, in-plane eigenvalue ratio < 1.10) and on < 2 helices —
  ROM fixtures must be **rectangular** (the tests use a 2×6 SQUARE grid; a single bar clustered whole).
- The OBB `half`/`axes`/`center` bound the helix **axis endpoints**, NOT the DNA surface. Phase 2's swept-OBB
  clearance probably wants a **surface pad** (helix radius) so two bars touching rim-to-rim register contact before
  their axis boxes overlap — decide the pad when you build the SAT.
- A `ClusterJoint` does NOT move helices, so `cluster_obb(before) == cluster_obb(after)` across a joint placement —
  the OBB is stable to anchor against. For ROM, the moving body's OBB is *swept*, the obstacle OBBs are static.

**▶ GOTCHAS BANKED from AF-15 Phase 2 (read before AF-14):**
- The OBB cross-section frame uses **PCA**, NOT `deformation._initial_cross_section_frame` (that one snaps u/v to
  WORLD axes by the dominant tangent → not equivariant → edge keys jump after a pose). The PCA frame is
  equivariant; its sign anchor is **positional** (first sorted-id helix with a clear u-projection), NOT an
  argmax over offsets — a value-argmax ties on the 4 symmetric corners and float-rounding flips the frame after a
  rotation (this bit once; the equivariance test catches it). **`cluster_obb` RAISES on a square footprint**
  (ambiguous u/v, in-plane eigenvalue ratio < 1.10) and on < 2 helices — AF-14 fixtures must be **rectangular**
  (the tests use a 2×3 / 2×6 SQUARE grid).
- `OBB.half`/`axes`/`center` bound the helix **axis endpoints** (not the DNA surface) — fine for edge alignment
  and joint placement; AF-14's ROM may want a surface pad (helix radius) for true clearance — decide then.

**▶ DEFERRED — `bind_overhangs` (AF-11 Phase 2 last sub-op): PENDING FURTHER DEVELOPMENT.**
Per user (2026-06-17): **overhang binding still needs work in general** before it's ready to expose to users
through the build-spec grammar — do NOT add the `bind_overhangs` spec op until the underlying overhang-binding
system is firmed up. The relations cluster (`gear`/`belt`/`polymerize`/`bind_overhangs`) is otherwise COMPLETE:
**`gear` + `belt` + `polymerize` SHIPPED**; `bind_overhangs` parked here. When it's revived, the plan below holds.
Drive `hab.bind_overhangs(inst_a, inst_b, *, overhang_a_id, sub_domain_a_id, overhang_b_id, sub_domain_b_id,
binding_mode=…)` (AF-9 overhang-binding wrapper). **Spec shape (proposed):**
`{"op":"bind_overhangs","instance_a":"<ref>","instance_b":"<ref>","overhang_a":…,"sub_domain_a":…,
"overhang_b":…,"sub_domain_b":…,"binding_mode":…}` — it references two prior `add_part` instance `ref`s (the
*instance* namespace `defined`, NOT the joint `ref` namespace gear/belt/polymerize use — bind couples
overhangs, not joints). **The fixture gotcha (TWO traps):** (1) each part design needs `grid_pos` SET on its
helices (the AF-5 `grid_pos=None` TypeError trap) AND an `OverhangSpec` (which auto-populates one sub-domain) —
the inline `_BEAM_SPEC`/`make_6hb_design()` fixtures have NEITHER, so this sub-op needs a NEW part-spec fixture
carrying overhangs (or a `bundle` + an overhang-extrude design op the grammar does NOT have yet — likely a NEW
part-builder fixture in the test, not a new grammar op). (2) the spec must surface the runtime
`(overhang_id, sub_domain_id)` of each part — these are generated at build time, so the driver must look them up
on the built part design, not hard-code them; decide whether the spec names sub-domains by index/label or the
driver resolves "the part's sole overhang". **Oracle:** `assert_binding_resolves(assembly, binding_id, *,
require_cross_part=True)` is the LOAD-BEARING one — `canonical_assembly` (5-tuple, fingerprints `overhang_bindings`)
catches a dropped/rewired binding, but `canonical_topology` is BLIND to a design's overhangs/sub-domains, so a
round-trip that regenerated a sub-domain id while the binding kept its stale ref slips past the fingerprint —
only `assert_binding_resolves` catches that. So pair `assert_spec_matches_calls` (structural) with
`assert_binding_resolves` (referential integrity, the real proof).
**Discipline:** the driver DRIVES the real `hab.*` wrappers — never re-implement — so coverage stays flat
(composition sugar, 32; `test_spec_build_adds_no_coverage` guards it). **PICK THE ORACLE BY WHAT THE OP CHANGES (the
load-bearing AF-11-P2 lesson, confirmed seven times now):** `assert_spec_matches_calls` is the golden pin ONLY when
`canonical_topology`/`canonical_assembly` can see the op's effect — load-bearing for strand-graph ops AND for
fingerprinted top-level assembly relations (gears/belts/joints/instances/polymer-chains/bindings, since AF-9),
VACUOUS for overlays outside it (`loop_skip`→`geometric_nucleotide_count`, `bend`/`twist`→`assert_deformation_angle`).
For relations ALSO pair it with the kinematic/semantic oracle (`assert_gear_ratio` / `assert_polymer_chain` /
`assert_binding_resolves`) — the fingerprint catches a dropped/rewired relation, the semantic oracle catches one
that's present-but-doesn't-work. **NEW lesson from polymerize:** NOT every relations sub-op needs the revolute gate —
polymerize takes a SINGLE seed mate of ANY joint_type, so its referential-integrity branch omits the gate gear/belt
enforce (`test_assembly_spec_polymerize_allows_rigid_seed` pins that). `bind_overhangs` references the *instance*
namespace, not the joint one — a third referential-integrity shape.
**HOW:** mirror this session — `_ASSEMBLY_OP_KEYS` entry + parse branch + referential-integrity (resolve the right
ref namespace) + dispatch branch + grammar-rejection tests + a driver test using the op's own oracle.

**▶ ~~DEFERRED~~ DONE 2026-06-18 — `apply_loop_skips` (design op).** Shipped alongside the `auto_scaffold`/
`auto_crossover`/`full_autostaple` cluster (as planned): `auto_crossover` now produces the cross-helix domain
transitions its route demands, so a SQUARE `bundle → auto_scaffold → auto_crossover → apply_loop_skips` spec bakes
the periodic-skip pattern, pinned by the AF-3 per-helix `geometric_nucleotide_count == 2×net_marks` conservation
check (`test_apply_loop_skips_spec_honors_marks_per_helix`, mirroring
`test_apply_deformations_geometry_honors_marks_per_helix`). A `test_apply_loop_skips_spec_requires_crossovers`
red-test pins that the op runs the real route (400s on a bare bundle).

**▶ STRAGGLER (still open, its own session) — `polymerize_periodic`.** The SINGLE-part `is_periodic_seam` path
with the `derive_periodic_delta` Kabsch oracle was NOT built: it needs a part carrying `is_periodic_seam=True`
forced ligations the inline `make_6hb_design()` fixtures don't have. Build one headlessly via the
route-for-polymerization op first, then assert each copy sits at `T_seed @ derive_periodic_delta(design)^k`.

**▶ HARNESS NOW AVAILABLE (AF-11, use it):** `from tests.automation_harness import assert_spec_matches_calls`.
`assert_spec_matches_calls(build_from_spec, build_by_hand, *, kind="design"|"assembly")` — the faithful-façade /
golden-pin oracle: asserts a spec build produces the SAME `canonical_topology` (design) / `canonical_assembly`
(assembly) as the equivalent hand-call wrapper sequence, with a non-emptiness guard so it can't pass vacuously.
Builders: `from backend.api import headless_spec_build as hs` → `hs.build_design(spec)` / `hs.build_assembly(spec)`
(both parse → drive real wrappers in a scratch session → standalone deep copy; raise `BuildSpecError` at PARSE
time on a malformed spec). Parser: `from backend.core.build_spec import parse_design_spec, parse_assembly_spec,
BuildSpecError` (pure, HTTP-free — test grammar/rejection here without any build). Design helices are referenced
by `grid_pos` `[row,col]`; assembly instances by spec `ref` key; a part = a nested design spec under `parts`.

**▶ STRAGGLER (still open, its own session) — `polymerize_periodic`.** The SINGLE-part `is_periodic_seam` path
with the `derive_periodic_delta` Kabsch oracle was NOT built: it needs a part carrying `is_periodic_seam=True`
forced ligations the inline `make_6hb_design()` fixtures don't have. Build one headlessly via the
route-for-polymerization op first, then assert each copy sits at `T_seed @ derive_periodic_delta(design)^k`.

**▶ HARNESS NOW AVAILABLE (AF-10, use it):** `from tests.automation_harness import assert_instances_on_grid,
assert_instances_on_ring`. `assert_instances_on_grid(assembly, rows, cols, *, pitch, row_pitch=None, plane="XY",
tol_nm=0.01, instance_ids=None)` — reads the placed instance origins and asserts they form the exact rows×cols
lattice (count, even spacing == pitch on each axis, every cell filled), id-independent, with a `pitch>min_pitch`
non-degeneracy guard. `assert_instances_on_ring(assembly, n, *, radius, plane="XY", center=(0,0,0), tol_nm=0.01,
angle_tol_deg=1.0, instance_ids=None)` — every origin at `radius` from `center` + even angular step `360°/n`,
with a load-bearing `radius>min_radius` guard (radius=0 stacks all at centre → vacuous). Builders:
`hab.place_grid(design, rows, cols, *, pitch, row_pitch=None, plane="XY", center=False)` /
`hab.place_ring(design, n, *, radius, plane="XY", start_angle_deg=0.0, center=(0,0,0))` — pure-translation
placement (identity orientation; radial *facing* deferred as an ASK-FIRST orientation convention). Both are
construction sugar over `add_inline_instance` (NO route wrapped → coverage unchanged). Pure math in
`backend/core/instance_layout.py` (`grid_translations` / `ring_translations`, plane in {XY,XZ,YZ}). Keep layout
counts ≤6 if you round-trip (the >6-'full'→cylinders downgrade still applies).

**▶ HARNESS NOW AVAILABLE (AF-9 overhang-bindings, use it):** `from tests.automation_harness import
assert_binding_resolves`. `assert_binding_resolves(assembly, binding_id, *, require_cross_part=True)` — a
referential-integrity oracle for cross-part `AssemblyOverhangBinding`s: loads each endpoint's part design with
the route's own `_load_design_from_source` and asserts both `(overhang_id, sub_domain_id)` refs resolve, plus a
non-degenerate / cross-part guard. Use it AFTER a round-trip too — it catches the gap `canonical_assembly` can't:
`canonical_topology` doesn't fingerprint a design's overhangs/sub-domains, so a round-trip that regenerated a
sub-domain id while the binding kept its stale ref slips past the structure fingerprint. Builders:
`hab.bind_overhangs(inst_a, inst_b, *, overhang_a_id, sub_domain_a_id, overhang_b_id, sub_domain_b_id,
binding_mode=…, allow_n_wildcard=…)` / `hab.patch_binding(binding_id, *, binding_mode=…)` /
`hab.unbind_overhangs(binding_id)`. `canonical_assembly` now returns a **5-tuple** `(instances, joints, gears,
belts, bindings)` — it fingerprints `overhang_bindings`, so a dropped/rewired binding fails the round-trip oracle.
The overhang fixture needs `grid_pos` set on its helices (the AF-5 `grid_pos=None` TypeError trap) and an
`OverhangSpec` (auto-populates one sub-domain).

**▶ HARNESS NOW AVAILABLE (AF-9 polymerize, use it):** `from tests.automation_harness import assert_polymer_chain`.
`assert_polymer_chain(assembly_before, assembly_after, seed_joint_id, *, count, direction="forward", tol_nm=0.01,
min_delta_nm=0.5)` — the geometric oracle for mate-seeded polymerize. Re-derives the seed mate's repeat
`delta = T_B @ inv(T_A)` from the seed pair's world transforms ALONE (NOT the route's chain helpers → independent,
not a tautology) and asserts the `count−2` new instances form the exact `delta`-power multiset (`delta^k @ T_B`
forward / `inv(delta)^k @ T_A` backward), matched id-independently within `tol_nm`, with a can-go-red guard that
`delta`'s translation > `min_delta_nm` (a stacked seed pair → every copy on the seed → vacuous). Returns the 4×4
`delta`. Builder: `hab.polymerize(joint_id, count, *, direction, additional_instance_ids=…)` — needs a seed mate
between **identical** parts (use the SAME `Design` object for both `add_inline_instance` calls so `_sources_match`
is true, else the route 422s). `canonical_assembly` already fingerprints instances+joints, so a polymerized chain
round-trips through `assert_assembly_roundtrip_stable` unchanged with **no** harness extension (polymerize adds no
new top-level relation list — unlike gears/belts).

**▶ HARNESS NOW AVAILABLE (AF-9 belts, use it):** `hab.define_belt(joint_a_id, joint_b_id, *, radius_a, radius_b,
side_a=…, instance_a_id=…, connector_a_label=…)` (the two joints must already be **revolute** mates, like the gear
fixture). The belt's coupling relation surfaces with the synthetic id `f"__belt__{belt.id}"`; pin it by reusing the
gear oracle — `assert_gear_ratio(before, after, f"__belt__{belt.id}", expected_ratio=radius_a/radius_b)` — which now
searches `_coupling_relations` (gears + belt-derived), so the SAME oracle handles both. `canonical_assembly` now
returns a **4-tuple** `(instances, joints, gears, belts)` — it fingerprints belt_paths, so
`assert_assembly_roundtrip_stable` catches a dropped/rewired belt. When you add the next top-level relation list
(rider chains, polymer groups), extend `canonical_assembly` in the same commit (4th time — see the banked lesson).

**▶ HARNESS NOW AVAILABLE (AF-9 gears, use it):** `from tests.automation_harness import assert_gear_ratio`.
`assert_gear_ratio(assembly_before, assembly_after, rel_id, *, expected_ratio, ratio_tol=0.02, min_angle_deg=2.0)` —
the resolve-invariant for any ratio-coupling relation. Drive ONE side with `hab.drive_joint(joint_id, radians)` (its
PATCH auto-propagates the relation — no separate `resolve()` needed), capture `assembly_state.get_or_404()` as
`after`, and the oracle measures the two coupled bodies' real *instance-transform* rotation magnitudes (via the gear
endpoint sides) and asserts driven/driver = `|expected_ratio|`, with a can-go-red "driver actually rotated" guard.
**Direction-agnostic** (magnitude only — `invert` flips sign not magnitude, so no ASK-FIRST). Builders:
`hab.define_gear(joint_a_id, joint_b_id, *, ratio, invert=False, endpoint_*=…)` (the two joints must already be
**revolute** mates) and `hab.drive_joint(joint_id, value_radians, *, endpoint_side=None, silent=False)`.
`canonical_assembly` now returns a **4-tuple** `(instances, joints, gears, belts)` — it fingerprints gear AND belt
relations, so `assert_assembly_roundtrip_stable` catches a dropped/rewired gear or belt.

**▶ HARNESS NOW AVAILABLE (AF-8, use it):** `from tests.automation_harness import assert_mate_coincident`.
`assert_mate_coincident(assembly, joint_id, *, tol_nm=0.01, min_offset_nm=0.5)` — the two mated connectors are
coincident in world space (uses the SAME `_get_connector_world` machinery resolve uses, on the instance-overridden
design) within tol, with a non-triviality guard (the mated part origins must be separated, else the coincidence is
vacuous — place mate connectors at a non-zero LOCAL offset from their part origins). Builders:
`hab.add_connector(inst_id, label, position, normal)` (LOCAL position/normal) then
`hab.define_mate(child_inst_id, parent_inst_id, *, child_label, parent_label, joint_type="rigid", axis_origin=,
axis_direction=, min_limit=, max_limit=)`. The mate SNAPS the child onto the parent connector at create time
(coincident before resolve too); pass `joint_type="revolute"`+`axis_*` for the AF-9 gear mates. `canonical_assembly`
now keys joints by `(type, conn labels, parent-src, child-src, value)` so a dropped/rewired mate fails the
round-trip fingerprint.

**▶ HARNESS NOW AVAILABLE (AF-7, use it):** `from tests.automation_harness import canonical_assembly,
roundtrip_nass, assert_assembly_roundtrip_stable`. `assert_assembly_roundtrip_stable(build_fn)` = one-line
"assembly validates + survives a real `.nass` import unchanged". `canonical_assembly(a)` = id/order-independent
(instances, joints) fingerprint. `roundtrip_nass(a)` = in-memory `to_json`→`POST /assembly/import` (inline parts
travel inside; no disk). Builder: `from backend.api import headless_assembly_build as hab` →
`hab.assembly_scratch_session()` / `hab.new_assembly()` / `hab.add_inline_instance(design, name=, transform=)` /
`hab.add_file_instance(path, …)` / `hab.resolve()` / `hab.translation(x,y,z)`. Keep test assemblies ≤6 full-rep
instances (import auto-downgrades >6 'full' → 'cylinders', which would change the rep field the fingerprint reads).

**▶ KNOWN GOTCHA found in AF-5 (still relevant if you reuse round-trip):** `make_bundle_deformed_continuation`
(`backend/core/lattice.py:1234`) is the **only** bundle builder that does NOT set `grid_pos` on its new
helix — every other (`make_bundle_design`/`_segment`/`_continuation`) does. So a deformed-continuation helix
has `grid_pos=None`, which (a) makes `canonical_topology` raise `TypeError: '<' not supported between NoneType
and tuple` (it sorts on grid_pos) → **`assert_roundtrip_stable` CANNOT be used on a design with a deformed
continuation** (AF-5 used only the deformed-frame oracle for that reason), and (b) may be *intentional* (a
non-None grid_pos could make the straight-geometry path recompute the helix position from the lattice and
clobber the baked deformed axis coords). **Do NOT just add `grid_pos=(row,col)` — it's a three-layer
directionality question; ASK the user.** Logged as `ISSUE-11` in `issues_ledger.md`.

**▶ HARNESS NOW AVAILABLE (use it, don't re-derive):**
`from tests.automation_harness import canonical_topology, roundtrip_nadoc, assert_roundtrip_stable,
assert_inverse_pair, assert_geometric_length_delta, geometric_nucleotide_count, assert_circular_disc,
assert_on_deformed_frame, assert_deformation_angle, headless_coverage_report`.
- `assert_roundtrip_stable(build_fn)` — one-line "build survives save/load".
- `assert_inverse_pair(start, forward, inverse)` (AF-2) — op∘inverse is topology-identity, with a built-in
  "forward must actually mutate" guard. For add↔delete / nick↔ligate pairs.
- **`assert_geometric_length_delta(start, op, expected_bp_delta, *, helix_id=None, strands_per_bp=2)` (NEW,
  AF-3)** — op changes the geometry kernel's nucleotide count by exactly `expected_bp_delta` bp (× strands/bp).
  Direction-AGNOSTIC (counts how many nucs changed, not which way) → safe on bend/twist apply without sign
  reasoning. Pass `helix_id=` for the strong per-helix conservation check. `geometric_nucleotide_count(d, hid=None)`
  is the bare count. **Caveat banked: `canonical_topology` does NOT see loop/skips** (they're on the helix, not
  the strand graph) — so `assert_roundtrip_stable` can't prove a loop/skip persisted; use the geometric count.
- **`assert_circular_disc(design, requested_radius_nm, *, max_spread_nm=0.5, radius_tol_nm=0.5, helix_ids=None)`
  (NEW, AF-4)** — geometric oracle for parametric disc primitives: reads the *placed* helices' axis spans
  (not a stored field), orders by lattice column, asserts `circularity_spread < max_spread_nm` AND `fit_radius`
  within `radius_tol_nm` of the requested R. Pins the whole radius→geometry path. `helix_ids=` filters to the
  disc helices when other DNA is present.
- **`assert_on_deformed_frame(before, after, source_bp, cells, *, ref_helix_id=None, pos_tol_nm=0.02,
  min_deflection_nm=0.5)` (NEW, AF-5)** — geometric oracle for continuations onto a bent/twisted face: reads
  the *placed* helices' `axis_start`, asserts each lies on the independently re-derived deformed cross-section
  frame at `source_bp` AND that the deformed placement is displaced > `min_deflection_nm` from a straight
  extrude (the can-go-red guard, so it won't pass vacuously on an un-deformed design). Direction-agnostic.
  Returns the max deflection observed. **NB: needs a real bend/twist applied first** (now use `hb.add_bend`).
- **`assert_deformation_angle(design_after, plane_a_bp, plane_b_bp, expected_total_deg, *, ref_helix_id=None,
  angle_tol_deg=1.0, step_bp=1, min_angle_deg=5.0)` (NEW, AF-6)** — geometric MAGNITUDE oracle for bend/twist:
  walks the deformed frame in `step_bp` steps and SUMS each step's relative-rotation magnitude (unwraps past
  180°/360° — a 540° twist reads 540°, not folded), asserts total = `κ×(b−a)` (bend) / total twist, plus a
  can-go-red guard (fails on an un-deformed design). **Direction-AGNOSTIC** (no sign/frame reasoning → safe
  per the ASK-FIRST rule; a signed-curvature oracle was deliberately NOT built). `design_after` is the design
  after the deformation is applied.
- `headless_coverage_report()["uncovered_routes"]` IS the live AF backlog (**207 uncovered / 32 covered** after
  AF-9 overhang-bindings; paths carry the `/api` prefix — match with `.endswith()`). Now lists mostly
  `/assembly/*` layout/overhang-connection routes + the design cluster/extension residue (the AF-10+ gap).
- Headless wrappers now exist: `hb.nick/ligate/delete_strand` (AF-2); `hb.loop_skip(h,bp,delta)` +
  `hb.apply_loop_skip_deformations()` (AF-3, delta=0 removes); `hb.circle_segment(radius_nm)` (AF-4, SQUARE);
  `hb.bundle_deformed_continuation(cells, length_bp, *, source_bp, ref_helix_id)` (AF-5);
  `hb.add_bend(a, b, *, curvature_deg_per_bp, direction_deg)` + `hb.add_twist(a, b, *, total_degrees |
  degrees_per_nm)` (AF-6).

**▶ STRUCTURAL FACTS from the audit (don't re-derive these — they're durable):**
- `headless_build.py` exposes ~19 design ops; **`headless_assembly_build.py` now exists (AF-7/8)** with
  create/place/resolve/import + add-connector/define-mate — the AF-9..AF-10 gap is now gears/belts,
  overhang-bindings/polymerize, and layout helpers.
- Remaining design REST routes lacking a wrapper: overhang rotation, cluster ops (`/design/cluster`),
  strand-end-resize, extensions, scaffold-nick — plus the whole `/assembly/*` surface (AF-7+).
- Pixel-drag-only ops (crossover sprite place/move, domain-shift, strand-end-resize, helix-reorder) DO
  have coord-taking REST routes — they're headless-reachable; only the pixel→bp mapping is UI. The *truly*
  UI-only residue (lasso/select state, gizmo intermediate drags) has no coord route → those go to MV, not here.

**Gotchas banked:**
- The `/design/import` route does post-load processing (migrate split-staple domains, autodetect overhangs,
  backfill sub-domains, recompute flexible connections). `roundtrip_nadoc` drives the *real* route, so a
  build that survives the round-trip survives that processing too — but if a future op's output *isn't*
  idempotent under autodetect, `assert_roundtrip_stable` will (correctly) flag it. That's a real bug to fix
  in the op, not a harness false-positive.
- Coverage is matched by **endpoint function identity**, so a wrapper MUST import the exact route handler
  (`create_bundle as _route_create_bundle`), not re-implement it, to register as covered — which is also
  the anti-passthrough discipline. A wrapper that re-implements logic won't show as covered (good signal).

---

## Backlog (ranked, validation-first). Probed status is the 2026-06-16 audit; verify before claiming.

### Tier 0 — validation foundation (everything leans on it)

- [x] **AF-1 — Headless round-trip validation harness + coverage report.** SHIPPED 2026-06-16.
  `tests/automation_harness.py`: `canonical_topology` (promoted from `test_section_router.py`),
  `roundtrip_nadoc` (real `to_json` → `POST /design/import`, scratch-isolated), `assert_roundtrip_stable`
  (validate → round-trip → validate + fingerprint-equal; injectable `roundtrip` seam),
  `headless_coverage_report` (route-vs-wrapper by **function-object identity** → never stale). 8 meta-tests
  in `tests/test_automation_harness.py`, incl. the load-bearing "oracle fires on a corrupted round-trip".
  Coverage at ship: **11 / 239** design+assembly mutation routes wrapped.

### Tier 1 — design-op headless wrappers (REST exists, wrapper missing; small, high validation value)

- [x] **AF-2 — nick / ligate / delete-strand wrappers** in `headless_build.py` (routes `/design/nick`,
  `/design/ligate`, `DELETE /design/strands/{id}`). SHIPPED 2026-06-16. **Augment:** `assert_inverse_pair`
  (new reusable oracle in `automation_harness.py`) — `nick(h,bp,d)` then `ligate(h,bp,d)` → canonical
  topology unchanged, with a built-in "forward must mutate" guard so it can go red; delete pinned by
  canonical strand-set subtraction + round-trip stable. Coverage 11→14.
- [x] **AF-3 — loop/skip insert + apply-all-deformations wrappers** (routes `/design/loop-skip/insert`,
  `/design/loop-skip/apply-deformations`). SHIPPED 2026-06-16. `hb.loop_skip(h,bp,delta)` +
  `hb.apply_loop_skip_deformations()`. **Augment:** `assert_geometric_length_delta` (new reusable oracle in
  `automation_harness.py`) — pins the topology→geometry conservation law: a loop +1 adds 1 bp of geometry
  (1 nuc/strand), a skip −1 removes 1, delta=0 restores; per-helix scoping proves bulk apply honours each
  helix's marks one-for-one even when the global net cancels. Also pins loop survives `.nadoc` round-trip
  (canonical_topology is blind to loop/skips, so the geometric count is what proves persistence). Coverage 14→16.
- [x] **AF-4 — parametric circle (`circle-segment`) wrapper** (route `POST /design/circle-segment`).
  SHIPPED 2026-06-17. `hb.circle_segment(radius_nm, *, plane, offset_nm, …)` — takes the *radius*, runs the
  same `circle_footprint` analytic the UI mirror uses, drives `add_circle_segment`. **Augment:**
  `assert_circular_disc` (new reusable oracle in `automation_harness.py`) — reads the *placed* helices' axis
  spans (not a stored field) so it pins the full path radius→footprint→route→builder→geometry: `circularity_spread
  < 0.5 nm` + `fit_radius` within 0.5 nm of the requested R. Coverage 16→17.
- [x] **AF-5 — deformed-continuation wrapper** (route `/design/bundle-deformed-continuation`).
  SHIPPED 2026-06-17. `hb.bundle_deformed_continuation(cells, length_bp, *, source_bp, ref_helix_id, plane)`
  — samples the deformed frame via `get_deformed_frame` then POSTs *with* `source_bp` (the replayable path,
  mirrors the UI). **Augment:** `assert_on_deformed_frame` (new reusable oracle in `automation_harness.py`) —
  asserts each appended helix's `axis_start` lies on the independently re-derived deformed cross-section frame
  at `source_bp` AND is displaced > 0.5 nm from where a straight extrude would land (the can-go-red guard).
  Coverage 17→18.

### Tier 2 — deformation by constraint (gizmo-only construction → programmatic; known three-layer-bug area)

- [x] **AF-6 — `add_bend` / `add_twist` by constraint** wrapping the `addDeformation` REST path.
  SHIPPED 2026-06-17. `hb.add_bend(a, b, *, curvature_deg_per_bp, direction_deg)` +
  `hb.add_twist(a, b, *, total_degrees | degrees_per_nm)` (import `add_deformation` → covered by identity).
  **Augment:** `assert_deformation_angle` (new reusable oracle) — walks the deformed frame in 1-bp steps
  and SUMS each step's relative-rotation magnitude (unwraps past 180°/360°: a 540° twist reads 540°),
  asserting the total = κ×(b−a) for a bend / the total twist, plus a can-go-red guard (fails on an
  un-deformed design). **Direction-AGNOSTIC** (magnitude only → no ASK-FIRST sign/frame reasoning needed;
  the signed-curvature oracle the backlog floated was *not* built, deliberately). Coverage 18→19.

- [x] **AF-14 — geometry-aware revolute-joint placement on hull-prism corners/edges. ALL 3 PHASES SHIPPED (P1 2026-06-17, P2 2026-06-17, P3 2026-06-18 — see sub-items).** (route
  `POST /design/cluster/{cluster_id}/joint`, handler `add_joint` in `routes_cluster_joints.py`; currently
  gizmo-only — the user clicks a face on the cluster's hull-surface approximation, the frontend computes a
  world axis, the route converts it to the cluster's LOCAL frame). **No headless wrapper exists** → uncovered.
  Three-layer note: a `ClusterJoint` is a **topological/design-layer** intent (which rigid cluster rotates
  about what axis) — placing one is an allowed write; the hull prism, the OBB, and the range-of-motion (ROM)
  math are all **geometric reads** and never write back (clean Three-Layer; mirrors how AF-6 deformation reads
  the frame). Multi-phase — one phase per session.

  **The kinematic-design framing (this is the point — it's why "face corners" is the right primitive).**
  A revolute joint is a hinge: a rigid cluster M swings about an axis line relative to the static rest of the
  design. What a designer actually wants to pick is *which hinge gives the desired free swing without M
  colliding into a neighbouring cluster*. The hull prism **is the cluster's oriented bounding box (OBB)**, so
  its faces/edges/corners are the natural discretised anchor set, and the relevant mechanical principles are:
  - **The hinge axis belongs on the contact interface (the door-jamb principle).** Co-locating the axis with
    the *edge of M's OBB that lies against the neighbour* maximises ROM: M rotates immediately *away* from the
    obstacle instead of swinging *into* it. An axis through M's interior (or the far edge) collides almost
    at once. So the high-value candidates are the OBB **edges on the face adjacent to the obstacle**.
  - **For a revolute joint the primitive is an EDGE (a corner→corner pair); for a ball/point joint it's a
    CORNER.** "Face corners" enumerates both: the 8 corners give point pivots; corner-pairs give the 12
    candidate hinge edges. The axis *direction* is the edge's line (typically perpendicular to the helix axis
    = a fold; parallel = a barrel-roll — usually not what's wanted).
  - **ROM is a swept-collision root-find.** Rotating M about axis a sweeps every point p on a circle of radius
    `r = dist(p, a)`; first contact is driven by the point of M **farthest from a on the obstacle side** (the
    instantaneous-centre / largest-swing-radius point). Because both M and every obstacle are OBBs, the swept
    interference is exact and cheap: **bisect θ on OBB–OBB separation (SAT) to find θ⁺ and θ⁻**, and
    `ROM(a) = θ⁺ + θ⁻` (clamped to the joint's `min/max_angle_deg` limits), checked against **all** other
    clusters, not just the nearest. This is the discretised collision-free workspace of a 1-DOF joint.
  - Connects to the **AF-12 hinge-primitive / 4-bar-linkage** discussion: a multi-joint mechanism's mobility
    (Grübler) and ROM both depend on these corner/edge choices; AF-14 is the per-joint geometry the linkage
    layer will compose.

  **Feasibility blocker to settle first (do this in Phase 1):** the hull-prism OBB is currently computed in
  **JS** (`frontend/src/scene/joint_renderer.js` — `_bundleGeometry`/`_buildExtrusionBoxes`), NOT Python, so a
  headless ROM oracle needs a backend OBB. Build it from the geometry kernel (`_geometry_for_design` →
  per-cluster nucleotide positions → PCA/bundle-frame OBB), as a NEW pure `backend/core/cluster_obb.py`
  (service+oracle shape, rule 3; `backend/core` imports nothing from `backend/api`). Pin it for parity against
  the JS extents on a shared fixture so the headless corner set matches what the user sees.

  - [x] **Phase 1 — `hb.place_cluster_joint` + corner/edge resolver + on-corner oracle. SHIPPED 2026-06-17.**
    Wrapper in `headless_build.py` importing `add_joint` (covered by identity) + `AddJointBody`. The pure helper
    `hull_prism_axis(design, cluster_id, *, edge=(axis,s1,s2) | corner=(su,sv,sw)+face=(axis,sign))
    → (axis_origin, axis_direction)` in `cluster_obb.py` turns a named OBB edge/corner into the world axis the
    route expects (edge = revolute hinge ALONG the edge: origin=midpoint, dir=edge line; corner = point pivot AT
    the corner, dir=face normal). **Augment:** `assert_joint_on_hull_corner(design, joint_id, *, edge|corner,
    face, tol_nm, tol_deg)` — re-derives the joint world axis from its LOCAL storage via `_local_to_world_joint`
    + the cluster's current pose, recomputes the OBB independently, asserts the axis is collinear with the named
    edge / passes through the named corner. Direction-AGNOSTIC. Coverage **34 → 35** (`add_joint` — first flip
    since AF-15 P1). Tests: 7 in `test_cluster_obb.py` + 5 in `test_automation_harness.py` (incl. a posed-cluster
    local-frame round-trip test + 2 load-bearing red-tests).
  - [x] **Phase 2 — `cluster_range_of_motion` + `rank_joint_candidates` (the geometry-aware selector).
    SHIPPED 2026-06-17.** Pure swept OBB–OBB SAT (`_obb_intersect`, Ericson 15-axis) + per-step scan +
    bisection in `cluster_obb.py`: `obb_sweep_rom(moving, obstacles, axis_origin, axis_dir, *, min_deg,
    max_deg, pad, step_deg)` (on OBBs) → `cluster_range_of_motion(design, cluster_id, axis, *, obstacles=None,
    min_angle_deg, max_angle_deg, pad=HELIX_RADIUS, step_deg)` (anchored cluster swings, others static) →
    `rank_joint_candidates(design, cluster_id, *, target_rom_deg=None)` ranks the 12 OBB **edges** (corners are
    3-DOF ball pivots — single swing angle ill-defined — deliberately not ranked). **Augment:**
    `assert_range_of_motion(design, cluster_id, axis, expected_deg, *, tol_deg, …)` in `automation_harness.py`.
    **ASK-FIRST decisions (user, 2026-06-17):** anchored cluster is the moving body / all others static; ROM =
    **total two-sided magnitude** (θ⁺+θ⁻, each clamped to the limit) → direction-AGNOSTIC, no handedness; OBBs
    **padded by the helix radius** (~1 nm) so contact is rim-to-rim. Analytic precision proved on a SYNTHETIC
    rod+double-wall fixture (closed-form `2·(asin(Y0/√(L²+w²))−atan2(w,L))`, an independent derivation, tol 1°);
    the two can-go-red guards proved on real bars (no-obstacle → full 360°/limit; a neighbour in the path
    strictly reduces ROM, monotonic with the gap). Coverage **35 → 35** (composition over the already-covered
    `add_joint`/`update_cluster` — wraps no new route; the oracle is the deliverable). 10 new tests.
  - [x] **Phase 3 — edge-mapping joint recommender (`recommend_hinge_joints`) + corner anchoring.
    SHIPPED 2026-06-18.** `recommend_hinge_joints(design, cluster_id, *, anchor="corner", axial_tol_deg=20,
    target_rom_deg=None)` in `cluster_obb.py` ranks ALL 12 OBB edges by the user-fixed priority below
    (non-axial first → longest edge → ROM tiebreak), returning each annotated `{edge, edge_length,
    angle_to_axis_deg, is_axial, rom_deg, axis_origin, axis_direction}`; `axis_origin` is corner-anchored.
    `hull_prism_axis` + `place_cluster_joint` gained `anchor="midpoint"|"corner"` (default midpoint =
    backward-compatible; corner stores the edge's `−axis` endpoint — same hinge line). **Augment:**
    `assert_recommended_hinge` (new reusable oracle, re-measures on the independent equivariant OBB) — pins the
    #1 hinge is non-axial + the longest non-axial edge + corner-anchored, with 2 load-bearing red-tests
    (axial-on-top, midpoint-anchor). Coverage **35 → 35** (pure selector; the anchor reuses the already-covered
    `add_joint` route). Tests: 7 in `test_cluster_obb.py` + 3 harness meta-tests; full suite **2523 passed /
    55 skipped**. NB the capstone's 4-bar hinged on the axial `w`-edge (a barrel-roll); a follow-up could
    re-point `build_parallelogram` at the recommended cross-section edge.

    <details><summary>original Phase-3 spec</summary>
    Surface
    headlessly the **most-likely hinge-joint candidates** as an edge mapping: for each cluster, enumerate the OBB
    edges and rank them by the **user-fixed hinge-recommendation priority (2026-06-18, takes precedence over the
    Phase-2 ROM-only sort)**:
      1. **Hinge edge = the largest edge that is NOT parallel to the helical axis.** The OBB `w` axis IS the
         helical/bundle axis, so its 4 long edges (`("w", …)`) are *excluded* — hinging about them is a
         barrel-roll, not a fold. Among the remaining cross-section edges (`("u", …)` / `("v", …)`), prefer the
         **longest** (for a 3×6 bar the `u` edge — the wide cross-section — beats the `v` edge). ROM stays a
         secondary tiebreaker (the Phase-2 door-jamb sort), not the primary key.
      2. **Anchor joints at face corners, NOT edge midpoints.** `hull_prism_axis` edge mode currently sets
         `origin = edge midpoint`; the recommender must place the joint's anchor at a **face corner** (an edge
         endpoint) instead. The revolute axis *line* runs along the chosen edge as before — corner vs. midpoint
         only moves the stored anchor point — but the convention is corner-anchored. (Decide whether this is a new
         `anchor="corner"` option on `hull_prism_axis`/`place_cluster_joint`, or the recommender returns the
         corner explicitly; corner mode's `corner=(su,sv,sw)+face` storage may suffice with `direction` overridden
         to the edge line — settle when building.)
    **Augment:** `assert_recommended_hinge(design, cluster_id, …)` — the top recommendation is a non-axial edge
    (angle to `w` > tol), is the longest such edge, and the placed joint is corner-anchored; can-go-red on a
    design where an axial `w`-edge is (wrongly) returned first or the anchor is the midpoint. Reuses the
    equivariant OBB + `rank_joint_candidates`. **NB this revises the capstone's choice** (the 4-bar used the
    axial `w`-edge as the hinge — a barrel-roll); the new rule prefers a cross-section fold edge, so the
    parallelogram builder/oracle may want a follow-up pass to use the recommended edge.
    </details>

- [x] **AF-16 — headless cluster creation + a loggable cluster-create feature-log entry. SHIPPED 2026-06-18.**
  NEW `ClusterCreateLogEntry` Pydantic model in `backend/core/models.py` (mirrors `ClusterOpLogEntry`:
  `cluster_id`/`name`/`helix_ids`/`domain_ids`) added to the `FeatureLogEntry` union; `add_cluster` route gained an
  opt-in `log: bool = False` that appends the entry with the same cursor-truncation discipline `update_cluster`
  uses; `hb.add_cluster(..., log=False)` gained the passthrough (default off — backward-compatible, the capstone +
  all existing tests don't log). **Augment:** `assert_cluster_in_feature_log(design, cluster_id, *,
  expect_helix_ids=None)` — the `cluster_create` entry exists, names the cluster's exact helix set + name; call it
  on a `roundtrip_nadoc` result to prove the grouping survived `.nadoc` save/load (canonical_topology is blind to
  clusters — the entry is the only proof of persistence). Coverage **35 → 35** (`add_cluster` already covered since
  AF-15 P1 — this adds the log path, not a new route). Tests: 3 in `test_headless_build.py` + 3 harness meta-tests
  (incl. 2 load-bearing red-tests: unlogged build leaves no entry; wrong helix set raises). Full suite **2529
  passed / 55 skipped**. The generated 4-bar part's feature log is now completable — the cluster-creation step is
  representable. **The gap (found 2026-06-17 while generating the 4-bar part):** `add_cluster` creates the cluster in
  design state but emits **no feature-log entry** — there is no `ClusterCreateLogEntry` type (the log has
  `cluster_op` for translate/rotate, but nothing for *grouping helices into a bar*). So a design's feature log
  cannot record "create the 4 bars," and the construction history is incomplete: a user replaying the log sees the
  bundle + the transforms + the joints (minor mutations under "Fine Routing") but not the cluster creation. Closing
  this means (a) a NEW `ClusterCreateLogEntry` Pydantic model in `backend/core/models.py` added to the
  `FeatureLogEntry` union (mirror `ClusterOpLogEntry`: `cluster_id`, `name`, `helix_ids`, `domain_ids`), (b) wiring
  `add_cluster`'s route to append it (with the same `commit`/`log` discipline `update_cluster` uses), and (c) the
  `hb.add_cluster` wrapper gaining a `log=` passthrough. **Three-layer note:** creating a cluster is a
  display/geometry-layer grouping (it never touches the strand graph), exactly like `cluster_op` — clean.
  **Augment:** `assert_cluster_in_feature_log(design, cluster_id)` — after a logged `add_cluster`, the feature log
  carries a `cluster_create` entry naming that cluster + its exact helix set, and it survives a `.nadoc`
  round-trip (canonical_topology is blind to clusters, so the feature-log entry is what proves the grouping
  persisted — same shape as the AF-3 loop/skip / AF-6 deformation blind-spot lesson). Can-go-red: a build that
  creates a cluster *without* logging leaves no entry. **This is what makes the generated 4-bar part's feature log
  truly complete** (today its cluster-creation step is unrepresentable).

- [x] **AF-15 — cluster rigid-transform wrapper + OBB-edge-alignment solver. BOTH PHASES + 4-BAR CAPSTONE SHIPPED 2026-06-17 (see sub-items).** (routes `POST /design/cluster`
  = `add_cluster`, `PATCH /design/cluster/{cluster_id}` = `update_cluster` in `routes_clusters.py`; both
  uncovered). **Sequences BEFORE AF-14 Phase 2 and the linkage demo** — you arrange the rigid bars, *then*
  hinge them. This is the design-layer analog of the AF-8 assembly connector-mate, but driven by **OBB edges**
  instead of named connectors. Three-layer note (load-bearing, and clean here): a `ClusterRigidTransform` is a
  **DISPLAY/geometric pose — it never mutates topology** (stated at `routes_clusters.py:8`). So aligning two
  bars edge-to-edge *reposes rigid bodies*; the DNA strand graph of each bar is untouched. The articulated
  arrangement (poses) + AF-14 joints (kinematic intent) together describe the mechanism without ever editing
  the bars' topology — the three-layer law made concrete for a mechanism. **Shares `backend/core/cluster_obb.py`
  with AF-14** (whichever lands first builds it; the OBB corner/edge enumerator is the common foundation).

  **What the user wants automated (the parallelogram 4-bar linkage, at the part-design level):** four rigid
  bars → arranged into a parallelogram → hinged at the four corners → a working 1-DOF mechanism, all in ONE
  `Design` (4 clusters + 4 `ClusterJoint`s), no assembly layer. The pieces:
  - **Extrude the bars — ALREADY AUTOMATABLE.** `hb.create_bundle` / `hb.extrude` (and the AF-11 `bundle` /
    `extrude` build-spec ops) build the bar bundles today. AF-15 does NOT re-do this.
  - **Cluster each bar — NEW.** `hb.add_cluster(name, helix_ids, domain_ids=…)` wraps `add_cluster` (covered
    by identity).
  - **Pose each bar — NEW.** `hb.transform_cluster(cluster_id, *, translation, rotation_quat, pivot)` wraps
    `update_cluster` (covered). Low-level; takes an explicit rigid transform.
  - **Align by OBB edge — NEW, the high-value piece.** A pure solver
    `align_edge_transform(design, cluster_id, src_edge, target_edge|target_line) → (R, T, pivot)` in
    `cluster_obb.py` computes the rigid transform that brings cluster M's chosen OBB edge onto a target edge
    (another cluster's OBB edge, or a world line), then drives `transform_cluster`. Composing four of these is
    the parallelogram arrangement.

  **Augment (Phase split — one per session):**
  - [x] **Phase 1 — cluster create/transform wrappers + round-trip pin. SHIPPED 2026-06-17.**
    `hb.add_cluster(name, helix_ids, *, domain_ids=())` + `hb.transform_cluster(cluster_id, *, translation,
    rotation, pivot, commit=True, log=False)` (import `add_cluster`/`update_cluster` → covered by identity).
    **VERIFIED `canonical_topology` IS blind to the cluster pose** (it fingerprints helices by `axis_start` +
    strands; cluster_transforms aren't in it — the AF-3 loop/skip / AF-6 deformation blind-spot confirmed for a
    third overlay), so `assert_roundtrip_stable` is necessary-but-NOT-load-bearing for the pose. The load-bearing
    augment is the NEW geometric oracle `assert_cluster_translated(before, after, cluster_id, *, translation)` —
    it reads the cluster-posed helix axes via `deformed_helix_axes` and asserts (1) every cluster helix's
    `start`/`end` shifted by exactly the translation, (2) only the cluster moved (non-cluster helices unchanged),
    (3) `‖T‖ > min` can-go-red guard. **Direction-AGNOSTIC** (a pure world-space translation, no quaternion/pivot
    convention → ASK-FIRST-safe; **rotation poses deliberately out of scope** — they ARE a directionality question,
    deferred to Phase 2's edge-alignment flip/snap). Coverage **32 → 34** (`add_cluster` + `update_cluster`).
    **`cluster_obb.py` was NOT built** — Phase 1 needs no OBB (a translation oracle reads posed axes directly);
    the OBB enumerator is first needed by Phase 2's `align_edge_transform` + AF-14's ROM.
  - [x] **Phase 2 — `align_edge_transform` solver + alignment oracle. SHIPPED 2026-06-17.**
    NEW pure core `backend/core/cluster_obb.py` (the **equivariant OBB enumerator** — corners/edges keyed
    `(axis, s1, s2)` — built from posed helix axes via a PCA cross-section frame, NOT
    `_initial_cross_section_frame` which snaps to world axes and would not track a posed cluster; + the pure
    `align_edge_transform` solver) + the `hb.align_cluster_edge` wrapper driving `transform_cluster` (coverage
    UNCHANGED 34 — wraps no new route) + the reusable `assert_edges_collinear` oracle. **ASK-FIRST conventions
    confirmed with the user (2026-06-17): minimal rotation / auto-flip (≤90° onto ±target_dir) / midpoint snap
    (endpoints coincide) / roll left free.** The load-bearing pin proved equivariance
    (`OBB(g·design)=g·OBB(design)`) — the property that makes an edge key refer to the same physical edge before
    and after the solve. Tests: `tests/test_cluster_obb.py` (11) + 4 harness meta-tests. **`cluster_obb.py` is now
    the shared foundation AF-14 reuses** (the OBB enumerator + a future swept-OBB SAT for ROM).
    `assert_edges_collinear(design, cluster_id, src_edge, target_edge, *, tol_nm, tol_deg)` — after the solved
    transform the two OBB edges are **collinear** (shared line: angle between directions ≈ 0/180° AND
    perpendicular distance < tol), with a can-go-red guard (the pre-align edges are skew/separated, so a no-op
    solver fails). Collinearity is **direction-AGNOSTIC** (a line, not a ray). **The capstone integration test
    SHIPPED 2026-06-17** (`tests/test_parallelogram_linkage.py` + `grubler_mobility` in `cluster_obb.py` +
    `assert_parallelogram_linkage` in `automation_harness.py`): the **4-bar parallelogram built headlessly** —
    extrude 4 bars, cluster + edge-align into a rhombus (adjacent bars share an OBB corner), place 4 revolute
    joints on the shared side-edges — and assert it's a closed, parallel, Grübler-1-DOF linkage with every hinge
    movable. The first headless **kinematic mechanism** and the AF-12 linkage-mobility demo; the Tier-2 arc is
    complete.

### Tier 3 — headless ASSEMBLY builder (biggest construction gap; multi-phase, `headless_assembly_build.py`)

- [x] **AF-7 (Phase 1) — assembly scratch-session + `add_instance(source, transform)` + save/validate.**
  SHIPPED 2026-06-17. NEW module `backend/api/headless_assembly_build.py` mirroring `headless_build.py`:
  `assembly_scratch_session()` + `new_assembly` + `add_inline_instance` / `add_file_instance` / `add_instance`
  (imports `create_assembly` / `add_instance` / `resolve_assembly` / `import_assembly` route handlers → covered
  by function identity) + `resolve()` + `translation()` helper. **Augment:** `assert_assembly_roundtrip_stable`
  (new reusable oracle) + `canonical_assembly` fingerprint + `roundtrip_nass` in `automation_harness.py` — build
  → `.nass` export (`to_json` v2) → real `POST /assembly/import` → `validate_assembly_report` passes both sides
  AND id/order-independent fingerprint (inline source → embedded design's `canonical_topology`; file → path+sha;
  + per-instance transform/mode/rep/fixed/visible; + joints for AF-8) is unchanged. In-memory (inline parts
  travel inside the payload, no disk) — the assembly analog of `roundtrip_nadoc`'s import path, NOT file save/load.
  Coverage 19→23 (create + add-instance + resolve + import all flip). `headless_coverage_report` now scans both
  `headless_build` AND `headless_assembly_build`.
- [x] **AF-8 (Phase 2) — headless mate/joint by connector labels.** SHIPPED 2026-06-17.
  `hab.add_connector(inst, label, position, normal)` (imports `add_connector` route → covered) +
  `hab.define_mate(child, parent, *, child_label, parent_label, joint_type="rigid")` (imports `create_mate`
  → covered); the route snaps the child so its connector meets the parent's (no FK transform passed — the
  connector-derived snap aligns the parts). **Augment:** `assert_mate_coincident` (new reusable oracle) —
  the two mated connectors are coincident in world space (via the SAME `_get_connector_world` machinery
  resolve uses) within tol, plus a non-triviality guard (mated part origins must be separated, else
  coincidence is vacuous). Also enriched `canonical_assembly`'s joint key with the mated parts' source
  fingerprints (id-independent). Coverage 23→25.
- [x] **AF-9 (Phase 3) — gears / belts / overhang-bindings / polymerize wrappers. ALL 4 SUB-OPS SHIPPED 2026-06-17; only the `polymerize_periodic` straggler remains (sub-item below).** Multi-op; one sub-op
  per session. **Augment:** each resolve-invariant (gear ratio holds, belt tangent length, polymerized chain
  count + seam geometry via `derive_periodic_delta`).
  - [x] **gears — SHIPPED 2026-06-17.** `hab.define_gear(joint_a_id, joint_b_id, *, ratio, invert=…)`
    (imports `create_gear_relation`) + `hab.drive_joint(joint_id, value, *, endpoint_side=…)` (imports
    `patch_joint`; PATCH auto-propagates the gear, path 1). **Augment:** `assert_gear_ratio(before, after,
    rel_id, *, expected_ratio)` — measures the two coupled bodies' real *instance-transform* rotation
    magnitudes after driving one side, asserts driven/driver = |ratio| (NOT a re-test of `current_value`),
    with a can-go-red "driver actually moved" guard. Direction-agnostic (magnitude only). Also enriched
    `canonical_assembly` to fingerprint `gear_relations` (keyed by the coupled joints' id-independent
    fingerprints + ratio/invert/anchors) so the round-trip oracle now catches a dropped/rewired gear.
    Coverage 25→27.
  - [x] **belts — SHIPPED 2026-06-17.** `hab.define_belt(joint_a_id, joint_b_id, *, radius_a, radius_b, …)`
    (imports `create_belt_path` + `CreateBeltPathRequest`/`BeltPulleyRequest` from `routes_assembly_belts`).
    **Augment:** generalised `assert_gear_ratio` to search `_coupling_relations` (gears + belt-derived) so a
    belt pins with the SAME oracle — pass `rel_id=f"__belt__{belt.id}"` + `expected_ratio = radius_a/radius_b`;
    it proves `_belt_to_relation`'s radius→ratio synthesis actually drives the coupled pulley (NOT a hand-passed
    gear ratio). Also extended `canonical_assembly` to fingerprint `belt_paths` (now a **4-tuple**). Coverage 27→28.
  - [x] **polymerize (mate-seeded) — SHIPPED 2026-06-17.** `hab.polymerize(joint_id, count, *,
    direction="forward", additional_instance_ids=…)` (imports `polymerize_assembly` +
    `PolymerizeAssemblyRequest` from `routes_assembly_polymerize`). **Augment:**
    `assert_polymer_chain(before, after, seed_joint_id, *, count, direction)` — re-derives the seed mate's
    repeat `delta = T_B @ inv(T_A)` from the seed pair ALONE (not the route's chain helpers) and asserts
    the `count−2` new copies form the exact `delta`-power multiset (`delta^k @ T_B` fwd / `inv(delta)^k @ T_A`
    back), id-independent, within tol — plus a can-go-red guard that `delta`'s translation > 0.5 nm (stacked
    seed → vacuous). `canonical_assembly` already fingerprints instances+joints, so the round-trip oracle
    catches a dropped copy/joint with no extension needed. Coverage 28→29.
  - [x] **overhang-bindings — SHIPPED 2026-06-17.** `hab.bind_overhangs` / `hab.patch_binding` /
    `hab.unbind_overhangs` (import `create_/patch_/delete_assembly_overhang_binding` + the two request models
    from `routes_assembly_overhangs` — covered by function identity). **Augment:** `assert_binding_resolves`
    (new reusable oracle) — a cross-part binding's two endpoints each resolve to a real overhang sub-domain on
    their part design (loaded via the route's own `_load_design_from_source`), with a non-degenerate guard
    (distinct endpoints + cross-part). Genuinely new power: `canonical_topology` does NOT fingerprint a design's
    overhangs/sub-domains, so a round-trip that regenerated a sub-domain id while the binding kept its stale ref
    would slip past `canonical_assembly` — only resolving against the actual designs catches it. Also extended
    `canonical_assembly` to fingerprint `overhang_bindings` (now a **5-tuple**). Coverage 29→32.
  - [x] **periodic polymerize — SHIPPED 2026-06-22.** `hab.polymerize_periodic(instance_id, count, *,
    direction)` wraps `POST /assembly/polymerize-periodic` (flips `polymerize_periodic_assembly` → covered,
    36→37). Fixture turned out light: a 2-helix HC bundle + two `_seam_for` `is_periodic_seam` ligations
    (mirrors `test_periodic_polymer.py`). Oracle NEW `assert_periodic_chain_tiles` — the derived repeat unit
    tiles seamlessly at EVERY rigid seam junction (3p↔5p coincidence via `_get_connector_world`) AND is a
    single repeating unit (constant step length + rotation, magnitude-only → direction-agnostic) + a
    non-vacuity step>min guard. Distinct from `assert_polymer_chain` (mate-seeded, re-derives delta from two
    instances): here the delta is auto-derived from ONE part's seam geometry.
- [x] **AF-10 — instance layout helpers** (grid / ring placement) for parametric assembly gen.
  SHIPPED 2026-06-17. NEW pure core `backend/core/instance_layout.py` (`grid_translations` /
  `ring_translations` — spec→world translations, identity orientation; mirrors `circle_primitive`) +
  `hab.place_grid` / `hab.place_ring` (construction sugar over the already-covered `add_instance` — they
  wrap NO new route, so headless-coverage is unchanged at 32). **Augment:** `assert_instances_on_grid` /
  `assert_instances_on_ring` (new reusable oracles) — read the *placed* instance origins and assert the
  lattice as PROPERTIES re-derived from the user-facing params (count exact, even spacing == pitch / every
  cell filled; on-ring radius exact + angular step == 360°/n), not by re-running the placement formula, each
  with a non-degeneracy guard (the ring's `radius>0` guard is load-bearing — radius=0 stacks every part where
  `dist==radius==0` passes vacuously). Radial-facing/rotated layouts deferred (orientation convention =
  ASK-FIRST). Coverage 32→32.

### Tier 4 — text-to-DNA-origami groundwork (the eventual goal; built ON the validated wrapper library)

- [x] **AF-11 (Phase 1) — declarative build-spec interpreter.** SHIPPED 2026-06-17. Pure grammar/parser
  `backend/core/build_spec.py` (`parse_design_spec` / `parse_assembly_spec` → ordered `BuildOp` list; full
  grammar + referential-integrity validation, NO execution) + driver `backend/api/headless_spec_build.py`
  (`build_design` / `build_assembly` dispatch each parsed op to the REAL existing wrappers — re-implements
  nothing). Grammar: design `{bundle, extrude, nick, ligate}` (helices referenced by `grid_pos`), assembly
  `{add_part, place_grid, place_ring, mate}` (parts = a named library of nested design specs; instances by
  spec `ref`; nested part designs built via `build_design`). **Augment:** `assert_spec_matches_calls` (new
  reusable oracle) — a spec builds the SAME `canonical_topology`/`canonical_assembly` as the equivalent
  hand-call wrapper sequence (the faithful-façade / golden-pin guarantee), + reuse of
  `assert_roundtrip_stable` / `assert_assembly_roundtrip_stable` per spec. Coverage 32→32 (wraps no new
  route — composition sugar, like AF-10). *Phase 2 grammar growth (one cluster per session): **`bend`/`twist`
  SHIPPED 2026-06-17** (drive `hb.add_bend`/`add_twist`; pinned by `assert_deformation_angle`, NOT
  `assert_spec_matches_calls` — the canonical fingerprint is blind to a deformation overlay). **`loop_skip`
  SHIPPED 2026-06-17** (drive `hb.loop_skip`; helix by `grid_pos`; `delta ∈ {-1,0,+1}` parse gate; pinned by the
  geometric `geometric_nucleotide_count`, NOT `assert_spec_matches_calls` — canonical is blind to a loop/skip mark
  too. Sibling `apply_loop_skips` DEFERRED: its route needs crossovers the grammar can't yet produce → rides with
  the auto-scaffold cluster). **`circle_segment` SHIPPED 2026-06-17** (primordial design op — may be FIRST, builds
  its own helices; requires a `square` lattice, enforced at parse time; drives `hb.circle_segment(radius_nm)`.
  Pinned by BOTH `assert_spec_matches_calls` — LOAD-BEARING here, circle ADDS real strands so canonical_topology
  sees it — AND the geometric `assert_circular_disc` from AF-4 as the radius→geometry pin). **`gear` SHIPPED
  2026-06-17** (assembly relations cluster — first sub-op; drives `hab.define_gear` over two revolute mate-joints
  referenced by a NEW joint-`ref` namespace added to the `mate` op; pinned by BOTH `assert_spec_matches_calls` —
  load-bearing, gears ARE fingerprinted in `canonical_assembly` since AF-9 — AND the kinematic `assert_gear_ratio`,
  which catches the orthogonal failure the fingerprint can't: a gear that's structurally present but fails to
  *drive* its coupled body. Parser also rejects gear-over-rigid + dangling joint refs at parse time). **`belt`
  SHIPPED 2026-06-17** (relations cluster, second sub-op; reuses the gear's joint-`ref` namespace verbatim by
  widening the revolute-ref check to `op in ("gear","belt")`; drives `hab.define_belt`; pinned by BOTH
  `assert_spec_matches_calls` — load-bearing, belts ARE fingerprinted in `canonical_assembly` since AF-9 — AND
  `assert_gear_ratio` handed `f"__belt__{belt.id}"` + `expected_ratio = radius_a/radius_b`, passing the *radii* so it
  pins `_belt_to_relation`'s radius→ratio synthesis distinctly from the gear test). Remaining:
  polymerize/overhang-bindings (assembly, each like gear) + auto-scaffold/full-autostaple (design) — each a
  tiny dispatch entry over an existing wrapper, oracle picked by what the op changes.*

- [~] **AF-12 — build from primitives (catalog/file-backed parts in the build-spec).** **Phase 1 (`from_file`)
  SHIPPED 2026-06-22** — an assembly spec's `parts` library may now reference a saved validated `.nadoc` **by path**:
  `"parts": {"hinge": {"from_file": "<path>"}}`. The pure parser (`build_spec._parse_part`/`FilePart`) discriminates a
  file part from an inline design spec by the `from_file` key, validates it (non-empty string path, no extra keys), and
  restricts file parts to `add_part` placement (place_grid/place_ring instance an inline design per slot → rejected at
  parse time). The interpreter (`headless_spec_build._build_assembly_from_parsed`/`_run_assembly_op`) lowers a file part
  to `hab.add_file_instance(path)` (the validated design travels as a REFERENCE, not an embedded copy) — wraps no new
  route (`add_file_instance` already existed → coverage flat at 36). **Oracle = NEW `assert_part_from_file(assembly,
  instance_id, expected_topology)`** — loads the design the instance actually references (via the route's
  `_load_design_from_source`) and asserts its `canonical_topology` equals the saved primitive's. **Load-bearing because
  `canonical_assembly` keys a file source by `("file", path, sha256)` ONLY and never loads the design** — so
  `assert_spec_matches_calls` catches a dropped/wrong-path `from_file` but is BLIND to whether the path resolves to the
  INTENDED validated topology; only this oracle catches a stale/edited/wrong-path primitive silently substituting. 10
  tests (test_build_spec: 1 parse + 5 reject; test_headless_spec_build: 1 augment + 2 can-go-red + 1 roundtrip).
  **Follow-up (file-backed `place_grid`/`place_ring`) SHIPPED 2026-06-22** — a file part may now be placed by
  `place_grid`/`place_ring` (not only `add_part`): the parse-time rejection is removed, the interpreter dispatches a
  file part to NEW `hab.place_file_grid(path, rows, cols, …)` / `hab.place_file_ring(path, n, …)` (loop
  `add_file_instance` with the same per-slot `grid_translations`/`ring_translations` — so the validated `.nadoc`
  travels as one path reference per copy, not rows·cols embedded designs). **Oracle = NEW `assert_instances_from_file(
  assembly, expected_topology, *, instance_ids=None)`** — the layout-AGNOSTIC source pin: it LOADS the design behind
  EVERY selected slot and asserts each is file-backed and resolves to the saved primitive's `canonical_topology`. It
  composes with `assert_instances_on_grid`/`_on_ring` (which pin the lattice but never load the design) to fully pin a
  file-backed layout; the plural of `assert_part_from_file` (a one-slot check misses a layout that file-backed only
  slot 0 and embedded inline copies for the rest). Coverage flat (no new route). Net +9 tests (test_build_spec: 2 accept
  replacing 2 deleted rejects; test_headless_assembly_build: 3 wrapper; test_headless_spec_build: 3 spec + 3 can-go-red).
  **Phase 2
  (`from_primitive` — catalog-by-name, STATIC catalog primitives) SHIPPED 2026-06-22:** an assembly spec's `parts`
  library may reference a curated catalog primitive **by name** — `"parts": {"beam": {"from_primitive": "6hb_primitive"}}`
  — the same name the "Add Primitive" UI shows. The pure parser (`build_spec._parse_part`/`PrimitivePart` +
  `_PRIMITIVE_PART_KEYS`) discriminates a `from_primitive` part from a `from_file` part and an inline spec; the
  interpreter (`headless_spec_build._resolve_primitive_path`) resolves the NAME → the catalog primitive's `.nadoc` path
  (`primitive_catalog.design_path`, `primitives_dir` overridable, default = the live workspace `Primitives` dir) and then
  lowers it through the EXACT `from_file` machinery (one path reference per copy; placeable by `add_part`/`place_grid`/
  `place_ring`). An unknown name fails the BUILD with a clear `BuildSpecError` (the parser is catalog-agnostic). Wraps no
  new route (reuses `add_file_instance` → coverage flat at 37). **Oracle = NEW `assert_part_from_primitive(assembly,
  instance_id, primitive_name, primitives_dir)`** — independently re-resolves the catalog NAME through
  `primitive_catalog.design_path`, loads that primitive's `.nadoc`, and delegates to `assert_part_from_file`; the new
  load-bearing piece over `from_file` is the **name→catalog-path RESOLVER** (a name mapped to the wrong/renamed primitive
  is invisible to `canonical_assembly`). Net +6 tests (test_headless_spec_build: 1 augment + 2 can-go-red on the oracle +
  1 unknown-name-fails-build + 1 roundtrip + 1 place_grid layout; suite 3002→3008). Scoped to STATIC (file-backed) catalog
  primitives per the user's choice. **Still OPEN:** the PARAMETRIC circle disc (`metadata.primitive_kind="circle"`, needs a
  radius → generative `hb.circle_segment` path, not a file reference) + parts carrying small mate recipes (an
  assembly-level hinge *template*, not just geometry). Original assessment below.
  **The gap (assessed 2026-06-17):** there is no primitive-catalog → automation pipeline. The design-level "Add
  Primitive" catalog is **read-only + UI-only** — `routes_primitives.py` exposes only `GET /primitives` +
  `preview.gif`/`poster.png`; there is **no placement route** (the browser reads `derive_placement_spec` and composes
  the `bundle-segment`/`continuation` calls client-side), and no headless layer references the catalog at all (the
  one parametric primitive with a headless entry is the circle disc, `hb.circle_segment`). At the assembly level,
  `hab.add_file_instance(path)` CAN instance a saved validated `.nadoc` part by workspace path and mate it — but the
  declarative grammar's `add_part`/`parts` accept **inline design specs only** (`parse_design_spec` per part), so a
  spec cannot reference a saved/validated primitive **by name**. **The missing rung** = a catalog/file-backed
  `add_part` (e.g. `"parts": {"hinge": {"from_primitive": "hinge_6hb_120deg"}}` or `{"from_file": "<path>"}`) + a
  headless primitive-instantiation wrapper. **The motivating use case (user, 2026-06-17):** hand-author +
  experimentally validate a hinge's custom scaffold routing (real topology = ground truth), save it as a part, then
  let automation place/articulate copies (display-layer mates/gears — never touching the validated topology; fits the
  three-layer law). A "hinge primitive" is likely an *assembly-level template* (two leaves + a revolute mate), not
  just a design primitive — so consider a parts-library that can carry small mate recipes, not only geometry.
  **Augment (when built):** a round-trip-style oracle asserting the instanced part's `canonical_topology` equals the
  referenced catalog file's `canonical_topology` — i.e. "build from primitive X provably uses *exactly* validated X"
  (so a stale/renamed/edited primitive can't silently substitute). Builds ON AF-11 (the build-spec interpreter) and
  AF-7 (`add_file_instance`). See the chat assessment + the 4-bar/parallelogram linkage discussion for context.
  **NB (2026-06-17): the mechanism layer this item gestured at is now spec'd as AF-14 + AF-15** (Tier 2,
  geometry-aware joint placement + OBB-edge alignment, sharing `backend/core/cluster_obb.py`). The 4-bar
  parallelogram capstone there builds the linkage at the *part-design level* (4 clusters + 4 `ClusterJoint`s in
  one `Design`); AF-12's role is the complementary path — instancing a hand-validated *saved* hinge/bar primitive
  by name — so the two compose (validated primitive geometry ← AF-12; articulation/arrangement ← AF-14/AF-15).

### Tier 5 — physical-layer validation (oxDNA-in-the-loop) + constraint satisfaction (the eventual goal)

**What's different here.** Tiers 0–4 validate the **topological/geometric** layers and are *deterministic*
(`canonical_topology` equality, analytic geometry oracles). Tier 5 validates the **physical** layer: it
drives an oxDNA relaxation/production headlessly, *measures* a property of the relaxed structure (end-to-end
distance, R_g, inter-helix spacing, segment angle), and — the capstone — **iterates the design until a user
constraint is satisfied.** Because MD is stochastic, the oracle class is new: **a measured property within a
tolerance, GATED by the confidence metric** (`oxdna_health.rmsf_confidence` — frames pooled + RMSF standard
error, already built), NOT exact equality. A short run reports *inconclusive*, not pass/fail.

**Eventual goal (user, 2026-06-17):** *"Make sure two ends of a curved structure are 50 nm ± 5 nm apart"* →
NADOC iterates over several oxDNA simulations until the request is met.

**Three-Layer Law (load-bearing here).** The iterate loop EDITS the **topological** layer (a bend op /
loop-skip / length knob), re-derives **geometric** positions, RE-RELAXES the **physical** layer (oxDNA),
then MEASURES the physical result. The edit is topological; the measurement is physical; **oxDNA output is
never written back into `Design`** (it stays a Physical-layer artifact, exactly as the display/RMSF paths do).
Confusion about *which* nucleotide is "an end", or *which* knob bends *which* way, is an ASK-FIRST
directionality question (`feedback_crossover_no_reasoning`, the DNA-topology rule) — do not guess.

**Reuse map (durable — don't re-derive; see `memory/project_oxdna_relaxation.md`):** job lifecycle / resume /
reconcile in `backend/core/oxdna_runner.py`; routes in `backend/api/routes_oxdna.py` (`create_oxdna_job`,
`start_oxdna_job`, `append_oxdna_production`, `/rmsf`, `/trajectory`, `/display`); average-structure + per-base
RMSF in `oxdna_health.production_rmsf`; the confidence metric in `oxdna_health.rmsf_confidence`; relaxed-geometry
readers `read_configuration_unwrapped` / `read_configuration_full` / `oxdna_backbone_site` in
`backend/physics/oxdna_interface.py`. **CI-without-GPU:** the **mock oxDNA binary** (`_MOCK_OXDNA` fixture in
`tests/test_oxdna_relaxation.py`) lets the wrapper + oracles run deterministically; gate real-binary paths with
`skipif find_oxdna() is None`.

- [x] **AF-13 (Phase 1) — headless oxDNA job wrapper. SHIPPED 2026-06-18.** NEW
  `backend/api/headless_oxdna_build.py` drives the REAL routes (`create_oxdna_job` → `start_oxdna_job` → poll →
  optional `append_oxdna_production` → `get_oxdna_display`) from an isolated scratch session, against the mock
  binary (`$OXDNA_BIN`). `hox.run_relaxation(design, workspace, *, min_bp_retained=0.0, …) → terminal OxdnaJob`;
  lower-level `create_job`/`start_relaxation`/`append_production`/`read_relaxed_positions`/`wait_for_terminal`.
  **Augment:** `assert_relaxed_geometry_recovered(job, design, workspace)` — job is `completed` AND its relaxed
  `last_conf` reads back (via the display route's `read_configuration_unwrapped`) into a full per-nucleotide
  position map (exactly one finite position per design nucleotide, every key a real `(helix_id, bp, dir)`).
  Physical-layer only — never written back to topology. NEW separate `oxdna_coverage_report()` (3 `/oxdna`
  mutation routes covered) keeps the design/assembly count untouched at 35.

- [x] **AF-13 (Phase 2) — relaxed-geometry MEASUREMENT oracle (the constraint primitive). SHIPPED 2026-06-18.**
  Landmark convention (ASK-FIRST answered by user): the raw **`(helix_id, bp_index, direction)` tuple** — most
  primitive, indexes the relaxed-display + RMSF maps directly, no strand-polarity resolution. Pure
  `measure_end_to_end(positions, a, b)` in `backend/core/oxdna_health.py` (Euclidean nm between two landmark
  backbone sites; raises on empty/identical/absent). NEW read-wrapper `hox.read_flexibility_map(job_id, ws)`
  drives the REAL `GET /oxdna/jobs/{id}/rmsf` → pooled noise-averaged mean structure + `confidence`. **Augment:**
  `assert_relaxed_measurement(job, measure_spec, target_nm, tol_nm, *, workspace, min_confidence)` — the first
  STOCHASTIC-class oracle: status-completed + reads the mean structure + **confidence gate** (≥ `min_confidence`
  pooled frames else INCONCLUSIVE-raise) + measured ∈ [target±tol]. On the identity-mock 6hb the relaxed mean
  reproduces the design's own end-to-end to ~0.002 nm (pinned at tol 0.1). Coverage unchanged (rmsf is a GET).

- [x] **AF-13 (Phase 3) — declarative constraint spec + checker. SHIPPED 2026-06-18.** `parse_constraint_spec`
  (PURE validate/normalise → `ConstraintSpecError` at parse time) + `check_relaxed_constraint(constraint,
  read_flexibility_map_dict)` REPORTING `{met, status∈{met,unmet,inconclusive}, measured_nm, n_frames,
  min_confidence, confidence}` — both in `backend/core/oxdna_health.py`, reusing P2's `measure_end_to_end`.
  The REPORTER counterpart to P2's *asserter*. **Load-bearing guard pinned:** `met` is NEVER True below
  `min_confidence`, even when the value is within tolerance (the confidence gate, now a returned status). 20 pure
  tests (13 rejection cases + idempotency + tolerance bracket + the low-frame-never-met red-test) + 2 real-run
  integration tests (`_MOCK_OXDNA_TRAJ` → `read_flexibility_map` → checker). Coverage UNCHANGED (no route wrapped).
  Wired into the AF-11 grammar as a design `constraints` block by AF-13 P5 (`build_and_check_design`).

- [x] **AF-13 (Phase 4, capstone — the eventual goal) — iterate-until-met loop. SHIPPED 2026-06-19.**
  `hox.iterate_to_constraint(build_fn, adjust_fn, constraint, ws, *, initial_knob, …)` — the closed
  build→relax→production→measure→adjust loop. Branches on the AF-13 P3 verdict **status** (never the raw measured
  value): `met`→return; `unmet`→`adjust_fn(knob, verdict)` rebuild; `inconclusive`→`_pool_until_conclusive`
  appends MORE production to the SAME job (pooling frames) until the confidence gate clears, NOT a knob change.
  `tuned=True` relaxes via `run_relaxation_tuned` (AF-17 bridge). Oracle `assert_converges_to_constraint` proves
  the loop converged AND every `met` verdict was confidence-gated (≥`min_confidence` frames) AND non-vacuously
  (first attempt was off-target). Augment fixture = a **bend-curvature knob** on a 2-helix bundle (probed monotone:
  κ 0→13.74 nm, 2.5→12.04, 3→11.33; landmarks stable since topology is unchanged) + a bisection `adjust_fn`;
  identity mock reproduces the design geometry so the *bend* moves the measured end-to-end. Three-Layer-clean (knob
  edits topology, relaxed coords never written back). Composition-sugar (wraps no new route → oxDNA coverage flat).

- [x] **AF-13 (Phase 5) — design `constraints` block wired into the AF-11 grammar (attach + report, no knob).
  SHIPPED 2026-06-21.** A design spec carries an optional top-level `constraints` list (AF-13 P3 specs; landmarks
  name a helix by **grid_pos** `{helix:[r,c], bp_index, direction}`), validated at parse time by `build_spec.py` (via
  `parse_constraint_spec` — a malformed constraint raises `BuildSpecError` BEFORE any build/relax). Driver
  `hs.build_and_check_design(spec, ws, *, steps, tuned, **relax_params) → {design, verdicts}` resolves each landmark's
  grid_pos→runtime id (fail-fast), relaxes ONCE + production, then `check_relaxed_constraint` per constraint. All four
  `measure_*` kinds get the path for free. Oracle `assert_spec_constraints_reported` proves the grammar reports the
  SAME verdict a hand-driven `check_relaxed_constraint` does — load-bearing because `assert_spec_matches_calls` is
  blind to a physical-layer verdict. Composition-sugar (coverage flat, 36; god-files Δ=0). The knob-driven
  `iterate_to_constraint` grammar clause is the deferred next step.

- [x] **AF-13 (Phase 6) — design `optimize` block (knob → `iterate_to_constraint`). SHIPPED 2026-06-22.** A design
  spec carries an optional top-level `optimize` block: a parametric `knob` (`{op:<index>, param:<numeric param>, lo,
  hi, initial, response:"increasing"|"decreasing"}`) + a single AF-13 P3 `constraint`. The pure grammar
  `build_spec.py` (`_parse_optimize`/`_parse_knob`) validates it at parse time — knob index in range, param present +
  **numeric**, `lo<hi`, `initial∈[lo,hi]`, response in the enum, constraint via `parse_constraint_spec` — so a
  malformed optimize block raises `BuildSpecError` BEFORE any build/relax. Driver
  `hs.build_and_optimize_design(spec, ws, *, max_iterations, production_steps, tuned, **relax_params)` lowers it to the
  closed `hox.iterate_to_constraint` loop: synthesises `build_fn` (rebuild with the knob overriding
  `ops[op].params[param]`) + `adjust_fn` (bisection whose direction comes from the **declared** `response`, never an
  inferred bend sign) and resolves the constraint's grid_pos landmarks → runtime ids on one probe build (ids
  deterministic → stable across rebuilds). Oracle = reuse `assert_converges_to_constraint` (the AF-13 P4 capstone
  oracle): the spec converges a bend-curvature knob to the relaxed end-to-end target, confidence-gated + non-vacuous.
  Load-bearing because `assert_spec_matches_calls` is blind both to the bend overlay AND to a physical-layer
  convergence. Composition-sugar (coverage flat, 36; god-files Δ=0). NO ASK-FIRST: the knob magnitude is
  direction-agnostic, the monotone sense is a spec-author declaration the grammar lowers, never reasons about.

- [x] **AF-ATOM (Phase 1) — atomistic-display validation oracle + queryable route + `/validate-atomistic`
  skill. SHIPPED 2026-06-21.** Every element the oxDNA-display **atomistic** rep draws (each bond stick, each
  atom sphere) is now measurable, so a stretched / hidden / clashing element is queryable, not just visible.
  `backend/core/atomistic_validation.py`: `audit_bonds(design, frame)` reconstructs the model with the SAME
  `build_atomistic_model(frame_override=…)` the renderer uses (so audited bonds ARE rendered bonds — identical
  serial pairs) and classifies every bond `rigid | linker | backbone | bridge`, flagging **rigid-stamp
  violations** (frame-invariant bonds ≠ template = a placer bug; the *load-bearing* oracle), over-stretched
  bonds (the long sticks the screenshot shows), bonds the renderer **hides** (>1 nm — drawn as nothing but
  listed), clashes, and non-finite atoms.  `latest_job_for_design` / `relaxed_frame_for_job` / `audit_oxdna_job`
  give the headless entry point; route `POST /oxdna/jobs/{id}/display-atomistic-audit` makes the live app's
  displayed frame queryable; CLI `scripts/audit_atomistic.py` (`just audit-atomistic`) + the `validate-atomistic`
  skill drive it (default `workspace/6hb_sim_tests.nadoc` latest job). Tests: `tests/test_atomistic_validation.py`
  (8) — stamp-invariance, over-stretch/hidden/clash/non-finite detectors, class partition, job entry point,
  route. **Real-job finding (job c1299e0b07b5):** stamp clean (18 279 rigid bonds, max Δ 0.0000 Å, 0
  violations → placer correct), but **1005 backbone O3'→P bonds at mean 1.0 nm / max 3.16 nm** — oxDNA's
  one-bead-per-nucleotide frames don't enforce all-atom backbone continuity, so the sticks genuinely stretch
  (the screenshot). **Validation gained, not a passthrough:** first programmatic proof of which atomistic bonds
  are real vs over-stretched vs renderer-hidden, and that the rigid stamp is frame-invariant — a number no
  HTTP-200 or eyeball gives.  **Deferred → Tier F (AF-ATOM P2) + the backbone-closure feature below.**

### Tier 6 — time-resolved E-field response + interactive engine (the real-time field-exploration goal)

**What's different here.** Tier 5 measures a *static* property of one relaxed mean structure. Tier 6 measures a
**time course**: subject an anchored structure to an E-field and watch its helical alignment + base-pairing evolve
*frame by frame*, extracting an **equilibration time τ** and a **non-destructive window** (aligns without melting).
The oracle class is still Tier-5's stochastic/confidence-gated one, but now over a *trajectory* (per-frame
observables), not a single pooled mean. The capstone is an **automated cross-design field sweep**.

**What already exists (audited 2026-06-22 — do NOT rebuild; see `memory/project_oxdna_efield.md` + `project_oxdna_relaxation.md`).**
The *batch* field path is shipped and automatable end-to-end: `POST /oxdna/jobs/{id}/field` spawns a field **child
job** (parent's relaxed `last_conf` → single `field` stage) with composable forces (`write_field_forces` =
uniform `string` force on all beads + anchor `trap`s, `DEFAULT_ANCHOR_STIFF=1000` = immobile); anchors resolve
server-side (`resolve_anchor_particles`: overhang / cluster / domain → particle indices); the oracle
`measure_field_response(field_pos, ref_pos, field_dir, anchor_keys)` already asserts anchored-held + free-deflected-
along-field; `headless_oxdna_build.run_field` / `run_field_validation` / `field_response_from_confs` drive it
headlessly; and a **field-deflecting mock binary** (`_FIELD_MOCK_OXDNA`) shifts free beads ∝F0 along the field +
holds trapped beads → the whole pipeline + oracle run on CPU with NO GPU (deflection already pinned monotonic in
field magnitude). The field stage writes a `trajectory.dat` (the `/trajectory` route includes it; RMSF/flex-map
pools `kind in {production,field}`). **So Tier 6 builds measurement + sweep ON the existing field child-job +
mock**, not a new engine — except the AF-21/22 live sub-track.

**Physics caveats (load-bearing — keep them in every oracle's framing; from `project_oxdna_efield.md` §1).**
(1) **Quasi-static only** — no explicit ions/screening, no hydrodynamics, timestep can't reach AC fields; τ is the
*mechanical relaxation to a new DC pose*, NOT electrophoretic mobility, and the swing *trajectory* is qualitative
while the *equilibrium pose* is meaningful. (2) **Anchors are mandatory** (uniform field ⇒ net COM force ⇒ a free
structure streams across the box) AND **anchor selection matters** (pinning only a floppy ssDNA overhang holds the
overhang but lets the rigid duplex swing — pin a duplex/cluster to hold the body). (3) **τ vs throughput** —
re-equilibration is ~10⁵–10⁶ steps; interactive rates are realistic only for *small* specimens (single duplex +
overhang), batch for large origami. Frame these as documented scope, not as bugs.

**Three-Layer Law (as in Tier 5).** The field is a **Physical-layer** load; field/relaxed coords are read back as
display/measurement artifacts and **never written into `Design`**. The *anchor designation* and *overhang* are
topological/spec inputs the user (or spec) provides; the resolver is mechanical (no geometric reasoning about which
nucleotide aligns which way — that's the ASK-FIRST `feedback_crossover_no_reasoning` rule). Field direction +
magnitude are user/spec inputs; oracles measure **magnitudes** (alignment projection, |displacement|, τ) →
direction-agnostic, no sign/handedness reasoning enters the driver.

**oxpy prerequisite (AF-21+ only; AF-18/19/20/23-batch need none) — ✅ BUILT + WIRED 2026-06-23.** The interactive
engine needs oxDNA's Python binding **oxpy**, which lets a persistent Python process step the engine in bursts and
mutate the field force vector *without restarting / re-initing CUDA*. **Now built and importable from the NADOC
venv** (was `Python:BOOL=OFF`). As-built, for the AF-21 session — DO NOT re-derive:
- Rebuilt the EXISTING `~/oxDNA/build` (CUDA objects reused) with
  `cmake .. -DCUDA=ON -DPython=ON -DPython_EXECUTABLE=/home/joshua/NADOC/.venv/bin/python3 && make -j12`. Prereq was
  `sudo apt-get install -y python3-dev` (the venv runs on the *system* Python `/usr`; its dev headers were missing —
  user ran the one sudo step). pybind11 submodule was already populated at `~/oxDNA/src/oxpy/pybind11`.
- Built module: `~/oxDNA/build/python/oxpy/core.so` (+ `__init__.py`/`utils.py`), plain `setuptools` pyproject.
  **Editable-installed into the venv:** `uv pip install --python .venv/bin/python3 -e ~/oxDNA/build/python` → a future
  `make` that refreshes `core.so` is picked up automatically (no re-install). `import oxpy` works with NO PYTHONPATH.
- **API surface confirmed present** (the AF-21 substrate): `oxpy.OxpyManager` with `.run(steps)` (burst-step),
  `.current_step`/`.steps_run`, `.config_info` (live particle/position access), `.print_configuration`; top-level
  `oxpy.forces` (where the field `ConstantRateForce` is added + **mutated live** between bursts) and `oxpy.observables`
  (live alignment/bp monitoring). The standalone CLI binary (`find_oxdna` → `~/oxDNA/build/bin/oxDNA`) is unchanged, so
  the shipped *batch* field path (AF-18→20) is unaffected. Nothing in NADOC imports oxpy yet — AF-21 introduces the
  first `import oxpy` (in a NEW `backend/physics/oxdna_live.py`, NOT a god-file).
- **GOTCHA for AF-21 tests:** the parity oracle's binary half is GPU-free via `_FIELD_MOCK_OXDNA`, but the *oxpy* half
  needs the real engine — gate oxpy tests with `pytest.importorskip("oxpy")` (mirror the `skipif find_oxdna() is None`
  pattern) so CI on a machine without the build still passes.

- [x] **AF-18 — full-pipeline anchored field-specimen builder.** One headless call composing the entire
  build→field-ready chain into a single validated entry point: `hox.build_field_specimen(spec_or_design, ws, *,
  overhang, anchor, **relax_params) → {design, job, anchor_keys}` (new code in `headless_oxdna_build.py` /
  `headless_spec_build.py`, NOT a god-file) — bundle/route (`hb.auto_scaffold`+`hb.full_autostaple` or a build-spec)
  → `hb.full_sequence` → `hb.overhang_extrude` → `hox.run_relaxation` → designate the overhang/cluster as the field
  **anchor** (resolve via `resolve_anchor_particles`). **Augment = NEW `assert_field_ready_specimen(result, design,
  ws)`** — composes three proofs into "this specimen can run a field experiment": fully sequenced (reuse
  `assert_fully_sequenced`) + relaxed geometry recovered (reuse `assert_relaxed_geometry_recovered`) + **≥1 anchor
  resolves to particle indices AND a probe field holds the anchored beads while the free part deflects** (reuse
  `measure_field_response` on a short mock field run). **Load-bearing because nothing today proves an end-to-end-built
  design is field-experiment-ready** — each piece (sequence, relax, anchor) is pinned alone, but not that they
  compose into a runnable, anchorable specimen; the gap is exactly the user's "build → … → set as anchor" chain.
  Can-go-red: an unsequenced/unrelaxed/un-anchorable specimen fails the corresponding clause. No oxpy. **ASK-FIRST:**
  which nucleotides are the overhang/anchor is a spec input — do not infer it geometrically.

- [x] **AF-19 — field equilibration-timeline measurement (τ) + non-melt oracle.** The key NEW physical observable.
  Pure `measure_field_equilibration(frames, field_dir, anchor_keys, *, observable="alignment") → {tau_steps,
  plateau, aligned_final, bp_timecourse, melted}` in `backend/core/oxdna_health.py`: per-frame alignment of the free
  body's principal axis to the field (reuse the `field_response` projection) + per-frame base-pair retention (reuse
  the bp metric), fit the monotone approach to its plateau, extract τ (time to reach 1−1/e of the plateau).
  **Augment = NEW `assert_equilibration_timeline(job, ws, field_dir, anchor_keys, *, melt_floor, min_confidence)`** —
  the field trajectory shows a finite positive τ, a monotone-within-noise approach to a stable plateau, AND **bp
  retention never drops below `melt_floor` across the WHOLE timeline** (the "without ripping it apart" invariant),
  confidence-gated on frame count. **Load-bearing because `measure_field_response` is endpoint-only** (final
  aligned/displaced) — blind to the *time course* and to *transient* melting mid-swing. Reuses the `field`-stage
  trajectory + `_FIELD_MOCK_OXDNA` (its ∝F0-per-step shift gives a synthetic monotone alignment ramp for CI).
  Can-go-red: a non-converging (never-plateau) run → no finite τ; a melt during the swing → floor breach. No oxpy.

- [x] **AF-20 — field sweep driver + (|E|,direction)→response map + correlation oracle.** SHIPPED 2026-06-23
  (`hox.sweep_field_response` + `assert_field_sweep_map`; HARNESS block at the top of the handoff). `hox.sweep_field_response(
  specimen, intensities_pN, directions, ws) → {(pN,dir): {tau, aligned, bp_retained, destructive}}` — each grid cell
  a child field job off the same relaxed parent (reuse the field child-job spawn), measured by AF-19, assembled into
  a map flagging the non-destructive regime (`aligned ∧ bp_retained ≥ floor`). **Augment = NEW `assert_field_sweep_map(
  map, *, benign_range, destructive_range)`** — every cell carries a verdict (no gaps); the non-destructive regime is
  **non-empty in `benign_range` and empty in `destructive_range`** (can-go-red); AND **τ decreases monotonically with
  |E| in the responsive band** (the field-strength ↔ equilibration-timeline correlation the user wants). **Load-bearing
  as the first automated MULTI-config physical experiment with a reusable field↔τ correlation oracle** — Tier 5
  measured one structure at one condition; this measures a *response surface*. Reuses AF-19 + the mock's
  already-pinned "deflection scales with magnitude". Can-go-red: a flat (field-independent) τ, or a non-empty
  destructive window. No oxpy. **Log a `log()`/note if any cell is skipped** (no silent truncation of the sweep).

- [ ] **AF-21 — oxpy persistent interactive engine + equilibrium-parity / live-mutation oracle. [PREREQ: oxpy build
  `-DPython=ON` — ask the user first.]** NEW `backend/physics/oxdna_live.py` wrapping oxpy: `LiveOxdnaSession` loads
  topology+conf, steps in bursts (`run(M)` loop), **mutates the field `ConstantRateForce` vector live**, and reads CM
  positions in-process (no file round-trip, no CUDA re-init between bursts) — a cohesive module, NOT a god-file
  block. Headless `hox.run_live_field(...)` drives it. **Augment = NEW `assert_oxpy_equilibrium_parity(live_result,
  batch_result, *, tol, min_confidence)`** — an oxpy burst-stepped run reaches the **same equilibrium observables**
  (alignment, R_g, bp retention) within `tol` as a one-shot binary run of the same total steps from the same seed,
  **confidence-gated** (stochastic thermostats forbid trajectory parity → assert *equilibrium-property* parity, the
  Tier-5 stochastic-oracle class), AND **mutating the field vector mid-run shifts the measured deflection toward the
  new vector**. **Load-bearing because it proves the interactive engine is physically equivalent to the validated
  batch engine** (else "real-time" output is untrustworthy) + that live field control actually steers. The parity
  half is testable GPU-free against the binary `_FIELD_MOCK_OXDNA`; the live-mutation half needs the real oxpy build.
  Can-go-red: an oxpy run diverging from the binary beyond tol, or a field-vector change that doesn't move the body.

- [ ] **AF-22 — live field-steering session + field-following oracle. [builds on AF-21.]** `hox.steer_field_session(
  session, waypoints) → timeline` — set field dir d₁, run a burst, read observables; switch to d₂, run, read; … a
  steered timeline (the programmatic form of a user dragging the field gizmo). **Augment = NEW `assert_live_field_
  following(timeline, *, melt_floor)`** — after each waypoint the free body's alignment observable moves **toward the
  current field vector** (the structure follows the field), and bp retention stays above `melt_floor` across ALL
  waypoints. **Load-bearing because it proves the interactive control loop produces real field-following without
  melting** — the substance behind "playing in real time", distinct from a merely responsive UI. Reuses AF-19's
  per-frame observables + AF-21's session. Can-go-red: a body that ignores a waypoint change, or a melt during
  steering. (The frontend live-steering UI + frame-streaming WS is a separate Tier-F display item → push an `MV-`
  row when that ships; this AF item is the headless, automatable control loop.)

- [x] **AF-23 — CAPSTONE: cross-design automated field-response campaign (the user's stated goal). SHIPPED 2026-06-23**
  (`hox.run_field_campaign` + `assert_field_campaign`; HARNESS block at the top of the handoff).
  `hox.run_field_campaign(specs, intensities_pN, directions, ws) → {design_name: sweep_map}` — build each design from
  a build-spec / catalog primitive (reuse the AF-11/12 grammar + AF-18 specimen builder), run the AF-20 sweep on each,
  report **per-design non-destructive operating window + alignment-vs-field response**. **Augment = NEW
  `assert_field_campaign(campaign, *, expect_distinguishable)`** — every design yields a populated map with a reported
  non-destructive window; designs are **distinguishable** (a floppier / longer-lever design aligns at a lower |E| or
  shorter τ — proven on two specimens chosen to differ); reproducible across a re-run (deterministic mock). **Load-
  bearing as the capstone that ties text→design (grammar) + field sweep (AF-20) + equilibration (AF-19) into one
  automated study reusable for ANY origami** — "automatic exploration of E-field intensities and directions that
  correlate with DNA alignment equilibration timelines, without ripping it apart, for various designs." Runs on the
  batch path (AF-20, de-risked) now; transparently swaps to the AF-21/22 oxpy fast path once built. Can-go-red: a
  campaign where designs are indistinguishable (`expect_distinguishable` violated) or a design yields an empty map.

### Tier F — frontend display subsystems (no REST route; JS-controller API + vitest-oracle augment)

**What's different here.** These subsystems are driven entirely client-side (a JS controller exposed on
`window.__*`), so the augment is **vitest oracles reading real Three.js state**, NOT a `headless_build`
wrapper. The anti-shovel rule still bites: assert the setter drove the *object* (a scene-graph light, a
`material.metalness`, a `pass.enabled`, a `camera.fov`), never `getSettings()` (which just echoes stored
intent → a passthrough). Bound by `FEATURE_DEVELOPMENT.md` — lands in the subsystem module + its
`*.test.js`, never a god-file.

- [x] **AF-ATOM (Phase 2) — renderer↔audit parity. SHIPPED 2026-06-21.** `frontend/src/scene/atomistic_renderer.test.js`
  (+1, now 4): drives a bond set with known lengths through `applyPositionLerp` and asserts, by decomposing each
  bond InstancedMesh instance matrix, that the renderer zero-scales (hides) EXACTLY the >`_MAX_BOND_NM` (1 nm)
  bonds — the same set the backend audit reports as `hidden_by_renderer` (both use the 1 nm cutoff) — and draws
  every other stick at its true atom-distance (scaleY). **Validation gained:** the on-screen sticks are now tied
  to the audited model bond-for-bond, so a renderer regression (wrong cutoff/transform) is caught, not invisible.
  Original intake below.
- [ ] **AF-ATOM (Phase 2, original intake) — renderer↔audit parity.** AF-ATOM P1 validates the atomistic *model*; the *render* parity is now P2 (shipped, above).
  `atomistic_renderer.applyPositionLerp` hides bonds > `_MAX_BOND_NM` (1 nm) by zero-scaling the bond
  InstancedMesh instance. **Enabling fact:** the renderer can be built in jsdom with a real model + fake GL;
  the bond InstancedMesh `setMatrixAt` scales are readable. **Oracle:** drive a frame with N known >1 nm bonds,
  assert the renderer zero-scaled EXACTLY those N instances (the `hidden_by_renderer` set from the backend
  audit) and drew all others at a finite length spanning the correct two atom positions — closing "the stick
  you see is the bond the audit measured, and the bond you DON'T see is hidden, not lost." Anti-shovel: assert
  the InstancedMesh matrix (the real object), never a settings echo. Lands in
  `frontend/src/scene/atomistic_renderer.test.js`. **Validation gained:** first proof the render matches the
  audited model bond-for-bond — today a renderer regression (wrong cutoff, wrong transform) is invisible.
- [ ] **AF-ATOM (Phase 3) — per-atom sphere coverage oracle.** Assert every drawn atom-sphere instance's
  radius (element→VDW) + color (element→CPK) matches the model's element mapping, so no atom renders with the
  wrong size/color. Lower priority than P2 (spheres are less bug-prone than bonds). Lands in the renderer test.
- [x] **AF-ATOM-CLOSURE — display-time backbone closure (the FIX for the stretched O3'→P sticks). SHIPPED
  2026-06-21** (user-authorized the geometry fix).  Root cause (measured): the stretch is **systematic, not
  fraying** — on the real 6hb_sim_tests relaxed frame the sequential O3'→P gaps are ideal 0.166 nm but relaxed
  **median 0.91 nm / 95% > 0.6 nm**, because oxDNA's per-nucleotide CG frames don't enforce all-atom backbone
  continuity, so each rigidly-stamped O3'(i) misses P(i+1).  Fix: `atomistic._close_sequential_backbone`, gated
  on `frame_override` + `close_backbone=True` (DISPLAY path only — design/PDB/NAMD-seed byte-identical), re-seats
  only the phosphate linker (O3'/P/O5'/OP1/OP2) between the rigid C3'(i)/C5'(i+1) anchors via the validated
  `_interpolate_backbone_bridge` (linear, ~0.01 s for ~1000 bonds — 2000× faster than the L-BFGS bridge and
  slightly better; the ribose ring + base never move, so the rigid-stamp invariant holds).  **Audit-verified
  (the oracle IS the acceptance test):** backbone mean 1.005→0.185 nm, max **3.155→0.806 nm**, **hidden-by-
  renderer 266→0** (the whole backbone now draws connected — no long sticks, none silently hidden), rigid-stamp
  still 0 violations.  Residual: ~744 mild over-stretches (0.20–0.81 nm) + clashes at genuinely-frayed/tightly-
  packed regions — inherent to un-minimised CG→all-atom display, honestly surfaced by the audit (a full display
  minimisation would be the next step; out of scope).  Pins: `tests/test_atomistic_validation.py::test_backbone_
  closure_connects_and_preserves_rigid` + the P1 audit on the real job.  **Live visual is human-eye → MV-OXREPS.**

- [x] **AF-PHOTO (P-A + P-B) — photomode option-coverage + effect oracles. SHIPPED 2026-06-18.** `frontend/src/scene/photo_renderer.test.js` (39 tests): P-A drives each setter and asserts the REAL object (renderer.toneMapping/exposure, scene-graph lights, `material.metalness`, `camera.fov`, composer `pass.enabled` via the new `getComposerState()`); P-B is the automation contract (getSettings is a copy; a 21-case table proves every option is settable through the API + every key persists). Shipped alongside the R1–R5 render fixes from the audit (tone mapping + exposure, Sun-sole, env re-bake isolation, emissive bloom clamp, Reflector state isolation). Remaining: P-C GPU-truth e2e → `MV-PHOTO-1`/`MV-PHOTO-2` (manual-validation debt). Below is the original intake item.
- [x] **AF-PHOTO — photomode option-coverage + effect oracles. P-A + P-B SHIPPED 2026-06-18 (row above); only P-C (GPU-truth e2e) remains and is routed to manual-validation debt as `MV-PHOTO-1`/`MV-PHOTO-2`, NOT an active AF item.** Photo mode
  ([frontend/src/scene/photo_renderer.js](frontend/src/scene/photo_renderer.js), ~1588 ln, ~45 setters on
  `window.__photoRenderer`) has **zero test coverage**; no automated proof any option takes effect, nor that
  the full option surface is reachable + persisted programmatically. **Enabling fact:** the controller can be
  built in jsdom with a real scene/camera + fake renderer and `activate({environment:'off'})`; the
  `EffectComposer` + passes *construct* without GL (only `.render()` / PMREM baking need WebGL), so even
  `bloomPass.enabled` / inscatter uniforms are vitest-assertable. **Phases:** (P-A) table-driven per-setter
  effect oracles in a new `photo_renderer.test.js` — see catalogue in `photo_mode_audit_plan.md` Part 3;
  (P-B) automation-contract oracles — setter⇄`getSettings` completeness + full profile round-trip; (P-C,
  MV-debt) GPU-truth e2e incl. the **yellow/purple no-tint regression** that guards the R1–R3 render fixes.
  **Validation gained, not a passthrough:** first proof photomode options reach the GPU-facing objects + the
  whole surface round-trips. Plan + per-setter table + the R1–R5 render-bug remediation in
  **`photo_mode_audit_plan.md`** (repo root, from the 2026-06-18 audit). Two MV rows queued:
  `MV-PHOTO-1` (no-tint regression render), `MV-PHOTO-2` (mid-session env-change garbage-frame guard).

### Appendix — genuinely UI-only (route these to manual-validation debt, NOT here)

Operations with no coord-taking route — they can only be hand-validated. When an AF session confirms one
is un-headless-able, push an `MV-N` row to `manual_validation_debt.md` instead of an AF item:
- Instance/strand **selection + lasso multi-select** (client store state, no backend reflection).
- **Gizmo intermediate drags** (TransformControls partial states; only the *committed* transform has a route).
- Pure **view toggles** (coloring, labels, periodic-boundary view) — no design mutation, nothing to validate.
