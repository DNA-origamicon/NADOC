# Standing lessons (carry forward — compressed from earlier passes) — supporting detail

[Topic head](../../plan_audit_ledger.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

- **Audit the path-scoped rules, not just the plans.** A stale `project_*.md` costs a session only
  when someone opens it; a stale `.claude/rules/*.md` is **auto-loaded** and teaches every session
  in the area, unprompted. Same rot, strictly worse decay.
- **The glob heuristic is retired — it went 4 for 4, then 0 for 2.** A bad glob (`cadnano-2d`,
  `animation`, `selection`, `cadnano-editor`) does predict body rot, because the rule never loaded on
  the code it describes so nothing ever corrected it. But `api-and-state` and `main-init` had
  **perfect globs and the worst bodies yet**. **Exposure is not validation:** a rule is corrected
  only when a session *fails* against it, and the dominant rot — stale line anchors, undercounted
  API surfaces, dead "CRITICAL" warnings — fails silently. Rank by **code churn in the globbed
  files**.
- **Grep the identifiers inside the pretty ASCII diagram — they are the least-checked text in any
  doc.** `rendering`'s architecture box was built on `iFwd`/`iRev`, two instanced meshes with **zero
  hits repo-wide**; nothing was ever renamed away from them, they were simply invented and never
  checked. A diagram reads as settled architecture, which is exactly why nobody greps it. Same class
  as the 3-for-3 phantom `MAP_*.md` links and `api-and-state`'s phantom `_active_design`.
- **An invariant can be obsoleted by a code *improvement*, not by rot — and it fails silently.**
  `deformation.md`'s only `CRITICAL` section demanded `deformations=existing_design.deformations`
  on every `Design(...)` rebuild in `lattice.py`; the file later migrated to
  `existing_design.copy_with(...)` (16 sites), which preserves unlisted fields by construction, so
  the obligation became a **no-op** — and the runbook still made grepping `Design(` the first step
  for "my bend vanished" (a file with **one** `Design(` call in it). **Tell: any "every call site
  MUST pass X" sentence — grep whether a helper, default, or base class now makes it structural.**
  Cousin of the dead-invariant lesson below: both are docs describing a world that got better.
- **Verify doc-only invariants by grepping the call sites, not the definition.** `rendering.md` and
  its runbook both stated "after any `revertToGeometry()`, call `deformView.reapplyLerp()`" — the
  function exists and is exported, and **nothing in `frontend/` has ever called it**. A dead symbol
  fails loudly on first use; a dead invariant makes readers add a call nobody needed, or stop looking
  for the real cause. Pairs with "verify ONLY/ALWAYS/NEVER sentences first".
- **A globbed-but-unmentioned file is a guaranteed hole** (mechanical tell, cheap, run it first):
  diff each rule's `paths:` against the filenames its body mentions. `rendering` globbed 5 and never
  mentioned 2 — one of which (`crossover_connections.js`) carries a DNA-topology law in its file
  header. The rule auto-loads on that file and says nothing about it. *Run on the 3 remaining rules
  2026-07-30: all clean, so it does not rank them — fall back to churn.*
- **Delete enumerations; keep recipes.** A list whose length tracks the codebase (routes, files,
  hotkeys, init calls) is guaranteed to rot and is unreadable when correct. `api-and-state`'s route
  index was 84 of 567 with 10 dead; `main-init`'s init-order table was 30 of 154 with **every line
  number wrong**. Both were replaced by the `rg` command that regenerates the list on demand, plus
  the invariant that makes it meaningful (`prefix="/api"` on all 62 routers; store fires subscribers
  in registration order). Coarse family maps are fine — they change only when a subsystem appears.
- **In a file under active carve-up, a line anchor is a liability, not a citation.** Write the *law*
  ("registered after `initSequenceOverlay` so it fires after the sprite rebuild") and let the reader
  grep for the line. Where an anchor genuinely helps, date it and say it drifts.
- **Re-derive the model before auditing the symbols.** `api-and-state` and its runbook were both
  built on `_active_design` + a module-level `_history` in a backend that is per-document
  (`_sessions[doc_id]`). Every sentence downstream inherited the error. **Tell: the doc says "the
  X", the code says `dict[key, X]`.**
- **Verify ONLY / ALWAYS / NEVER sentences first.** They are the most-obeyed and most-damaging
  lines in any doc. `RUNBOOK_API.md` said `mutate_and_validate` was "the ONLY correct way to
  mutate" after `mutate_with_reconcile` became mandatory for cluster-affecting edits — following it
  writes a silent cluster bug.
- **Count the API surface; don't sample it.** `selection.md` listed 8 of 26 init opts, 2 of 19 API
  methods, 8 of 11 store flags and 3 of 10 enum values — every listed item *correct*, so any
  spot-check passes and the gap is invisible. Compare integers (destructure length, return-object
  keys, literal fields) against each doc table. And check whether a stale **source comment** shares
  the doc's root: 3 of those 4 undercounts were mirrored in the code itself, so fixing only the rule
  leaves the seed. Log the comment to `tech_debt` and give the rule a "Traps" section so nobody
  "fixes" the code to match its own wrong comment.
- **The missing rule is worse than the stale rule, and it is invisible.** A stale rule announces
  itself when a session hits a dead symbol; an absent one produces no signal and the area gets
  re-derived forever. Tell: when a rewrite makes you write "not this rule: X", check whether X has a
  rule. That found `cadnano-editor` (10,713 LOC, zero coverage).
- **Verify the handoff's own anchors.** Pre-gathered evidence carried into the `cadnano-editor` pass
  had **5 wrong claims** (off-by-one line, an unbound hotkey, 3 keys in the wrong file, a constant in
  the wrong module). Reuse a handoff to *scope* the probe; re-verify everything you write down — a
  wrong rule is auto-loaded, so it is worse than the hole it fills. **Tally: 6 passes, 6 handoffs
  with at least one wrong claim** — now **7 for 7**: the `unfold` handoff said `deform_view.js:308`
  calls `reapplyIfActive()` "after *every* lerp", when it fires only inside the async
  `getStraightGeometry()` fallback subscriber, not on the per-frame lerp path.
- **A rule can be wrong about a causal story, not just a symbol.** `cadnano-2d`'s worst content was a
  "Known culprit (fixed 2026-04-01)" section guarding against a subscriber that no longer existed, in
  a function with zero callers. Every identifier still resolved; only the wiring was gone. When a
  rule explains WHY, probe the call graph.
- **State test coverage honestly and by name.** A filename that implies coverage it doesn't provide
  is worse than no test (`e2e/cadnano_*.spec.js` cover the importer and the *editor*, not the view;
  `test_cluster_config.py` is Alpine HPC, not cluster transforms).
- **Plan status text is stale in BOTH directions** (4 for 4 among kept plans). `mixed_representation`
  claimed "UI pending" (shipped) *and* claimed two helpers that no longer exist. Diff every head
  claim line-by-line; never trust the top-line banner. **Probe the `NOT built` list first** — that is
  where a stale doc most actively misleads (`protein_attachment`'s two "not built" bullets were a
  563-LOC shipped subsystem and a helper on a live call path).
- **A plan that outlived its subject splits into a dead half and a still-true half belonging to a
  younger doc.** Probe the halves separately; "some of this is still true" is not a reason to keep
  the file. Before any delete, grep the head for "user rule / user decision / user accepted" — a user
  decision whose signature looks like a bug (matched-ends `far−near ∈ {P, P-1}`) is the highest-risk
  thing to lose.
- **A code-location table beats the prose around it.** Probes keep finding paths moved by the
  carve-ups (crud.py → `routes_*`, main.js → `ui/*`) and test paths that were never right.
- **Split head/archive as part of the audit** when a head has grown into a reverse-chronological work
  log (880 lines in `simulate_panel_overhaul`). Mechanical, and as much the deliverable as the verdict.
- **Every pass turns up stale non-plan artifacts the doc was innocent of** — dead-API scripts, e2e
  specs POSTing removed routes, `CELLS_6HB` copy-pasted with divergent geometry, a 4th divergent
  `STAPLE_PALETTE`, `docs/triage/` fiction. Those go to `project_tech_debt`. A good probe audits the
  code as a side effect; give the code defects a home instead of dropping them.

**Standing HOLDs (user-owned decision, do not touch):** `project_bundle_stiffness_params`,
`project_periodic_md` — both LIVE-REFERENCE, parked in the HOLD block above.
