# Refactor 06-A — PDB import pure-math helpers test backfill

You are a **worker session** in a git worktree. This is a **(test) test-coverage backfill** — pure additive (new test file). No production code changes expected.

## Pre-read (in order)

1. `CLAUDE.md` — Three-Layer Law, DNA-topology rule, tone
2. `REFACTOR_AUDIT.md` § "Universal preconditions"
3. `REFACTOR_AUDIT.md` § "Findings" #16 — the coverage audit that flagged this work as #1 priority (pure-math + lowest fixture cost)
4. `backend/core/pdb_import.py:100-540` — read the 7 target helpers below in full
5. `tests/conftest.py` — see `make_minimal_design()` for fixture-style precedent
6. This prompt

## Goal

`backend/core/pdb_import.py` is at **0% coverage / 529 LOC** (Finding #16's #1 entry). The 7 functions below are pure-math (numpy in / numbers out, no I/O, deterministic). Write `tests/test_pdb_import_geometry.py` with one focused test per function. Target: lift `pdb_import.py` from 0% to ≥30% coverage by exercising these helpers.

## In scope — 7 target functions

| Function | Line | Signature shape | What to test |
|---|--:|---|---|
| `_dihedral(p1, p2, p3, p4) -> float` | 100 | 4 ndarrays → angle in radians | known geometry: collinear → 0, perpendicular planes → π/2, ±π wrap |
| `fit_helix_axis(midpoints)` | 129 | Nx3 ndarray → (origin, direction) | straight z-axis stack → direction ≈ (0,0,1); rotated stack → direction matches rotation; degenerate single-point or co-linear handling if applicable |
| `compute_nucleotide_frame(residue, partner, axis_dir)` | 142 | Residue/partner/axis → (origin, rotation_matrix) | identity case (residue at origin, partner on +x, axis +z) → rotation = identity within tolerance; orthonormality of returned rotation matrix |
| `sugar_pucker_phase(residue)` | 211 | Residue → (P, ν_max, conformation_label) | construct a synthetic C3'-endo residue → label = "C3'-endo"; C2'-endo → label = "C2'-endo"; intermediate phase angle |
| `chi_angle(residue)` | 276 | Residue → χ angle (degrees or radians, check signature) | synthetic anti-conformation → χ ≈ −160°; syn → χ ≈ +60° |
| `analyze_wc_pair(res_fwd, res_rev)` | 359 | (Residue, Residue) → `WCPairGeometry` dataclass | known A·T pair geometry → Watson-Crick distance and angle within tolerance; mismatched pair (e.g. A·G) → flag in result |
| `analyze_duplex(...)` | 537 | duplex residues → analysis dict/dataclass | small 4-bp synthetic duplex → expected per-bp WC geometry, mean rise ≈ 0.34 nm, mean twist ≈ 34° |

## Test fixture strategy

These helpers take BioPython `Residue` objects with atom positions. Two fixture styles to try (in order):

**Style 1 — Synthetic residues (preferred)**: build minimal `Residue`-like objects with the atoms each helper actually reads. The `_dihedral` and `fit_helix_axis` tests need only ndarrays (no Residue at all). The frame/pucker/χ/WC tests need a small set of named atoms. Inspect each helper's body to see which atom names it reads (e.g. `residue["C1'"]`), then build a minimal stub.

**Style 2 — Tiny fixture PDB**: if the synthetic-stub approach gets unwieldy, drop a minimal 2-bp duplex PDB into `tests/fixtures/pdb/` and parse it with `Bio.PDB.PDBParser`. Check if the project already has a fixtures directory. Use a public ideal-B-DNA template (one of the rcsb.org test entries) — but ONLY if you can ship it as a < 5 KB file with no licensing concerns.

**Avoid**:
- Calling out to the `backend/core/pdb_import.py::import_pdb` orchestrator — that's `mixed`-tag in Finding #16, not pure-math, and needs its own fixture-based test in a separate session.
- Mocking `Bio.PDB` at the API level — that's brittle. Either build real `Residue` objects or use a real fixture file.

## Out of scope

- `import_pdb` / `merge_pdb_into_design` orchestrators (separate test session).
- Any change to `backend/core/pdb_import.py` source — read-only target.
- Adding `pytest-cov` to dev-deps.
- Other coverage-low modules.

## Verification plan

### Pre-state
```bash
git status > /tmp/06A_dirty_pre.txt
just lint > /tmp/06A_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/06A_lint_pre.txt
just test > /tmp/06A_test_pre1.txt 2>&1
just test > /tmp/06A_test_pre2.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/06A_test_pre1.txt | sort > /tmp/06A_baseline1.txt
grep -E '^FAILED|^ERROR' /tmp/06A_test_pre2.txt | sort > /tmp/06A_baseline2.txt
comm -12 /tmp/06A_baseline1.txt /tmp/06A_baseline2.txt > /tmp/06A_stable_failures.txt

# Optional: capture pre-coverage for pdb_import.py specifically
uv pip list | grep -iE "pytest.cov" || uv pip install pytest-cov
uv run pytest --cov=backend.core.pdb_import --cov-report=term tests/ 2>&1 | grep "pdb_import" > /tmp/06A_cov_pre.txt
```

### Implementation
1. Open `backend/core/pdb_import.py` and read each of the 7 target functions end-to-end. Note the atom-name dependencies and any non-obvious math.
2. Write `tests/test_pdb_import_geometry.py` with one `class` or one `def test_*` per target function. Keep tests focused — one assertion per concept (e.g. `test_dihedral_collinear`, `test_dihedral_perpendicular`, `test_dihedral_sign_convention`).
3. After EACH function's tests pass: run `just test-file tests/test_pdb_import_geometry.py` to confirm. Then run full `just test` after all 7 to confirm baseline preserved.

### Post-state
```bash
just lint > /tmp/06A_lint_post.txt 2>&1 ; echo "EXIT $?" >> /tmp/06A_lint_post.txt
just test > /tmp/06A_test_post.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/06A_test_post.txt | sort > /tmp/06A_post_failures.txt
diff /tmp/06A_stable_failures.txt /tmp/06A_post_failures.txt   # MUST be empty (the new tests should be in PASSING set)

uv run pytest --cov=backend.core.pdb_import --cov-report=term tests/test_pdb_import_geometry.py 2>&1 | grep "pdb_import" > /tmp/06A_cov_post.txt
```

## Stop conditions

- A target function's body reaches into BioPython parsing in a way that makes synthetic-stub testing impractical AND a tiny fixture PDB isn't available: skip THAT function, document why, ship the rest. Do not block on one function.
- Test post-state shows a NEW failure not in stable_baseline ∪ flakes: revert the offending test, ship the rest, document.
- A test reveals an apparent bug in `pdb_import.py`'s math (e.g. `_dihedral` returns wrong sign): STOP, do NOT fix the production code, write up the discrepancy as a deferred follow-up. Per `feedback_interrupt_before_doubting_user.md`, validate before assuming the helper is wrong.
- BioPython is not installed in the worktree's venv: install via `uv pip install biopython` (project likely already has it).

## Output (final message)

```markdown
## 06-A PDB import pure-math tests — <REFACTORED|UNSUCCESSFUL>

### Pre-existing dirty state declaration
<git status output>

### Findings entry (manager appends to master REFACTOR_AUDIT.md)

### 18. PDB import pure-math test backfill — `low` ✓ REFACTORED (test category)
- **Category**: (test)
- **Move type**: additive (new test file only)
- **Where**: `tests/test_pdb_import_geometry.py` (new)
- **Diff hygiene**: worktree-used: yes; files-this-refactor-touched: 1 (the new test file); other-files: <none | tests/fixtures/pdb/<small.pdb> if used>
- **Transparency check**: not applicable (additive tests; no production code change)
- **API surface added**: none (test file only)
- **Visibility changes**: none
- **Callsites touched**: 0
- **Symptom**: Finding #16 flagged `pdb_import.py` as 0% coverage / 529 LOC / `untested-but-testable`. The pure-math helpers are deterministic and free of I/O — should be tested.
- **Why it matters**: PDB import is a user-facing pipeline (Import → .pdb file load); regressions in helper math would silently corrupt geometry. Tests give a safety net for future refactors / PDB-handling improvements.
- **Change**: 7 test functions covering `_dihedral`, `fit_helix_axis`, `compute_nucleotide_frame`, `sugar_pucker_phase`, `chi_angle`, `analyze_wc_pair`, `analyze_duplex`.
- **Effort**: M (~30-60 min worker time given fixture-construction overhead)
- **Three-Layer**: not applicable (test file)
- **Pre-metric → Post-metric**:
  - `pdb_import.py` coverage: 0% → <X%> (per `/tmp/06A_cov_post.txt`)
  - Tests: <X pass / Y fail / Z err> → <X+N pass / Y fail / Z err>
  - Lint Δ: 0
- **Raw evidence**: `/tmp/06A_*.txt`
- **Linked Findings**: #16 (the coverage audit that surfaced this)
- **Queued follow-ups**: `import_pdb` / `merge_pdb_into_design` orchestrators (Finding #16 #3 priority — needs a small duplex-PDB fixture)
- **Skipped functions** (if any): <list with one-line reason>
- **Apparent-bug flags** (if any): <list any math discrepancies surfaced; do not fix here>

### Tracker updates
- inventory row for `backend/core/pdb_import.py` updated: status `PARTIAL` (was `NOT SEARCHED`), notes "tested by test_pdb_import_geometry.py for 7 pure-math helpers"
```

## Success criteria

- [ ] `tests/test_pdb_import_geometry.py` exists with at least 6 of 7 target functions covered (1 skip allowed if documented)
- [ ] `just test` passes with no NEW failures vs stable_baseline ∪ flakes
- [ ] Post coverage of `pdb_import.py` ≥ 30% (target: cover the 7 helpers' bodies)
- [ ] No production code modified
- [ ] Lint delta ≤ 0
- [ ] If a fixture PDB is added, < 5 KB, public-domain or appropriate license documented in the file's header comment

## Do NOT

- Modify `backend/core/pdb_import.py`. Even if a test surfaces what looks like a bug.
- Test the orchestrators (`import_pdb`, `merge_pdb_into_design`).
- Add new dev-dependencies. `pytest-cov` and `biopython` are project-level concerns.
- Commit. Manager handles git operations.
- Append to `REFACTOR_AUDIT.md` from the worktree.
