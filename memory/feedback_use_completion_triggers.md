---
name: feedback-use-completion-triggers
description: "Wait on long-running jobs (sims, ladders, GPU runs) with a background completion trigger that notifies on finish — never foreground sleep/poll loops that burn turns."
metadata:
  node_type: memory
  type: feedback
  originSessionId: 78578ada-ee6f-4f68-bc99-2b8ae2ee803d
---

When waiting for a long-running job to finish (NAMD/oxDNA runs, relaxation ladders, any
multi-minute GPU/CPU task), **use a background completion trigger, not foreground polling.**

**Why:** repeated `sleep 110; check` foreground calls burn a tool turn each, spam the
transcript, and make the user watch me idle. A single backgrounded wait-until-done loop
(`Bash run_in_background: true`, or Monitor) blocks silently and fires ONE task-notification
the moment the condition is met — the harness re-invokes me automatically then.

**How to apply:** launch the job detached, then in ONE `Bash run_in_background: true` call run
`while [ ! -f done.sentinel ]; do sleep 8; done; <print verdict>` (job `touch`es the sentinel on
exit), or watch the LOG CONTENT: `while ! grep -qiE "End of program|FATAL ERROR|Atoms moving too
fast" run.log; do sleep 8; done`. Do NOT chain `sleep`+check in the foreground.

**⚠️ The trap that bit me (2026-07-15): NEVER gate the loop on `pgrep -f "<jobfile>"`.** The
watcher process's OWN command line contains `<jobfile>`, so `pgrep -f` self-matches the watcher —
the loop never goes false even after the real job dies, the trigger hangs forever, and NO
completion notification fires (you sit there thinking a run is going when it finished ages ago).
Gate on FILE state (a sentinel file, or a terminal marker grepped from the LOG FILE) or on a
captured PID (`kill -0 $PID`) — never on a process-name string that appears in the watcher itself.

Match the poll interval to the state you're watching (see [[project_test_parallelization]]). Don't
schedule short wakeups to poll harness-tracked work — completion already notifies me.
Related: [[feedback-runpod-downloads-to-archive]].
