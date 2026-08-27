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

function _shownNs(value) {
  return Number(value).toFixed(2).replace(/\.0+$/, '').replace(/(\.\d*[1-9])0+$/, '$1')
}

/** Requested production length encoded by new payloads, old stage prose, or old names. */
function _productionTargetNs(seg) {
  if (seg?.target_ns != null) {
    const explicit = Number(seg.target_ns)
    if (Number.isFinite(explicit) && explicit >= 0) return explicit
  }
  const text = `${seg?.stage ?? ''} ${seg?.name ?? ''}`
  if (!/production/i.test(text)) return null
  const before = text.match(/([0-9]+(?:\.[0-9]+)?)\s*ns\b[^\n]*?\bproduction\b/i)
  if (before) return Number(before[1])
  const after = text.match(/production(?:_|\s+)([0-9p.]+)\s*ns\b/i)
  return after ? Number(after[1].replace(/p/g, '.')) : null
}

/** Pure: the compact production-stage label shared by the timeline and Latest card.
 *
 * The backend supplies `completed_ns` for live local/RunPod readings, synced or
 * projected Alpine readings, and terminal/interrupted jobs. Keeping the submitted
 * target beside it makes a stopped 245 ns run visibly different from a completed
 * 500 ns run. A tilde is reserved for Alpine progress carried forward while the
 * cluster cannot be synced. */
export function mdProductionStageLabel(seg) {
  const targetNs = _productionTargetNs(seg)
  if (targetNs == null) return null
  if (seg?.completed_ns == null) return `${_shownNs(targetNs)} ns production run`
  const completedNs = Number(seg?.completed_ns)
  if (!Number.isFinite(completedNs) || completedNs < 0) {
    return `${_shownNs(targetNs)} ns production run`
  }
  const estimated = seg?.completed_ns_estimated ? '~' : ''
  return `${estimated}${_shownNs(completedNs)}/${_shownNs(targetNs)} ns production run`
}

function _withCompletedNs(shortLabel, seg) {
  return mdProductionStageLabel(seg) || shortLabel
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
