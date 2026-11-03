---
name: MD panel — implementation status and algorithm details
description: What works, what the PBC pipeline does, known limits, and how to extend the trajectory for late frames
type: project
originSessionId: 184cf93b-87e6-47df-98ad-3d8aa2a3bad9
---

# MD panel status

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

## RunPod display pulls its own snapshots (2026-08-08)

The MD Display used to tell a RunPod user to do the work themselves — *"This run's
trajectory is on the pod, not on this computer. Fetch a live frame…"* — for a fetch the
panel was never wired to make: `shouldFetchLiveFrame` required `clusterState ===
'connected'` **and** Alpine-only `mdIsRemoteRunning`, and `POST /md/jobs/{id}/fetch-live-frame`
409'd anything without a Duo cluster session. So the instruction named a button that did
not exist for that target.

Now: **RunPod snapshots arrive on a timer, unprompted.**

* **`runpod_executor.open_pod_connection(job, client=…)`** — a read-only SSH channel to a
  job's live pod. ⚠️ Deliberately **not** `client.pod()` / `client.adopt()`: both DESTROY
  the pod in their `finally`, so either would kill the paid run it was peeking at. Uses
  `get_pod` (a plain read); the caller owns the connection and must close it. A 404 is
  reworded as "that pod no longer exists" — it is the ordinary end of every run.
* **The route branches on target.** Alpine keeps its Duo-gated manager; RunPod opens a
  per-errand connection. Same `remote_live_frame.fetch_live_frame` underneath — it takes
  any object with `sftp_get`, which is the conn duck-type paying off again.
* **Cadence: `LIVE_FRAME_REFRESH_MS = 120_000`**, matched to what the pod actually
  produces (NAMD rewrites `restart.coor` every `restartfreq`, minutes apart). The backend
  keeps its own 60 s floor (`remote_live_frame.MIN_REFETCH_INTERVAL_S`). A 5 s tick moves
  the countdown label; only `liveFrameCountdown` decides when to spend a fetch.
* **`_liveFrameAt` is stamped on FAILURE too.** A pod with no checkpoint yet answers
  "not ok" every time; without the stamp the countdown sits at due and re-pulls ~32 MB
  every tick.
* **`_liveFrameTried` is Alpine-only now.** That one-shot set exists because Duo means one
  chance per session; a pod is key-based, so it must retry.
* **The ⟳ button** (`#md-jobs-live-frame-refresh`) shows only for `mdIsPodRunning` + display
  on, and passes `force: true` to bypass the 60 s floor — the user asked explicitly.
* **`runpodConnected(preflight)`** (new, `runpod_status.js`) is narrower than
  `runpodCanLaunch`: reaching an existing pod needs only the API session, not the volume /
  SSH-key / stock / sizing gates that renting a NEW GPU needs.

**VERIFIED against the live 2hb_1xT run** (job `7d5937e569c6`, pod `cw4i37gthl10dw`,
2026-08-08): frame on screen 6.1 s after toggling Display MD, ⟳ re-fetched in ~5 s, the
2-minute auto-refresh fired, zero console errors. `frontend/e2e/md_runpod_live_frame.spec.js`
+ `e2e/logs/md_runpod_live_frame.png`. Getting there took two real bugs:

### Bug 1 — `job.json` has two writers, and the loser was `live_frame`

The fetch route loaded its own `MdJob`, set `live_frame`, saved. `runpod_executor
._supervise_run` holds a SEPARATE in-memory job and re-saves the whole record every 30 s
poll, reverting the field. The next fetch then saw a DCD it no longer recognised as a
stand-in and refused to touch it — `{"ok": true, "skipped": "real trajectory already
local"}` **forever**, while reporting success. The display froze on its first snapshot.

Fix: the marker moved to a **sidecar** `output/<seg>.dcd.live.json` — one writer, and it
describes the FILE rather than living in a record someone else owns.
`remote_live_frame.{marker_path,read_marker}`; `is_live_stand_in`/`clear_live_frame` take an
optional `package_dir` and prefer the sidecar. `job.live_frame` is still written (display
payload) but is no longer the authority.

⚠️ **Generalise this.** Any field a ROUTE writes on a job that a supervisor is also running
will be reverted within a poll. Check for this before adding another.

