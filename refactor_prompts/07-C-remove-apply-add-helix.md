# Refactor 07-C — Surgical removal of `_apply_add_helix` (Finding #17 follow-up)

You are a **worker session** in a git worktree. Single-symbol dead-code removal. Lowest-risk Pass 7 candidate; the symbol has been independently dead-confirmed by Followup 05-C.

## Pre-read (in order)

1. `CLAUDE.md` — Three-Layer Law
2. `REFACTOR_AUDIT.md` § "Universal preconditions" — note **#1 (3× baseline)**, **#15 (CWD safety)**, and **#6 (dead-file 3-step check)**
3. `REFACTOR_AUDIT.md` § "Findings" #17 — the vulture audit that flagged this; note Followup 05-C's independent confirmation: "agree it's truly unreferenced — only the def line appears in `rg`. Sibling endpoint `add_helix` at line 2870 implements its own inline `_apply` closure"
4. `backend/api/crud.py:2874` — read the function definition + the surrounding 30 lines of context
5. `backend/api/crud.py:2870` — read the sibling `add_helix` route handler to confirm it uses an inline `_apply` closure (NOT calling `_apply_add_helix`)
6. This prompt

## Step 0 — CWD safety (mandatory per precondition #15)

```bash
pwd && git rev-parse --show-toplevel
# Both must equal $WORKTREE_PATH; if not STOP and report.
```

## Goal

