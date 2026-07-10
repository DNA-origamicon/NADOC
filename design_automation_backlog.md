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

1. **Read** this map (start with the ≤8-line `## Next-session handoff`) + `design_automation_log.md`
   (conventions + oracle catalog + lessons + difficulties). Read `FEATURE_DEVELOPMENT.md` (module-first law).
   Skim the relevant `memory/project_*.md` for the area (e.g. `headless_build`, `assembly_overhaul`). Do NOT
   read `design_automation_harness.md` / `design_automation_metrics.md` wholesale — open only the harness
   block / metrics row for the item you're extending (the handoff names it).
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
8. **Update the ledgers:** check the box here; add a metrics row to **`design_automation_metrics.md`** **with
   the mandatory justification line**; if you shipped a reusable wrapper, add ONE block to
   **`design_automation_harness.md`** (+ its one-line index entry) and a row to the log's oracle catalog;
   bank any new lesson in the log. **Overwrite** `## Next-session handoff` (≤8 lines) — never append harness
   blocks to it; that regression is exactly what the 2026-06-25 split undid.
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

_Living pointer — OVERWRITE this each session (protocol step 8). Keep it ≤8 lines. Do NOT append harness blocks here — those live in `design_automation_harness.md`._

**▶ CORNER PRIMITIVE SHIPPED (2026-07-08, outside the AF numbering; see `project_corner_primitive.md`):** `backend/api/headless_corner_build.build_corner(*, n_helices=6, base_length_bp=56, target_angle_deg=90, optimize=True, optimize_fold=True)` — two SQUARE sheets, mitre-trimmed, sheet B folded 180° about the miter diagonal (logged `cluster_op`), N cross-seam forced ligations. **TWO optimizer stages:** (1) phase-aware LENGTH optimizer (two-constraint principle: axial miter + rotational phase) → 1.87 nm FL stretch (vs reference 3.43); (2) FOLD-POSE optimizer (user request) — tunes B's fold rotation+shift to cut the seam clashes the tight mating packs → **co-optimized beats the hand-tuned reference on BOTH axes: 11 genuine clashes @ 2.82 nm (vs reference 11 @ 3.43).** Validated with the design-layer **clash detector** (`clash.clash_report`) via `steric_clash_count` (= clash count MINUS seam FL bonds — a good ligation IS a sub-0.65 nm "clash" so must be excluded). Oracle `assert_corner_folded` (7 clauses, all 3 layers). Optimizers FAST (path-B analytic: beads are trim-invariant → build straight once; fold grid pre-filters to near-A B beads, ~5.5s). Tests `test_headless_corner_build.py` (14). USER-DECIDED length objective: lexicographic min-total-stretch, ±2bp window; fold objective: min `clash+4·Σbond` s.t. bonds<1nm + angle±5°.

