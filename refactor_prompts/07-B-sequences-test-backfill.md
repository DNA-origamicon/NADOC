# Refactor 07-B — `backend/core/sequences.py` test backfill

You are a **worker session** in a git worktree. **(test) coverage backfill** — additive (new test file only).

## Pre-read (in order)

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" — note **#1 (3× baseline)** and **#15 (CWD-safety preamble)**
3. `REFACTOR_AUDIT.md` § "Findings" #16 — `sequences.py` flagged at 20.8% coverage as Tier-2 user-facing surface
4. `tests/conftest.py` — for `make_minimal_design()` fixture
5. `backend/core/sequences.py` — read all 12 functions
6. `tests/test_models.py` — for fixture-style precedent
7. This prompt

## Step 0 — CWD safety
```bash
pwd && git rev-parse --show-toplevel
# Both must equal $WORKTREE_PATH; if not STOP and report.
```

## Goal

`backend/core/sequences.py` has 12 functions and 20.8% coverage per Finding #16. Goal: lift to ≥60% by testing the deterministic / pure helpers and the public scaffold/staple sequence assignment functions.

## In scope — function targets

Top priority (pure helpers, low fixture cost):

- `complement_base(base)` (L67) — Watson-Crick complement of a base. Trivial table-lookup. Test all 4 bases + 'N' + invalid input.
- `domain_bp_range(domain)` (L84) — returns the bp range a domain covers. Pure function.
- `_strand_nt_with_skips(strand, ls_map)` (L92) — counts strand nucleotides accounting for loop/skip modifications. Pure.
- `_resolve_scaffold_strand(design, strand_id)` (L110) — picks scaffold strand by id or auto-pick.
- `_build_loop_skip_map(design)` (L75) — builds a (helix_id, bp_index) → delta lookup. Pure.
- `build_scaffold_base_map(design)` (L256) — returns dict mapping `(helix_id, bp_index, direction) → list[base]`.
- `build_scaffold_index_map(design)` (L287) — returns ordered list of `(helix_id, bp_index, direction)` along the scaffold path.

Second priority (orchestrators; medium fixture cost):
- `assign_scaffold_sequence(design, scaffold_name, ...)` (L170) — public; assigns M13mp18 / p7560 / p8064 sequence to scaffold. Test happy path with a small design + the shortest available scaffold; assert sequence applied.
- `assign_custom_scaffold_sequence(design, sequence, ...)` (L214) — public; assigns user-provided sequence. Test sequence-too-short/too-long error paths.
- `assign_staple_sequences(design)` (L316) — public; assigns Watson-Crick complements to staples. Requires scaffold sequence already set.

Skip (file I/O):
- `_load_seq(filename)` (L32) — file I/O. Skip — covered transitively by `assign_scaffold_sequence` if the scaffold names resolve.

Skip (defensive helper used only inside `_do_assign_sequence`):
- `_do_assign_sequence(...)` (L132) — covered transitively by `assign_scaffold_sequence` and `assign_custom_scaffold_sequence`.

## In scope — test file

Write `tests/test_sequences.py` with classes/functions:
- `TestComplementBase` (5–6 tests: A/T/G/C/N cases + invalid)
- `TestDomainBpRange` (1–2 tests on a simple Domain fixture)
- `TestLoopSkipMap` (2 tests: empty design returns empty map; design with one loop_skip returns expected entry)
- `TestStrandNtWithSkips` (2 tests: no skips → matches naive count; with one skip → count differs by delta)
- `TestResolveScaffoldStrand` (2 tests: explicit strand_id → returns it; None → auto-picks the one scaffold)
- `TestBuildScaffoldBaseMap` (1–2 tests: empty scaffold sequence → values are empty lists; with sequence → keys present)
- `TestBuildScaffoldIndexMap` (1 test: ordered list length matches scaffold nt count)
- `TestAssignScaffoldSequence` (2 tests: assigns M13mp18 to a small `make_minimal_design()`-like Design; assert scaffold strand has sequence after; sad path: scaffold-too-long-for-design)
- `TestAssignCustomScaffoldSequence` (2 tests: exact-length custom sequence applies; too-short raises or pads with 'N')
- `TestAssignStapleSequences` (1 test: assigns staple sequences after scaffold sequence is set; assert staples have non-None sequence with correct length)

