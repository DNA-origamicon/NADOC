# Refactor 07-A — PDB orchestrator test backfill (`import_pdb` + `merge_pdb_into_design`)

You are a **worker session** in a git worktree. **(test) coverage backfill** — additive (new test file + small fixture PDB only). No production code changes expected.

## Pre-read (in order)

1. `CLAUDE.md` — Three-Layer Law, DNA-topology rule
2. `REFACTOR_AUDIT.md` § "Universal preconditions" — note **#1 (3× baseline runs)** and **#15 (CWD-safety preamble — `pwd && git rev-parse --show-toplevel` first)**
3. `REFACTOR_AUDIT.md` § "Findings" #16 (coverage audit; this is its #3 priority follow-up) and #18 (PDB pure-math tests; reuse the inline-PDB-writer pattern)
4. `tests/test_pdb_import_geometry.py` — specifically `_write_synthetic_duplex_pdb` and `TestAnalyzeDuplex` — your starting template for fixture construction
5. `backend/core/pdb_to_design.py:438` (`import_pdb`) and `:675` (`merge_pdb_into_design`)
6. This prompt

## Step 0 — CWD safety (mandatory, per precondition #15)

```bash
pwd
git rev-parse --show-toplevel
# Both should equal $WORKTREE_PATH. If not, STOP and report.
```

## Goal

