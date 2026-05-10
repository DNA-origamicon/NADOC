# Followup 02-A — Evaluate frontend debug-log gating refactor

You are a **followup session**. You do not implement code changes. You audit the previous worker session's output against its prompt and against the framework, and propose framework improvements.

## Pre-read

1. `refactor_prompts/02-A-frontend-debug-log-gating.md` — the prompt the worker was given
2. `REFACTOR_AUDIT.md` § "Universal preconditions", "Categories", "Findings" #6 (the worker's entry)
3. The worker's git diff for `frontend/src/main.js` (if no commit, use `git diff` on the working tree)

## Your job

Answer four questions concretely, with file:line evidence.

### Q1 — Did the worker hit the metrics?

- Re-run `just lint` and `just test`. Compare to the worker's recorded values. Flag any discrepancy ≥ 1 test or any lint state change.
- Re-count `rg -c 'console\.log' frontend/src/main.js` and the unconditional subset. Confirm pre/post numbers in the Findings entry are accurate (sample 5 random gated calls and verify the gate is real).
- If the worker said `NOT VERIFIED IN APP`, do not penalize — but note whether the app could have been reached and wasn't.

### Q2 — Did the worker stay in scope?

Search the worker's diff for:
- Any `console.error` / `console.warn` changes — these are out of scope; flag.
- Any file other than `frontend/src/main.js` changed — out of scope; flag.
- Any log message text edits — out of scope; flag.
- Any `console.log` removals (not gated, deleted) — flag, ask why.

### Q3 — What did the prompt itself get right or wrong?

For each of these, write 1–2 sentences:

- **Scope clarity**: did the in-scope / out-of-scope rules correctly anticipate the work? What ambiguity did the worker hit? (Look at the worker's "Open questions / surprises" section.)
- **Verification plan completeness**: did the metrics capture the change well? Did the post-state capture miss anything (bundle size? page-load timing? a regression we'd only see in the running app)?
- **Classification rubric**: did the four-bucket rubric (dev-only / production-startup / production-event / already-gated / unsure) match what the worker actually saw, or did real cases fall outside? Sample 5 of the worker's classifications and judge each.
- **Stop conditions**: did any stop condition fire? If so, was it appropriate?

### Q4 — Framework improvements

Based on Q1–Q3, propose specific edits to `REFACTOR_AUDIT.md`:

- New rule under "Universal preconditions"? Quote the rule verbatim and the section it'd go in.
- New category, signal, or check command? Same — verbatim text.
- Tracker columns or Findings template fields that would have helped?
- Should any *future* refactor prompts in `refactor_prompts/` adopt a different structure? (E.g., always require a "frontend bundle-size pre/post" check.)

## Output format

Append your evaluation to `REFACTOR_AUDIT.md` under `## Followup evaluations`, using this template, AND output the same content to chat:

```markdown
### Followup 02-A — frontend debug-log gating  (eval date)

**Worker outcome confirmation**: <REFACTORED|UNSUCCESSFUL — confirmed/disputed>

**Metric audit**
- lint: claimed <X>, observed <Y>
- test: claimed <X>, observed <Y> ; stable baseline match: <yes/no>
- log counts: claimed pre=N1 post=N2, observed pre=N1' post=N2'
- sampled gated calls (5): <pass/fail per sample>

**Scope audit**
- out-of-scope diffs found: <none | list>

**Prompt evaluation**
- Scope clarity: ...
- Verification plan completeness: ...
- Classification rubric fit: ...
- Stop conditions: ...

**Proposed framework edits**
1. <edit description, with section + verbatim before/after>
2. ...
```

## Time budget

200 lines of evaluation max. If you find yourself going longer, you're doing the worker's job — stop and summarize.

## Do NOT

- Implement any code change yourself.
- Open the same prompt as a new worker. (If the work needs a redo, write a new prompt 02-A-v2 instead.)
- Add new refactor candidates. That is the manager's job.
