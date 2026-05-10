# Pass 10 followup template (shared)

Used by all Pass 10 followup prompts (10-A-followup, 10-B-followup, …, 10-I-followup). Each per-prompt followup file references this template and adds 5-10 lines of candidate-specific anchors.

## Step 0 (every followup)
```bash
git worktree list
```

## Universal audit checklist

1. **Worker outcome reproducibility**: re-run `just lint` and `just test` in the worktree (or `/tmp/<id>_*.txt` artifacts if worktree was auto-cleaned). Match worker's claimed numbers within ±1 test (flake tolerance).
2. **Failure-set diff**: post-failures ⊆ stable_baseline ∪ KNOWN_FLAKES ∪ env-skip-flips per precondition #17.
3. **Production-untouched / scope**: `git -C <worktree> diff HEAD --stat` shows only the files the worker claimed.
4. **CWD safety (precondition #15)**: confirm worker reported a passing Step 0 check.
5. **Apparent-bug flags**: validate each by reading the production code under test. Per `feedback_interrupt_before_doubting_user.md`, do NOT fix; document.
6. **Auto-cleaned worktree handling (precondition #17 corollary)**: if the worker made no production-code changes, the worktree may be gone — fall back to `/tmp/` artifacts.
7. **Followup-MUST-NOT-write (precondition #22)**: do NOT append your evaluation directly to `REFACTOR_AUDIT.md`. Return text in the agent result; manager appends.

## Universal output format

```markdown
### Followup 10-X — <candidate name>  (eval 2026-05-10)

**Worker outcome confirmation**: <REFACTORED|UNSUCCESSFUL|INVESTIGATED|REFACTORED-with-caveats>
**Worktree audit context**: <path or "auto-cleaned; verified via /tmp/ artifacts">
**Diff vs claimed-touched files**: <K claimed | M observed>

**Metric audit**
- lint: claimed Δ=<X>, observed Δ=<Y>
- test: claimed <P>/<F>/<E>, observed <P>/<F>/<E>; baseline match: yes/no
- (candidate-specific metrics)

**Scope audit**
- production code unchanged where claimed: yes/no
- locked areas (`_PHASE_*`, `make_bundle_continuation`, atomistic): not touched: yes
- (candidate-specific scope checks)

**(Candidate-specific deep checks here — see per-prompt file)**

**Apparent-bug flags validated**: <none | list>

**Prompt evaluation**
- Was the scope right? Too tight? Too loose?
- Did the worker hit any unanticipated stop?

**Proposed framework edits**
1. ...
```

100 lines max per followup output.

## Do NOT
- Modify code
- Append to `REFACTOR_AUDIT.md` from the followup session
- Pick new candidates
- Re-do the worker's job

## Candidate-specific anchors

The per-prompt followup files (`10-A-followup.md`, `10-B-followup.md`, …) provide the candidate-specific anchors that go in the "(Candidate-specific deep checks here)" slot. They reference this template for the boilerplate.
