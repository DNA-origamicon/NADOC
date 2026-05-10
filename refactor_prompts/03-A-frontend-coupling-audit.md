# Refactor 03-A — Frontend coupling / circular-import audit

You are a **worker session**. Execute exactly this one task. Do NOT pick further candidates. The deliverable is a *report* (one or more Findings entries), not a sprawling code change. Code changes are only allowed for circulars whose fix is mechanically obvious AND < 20 LOC; everything else is documented and handed back to the manager.

## Pre-read (mandatory, in this order)

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (especially #1 baseline-twice, #2 lint delta-stable, #8 frontend, #9 clean-tree)
3. `REFACTOR_AUDIT.md` § "Categories" — this is a **(e) coupling** task
4. `REFACTOR_AUDIT.md` § "Findings" #1–#7 — context for what's already been refactored
5. The followup evaluations for 02-A and 02-B — they document the framework debts that produced the new preconditions
6. This prompt to the end

## Goal

Run a coupling audit on `frontend/src/`. Produce numbered Findings entries for:

- Every circular-import cycle (must be 0 in healthy code; report whatever exists)
- Every module with import fan-in ≥ 15 (modules everyone depends on — kernels)
- Every module with fan-out ≥ 20 (modules that pull in everything — god-files)
- Every cross-area import that bypasses an intended boundary (e.g. `frontend/src/ui/` importing from `frontend/src/scene/` deep internals; `frontend/src/scene/` importing from `frontend/src/cadnano-editor/`)
- Any heavy *runtime* coupling that imports look clean for but state shows otherwise — specifically, `window.*` global writes outside `main.js` (per JS-specific signals in REFACTOR_AUDIT.md)

## In scope

- **Read-only investigation across `frontend/src/`** — every `*.js` file (skip `*.test.js`).
- Tools: `npx -y madge`, `npx -y jscpd`, `rg`, `grep`. No new dev-dependencies added to `package.json`. Run via `npx -y` so the binaries are ephemeral.
- Code changes ONLY for: a circular cycle whose break is a single-line `import` removal or a single function move ≤ 20 LOC. If any potential fix is larger, do NOT implement it — document it as a Finding with priority `high` and stop. The manager will pick up.

## Out of scope (do not touch)

- `package.json` / `frontend/package.json` — no new dependencies.
- Backend code (`backend/`) — only `frontend/src/` is in scope.
- Test files (`tests/`, `frontend/**/*.test.js`).
- Any file the audit doesn't directly identify as part of a coupling problem. The temptation: "while I'm here, this looks ugly, let me fix it." Resist; that's a separate prompt.
- Refactoring `main.js` for fan-out — its 11829-LOC size is a known god-file already tracked. Just confirm/refute it shows in the fan-out top-3.
- Refactoring `client.js` for fan-out — likewise tracked; refactor 03-B is queued for it.

## Verification plan

### Pre-state capture
```bash
git status > /tmp/03A_dirty_pre.txt   # precondition #9: clean tree
just lint > /tmp/03A_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/03A_lint_pre.txt
just test > /tmp/03A_test_pre1.txt 2>&1
just test > /tmp/03A_test_pre2.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/03A_test_pre1.txt | sort > /tmp/03A_baseline1.txt
grep -E '^FAILED|^ERROR' /tmp/03A_test_pre2.txt | sort > /tmp/03A_baseline2.txt
comm -12 /tmp/03A_baseline1.txt /tmp/03A_baseline2.txt > /tmp/03A_stable_failures.txt
```

### Investigation rhythm
Run, in this order. Save raw output for the followup session.

```bash
# ── 1. Circular imports ──────────────────────────────────────────────────────
npx -y madge --circular --extensions js frontend/src > /tmp/03A_circulars.txt 2>&1

# ── 2. Fan-out ranking (modules with most imports) ───────────────────────────
for f in $(find frontend/src -name '*.js' -not -name '*.test.js'); do
  n=$(grep -cE "^import\b|^const.*=\s*require\(" "$f")
  echo "$n $f"
done | sort -rn > /tmp/03A_fanout.txt
head -20 /tmp/03A_fanout.txt

# ── 3. Fan-in ranking (modules imported by most others) ──────────────────────
# Build map: file -> count of unique sources that import it
npx -y madge --json frontend/src > /tmp/03A_madge.json 2>/dev/null
# Or compute manually if madge JSON not loaded:
for f in $(find frontend/src -name '*.js' -not -name '*.test.js'); do
  base=$(basename "$f" .js)
  # crude: count source files mentioning './<base>' or '/<base>.js'
  n=$(rg -lF "/$base'" frontend/src | wc -l)
  m=$(rg -lF "/$base\"" frontend/src | wc -l)
  echo "$((n + m)) $f"
done | sort -rn > /tmp/03A_fanin.txt
head -20 /tmp/03A_fanin.txt

# ── 4. Cross-area boundary leaks ─────────────────────────────────────────────
echo "ui → scene internals:" > /tmp/03A_boundary.txt
rg -n "from\s+['\"]\.\./scene/" frontend/src/ui >> /tmp/03A_boundary.txt
echo "scene → ui:" >> /tmp/03A_boundary.txt
rg -n "from\s+['\"]\.\./ui/" frontend/src/scene >> /tmp/03A_boundary.txt
echo "scene → cadnano-editor:" >> /tmp/03A_boundary.txt
rg -n "from\s+['\"]\.\./cadnano-editor/" frontend/src/scene >> /tmp/03A_boundary.txt
echo "cadnano-editor → scene:" >> /tmp/03A_boundary.txt
rg -n "from\s+['\"]\.\./scene/" frontend/src/cadnano-editor >> /tmp/03A_boundary.txt

# ── 5. Runtime global-state coupling ─────────────────────────────────────────
rg -n "window\.\w+\s*=" frontend/src --glob '!main.js' > /tmp/03A_globals.txt
wc -l /tmp/03A_globals.txt

# ── 6. Duplication (sanity) ──────────────────────────────────────────────────
npx -y jscpd --min-lines 30 --min-tokens 80 frontend/src > /tmp/03A_jscpd.txt 2>&1
```

### Post-state capture (only if any code changed)
```bash
just lint > /tmp/03A_lint_post.txt 2>&1 ; echo "EXIT $?" >> /tmp/03A_lint_post.txt
just test > /tmp/03A_test_post.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/03A_test_post.txt | sort > /tmp/03A_post_failures.txt
diff /tmp/03A_stable_failures.txt /tmp/03A_post_failures.txt   # expect ⊆ baseline ∪ flake
```

If no code changed, you can skip post-state. Just confirm baseline tests still pass after the investigation (`npx -y madge` shouldn't touch anything but be safe).

## Stop conditions

- **Pre-state dirty tree is acceptable** for this read-only audit, BUT you MUST list every `M`/`??` file in your `### Pre-existing dirty state declaration`. (Per precondition #9 — Pass 2-A absorbed dirty state silently; don't repeat.)
- If `npx -y madge` fails to install: try `npx --yes --package=madge madge --version` once, then if still failing, document and continue with the manual fan-in/fan-out scan.
- If a circular cycle's break requires > 20 LOC or any semantic decision: **stop, document in a Finding with priority `high`, do not implement**.
- If `jscpd` flags a duplicate that overlaps with an already-tracked Finding (#1, #2, #3, #7): note it and move on; don't re-refactor.

## Lint-delta rule (precondition #2)

This is investigation-only by default. Pre lint will likely show ~449 errors (chronic baseline). Success = post-error-count ≤ pre-error-count IF you changed any code. If you did NOT change code, lint delta is N/A.

## Output format for final message

```markdown
## 03-A frontend coupling audit — REPORTED  (and optional REFACTORED if a circular was fixed)

### Pre-existing dirty state declaration
<list every file from `git status` at session start that this refactor did NOT touch>

### Pre/post environment
- pre lint: <PASS/FAIL>; post lint: <unchanged/N hunks delta>
- pre test: <X> pass / <Y> fail / <Z> error  |  post: <unchanged or X' / Y' / Z'>
- stable baseline failure set: <count> ; flake set: <count>

### Coupling findings summary
| # | Type | Severity | Module(s) | One-line |
|---|---|---|---|---|
| F1 | circular | high | A.js ↔ B.js | <cycle nodes> |
| F2 | fan-out | low | main.js | imports N modules |
| ... |

### Per-finding details
For each row above, write a full Findings-template entry to be appended to `REFACTOR_AUDIT.md`. Use the post-Pass-2 template (Category, Where, Files touched, Out-of-scope diff in same files, API surface added, Callsites touched, Symptom, Why it matters, Change, Effort, Three-Layer, Pre-metric → Post-metric, Linked Findings).

For investigation-only findings (no code change), use:
- **Files touched**: `none` (or the report file path if you wrote one)
- **Callsites touched**: 0
- **Change**: `documented; not implemented — see manager queue`
- **Pre-metric**: the raw count (e.g. "5 circular cycles found by `madge --circular`")
- **Post-metric**: equal to pre-metric (no change made)

### What was deliberately NOT changed
<bullet list — show you held the line on out-of-scope items, especially "while I'm here" temptations>

### Open questions / surprises
<anything the prompt didn't anticipate>

### Tracker updates
- inventory rows updated for any file that scored top-3 in fan-in or fan-out
- N new Findings entries appended (numbered #8 onward)
```

## Success criteria

- [ ] `### Pre-existing dirty state declaration` section present and complete
- [ ] `npx -y madge --circular` ran and produced output (or fallback documented)
- [ ] Top-10 fan-out and top-10 fan-in lists captured to `/tmp/03A_*.txt`
- [ ] Cross-area boundary leaks enumerated (or "none found" stated)
- [ ] At least one Findings entry written, even if outcome is "no high-severity coupling debt found"
- [ ] If any code changed: lint delta ≤ 0 AND test post ⊆ stable_baseline ∪ flakes
- [ ] No `package.json` / `frontend/package.json` modification
- [ ] No file outside `frontend/src/` modified
- [ ] Tracker `## Active refactor prompts` row for 03-A updated to `✓ closed`

## Do NOT

- Add new categories to the framework — that's a manager job; flag them in your Open questions instead.
- Refactor `main.js` or `client.js` size — separate prompts (03-B is queued for client.js).
- Run `just frontend` or modify the running app — read-only audit.
- Commit or push.
