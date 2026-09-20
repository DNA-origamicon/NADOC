/** Pure trajectory sizing, timing, and analysis-progress presentation. */
// Production runs at the timestep chosen in the Advanced card: 4 fs fast (default),
// 2 fs medium, or 1 fs conservative.  (This was hard-coded to 1 fs, which under-reported
// every fast production run's simulated time by 4x.)
export const DEFAULT_PRODUCTION_TIMESTEP_FS = 4.0
/** Pure: simulated ns for a raw NAMD step count at a given production timestep (fs). */
export function productionNsFromSteps(steps, timestepFs = DEFAULT_PRODUCTION_TIMESTEP_FS) {
  const ts = Number(timestepFs) > 0 ? Number(timestepFs) : DEFAULT_PRODUCTION_TIMESTEP_FS
  return (Number(steps) || 0) * ts / 1_000_000
}

/** Pure presentation model for the NAMD photoproduct loading indicator. */
export function photoproductProgressView(progress = {}) {
  const fraction = Math.max(0, Math.min(1, Number(progress.fraction) || 0))
  const percent = Math.round(fraction * 100)
  const units = {
    screening: 'frames',
    measuring: 'frames',
    aggregating: 'pairs',
    serializing: 'bases',
    coloring: 'bases',
  }
  const unit = units[progress.phase]
  const count = Number(progress.total) > 0
    ? ` · ${Number(progress.done) || 0}/${Number(progress.total)}${unit ? ` ${unit}` : ''}`
    : ''
  return {
    percent,
    count,
    message: progress.message || 'Preparing photoproduct visualization',
    tone: progress.phase === 'error' ? 'error'
      : progress.phase === 'complete' ? 'complete' : 'active',
  }
}
// "View trajectory" frame interval: load every Nth frame of each written segment, the
// same idea as the stride field when a DCD is imported into VMD.  The DEFAULT lives in
// index.html's `value=` attribute (form_defaults reads el.defaultValue) — this constant is
// only the fallback for an unreadable/empty field.
/** A segment is PRODUCTION dynamics iff its stage label says so — the same rule as the
 *  backend's `md_production_segments`, so the panel cannot offer a view the analysis
 *  refuses. Every builder that emits a production segment puts the word in its label
 *  ("… production run", "… production replica (seed n)", "… conservative production N ns
 *  unrestrained", "shell NVT production (…)"). */
export const MD_PRODUCTION_MARKER = 'production'

/**
 * Does this job have PRODUCTION frames? Pure.
 *
 * Occupancy clustering is only meaningful over free dynamics. A POSITIVE test, because
 * restraint is encoded in the label as `k=<value>` — `50K NVT k=5.0`,
 * `310K NPT k=5.0 → … → 0.01`, `Vacuum ENRG-MD shape relaxation` — and no reasonable list
 * of "restrained" keywords catches them all. Excluding by keyword admitted every one of
 * those on the real job set; matching "production" admits exactly the runs the
 * Run-production button (and the ensemble/replica builders) create.
 *
 * A segment counts only once it has written frames (done/running): a queued production
 * run is not sampling yet.
 */
export function mdHasProductionRun(job) {
  return (job?.segments || []).some((seg) => {
    if (seg?.status !== 'done' && seg?.status !== 'running') return false
    return String(seg.stage ?? seg.name ?? '').toLowerCase().includes(MD_PRODUCTION_MARKER)
  })
}

export const DEFAULT_TRAJ_INTERVAL = 20
// Past this many frames a load is slow and memory-hungry enough to be worth confirming
// rather than silently starting.  Warn, don't cap — the user asked for the frames.
export const TRAJ_FRAME_CONFIRM = 500
/** Pure: how many frames a given interval will actually load, given each written
 *  segment's raw DCD frame count.  Mirrors the backend's `_composite_indices` stride
 *  branch exactly — every segment is strided on its own (so a non-empty segment always
 *  keeps at least its own frame 0), hence ceil per segment rather than over the total. */
export function stridedFrameCount(rawCountsPerSegment, interval) {
  const s = Math.max(1, Math.floor(Number(interval)) || 1)
  if (!Array.isArray(rawCountsPerSegment)) return 0
  return rawCountsPerSegment.reduce((n, c) => {
    const raw = Math.floor(Number(c)) || 0
    return n + (raw > 0 ? Math.ceil(raw / s) : 0)
  }, 0)
}
/** Pure: the production timestep a prepared job will actually use — its stored
 *  `production_timestep_fs` (Advanced card), or the legacy fast?4:1 derivation for
 *  jobs prepared before that field existed. */
export function jobProductionTimestepFs(job) {
  const pp = job?.prep_params
  const ts = Number(pp?.production_timestep_fs)
  if (ts === 1 || ts === 2 || ts === 4) return ts
  if (pp) return pp.fast ? 4.0 : 1.0
  return DEFAULT_PRODUCTION_TIMESTEP_FS
}
/** Pure: the production timestep the ETA, the "x ns" readout and the Start-Production
 *  POST must ALL use.
 *
 *  The DROPDOWN wins. It is the control the user operates, and it is now sent with the
 *  production request, so the estimate is computed from the same number the run uses.
 *  This used to return the selected JOB's stored dt while the dropdown reached prep only
 *  — so changing it before starting production moved neither the run nor the estimate,
 *  and a 2 fs selection produced a 1 fs trajectory under a 1 fs ETA (seen on 2hb_1xT).
 *
 *  Falls back to the selected job's stored dt (which also seeds the dropdown on
 *  selection), then the global default — so the value shown for a prepared job that the
 *  user has not touched is unchanged. */
export function effectiveProductionTimestepFs({ selectValue, job } = {}) {
  const sel = Number(selectValue)
  if (sel === 1 || sel === 2 || sel === 4) return sel
  if (job) return jobProductionTimestepFs(job)
  return DEFAULT_PRODUCTION_TIMESTEP_FS
}
