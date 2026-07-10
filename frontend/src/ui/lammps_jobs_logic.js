/**
 * Pure decision helpers for the LAMMPS (parallel-oxDNA) jobs panel. NO DOM, NO I/O.
 *
 * Inputs are the `/api/lammps/available` payload and `LammpsJob` dicts from
 * `/api/lammps/jobs`; outputs are the small set of display decisions the panel DOM
 * layer needs (run-button state, progress %, row label, poll gate), so the panel
 * stays presentational and these stay unit-tested. Mirrors md_engines_logic.js.
 */

const ACTIVE = ['queued', 'preparing', 'running']

/** Percent complete from current_step / steps, clamped to [0, 100]. */
export function progressPct(job) {
  const total = Number(job?.steps) || 0
  if (total <= 0) return 0
  const cur = Number(job?.current_step) || 0
  return Math.max(0, Math.min(100, Math.round((cur / total) * 100)))
}

/** True while a job is queued/preparing/running (drives polling + the Stop button). */
export function jobIsActive(job) {
  return ACTIVE.includes(job?.status)
}

/** True when a finished run can be visualised (not active, has trajectory frames). */
export function jobIsViewable(job) {
  return !!job && !ACTIVE.includes(job.status) && (job?.frames || 0) > 0
}

/** Status line for the flexibility (RMSF) view from a displayRmsf result. */
export function flexStatusText(r) {
  if (!r || !r.ok) return ''
  const f = (v) => (Number.isFinite(v) ? v : 0).toFixed(3)
  const n = r.nFrames || 0
  const prelim = n < 20 ? ' — preliminary (short run)' : ''
  return `RMSF ${f(r.min)}–${f(r.max)} nm over ${n} frames${prelim}`
}

/** True if any job in the list is still active (gate the poll timer). */
export function anyActive(jobs) {
  return (jobs || []).some(jobIsActive)
}

/**
 * Run-button state from the availability payload:
 *   { enabled, label, title }
 * Disabled (with a reason) when LAMMPS is missing or lacks the CG-DNA package.
 */
export function runButtonState(available) {
  if (!available) return { enabled: false, label: '▶ Run on LAMMPS', title: 'Checking LAMMPS…' }
  if (!available.available) {
    return { enabled: false, label: 'LAMMPS not installed',
             title: 'Build LAMMPS + CG-DNA in the MD Engines panel first.' }
  }
  if (!available.cgdna_capable) {
    return { enabled: false, label: 'No CG-DNA package',
             title: 'This LAMMPS lacks CG-DNA — rebuild with -D PKG_CG-DNA=on.' }
  }
  return { enabled: true, label: '▶ Run on LAMMPS',
           title: 'Run the oxDNA2 force field in LAMMPS (CPU-parallel) on the loaded design.' }
}

/** One-line availability note shown under the heading. */
export function availabilityMessage(available) {
  if (!available) return ''
  if (!available.available) return 'LAMMPS not installed — set it up in the MD Engines panel.'
  if (!available.cgdna_capable) {
    return 'LAMMPS is installed but lacks the CG-DNA package — rebuild with PKG_CG-DNA.'
  }
  return 'LAMMPS ready — CPU-parallel oxDNA for very large assemblies.'
}

/** Short row label for a job in the list. */
export function jobRowLabel(job) {
  const name = job?.design_name || 'design'
  const status = job?.status || 'unknown'
  if (status === 'running' || status === 'preparing') return `${name} — ${status} ${progressPct(job)}%`
  if (status === 'completed') return `${name} — completed (${job?.frames || 0} frames)`
  if (status === 'failed') return `${name} — failed`
  return `${name} — ${status}`
}

/** Max selectable cores from the availability payload (physical-core ceiling).
 *  Falls back to 1 until the probe lands so the input can't over-request. */
export function maxRanks(available) {
  const n = Math.floor(Number(available?.max_ranks))
  return Number.isFinite(n) && n > 0 ? n : 1
}

/** Currently-free cores from the availability payload (for the "use free cores"
 *  button), clamped into [1, maxRanks]. Falls back to the ceiling when absent. */
export function freeRanks(available) {
  const cap = maxRanks(available)
  const n = Math.floor(Number(available?.free_ranks))
  if (!Number.isFinite(n) || n < 1) return cap
  return Math.min(cap, n)
}

/** Guard message for a rank request that exceeds the available cores, else null.
 *  Mirrors the backend 400 so the user never launches a job MPI would refuse. */
export function ranksError(ranks, cores) {
  const r = Math.floor(Number(ranks))
  const c = Math.floor(Number(cores))
  if (!Number.isFinite(r) || r <= (c || 1)) return null
  const s = c === 1 ? '' : 's'
  return `${r} MPI ranks requested but only ${c} CPU core${s} available — reduce to ${c} or fewer.`
}

/** Validate + coerce the Advanced-card inputs (+ optional forces / design path) into
 *  a create-job payload.  `field`/`anchors` are the external-force spec from
 *  lammps_forces_setup; only non-empty ones are attached.  `cores` (when given)
 *  clamps ranks to the physical-core ceiling as a belt-and-suspenders guard. */
export function buildCreatePayload({
  steps, dumpEvery, temperature, salt, ranks, cores = null,
  designSourcePath = null, field = null, anchors = null, wall = null,
} = {}) {
  const posInt = (v, d) => {
    const n = Math.floor(Number(v))
    return Number.isFinite(n) && n > 0 ? n : d
  }
  const pos = (v, d) => {
    const n = Number(v)
    return Number.isFinite(n) && n > 0 ? n : d
  }
  const payload = {
    steps: posInt(steps, 100000),
    dump_every: posInt(dumpEvery, 1000),
    temperature: pos(temperature, 0.1),
    salt_molar: pos(salt, 0.5),
    ranks: Math.max(1, posInt(ranks, 1)),
  }
  const ceiling = Math.floor(Number(cores))
  if (Number.isFinite(ceiling) && ceiling >= 1) payload.ranks = Math.min(payload.ranks, ceiling)
  if (designSourcePath) payload.design_source_path = designSourcePath
  if (field && Number(field.field_pN) > 0) payload.field = field
  if (Array.isArray(anchors) && anchors.length) payload.anchors = anchors
  if (wall && Number(wall.stiff) > 0) payload.wall = wall
  return payload
}
