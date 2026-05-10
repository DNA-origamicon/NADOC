# Audit + Refactor 07 — Multi-domain & multi-jointed overhangs

You are a **fresh audit + refactor session**. NADOC currently models every overhang as a single domain on a single dedicated (or shared inline) helix, with one optional ball-joint rotation around one pivot. The user wants to expand into **multi-domain overhangs** — overhangs whose strand path crosses multiple helices (small structures hanging off the main bundle) — and eventually **multi-jointed overhangs** where each segment can articulate around its own pivot.

Recent precedent: bug-fix session 06 (see `refactor_prompts/06-debug-overhang-sequence-resize-and-rotation.md` and the LESSONS.md entries E4 + E5 it added) exposed how brittle the single-domain assumption already is. Bug 1 came from `patch_overhang` assuming the junction is at the helix's low bp end; Bug 2 came from `apply_overhang_rotation_if_needed` masking by domain direction so the Watson-Crick complement on the same helix didn't follow the rotation. Both fixes were point patches inside the single-domain model. Multi-domain OHs will violate the same assumptions in more places — the goal of this prompt is to find them all *before* expanding the data model.

This is **NOT a bug-fix** prompt. It is an **audit-then-stage** prompt: in this session, deliver an inventory + a small set of low-risk preparatory refactors that make multi-domain expansion safe. Do NOT change the data model in this session.

## ⚠ DNA-topology rule (CRITICAL)

Per `CLAUDE.md`: any confusion about strand polarity, helix orientation, domain traversal, or scaffold path → **ask the user first, implement nothing**. Reasoning about geometry/topology/directionality alone consistently produces wrong results in this codebase.

Per `feedback_crossover_no_reasoning.md`: never reason geometrically about crossover placement; only apply mechanical rules.

Per `feedback_overhang_definition.md`: an overhang is a portion of a strand embedded in a scaffolded structure that extends outward — it begins on a scaffolded helix and the free end hangs off into the overhang helix. The "free tip" terminology in the codebase refers to the strand-terminal end; the "root" or "junction" end is where the OH connects (via crossover) back to the parent strand.

Per `feedback_phase_constants_locked.md`: `_PHASE_*` constants in `lattice.py` require explicit user approval to change.

## Scope clarifications — ASK before assuming

The user said "multi-jointed, multi-domain overhangs" but the structural details are open. Before any model changes, get explicit clarification on:

