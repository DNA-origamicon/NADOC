# Agent-memory hygiene

Use this rubric when auditing `CLAUDE.md`, `memory/`, `.claude/rules/`, runbooks, and skills.

| Dimension | Weight | Full-credit condition |
|---|---:|---|
| Instruction clarity and priority | 20 | Durable rules are specific, non-conflicting, and action-oriented. |
| Retrieval and discoverability | 20 | Every active topic is linked from the index and has one canonical owner. |
| Context economy | 20 | Always-loaded files are concise; heads stay at or below 200 lines; history is archived. |
| Currency and provenance | 15 | Status, authority, review date, supersession, and evidence are visible where useful. |
| Safety and enforcement | 15 | Destructive boundaries are explicit and hard requirements have deterministic gates. |
| Maintainability and lifecycle | 10 | Naming, metadata, linting, and archive rules make drift cheap to detect and fix. |

## Maintenance loop

1. Run `just lint-memory`.
2. Resolve errors immediately. Treat size warnings as an ordered migration queue, largest first.
3. When a head passes 200 lines, move dated/resolved narrative to its matching archive. Keep current
   state, binding invariants, open decisions, next actions, and verification evidence in the head.
4. Add a new topic to `memory/MEMORY.md` as a Markdown link. Do not put its changing project status
   in the index unless that status is necessary for routing.
5. Record a recurring failure as one symptom hook in `LESSONS.md` and its full evidence in
   `LESSONS_archive.md`.
6. Put universal repository behavior in `CLAUDE.md`, path behavior in `.claude/rules/`, debugging
   procedures in runbooks, and occasional workflows in skills.

## Retrieval evaluation

Run these questions in a fresh session after a structural change. The answer passes when the agent
opens the named canonical source without opening an archive or unrelated topic.

| Question | Expected source |
|---|---|
| Where is the canonical rule for topology mutations? | `CLAUDE.md` → `REFERENCE_DNA_TOPOLOGY.md` |
| How is a frontend-only behavior change verified? | `CLAUDE.md` verification law |
| What is currently open in MD visualization? | `project_md_viz_tools.md` |
| What prevents an unattended RunPod bill? | `REFERENCE_RUNPOD_RUNBOOK.md` plus matching feedback rule |
| Where is a recurring bug recorded? | `LESSONS.md` hook plus `LESSONS_archive.md` detail |

Record misses as one of: wrong source, archive opened unnecessarily, conflicting answer, missing
link, or stale answer. Fix the routing/document contract that caused the miss rather than adding a
one-off reminder to `CLAUDE.md`.
