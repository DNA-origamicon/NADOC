# Refactor 10-A — `namd_package.py` pure-helper extraction + tests

**Worker prompt. Template: same shape as Finding #27 (09-B `gromacs_helpers.py`).**

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (#1, #15, #16, #19, #20, #21)
3. `REFACTOR_AUDIT.md` Findings #27 (09-B reference implementation; mirror that template)
4. `backend/core/namd_package.py:1-280` — read functions in full
5. `backend/core/gromacs_helpers.py` — see the structural pattern

## Step 0 — CWD safety
```bash
pwd && git rev-parse --show-toplevel
```

## Goal

`backend/core/namd_package.py` (882 LOC, 0% coverage) has 9 functions; pre-flight confirmed **no `subprocess`/`os.system`/`Path.read/write_text` imports** at module level. Identify pure-text helpers + extract them to `backend/core/namd_helpers.py` + add `tests/test_namd_helpers.py`.

## Candidate functions (worker confirms purity from bodies)

- `complete_psf(design)` — likely pure, builds PSF text from a Design
- `_complete_psf_from_stub(stub)` — pure, transforms PSF stub text
- `get_ai_prompt(design)` — pure, builds a prompt string
- `_render_namd_conf(name)` — likely pure, renders a NAMD config template

Confirm each is pure (no I/O); skip `build_namd_package` (likely orchestrator) and `_check_ff_files` (file I/O) and `main` (CLI).

## In scope

Move the confirmed pure helpers (target ≥ 3 of the 4 above, possibly 4) verbatim to `backend/core/namd_helpers.py` + any module-private constants they reference. Re-import in `namd_package.py` with `# noqa: F401` only if needed for back-compat. Add `tests/test_namd_helpers.py` with ≥ 8 tests.

## Out of scope

- `build_namd_package`, `_check_ff_files`, `main` (orchestrator / I/O)
- Other modules
- `pyproject.toml`

## Verification (3× baseline per #1)
```bash
for i in 1 2 3; do just test > /tmp/10A_test_pre$i.txt 2>&1; done
for i in 1 2 3; do grep -E '^FAILED|^ERROR' /tmp/10A_test_pre$i.txt | sort > /tmp/10A_baseline$i.txt; done
comm -12 /tmp/10A_baseline1.txt /tmp/10A_baseline2.txt | comm -12 - /tmp/10A_baseline3.txt > /tmp/10A_stable_failures.txt
just lint > /tmp/10A_lint_pre.txt 2>&1
```
Post-state: re-run lint + test; diff post failures vs stable_baseline; coverage check on namd_helpers.py.

## Stop conditions
- Step 0 fails → STOP
- Any target function uses subprocess/os/pathlib I/O → STOP, reduce scope
- Test post-failure not in stable_baseline ∪ flakes → revert, STOP
- ≥ 5 LOC change to anything outside the 3 target files → STOP

## Output (Findings #29)

Same shape as Finding #27. Required fields:
- Move type: verbatim (N functions)
- LOC delta on namd_package.py
- namd_helpers.py size + coverage
- Tests added count
- Lint Δ
- Pure-helper claim verified (no I/O imports)
- Linked: #27 (template), #16, #24

## Do NOT
- Touch namd-spawning core
- Commit / append to REFACTOR_AUDIT.md from worktree
