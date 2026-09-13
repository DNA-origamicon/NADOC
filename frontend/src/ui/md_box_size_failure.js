/** Preparation happens after the wizard closes; report fixed-cell failures on job polls. */
export function createBoxSizeFailureNotifier(alert = message => window.alert(message)) {
  const shown = new Set()
  return jobs => {
    for (const job of jobs || []) {
      const error = String(job.error || '')
      if (job.status !== 'failed' || !error.includes('Final box-size check failed:')) continue
      const key = `${job.job_id}:${job.created_at}:${error}`
      if (shown.has(key)) continue
      shown.add(key)
      alert(`Initial box size needs attention — ${job.design_name || job.job_id}\n\n`
        + error.replace(/^Preparation failed:\s*/, '')
        + '\n\nPreparation stopped before solvation or submission. Open the job settings, '
        + 'increase the indicated dimensions in tab 2, and prepare again.')
    }
  }
}