1. **What "multi-domain" means concretely.** Candidate interpretations:
   - (a) **Branched OH** — a single OH strand with domains on >1 dedicated helix (e.g. a 2-helix overhang structure: one helix runs perpendicular to the bundle, the other extends from its tip). One scaffold-side root, one free tip, one or more crossovers internal to the OH structure.
   - (b) **Chained OH** — multiple OverhangSpec records linked into a sequence (e.g. one OH sticks out, then a second OH is anchored to the first OH's tip rather than to the bundle). Each OH has its own `helix_id` and `pivot`.
   - (c) **Multi-helix overhang bundle** — the OH is itself a small DNA-origami bundle (multiple parallel helices with internal crossovers), connected to the parent at one or more crossovers.
   - The three differ in how rotation, linker attachment, and rendering must compose.
2. **What "multi-jointed" means.**
   - One ball-joint per OH segment (each domain → its own pivot at the junction with the previous segment)?
   - Or a single OH with multiple internal joints along a chain of helices?
   - Joint angle limits per joint (already supported on `ClusterJoint`)?
3. **Use cases to design for.** A toehold + a separate aptamer on the same staple? A small Y-junction off the bundle? Two-step linker arms? Get one or two concrete user scenarios in mind before you refactor.

Send these questions back as a single short clarification message before doing any backend code changes. The reading + audit work below can proceed without the answers.

## Pre-read (in order)

1. `CLAUDE.md` — Three-Layer Law, DNA-topology rule, tone, communication mode (terse, code-ELI5)
2. `memory/REFERENCE_DNA_TOPOLOGY.md` — strand polarity, scaffold-path conventions
3. `memory/feedback_overhang_definition.md`
4. `memory/feedback_crossover_no_reasoning.md`
5. `memory/feedback_interrupt_before_doubting_user.md`
6. `memory/project_overhang_connections.md` — ss + ds linkers, bridge nucs, **8 critical gotchas**, relax algorithm
7. `memory/project_overhang_lookup_infra.md` — 4-stage pipeline, `_ovhgDomainMap`, `_ovhgRootMap`
8. `memory/project_overhang_generation.md`
9. `memory/project_mate_connectors.md` — `getInstanceBluntEnds`, cache invalidation, duplicate-connector
10. `memory/LESSONS.md` — focus on **E4** (OH rotation didn't reach linker complement) and **E5** (patch_overhang extrude resize). Both are direct prefigurings of multi-domain failure modes.
11. `refactor_prompts/06-debug-overhang-sequence-resize-and-rotation.md` — the prior session's prompt + diff
12. Recent `git log` (last ~20 commits) for currency

## Audit scope (stage 1 — read-only)

Inventory every place that assumes the single-domain-OH model. For each, note: **file:line · which assumption is being made · what would break with multi-domain · suggested fix shape (don't implement)**.

The known hot spots — start here, then walk outward via grep:

### Backend
- `backend/core/models.py` — `OverhangSpec` (single `helix_id`, single `pivot`, single `rotation`).
- `backend/core/lattice.py` — `make_overhang_extrude` (creates exactly one new helix + one new domain), `_reconcile_inline_overhangs`, `autodetect_overhangs`, `_make_complement_domain`, `_make_virtual_linker_helix`, `generate_linker_topology`, `assign_overhang_connection_names`, `_find_overhang_domain`.
- `backend/api/crud.py`:
  - `patch_overhang` — extrude branch now uses `design.crossovers` to find the junction (post-Bug-06). This still assumes exactly one junction crossover per overhang helix.
  - `_emit_bridge_nucs` and `_anchor_for` — assume one OH domain on one helix.
  - `overhang_extrude` POST handler — payload shape (single helix_id + bp_index + neighbor cell).
  - `delete_overhang` (and `DELETE /design/overhangs/batch`) — domain cleanup.
  - `_resplice_overhang_in_strand` — sequence patching across strand domains.
  - `_geometry_for_helices` — per-helix loop calls `apply_overhang_rotation_if_needed` once per helix; multi-helix OHs need rotation composition across helices.
- `backend/core/deformation.py`:
  - `apply_overhang_rotation_if_needed` (single helix, single OH domain, single complement-on-same-helix rule — Bug 06 fix).
  - `_apply_ovhg_rot_to_samples` and `_apply_ovhg_rotations_to_axes`.
  - `apply_overhang_rotation` flow inside `effective_helix_for_geometry`.
- `backend/core/linker_relax.py`:
  - `_overhang_helix_id` (returns one helix), `_overhang_owning_cluster_id`, `_oh_attach_nuc`, `_anchor_pos_and_normal`.
  - `bridge_axis_geometry` — depends on a single anchor point per side.
- `backend/api/assembly.py`:
  - `get_instance_geometry` / `get_assembly_geometry` paths that call `_apply_ovhg_rotations_to_axes`.
  - `getInstanceBluntEnds` (frontend) and its backend feed — already known fragile per `project_mate_connectors.md`.
- `backend/core/validator.py` — overhang-related rules.
- `backend/core/atomistic.py` and `cg_to_atomistic.py` — atomistic placement of OH nucs.
- `backend/core/scadnano.py`, `backend/core/cadnano.py` — import/export round-trip.

### Frontend
- `frontend/src/main.js` — `_ovhgSpecMap`, `_ovhgDomainMap`, `_ovhgJunctionMap`, `_ovhgRootMap` (4-stage lookup pipeline assumes one domain per OH; `findIndex(d => d.overhang_id === spec.id)` returns one).
- `frontend/src/scene/overhang_link_arcs.js` — `_linkerAttachAnchor`, single helix/bp lookup.
- `frontend/src/scene/overhang_locations.js` — gizmo placement.
- `frontend/src/scene/selection_manager.js` — OH ctrl+click and color/Linker context menus, multi-OH selection cap of 2.
- `frontend/src/ui/overhangs_manager_popup.js` — UI assumes per-OH list with one helix/strand each.
- `frontend/src/scene/assembly_renderer.js` — `getInstanceBluntEnds`, `_isFree`, `_axesArrayToMap.ovhgAxes`.

### Tests
- `tests/test_overhang_geometry.py`, `test_overhang_connections.py`, `test_overhang_sequence_resize.py`, `test_overhang_linker_rotation.py` — each fixture is a single-domain seed. Multi-domain OHs need new fixtures.

## Deliverables (this session)

### A — Audit document

Write `refactor_prompts/07-multi-domain-overhang-audit-FINDINGS.md` with sections:

1. **Single-domain assumption inventory** — table: file:line · assumption · break mode · fix shape (model change | per-domain loop | per-helix loop | rendering composition | other).
2. **Already-correct-by-construction places** — list places that *don't* need to change because they already iterate strand domains generically. Surprising negatives are valuable.
3. **Cross-cutting risks** — flag the known fragile areas the user has called out:
   - `make_bundle_continuation` (474 LOC, deformation-sensitive — flagged in LESSONS.md, do NOT touch).
   - `_PHASE_*` constants — locked.
   - `linker_relax.py` (recent commits: 5b432da, 7d8e093 — user iterating; `bridge_axis_geometry` is single-source-of-truth).
   - `_BRIDGE_PHASE_OFFSET` synchronization across `_bridge_boundary_radials` and `_emit_bridge_nucs`.
   - Three anchor implementations that must agree: `_anchor_pos_and_normal`, `_anchor_for`, `_linkerAttachAnchor`.
4. **Open questions for the user** — concrete topology/polarity questions that arose during the walk. Per `feedback_interrupt_before_doubting_user.md` and the topology rule, ask before guessing.
5. **Proposed model changes** (3 alternatives ranked) — DO NOT implement; this section feeds the next session.
   - Alt A — minimal: add a `domain_helix_ids: list[str]` (or similar) to `OverhangSpec`; keep one OH per spec.
   - Alt B — chained: introduce `OverhangChain` containing multiple specs; keep specs simple.
   - Alt C — bundle-as-OH: use the existing cluster + crossover machinery to model an OH structure as a small auto-clustered sub-bundle with a special tag.
   For each: data model delta, impact on `OverhangConnection` (ss/ds linker + relax), impact on rendering, impact on persistence/round-trip.

### B — Low-risk preparatory refactors (this session)

Implement ONLY refactors that are pure code-locality / naming improvements and don't change behaviour or schema. Examples (verify each survives `just test` with no failure-set delta vs. baseline):

- Hoist single-purpose junction-bp lookup into a helper: `_overhang_junction_bp(design, spec_id)` reading from `design.crossovers`. Used today in `patch_overhang`, `apply_overhang_rotation_if_needed`'s pivot derivation, and `_anchor_for`. Once it's named, future multi-domain code can extend it to return a list.
- Hoist Watson-Crick partner-domain enumeration into a helper: `_complement_domains_for(design, ovhg, helix)` — currently inlined in `apply_overhang_rotation_if_needed` (Bug 06 fix). A named helper makes it trivial to call from atomistic / linker / assembly paths if those turn out to need the same fix.
- Add domain-iteration helpers: `_overhang_domains(design, spec_id)` returning every domain whose `overhang_id == spec_id`. Today there's exactly one; tomorrow there may be many. Call sites that today use `next(d for d in ...)` should use the helper so the multi-domain switch is one diff per site.
- Tighten naming: places that say `the OH domain` (singular) in code comments should say `the OH-tagged domain on this helix` so the reader doesn't internalise the singular assumption.

For each refactor: confirm `just test` passes with the same failure set as the baseline you captured at session start. Do **not** add new behaviour. Do **not** change `OverhangSpec` fields, `make_overhang_extrude` signature, or any API route.

### C — Frontend (read-only this session)

The 4-stage lookup map pipeline in `main.js` (`_ovhgSpecMap` / `_ovhgDomainMap` / `_ovhgJunctionMap` / `_ovhgRootMap`) is the central place a multi-domain switch will land on the frontend. Audit it. Do NOT modify. Add a section to FINDINGS.md describing the exact map-key mutations needed and which call sites would migrate.

## Stop conditions (when to ask the user)

- The audit reveals a model-shape choice (Alt A vs B vs C) that depends on a use case the user hasn't named — STOP, summarise the alternatives, ask.
- Any refactor would touch `_PHASE_*`, `make_bundle_continuation`, or the locked anchor-implementation triplet in a way the user might object to.
- The audit finds that an existing correctness issue (not just a multi-domain extension) has slipped past the bug-06 fixes — STOP, write up, ask whether to fold into THIS session or queue as new bug-debug.

## Verification plan

### Pre-state (capture at session start)
```bash
git status
just lint > /tmp/07_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/07_lint_pre.txt
just test > /tmp/07_test_pre1.txt 2>&1
just test > /tmp/07_test_pre2.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/07_test_pre1.txt | sort > /tmp/07_baseline1.txt
grep -E '^FAILED|^ERROR' /tmp/07_test_pre2.txt | sort > /tmp/07_baseline2.txt
comm -12 /tmp/07_baseline1.txt /tmp/07_baseline2.txt > /tmp/07_stable_failures.txt
```

### Post-state
```bash
just lint > /tmp/07_lint_post.txt 2>&1 ; echo "EXIT $?" >> /tmp/07_lint_post.txt
just test > /tmp/07_test_post.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/07_test_post.txt | sort > /tmp/07_post_failures.txt
diff /tmp/07_stable_failures.txt /tmp/07_post_failures.txt   # MUST be empty
```

No new failures. Lint count Δ ≤ 0. The new helpers are exercised by the existing test suite (no behaviour change, so no new tests should be needed for the helpers themselves — but if you find an untested codepath while extracting, file a NEW test and note it).

## Output format (final message)

```markdown
## Audit 07 — Multi-domain overhang preparation — <DELIVERED|PARTIAL>

### Scope clarifications still pending
<bullet list of the questions you sent to the user up-front; mark answered/unanswered>

### Single-domain assumption inventory
<count> sites identified. Top 10 by risk:
- <file:line> — <assumption> — <break mode> — <fix shape>
- ...

### Already-correct-by-construction
<bullet list of pleasant surprises>

### Cross-cutting risks
<bullet list — flag the locked / fragile areas you steered around>

### Proposed model alternatives
- Alt A (<one-line>): <one-paragraph delta>
- Alt B (<one-line>): <one-paragraph delta>
- Alt C (<one-line>): <one-paragraph delta>
- Recommended: <which one>, <one-sentence why>

### Preparatory refactors landed this session
- <helper> in <file:line> — <one-sentence why>
- ...

### Verification
- pre lint: X; post lint: Y (Δ ≤ 0)
- pre tests: A pass / B fail / C err; post: A' pass / B' fail / C' err
- failure-set diff: empty / explained

### Open questions
<the bigger ones that block the next session>
```

## Do NOT (this session)

- Skip pre-read.
- Reason geometrically about strand polarity / crossover placement.
- Touch `_PHASE_*` constants.
- Touch `make_bundle_continuation`.
- Touch `linker_relax.py`'s `bridge_axis_geometry`, `_optimize_angle`, or relax loss.
- Modify `OverhangSpec` shape, add fields, or change API routes.
- Add user-facing features (UI, gizmos, new endpoints).
- Implement multi-domain rendering.
- Commit. The user reviews and decides.
- Resume Pass 6 refactor candidates queued in `REFACTOR_AUDIT.md` until this audit lands and the user picks a model alternative.

## Prompt status

Pass 6 candidates remain paused. Bug 06 fixes are merged into the working tree (uncommitted at session 06 close, awaiting user commit). Multi-domain OH expansion is the next big arc, and the user wants to do it carefully — hence audit-first.
