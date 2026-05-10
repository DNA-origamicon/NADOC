# Audit 10-C — vulture@60 mass-triage + `_advanced_*` cluster status doc

**Worker prompt. INVESTIGATED-only. No code changes expected.**

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (#1, #6 dead-file 3-step + audit-self-ref exemption, #15)
3. `REFACTOR_AUDIT.md` Findings #17 (51 vulture@60 candidates queued for manual review), #22 (`_apply_add_helix` example removal)
4. This prompt

## Step 0 — CWD safety + tooling
```bash
pwd && git rev-parse --show-toplevel
uvx vulture backend --min-confidence 60 > /tmp/10C_vulture.txt 2>&1
wc -l /tmp/10C_vulture.txt
```

## Goal

Two outputs:

### Output A: `_advanced_*` cluster live-status documentation

Pre-flight already confirmed all 9 `_advanced_*` functions in `backend/core/seamed_router.py` are LIVE (called by `auto_scaffold_advanced_seamed` which is called by `crud.py:6045` + tested). Document this finding to close Finding #17's "possibly-dead" flag for these 9 functions.

Quick verification: `rg "auto_scaffold_advanced_seamed" backend tests` should show the call chain.

### Output B: vulture@60 mass-triage

For each candidate in `/tmp/10C_vulture.txt` (~50 entries after filtering decorated symbols):

- **Tag** as: `live-by-test` / `live-by-decorator` / `live-by-string-ref` / `live-by-md-doc` / `confirmed-dead-removable` / `confirmed-dead-but-keep` (e.g. archived prototype)
- For `confirmed-dead-removable`: cite the 4-condition check (precondition #6) — backend refs / tests refs / frontend refs / *.md refs (audit-self-refs exempt)
- For `confirmed-dead-but-keep`: cite the keep-reason (e.g. memory/project_X.md documents intentional preservation)

Use `rg <symbol>` to confirm each tag.

Cap at first 30 if more than 30 unique candidates remain after exclusions.

Recommend ≤ 3 highest-confidence `confirmed-dead-removable` symbols for a future single-symbol-removal pass.

## In scope

- Reading code to confirm tags
- Cross-referencing with `memory/*.md` files
- Tagging each candidate
- Recommending up to 3 for removal

## Out of scope

- Removing any code
- Touching `_PHASE_*`, `make_bundle_continuation`, `linker_relax.py` core
- Atomistic family

## Verification (3× baseline per #1)

Lighter for INVESTIGATED-only: just confirm test suite is unchanged at end (no code modified).

```bash
just test > /tmp/10C_test_pre.txt 2>&1
# (audit work)
just test > /tmp/10C_test_post.txt 2>&1
diff <(grep -E '^FAILED|^ERROR' /tmp/10C_test_pre.txt | sort) <(grep -E '^FAILED|^ERROR' /tmp/10C_test_post.txt | sort)
git diff HEAD --stat   # MUST be empty
```

## Stop conditions

- Step 0 CWD fails → STOP
- More than 50 candidates after decorator filter → cap at 30, document remainder as "uninvestigated; future pass"
- Recommend any removal that would breach precondition #16 (≥5 LOC) → flag, do NOT include in the recommend-≤3 list

## Output (Findings #31)

Two-part Findings entry:

**Part 1: `_advanced_*` cluster status** — closes Finding #17's "possibly-dead" flag for these 9 functions. Documents call chain.

**Part 2: vulture@60 mass-triage table**
| Symbol | File:line | Tag | Confidence | Recommend remove? |
|---|---|---|---|---|
| `_apply_X` | crud.py:NNN | confirmed-dead-removable | 60% | YES (≤5 LOC) |
| `Y` | other.py:NNN | live-by-test | n/a | NO |
| ... |

Plus ≤ 3 highest-confidence removal recommendations with file:line + LOC count + 4-condition cross-check.

Linked Findings: #4 (debug_snippet pattern), #17 (parent audit), #22 (precedent removal).

## Do NOT
- Remove any code
- Modify REFACTOR_AUDIT.md from worktree
