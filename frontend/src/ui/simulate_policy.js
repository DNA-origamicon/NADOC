/**
 * Pure presentation helpers for the auto engine-selection policy. NO DOM, NO I/O.
 *
 * Inputs are the `/api/simulate/recommendation` payload; outputs are the resource
 * status-line text, the GPU-busy dialog copy + choices, and the oxDNA→LAMMPS param
 * translation used when a user picks the CPU fallback. Kept pure so they're
 * unit-tested; the coordinator (simulate_launch.js) does the DOM/network.
 */

const _ENGINE = { lammps: 'LAMMPS', oxdna: 'oxDNA' }
const _BACKEND = { CUDA: 'GPU', CPU: 'CPU' }

/** Minimal ETA formatter (mirrors job_activity.formatEta; inlined to keep this pure). */
function _fmtEta(seconds) {
  if (seconds == null || !isFinite(seconds) || seconds < 0) return ''
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60), rs = s % 60
  if (m < 60) return rs ? `${m}m ${rs}s` : `${m}m`
  const h = Math.floor(m / 60), rm = m % 60
  return rm ? `${h}h ${rm}m` : `${h}h`
}

function _gpuState(gpu) {
  if (!gpu || !gpu.available) return 'unknown'
  if (gpu.busy) return gpu.holder_name ? `busy (${gpu.holder_name})` : 'busy'
  return 'free'
}

/** One-line resource + chosen-engine summary shown below the Run button.
 *  Takes the whole `/simulate/recommendation` payload. */
export function statusLineText(payload) {
  const { gpu, free_cores: freeCores, recommendation, has_proteins: hasProteins } = payload || {}
  const rec = recommendation || {}
  const cores = Number.isFinite(+freeCores) && +freeCores > 0 ? Math.floor(+freeCores) : 1
  const eng = `${_ENGINE[rec.engine] || 'oxDNA'} (${_BACKEND[rec.backend] || 'GPU'})`
  let why = 'fastest here'
  if (hasProteins) why = 'required for proteins'
  else if (rec.engine === 'lammps') why = 'GPU busy → CPU fallback'
  return `GPU: ${_gpuState(gpu)} · ${cores} core${cores === 1 ? '' : 's'} free · Engine: ${eng} — ${why}`
}

/** Title + message for the GPU-busy confirmation dialog (cross-engine: CPU = LAMMPS). */
export function recommendationDialogCopy({ hogName, etaSeconds, slowdownFactor, freeCores } = {}) {
  const hog = hogName || 'another job'
  const eta = _fmtEta(etaSeconds)
  const factor = Number.isFinite(+slowdownFactor) && +slowdownFactor > 0 ? Math.round(+slowdownFactor) : null
  const cores = Number.isFinite(+freeCores) && +freeCores > 0 ? Math.floor(+freeCores) : 1
  const remaining = eta ? ` (about ${eta} remaining)` : ' (time remaining unknown)'
  const slower = factor ? `about ${factor}× slower` : 'slower'
  return {
    title: 'The GPU is busy',
    message:
      `The GPU is busy with ${hog}${remaining}.\n\n` +
      `This design runs ${slower} on the CPU — but it runs in parallel across ` +
      `${cores} core${cores === 1 ? '' : 's'} and doesn't wait for the GPU. ` +
      'You can also run on the GPU anyway (it will compete with the current job).',
  }
}

/** The 3 dialog choices, recommended (CPU) first. showChoice returns the `value`. */
export function dialogChoices() {
  return [
    { label: 'Run on CPU (recommended)', value: 'cpu', variant: 'success' },
    { label: 'Run on GPU anyway', value: 'gpu', variant: 'danger' },
    { label: 'Cancel', value: 'cancel' },
  ]
}

/** Translate the oxDNA run form + run-elements into LAMMPS buildCreatePayload args when
 *  the user takes the CPU fallback. LAMMPS runs the same oxDNA2 FF, so step/salt map
 *  directly; oxDNA's relaxation temperature isn't user-exposed, so LAMMPS uses its
 *  reduced-T default (0.1 ≈ 300 K). Forces come in the oxDNA `_oxdnaRunElements` shape
 *  `{field:{field_pN,dir,enabled}, surface:{dir,offsetNm,stiff}, anchors}` and are mapped
 *  to the LAMMPS shape `{field:{field_pN,dir}, wall:{dir,offset_nm,stiff}, anchors}`
 *  (surface→wall, offsetNm→offset_nm). buildCreatePayload coerces/clamps downstream. */
export function translateOxdnaToLammps({ oxdnaForm = {}, forces = {}, freeCores = 1 } = {}) {
  const steps = Number(oxdnaForm.steps) || Number(oxdnaForm.mdRelaxSteps) || 100000
  const salt = Number.isFinite(+oxdnaForm.salt) ? +oxdnaForm.salt : 0.5
  const f = forces.field
  const field = f && Number(f.field_pN) > 0 ? { field_pN: f.field_pN, dir: f.dir } : null
  const s = forces.surface
  const wall = s && Number(s.stiff) > 0 ? { dir: s.dir, offset_nm: s.offsetNm, stiff: s.stiff } : null
  const anchors = Array.isArray(forces.anchors) && forces.anchors.length ? forces.anchors : null
  return { steps, salt, temperature: 0.1, cores: freeCores, ranks: freeCores, field, anchors, wall }
}