<a id="bug-2--the-snapshot-had-no-unit-cell-so-the-display-refused-it"></a>
- [Bug 2 — the snapshot had no unit cell, so the display refused it](details/project_md_panel_status/01-bug-2--the-snapshot-had-no-unit-cell-so-the-display-refused-it.md#bug-2--the-snapshot-had-no-unit-cell-so-the-display-refused-it)

<a id="the-troubleshooting-tool"></a>
- [The troubleshooting tool](details/project_md_panel_status/01-bug-2--the-snapshot-had-no-unit-cell-so-the-display-refused-it.md#the-troubleshooting-tool)

<a id="the-readiness-dot-described-the-previous-job-fixed-2026-08-08"></a>
- [The readiness dot described the PREVIOUS job (fixed 2026-08-08)](details/project_md_panel_status/01-bug-2--the-snapshot-had-no-unit-cell-so-the-display-refused-it.md#the-readiness-dot-described-the-previous-job-fixed-2026-08-08)

## What is built and working

- **`backend/core/md_metrics.py`** — `scan_run_dir`, `parse_log_metrics`, `count_frames`
- **`POST /api/md/load`** in `crud.py` — validates topology/XTC, returns frame count + metrics
- **`/ws/md-run`** WebSocket in `ws.py` — `load`, `seek`, `get_latest` actions
- **`frontend/src/ui/md_panel.js`** — full panel: load, scrubber, play/pause/loop/live, speed, stride, repr, opacity, displacement amp slider
- **`frontend/src/scene/md_overlay.js`** — InstancedMesh beads-only overlay
- **`frontend/index.html`** — `#md-panel` section wired up
- **Frame application** (`applyFemPositions` in `helix_renderer.js`) — NADOC full mode

<a id="pbc-correction-pipeline-in-_seek_sync"></a>
- [PBC correction pipeline (in `_seek_sync`)](details/project_md_panel_status/02-pbc-correction-pipeline-in-_seek_sync.md#pbc-correction-pipeline-in-_seek_sync)

<a id="performance-on-10hb-nominal-run"></a>
- [Performance on 10hb nominal run](details/project_md_panel_status/02-pbc-correction-pipeline-in-_seek_sync.md#performance-on-10hb-nominal-run)

<a id="pbc-quality-check-at-load-time"></a>
- [PBC quality check at load time](details/project_md_panel_status/02-pbc-correction-pipeline-in-_seek_sync.md#pbc-quality-check-at-load-time)

<a id="how-to-extend-view_wholextc-for-late-frames--546-ns"></a>
- [How to extend view_whole.xtc for late frames (> 54.6 ns)](details/project_md_panel_status/02-pbc-correction-pipeline-in-_seek_sync.md#how-to-extend-view_wholextc-for-late-frames--546-ns)

<a id="live-mode-updated-2026-07-01"></a>
- [Live mode (updated 2026-07-01)](details/project_md_panel_status/02-pbc-correction-pipeline-in-_seek_sync.md#live-mode-updated-2026-07-01)

<a id="toggle-latency-cost-breakdown--prewarm-on-open-2026-07-01"></a>
- [Toggle latency: cost breakdown + prewarm-on-open (2026-07-01)](details/project_md_panel_status/02-pbc-correction-pipeline-in-_seek_sync.md#toggle-latency-cost-breakdown--prewarm-on-open-2026-07-01)

<a id="toggle-readiness-indicator--the-mda_unwrap-load-bomb-2026-07-01"></a>
- [Toggle readiness indicator + the mda_unwrap load bomb (2026-07-01)](details/project_md_panel_status/02-pbc-correction-pipeline-in-_seek_sync.md#toggle-readiness-indicator--the-mda_unwrap-load-bomb-2026-07-01)

## Variable naming trap in ws.py `_seek_sync`

`_load_sync` stores eq positions in the result dict as `"eq_positions"`.  
`_seek_sync` reads it as `eq_pos = _ctx.get("eq_positions")`.  
Inside `_seek_sync`, always use `eq_pos` — NOT `eq_positions` (which doesn't exist in that scope and raises NameError). This was the bug causing WebSocket errors after the inlier Kabsch was added.
