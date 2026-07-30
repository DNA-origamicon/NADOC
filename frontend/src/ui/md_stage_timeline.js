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

/** Pure: what the "Latest" stat card shows. A live health sample wins, then the last
 *  persisted one, then a RUNNING minimisation — that step emits no health sample, so
 *  without it the card reads "—" for the whole (long) minimisation. */
export function mdLatestStageLabel(job, health, persisted) {
  if (health) return mdShortStage(health.stage)
  if (persisted?.stage) return mdShortStage(persisted.stage)
  const min = mdMinimizationRow(job)
  if (min && min.status === 'running') return mdShortStage(min.stage)
  return '—'
}