**▶ DUPLEX-GRAPH COVERAGE (2026-06-30, Proposal-B — outside the AF numbering; see `project_overhang_duplex_foundation.md`):** the register-bearing overhang `Duplex` graph now has: headless `hb.connect_duplex` (wraps `POST /design/duplexes/connect`; creates the register + relocates a different-length driven onto the driver's paired window); oracle `assert_duplex_relocated` (relocated-but-NOT-stretched length pin, round-trip stable); `summarize_duplexes` readout; and a `validate_design` soft check (flags a duplex whose register has ZERO complementary bases — the Q2 "applied but not pairing" warning; partial mismatches OK). Tests `test_duplex_automation.py` / `test_duplex_relocate.py` / `test_duplex_length_preserve.py`. Remaining duplex geometry: driver-flip re-place for the binding-less path + a binding-less relax (see topic file).

**▶ INTAKE (2026-07-01):** Constrained-move work shipped (ds-linker rigid strut + movable-link duplex swing + selection-driven Move/Rotate) with headless DESCRIPTORS tested (`cluster_connection_tethers` / `cluster_movable_links` in `test_connection_tethers.py`) but the constrained-drag SOLVERS are JS-only in the gizmo → NEW gaps **AF-40** (headless free-until-taut + ds rigid-strut projector port + `assert_tethers_satisfied`) and **AF-41** (headless movable-link chain solve + `assert_link_chain_settled`, depends on AF-40). Both mirror AF-29's parity-port pattern; today these behaviors are human-eye-only (MV-CONNTETHER / MV-CONNLINK / MV-MRSEL). Good self-contained pickups.

**▶ STATE (2026-06-29):** Tiers 0–7 + AF-36 + **AF-27 P1+P2** + **AF-37 end-to-root binding** + **AF-38 direct-bind RELAX** done (coverage **54**). **AF-38 (this loop) = "relax for ALL connection types":** AF-27 P2 had ds/ss LINKER + generic-bond relax; AF-38 adds the two DIRECT-bind paths — `hb.relax_overhang_binding(binding_id)` (root-to-root, wraps `POST /design/overhang-bindings/{id}/relax`) + `hb.relax_end_to_root(version_id)` (version-keyed, wraps the NEW `POST /design/connection-versions/{id}/relax-end-to-root`; solver `backend/core/end_to_root_relax.py` swings A's overhang duplex 2-DOF [persisted as `OverhangSpec.rotation`] + cluster kinematics to close the spliced FL chord; same body → swing only). Oracles `assert_binding_relaxed_pose` + `assert_end_to_root_relaxed_pose` (minimized-bond-distance, strain-reduction on POSED geometry; the e2r pose-moved clause accepts an overhang-ROTATION change, not just a cluster). **GAPS (open):** (1) ss-LINKER relax is wrapped + oracle-supported (`natural_span_nm=R_ee`) but has NO ss-specific headless test; (2) direct-binding CREATION still unwrapped (AF-37 blockers 1–4) — root-to-root bindings are model-built by hand for the relax fixture; only e2r creation is wrapped. AF-37 root-to-root / sub-domain-binding / joint-lock STILL OPEN. AF-24 **P2/P3** still **OTHER COMPUTER — don't pick up.**
**▶ DEPENDENCY (hinge chain):** AF-33/34/35/36 + AF-27 P1/P2 DONE. Multi-link ROUTING (G6) is an algorithm blocker in `project_hinge_autoscaffold.md`, NOT an AF item; `test_hinge_router::test_multi_link_hinge_routes` xfail keeps it visible.
**▶ NEXT cycle — COMPOSE the full hinge-with-linker end-to-end (the AF-27 keystone now has all its pieces).** Drive a `scratchpad/build_linked_hinge.py` generator (lift the AF-36 pattern): `build_hinge(k,n)` → `overhang_extrude` a staple overhang on EACH leaf at the gap face → `hb.connect_overhangs` (P1) to tie them with a ds/ss linker whose contour CONFINES the angle → place a revolute joint on the gap edge → `hb.relax_overhang_connection` to settle the rest pose → set absolute hinge angle → save. **ASK-FIRST** (still un-answered, the real blocker): WHICH overhang nucleotide is the linker attach endpoint, ss-vs-ds, and the bridge length for a given gap — directionality/topology, do NOT infer. Augment = compose `assert_linker_connects` (P1) + `assert_linker_relaxed_pose` (P2) on the generated design. Consider promoting the generator to a headless module (`headless_hinge_build.build_linked_hinge`) if it stabilises.
**▶ ALSO PICKABLE NOW (AF-38 gaps, small + self-contained — good warm-up items):** **(G1 = AF-39)** ss-LINKER relax has NO ss-specific headless test — the `relax_overhang_connection` wrapper dispatches to `relax_ss_linker` (FJC R_ee target) and `assert_linker_relaxed_pose(natural_span_nm=R_ee)` already supports it, so this is a fixture+test add (a 2-overhang ss-linker leaf pair + a joint, relax, assert strain→R_ee falls), no new wrapper/oracle. See AF-39 entry. **(G2)** direct-binding **CREATION** is still unwrapped (only RELAX + end-to-root creation are) → it's exactly AF-37's open blockers 1–4 (`hb.create_overhang_binding` + sub-domain `split`/sequence wrappers + `assert_binding_locks_joint`); closing G2 = doing AF-37 root-to-root. Older open: AF-24 P2/P3 (OTHER COMPUTER), Tier F AF-ATOM P2/P3.
**▶ GOTCHAS banked:** (AF-27 P2) the linker relax optimises CONNECTOR-ARC residuals (toward ~0.67nm each) by rotating the joint cluster — it does NOT directly minimise the raw anchor-to-anchor chord, but the consequence is the chord moves to the duplex's natural span (`_ds_target_length_nm`); so the solver-independent oracle is STRAIN-REDUCTION (`|chord − natural_span|` falls), NOT chord-≤-contour (which is either vacuous for a long linker already within, or unsatisfiable for a short one that can't close). The natural relax fixture is DEGENERATE: with the joint origin ON the moving overhang (`[2.5,0,0]`) the anchor is on the hinge axis so rotation can't change the chord (cluster transform changes by a tiny θ but strain is flat) — that's the load-bearing can-go-red; move the joint origin OFF the overhang (`[0,0,0]`) for a real reduction. Both relax routes are POSE-ONLY (mutate `cluster_transforms` + append a `ClusterOpLogEntry`, never the strand graph → `canonical_topology` invariant). DROP the grid_pos-less `demo_helix` from any relax test fixture or `canonical_topology` raises (sorts helix tuples, None grid_pos breaks `<`). The relax resolves linker anchors from the CONNECTION METADATA alone (geometry emits the `__lnk__` bridge), so a metadata-only `OverhangConnection` (no real bridge strands) is a valid fixture AND keeps `canonical_topology` seeing only the two real overhang helices. (AF-36) hinge ssDNA is PHASE-PAIRED short/long, NOT uniform: neighbouring rail helices carry OPPOSITE phase → the TOWARD-facing rail takes a SHORT (2nt) tether, the AWAY-facing one a LONG (16nt ≈ 1 turn to re-phase); `_rail_faces_toward` (scaffold backbone radial · rail-pair chord at the gap-face duplex-edge bp) decides it, validated byte-for-byte vs the goldens; ALL ssDNA on the leaf-A rail, leaf B blunt. The 2x2 golden was INVERTED (mis-authored) — the user CORRECTED it mid-session; SURFACE a golden that contradicts a stated rule, don't silently match. Feature-log SEEK was blind to `cluster_joints`/`flexible_segment_marks`/`flexible_connections` (`_topology_substitute` swapped only strand-graph + overhangs) → they persisted at EVERY seek incl. the empty state; fix restores them from the seek snapshot (membership is topology-like, same rationale as overhangs; joints store a LOCAL-frame axis so invariant under the cluster-transform delta replay). Commit a relax as a logged `cluster_op` (`transform_cluster(log=True)` per moved cluster, from `compute_relax_transforms`), NOT the `flexible-relax` route, for seek fidelity (seek reconstructs cluster poses ONLY from `cluster_op`). "Set hinge angle = X°" → compose the fold onto the relaxed REST pose, solving θ so the SIGNED dihedral about the hinge axis == X (linear in θ → exact); place the joint BEFORE folding (rotation about its own axis leaves the hinge line invariant). (AF-35) preserve-verbatim placement is a rigid GRAFT, NOT a route-replay: `create_bundle` is destructive (the GUI placement uses `bundle-segment`, a DIFFERENT builder whose axis floats differ from `create_bundle`'s by the AF-30 ISSUE-13 re-trim) — so the only way to land the primitive's EXACT axis geometry is to copy its already-built helices and translate by one rigid lattice vector. `canonical_topology` rounds axes to 4 dp, so float add-then-subtract of the same world-delta is exact. The hinge ALSO carries 2 identity `cluster_transforms` (the rigid leaves) + a construction `feature_log` → the graft copies+remaps the clusters (verbatim) but does NOT graft the feature_log (it's the standalone's history, not the host's). `assert_primitive_placed` offset-corrects INDEPENDENTLY via `_lattice_position` (ground-truth lattice constant, NOT the graft's own `_world_delta`) so a graft plane-mapping/translation bug can't mask itself. Honeycomb odd-parity shift = non-rigid (stagger flips) → the graft raises (same rule as the GUI's parity-snap); SQUARE is unconstrained. Placement does NOT shift along-axis (`offset_nm`) — deferred. (AF-34) a plain `create_bundle` routed seamed is NOT compliant (its blunt full-length staples bury the end crossovers → 2bp margin) — so the oracle's GREEN meta-test uses a SEAMLESS route at `require_seams=False` (its end crossovers land in extended ssDNA) and the same seamless route at `require_seams=True` is the load-bearing RED; the genuine seamed-green path is the HINGE end-to-end (its duplex shift leaves proper margins). `build_hinge_primitive` needs NO golden file (builds from scratch) so the AF-34 end-to-end runs in a clean checkout. (AF-33) the 2x2 golden's recipe is `create_bundle(len=40, ligate_adjacent=True)` → resize EVERY helix's low-bp end +8 (shift duplex into bp 8…39) → 2 gap-bridge `(resize,force_ligate)` pairs; the bridge trims are ASYMMETRIC (`scaf_1_0` 3p −3, `scaf_1_1` 5p −16) — that's hand-authored gap geometry, replayed as a constant, NOT re-derived (ASK-FIRST). Replaying create-at-40-then-shift (not create-at-32) is load-bearing: AF-30 ISSUE-13 axis re-trim means only the same op sequence reproduces the golden's axis floats. `_fl_endpoint_set` check is load-bearing (canonical_topology blind to FLs). The whole golden recipe lives in the file's own `feature_log` (SnapshotLogEntry params + RoutingClusterLogEntry children). **(AF-33 P2, done)** 2x4 trims are ASYMMETRIC by column parity (even `3p −16` / odd `5p −2`) and differ from 2x2 → per-primitive constants, transcribed verbatim; 2x6 was generated by `build_hinge(2,6)` so it has NO trims (`build_hinge(2,6)` reproduces the 2x6 golden byte-for-byte; `build_hinge(2,4)` does NOT — golden has hand trims). Per-bridge (trim→FL) replay == golden's all-trims-then-all-FLs (per-column strand independence). (AF-30) the inverse pair is NOT clean from a raw `create_bundle` — `resize_strand_ends`' axis re-trim uses `(max_index−min_index)·rise` but `create_bundle` uses `length_bp·rise` (one rise longer), so the FIRST resize shifts the helix `axis_end` convention and `canonical_topology` (fingerprints axis floats) never restores → capture `start` AFTER a settling resize so both ±δ runs share the re-trim convention (logged ISSUE-13, ask-first geometry convention). The resize DOES change the nuc count (that's the point); the ISSUE-13 *axis-endpoint* off-by-one does NOT, so `assert_geometric_length_delta` stays clean — but pick the resized strand so its terminal domain DEFINES the helix extent, else the count won't move (resizing inward, within another strand's span, leaves `length_bp` unchanged). (AF-32) force-ligate→delete is a CLEAN inverse pair; `assert_forced_ligation` takes BOTH `before` AND `after`; 2hb HC bundle `[[0,0],[0,1]]` has one scaffold strand per helix off `create_bundle`. (AF-31) inverse pair is **delete→place** (place adds nicks). (AF-29) `cluster_gizmo.js` NOT rewired to pure `flexible_relax_solver.js`.
**▶ REFERENCE (read on demand, NOT per loop):** shipped wrapper signatures + banked gotchas → `design_automation_harness.md` (consult per-item). Per-item metrics rows + data fits → `design_automation_metrics.md`. Oracle catalog + lessons + difficulties → `design_automation_log.md`.

