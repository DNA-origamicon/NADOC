---
name: feedback_no_live_server_mutation_for_verify
description: "Never mutate the shared running server's design/job state to \"verify\" a feature — it clobbers the user's / a concurrent session's in-flight work."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d196cf87-60ff-41bb-a422-837be4dac33f
---

Do **not** drive the live dev server (`POST /design/bundle`, `/snupi/jobs`, `POST /design` reset,
`DELETE .../jobs/{id}`, etc.) to verify a feature end-to-end. The server holds ONE in-memory active
design + on-disk jobs shared across the user and any concurrent Claude sessions. On 2026-07-12 I ran a
dynamics-job probe against the live server: the job list showed jobs I did NOT create (incl. a
2520-node design's job — someone else's real work), and my "cleanup" reset the active design to empty
and deleted those jobs. That is exactly the concurrent-session clobbering [[feedback_concurrent_sessions]]
warns about, applied to server state rather than git.

**Why:** "No active design" at one moment does NOT mean the server is idle — a concurrent session (or
the user) can load a design between your check and your mutation. Server mutations are not yours to make.

**How to apply:** Verify backend features through the **test suite** (pytest builds designs in an
isolated `hb.scratch_session`, never the live server) — e.g. `predict_shape(..., dynamics=True)` +
its cached-payload/route path. For genuine in-app verification, **ask the user to load a design and
tell you it's safe to submit a job**, or lead the done message with `NOT VERIFIED IN APP`. Read-only
GETs against the live server are fine; POST/DELETE/reset are not. Never `POST /design {}` (resets the
active design) or delete jobs you didn't create.
