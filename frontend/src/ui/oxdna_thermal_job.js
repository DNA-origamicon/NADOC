/** Presentation of a thermal job's real managed stages; no synthetic job IDs. */
export function isThermalRun(job) {
  return (!job?.engine || job.engine === 'oxdna') && !!job?.run_config?.thermal_ramp
}

export function thermalRunNumbers(jobs = []) {
  const counts = new Map(), numbers = new Map()
  for (const job of (jobs || []).filter(j => (!j.engine || j.engine === 'oxdna') && (j.parent_job_id || isThermalRun(j))).sort((a, b) =>
    (a.created_at || 0) - (b.created_at || 0) || a.job_id.localeCompare(b.job_id))) {
    const design = job.design_source_path || job.project_id || job.design_name || ''
    const next = (counts.get(design) || 0) + 1
    counts.set(design, next)
    if (isThermalRun(job)) numbers.set(job.job_id, next)
  }
  return numbers
}

export function thermalRunSignature(job) {
  if (!isThermalRun(job)) return ''
  return JSON.stringify([job.run_config.thermal_ramp, job.current_stage_idx,
    (job.stages || []).map(s => [s.name, s.status, s.started_at, s.completed_steps, s.steps]),
    job.run_config.thermal_progress])
}

export function thermalRunSteps(job) {
  if (!isThermalRun(job)) return null
  const cfg = job.run_config.thermal_ramp
  const start = Number(cfg.start_c), end = Number(cfg.end_c), increment = Number(cfg.step_c)
  return (job.stages || []).flatMap((stage, index) => {
    const match = /^(\d+)_thermal$/.exec(stage.name)
    if (!match) return [] // A later ordinary production stage is not part of the ramp.
    const report = job.run_config.thermal_progress?.[stage.name]
    const recorded = /^([\d.+-]+)K$/.exec(stage.temperature || report?.temperature || '')
    const celsius = recorded ? Number(recorded[1]) - 273.15
      : [start, end, increment].every(Number.isFinite) && increment > 0
        ? start + Math.sign(end - start) * Math.min((Number(match[1]) - 1) * increment, Math.abs(end - start)) : null
    const current = index === job.current_stage_idx
    let status = 'waiting'
    if (stage.status === 'skipped') status = 'skipped'
    else if (stage.status === 'done') status = 'completed'
    else if (stage.status === 'failed' || (current && job.status === 'failed')) status = 'failed'
    else if (current && ['stopped', 'paused'].includes(job.status)) status = job.status
    else if (job.status === 'running' && (stage.status === 'running' || (current && stage.started_at))) status = 'running'
    const temperature = celsius != null && Number.isFinite(celsius)
      ? `${Number(celsius.toFixed(6))} °C` : 'Temperature unavailable'
    return [{ name: stage.name, number: Number(match[1]), temperature, status, steps: stage.steps, ...(status === 'skipped' && job.run_config.melt_stop && index > job.stages.findIndex(s => s.name === job.run_config.melt_stop.stage) ? {reason: 'Melt threshold reached; later temperature not run'} : {}) }]
  })
}
