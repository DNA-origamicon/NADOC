---
name: feedback-runpod-babysitter-must-act
description: "A RunPod monitor must ACT on failure (kill the pod / alert), not just log status. The launcher's teardown-on-failure runs fetch_outputs first, which has NO timeout — a hung fetch bills an idle pod indefinitely."
metadata:
  node_type: memory
  type: feedback
  originSessionId: 78578ada-ee6f-4f68-bc99-2b8ae2ee803d
---

When babysitting a RunPod run, the monitor loop must **take action on a terminal/failed
state**, not merely record it. In the 2026-07-15 24hb heavy-base validation the job FAILED at
segment `02_p10`; `watch.py` surfaced `PROBLEM: failed:…` but my babysitter only appended it to a
log every 5 min — so the USER noticed the idle-billing pod before I did.

**Why:** a passive logger provides no protection. The pod bills while the failure sits unread.

**How to apply:**
- The babysitter must, each poll, grep the `watch.py`/status output for `failed:` / `FATAL` /
  `completed` / `PROBLEM` and on any terminal state **immediately reap the pod** (targeted
  `terminate_pod`, or `reap.py --kill` when it's the only pod) AND touch its sentinel so the
  completion trigger fires — do not wait for the next 5-min tick or for me to read the log.
- **Known launcher gap:** `run_job_on_pod` detects `failed` correctly (parses `failed:<seg>` →
  breaks) but then calls `md_executor.fetch_outputs` BEFORE the pod's `finally` teardown, and
  `fetch_outputs` has **no timeout**. A hung SFTP fetch (the runbook's documented "stuck fetch
  bills an idle pod indefinitely") therefore leaves the pod alive. Until that has a timeout, an
  EXTERNAL watchdog that can kill the pod is mandatory — never trust the launcher's own teardown
  as the sole safety net. The pod's budget-derived lifetime kill-switch (hours) is far too coarse
  to catch a quick failure.
- On any teardown, always finish with `reap.py` (no `--kill`) to confirm **0 pods billing**.

Related: [[REFERENCE_RUNPOD_RUNBOOK]], [[feedback-use-completion-triggers]],
[[feedback-runpod-downloads-to-archive]].
