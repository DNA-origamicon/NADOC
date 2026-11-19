import { thermalRunSteps } from './oxdna_thermal_job.js'

/** Project the selected plateau onto the existing progress formatters only.
 * Job identity, run controls and the underlying stage objects stay untouched. */
export function thermalStageProgress(job, stageName, live = null) {
  const row = thermalRunSteps(job)?.find(stage => stage.name === stageName)
  if (!row) return null
  const index = job.stages.findIndex(stage => stage.name === stageName)
  const stage = job.stages[index], total = Math.max(0, Number(stage.steps) || 0)
  const current = index === job.current_stage_idx
  let completed = Math.max(0, Number(stage.completed_steps) || 0)
  if (stage.status === 'done') completed = total
  else if (current && !['waiting', 'skipped'].includes(row.status)) {
    // Live panel progress already includes banked work from resumed attempts.
    const fraction = live?.current_stage_idx === index ? live.stage_fraction : null
    if (fraction != null && Number.isFinite(Number(fraction))) completed = Number(fraction) * total
    else if (job.progress_fraction != null && Number.isFinite(Number(job.progress_fraction))) {
      // The list reports (finished stage count + current stage fraction) / count,
      // not a step-weighted fraction. Undo that formula before applying this budget.
      const finished = job.stages.filter(s => ['done', 'skipped'].includes(s.status)).length
      completed = Math.max(completed, (Number(job.progress_fraction) * job.stages.length - finished) * total)
    }
  }
  completed = Math.max(0, Math.min(total, Math.round(completed)))
  return { ...job, status: row.status === 'waiting' ? 'queued' : row.status,
    production_state: undefined, stages: [{ ...stage, steps: total }], current_stage_idx: 0,
    current_step: completed, steps: total, progress_fraction: total ? completed / total : 0,
    eta_seconds: null, thermal_stage_label: row.temperature }
}
