// Keep a newly requested job visible until the server's list includes its saved ID.
let serial = 0
const pending = new Map()
let generation = 0
if (typeof window !== 'undefined') {
  for (const event of ['nadoc:document-reset', 'nadoc:workspace-path-change']) {
    window.addEventListener(event, () => { generation++; pending.clear() })
  }
}
export function mergeCreatingJobs(jobs, engine) {
  for (const job of jobs) if (!pending.get(job.job_id)?.creating) pending.delete(job.job_id)
  return [...pending.values()].filter(j => (!engine || j.engine === engine)
    && !jobs.some(saved => saved.job_id === j.job_id)).concat(jobs)
}
export async function withCreatingJob(engine, body, request) {
  const startedGeneration = generation
  const id = `creating-${++serial}`
  const node = { ...body, engine, job_id: id, status: 'preparing', creating: true,
    design_name: body?.design_name || 'New job', created_at: Date.now() / 1000,
    kind: 'relax', stages: [], viewable: false, prep_params: body, run_config: body }
  const emit = detail => {
    if (startedGeneration === generation && typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('nadoc:sim-job-creation', { detail }))
  }
  pending.set(id, node)
  emit({ node })
  try {
    const result = await request()
    const job = result?.job || result
    pending.delete(id)
    if (job?.job_id && startedGeneration === generation) pending.set(job.job_id, { ...job, engine })
    emit({ removeJobId: id, node: job?.job_id ? { ...job, engine } : null })
    return result
  } finally {
    if (pending.delete(id)) emit({ removeJobId: id, node: null })
  }
}