## Backlog — open items (ranked). Full rows + all SHIPPED items live in the archive.

_The verbose full rows (open + shipped) moved to `design_automation_backlog_archive.md` for context economy._
_These are the still-open/actionable `AF-N`; click through for the full audited row._

- **AF-27** — overhang-linker create + linker/bond relax — hinge-confinement keystone; P1+P2 shipped, parent open. [detail](design_automation_backlog_archive.md#af-27)
- **AF-37** — direct overhang-binding + sub-domain wrappers — root-to-root / joint-lock open (end-to-root shipped). [detail](design_automation_backlog_archive.md#af-37)
- **AF-39** — ss-linker relax headless test (AF-38 gap G1) — fixture+test only, no new wrapper. [detail](design_automation_backlog_archive.md#af-39)
- **AF-40** — headless constrained-drag solver (free-until-taut + ds rigid-strut) + tether oracle. [detail](design_automation_backlog_archive.md#af-40)
- **AF-41** — headless movable-link chain solve + oracle — depends on AF-40. [detail](design_automation_backlog_archive.md#af-41)
- **AF-28** — hinge-angle linker designer: overhang-placement optimizer — open question, depends on AF-27. [detail](design_automation_backlog_archive.md#af-28)
- **AF-24 P2/P3** — real-engine field-sweep + cross-design campaign — OTHER COMPUTER, don't pick up. [detail](design_automation_backlog_archive.md#af-24)
- **AF-ATOM P3** — per-atom sphere coverage oracle (Tier F). [detail](design_automation_backlog_archive.md#af-atom-p3)

> **History.** Shipped AF items live in [design_automation_backlog_archive.md](design_automation_backlog_archive.md). Read on demand only — never in a routine loop.
