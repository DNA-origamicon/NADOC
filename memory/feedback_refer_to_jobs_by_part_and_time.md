---
name: refer-to-jobs-by-part-and-time
description: Never identify an MD/oxDNA job to the user by its hex job_id — use the part name plus the job creation time, because that is all the frontend exposes.
metadata:
  node_type: memory
  type: feedback
---

Refer to a simulation job as **"<part> run created <YYYY-MM-DD HH:MM>"**, e.g.
*"the 2hb_1xT run created 2026-07-30 15:26"* — never as `ccdcdca7675a`.

**Why:** hex `job_id`s are not surfaced anywhere the user can match them against. Told to
verify something on jobs `ccdcdca7675a` / `c8bcf4c1406f` / `29c5b267380f`, the user could
not find them in the frontend at all and the verification had to be abandoned. The part
name and the creation time are the only handles the UI currently gives them.

**How to apply:**
- In any message naming a job, lead with part + creation time. The `job_id` may follow in
  parentheses for a command they can paste, but it is never the identifier.
- Same rule for a *feature that only works on some jobs*: say which part, and which run by
  time — not "job X supports this".
- **Part + minute is not always unique** — two 2hb_1xT runs here were both created
  2026-07-28 16:39. Add seconds, or a distinguishing detail (length, status, "the 500 ns
  one"), when more than one candidate shares a minute.
- This is a symptom of a UI gap, not just a naming habit: anything that asks the user to
  pick a job should show part + creation time itself. Prefer building that over writing a
  better sentence.

Related: [[project_cpd_umbrella_sampling]] · [[project_md_job_system]]
