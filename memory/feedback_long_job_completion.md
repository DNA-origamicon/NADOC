---
name: Long jobs must wake the originating agent
type: feedback
authority: canonical
status: active
---

User instruction, 2026-09-19: avoid unnecessary polling during long tests; estimate
runtime and query a process after it exceeds an explicit threshold; verify that
completion triggers actually wake the agent.

- Before a long job, record expected wall time, register completion/failure events,
  capture the exact originating CODEX_THREAD_ID, and confirm the watcher is armed.
- Prefer process exit / pidfd and filesystem events (inotify for atomic status
  replacement). Do not poll job files or wake the model every 30 seconds.
- Default overdue threshold: expected remaining runtime + max(50%, 5 minutes).
  At that threshold capture process/log progress and wake the originating agent
  once. The agent decides whether to set a revised deadline. Do not kill a merely
  slow process or launch replacement jobs automatically.
- This installation supports `codex queue --thread <exact-id> --message <text>`.
  Queue acceptance is not delivery. Persist the message ID/token, then the resumed
  agent writes a matching acknowledgment before reporting a verified wake.
- Do not call a subprocess exit-code-zero report a successful scientific review.
  Require actual evidence access and verified-result counts. A review claiming it
  could not read files is a review failure, regardless of CLI exit code.
- The previous standalone read-only reviewer failed initializing bwrap. Use the
  originating session's established tools instead of silently loosening sandbox
  policy. Save separate states for armed, queued, acknowledged, and reviewed.
- Reference implementation: experiments/cpd_published_comparator/completion_events.py
  and trigger_dna_review.py. The CPD extension runner arms it before simulation.

Verified end to end on 2026-09-19: both the live test message and the real CPD
completion event resumed the exact originating session as new turns. The resumed
agent saved a matching `completion_wake_ack.json`, reran the evidence audit, and
saved `completion_wake_review.json` under `cpd-dna-extended-v1`. This verifies
active-session queue delivery after yielding; offline/reboot recovery is not tested.
