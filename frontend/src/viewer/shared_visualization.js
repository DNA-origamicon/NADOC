/** Only the published job's display label crosses the sharing boundary. */
const MODES = {
  display: 'Simulation structure', flex: 'Flexibility map (RMSF)', deviation: 'Deviation map',
  strain: 'Strain map', occupancy: 'Occupancy clouds', traj: 'Trajectory',
  'traj-full': 'Full trajectory', photoproduct: 'Photoproduct propensity',
  'ion-paths': 'Nanopore ion paths', 'ion-vector-field': 'Ion vector field',
}
export function captureSharedVisualization(doc, job) {
  if (!job?.id || !['oxdna', 'namd', 'lammps'].includes(job.engine)) return null
  const prefix = job.engine === 'namd' ? 'md' : 'oxdna'
  const mode = doc.querySelector(`input[name="${prefix}-viz"]:checked`)?.value
  if (!Object.hasOwn(MODES, mode)) return null
  const date = typeof job.createdAt === 'number' && job.createdAt > 0 ? new Date(job.createdAt * 1000) : null
  return { engine: job.engine, jobId: String(job.id).slice(0, 200), jobName: String(job.name || job.id).slice(0, 200),
    runDate: date && Number.isFinite(date.getTime()) ? date.toISOString() : null, mode: MODES[mode] }
}
export function validateSharedVisualization(value) {
  if (value == null) return
  if (typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(k => !['engine', 'jobId', 'jobName', 'runDate', 'mode'].includes(k)) ||
      !['oxdna', 'namd', 'lammps'].includes(value.engine) ||
      !['jobId', 'jobName', 'mode'].every(k => typeof value[k] === 'string' && value[k].length > 0 && value[k].length <= 200) ||
      !Object.values(MODES).includes(value.mode) ||
      (value.runDate !== null && (typeof value.runDate !== 'string' || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(value.runDate) || !Number.isFinite(Date.parse(value.runDate))))) throw new Error('Invalid shared visualization label')
}
