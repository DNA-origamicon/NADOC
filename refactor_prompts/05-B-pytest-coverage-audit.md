# Refactor 05-B — Backend test-coverage audit (`pytest --cov`)

You are a **worker session** in a git worktree. This is an **INVESTIGATED**-only task — produce a Findings entry classifying coverage gaps. Code changes are not expected.

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (#1 baseline-twice, #2 lint-delta-stable, #9 clean-tree)
3. `REFACTOR_AUDIT.md` § "Roles" — you are running an investigation; no merge expected
4. `REFACTOR_AUDIT.md` § "Findings" #8 (the 03-A coupling audit) — your reference for INVESTIGATED-shape Findings entries
5. This prompt

## Goal

Produce a coverage report for `backend/` and surface the 5 lowest-coverage modules as a Findings entry. The output is informational; future passes can target those modules with focused tests. No code changes.

## In scope

- Install `pytest-cov` if not already present: `uv pip install pytest-cov`. (One-time tooling install in the worktree's venv; the user's main venv is unaffected when worktree is removed because `.venv` is shared via git's worktree mechanism. **Caveat**: this DOES affect the main venv. If `pytest-cov` is already installed system-wide, skip the install.)
- Run: `uv run pytest --cov=backend --cov-report=term-missing --cov-report=json:/tmp/05B_cov.json tests/ 2>&1 | tee /tmp/05B_cov_full.txt`
- Parse the report; surface the 5 modules with lowest coverage percentage (excluding modules with 0% coverage that are actually orchestration / `__main__` shells — flag those separately).
- Spot-check the lowest-coverage module: read its source briefly, judge whether the gap is "untested code that has bugs" vs "code that's hard to test (file I/O, GROMACS, etc.)" vs "dead code that should be removed."

## Out of scope

- Writing new tests. The output is a *plan*, not a test.
- Adding a coverage gate to CI / changing project config.
- Coverage of `frontend/`. JS coverage tooling is a different problem.
- Modifying `pyproject.toml` to add `pytest-cov` as a dev-dependency. This is a one-time investigation tool.

## Verification plan

### Pre-state capture
```bash
git status > /tmp/05B_dirty_pre.txt
just lint > /tmp/05B_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/05B_lint_pre.txt
just test > /tmp/05B_test_pre1.txt 2>&1
just test > /tmp/05B_test_pre2.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/05B_test_pre1.txt | sort > /tmp/05B_baseline1.txt
grep -E '^FAILED|^ERROR' /tmp/05B_test_pre2.txt | sort > /tmp/05B_baseline2.txt
comm -12 /tmp/05B_baseline1.txt /tmp/05B_baseline2.txt > /tmp/05B_stable_failures.txt
```

### Investigation
```bash
# Install pytest-cov (skip if already present)
uv pip list | grep -iE "pytest.cov|coverage" || uv pip install pytest-cov

# Run with both terminal and JSON reports
uv run pytest --cov=backend --cov-report=term-missing --cov-report=json:/tmp/05B_cov.json tests/ 2>&1 | tee /tmp/05B_cov_full.txt

# Extract per-file coverage from the JSON
uv run python -c "
import json
data = json.load(open('/tmp/05B_cov.json'))
files = data['files']
ranked = sorted(files.items(), key=lambda kv: kv[1]['summary']['percent_covered'])
print('=== 15 lowest-coverage modules ===')
for path, info in ranked[:15]:
    pct = info['summary']['percent_covered']
    cov = info['summary']['covered_lines']
    total = info['summary']['num_statements']
    print(f'{pct:5.1f}%  {cov:4d}/{total:<4d}  {path}')
print()
print('=== Whole-suite ===')
print(f'  lines covered: {data[\"totals\"][\"covered_lines\"]}/{data[\"totals\"][\"num_statements\"]}')
print(f'  branches:      {data[\"totals\"][\"covered_branches\"]}/{data[\"totals\"][\"num_branches\"]}' if data['totals'].get('num_branches') else '  (no branch coverage)')
print(f'  total %:       {data[\"totals\"][\"percent_covered\"]:.1f}%')
" > /tmp/05B_cov_summary.txt
cat /tmp/05B_cov_summary.txt
```

### Classify the 5 lowest-coverage modules

For each, briefly skim the source and tag it:

- **untested-but-testable**: code that should have tests; gap is a real risk. List 1-2 specific functions/methods that look most important to test.
- **hard-to-test**: side-effecting (filesystem, network, GROMACS / NAMD subprocess, mrdna). Note what the test would need (mock, integration env, fixture data).
- **possibly-dead**: code that may not be reachable from any production path. Cross-reference with Pass 4's F401 output — if the module is mostly unused, that's a dead-code candidate for a later pass.
- **mixed**: some functions need tests; others are hard-to-test. Split the recommendation.

### Post-state capture
```bash
just test > /tmp/05B_test_post.txt 2>&1   # confirm baseline preserved (you didn't change code)
grep -E '^FAILED|^ERROR' /tmp/05B_test_post.txt | sort > /tmp/05B_post_failures.txt
diff /tmp/05B_stable_failures.txt /tmp/05B_post_failures.txt   # must be empty (no code changed)
```

## Stop conditions

- `pytest-cov` install fails: try alternatives (`coverage` package, manual sys.settrace) or stop and report.
- Coverage run takes > 10 minutes: kill, sample a subset of `tests/`, document.
- Test post-state ≠ pre-state: you accidentally changed code; revert.

## Output (worker's final message)

```markdown
## 05-B Backend coverage audit — INVESTIGATED

### Pre-existing dirty state declaration
<git status output at session start>

### Tooling note
- pytest-cov installed: <yes pre-existing | yes installed-now | no using-fallback>

### Findings entry (manager appends to master REFACTOR_AUDIT.md)

### 16. Backend test-coverage audit — `pass` ✓ INVESTIGATED
- **Category**: (test) — coverage gap analysis
- **Move type**: investigation-only
- **Where**: `backend/` (whole tree)
- **Diff hygiene**: worktree-used: yes; files-this-refactor-touched: none; other-files: none
- **Transparency check**: not applicable (no code change)
- **API surface added**: none
- **Visibility changes**: none
- **Callsites touched**: 0
- **Symptom**: backend coverage was unknown before this audit; never measured.
- **Whole-suite coverage**: <X.Y%> ; lines covered <C>/<T>
- **5 lowest-coverage modules**:
  | Rank | Module | % | Lines | Tag | Note |
  |---|---|--:|---|---|---|
  | 1 | <path> | <X%> | <c>/<t> | <untested-but-testable | hard-to-test | possibly-dead | mixed> | <1 line about specific functions> |
  | 2 | … | … | … | … | … |
  | 3 | … | … | … | … | … |
  | 4 | … | … | … | … | … |
  | 5 | … | … | … | … | … |
- **Why it matters**: untested code accumulates correctness debt invisibly; this is the first map of where the safety net has holes.
- **Change**: documented; not implemented
- **Implementation deferred**: each "untested-but-testable" entry is a candidate for a focused test-writing prompt in a future pass. "hard-to-test" entries may need fixture investment first.
- **Effort**: S (audit only, ~15 min)
- **Three-Layer**: not applicable
- **Pre-metric → Post-metric**: <X.Y%> → <X.Y%> (no change; baseline measurement)
- **Raw evidence**: `/tmp/05B_cov.json`, `/tmp/05B_cov_summary.txt`, `/tmp/05B_cov_full.txt`
- **Linked Findings**: #14 (F401 cleanup may have removed truly-dead imports that were dragging modules into the coverage denominator)
- **Queued follow-ups**: write tests for the 1-2 highest-risk "untested-but-testable" modules (manager picks based on which areas the user is actively touching).
```

## Success criteria

- [ ] `/tmp/05B_cov.json` and `/tmp/05B_cov_summary.txt` exist with valid output
- [ ] 5 lowest-coverage modules each tagged with one of the 4 categories
- [ ] Whole-suite coverage % reported
- [ ] No code changed: `git diff HEAD --stat` empty (or only `pyproject.toml` if pytest-cov needed adding to dev-deps — flag if so)
- [ ] Findings entry uses INVESTIGATED status

## Do NOT

- Write tests.
- Edit project source.
- Add CI gates.
- Commit. Append to REFACTOR_AUDIT.md from worktree.
