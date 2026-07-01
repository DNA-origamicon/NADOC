---
name: dev-server-shutdown-hang
description: uvicorn dev server wedges on reload/stop because status websockets never close
metadata: 
  node_type: memory
  type: project
  originSessionId: 3e50f67f-227e-4e31-8f9b-c16fbe3f92d1
---

**Symptom:** the FastAPI dev server (`just dev`) becomes unreachable (HTTP times
out at ~5 s, not connection-refused). A running/preparing MD job then "appears
ongoing" forever in the UI — the prep heartbeat (`prep_progress.json`, written 1 Hz)
freezes, and `_reconcile_preparing`/`reconcile_job_status` can't run to fail it.

**Root cause:** uvicorn graceful shutdown. A `--reload` (or stop) tells the worker
to shut down; it then logs `Waiting for connections to close. (CTRL+C to force quit)`
and **waits forever** because NADOC's status websockets (`/ws/md-jobs/{id}`) are
long-lived and never close on their own. The event loop is parked in shutdown → all
HTTP hangs, heartbeats die. Diagnose via `ps`: the real worker is the
`multiprocessing.spawn_main` child (not the `--reload` parent); 0 % CPU + dozens of
threads in `futex_do_wait` + that log line = this hang.

**Fix (justfile `dev`):** `--timeout-graceful-shutdown 5` caps the wait so reload/stop
force-closes within seconds. Applies only after a FULL `just dev` restart (the reload
parent's command is fixed at launch).

**Recover a live wedged server without restarting:** `kill -KILL <spawn_main worker pid>`
— the `--reload` parent respawns a fresh, responsive worker; the next `/api/md/jobs`
poll then auto-fails any stale `preparing` job (`_PREP_STALE_S=30`).

This bit twice in one session: a `/stop` API call hung (had to kill NAMD directly),
and later a fresh VoltronCore prep froze at ~11 % topology. Also removed the
elapsed-vs-expected "may be stalled" prep warning (md_prep_progress.py) — nominal
times vary too much by design size to be useful; stale heartbeat is the real signal.
Frontend now shows "⚠ Backend not responding" after 2 failed job polls
([[md-panel-status]]).
