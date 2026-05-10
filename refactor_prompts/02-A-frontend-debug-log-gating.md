# Refactor 02-A — Frontend debug-log gating in `main.js`

You are a **worker session**. Execute exactly this one refactor. Do not pick further candidates. Do not propose other work. When done, fill the metrics and update the tracker.

## Pre-read (mandatory, in this order)

1. `CLAUDE.md` — three-layer law, tone, verification expectations
2. `REFACTOR_AUDIT.md` § "Universal preconditions" — flake handling, lint, pre-flight, pydantic, dead-file, worktree, frontend-app rules
3. `REFACTOR_AUDIT.md` § "Findings" #1–#5 — context for what Pass 1 already did
4. `memory/MEMORY.md` index; open `feedback_*.md` only if their filenames match what you're touching
5. This prompt to the end before doing anything

## Goal

`frontend/src/main.js` has 105 `console.log` calls in 11829 lines. Some are gated behind `window.nadocDebug.<flag>` (see lines 2072, 2089, 2130, 2135 etc.); many are unconditional and spam the dev console on every load. Goal: classify each `console.log` and gate the dev-only ones uniformly.

## In scope

- **Only `console.log`** in `frontend/src/main.js`. Do not touch `console.error`, `console.warn`, `console.info`, `console.debug`. Those are legitimate diagnostics.
- **Only `main.js`** — not other files. Even though `pathview.js` (24 calls), `slice_plane.js` (19), and others have many, this prompt is scoped to `main.js`.
- Add a new flag `window.nadocDebug.verbose` (default `false`) to the existing `nadocDebug` object defined at `main.js:11737` if no existing flag fits. Re-use existing flags (`cn`, `posTrace`, `snapPos`, `storeTrace`, `subTrace`, etc.) where the call's domain matches.
- Wrap each unconditional dev-debug `console.log` in `if (window.nadocDebug?.<flag>) { console.log(...) }`.

## Out of scope (do not touch)

- `console.error` / `console.warn` calls — they're real diagnostics
- The `STILL BROKEN` instrumentation block in `frontend/src/scene/cadnano_view.js` — user-active debug machinery
- Any console.log that's already gated — leave its existing gate alone
- Log message text — do not edit strings
- Extracting code from `main.js` — that's a different refactor (god-file decomposition)
- Other `*.js` files

## Classification rubric

For each `console.log` in `main.js`, decide one of:

- **dev-only** → wrap in `if (window.nadocDebug?.<flag>)`. Pick the flag that matches the call's purpose; introduce `verbose` as the catch-all for un-domain-specific dev logs.
- **production-startup** → leave unchanged. Examples: app version banner, build hash, "loaded N helices in Xms" metrics that are useful in production bug reports.
- **production-event** → leave unchanged. Examples: "user-initiated export started" or other one-shot user-driven log lines.
- **already-gated** → leave unchanged.
- **unsure** → leave unchanged + add a `// REVIEW: classification` comment so the followup session can decide.

Bias: when in doubt, classify as `production-startup` and leave it. False negatives (over-gating) are worse than false positives.

## Verification plan (mandatory)

Run these in order.

