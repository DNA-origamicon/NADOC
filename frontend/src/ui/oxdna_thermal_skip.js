/** A row's skip command always addresses the active plateau, never the clicked child. */
export function thermalSkipAction(job) {
  if (job?.engine !== 'oxdna' || !job.run_config?.thermal_ramp || job.remote_only) return null
  const current = job.stages?.[job.current_stage_idx]
  const next = job.stages?.[job.current_stage_idx + 1]
  const enabled = ['running', 'stopped', 'failed'].includes(job.status)
    && (!job.execution_target || job.execution_target === 'local')
    && current?.name?.endsWith('_thermal') && next?.name?.endsWith('_thermal')
  return { enabled: !!enabled, stage: current?.name,
    title: enabled ? 'Stop the current temperature and continue to the next. Retain recorded data.'
      : !next ? 'There is no next temperature.' : 'Select a local active or interrupted thermal run.' }
}

export async function skipThermalStage(job, { api, refresh, toast }) {
  const action = thermalSkipAction(job)
  if (!action?.enabled) return
  toast('Skipping the current temperature…')
  try {
    const result = await api.skipOxdnaStage(job.job_id, { expected_stage: action.stage })
    if (!result?.ok) throw new Error(api.lastErrorMessage?.() || 'Could not skip the temperature.')
    toast('The run has advanced to the next temperature.')
    await refresh()
  } catch (error) {
    toast(error.message || 'Could not skip the temperature.', { severity: 'error' })
  }
}
