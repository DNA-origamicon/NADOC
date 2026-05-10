# Refactor 08-C — Fix `make_minimal_design()` REVERSE-staple convention bug

You are a **worker session** in a git worktree. Small, well-bounded fixture-bug fix surfaced by Followup 07-B.

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" — note **#1 (3× baseline)** and **#15 (CWD safety)**
3. `REFACTOR_AUDIT.md` § "Findings" #21 + Followup 07-B for the bug context (the queued backlog item)
4. `tests/conftest.py:1-90` — read `make_minimal_design()` fully
5. `backend/core/sequences.py:84-95` — read `domain_bp_range()` to understand the convention
6. `backend/core/models.py` — read `Domain` and `Direction` to confirm field shapes
7. This prompt

## Step 0 — CWD safety
```bash
pwd && git rev-parse --show-toplevel
```

## Goal

Fix the documented-but-unenforced convention drift in `tests/conftest.py::make_minimal_design()`. The REVERSE staple is currently built as `start_bp=0, end_bp=helix_length_bp-1, direction=REVERSE`, which violates `sequences.py`'s documented "REVERSE: start_bp > end_bp" convention. As a result, `domain_bp_range()` returns an empty iterator for it.

After fix: REVERSE staple uses `start_bp=helix_length_bp-1, end_bp=0, direction=REVERSE`. Run full suite to surface any tests that were silently relying on the empty-iterator behavior — those are second-order bugs that need addressing.

## In scope

- `tests/conftest.py::make_minimal_design()` — flip the REVERSE staple's `start_bp` and `end_bp` to follow the documented convention.
- Update the helper's docstring to explicitly cite the convention.
- Run full `just test` and observe failures.
- For each NEW failure surfaced (not in stable_baseline), classify:
  - **silent-reliance**: the test was using `make_minimal_design()` for a topological scenario where it accidentally needed the REVERSE staple to span 0-bp. Update the test to either build its own staple (worker's 07-B `_design_with_proper_reverse_staple`-style helper) or use the new convention. Document each such test in the Findings entry.
  - **real bug exposed by fix**: the production code under test was always wrong; just surfaced by the fixture fix. STOP, document under "Apparent-bug flags" — do NOT fix the production code in this session.
- Goal: zero NEW test failures after fix; the 2-3 likely silent-reliance tests are updated in this same session.

## Out of scope

- Modifying `backend/core/sequences.py` or `backend/core/models.py`.
- Adding new fixture variants beyond the fix.
- Any other test backfill.

## Verification plan

### Pre-state (3× baseline)
```bash
git status > /tmp/08C_dirty_pre.txt
just lint > /tmp/08C_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/08C_lint_pre.txt
for i in 1 2 3; do just test > /tmp/08C_test_pre$i.txt 2>&1; done
for i in 1 2 3; do grep -E '^FAILED|^ERROR' /tmp/08C_test_pre$i.txt | sort > /tmp/08C_baseline$i.txt; done
comm -12 /tmp/08C_baseline1.txt /tmp/08C_baseline2.txt | comm -12 - /tmp/08C_baseline3.txt > /tmp/08C_stable_failures.txt
```

### Implementation rhythm
1. Open `tests/conftest.py`. Locate the REVERSE staple construction.
2. Flip `start_bp` and `end_bp`. Update docstring.
3. Run `just test`. Capture failures.
4. For each NEW failure: read the test body. Decide silent-reliance vs apparent-bug. Update silent-reliance tests inline.
5. Re-run `just test`. Iterate until post-failure-set ⊆ stable_baseline ∪ flakes.

### Post-state
```bash
just lint > /tmp/08C_lint_post.txt 2>&1 ; echo "EXIT $?" >> /tmp/08C_lint_post.txt
just test > /tmp/08C_test_post.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/08C_test_post.txt | sort > /tmp/08C_post_failures.txt
diff /tmp/08C_stable_failures.txt /tmp/08C_post_failures.txt   # MUST be empty
```

## Stop conditions

- Step 0 fails: STOP.
- More than 6 silent-reliance tests surface: STOP, scope is bigger than this prompt anticipated; report what you've found and let the manager re-scope.
- An "apparent-bug exposed by fix" surfaces: STOP, do NOT fix production code; document under "Apparent-bug flags" with the test's signal and let the manager queue a separate bug-debug session.
- Fix touches `backend/core/`: revert and stop. Out of scope.

## Output (worker's final message)

```markdown
## 08-C make_minimal_design REVERSE-staple fix — <REFACTORED|UNSUCCESSFUL>

### CWD-safety check
- Match: yes/no

### Pre-existing dirty state declaration
<git status>

### Findings entry (manager appends)

### 25. `make_minimal_design()` REVERSE-staple convention fix — `low` ✓ REFACTORED
- **Category**: (test) — fixture correctness
- **Move type**: targeted fix + N silent-reliance migrations
- **Where**: `tests/conftest.py::make_minimal_design()` (REVERSE staple direction flip + docstring); + N test files where silent-reliance was found
- **Diff hygiene**: worktree-used: yes; files-this-refactor-touched: <1 + N>
- **Transparency check**: not applicable (test-fixture behavior change)
- **API surface added**: none (signature unchanged)
- **Visibility changes**: none
- **Symptom**: documented "REVERSE: start_bp > end_bp" convention in `sequences.py:84-89` was unenforced in the shared `make_minimal_design()` test fixture. `domain_bp_range()` returned empty iterator for the REVERSE staple. Discovered by Followup 07-B's audit of `tests/test_sequences.py`.
- **Why it matters**: latent bug landmine for any test of staple-pairing, scaffold-staple coverage, or strand-nt accounting on this fixture; would silently produce 0-nucleotide staple traversal without error.
- **Change**: flip `start_bp` and `end_bp` in REVERSE-staple construction; update fixture docstring to cite the convention.
- **Silent-reliance tests updated** (none if 0):
  - `<test path>` — <one-line description of how the test was relying on the broken behavior, and how it's now fixed>
  - ...
- **Effort**: S (~10-30 min depending on silent-reliance count)
- **Three-Layer**: not applicable (test infrastructure)
- **Pre-metric → Post-metric**:
  - Test pass count: <pre> → <post>
  - Failure-set: stable_baseline ∪ flakes preserved
  - Silent-reliance migrations: <N>
- **Raw evidence**: `/tmp/08C_*.txt`
- **Linked Findings**: #21 (Followup 07-B's surfaced backlog item)
- **Apparent-bug flags**: <none | list with test:line and the production-code signal>
```

## Success criteria

- [ ] Step 0 passed
- [ ] `make_minimal_design()` REVERSE staple uses `start_bp > end_bp`
- [ ] Docstring updated to cite the convention
- [ ] Test post-failure set ⊆ stable_baseline ∪ flakes
- [ ] No `backend/core/` modification
- [ ] Lint Δ ≤ 0
- [ ] Each silent-reliance test updated inline (or the prompt re-scoped if > 6)

## Do NOT
- Modify `backend/core/sequences.py`, `backend/core/models.py`, or any production code.
- Add new fixture variants.
- Commit. Append to REFACTOR_AUDIT.md from the worktree.
