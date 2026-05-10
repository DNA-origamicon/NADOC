# Followup 03-A — Evaluate frontend coupling audit

You are a **followup session**. Audit, do not implement.

## Pre-read

1. `refactor_prompts/03-A-frontend-coupling-audit.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" + new Findings entries the worker added (likely #8 onward)
3. The worker's git diff (if any) and the `/tmp/03A_*.txt` artifacts they captured
4. Followup template requirement: `**Diff vs claimed-touched files**` field

## Your job

### Q1 — Did the investigation produce evidence?

For each `/tmp/03A_*.txt` artifact, confirm it exists and is non-empty. Spot-check the content:

- `/tmp/03A_circulars.txt` — does the worker's reported cycle count match what `npx -y madge --circular` outputs when you re-run it now?
- `/tmp/03A_fanout.txt` — re-run the worker's fan-out script and confirm top-5 modules match (allow ±1 for files added/modified mid-session).
- `/tmp/03A_fanin.txt` — same for fan-in.
- `/tmp/03A_boundary.txt` — re-run the boundary checks; do the listed cross-area imports still exist?
- `/tmp/03A_globals.txt` — `wc -l` should match what the worker reported.

If any artifact is missing or empty, that's a process miss; flag it and ask whether the prompt's investigation rhythm was clear enough.

### Q2 — Did the worker stay in scope?

- `git diff` — if non-empty, every change must be either (a) a circular-cycle break ≤ 20 LOC OR (b) tracker text. Anything else is scope creep; flag.
- `package.json` / `frontend/package.json` must be unchanged. If `npx -y` left a lockfile delta, flag.
- No backend / test edits. No `main.js` / `client.js` size changes (those are tracked elsewhere).
- Verify `### Pre-existing dirty state declaration` is present and complete by running `git status` and comparing.

### Q3 — Are the Findings entries usable?

Each new Findings entry (#8 onward) is supposed to be actionable by the manager. For each, judge:

- **Specificity**: does it cite file:line or module:function? "main.js is too coupled" is unusable; "main.js imports from X cyclic with Y via Z" is usable.
- **Severity claim**: does the worker's `low/high` priority match the followup's reading?
- **Three-Layer**: cross-layer leaks (Topological/Geometric/Physical) should be flagged `high` per CLAUDE.md. Verify.
- **Linked Findings**: did the worker connect new Findings to existing #1–#7 where there's overlap?

### Q4 — What did the prompt itself get right or wrong?

- **Investigation rhythm**: was the 6-step ordering (circulars → fanout → fanin → boundary → globals → duplication) the right cheap-to-expensive order? Did the worker run them in order? Did any step produce no signal and could be dropped?
- **Stop condition for code changes**: was the "≤ 20 LOC OR document only" gate clear? Did the worker hit any cycle that wanted a 30-LOC break and feel pressured to either over- or under-implement?
- **Tool availability**: did `npx -y madge` install fine? `jscpd`? If any failed, the prompt's fallback was "document and continue" — was that adequate?
- **Output template**: did the "investigation-only findings" placeholder field-set work, or did the worker have to invent fields?

### Q5 — Framework improvements

Specific edits to `REFACTOR_AUDIT.md`:

- Should "investigation-only" be a first-class STATUS distinct from `REFACTORED` / `UNSUCCESSFUL`? Pass 1 didn't anticipate read-only audits as primary outputs.
- Should the Findings template add a `**Implementation deferred**: <reason>` field for investigation-only entries?
- Did the JS-specific signal-scan list (in `## Suggested check commands`) actually fire? If not all six signals produced useful output for the worker, prune.
- Should fan-out / fan-in numeric thresholds (`≥ 15` and `≥ 20`) be revised based on what the audit found?

## Output format

Append your evaluation to `REFACTOR_AUDIT.md` under `## Followup evaluations`, AND output to chat:

```markdown
### Followup 03-A — frontend coupling audit  (eval date)

**Worker outcome confirmation**: <REPORTED|REFACTORED|UNSUCCESSFUL — confirmed/disputed>

**Diff vs claimed-touched files**: <N hunks claimed | M hunks observed | extra/missing list>

**Investigation evidence audit**
- /tmp/03A_circulars.txt: <present, N cycles> | observed N' cycles on rerun
- /tmp/03A_fanout.txt: <top-5 match: yes/no, deltas if any>
- /tmp/03A_fanin.txt: <top-5 match: yes/no>
- /tmp/03A_boundary.txt: <leak counts match: yes/no>
- /tmp/03A_globals.txt: <wc match: yes/no>

**Scope audit**
- code changes: <none | list with line counts>
- package.json: <unchanged|delta>
- pre-existing dirty state declaration present: <yes/no, complete?>

**Findings-entry usability audit** (per new entry)
- #N: <specificity good/poor> | <severity match yes/no> | <Three-Layer flagged correctly yes/no> | <linked to existing yes/no>

**Prompt evaluation**
- Investigation rhythm: ...
- Stop condition for code changes: ...
- Tool availability: ...
- Output template: ...

**Proposed framework edits**
1. ...
2. ...
```

## Time budget

200 lines max.

## Do NOT

- Implement code.
- Pick new candidates.
- Re-run the audit at full depth — spot-check is sufficient.
