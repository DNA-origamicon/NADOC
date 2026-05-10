# Bug Investigation 06 — Overhang sequence-regeneration resizes wrong end + rotation lost in linker generation

You are a **fresh debugging session**. Two distinct bugs surfaced during user validation of Finding #15 (Pass 5's overhang-endpoint extract). Both are likely **pre-existing**: that refactor was a verbatim move of frontend HTTP-wrapper code with no semantic change, so it cannot have introduced these bugs — it only exposed them by giving the user a reason to exercise the panel.

Refactor work (Pass 6 candidates) is paused until these are resolved.

## ⚠ DNA-topology rule (CRITICAL)

Per `CLAUDE.md`: any confusion about strand polarity, helix orientation, domain traversal, or scaffold path → **ask the user first, implement nothing**. Reasoning about geometry/topology/directionality alone consistently produces wrong results in this codebase.

Also per `feedback_crossover_no_reasoning.md`: never reason geometrically about crossover placement; only apply mechanical rules. The Bug 1 symptom (an extra crossover appearing on a strand end) is exactly the failure mode this rule guards against.

Also per `feedback_interrupt_before_doubting_user.md`: ask first; do not preemptively "fix" the user's observation.

## Pre-read (in order — do not skip)

1. `CLAUDE.md` — Three-Layer Law, DNA-topology rule, tone
2. `memory/REFERENCE_DNA_TOPOLOGY.md` — strand polarity, scaffold-path conventions
3. `memory/feedback_overhang_definition.md` — what an overhang IS (strand embedded in scaffold, free tip on overhang helix)
4. `memory/feedback_crossover_no_reasoning.md`
5. `memory/feedback_interrupt_before_doubting_user.md`
6. `memory/project_overhang_connections.md` — ss + ds linkers, bridge nucs, relax algorithm
7. `memory/project_overhang_lookup_infra.md` — 4-stage pipeline, debugging entry point
8. `memory/project_overhang_generation.md` — Johnson et al. 5-mer, Gen button (merged)
9. `memory/project_mate_connectors.md` — known cache-invalidation + duplicate-connector issues (highly relevant to Bug 1)
10. `memory/LESSONS.md` — search for "overhang", "rotation", "regenerate", "extra crossover", "double crossover"
11. `REFACTOR_AUDIT.md` Findings #15 — the recent refactor; confirm it was verbatim (it was)

## Bug 1 — Overhang sequence regeneration extends wrong end

### Reproduction (from user validation 2026-05-09)

1. `just dev` + `just frontend`. Load any `.nadoc` design with at least one staple end available.
2. Create a 5'/3' overhang on any helix end with **no sequence** (length-only, e.g. 8 bp).
3. Modify the sequence to be **longer than the initial length** (e.g. 12 bp). Either via:
   - The Overhangs panel sequence input
   - `PATCH /design/overhang/{id}` with `{ sequence: '<12-mer>' }`
   - Or `POST /design/overhang/{id}/generate-random` (this generates a sequence; check whether it can produce one longer than initial length)
4. Observe: the resize affects the **wrong end** of the strand — specifically the **crossover-connecting end** (the "root" of the overhang, where it joins the scaffold/staple via a crossover). The free tip end stays at its original position.
5. Result: the strand end now has **two crossover connections** because the resize ate into the adjacent strand on the other side of the original crossover.

User attached a screenshot of a yellow strand with two crossover connections at one end after this sequence — visual confirmation that the wrong end grew.

### Hypothesis space (verify before implementing)

A. **Endpoint mismatch in `extend_or_truncate_strand_end`-style logic.** Overhang strands have a "tip" end (free, away from scaffold) and a "root" end (anchored, with crossover). When the sequence length changes, the resize must always operate on the **tip end**. If the code resizes by `domain[-1].end_bp += delta`, it might be growing the root direction depending on strand orientation (5'→3' vs 3'→5').

B. **`is_five_prime` polarity confusion.** `OverhangSpec` records whether the overhang extrudes from a 5' or 3' free end. Resize math may use this flag inconsistently — e.g. picking the right boundary in one place and the wrong one in another.

C. **Sequence-set vs length-set divergence.** PATCH-with-sequence may take a different code path from PATCH-with-length, and only one path correctly resizes the tip end.

D. **Cache invalidation.** `project_mate_connectors.md` documents known cache-invalidation issues with mate connectors. Possible the resize updates the strand correctly but leaves a stale crossover/half-crossover pointer.

### Investigation plan

