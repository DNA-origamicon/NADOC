import { isThermalRun, thermalRunSteps } from './oxdna_thermal_job.js'

/** A temperature selection addresses a real stage of a job, never a synthetic job. */
export function initThermalSelection({ stopTrajectory = () => {}, host = null } = {}) {
  let selectedJob = null, selectedStage = null
  const hint = host ? document.createElement('div') : null
  if (hint) { hint.className = 'thermal-trajectory-selection'; hint.hidden = true; host.prepend(hint) }
  return {
    set(job, stage = null) {
      if (stage && (!isThermalRun(job) || !thermalRunSteps(job).some(s => s.name === stage))) return false
      if (job.job_id === selectedJob && stage !== selectedStage) stopTrajectory()
      selectedJob = job.job_id; selectedStage = stage
      if (hint) {
        hint.hidden = !isThermalRun(job)
        hint.textContent = stage
          ? `Trajectory: ${thermalRunSteps(job).find(s => s.name === stage).temperature} only`
          : 'Trajectory: all temperatures in this Tm run'
      }
      return true
    },
    stageFor(jobId) { return jobId === selectedJob ? selectedStage : null },
    scope(job, fallback = 'job') {
      if (!isThermalRun(job)) return fallback
      return selectedJob === job.job_id && selectedStage ? `thermal:${selectedStage}` : 'thermal'
    },
    hasTrajectory(job, fallback) {
      if (!isThermalRun(job)) return fallback(job)
      const stages = job.stages.filter(s => s.name.endsWith('_thermal')
        && (job.job_id !== selectedJob || !selectedStage || s.name === selectedStage))
      return stages.some(s => ['done', 'running'].includes(s.status) || s.started_at || s.completed_steps > 0)
    },
  }
}
