# Superseded final-session notes — historical evidence

[Topic head](../../plan_audit_ledger.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Superseded final-session notes

**THE AUDIT QUEUE IS EMPTY. The loop has reached its terminal state.** 38 recorded rows (30 here
+ 8 in the archive): every
`memory/project_*.md` in the queue, both root plans, and all 11 `.claude/rules/` (10 rewritten,
1 written new) are audited. **Do not invent new targets.** What remains is three one-question
HOLDs that only the user can settle — see the HOLD section, and surface all three together:
`drag_scrub` (shipped-then-vanished: dropped, or lost in the carve-up?),
`bundle_stiffness_params` (user said delete; it's a live 0T parameter DB → provisional
LIVE-REFERENCE), `periodic_md` (user said archive; the backend is live → provisional
LIVE-REFERENCE). If a *new* plan file is written later, it joins the queue then.

**This pass's tell — a doc's self-label is a claim, and it can be false in BOTH directions at
once.** `pipeline_validation_log` was headed "NOT YET VALIDATED" and sat in the unfinished band
for that reason alone. It was neither: the validation it called pending had been **run to
completion** (T0 200 ns, T1 185 ns) *and* the whole method it validated had been **abandoned**
nine days later (τ≈11 ns → needs ~2 µs), by a successor doc that was already the one `MEMORY.md`
and the code point at. **Tell: a self-labelled-incomplete doc is the cheapest kind to over-rank.
Before ranking anything on its own status line, diff it against its newest sibling by DATE — the
successor here was 9 days newer and answered every open item.**

Second: **check whether the artifacts a log claims to have produced actually carry those names.**
The log named `T0/params.json` and `T0/convergence_report.json` as outputs. Neither string exists
anywhere in the repo — the real file is `params_c36.json` (and `convergence.py` returns its report
as a dict, never writing one). A filename in a log is as falsifiable as a symbol, and it's an
`ls` away. The `_c36` suffix was also the whole story: it proved a charmm36 re-run the log never
mentions.

Third: **`.gitignore` is part of the probe.** `runs/` is gitignored, so `run_pipeline.py` and
every artifact this "log of record" describes exist **on one computer only** — a two-computer
repo where half the evidence isn't in the repo. Nothing in the doc said so.
**Tell: when anchors resolve to paths outside `backend/`/`frontend/`/`tests/`, grep `.gitignore`
for the top-level dir before you trust that the next session can see them.**

(The count/number tell paid again: the live DB contradicts all **four** headline parameters, not
some; and modules were 6 in the doc, 8 on disk.)

---

*(Previous pass — `project_ux_overhaul`, 07-31)*

**Audit the SHIPPED list, not just the open list.** Every prior pass treated "shipped" rows as
settled and spent its probe on the open items. This pass inverted it and found the two worst
errors in the file there: `input/drag_scrub.js` — claimed shipped and wired into 7 panels — **does
not exist**, and `scene/overhang_binding_lines.js` was deleted 2026-07-01 (recorded in a *sibling*
doc, never crossed off here). A shipped row is a claim with an expiry date and nothing ever
re-checks it, whereas an open item at least gets re-read by whoever picks it up. **Tell: `ls` every
file path in the SHIPPED section first. It is one command, and a shipped-but-deleted feature is
strictly worse than a stale open item — it tells the next session the work is done.**

Second: **when a doc cites a line number in a file that has been carved up, check the file's LOC
before chasing the anchor.** This doc cited `main.js:10517`; `main.js` is **8,070 lines**. That
single number dated the whole citation block to before the carve-up and predicted (correctly) that
every `main.js:NNNN` in the file was worthless. **Tell: `wc -l` the god-file first; any cited line
beyond it marks the doc's entire line-reference vintage as pre-carve-up, and you can skip verifying
them individually and just re-derive.**

Third: **a "held pending plan X" note in tech_debt plus a "see tech_debt" note in plan X is a
deadlock, not a decision.** `ui/validation_report_panel.js` is HELD in `project_tech_debt:98`
*because* it is item 15 of this plan; item 15 exists because the panel exists. Neither file can
resolve it, and meanwhile the panel is orphaned AND its DOM mount was never added to `index.html`.
**Tell: when an audited plan cites tech_debt for a decision, open tech_debt and check it isn't
citing the plan back. Break the cycle in the pass — name the concrete precondition (here: "mount
it or delete it") rather than leaving two mutual deferrals.**

(The carried-in argument-diff tell paid a third time: 3 destructive `showConfirm` sites without
`danger:true`, and `import_menu.js` as the lone holdout on the legacy `showToast(msg, ms)` form —
4 sites out of 374. Both were invisible to existence-level probing.)

*(Its ▶ NEXT — `pipeline_validation_log` — was executed 07-31; the prediction "don't rank it just
because the queue put it in the unfinished band" was right: it deleted.)*

Carried in:

- **The UI-chrome band is closed** — `project_ux_overhaul` (P2) is the sole owner of file
  browser / library panel / sidebar widths / modals / toasts; no rule and no other topic file
  covers it. Read its head before any UI-chrome work; its `_archive.md` is known-stale by design.
- **Three HOLDs now, not two.** `drag_scrub` joined `bundle_stiffness_params` and `periodic_md`.
  All are one-question decisions; consider surfacing all three together to the user in one go.

---

*(Previous pass — `project_overhang_sequence_display`, 07-31)*

**Existence is the wrong unit — probe the ARGUMENTS.** Every anchor was alive for the second pass
running, and the one real bug was invisible at symbol level: `assembleOverhangSequence(ovhg,
domainLen)` has an optional 2nd arg, five production call sites pass `overhangDomainLength(...)`,
and **one — `sequence_overlay.js:227` — passes nothing**, so drag-resized overhangs render the
stale nominal length in 3D while every other surface shows the grown one. A probe that asks
"exists / wired / orphaned" reports six healthy callers. **Tell: whenever a doc names a helper with
an optional or defaulted parameter, enumerate its call sites and DIFF THE ARGUMENT LISTS. The odd
one out is the defect, and it is the cheapest real bug this loop finds.**

Second: **a module that imports nothing from the canonical helper file is a rival implementation.**
`overhangs_manager_popup.js` and `assembly_overhangs_manager_popup.js` both read raw
`ovhg.sequence`, and the latter carries a **third** copy of the length formula — neither imports
`design_queries.js` at all. **Tell: after finding the canonical module, list every sibling in the
subsystem and check its import block. A sibling with zero imports from the canonical file has
either no business there or its own copy of the rule** (fifth sighting of "two mechanisms enforcing
one rule" in this ledger — here it is three).

Third: **"kept for future / headless / ML callers" is a prediction, and it expires silently.**
`reassign_if_sequenced` was left in for exactly that reason and has zero callers repo-wide, while
three docstrings still describe its replaced semantics as current. **Tell: grep the named future
caller. If the doc says "kept for X", X is a falsifiable claim.**

(The carried-in count tell paid again: propagation tests **3**, doc said 4; `design_queries.test.js`
**53** `it(`; e2e lives under `frontend/e2e/`, not `e2e/`.)

---

**When every anchor is alive, the doc is still wrong — in its COUNTS.** This was the first pass
where not one named symbol had died: 15 panel internals, 9 `ct_icons` exports, 11 API wrappers, 8
`_cv_*` helpers, 2 length-fork guards — all present, mostly at the cited lines. And the doc was
still stale, because a doc records the tests that existed the day it was written and **nothing ever
increments it**: 6 vitest spec files documented, **12** on disk; 12 backend tests documented, **16**;
11 `ct_icons` tests documented, **17**. **Tell: for a doc that reads as "shipped", count test files
and test functions BEFORE reading the narrative.** A doubled count is months of undocumented work,
and it means the doc's *open-items* list is exactly that far out of date too — which is where the
audit value actually is. Cheapest version: `ls` the module's sibling `*.test.js` and
`grep -c '    def test_\|it('` the pinned test files.

Second, the one that finds real defects rather than doc drift: **a backend comment that delegates to
a frontend function is an automation hole with a name.** `_cv_create_bound_binding` returns early on
unequal-length attach sub-domains with the comment "the duplex … is created separately by the
frontend's `_ensureDuplexForPair`". That sentence *is* the bug: the UI path works, and every
non-UI caller (raw API, `headless_build.apply_connection_version`) silently gets neither a binding
nor a duplex. **Tell: grep backend comments/docstrings for frontend symbol names — `_on`, `.js`,
"the frontend", "the panel". Each hit marks a code path that headless and automation cannot
complete**, and none of them show up as a dead symbol, a failing test, or a 500.
