# MD Sidebar UX Audit (2026-06-11) — supporting detail

[Topic head](../../project_md_sidebar_audit.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

# MD Sidebar UX Audit (2026-06-11)

## Early-stop card moved under the Jobs card — SHIPPED 2026-08-07
`#md-jobs-live-controls` left the NAMD panel (it used to sit between E-field and
Visualizations) and now lives at **section level, directly under the unified Jobs card**, in
the new host `#namd-live-controls-host` (`index.html`, above the Shape-comparison card) —
the one control that acts on the RUNNING relaxation sits next to the run it affects.
**Two independent visibility gates now:** the host is shown only on the NAMD tab (one line of
wiring in the engine-selector `onSelect`, `main.js`), the card inside only while a local
relaxation is live (`_isLiveRelax`, unchanged, `md_jobs_panel.js`). Ids unchanged, so all the
panel wiring and `mdEarlyStopToggleState` are untouched. vitest 5029; smoke 23 pass.

## Cluster card promoted + connect chip moved + early-stop de-experimentalized — SHIPPED 2026-07-11
- Dropped the "(experimental)" tag from the early-stop toggle label + tooltip (well-tested now).
- **Cluster (Alpine) card pulled OUT of `#md-jobs-detail` to a top-level, always-visible card**
  (parity with the Viz card; verified in-app). It now leads with the **connect chip**
  (`#md-cluster-connection-mount` relocated from the Advanced card into `#md-jobs-cluster-body`
  at init, `main.js`) so connecting is reachable BEFORE any Alpine job exists (fixed audit
  friction #1/#12). The per-job controls (submit/resume/ensemble/rollup/status/resume-history)
  still show/hide with the selection; `_clearSelectedJob` resets those parts but keeps the card.
  `_applyJobState` no longer toggles the card's own visibility. vitest 2659; smoke 21 pass.
- **Alpine vs local protocol AUDIT (2026-07-11):**
  - **#2 FIXED** — run-target radios (Local/Alpine) moved from the collapsed Advanced card into
    the Cluster card (after the connect chip), so run-location controls sit together + are
    visible. HTML move; ids unchanged; verified in-app.
  - **#3 FIXED** — `mdRunControl` now takes `runTarget`; a fresh launch with target=Alpine
    relabels the primary button **"▶ Prepare for Alpine"** (it only preps+queues; a separate
    Submit follows). Run-target radio `change` repaints it; stop/resume labels unchanged. Test
    added.
  - **#8 FIXED** — `MdJob.pending_scancel` (load-setdefault). Stop on a disconnected remote job
    marks it stopped locally AND sets `pending_scancel` (`routes_md.stop_md_job`); the next
    connected `poll_remote_jobs` pass drains it (issues scancel, clears flag) even though the job
    is no longer "active" — so the SLURM job doesn't keep burning SU. Frontend toasts the deferred
    message. Tests: `test_poll_remote_jobs_drains_pending_scancel`,
    `test_stop_disconnected_defers_scancel`.
  - **#6 FIXED** — two parts. (a) A successful `POST /cluster/connect` now kicks
    `poll_remote_jobs` immediately (`routes_cluster.py`), so a run that FINISHED while the
    session was down gets its results fetched on reconnect (not up to ~30 s later) — this also
    drains #8's deferred scancels. (b) Frontend nudge: pure `mdRemoteReconnectPrompt(jobs,
    clusterState)` → an amber `#md-jobs-cluster-reconnect-note` in the Cluster card ("N Alpine
    runs in flight — reconnect to monitor and fetch results") shown when submitted Alpine jobs
    are queued/running/preparing AND the session isn't connected. Wired to
    `nadoc:cluster-state-change` + every `_fetchJobs`. Tests: `test_cluster_connect_kicks_remote_poll`
    (backend), `mdRemoteReconnectPrompt` (frontend).
  - #5 by design — no live metrics/health for remote runs (SLURM has no local WS). The card now
    says so via `health_probe`/`mdRemoteReadoutNote` rather than spinning (2026-07-31).
  - #11 minor — ensemble button gated on connection though `ensemble-production` staging works
    offline (only submit needs the session).
