/** Preparation failures belong to the Box and solvent card, not modal alerts. */
export function createBoxSizeFailureNotifier(report) {
  let previous = null
  return (jobs, scope = null) => {
    const warnings = (jobs || []).filter(job => job.status === 'failed'
      && String(job.error || '').includes('Final box-size check failed:')).map(job => {
      const error = String(job.error)
      const message = error.replace(/^Preparation failed:\s*/, '')
        .replace(/Increase[^.]*wizard tab 2[^.]*\./g, '')
        .trim() + ' Adjust Box and solvent, then update the affected job’s settings before preparing again.'
      return {key:`${job.job_id}:${job.created_at}:${error}`,name:job.design_name || job.job_id,message}
    })
    const signature = JSON.stringify([scope,warnings])
    if(signature !== previous){previous=signature;report?.(warnings)}
  }
}
