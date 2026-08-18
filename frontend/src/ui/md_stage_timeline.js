/**
 * md_stage_timeline.js — pure derivations for a NAMD job's stage timeline.
 *
 * One reason to change: what the timeline (and the master progress tooltip) says a job
 * is doing. No DOM, no store, no api — every function here is (job → value).
 *
 * Exists as its own module because two panels need the same answer: `md_jobs_panel`
 * draws the timeline rows, `simulate_jobs` writes the master progress bar's tooltip.
 */

/** Pure: the timeline's leading MINIMISATION row, or null when the job has none.
 *
 *  The minimisation (for an ensemble replica: its velocity reseed) runs BEFORE segment 1
 *  and is not a member of `job.segments` — the backend keeps it in its own manifest slot
 *  because the runner indexes that list. Without this row a large-box run shows an
 *  all-pending timeline for the tens of minutes it spends minimising, which is
 *  indistinguishable from a stuck job. Jobs prepared before the backend recorded it
 *  return null (the timeline simply omits the row).
 *
 *  Status is INFERRED, not merely echoed, because only the local runner stamps the
 *  record: a segment that has started is proof the minimisation finished — the ladder
 *  chains from its .coor — which keeps an Alpine/RunPod run truthful without needing a
 *  second status-writing path on the cluster side.
 */
export function mdMinimizationRow(job) {
  const min = job?.minimization
  if (!min?.name) return null
  const segs = job?.segments ?? []
  const anySegmentStarted = segs.some(s => s.status === 'running' || s.status === 'done'
                                        || s.status === 'failed')
  let status = min.status || 'pending'
  if (anySegmentStarted) status = 'done'
  else if (status === 'pending' && job?.status === 'running') status = 'running'
  else if (status !== 'done' && job?.status === 'failed') status = 'failed'
  return { name: min.name, stage: min.stage || 'Minimization', steps: min.steps ?? 0, status }
}

/** Pure: shorten a stage name for the narrow "Latest" stat card. */
export function mdShortStage(stage) {
  return String(stage ?? '—')
    .replace(/^300K NPT MGHH-only handoff$/i, '300K NPT k=0')
    .replace(/^310K NPT (?:conservative )?production ([0-9.]+) ns(?: unrestrained)?$/i, '$1 ns production run')
    .replace(/^310K NPT\s+/i, '')
    .replace(/\s+unrestrained$/i, '')
}

/** Pure: swap a "N ns production run" label for what actually completed, when the
 *  named segment carries it. ``Terminate run and download`` (and a timed-out remote
 *  job whose walltime cut a production segment short) decorates that segment with
 *  ``completed_ns`` — see the backend's ``_decorate_terminal_segment_progress`` — but
 *  a bare stage string can't tell "ran to its submitted target" from "cut short", so
 *  the raw label alone would keep reporting the submitted total forever. Falls back
 *  to the raw label when no segment matches or it carries no completed_ns yet (a run
 *  still in progress, or a job persisted before this decoration existed). */
function _withCompletedNs(shortLabel, seg) {
  const completedNs = Number(seg?.completed_ns)
  if (!Number.isFinite(completedNs) || completedNs < 0) return shortLabel
  const m = /^([0-9.]+)\s*ns production run$/.exec(shortLabel)
  if (!m) return shortLabel
  const shown = completedNs.toFixed(2).replace(/\.0+$/, '').replace(/(\.\d*[1-9])0+$/, '$1')
  return `${shown} ns production complete`
}

function _segmentByName(job, name) {
  return name ? (job?.segments ?? []).find(s => s.name === name) ?? null : null
}

/** Pure: what the "Latest" stat card shows. A live health sample wins, then the last
 *  persisted one, then a RUNNING minimisation — that step emits no health sample, so
 *  without it the card reads "—" for the whole (long) minimisation.
 *
 *  Last resort: the segment the job says it is on. That is carried on every running job
 *  regardless of whether anything has measured it yet, so "Latest" should never be
 *  unknown mid-run — it used to read "—" (and, on an active job, spin) for the entire
 *  first segment of a production run, which produces exactly one health sample at its
 *  very end. */
export function mdLatestStageLabel(job, health, persisted) {
  if (health) return _withCompletedNs(mdShortStage(health.stage), _segmentByName(job, health.segment))
  if (persisted?.stage) return _withCompletedNs(mdShortStage(persisted.stage), _segmentByName(job, persisted.segment))
  const min = mdMinimizationRow(job)
  if (min && min.status === 'running') return mdShortStage(min.stage)
  const seg = job?.segments?.[job?.current_segment_idx]
  if (seg?.stage) return _withCompletedNs(mdShortStage(seg.stage), seg)
  return '—'
}
