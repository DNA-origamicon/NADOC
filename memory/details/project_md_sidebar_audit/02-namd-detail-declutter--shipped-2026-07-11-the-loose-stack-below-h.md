# NAMD detail declutter — SHIPPED 2026-07-11 (the loose stack below Health) — supporting detail

[Topic head](../../project_md_sidebar_audit.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## NAMD detail declutter — SHIPPED 2026-07-11 (the loose stack below Health)
Audited the loose items under the Health card; user directed the cleanup. Done in
`index.html` + `md_jobs_panel.js`:
- **Removed (derelict/redundant):** the duplicate detail status line (`#md-jobs-detail-status`,
  redundant with the master job card); the invisible progress bar (`#md-jobs-progress`,
  `display:none`, superseded by the master bar) + its ~150 lines of dead render code
  (`_showPreparingProgress`/`_renderPrepProgress`/`_fmtEta`/`_renderProgress`/
  `_productionRunSummary`/`_productionAdvisoryText`/`_productionFailureText`, + orphaned
  `_statusLabel`/`_latestHealthForSegments`); the "Load Frames" button (`#md-jobs-frame-controls`,
  duplicated the Display-MD radio → `_startMdDisplay`); the separate mid-run early-stop toggle.
- **New "Cluster (Alpine)" card** (`#md-jobs-cluster-card`, collapsible, shown only when the
  selected job has cluster content): Submit-to-Alpine + Resume buttons, Ensemble replicas,
  ensemble roll-up, resume history, and an Alpine-only status line (`#md-jobs-cluster-status`,
  the awaiting-submit / SLURM-queued states rescued from the deleted status line). Visibility =
  OR of its parts, computed in `_applyJobState`.
- **SUPERSEDED 2026-08-03 (Job Wizard):** the Advanced card is DELETED — every launch
  parameter lives in the wizard (`＋ New job`). `#md-jobs-early-stop` kept ONLY its live
  role, in `#md-jobs-live-controls`, shown only for a running local relaxation; its launch
  default is a wizard field. `mdRunControl` is now one Run/Stop/Resume control over the
  SELECTED job (production children included), and `mdProductionAction` /
  `mdSelectedJobControl` are gone. The paragraphs below describe the pre-wizard layout.

- **Early-stop unified:** the ONE Advanced toggle (`#md-jobs-early-stop`) is now BOTH the launch
  default AND the live mid-relax control — for a running local relaxation a change POSTs the
  override (`setMdEarlyStop`) with the `#md-jobs-early-stop-pending` badge; otherwise it's the
  create default. Gated by `_isLiveRelax(job)`. The old `#md-jobs-early-stop-live*` removed.
- **Error box moved into the Health card body** (`#md-jobs-detail-error`).
- Timeline unchanged (already relocated to the master jobs card by main.js).
- vitest **2659**; smoke 21 pass (2 pre-existing unrelated); **DOM restructure verified in the
  running app** (throwaway Playwright: cluster card present, error in Health body, all removed
  ids absent, submit/resume/ensemble/rollup/resume-history inside the cluster card).

## Production-job button mislabeling — FIXED 2026-07-11 (follow-up to Phase 2)
User: selecting a RUNNING production job showed the primary control as "■ Stop Relax" +
grayed "Start Production". Backend was CORRECT (job `7456d0130168` `run_kind='production'`,
seeded from parent) — purely a frontend labeling bug: `mdRunControl` hardcoded verb 'Relax'
+ keyed off `mdJobIsActive` regardless of `run_kind`, and `_renderProductionControls` only
enabled its button for a `completed` job. **Fix (`md_jobs_panel.js`):** the primary control
governs the RELAXATION lifecycle only — `mdRunControl` returns "▶ Relax" DISABLED when a
production child is selected (`mdIsProductionChild`). The Production button becomes that
child's Stop/Resume control via pure `mdProductionAction(job)` → stop (running) / resume
(stopped-failed) / start (relax root or completed→chain); its click branches to
`_stopSelected(prodBtn)`/`_resumeSelected(prodBtn)` (both now take a btn arg). Resume states
get a tooltip "Stopped jobs can be resumed from their last checkpoint." (both the Production
button AND the primary Relax control's Resume). `_paintRunControl` now honours `rc.disabled`.
Tests: `mdRunControl` production-child (disabled) + `mdProductionAction` (4). vitest 2659;
smoke 21 pass (2 pre-existing unrelated). **NOT auto-verified in-app** (per-design job select
is the MV-28 doc-context limit) — user has the live repro to confirm by re-clicking.