Use `make_minimal_design()` from `tests/conftest.py` where possible; extend with bp range / scaffold sequence overrides as needed.

## Out of scope

- Modifying `backend/core/sequences.py`. Read-only target.
- Testing the M13mp18 / p7560 / p8064 file loading (file I/O; skip per above).
- Other modules.
- Adding pytest-cov to dev-deps.

## Verification plan

### Pre-state (3× baseline)
```bash
git status > /tmp/07B_dirty_pre.txt
just lint > /tmp/07B_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/07B_lint_pre.txt
for i in 1 2 3; do just test > /tmp/07B_test_pre$i.txt 2>&1; done
for i in 1 2 3; do grep -E '^FAILED|^ERROR' /tmp/07B_test_pre$i.txt | sort > /tmp/07B_baseline$i.txt; done
comm -12 /tmp/07B_baseline1.txt /tmp/07B_baseline2.txt | comm -12 - /tmp/07B_baseline3.txt > /tmp/07B_stable_failures.txt
```

### Implementation rhythm
1. Start with the 3 trivial pure-helper tests (`complement_base`, `domain_bp_range`, `_build_loop_skip_map`). Confirm each passes individually before moving on.
2. Add the strand-counting + scaffold-resolution tests.
3. Add the build_scaffold_*_map tests.
4. Add the orchestrator tests last (most fixture overhead).

### Post-state
```bash
just lint > /tmp/07B_lint_post.txt 2>&1 ; echo "EXIT $?" >> /tmp/07B_lint_post.txt
just test > /tmp/07B_test_post.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/07B_test_post.txt | sort > /tmp/07B_post_failures.txt
diff /tmp/07B_stable_failures.txt /tmp/07B_post_failures.txt   # ⊆ stable_baseline ∪ flakes
uv run pytest --cov=backend.core.sequences --cov-report=term tests/test_sequences.py 2>&1 | grep "sequences" > /tmp/07B_cov_post.txt
```

## Stop conditions

- Step 0 CWD assert fails: STOP.
- A test reveals an apparent bug: document under Apparent-bug flags, do NOT fix the production code.
- Scaffold-loading tests fail because the M13/p7560/p8064 files aren't in the worktree: skip those tests, document as "infrastructure-bound" and ship the rest.

## Output

```markdown
## 07-B sequences.py test backfill — <REFACTORED|UNSUCCESSFUL>

### CWD-safety check (precondition #15)
- Match worktree path: yes/no

### Pre-existing dirty state declaration
<git status>

### Findings entry (manager appends)

### 21. `sequences.py` test backfill — `low` ✓ REFACTORED (test category)
- **Category**: (test) coverage backfill
- **Move type**: additive (new test file)
- **Where**: `tests/test_sequences.py` (new)
- **Pre-metric → Post-metric**:
  - `sequences.py` coverage: 20.8% → <X%>
  - Tests: <pre> → <pre + N>
  - Lint Δ: 0
- **Raw evidence**: `/tmp/07B_*.txt`
- **Linked Findings**: #16 (Tier-2 sequences.py target — closed)
- **Apparent-bug flags**: <list any>
- **Skipped tests**: <list with reason; e.g. M13mp18 file not in worktree>
```

## Success criteria

- [ ] Step 0 CWD assert passed
- [ ] ≥ 15 test functions across ≥ 8 classes/groups
- [ ] Post-coverage `sequences.py` ≥ 60% (target; partial credit if ≥ 40%)
- [ ] No production code modified
- [ ] Test post-failure set ⊆ stable_baseline ∪ flakes
- [ ] Lint Δ ≤ 0

## Do NOT
- Modify `backend/core/sequences.py`.
- Test file I/O (`_load_seq`).
- Add new dev-dependencies.
- Commit. Append to REFACTOR_AUDIT.md from the worktree.