Remove `_apply_add_helix` from `backend/api/crud.py:2874`. Independently dead-confirmed (Findings #17 + Followup 05-C). The removal is mechanical IF and ONLY IF the 4-condition removal threshold from Finding #17 still holds at session start.

## In scope

- Re-verify the 4-condition removal threshold (precondition #6 dead-file 3-step check, function-level analog):
  1. **No imports / no callers in `backend/`**: `rg "_apply_add_helix" backend --type py` should return ONLY the definition line at `crud.py:2874`.
  2. **No callers in `tests/`**: `rg "_apply_add_helix" tests --type py` should be empty.
  3. **No callers in `frontend/src/`**: `rg "_apply_add_helix" frontend/src` should be empty.
  4. **No `*.md` documentation references**: `rg "_apply_add_helix" --type md` should be empty.
- If ALL FOUR conditions pass: delete the function (and any leading docstring / immediately-preceding comment that describes only this function). Do NOT delete blank lines that separate it from neighbors — keep file readable.
- If ANY condition fails: STOP, report what was found, do NOT remove.

## Out of scope

- Any other vulture@60 candidate from Finding #17. This prompt is single-symbol.
- Touching the sibling `add_helix` route or its inline `_apply` closure.
- Any other dead-code cleanup.
- Documentation updates beyond the function removal itself.

## Verification plan

### Pre-state (3× baseline per precondition #1)
```bash
git status > /tmp/07C_dirty_pre.txt
just lint > /tmp/07C_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/07C_lint_pre.txt
for i in 1 2 3; do just test > /tmp/07C_test_pre$i.txt 2>&1; done
for i in 1 2 3; do grep -E '^FAILED|^ERROR' /tmp/07C_test_pre$i.txt | sort > /tmp/07C_baseline$i.txt; done
comm -12 /tmp/07C_baseline1.txt /tmp/07C_baseline2.txt | comm -12 - /tmp/07C_baseline3.txt > /tmp/07C_stable_failures.txt
```

### Removal-threshold re-verify
```bash
# 4-condition check (must ALL pass before removal):
echo "=== Condition 1: backend/ refs (expect 1: the def line) ===" 
rg -n "_apply_add_helix" backend --type py
echo "=== Condition 2: tests/ refs (expect 0) ==="
rg -n "_apply_add_helix" tests --type py
echo "=== Condition 3: frontend/src/ refs (expect 0) ==="
rg -n "_apply_add_helix" frontend/src
echo "=== Condition 4: *.md refs (expect 0) ==="
rg -n "_apply_add_helix" --type md
```

### Implementation
1. Read `crud.py:2870-2920` to confirm the sibling `add_helix` route handler uses an inline `_apply` closure (not calling `_apply_add_helix`).
2. Identify the exact line range of `_apply_add_helix` (def line + body + any trailing blank lines that go with it).
3. Use Edit to delete the function. Confirm the surrounding code remains valid Python.
4. Run `just test-file tests/test_lattice.py` (touches lattice/helix paths) to spot any indirect breakage.
5. Run full `just test` — failure set must equal stable_baseline.

### Post-state
```bash
just lint > /tmp/07C_lint_post.txt 2>&1 ; echo "EXIT $?" >> /tmp/07C_lint_post.txt
just test > /tmp/07C_test_post.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/07C_test_post.txt | sort > /tmp/07C_post_failures.txt
diff /tmp/07C_stable_failures.txt /tmp/07C_post_failures.txt   # ⊆ stable_baseline ∪ flakes
wc -l backend/api/crud.py > /tmp/07C_crud_loc_post.txt
rg -c "_apply_add_helix" backend tests frontend/src 2>/dev/null   # expect 0 globally now
```

## Stop conditions

- **Step 0 CWD assert fails**: STOP.
- **Removal-threshold re-verify finds ANY non-definition reference**: STOP, report, do NOT remove. The vulture@60 confidence and Followup 05-C confirmation may have been correct at the time but stale relative to the user's recent work.
- **Test post-failure not in stable_baseline ∪ flakes**: revert the removal, stop. The function may be dynamically referenced (e.g. via `getattr` or a registry) in a way the static checks miss.
- **Sibling `add_helix` at L2870 actually CALLS `_apply_add_helix`**: STOP, report. Followup 05-C may have misread; verify before removing.

## Output (worker's final message)

```markdown
## 07-C `_apply_add_helix` removal — <REFACTORED|UNSUCCESSFUL — held line>

### CWD-safety check (precondition #15)
- Match: yes/no

### Removal-threshold re-verify
- Condition 1 (backend/ refs): <count>
- Condition 2 (tests/ refs): <count>
- Condition 3 (frontend/src/ refs): <count>
- Condition 4 (*.md refs): <count>
- All 4 conditions pass: yes/no

### Sibling-route confirmation
- `add_helix` at crud.py:2870 calls `_apply_add_helix`: yes / NO (inline closure confirmed)

### Pre-existing dirty state declaration
<git status>

### Findings entry (manager appends)

### 22. Surgical removal of `_apply_add_helix` — `low` ✓ REFACTORED (b dead-code)
- **Category**: (b) dead-code — single-symbol removal
- **Move type**: pure deletion
- **Where**: `backend/api/crud.py:2874` (function def removed)
- **Diff hygiene**: worktree-used: yes; files-this-refactor-touched: 1; other-files: none
- **Transparency check**: PASS — sibling `add_helix` route uses inline `_apply` closure; no caller affected
- **API surface added**: none
- **Visibility changes**: none (private symbol removed)
- **Callsites touched**: 0 (no callers existed)
- **Symptom**: vulture@60 candidate; Followup 05-C independently confirmed dead. Removal-threshold 4-condition check at session start: <result>.
- **Why it matters**: dead code creates cognitive friction; readers wonder if `_apply_add_helix` is the canonical helper or whether `add_helix`'s inline closure is.
- **Change**: delete `_apply_add_helix` and its docstring/comment.
- **Effort**: S (~5 min)
- **Three-Layer**: Topological (was a Design-mutation helper, never called)
- **Pre-metric → Post-metric**:
  - crud.py LOC: <pre> → <post> (Δ = − the function's LOC)
  - Tests: baseline-equivalent (no callers existed; no behavior change)
  - Lint Δ: 0 (or ≤ 0)
  - Global `_apply_add_helix` references: 1 → 0
- **Raw evidence**: `/tmp/07C_*.txt`
- **Linked Findings**: #17 (the vulture audit that flagged this); Followup 05-C (independent confirmation)
- **Queued follow-ups**: 50 remaining vulture@60 candidates from Finding #17; manager can dispatch additional single-symbol removal prompts using this prompt as the template.

### Tracker updates
- inventory row for `backend/api/crud.py`: notes update with "Finding #22: removed dead `_apply_add_helix` helper"
```

## Success criteria

- [ ] Step 0 CWD assert passed
- [ ] All 4 removal-threshold conditions re-verified at session start
- [ ] Sibling `add_helix` confirmed to use inline closure (not call `_apply_add_helix`)
- [ ] Function deleted; only `crud.py` modified
- [ ] Test post-failure set ⊆ stable_baseline ∪ flakes
- [ ] Lint Δ ≤ 0
- [ ] Global ripgrep for `_apply_add_helix` returns 0 matches post-removal

## Do NOT

- Remove other vulture@60 candidates "while you're here" — single-symbol scope.
- Touch the sibling `add_helix` route.
- Refactor the inline `_apply` closure pattern.
- Commit. Manager handles git.
- Append to REFACTOR_AUDIT.md from the worktree.