`import_pdb` and `merge_pdb_into_design` are orchestrators in `backend/core/pdb_to_design.py` (~347 LOC at 0% coverage per Finding #16). Both are user-facing entry points (Import → .pdb file). Goal: write `tests/test_pdb_to_design.py` with end-to-end tests that exercise both orchestrators against a synthetic duplex PDB.

Target: lift `pdb_to_design.py` from 0% to ≥40% coverage by exercising the happy paths.

## In scope

- Create `tests/test_pdb_to_design.py` with at least these test functions:
  - `test_import_pdb_single_duplex_returns_valid_design` — write a 4–8 bp synthetic AT/GC duplex PDB inline (reuse / adapt `_write_synthetic_duplex_pdb` from `test_pdb_import_geometry.py`); call `import_pdb(<path>)`; assert returned `Design` has 2 helices (one fwd, one rev) OR 1 helix with two strands depending on what the helper produces; bp count matches PDB length; scaffold/staple roles assigned.
  - `test_import_pdb_round_trip_bp_count` — load the synthetic PDB, count bp on both helices, assert equal to input length.
  - `test_merge_pdb_into_design_appends_to_existing` — start with a `make_minimal_design()` from `tests/conftest.py`; call `merge_pdb_into_design(existing_design, <path>)`; assert original helices preserved + new helices added; total bp count = original + imported.
  - `test_merge_pdb_into_design_preserves_existing_strand_ids` — confirm existing strand IDs unchanged after merge.
  - At least 1 sad-path: `test_import_pdb_invalid_path_raises` (FileNotFoundError or similar) OR `test_import_pdb_single_strand_pdb_raises_or_warns` (insufficient duplex residues).
- Optionally: 1–2 fixture PDBs in `tests/fixtures/pdb/` if the inline-writer approach gets unwieldy. Each < 10 KB. Document the source/license in a header comment.

## Out of scope

- Modifying `backend/core/pdb_to_design.py` source — read-only target.
- Testing `_detect_wc_pairs`, `_segment_duplexes`, `_rotation_between` (private helpers; bring up if a test naturally exercises them, but don't write dedicated tests — they're flagged as "pure" in Finding #16 and could be a separate session).
- Testing the chi/sugar/dihedral helpers — those are covered by Finding #18.
- Adding `pytest-cov` or `biopython` to dev-deps.
- Other coverage-low modules.

## Verification plan

### Pre-state (3 baseline runs per precondition #1)
```bash
git status > /tmp/07A_dirty_pre.txt
just lint > /tmp/07A_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/07A_lint_pre.txt
for i in 1 2 3; do just test > /tmp/07A_test_pre$i.txt 2>&1; done
for i in 1 2 3; do grep -E '^FAILED|^ERROR' /tmp/07A_test_pre$i.txt | sort > /tmp/07A_baseline$i.txt; done
# Stable baseline = intersection of all 3
comm -12 /tmp/07A_baseline1.txt /tmp/07A_baseline2.txt | comm -12 - /tmp/07A_baseline3.txt > /tmp/07A_stable_failures.txt
# Flake set = anything in any baseline NOT in all 3
sort -u /tmp/07A_baseline1.txt /tmp/07A_baseline2.txt /tmp/07A_baseline3.txt | comm -23 - /tmp/07A_stable_failures.txt > /tmp/07A_flakes.txt
```

### Implementation rhythm
1. Read `import_pdb` and `merge_pdb_into_design` end-to-end. Note: input parameters, return type, side effects, error paths.
2. Adapt `_write_synthetic_duplex_pdb` from `test_pdb_import_geometry.py` (it's currently inside a `TestAnalyzeDuplex` helper — extract or copy).
3. Write each test function in order; run `just test-file tests/test_pdb_to_design.py` after each pair to catch issues early.
4. After all tests pass: full `just test` to confirm baseline preserved.

### Post-state
```bash
just lint > /tmp/07A_lint_post.txt 2>&1 ; echo "EXIT $?" >> /tmp/07A_lint_post.txt
just test > /tmp/07A_test_post.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/07A_test_post.txt | sort > /tmp/07A_post_failures.txt
diff /tmp/07A_stable_failures.txt /tmp/07A_post_failures.txt   # expected: empty (post ⊆ stable_baseline ∪ flakes)
uv run pytest --cov=backend.core.pdb_to_design --cov-report=term tests/test_pdb_to_design.py 2>&1 | grep "pdb_to_design" > /tmp/07A_cov_post.txt
```

## Stop conditions

- Worker writes outside `tests/` or `tests/fixtures/`: revert, stop.
- A test exposes what looks like a bug in `pdb_to_design.py`: STOP, do NOT fix the production code, document under "Apparent-bug flags". Per `feedback_interrupt_before_doubting_user.md`, the user is the biophysicist; the math is calibrated.
- BioPython parser fails on the synthetic PDB: try a fixture file from rcsb.org (small, public domain) or document and skip the affected test.
- Step 0 CWD assert fails: STOP and report.

## Output (worker's final message)

```markdown
## 07-A PDB orchestrator tests — <REFACTORED|UNSUCCESSFUL>

### CWD-safety check (precondition #15)
- pwd: <output>
- git rev-parse --show-toplevel: <output>
- Match worktree path: yes

### Pre-existing dirty state declaration
<git status output>

### Findings entry (manager appends to master REFACTOR_AUDIT.md)

### 20. PDB orchestrator test backfill — `low` ✓ REFACTORED (test category)
- **Category**: (test) — coverage backfill
- **Move type**: additive (new test file; optional fixture PDB)
- **Where**: `tests/test_pdb_to_design.py` (new); optionally `tests/fixtures/pdb/<small.pdb>`
- **Diff hygiene**: worktree-used: yes; files-this-refactor-touched: <1 or 2>
- **API surface added**: none
- **Visibility changes**: none
- **Pre-metric → Post-metric**:
  - `pdb_to_design.py` coverage: 0% → <X%>
  - Tests: <pre> → <pre + N>
  - Lint Δ: 0
- **Raw evidence**: `/tmp/07A_*.txt`, `/tmp/07A_cov_post.txt`
- **Linked Findings**: #16 (Tier-2 #3 priority — closed)
- **Apparent-bug flags**: <list any>

### Tracker updates
- inventory row for `backend/core/pdb_to_design.py`: NOT SEARCHED → PARTIAL
```

## Success criteria

- [ ] Step 0 CWD assert passed
- [ ] `tests/test_pdb_to_design.py` has ≥ 5 test functions
- [ ] Post-coverage of `pdb_to_design.py` ≥ 40%
- [ ] No production code modified
- [ ] Lint Δ ≤ 0
- [ ] Test post-failure set ⊆ stable_baseline ∪ flakes
- [ ] Findings entry written for manager

## Do NOT
- Modify `backend/core/pdb_to_design.py`. Even for an "obvious" bugfix.
- Touch other coverage-low modules.
- Add new dev-dependencies.
- Commit. Manager handles git.
- Append to REFACTOR_AUDIT.md from the worktree.
