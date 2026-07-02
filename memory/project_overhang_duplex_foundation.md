---
name: overhang-duplex-foundation
description: "Proposal-B rebuild of overhang pairing — a Duplex graph (register-bearing edges over helix bp intervals) replacing the symmetric equal-length one-per-overhang OverhangBinding. Supports relative slide, multivalency, mismatches, toeholds, fluorophores. Phased build; automation+validation per phase."
metadata:
  node_type: memory
  type: project
---

# Overhang Duplex foundation (Proposal B) — phased rebuild

Replaces the old `OverhangBinding` (symmetric, equal-length, one-per-overhang,
whole-sub-domain, monolithic relocation+one-joint-freeze) with a **Duplex graph**:
register-bearing hybridization edges over the EXISTING helix bp coordinate. See
the design discussion in this session for the full rationale.

## Locked decisions (user, 2026-06-30)
- **Coordinate (Q1):** reuse the existing helix bp index (like `Domain.start_bp/
  end_bp`). A `DuplexEnd` = `{overhang_id, start_bp, end_bp}` in that overhang's
  backing-domain helix coordinate; order encodes 5'→3' (mirrors sequences.py
  `bp = d.start_bp + offset*sign(end-start)`). NO new per-overhang slot index.
- **Register vs apply (Q1):** when APPLIED both ends are co-located on the driver's
  helix (apply already relocates the driven domain there). The *relative* bp
  positioning on that shared helix IS the register and is what a drag edits.
  Moving overhangs while UNAPPLIED (separate helices) must NOT change the stored
  applied register.
- **Slide = cadnano drag (Q2):** dragging must UPDATE the register, not break the
  handler. Sliding past an end to zero overlap is ALLOWED; warn (not error) if an
  APPLIED duplex has no overlapping bp range between its partners.
- **Mismatches yes, bulges deferred (Q3):** both ends EQUAL length (no gapped
  alignment). Per-base WC check → paired/mismatch; no bulge (length-asymmetric)
  support — deferred indefinitely.
- **Driver explicit (Q4):** `Duplex.driver: 'left'|'right'`, user-set via a toggle
  even for monovalent. Multivalent v1 rule: **longest overhang is the driver**
  (shorter partners ride its helix). Full multi-joint solve deferred.
