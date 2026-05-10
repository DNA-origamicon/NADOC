# Followup 05-B — Evaluate backend coverage audit

You are a **followup session**. Audit, do not implement.

## Step 0
```bash
git worktree list
```

## Pre-read
1. `refactor_prompts/05-B-pytest-coverage-audit.md`
2. Worker's Findings #16 text (passed by manager)

## Q1 — Did the worker actually run coverage?

Check `/tmp/05B_cov.json` exists and is parseable JSON:
```bash
ls -la /tmp/05B_cov.json
uv run python -c "import json; print(len(json.load(open('/tmp/05B_cov.json'))['files']))"
```

Spot-check the worker's "5 lowest-coverage modules" table. Run:
```bash
uv run python -c "
import json
data = json.load(open('/tmp/05B_cov.json'))
ranked = sorted(data['files'].items(), key=lambda kv: kv[1]['summary']['percent_covered'])
for path, info in ranked[:5]:
    print(f'{info[\"summary\"][\"percent_covered\"]:5.1f}%  {path}')
"
```

Match worker's claim ±1 module (small reordering due to ties is fine).

## Q2 — Are the classification tags honest?

For each of the 5 lowest-coverage modules, the worker tagged it `untested-but-testable | hard-to-test | possibly-dead | mixed`. Spot-check 2 of them:

- Open the module source.
- For an `untested-but-testable` tag: are there functions that obviously could have unit tests (pure functions, deterministic input→output)?
- For a `hard-to-test` tag: is there real evidence (subprocess, network, filesystem)?
- For a `possibly-dead` tag: is the module really unimported anywhere? Cross-reference with `madge` or `rg`.

If a tag is wrong, flag it.

## Q3 — Scope

- `git -C <worktree> diff HEAD --stat` should be empty (no code changed). If `pyproject.toml` shows changes (pytest-cov added as dev-dep), flag — that wasn't in scope.
- Test baseline preserved: `diff /tmp/05B_stable_failures.txt /tmp/05B_post_failures.txt` empty.

## Q4 — Usability

The Findings entry's purpose is to drive future test-writing prompts. For each "untested-but-testable" module, did the worker name 1-2 specific functions worth testing? If the entry just says "coverage is low" without targets, it's not actionable. Flag.

## Output (return as agent result text)

```markdown
### Followup 05-B — backend coverage audit  (eval date)

**Worker outcome confirmation**: <INVESTIGATED — confirmed/disputed>
**Worktree audit context**: <path>
**Diff vs claimed-touched files**: <0 claimed | observed: empty | non-empty>

**Coverage measurement audit**
- /tmp/05B_cov.json present + parseable: <yes/no>
- Whole-suite %: claimed <X.Y%>, observed <X'.Y'%>
- Top-5 ranking match: <K of 5 match within ±1 position>

**Tag-honesty audit** (2 spot-checks)
- <module>: tag <X> — <agree/disagree, reasoning>
- <module>: tag <X> — <agree/disagree, reasoning>

**Scope audit**
- code changes: <none | list>
- pyproject.toml unchanged: <yes/no>
- test baseline preserved: <yes/no>

**Usability audit**
- Specific test-target functions named per "untested-but-testable" entry: <K of N>
- Findings entry actionable for future prompt-writing: <yes/no>

**Prompt evaluation**
- Was 15-min budget realistic?
- Did the 4-category tagging rubric fit the data?
- Anything the prompt should have asked but didn't?

**Proposed framework edits**
1. ...
```

100 lines max.

## Do NOT
- Implement code, write tests, pick new candidates, append to REFACTOR_AUDIT.md.
