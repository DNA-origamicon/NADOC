# Superseded final-session notes — supporting detail

[Topic head](../../plan_audit_ledger.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

- **A plan can be overtaken in every direction at once and still read as current.** Every one of
  `cadnano_overhaul`'s five phases resolved without it — shipped past scope (Phase 2), shipped
  under *different names* (Phase 3: `Part`/`?doc=`, never `Origami`/`?origami_id=`), shipped
  partially (Phase 4/5), or became **unbuildable** when a dependency was retired (the Phase 5 FEM
  heat-map). **Tell: check each phase against a different question — not "was it built?" but "did
  the problem it solves get solved another way, or stop existing?"** Its highest-rated architecture
  *risk* ("state.py singleton is the highest-risk backend change") had been quietly resolved by
  unrelated multi-document work.
- **The migration payload lives in the dev log, not the plan.** The four facts worth saving were
  all `[FIXED]`/`[PERF]` entries — root causes with their *why*, which is exactly the register a
  path-scoped rule omits. Two were latent data-loss traps (`_strip_feature_log_payloads` making the
  in-memory design incomplete; `_design`-reference cache keying). **Tell: when deleting a plan with
  a dev log, read the log's FIXED/PERF/GOTCHA entries as the migration list and re-verify each
  against source before writing it into the rule — three of the four had drifted anchors.**
- **Fourth pass running on "two mechanisms enforcing one rule"** (after unfold's `expanded_spacing`,
  strand-anim's hand-rolled contract, cluster scope's create-vs-render). Here: **two independent
  stale-data guards** — `_lastAppliedRev` drops stale *responses*, the `file-saved` broadcast
  suppresses a stale *file reload* — with the same user-visible symptom ("the nick reverts a second
  later") and no shared code. The rule documented one. Keep looking for this explicitly.
- ~~**A doc's own paired anchors are a cheap lie detector.**~~ **RETRACTED 2026-07-31** (`/audit-debt`
  pass 3, closing TD-03). The example was wrong: `paletteColor` **does** exist —
  `frontend/src/ui/spreadsheet.js:62`, called at `:142` inside `effectiveColor`, plus
  `spreadsheet.test.js:162` and a mention at `backend/api/routes_sequences.py:204`. The 07-30 probe
  searched `frontend/src/ui/strands_spreadsheet.js`, **a path that has never existed** — there are two
  same-named panels and the real one is `frontend/src/cadnano-editor/strands_spreadsheet.js` (which
  has `effectiveColor` at :72 but no `paletteColor`, hence the half-hit that looked like a lie).
  So the doc was telling the truth and the probe manufactured the finding.
  **The replacement lesson is stronger: a grep that returns nothing proves nothing until you have
  proved the path you grepped exists.** "Zero hits" and "wrong filename" produce identical output.
  Tell: before recording any STALE/never-existed verdict that rests on absence, run
  `rg --files -g '<basename>'` and cite it. Pairs are still worth grepping — just never let a
  one-of-two hit stand as evidence without confirming *where* you looked.

Carry into it (from the `assembly_part_context` pass):

- **A "deferred" item can have shipped under a path the doc never guessed.** The plan proposed
  `POST /assembly/instances/{id}/seek`; what exists is `…/instances/{id}/**features**/seek`. A grep
  for the doc's literal string returns nothing and reads as "not built." **Tell: for any proposed-
  but-unbuilt route/symbol, grep the *verb* and the *noun* separately (`seek`, `instances/`), not
  the proposed path — and check the doc's stated diagnosis independently, because the diagnosis
  can be right while the proposed fix is the thing that got replaced.**
- **Fifth pass on "two mechanisms enforcing one rule" — and this time one of them is unreachable.**
  Feature-log part-context (`_partPatchFn`) and the panel's own `_assemblyPartInstanceId` dropdown
  both implement "show this instance's feature log." The first is gated on `!assemblyActive` while
  its only trigger requires `assemblyActive` — a **contradiction, not a race**. Nothing fails; the
  code just never runs. **Tell: when you find duplicate mechanisms, immediately test each one's
  guard against its trigger condition. A gate that can't be satisfied is the cheapest dead-code
  proof there is, and no test will ever surface it.**
- **Authoring without playback is a shape to look for.** ~22 CRUD call sites let you build a
  part-mode animation; `playOpts` has no `_partMode` branch, so it can't be played. Half-features
  split along the read/write seam like this read as "complete" in any doc that lists what was built.
  **Tell: for any feature with a create path, find and grep the corresponding consume path.**
- **A bug fix can be quietly re-implemented by an unrelated perf rework.** Bug 1's `setVisible(on &&
  _mateMode)` gate still exists — on a *different group* — and the actual fix is now per-instance
  gating in `_applyActiveVisibility()`. The doc's sentence is false but the bug is still fixed.
  **Tell: verify the *behavior* the fix claims, not the mechanism, before recording it as stale.**

**One cross-cutting cleanup now worth doing as its own item, not per-pass:** `docs/triage/` is
**3 for 3 fiction** (animation, deformation, unfold passes). Twelve files built on phantom
`MAP_*.md` links and obsolete invariants, none auto-loaded, none cited by code. Proposal: delete
the directory or move it under `archive/` rather than audit it file by file. Logged in
`project_tech_debt`; **user call**.

**New-rule candidates, unchanged and still ranked** (metric in `project_tech_debt` → "Rule
coverage is 33% of production LOC" — don't re-run the sweep): `models-and-schema`
(`backend/core/models.py` 3,314 — the `Design` schema everything reads; `REFERENCE_MODELS.md`
covers it but is **not auto-loaded**); `assembly-render` (`assembly_renderer_shared.js` 3,940 +
`joint_renderer.js` 3,224 + `assembly_joint_renderer.js` 2,839 ≈ 10k LOC, and it holds 6 of the 7
callers of `buildHelixObjects`); `md-jobs`.

## Standing lessons (carry forward — compressed from earlier passes)

- **A doc can be factually perfect and still wrong about its own role.** `strand-anim.md` got
  every file, seam, mesh name, constant and invariant right — and described a "sandbox… built for
  drop-in to the main animation toolset" that **had already been dropped in**, in three places,
  months earlier. Nothing in it was false; the *tense* was. Consequence: `params.js` reads as a
  sandbox slider default while `overhang_unzip_overlay.js:83` consumes it in production. **Tell:
  grep every exported symbol of the module for importers OUTSIDE the module's own directory,
  before you read a word of the body.** Four external importers is not "a sandbox". This is the
  cheapest check in the loop and it caught the only real hole in the most accurate rule of 11.
- **Reuse is usually partial, and the unreused half is where the duplication lands.** The editor
  took `createStrandRenderer` and left `buildStrandGeometry`, so it hand-rolled the contract at
  `overhang_strand_anim.js:441/:599` and re-derived `smoothstep` inline 4×. Same shape as
  `expanded_spacing.js` (unfold) and `_ham_path_search` (scaffold). **Tell: when a module exports
  a matched pair (builder + renderer, model + view) and only one is imported elsewhere, the other
  has a hand-rolled twin.** Find it and name it in the rule; nothing else will pin them together.

- **When one rule is enforced in two places, the doc almost always describes only one of them —
  and usually the one that doesn't decide.** Cluster scoping is enforced at create time
  (`resolve_cluster_scope` → freezes `affected_helix_ids`) *and* at render time
  (`_arm_filter_cluster` → re-derives a cluster from helix membership, ignoring `op.cluster_ids`).
  The plan documented only the first, so its "how to apply" advice was about a field the geometry
  never reads. **Tell: for the doc's central field, grep who *reads* it, not who writes it.** If
  the consumers are all create/edit/copy/debug and none are in the math, the field is metadata and
  something else is doing the enforcing. Third pass running for the two-implementations shape
  (after `expanded_spacing.js` and the hand-rolled strand contract).
- **A subsystem is rarely one file, and the extra files are usually globbed by nothing.** `unfold`
  globbed `unfold_view.js` alone; the subsystem is three files, and the other two
  (`cross_section_minimap.js` 712, `expanded_spacing.js` 296) were matched by **no rule in the
  repo**. Worse, `expanded_spacing.js` is a **second, divergent implementation of the same
  contract** — it notifies 7 subsystems where the unfold view notifies 5, and it is the only
  caller of one of them. **Tell: grep the rule's central function name (`applyUnfoldOffsets`)
  repo-wide before writing the fan-out table** — a second caller list is a maintenance trap the
  rule must name, and it never shows up if you only read the file the glob points at. Cousin of
  "a globbed-but-unmentioned file is a guaranteed hole"; this is the unglobbed-and-unmentioned
  version, which is invisible to that mechanical check.
- **A cross-feature claim can be REVERSED, not merely dead — and reversed is worse.** `unfold.md`
  said "atomistic is hidden when unfold activates"; the code does the opposite (atomistic
  *blocks entering* unfold, `main.js:2547`). "View cube hidden when unfold active" and
  "`deformView.snapOff()` called before unfold activates" were pure fiction (0 hits / 0 callers).
  A dead symbol is caught on first grep; a **backwards causal direction** reads as correct,
  survives a spot-check, and sends the next session to instrument the wrong module. **Tell: for
  every "X happens when Y activates" sentence, find the code that *decides* it** — here all five
  gates lived in one undocumented function (`_toggleUnfold`), not in the view at all.
- **The doc's error was inherited from a wrong comment in the code it documents.** Two of
  `unfold`'s wrong facts (arcs are `THREE.Line`; minimap is top-right) are verbatim from
  `unfold_view.js:9` and `cross_section_minimap.js:2-3`, both of which contradict their own files
  (`LineSegments` at `:189`; `bottom/left` at `:58-66`). Auditing the doc against the code's
  *prose* reproduces the bug. **Read the constructor and the CSS, not the header comment** — and
  log the comment to `tech_debt` + a "Traps" section so nobody later "fixes" the code to match it.
  Third pass in a row where a stale source comment was the seed.