- **Process (Q5):** build automation + validation for EACH phase before the next.
- **Length preservation (2026-06-30):** connecting two DIFFERENT-length overhangs
  must NEVER resize either one (the OLD binding path forced equal-length tip
  sub-domains + resized on apply — that is exactly what we're replacing). The
  duplex pairs the shorter window (default `length = min(lenA, lenB)`, anchored at
  each attach end); the longer overhang keeps its full backing-domain length and
  its excess bases become a **toehold** (uncovered = unpaired). No `create`/`apply`
  step touches `Domain.start_bp/end_bp`. Locked by
  `test_duplex_crud.test_connect_different_lengths_preserves_both` + the
  Phase-4 geometry rule (derived placement, never a resize).
  - **BUG FIXED 2026-06-30 (user-reported "one ends up the length of the other"):**
    a `patch_overhang` SEQUENCE write resizes the backing domain to
    `len(sequence)` ([crud.py](backend/api/crud.py) `_build_overhang_patch`,
    `new_length_bp = len(new_seq)`). The connect flow set `B = RC(full A)` →
    resized B to A's length. TWO fixes: (1) frontend `_ensureComplementarySequences`
    / `_genSide` now cap the RC to the target's current length via
    `capSequenceToLength` (mirrors backend `_cv_sequence_for_live_overhang`) so the
    write never resizes; (2) backend `_cv_create_bound_binding` SKIPS different-
    length pairs (an unequal binding would fail validation / force equalization) —
    the Duplex represents them, binding-geometry deferred. Tests:
    `design_queries.test capSequenceToLength`, `overhang_connections_panel.lengthcap.test.js`,
    `test_duplex_length_preserve.py`.

## Phases
0. **Model groundwork (no behavior change). ✅ DONE 2026-06-30.** `DuplexEnd`/
   `Duplex` models ([models.py](backend/core/models.py)) + `Design.duplexes` +
   `_validate_duplexes` (skips when empty) + migration
   `synthesize_duplexes_from_bindings` ([core/duplex.py](backend/core/duplex.py),
   standalone, NOT auto-run). Tests: [tests/test_duplex_model.py](tests/test_duplex_model.py)
   (13). `just test` = 3394 passed (the 1 failure, `test_build_2x6_matches_golden`,
   is PRE-EXISTING golden drift on clean master — 42 vs 37 strands, unrelated).
1. **Pairing topology + CRUD. ✅ DONE 2026-06-30.**
   [routes_duplex.py](backend/api/routes_duplex.py): `GET/POST/PATCH/DELETE
   /design/duplexes` + `GET /design/duplexes/{id}/pairing` + `GET
   /design/overhangs/{id}/pairing-map`. Core ([core/duplex.py](backend/core/duplex.py)):
   `classify_duplex_pairing` (antiparallel per-base paired/mismatch, N-wildcard),
   `overhang_pairing_map` (bp→paired/mismatch/**toehold**, aggregates all duplexes =
   multivalency), `summarize_duplexes` (headless oracle), `duplex_wc_ok`,
   `smallest_unused_duplex_name`. **One-per-overhang dropped** (multivalency: only
   the no-double-pairing 409 remains). **WC gate KEPT** (user) — mismatch register =
   422; flip `duplex_wc_ok` off later for mismatched-kinetics designs. Equal-length
   still enforced on the model (bulges deferred). Tests:
   [test_duplex_classifier.py](tests/test_duplex_classifier.py) (6) +
   [test_duplex_crud.py](tests/test_duplex_crud.py) (12). `just test` = 3412 passed
   (same 1 pre-existing golden failure). NOT yet wired to any UI (Phase 2).
2. **Sequence + display read the graph. ✅ DONE 2026-06-30.** Pure JS mirror of
   `core/duplex.py` in [design_queries.js](frontend/src/scene/design_queries.js):
   `classifyDuplex`, `overhangDuplexCoverage` (bp→paired/mismatch/toehold),
   `overhangHasDuplex`, `overhangDuplexSegments` (colored runs). Client fns
   `createDuplex`/`patchDuplex`/`deleteDuplex` in
   [overhang_endpoints.js](frontend/src/api/overhang_endpoints.js). Connections-panel
   per-side preview now PREFERS the stored register (`_duplexLineEl`, green/amber/
   grey) when either side is in a duplex, falling back to the attach-anchored
   `pairingSegments` otherwise. Tests: design_queries.test.js (+6 mirror),
   `overhang_connections_panel.duplex.test.js` (+1). `just test-frontend` 1831 pass.
   **NOT VERIFIED IN APP:** `design.duplexes` is empty at runtime until a producer
   exists (Phase 3 connect flow or migration-on-load), so the display path is
   proven by tests, not yet visible.
3. Slide + a producer. **Step (a) DONE 2026-06-30:** migration wired into load —
   [crud.py](backend/api/crud.py) `_derive_duplexes_if_empty` runs in
   `/design/load` + `/design/import` (guarded: duplexes empty AND bindings exist;
   bindings stay). Existing binding-designs now show the graph. VISIBLY VALIDATED:
   [e2e/duplex_pairing_display.spec.js](frontend/e2e/duplex_pairing_display.spec.js)
   loads a fixture ([scripts/gen_duplex_demo_fixture.py](scripts/gen_duplex_demo_fixture.py)
   → `workspace/playwright_tests/duplex_demo.nadoc`, 6 bp A bound to 4 bp B) and
   asserts the connections-panel preview renders AAAC green (paired) + GG grey
   (toehold). Backend: `test_duplex_crud` +2 (`_derive_duplexes_if_empty`,
   import-endpoint). `just test` 3415 passed. **Remaining Phase-3 (b):** the
   cadnano drag updates the register (Q2), warn on zero-overlap applied; and a
   real connect flow that creates duplexes (min-length at attach ends).
4. Geometry derivation + user driver toggle (Q4); replace relocation/one-joint-
   freeze with derived placement; longest-drives multivalency.
5. **Attachments (fluorophore/quencher) — ALREADY EXISTED; my duplicate REVERTED
   2026-06-30 (user caught it).** Fluorophores/quenchers/biotin are the EXISTING
   `StrandExtension.modification` feature (`MODIFICATION_COLORS` = cy3/cy5/fam/tamra/
   atto488/atto550/bhq1/bhq2/biotin), with full single+batch CRUD
   ([routes_extensions.py](backend/api/routes_extensions.py)), geometry (beads on a
   Bézier arc off the terminus, `__ext_` helix), AND emission-glow rendering + FRET
   analysis ([fret_checker.js](frontend/src/scene/fret_checker.js) via
   `createMultiColorGlowLayer`, wired in main.js). **To put a fluorophore on an
   overhang: add a `StrandExtension{ strand_id, end, modification:'cy3' }` on the
   overhang's staple strand terminus** — already rendered + FRET-aware. I mistakenly
   built a parallel `Attachment` model (subset of StrandExtension, no FRET/geometry);
   it was fully reverted (model/routes/validator/headless/oracle/frontend/tests/fixture
   removed; coverage back to 54). Decision (user): terminal (5'/3') placement is
   enough; if internal-base labels are ever needed, EXTEND StrandExtension, not a new
   model. **Phase 5 is effectively already shipped via StrandExtension.**
   - **Right-click reach fix (2026-06-30):** an overhang-bead right-click routes to the
     overhang orientation menu, which had NO extensions item — so
     fluorophore/modification was unreachable from any overhang (plain, applied/
     relocated, relaxed — all carry `overhang_id`). Fix: the overhang menu
     ([overhang_orientation_menu.js](frontend/src/ui/overhang_orientation_menu.js)) now
     offers "Add/Edit extensions…" for the overhang's backing strand, opening the SAME
     dialog the strand menu uses via new `selectionManager.openExtensionsForStrands`
     ([selection_manager.js](frontend/src/scene/selection_manager.js)); wired in main.js.
     Binder domains already reached extensions (PAIRED → not the overhang route →
     strand menu, which has the item). Tests: `overhang_orientation_menu.test.js` (+4);
     `just smoke` green. **NOT hand-driven** — the live right-click-on-bead gesture
     wasn't manually exercised (menu logic + main.js wiring are unit/smoke-tested).
   - **Extensions automation + validation (2026-06-30):** `validate_design` now flags
     bad extensions (dangling strand / unknown modification / non-ACGTN sequence)
     ([validator.py](backend/core/validator.py)); headless `hb.add_strand_extension`
     (route coverage 54→55) + oracle `assert_extension_present` (round-trip)
     ([automation_harness.py](tests/automation_harness.py)); ledger row added. Tests
     `test_extensions_automation.py` (4). **Fluorophore Playwright (VISIBLE):**
     `e2e/fluorophore_toggle.spec.js` loads a Cy3-extension design, toggles View ▸
     Fluorescence (`menu-view-fluorescence`), asserts the glow renders (new
     `designRenderer.fluoroGlowCount()` / `createMultiColorGlowLayer.count()`) and
     clears on toggle-off. Fixture `workspace/playwright_tests/fluorophore_demo.nadoc`
     (regen `scripts/gen_fluorophore_demo_fixture.py`).

**Gen-button + pair-warning overhaul (2026-06-30, frontend-only).**
- **Warning** now fires ONLY when two direct overhangs share NO complementary
  region at all (`_complementaryOverlap === 0`) — a PARTIAL overlap (different-length
  overhangs with a real pairing window) is no longer flagged. New text: "…share no
  complementary region."
- **Shared Gen flow** [overhang_gen.js](frontend/src/ui/overhang_gen.js)
  (`runOverhangGen`) reused by the Connections panel per-side Gen AND the Overhangs
  sidebar Gen: no partner → random; partner-seq'd + this empty → RC(partner); BOTH
  seq'd → a 3-way `showChoice` ([primitives/choice.js](frontend/src/ui/primitives/choice.js),
  new multi-option modal): 'pair' (new random here + RC to partner) / 'override' (new
  random this only) / 'rc' (RC of partner). All-N counts as unsequenced. Choice buttons
  use SHORT labels ('New pair' / 'New (this only)' / 'RC of partner') with the long
  description as a hover `title` tooltip (`choice.js` passes `o.tooltip`→button title).
  **RC is REGISTER-AWARE** (2026-07-01): every "set to RC of partner" write goes through
  the injected `rcOfPartner`, which the panels wire to `overhangRcOfPartner(design,
  target, source)` in [design_queries.js](frontend/src/scene/design_queries.js). It
  overwrites ONLY the target's paired-window bases (per the connecting duplex register,
  reusing `classifyDuplex`'s antiparallel offset walk) with the WC complement of the
  register-aligned source bases, and PRESERVES the toehold — so the target keeps its own
  length (no resize; the old blunt `capSeq(reverseComplement(fullPartner))` was WRONG for
  different-length/toehold overhangs — it RC'd the whole partner then truncated/N-padded,
  misplacing the pairing and wiping the toehold). No duplex → full RC over the shorter
  length, roots aligned. Returns null (write skipped) when no backing domain. Sidebar Gen
  stays visible for a CONNECTED sequenced overhang so the choice is reachable. Tests:
  `overhang_gen.test.js` (injected-rcOfPartner + null-skip), `design_queries.test`
  (`overhangRcOfPartner`: window-RC-keep-toehold, no-duplex full RC, null), `choice.test.js`
  (tooltip), seqpair (backing domains added). `just test-frontend` 1857 green. **NOT
  hand-driven** — the live Gen-click→dialog gesture wasn't manually exercised (logic +
  modal + wiring + register math are unit-tested; verified by hand against the
  `2x2_OH_test.nadoc` register).
- **Relax on a binding-less duplex** (2026-07-01): the Connections-panel "Relax"
  button previously only knew the legacy `OverhangConnection`(linker)/`OverhangBinding`
  paths, so a DIRECT r2r connection stored as a bound `Duplex` with `overhang_bindings:[]`
  (the different-length/relocated case) left Relax DISABLED → clicking did nothing. Added
  `POST /design/duplexes/{id}/relax` ([routes_duplex.py](backend/api/routes_duplex.py)):
  resolves driver/driven from the duplex's `driver` field and runs the SAME proven
  `direct_relax.relax_direct_binding` solve (swing driver overhang about its root +
  cluster kinematics) that `relax_overhang_binding` uses — no new solver. 422 if the
  duplex isn't `bound` (driven not yet relocated), 404 if unknown. Client `relaxDuplex`
  ([overhang_endpoints.js](frontend/src/api/overhang_endpoints.js)); panel `_onSecondary`
  + button-enable now fall back to `_boundDuplexForPair()` when there's no linker/binding.
  Headless `hb.relax_duplex` + oracle `assert_duplex_relaxed` (delegates to
  `assert_direct_binding_relaxed_pose`: chord-closed + pose-moved + topology-unchanged).
  Route coverage 55→56 (THREE meta-tests bumped: `test_spec_build_adds_no_coverage`,
  `test_align_cluster_edge_adds_no_coverage`, AND `test_oxdna_coverage_report_*` which was
  stale at 53). Tests: `test_duplex_relax.py` (fixture relax closes bond + 422 unbound +
  404), `test_duplex_automation.py` (hb.relax_duplex + oracle). `just test` green (only
  pre-existing `test_build_2x6_matches_golden` fails). **NOT hand-driven** — live
  Relax-button click on the running app not manually exercised (endpoint + panel wiring
  are unit/fixture-tested against `2x2_OH_test.nadoc`).
- **Relax overshoot / min-motion fix** (2026-07-01): the shared `direct_relax` solve
  (used by BOTH `relax_overhang_binding` and `relax_duplex`) over-rotated the cluster
  hinge / wasn't idempotent. ROOT CAUSE: the solve is UNDER-CONSTRAINED — the 2-DOF
  overhang swing about the driver root can close the tip↔root chord at ANY hinge angle,
  so the joint θ is a free null-space parameter. The weak reg (`_THETA_REG_LAMBDA=1e-3`)
  couldn't pin it, and bounded Powell drifted θ (even returning a point WORSE than its
  x0), so every relax click rotated the hinge further (−22.5°→−29.5° on an
  already-closed bond). User decision: **minimize total motion** (Σ swing²+hinge²). FIX
  ([direct_relax.py](backend/core/direct_relax.py)): lexicographic post-selection —
  collect every seed's Powell result PLUS the do-nothing params=0, then pick the
  least-Σparams² candidate whose chord is within `_CHORD_ACCEPT_BAND_NM=0.02` of the best
  achievable chord (+ extra θ-perturbed seeds). Result: idempotent (already-closed bond →
  no hinge drift) and a fresh pre-relax closes with the LOCAL swing (θ≈2°) instead of
  swinging the whole cluster. Shared solver → also fixes the legacy binding + end-to-root
  relax. Tests: `test_duplex_relax.py` (idempotent + min-motion + route + 422/404),
  `test_duplex_automation.py` (oracle + idempotent) against a FROZEN immutable copy
  `tests/fixtures/relax_2x2_binding.nadoc` (the live workspace `.nadoc` is hand-edited
  between sessions — do NOT depend on it in tests). Existing 250 relax/binding tests
  green. **NOT hand-driven** — live Relax-button click not manually re-exercised after
  the solver change (solver behaviour pinned numerically against the frozen fixture).
- **Relax target = one-sided floor** (2026-07-01, follow-up): the min-motion fix still
  drove the tip↔root gap TO 0.67 nm; but the gap can go below 0.67 (closest approach
  ~0.2 nm), so a two-sided `(chord−target)²` backed a too-close bond APART to 0.67,
  over-rotating the hinge past closest approach. User decision: **minimize, floored at
  0.67** — only CLOSE a stretched bond, never back off a close one. FIX: one-sided strain
  `_stretch = max(0, chord − target)` in `_loss` + the selection residual (+ floored the
  0-DOF translate branch). chord ≤ target ⇒ zero strain ⇒ already-close bond stays put;
  a stretched bond stops at the NEAR-side floor. Pinned by
  `test_relax_does_not_back_off_an_already_close_bond` (frozen `relax_2x2_closebond.nadoc`,
  chord 0.38 → unchanged). See LESSONS E7. **NOT hand-driven** — re-apply + Relax in-app
  to confirm the hinge holds near your manual angle.
- **Direct apply → linker-bridge-style ORIENTED MIDPOINT placement** (2026-07-01, user:
  "make it behave like linker bridges"): a direct connection's apply used to relocate the
  driven tip onto the driver's helix and leave the WHOLE tip↔root stretch on the driven
  side. NEW: on apply the relocated duplex is re-seated like a linker bridge — **oriented
  along** and **centered on** the chord between its two embedded-staple connections (A's
  root junction, B's root junction) — so BOTH root bonds are equal and minimized
  (`bond_A = −bond_B`, each `(gap−span)/2`). Mechanism: new **`OverhangSpec.translation`**
  (nm) applied `p'=R(p−pivot)+pivot+translation` at geometry time, **paired with
  `OverhangSpec.rotation`** — apply now writes BOTH. `direct_relax.duplex_midpoint_placement`
  computes `R` (aligns duplex axis `c_B−c_A` → chord `P_B−P_A`, via `_quat_align`) + the
  `translation` that makes the junction-pivot transform equal `T(p)=R(p−center)+M`
  (`center=(c_A+c_B)/2`, `M=(P_A+P_B)/2`). `_cv_create_bound_binding` zeros driver
  rotation+translation, then stores the placement; `revert_bind_topology` zeros BOTH on
  unbind. Standalone single-domain driver (no root) → 422 → `None` → one-sided fallback.
  The co-moving driven tip rides via `_overhang_binding_partner_refs`; the whole duplex
  transforms rigidly. Display/geometry overlay only (topology untouched).
  - **Two bugs fixed vs. the first (translate-only) pass** (user-reported): (1) the
    overhang-helix **AXIS line** stayed at the old lattice spot — `_apply_ovhg_rotations_to_axes`
    applied `rotation` to axis samples but not the translation; added it in Layer-1 +
    ovhg_axes + fallback. KEY subtlety: that fn reads the junction pivot from the FINAL
    geometry (already transformed); rotation leaves the junction fixed but TRANSLATION
    shifts it, so it must **de-apply the translation** (`pivot_arr −= trans`) to recover
    the pre-transform pivot the base axis samples use (else double-count). (2) the duplex
    didn't ROTATE to minimize both bonds — apply now stores the aligning `R` (above).
    After the fix every overhang bead sits exactly 1 nm (radius) from its axis segment.
  - **Interim relax note:** apply now does the ORIENTATION the swing-relax used to do, so
    for same-body / small-gap cases the bond is already minimal → the (unchanged)
    `relax_direct_binding` is a valid no-op, and a single-revolute joint can't fully close
    a large centered gap. Tests updated accordingly (large gaps for separate-cluster
    relax; `require_reduced=False` + already-closed assert for same-body). This confirms
    the PREREQUISITE: **`relax_direct_binding` still needs the linker-bridge rewrite** —
    move CLUSTER joint(s) to bring the anchors to the duplex span so both bonds vanish
    symmetrically (see `relax_linker` summary). Tests:
    `test_direct_connection_unified.py` (`_seats_duplex_on_midpoint_symmetric_and_aligned`,
    `_moves_the_overhang_helix_axis_with_the_duplex`, `_unbind_zeroes_driver_midpoint_placement`).
  **NOT hand-driven in app** — recommend applying an end-to-root connection on
  `2x2_OH_test.nadoc` and confirming the duplex + its axis line sit centered/oriented
  between the two overhang roots with both connector bonds symmetric.
- **Direct RELAX rewritten to the linker-bridge method + DUPLEX-ONLY clash spin** (2026-07-01,
  user: "copy the dsDNA linker bridge relaxation method" + "rotation of overhang duplex only
  after arc minimization"). `direct_relax.relax_direct_binding` no longer swings the overhang
  about its root; three steps:
  1. **Arc minimization (cluster kinematics).** Anchors = the two embedded-staple root beads
     `P_A`,`P_B`. Rotate the connecting joint (`linker_relax._optimize_chord_angle`, 1-DOF
     grid+all-minima+smallest-|θ|; N-DOF Powell) — or, no joint, rigid-translate the driven
     cluster — to bring `|P_A−P_B|` → `span + n_bonds·target_nm`. Same rigid body ⇒ no motion.
     The joint rotates about ITS OWN axis (expected), NOT the overhang axis.
  2. **Re-seat** the duplex at the new oriented midpoint (`duplex_midpoint_placement` → driver
     `OverhangSpec.rotation`+`translation`), so both bonds land at `target_nm`.
  3. **Clash spin of the DUPLEX ONLY** (the correction after the reverted attempt that spun the
     whole cluster): rotate the duplex (driver overhang + driven tip, via the driver's
     `OverhangSpec.rotation`) about the root→root axis to the least-clashing angle
     (`_min_clash_rotation`, filters moving beads by `overhang_id ∈ {driver,driven}`, cKDTree
     contact count, tie→smallest|θ|). The clusters are NOT touched by this step. KEY GEOMETRY:
     after re-seat the duplex's two connecting beads are collinear on the root→root axis, so
     any spin preserves both bonds; the paired region (~1 helix diameter off-axis) swings clear.
     Compose it onto the placement about the geometry pipeline's UN-SEATED junction pivot `p0u`:
     `q_final = q_clash⊗q_seat`, `t_final = R_clash·(p0u+t_seat−P_A)+P_A−p0u` (the pivot-aware
     formula — the naive `R_clash·t_seat` shifted the bonds because `p0u` is OFF-axis).
  - **Two-sided target** (faithful bridge copy): opens an OVER-COMPRESSED bond back to natural
    0.67 — supersedes the old one-sided "don't back off" floor (LESSONS E7). Idempotent in the
    FINAL pose (re-seat zeros+re-derives the same absolute placement; `clash_spin_deg` reports
    the same angle each call but the result is stable).
  - **1-DOF reachability**: a single revolute joint can't always reach `span+1.34` for a large
    gap (partial close, both bonds still symmetric).
  - `info["mode"]` ∈ `same_body`/`joints`/`translate`; `swing_*` fields GONE. Tests:
    `test_duplex_relax.py` (idempotent / opens-over-compressed / closes-via-cluster-only),
    `test_direct_connection_unified.py` (modes), `test_duplex_automation.py` (headless
    idempotent), `test_headless_build.py` + `test_automation_harness.py` oracles.
  **NOT hand-driven in app** — confirm on `2x2_OH_test.nadoc` that Relax closes both bonds and
  ONLY the duplex reorients (the parts/clusters don't spin about the overhang axis).
6. Demote sub-domains to overlay; retire `OverhangBinding` after migration proven.

## Model shape (Phase 0)
`DuplexEnd{ overhang_id, start_bp, end_bp }` (inclusive; order = 5'→3').
`Duplex{ id, name, created_at, left, right, driver='left', bound=False,
binding_mode='duplex', allow_n_wildcard=True, target_joint_id?, locked_angle_deg?,
connection_type? }`. Equal-length both ends. Design invariant: no bp pairs twice
on one overhang.

## Migration (Phase 0, not yet auto-run)
`core/duplex.synthesize_duplexes_from_bindings(design)` → each legacy
`OverhangBinding(sd_a, sd_b)` → `Duplex` with each end's bp from the sub-domain
offset via the backing domain (`bp = d.start_bp + offset*sign(end-start)`), length
= min(sd_a.len, sd_b.len), driver from `binding.driver_oh_id`.

## Legacy overlay removed (2026-07-01)
The dashed 3D **overhang-binding-line** overlay (`scene/overhang_binding_lines.js` +
right-click `ui/overhang_binding_menu.js` Toggle-Bind/Delete) — the old per-`OverhangBinding`
connector (green=bound / amber=pre-bind) — was **deleted outright** (user request). It predated
the duplex render + duplex cluster and drew stale-endpoint lines into empty space once a duplex
was applied (the first-bead endpoint no longer matched the relocated overhang). Both modules +
`overhang_binding_menu.test.js` removed; all main.js wiring (subscribers + capture-phase
contextmenu) gone; 1852 frontend green + boot-clean e2e. Toggle/delete of a raw binding now lives
only in the Overhang Connections panel + the duplex cluster. `design.overhang_bindings` DATA is
untouched (still drives duplex derivation / `prior_driven_topology`).

## Related
[[overhang-connections-panel]] (CT picker + pairingSegments display) ·
[[overhang_binding_extensions]] (old OverhangBinding cluster-pose) ·
[[bond_relax]] · [[protein_attachment]] (Attachment precedent) ·
[[overhang_sequence_display]] (assembleOverhangSequence / overhangDomainLength).

## Next-session handoff
**Phases 0 + 1 + 2 DONE + green.** Backend graph + CRUD + classifier + oracle;
frontend pure mirror + client fns + connections-panel preview reads the register.
Everything is test-proven but the graph is EMPTY at runtime — no producer yet.

**Phase 3 DONE + VISIBLY VALIDATED (Playwright).** Both steps shipped:
- step (a) migration-on-load (`_derive_duplexes_if_empty`).
- step (b) PRODUCER + slide-robustness:
  * **Producer** `POST /design/duplexes/connect` (`connect_register`: mechanical
    attach-end register reusing the migration's polarity, `length = min`, no resize,
    longest-drives) + `POST /design/duplexes/sync-from-bindings`. Client
    `connectDuplex`/`syncDuplexesFromBindings`; connections panel calls
    `_ensureDuplexForPair()` after a direct Connect/Apply → duplex appears live.
  * **cadnano-drag robustness** ([crud.py](backend/api/crud.py) `_build_domain_shift`
    / `_build_strand_end_resize`): a MOVE shifts duplex ends with the domain
    (`shift_duplex_ends` — register preserved, Q1); a resize that pushes a register
    out of range drops it (`drop_invalid_duplexes`) instead of breaking. Full
    applied-shared-helix slide is Phase 4.
  * **Sidebar generalization**: Overhangs sidebar rows now render a duplex coverage
    line ([overhang_sequences_panel.js](frontend/src/ui/overhang_sequences_panel.js)).
Tests: backend 3420 passed (test_duplex_crud connect/sync +3, test_duplex_model
reconcile +2); frontend 1832; Playwright `duplex_pairing_display.spec.js` asserts
paired-green + toehold-grey in BOTH the connections panel AND the sidebar.

**Phase 4a — driver TOGGLE (Q4) — DONE + VISIBLY VALIDATED 2026-06-30.** A driver
control in the connections panel ([overhang_connections_panel.js](frontend/src/ui/overhang_connections_panel.js)
`_renderDriverToggle`): two buttons (one per overhang), the active driver
highlighted, clicking → `patchDuplex(id,{driver})`. The driver side is marked ▶ in
BOTH the connections-panel preview and the Overhangs sidebar coverage line
([overhang_sequences_panel.js](frontend/src/ui/overhang_sequences_panel.js)).
`longest_driver` is the create-time default (Q4). Tests:
`overhang_connections_panel.driver.test.js` (+2); Playwright spec now flips the
driver and asserts it persists + ▶ present. Frontend 1834. NO backend change
(uses the existing `patchDuplex`).

**Phase 4 geometry decisions (user, 2026-06-30):** (1) relocate the ENTIRE driven
domain (like the current binding path); (2) v1 leaves toehold/flanks at LATTICE
positions — right-click "set flexible" is a v2 option if substantial; (3) v1 uses
ONE combined solve for multivalency; (4) YES propagate the duplex driver to the
linked binding + use the existing proven relax.

**Phase 4b step #4 — driver→binding propagation — DONE 2026-06-30.**
`routes_duplex._propagate_driver_to_binding`: `PATCH /design/duplexes/{id}` with a
`driver` change writes the linked `OverhangBinding.driver_oh_id`/`driven_oh_id`
(matched by overhang pair), which `relax_overhang_binding` already reads
([crud.py:7500](backend/api/crud.py)) — so the existing relax honors the user's
choice on the next apply/relax. NO geometry moved here. Test
`test_patch_driver_propagates_to_linked_binding`. `just test` 3421.
KEY CONSTRAINT found: `relax_direct_binding` REQUIRES the driven tip already
relocated onto the DRIVER helix ([direct_relax.py:76] → 422 otherwise). So FLIPPING
an already-bound driver can't just re-relax — it needs revert (`revert_bind_topology`)
+ re-apply (`compute_bind_topology(driver_side=…)` + `apply_bind_topology`) + relax.
That live re-place is part of #1–#3 below.

**Phase 4b #4 + #1/#3 (equal-length case) — DONE + VERIFIED on the real fixture
2026-06-30.** Flipping the duplex driver now RE-PLACES geometry: `patch_duplex`
(driver change) → `_propagate_driver_to_binding` (#4) → `crud.reapply_binding_driver`
= revert (`revert_bind_topology`) + re-bind (`compute_bind_topology(driver_side)` +
`apply_bind_topology`) with the new driver, reusing the PROVEN primitives — so the
ENTIRE driven domain relocates onto the new driver's helix (#1) and the existing
`relax_direct_binding` is the single solve (#3). Best-effort (keeps the field edit
if relocation can't run). Verified: [tests/test_duplex_geometry.py](tests/test_duplex_geometry.py)
loads `workspace/playwright_tests/2x2_OH_test.nadoc` (copy of the user's fixture),
binds the two 10-mer overhangs, flips the driver, and asserts the shared duplex
helix moves h_XY_2_0 → h_XY_3_0. `just test`.

**Phase 4b binding-LESS / DIFFERENT-length relocation — DONE + VERIFIED 2026-06-30.**
(User report: "driven overhang not relocated after connecting different-length
overhangs" — a regression from the length-preserve skip.) The DUPLEX now drives its
own relocation when no equal-length binding backs it:
- `compute_bind_topology` gained `target_start_override`/`target_end_override`
  ([binding_relax.py](backend/core/binding_relax.py)) — relocate the driven's WHOLE
  domain onto only the driver's PAIRED-WINDOW bp range (not the driver's full
  domain), so a short driven isn't stretched to a long driver.
- `Duplex.prior_driven_topology` (new field) stores the snapshot for revert.
- `core/duplex.relocate_duplex` / `revert_duplex_relocation` wrap the proven
  `compute_bind_topology`/`apply_bind_topology`/`revert_bind_topology` via a
  transient binding carrier; target range = the driver-side duplex register (correct
  polarity, no reasoning). `POST /design/duplexes/connect` relocates when the pair
  has NO binding (equal-length still handled by the binding → skip). Toehold stays
  at lattice positions (#2). Verified: [tests/test_duplex_relocate.py](tests/test_duplex_relocate.py)
  — a 10 bp driven relocates onto a 24 bp driver's helix keeping its 10 bp length;
  driver untouched; `prior_driven_topology` recorded. `just test`.

**Validation + automation updated (2026-06-30, before Phase 5):**
- `validate_design` ([validator.py](backend/core/validator.py)) now flags a duplex
  whose register has ZERO complementary bases (real mismatches, not unsequenced N)
  — the Q2 "applied but sequences don't pair" soft warning; partial mismatches OK.
- Headless `hb.connect_duplex` ([headless_build.py](backend/api/headless_build.py))
  wraps `POST /design/duplexes/connect`; oracle `assert_duplex_relocated`
  ([automation_harness.py](tests/automation_harness.py)) pins relocated-but-NOT-
  stretched + round-trip. Ledger rows added (`design_automation_log.md` catalog +
  `design_automation_backlog.md` duplex-coverage note). Tests:
  [test_duplex_automation.py](tests/test_duplex_automation.py) (validator flag +
  headless+oracle).

**Phase 4b remaining (follow-ups):** (1) DRIVER FLIP for a binding-less relocated
duplex isn't re-placed yet (patch_duplex only re-places binding-backed via
`reapply_binding_driver`); flipping to make the SHORTER the driver is also
ill-defined (would stretch the longer down) — likely constrain the toggle to
longest-drives for different lengths. (2) relax (settle the stretched bond) for the
binding-less duplex. Then Phase 5 (attachments) / Phase 6 (retire OverhangBinding).

Then Phase 5 attachments (fluorophore), Phase 6 retire OverhangBinding. WC gate
still ON (revisit to SAVE mismatched registers). Playwright fixture
`workspace/playwright_tests/duplex_demo.nadoc` (regen via
`scripts/gen_duplex_demo_fixture.py`).
