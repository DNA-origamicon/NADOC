# Refactor 02-B — Extract `make_minimal_design()` test fixture into shared helper

You are a **worker session**. Execute exactly this one refactor. Do not pick further candidates. Do not propose other work.

## Pre-read (mandatory, in this order)

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (especially #1 baseline-twice, #3 pre-rename pre-flight)
3. `REFACTOR_AUDIT.md` § "Findings" #1–#5 — context for what Pass 1 already added to `Design`
4. `tests/conftest.py` if it exists — if not, you'll create it
5. This prompt to the end

## Goal

8+ test files build the same trivial `Design(helices=[h], strands=[scaffold, staple], lattice_type=LatticeType.HONEYCOMB)` boilerplate, including the surrounding 1–2 lines that build `h`, `scaffold`, `staple` from `Helix`, `Strand`, `Domain`. Extract a single `make_minimal_design()` helper into `tests/conftest.py` and migrate ≥ 6 *clearly-equivalent* test sites to use it.

## In scope

- Create or extend `tests/conftest.py` with a `make_minimal_design(...)` function.
- Migrate test sites where the original boilerplate is **clearly equivalent** to the helper's output. "Equivalent" means:
  - Same lattice type
  - One helix or two helices
  - One scaffold + one staple, OR variants the helper supports via parameters
  - No bespoke domain coordinates beyond what params can express
- Update tests' imports.
- Run the full suite and confirm baseline preserved.

## Required helper signature

```python
# tests/conftest.py
from backend.core.models import Design, Helix, Strand, Domain, Direction, StrandType, LatticeType, Vec3

def make_minimal_design(
    *,
    n_helices: int = 1,
    helix_length_bp: int = 42,
    lattice: LatticeType = LatticeType.HONEYCOMB,
    with_scaffold: bool = True,
    with_staple: bool = True,
) -> Design:
    """Minimal fixture: 1–2 honeycomb/square helices, optional scaffold + staple
    spanning a single domain each. Used by tests that need a valid Design but
    don't care about the topology specifics. Larger or bespoke designs should
    be built inline."""
    ...
```

Do NOT add: more parameters than these; helpers for multi-strand designs; helpers for crossovers; helpers for clusters; helpers for deformations. If a callsite needs any of these, leave that callsite as-is (write `# (intentionally not migrated — needs <X>)` comment if useful).

Do NOT make the helper a Pytest fixture (`@pytest.fixture`). Plain function — callable from anywhere, no fixture-injection magic. Tests already use a mix of fixtures and direct calls; a plain function is composable with both.

## Migration target

Migrate ≥ 6 sites. Candidates from Pass 1 inventory:

- `tests/test_domain_shift.py:82, 98, 210, 527, 566`
- `tests/test_strand_end_resize_api.py:34`
- `tests/test_xpbd.py:173`
- `tests/test_importer_crossover_classification.py:217`

For each: read the surrounding 30 lines first. Migrate ONLY if equivalent. If a test asserts on specific domain bp values that depend on the inline boilerplate's exact length / direction / phase, you cannot migrate it; leave a comment.

## Out of scope (do not touch)

- Any test in `tests/test_overhang_*.py`, `tests/test_assembly_*.py`, `tests/test_atomistic_*.py`, `tests/test_lattice.py`, `tests/test_joints.py`, `tests/test_loop_skip.py`, `tests/test_seamed_router.py`, `tests/test_seamless_router.py` — these have bespoke larger designs.
- Renaming any test.
- Refactoring any assertion logic.
- Adding new test cases.
- Touching any non-test file.

## Verification plan (mandatory)

### Pre-state capture
```bash
just lint > /tmp/02B_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/02B_lint_pre.txt
just test > /tmp/02B_test_pre1.txt 2>&1
just test > /tmp/02B_test_pre2.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/02B_test_pre1.txt | sort > /tmp/02B_baseline1.txt
grep -E '^FAILED|^ERROR' /tmp/02B_test_pre2.txt | sort > /tmp/02B_baseline2.txt
comm -12 /tmp/02B_baseline1.txt /tmp/02B_baseline2.txt > /tmp/02B_stable_failures.txt
diff /tmp/02B_baseline1.txt /tmp/02B_baseline2.txt > /tmp/02B_flakes.txt || true

rg -c 'Design\(helices=' tests > /tmp/02B_inline_pre.txt
```

### Pre-flight before any rename
The helper introduction is *additive*; you are not renaming any existing public symbol. So no rename pre-flight is needed for this prompt. If you ever decide the helper needs a different name than `make_minimal_design`, run `rg -n '\bmake_minimal_design\b' tests` first.

### Implementation
1. Create or extend `tests/conftest.py` with the helper. Write a single test (in a new file or as a docstring sanity check) confirming the helper returns a valid `Design` that passes `validate_design`.
2. Migrate one test site. Run `just test` for that file (`just test-file tests/test_domain_shift.py`). Confirm baseline preserved.
3. Repeat for at least 5 more sites. Run the full `just test` after every 2–3 migrations; abort if any new failure appears.

### Post-state capture
```bash
just lint > /tmp/02B_lint_post.txt 2>&1 ; echo "EXIT $?" >> /tmp/02B_lint_post.txt
just test > /tmp/02B_test_post.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/02B_test_post.txt | sort > /tmp/02B_post_failures.txt
diff /tmp/02B_stable_failures.txt /tmp/02B_post_failures.txt   # expect: ⊆ baseline ∪ flakes
rg -c 'Design\(helices=' tests > /tmp/02B_inline_post.txt
```

## Pydantic round-trip check

Before claiming done, verify the helper's output round-trips:

```python
d = make_minimal_design()
assert Design(**d.model_dump()) == d   # exact equality
d2 = make_minimal_design(n_helices=2, with_staple=False)
assert Design(**d2.model_dump()) == d2
```

Run this as an inline `python -c` or as part of the helper's smoke test.

## Success criteria

- [ ] `tests/conftest.py` created/extended with `make_minimal_design(**kwargs)` signature exactly as specified
- [ ] Pydantic round-trip check passes for at least 2 helper variants
- [ ] ≥ 6 test sites migrated (count callsites; not files)
- [ ] No test outside `tests/` directory touched
- [ ] No production code touched
- [ ] `just lint` passes pre and post
- [ ] `just test` post-failures = baseline (stable) ∪ flake-subset
- [ ] `REFACTOR_AUDIT.md` updated with new Findings entry

## Stop conditions

- If `just test` shows a *new* failure after a migration, revert that migration and continue with the rest. Mark the site as un-migratable in the Findings entry.
- If you can't find 6 clearly-equivalent sites, stop at whatever count and document why fewer were available.
- If creating `tests/conftest.py` triggers pytest collection issues (auto-discovery rules), stop and report.

## Output format for final message

```
## 02-B test-fixture conftest — <REFACTORED|UNSUCCESSFUL>

### Metrics
- pre lint: <PASS/FAIL>; post lint: <PASS/FAIL>
- pre test: <X> pass / <Y> fail / <Z> error  |  post: <X'> / <Y'> / <Z'>
- stable baseline failure set: <count>; flake set: <count>
- inline `Design(helices=...)` callsites pre: <N1>; post: <N2>
- sites migrated: <K>
- pydantic round-trip: PASS

### Migration map
| File | Line range pre | Migrated? | Reason if not |
|---|---|---|---|
| tests/test_domain_shift.py | 82 | yes | |
| tests/test_xpbd.py        | 173| no  | needs id="empty" override |
…

### Tracker updates
- new inventory row for `tests/conftest.py`
- Findings #7 added

### Open questions / surprises
<anything the prompt didn't anticipate>
```