### Pre-state capture
```bash
just lint > /tmp/02A_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/02A_lint_pre.txt
just test > /tmp/02A_test_pre1.txt 2>&1
just test > /tmp/02A_test_pre2.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/02A_test_pre1.txt > /tmp/02A_baseline1.txt
grep -E '^FAILED|^ERROR' /tmp/02A_test_pre2.txt > /tmp/02A_baseline2.txt
comm -12 <(sort /tmp/02A_baseline1.txt) <(sort /tmp/02A_baseline2.txt) > /tmp/02A_stable_failures.txt
diff <(sort /tmp/02A_baseline1.txt) <(sort /tmp/02A_baseline2.txt) > /tmp/02A_flakes.txt || true

rg -c 'console\.log' frontend/src/main.js > /tmp/02A_loglines_pre.txt
rg -n 'console\.log\(' frontend/src/main.js | wc -l   # should match
# Count of UNCONDITIONAL: lines where `console.log(` is NOT inside an `if (window.nadocDebug` block.
# Heuristic — manually classify; do not rely on grep alone.
```

### Implementation
Edit `frontend/src/main.js` in place. Each gating change should be a single targeted `Edit` with enough context to be unambiguous. Do not run a regex-replace blindly.

### Post-state capture
```bash
just lint > /tmp/02A_lint_post.txt 2>&1 ; echo "EXIT $?" >> /tmp/02A_lint_post.txt
just test > /tmp/02A_test_post.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/02A_test_post.txt > /tmp/02A_post_failures.txt
diff /tmp/02A_stable_failures.txt /tmp/02A_post_failures.txt
# Expected: post ⊆ stable_baseline ∪ flakes. Any new failure is a regression — revert.

rg -c 'console\.log' frontend/src/main.js > /tmp/02A_loglines_post.txt
# Net log count should be ~unchanged (you're gating, not removing).
```

### Frontend app verification
- If `just frontend` is running and you can reach the app, load it once with `window.nadocDebug = {}` (no flags), confirm dev console is markedly quieter than before. Then set `window.nadocDebug.verbose = true` and confirm logs return.
- If you cannot reach the app, your final message MUST start with `NOT VERIFIED IN APP` and explain why.

## Success criteria

- [ ] `just lint` passes pre and post (record both exit codes)
- [ ] `just test` post-failures ⊆ stable baseline ∪ flakes (no new failures)
- [ ] At least 30 `console.log` calls newly gated (or fewer if classification rubric leaves more in `production-*` than expected — document why)
- [ ] No `console.error` / `console.warn` touched
- [ ] No files outside `frontend/src/main.js` modified
- [ ] Frontend exercised in app, OR `NOT VERIFIED IN APP` caveat at top of final message
- [ ] `REFACTOR_AUDIT.md` updated:
  - inventory row for `frontend/src/main.js` set to `PARTIAL` with notes
  - new Findings entry using the template (Category: (b)/(d), pre/post log counts as the metric)
- [ ] No git commit unless explicitly asked by the user

## What to record

Append to `REFACTOR_AUDIT.md` under `## Findings` using the template. Required fields:

- **Category**: (b) dead-code-adjacent / (d) configuration unification
- **Files touched**: just `frontend/src/main.js:Lstart-end`
- **Callsites touched**: `<N>` (number of `console.log` lines newly gated)
- **Pre-metric → Post-metric**: e.g. `105 unconditional console.log → 30 unconditional`
- **Three-Layer**: not applicable (UI/main bootstrap)

## Stop conditions (refuse to continue)

- If `just lint` fails before any change → stop, report.
- If `just test` baseline differs by > 5 tests between two pre-runs → stop, suspect environment issue.
- If a flag you'd pick already has a different documented meaning → stop, ask the manager (file name `REFACTOR_AUDIT.md`-style report; do NOT invent meaning).
- If gating one log requires restructuring surrounding code → stop; that log is out of scope for this prompt.

## Output format for final message

```
## 02-A frontend debug-log gating — <REFACTORED|UNSUCCESSFUL>

[NOT VERIFIED IN APP — <reason>]   ← only if applicable

### Metrics
- pre lint: <PASS/FAIL>; post lint: <PASS/FAIL>
- pre test: <X> pass / <Y> fail / <Z> error  |  post: <X'> / <Y'> / <Z'>
- stable baseline failure set: <count> ; flake set: <count>
- console.log unconditional pre: <N1> ; post: <N2>
- callsites gated: <K>
- new flags introduced: <list>

### What was changed
<one paragraph>

### What was deliberately NOT changed
<bullet list — show you held the line on out-of-scope items>

### Tracker updates
- inventory row: `frontend/src/main.js` → PARTIAL, low
- Findings #6 added

### Open questions / surprises
<anything the prompt didn't anticipate>
```
