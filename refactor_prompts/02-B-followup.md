# Followup 02-B — Evaluate test-fixture conftest refactor

You are a **followup session**. Audit, do not implement.

## Pre-read

1. `refactor_prompts/02-B-test-fixture-conftest.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" + Findings #7 (the worker's entry)
3. The worker's diff: `git diff` for `tests/conftest.py` and any migrated test files

## Your job

### Q1 — Did the worker hit the metrics?

- Re-run `just lint`, `just test`. Compare to recorded values.
- Re-run `rg -c 'Design\(helices=' tests` and confirm the post number.
- For each "Migrated? yes" row in the worker's migration map: open the test file at the migrated line, confirm the call is `make_minimal_design(...)` with parameters that match the original boilerplate's intent (same lattice, same n_helices, etc.).
- For each "Migrated? no" row: confirm the reason given is real (e.g., the original truly has bespoke domain coordinates the helper can't express).
- Run the pydantic round-trip check yourself:
  ```python
  from tests.conftest import make_minimal_design
  from backend.core.models import Design
  d = make_minimal_design()
  assert Design(**d.model_dump()) == d
  ```

### Q2 — Did the helper stay minimal?

This is the critical risk for this refactor: over-engineering. Open `tests/conftest.py` and check:

- Is the signature `(*, n_helices, helix_length_bp, lattice, with_scaffold, with_staple)` as specified — or did the worker add extra parameters (e.g. `with_crossover`, `multi_scaffold`, `bp_per_domain`)?
- Did the worker add additional fixture functions beyond `make_minimal_design`? (Out of scope.)
- Is the docstring honest — does it warn that bespoke designs should be inline?
- Did the worker add `@pytest.fixture` decorations that weren't asked for?

For each over-engineering finding, quote the file:line and recommend a revert.

### Q3 — Did the worker stay in scope?

Search the diff for:
- Any non-test file changed → flag.
- Any test outside the listed migration candidates touched → flag (could be legitimate, but worker should have justified in the migration map).
- Any test renamed or removed → flag.
- Any assertion edits → flag.

### Q4 — What did the prompt itself get right or wrong?

- **Helper signature**: was the API minimal enough? Did the worker run into a callsite where they wished they had one more parameter? Is that addition justified or scope creep?
- **Migration target list**: were the 8 candidate sites the right ones? Did the worker discover others that should have been listed? Were any "candidates" unmigratable for a reason the prompt didn't anticipate?
- **Verification plan**: was running `just test-file` per migration efficient, or did the full-suite re-runs catch regressions the per-file run missed?
- **Out-of-scope list**: did the worker bump up against any "I'd have done X but it's out of scope" comment? If so, is X worth a future prompt?

### Q5 — Framework improvements

Specific edits to `REFACTOR_AUDIT.md`:

- Should "Tests" be its own audit category? (Pass 1 didn't list it. The categories list said "Test-code refactors are tracked separately" without defining how.) Propose verbatim text for a new "Test-code category" subsection.
- Should the Findings template gain a "Helper signature" or "API surface added" field for refactors that add public API?
- Should a per-prompt "anti-scope-creep checklist" be standard? Propose verbatim if so.
- Was the pydantic round-trip check useful or over-engineered for tests-only changes?

## Output format

Append your evaluation to `REFACTOR_AUDIT.md` under `## Followup evaluations`, AND output to chat:

```markdown
### Followup 02-B — test-fixture conftest  (eval date)

**Worker outcome confirmation**: <REFACTORED|UNSUCCESSFUL — confirmed/disputed>

**Metric audit**
- lint: claimed <X>, observed <Y>
- test: claimed <X>, observed <Y>; stable baseline match: <yes/no>
- inline callsites: claimed pre=N1 post=N2, observed pre=N1' post=N2'
- migrated sites verified: <K out of K' claimed>
- pydantic round-trip: <PASS/FAIL on <variant>>

**Helper-minimality audit**
- Signature matches spec: <yes/no — list deltas>
- Extra fixtures added: <list>
- Over-engineering findings: <bullets, file:line>

**Scope audit**
- out-of-scope diffs: <none|list>

**Prompt evaluation**
- Helper signature fit: ...
- Migration target list accuracy: ...
- Verification plan completeness: ...
- Out-of-scope coverage: ...

**Proposed framework edits**
1. ...
2. ...
```

## Time budget

200 lines max.

## Do NOT

- Implement code.
- Open the same prompt as a worker.
- Add new refactor candidates.
