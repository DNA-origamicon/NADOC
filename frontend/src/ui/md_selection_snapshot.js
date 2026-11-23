/** The visible job list already owns saved metadata, including parent settings.
 * Seed missing panel records from that snapshot; live panel records stay authoritative.
 * Selection must not wait for an unrelated all-job status/provenance refresh.
 */
export function mergeMdSelectionSnapshot(jobs, jobId, snapshotJobs = []) {
  if (!snapshotJobs.some(job => job.engine === 'namd' && job.job_id === jobId)) return jobs
  const known = new Set(jobs.map(job => job.job_id))
  const missing = snapshotJobs.filter(job => {
    if (job.engine !== 'namd' || !job.job_id || known.has(job.job_id)) return false
    known.add(job.job_id)
    return true
  })
  return missing.length ? [...jobs, ...missing] : jobs
}
