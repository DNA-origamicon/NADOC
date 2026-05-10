# Audit 08-A — Frontend comprehensive audit (scene + UI + cadnano-editor)

You are a **worker session** in a git worktree. **INVESTIGATED-only.** Output: per-file refactor priority tags + top-5 high-priority candidates for future passes. **No code changes.**

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" — note **#1 (3× baseline)**, **#15 (CWD-safety preamble)**
3. `REFACTOR_AUDIT.md` § "Findings" #8–#11 (Pass 3-A's coupling audit; do NOT re-do its work — just verify the audit is still valid post-Pass-7)
4. This prompt

## Step 0 — CWD safety
```bash
pwd && git rev-parse --show-toplevel
# Both must equal $WORKTREE_PATH; if not STOP and report.
```

## Goal

Tag every NOT SEARCHED file in `frontend/src/scene/` (42 files), `frontend/src/ui/` (32 files), and `frontend/src/cadnano-editor/` (7 files) with a refactor priority. Total ≈ 81 files. Surface top-5 highest-priority candidates for future refactor passes.

## In scope — heuristic signals (cheap, fast)

For each file, gather these signals (one `rg`/`wc` invocation each, scriptable):

1. **LOC** (`wc -l`)
2. **Function count** (`grep -cE "^(export )?(async )?function|^[a-zA-Z_]+\s*=\s*(async )?\(`)
3. **Long-function presence** — any function body > 150 LOC. Heuristic: count consecutive non-blank, non-`}` lines after a function declaration. Cheap proxy: `awk '/^(export )?function/{in_fn=1; n=0; next} in_fn{n++; if($0~/^}/){if(n>150)print FILENAME":"NR-n; in_fn=0}}'`.
4. **Console.log count** unconditional (not inside `if (window.nadocDebug` or `if (import.meta.env.DEV)`)
5. **TODO/FIXME/HACK/XXX count**
6. **Magic-number suspects**: `rg "0\.\d{2,}" file | wc -l` (B-DNA-ish floats); `rg "#[0-9A-Fa-f]{6}" file | wc -l` (hex colors that could be palette constants)
7. **Cross-area imports**: `from '../scene/`, `from '../ui/`, `from '../cadnano-editor/` — boundary leaks per Finding #11
8. **Top-level `window.X = ...` writes** (per Finding #11 globals concern)

## Tagging rubric

Per file, assign one of:

- **`pass`** — small, focused, no signals worth acting on
- **`low`** — small wins (1-2 of: stale TODOs, magic-number candidates, ungated console.logs); not urgent
- **`high`** — at least one of: LOC > 1500, multiple long functions > 150 LOC, ≥ 5 ungated console.logs, ≥ 3 cross-area imports outside the shared-service exemption from Finding #11, cross-layer leak (rare)
- **`pre-tracked`** — already covered by an existing Finding (#6 main.js, #12 animation_endpoints, #13 recent_files, #15 overhang_endpoints, #9 main.js fan-out, etc.). Cite the Finding number.

## Out of scope — do NOT audit these
- `frontend/src/main.js` — Findings #6, #9 already cover it; tagged separately
- `frontend/src/api/client.js` — partial extraction in #12, #13, #15; god-file decomposition is its own active workstream
- `frontend/src/api/{animation,recent_files,overhang}_endpoints.js` — extracted, low LOC
- `frontend/src/api/cadnano-editor/*` only as in scope per §1; no other api files
- `frontend/src/state/store.js`, `frontend/src/constants.js`, `frontend/src/shared/`, `frontend/src/physics/*` — Finding #10 confirmed these are healthy kernels / leaves
- `frontend/src/ui/primitives/*` — barrel module + small primitives; out of scope
- `frontend/src/scene/*.test.js` — test files

## Verification plan

### Pre-state (3× baseline per precondition #1)
```bash
git status > /tmp/08A_dirty_pre.txt
just lint > /tmp/08A_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/08A_lint_pre.txt
for i in 1 2 3; do just test > /tmp/08A_test_pre$i.txt 2>&1; done
for i in 1 2 3; do grep -E '^FAILED|^ERROR' /tmp/08A_test_pre$i.txt | sort > /tmp/08A_baseline$i.txt; done
comm -12 /tmp/08A_baseline1.txt /tmp/08A_baseline2.txt | comm -12 - /tmp/08A_baseline3.txt > /tmp/08A_stable_failures.txt
```

### Audit rhythm
1. Build a script that processes one file at a time, emits a CSV row per file with the 8 signals.
2. Run it across all 81 in-scope files; save raw output to `/tmp/08A_raw_signals.csv`.
3. Apply the tagging rubric programmatically (or by hand if simpler). Save to `/tmp/08A_tagged.csv`.
4. Manually skim the top-10 by LOC + the top-10 by ungated-console.log + any flagged with cross-area imports. Confirm tags by reading the actual file briefly.

### Post-state
```bash
just test > /tmp/08A_test_post.txt 2>&1   # confirm baseline preserved (no code changed)
grep -E '^FAILED|^ERROR' /tmp/08A_test_post.txt | sort > /tmp/08A_post_failures.txt
diff /tmp/08A_stable_failures.txt /tmp/08A_post_failures.txt   # MUST be empty
```

## Stop conditions

- Step 0 CWD assert fails: STOP.
- Test post ≠ pre (you accidentally changed code): revert, stop.
- Any audit finding suggests a Three-Layer-Law violation (physics/scene writes back to topology): STOP, document explicitly, don't try to fix; this is a manager-queue priority-`high` flag.

## Output (worker's final message)

```markdown
## 08-A Frontend comprehensive audit — INVESTIGATED

### CWD-safety check
- Match: yes/no

### Pre-existing dirty state declaration
<git status>

### Findings entry (manager appends to master REFACTOR_AUDIT.md)

### 23. Frontend comprehensive audit — `pass` ✓ INVESTIGATED 2026-05-10
- **Category**: (e) coupling + (c) god-file confirmation; comprehensive audit
- **Move type**: investigation-only
- **Where**: `frontend/src/scene/` (42), `frontend/src/ui/` (32), `frontend/src/cadnano-editor/` (7) = 81 files
- **Diff hygiene**: worktree-used: yes; files-this-refactor-touched: none; other-files: none
- **Per-file tags** (full table follows; ≈ 81 rows):

  | Area | pass | low | high | pre-tracked |
  |---|--:|--:|--:|--:|
  | scene/ | <n> | <n> | <n> | <n> |
  | ui/ | <n> | <n> | <n> | <n> |
  | cadnano-editor/ | <n> | <n> | <n> | <n> |
  | **total** | <N> | <N> | <N> | <N> |

- **Top-5 high-priority candidates for future refactors**:
  1. `<file>` (LOC, signal summary, suggested refactor shape)
  2. ...
  3. ...
  4. ...
  5. ...

- **Three-Layer-Law flags**: <none | list with file:line>
- **Cross-area boundary leaks (post-Pass-3-A re-check)**: <count> (vs Finding #11's 5 baseline)
- **Stale TODO/FIXME debt**: <total count> across <N> files; top contributors: <list>
- **Ungated console.log debt** (outside main.js, which is already tracked): <total count> across <N> files; top contributors: <list>
- **Pre-metric → Post-metric**: 81 NOT SEARCHED files → 81 tagged (pass/low/high/pre-tracked); 0 code change
- **Raw evidence**: `/tmp/08A_raw_signals.csv`, `/tmp/08A_tagged.csv`
- **Linked Findings**: #6, #9, #10, #11, #12, #13, #15

### Per-file tagging table (manager pastes into REFACTOR_AUDIT.md inventory)

```
<full table — file path, LOC, tag, 1-line note. ≈ 81 rows. CSV-ish or markdown table.>
```
```

## Success criteria

- [ ] Step 0 CWD assert passed
- [ ] All 81 in-scope files have a tag (pass/low/high/pre-tracked)
- [ ] Top-5 high-priority candidates named with concrete refactor shape
- [ ] No `frontend/src` code modified
- [ ] Test post-failure set ⊆ stable_baseline ∪ flakes
- [ ] Lint Δ ≤ 0 (no code changed)

## Do NOT
- Modify any code.
- Re-audit `main.js` or `client.js` (separate active workstreams).
- Make recommendations about `_PHASE_*`, `make_bundle_continuation`, or atomistic files (locked / deferred).
- Commit. Append to REFACTOR_AUDIT.md from the worktree.
