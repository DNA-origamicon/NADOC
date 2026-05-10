# Audit 08-B — Backend non-atomistic comprehensive audit

You are a **worker session** in a git worktree. **INVESTIGATED-only.** Output: per-file refactor priority tags + top-5 high-priority candidates. **No code changes.**

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions"
3. `REFACTOR_AUDIT.md` § "Findings" #16 (coverage audit), #17 (vulture@60 nominations), #14 (F401 cleanup), #19 (`_overhang_junction_bp` extension)
4. **`memory/feedback_phase_constants_locked.md`** — `_PHASE_*` constants in `lattice.py` are **locked**; do NOT recommend changes
5. This prompt

## Step 0 — CWD safety
```bash
pwd && git rev-parse --show-toplevel
```

## Goal

Tag every NOT SEARCHED file in `backend/api/`, `backend/core/` (excluding atomistic files — see "Out of scope"), `backend/parameterization/`, `backend/physics/` with a refactor priority. Total ≈ 38 files (after exclusions). Surface top-5 highest-priority candidates.

## Out of scope — explicit DEFERRED files

Per user directive 2026-05-09, the atomistic calibration workstream lives on user's other PC. Do NOT audit, recommend changes to, or surface candidates from:

- `backend/core/atomistic.py`
- `backend/core/atomistic_to_nadoc.py`
- `backend/core/cg_to_atomistic.py`

Mark these as `DEFERRED` in your output and skip the signal scan.

Also out of scope:
- `backend/core/lattice.py` `_PHASE_*` constants and `make_bundle_continuation` (locked / fragile per LESSONS.md)
- `backend/core/linker_relax.py` `bridge_axis_geometry`, `_optimize_angle`, relax-loss internals (user actively iterating; recent commits 5b432da, 7d8e093)
- Files already covered in Findings #16, #17, #18, #20, #21:
  - `backend/core/pdb_import.py` (Finding #18; coverage 64%)
  - `backend/core/pdb_to_design.py` (Finding #20; coverage 81%)
  - `backend/core/sequences.py` (Finding #21; coverage 97%)
  - `backend/core/staple_routing.py` (Finding #16: tagged `possibly-dead`; documented disabled)
  Cite these as `pre-tracked`.

## In scope — heuristic signals

For each file:

1. **LOC** + **function count**
2. **Long-function presence** (≥ 200 LOC) — Python AST parse:
   ```python
   import ast; tree = ast.parse(open(p).read())
   for node in ast.walk(tree):
       if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
           end = max(getattr(c,'end_lineno',node.lineno) for c in ast.walk(node))
           if end - node.lineno >= 200: print(f'{p}:{node.lineno}:{node.name}:{end-node.lineno+1}')
   ```
3. **Cyclomatic complexity** ≥ C grade: `uvx radon cc -nC <file>`
4. **TODO/FIXME/HACK/XXX count**
5. **Magic-number suspects**: hardcoded floats outside `_PHASE_*`/B-DNA constants. Heuristic: `rg "\b\d+\.\d{2,}" <file>` minus references to `BDNA_*`, `HELIX_RADIUS`, `0\.334`, etc.
6. **Coverage** (if `pytest-cov` installed): per-file coverage % via `uv run coverage report --include=<file>`
7. **Three-Layer-Law canary**: physics or core/geometry writing to `Design.strands` mutators
8. **Dead-function suspects** beyond Finding #17: `uvx vulture <file> --min-confidence 70`

## Tagging rubric

Same as 08-A:
- **`pass`** — no signals worth acting on
- **`low`** — small wins available
- **`high`** — LOC > 1500, or 1+ function ≥ 300 LOC, or radon CC ≥ D grade in any function, or coverage < 30%, or Three-Layer-Law violation
- **`pre-tracked`** — covered by an existing Finding (cite #)
- **`DEFERRED`** — atomistic family per above

## Verification plan

### Pre-state (3× baseline)
```bash
for i in 1 2 3; do just test > /tmp/08B_test_pre$i.txt 2>&1; done
for i in 1 2 3; do grep -E '^FAILED|^ERROR' /tmp/08B_test_pre$i.txt | sort > /tmp/08B_baseline$i.txt; done
comm -12 /tmp/08B_baseline1.txt /tmp/08B_baseline2.txt | comm -12 - /tmp/08B_baseline3.txt > /tmp/08B_stable_failures.txt
```

### Audit rhythm
1. Generate `/tmp/08B_raw_signals.csv` covering ≈ 38 in-scope files.
2. Apply tagging rubric.
3. Skim top-10 by LOC + any flagged radon CC ≥ D + any with coverage < 30%.
4. Confirm Three-Layer-Law canary returned 0 hits (or document each).

### Post-state
```bash
just test > /tmp/08B_test_post.txt 2>&1
diff <(grep -E '^FAILED|^ERROR' /tmp/08B_test_post.txt | sort) /tmp/08B_stable_failures.txt   # ⊆ stable_baseline ∪ flakes
```

## Stop conditions

- Step 0 CWD fail: STOP.
- Three-Layer-Law violation found: STOP, document explicitly, do NOT recommend a fix here (heightened-scrutiny path).
- Audit suggests touching `_PHASE_*` or `make_bundle_continuation`: STOP and document; per `feedback_phase_constants_locked.md` these need explicit user approval.

## Output

```markdown
## 08-B Backend non-atomistic audit — INVESTIGATED

### CWD-safety check
- Match: yes/no

### Pre-existing dirty state declaration
<git status>

### Findings entry (manager appends)

### 24. Backend non-atomistic comprehensive audit — `pass` ✓ INVESTIGATED 2026-05-10
- **Category**: comprehensive audit
- **Move type**: investigation-only
- **Where**: `backend/api/` (~7), `backend/core/` (~17 after exclusions), `backend/parameterization/` (~7), `backend/physics/` (~4) = ~35 files
- **Per-area tag table**:

  | Area | pass | low | high | pre-tracked | DEFERRED |
  |---|--:|--:|--:|--:|--:|
  | api/ | <n> | <n> | <n> | <n> | 0 |
  | core/ | <n> | <n> | <n> | <n> | 3 |
  | parameterization/ | <n> | <n> | <n> | <n> | 0 |
  | physics/ | <n> | <n> | <n> | <n> | 0 |
  | **total** | <N> | <N> | <N> | <N> | 3 |

- **Top-5 high-priority candidates**:
  1. `<file>` (LOC, primary signal, suggested refactor)
  ...

- **Three-Layer-Law flags**: <none | list>
- **Coverage gaps surfaced** (uncovered modules > 200 LOC): <list>
- **Long-function flags** (≥ 300 LOC): <list with file:line:name:loc>
- **Pre-metric → Post-metric**: 38 NOT SEARCHED → 38 tagged; 0 code change
- **Raw evidence**: `/tmp/08B_*.csv`, `/tmp/08B_*.txt`
- **Linked Findings**: #14, #16, #17, #18, #19, #20, #21

### Per-file tagging table (manager pastes into REFACTOR_AUDIT.md inventory)

<full table>
```

## Success criteria

- [ ] Step 0 passed
- [ ] All in-scope files tagged
- [ ] 3 atomistic files marked DEFERRED
- [ ] Top-5 candidates named
- [ ] No code modified
- [ ] Test post ⊆ stable_baseline ∪ flakes

## Do NOT

- Modify any code.
- Audit atomistic files.
- Recommend `_PHASE_*` or `make_bundle_continuation` changes.
- Commit. Append to REFACTOR_AUDIT.md from the worktree.