1. **Reproduce in a Python test first** (no UI needed). Build a `Design` with one helix + scaffold + one staple, extrude an overhang with `length_bp=8` and `sequence=None`. Assert pre-state: scaffold + staple + overhang strand-tip bp position. Then call the regenerate-sequence path with a 12-mer. Assert post-state: tip moved by +4 bp; root unchanged. If the test fails (tip didn't move OR root moved), Bug 1 is reproduced at the topology layer.
2. If the test does NOT fail, the bug is in the API layer or frontend — re-run via `httpx` against `just dev` with the same sequence.
3. Identify the offending function/route. Likely candidates:
   - `backend/api/crud.py` route handler for `PATCH /design/overhang/{id}` and `POST /design/overhang/{id}/generate-random`
   - `backend/core/overhang_generator.py` (sequence generation logic)
   - `backend/core/lattice.py::shift_domains` or a sister function (domain bp boundary math)
4. **Before implementing a fix**, write up: (a) which end was resized in the bug case, (b) which end *should* have been resized, (c) the exact line where the wrong end is picked. Send this back as a question if there's any ambiguity about which end is the tip in the user's setup.

### Add a regression test

`tests/test_overhang_sequence_resize.py` — covers both:
- length-only overhang → set sequence longer → tip moves, root fixed
- length-only overhang → set sequence shorter → tip retracts, root fixed
- Both 5'-extrude and 3'-extrude variants

## Bug 2 — Overhang rotation lost when generating linker

### Reproduction

1. Create two overhangs on opposing helices.
2. Rotate one of them (the rotation visibly works in the 3D view).
3. Trigger linker generation between the two overhangs (`createOverhangConnection`, possibly followed by `relaxLinker`).
4. Observe: the **overhang binding domain is positioned in the *pre-rotated* orientation** when the linker is rendered. The visual rotation persisted in the panel, but the linker math used the un-rotated overhang frame.
5. **No errors in DevTools console.**

### Hypothesis space

A. **`OverhangSpec.rotation` not read by linker math.** The rotation is a quaternion stored on `OverhangSpec` and applied in the 3D renderer (`overhang_locations.js` / `overhang_link_arcs.js`). The linker-generation backend (`backend/core/linker_relax.py` or whatever computes the binding-domain endpoints) may compute positions from `Helix.axis` + `OverhangSpec.helix_id` + `bp_index` without consulting `rotation`.

B. **Frame composition order.** The rotation may be applied in the renderer as a post-multiply on the world-space overhang origin, but the linker geometry pipeline uses a different frame source (e.g. the helix local frame) where the rotation never gets composed.

C. **Stale cached frame.** If overhang positions are cached and the rotation update doesn't invalidate the cache, the linker reads stale pre-rotation positions.

D. **Frontend vs backend split.** The 3D renderer applies rotation locally (correct view), but the linker is computed by a backend route that doesn't know about rotation. Linker is server-authoritative; user's rotation is client-only display until persisted via `patchOverhangRotationsBatch` — possibly the bug is that linker generation happens before the rotation persists.

### Investigation plan

1. Reproduce: create two overhangs, rotate one, IMMEDIATELY (before any auto-save or panel close) trigger linker generation. Compare result vs: rotate one, wait for `patchOverhangRotationsBatch` to fire (check Network tab), then trigger linker. If the second case works, Bug 2 is a "rotation persisted late" race; if both fail, the linker pipeline genuinely doesn't read the rotation.
2. Backend reproduction: write a Python test that builds a Design with two overhangs, sets `OverhangSpec.rotation = <90° quat>` directly on one, then calls the linker generation function. Assert the binding-domain endpoint reflects the rotated frame.
3. Identify the offending function. Likely candidates:
   - `backend/core/linker_relax.py::relax_linker` or its helpers (`_anchor_position`, `_moving_anchor_at`, `_ds_target_length_nm` per Finding #17's possibly-dead list — confirm before assuming)
   - Wherever `OverhangConnection` endpoint coordinates are computed
   - `backend/core/geometry.py` if there's an overhang-frame helper
4. Cross-check `frontend/src/scene/overhang_link_arcs.js` to confirm whether the frontend renders linker arcs from server-returned coordinates (then the bug is server-side) or computes them locally (then it's frontend).

### Add a regression test

`tests/test_overhang_linker_rotation.py` — covers:
- Two overhangs, no rotation → linker endpoints match a reference position
- Same setup with one overhang rotated 90° → linker endpoint moves accordingly
- Round-trip: `Design.model_dump()` and reload preserves rotation, and a fresh linker computation uses it.

## Stop conditions (when to ask the user)

- Either bug requires editing **`backend/core/linker_relax.py`** in a way that touches the bridge-axis side or the chord-magnitude target — these are the exact areas mentioned in recent commits (`5b432da`, `7d8e093`). The user has been actively iterating on this file. ASK before changing.
- Either fix would require changing `_PHASE_*` constants — locked, ask user.
- Diagnosing requires reasoning about strand polarity at the bp level — STOP, write up the question, ask the user.
- The reproduction can't be made deterministic because of timing-related state changes — STOP, ask the user whether the bug is timing-dependent.
- You suspect the issue is in `make_bundle_continuation` (474 LOC, deformation-sensitive) — ASK before touching, as it's flagged in `memory/LESSONS.md` as a fragile area.

## Verification plan

### Pre-state
```bash
git status
just lint > /tmp/06_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/06_lint_pre.txt
just test > /tmp/06_test_pre1.txt 2>&1
just test > /tmp/06_test_pre2.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/06_test_pre1.txt | sort > /tmp/06_baseline1.txt
grep -E '^FAILED|^ERROR' /tmp/06_test_pre2.txt | sort > /tmp/06_baseline2.txt
comm -12 /tmp/06_baseline1.txt /tmp/06_baseline2.txt > /tmp/06_stable_failures.txt
```

### Reproduction tests (write FIRST, before any fix)

Each bug gets one *failing* test before the fix. Confirm the test fails for the right reason (asserts on the user's reported symptom — wrong end resized / rotation ignored). Once reproduced:
- Bug 1 test → fix → test passes
- Bug 2 test → fix → test passes

### Post-state
```bash
just lint > /tmp/06_lint_post.txt 2>&1 ; echo "EXIT $?" >> /tmp/06_lint_post.txt
just test > /tmp/06_test_post.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/06_test_post.txt | sort > /tmp/06_post_failures.txt
diff /tmp/06_stable_failures.txt /tmp/06_post_failures.txt   # MUST be empty (no NEW failures); the 2 new tests should be in the PASSING set, NOT in the failure set
```

Plus 2 new tests should now appear as passing — confirm via `just test 2>&1 | grep -E "test_overhang_sequence_resize|test_overhang_linker_rotation"`.

## Output format (final message)

```markdown
## Bug 06 — Overhang sequence-regen + rotation-lost — <FIXED|PARTIALLY-FIXED|UNRESOLVED>

### Pre-existing dirty state declaration
<git status output at session start>

### Bug 1 — sequence-regen extends wrong end
- **Reproduction confirmed in test**: `tests/test_overhang_sequence_resize.py::<test name>` — <pass|fail before fix>
- **Root cause**: <file:line>: <one-paragraph explanation>
- **Fix**: <description; cite file:line>
- **Three-Layer**: <which layer; flag any boundary issues>
- **Regression test**: <test name + what it covers>

### Bug 2 — rotation lost when generating linker
- **Reproduction confirmed**: <Python test | requires UI | timing-dependent>
- **Root cause**: <file:line>
- **Fix**: <description>
- **Regression test**: <test name>

### Verification
- pre lint: <X>; post lint: <Y> (Δ = <0 or fewer>)
- pre tests: <X pass / Y fail / Z err>; post: <X' pass / Y' fail / Z' err>
- new tests added: <count>, all passing
- failure set ⊆ stable_baseline ∪ flake: yes / no

### What was deliberately NOT changed
<bullet list — show you held the line on locked / fragile areas like `_PHASE_*`, `make_bundle_continuation`, `linker_relax.py` core algorithm if not the root cause, etc.>

### USER TODO (in-app verification)
1. `just frontend` and load a saved design.
2. Repro Bug 1 (length-only overhang → set longer sequence) — confirm tip end resizes, not root.
3. Repro Bug 2 (rotate overhang → generate linker) — confirm linker uses rotated frame.
4. Confirm no DevTools console errors.
5. Mark the bug entries in this report as USER VERIFIED if both pass.

### Open questions
<anything the prompt didn't anticipate; e.g. ambiguity about which end is "tip" in 5'-extrude vs 3'-extrude>
```

## Do NOT

- Skip the pre-read. The codebase has multiple memory files specifically about overhangs that have prior debugging context; reading them might short-circuit the investigation.
- Reason geometrically about strand polarity or crossover placement. Read the code and the rules; ask if anything's unclear.
- Edit `_PHASE_*` constants.
- Edit `make_bundle_continuation` or other deformation-flagged areas without asking.
- Resume Pass 6 refactor work until both bugs are FIXED + USER VERIFIED.
- Add new features. Only fix the two reported bugs. If you spot a third bug during investigation, document it in Open questions; don't fix it.
- Commit. The user will review and merge.

## Prompt status

Pass 6 refactor candidate seeds (queued in REFACTOR_AUDIT.md audit log: `05-D` manual triage, `06-A` PDB import tests, `06-C` `staple_routing.py` deletion, `05-A-v3` `relaxLinker` move, `06-D` `sequences.py` + `ws.py` test backfill) are **paused** until this bug pair is resolved. Reason: Bug 2's investigation may touch `linker_relax.py` (where `relaxLinker`'s deferred private deps live), which would change the shape of `05-A-v3`'s prompt. Better to land bugfixes first.
