/**
 * Pure decision helpers for the MD Engines panel + sidebar gates. NO DOM, NO I/O.
 *
 * The backend `GET /api/engines/status` payload (see backend/core/engines.py) is
 * the single input. These functions turn it into the small set of decisions the
 * UI needs — which install action an engine wants, the copy-paste command text,
 * a human GPU summary, and per-sidebar-section readiness — so the DOM layer in
 * md_engines.js stays presentational and these stay unit-tested.
 */

// Display order for the status panel (required engines first, CG pipeline in the
// middle, bundled/optional last).
export const ENGINE_ORDER = [
  'oxdna', 'lammps_oxdna', 'namd', 'gromacs',
  'mrdna', 'arbd', 'cuda',
  'psfgen', 'dnanalysis',
]

/** Human one-liner about the local GPU, used at the top of the panel. */
export function gpuSummary(gpu) {
  if (!gpu || !gpu.present) return 'No CUDA GPU detected — engines will run on CPU.'
  const names = (gpu.names || []).join(', ') || 'CUDA GPU'
  if (!gpu.toolkit) {
    return `GPU detected (${names}), but the CUDA toolkit (nvcc) is missing — ` +
      'install it to build the much faster GPU engines.'
  }
  return `GPU detected (${names}) with CUDA toolkit — GPU builds available.`
}

/**
 * Which install affordance an engine needs:
 *   'installed' — nothing to do
 *   'auto'      — one-click build we can run here (try-auto)
 *   'download'  — license-gated download (NAMD) → instructions popup
 *   'guided'    — paste commands (GROMACS, or auto blocked by missing prereqs)
 *
 * A *degraded* engine (installed but CPU-only while a GPU is present) is treated
 * like a not-installed one for the affordance — it carries an `install` plan that
 * rebuilds it for CUDA — so the panel offers the rebuild instead of "Installed".
 */
export function actionKind(engine) {
  if (!engine) return 'installed'
  if (engine.installed && !engine.degraded) return 'installed'
  const inst = engine.install || {}
  if (inst.method === 'auto' && inst.can_auto) return 'auto'
  if (inst.method === 'download') return 'download'
  return 'guided'
}

/**
 * Button label for an engine's action.
 *
 * A *degraded* engine's rebuild wording defaults to the oxDNA case (installed but
 * CPU-only on a GPU box → "Rebuild for GPU"). Engines whose degradation isn't about
 * the GPU (e.g. LAMMPS built without the CG-DNA package) override it via the plan's
 * `degraded_action_label` / `degraded_guided_label` so the backend owns the wording.
 */
export function actionLabel(engine) {
  const degraded = !!engine?.degraded
  const inst = engine?.install || {}
  switch (actionKind(engine)) {
    case 'installed': return 'Installed'
    case 'auto':      return degraded ? (inst.degraded_action_label || `Rebuild for GPU (${inst.target})`)
                                      : `Install (${inst.target})`
    case 'download':  return 'Download…'
    default:          return degraded ? (inst.degraded_guided_label || 'Enable GPU…') : 'How to install…'
  }
}

/** Newline-joined command block for the copy button / <pre>. */
export function commandText(engine) {
  return (engine?.install?.commands || []).join('\n')
}

/** Status dot color key for an engine: 'ok' | 'warn' | 'err'. */
export function statusTone(engine) {
  // Installed but CPU-only while a GPU is present: it works, just not full-speed.
  if (engine?.degraded) return 'warn'
  if (engine?.installed) return 'ok'
  // A bundled engine (ships inside another) missing is a 'warn', not a hard error.
  if (engine?.required_note && /bundled|ships inside/i.test(engine.required_note)) return 'warn'
  return 'err'
}

/** Note to show under a degraded engine (empty string when not degraded). */
export function degradedNote(engine) {
  return (engine?.degraded && engine?.degraded_note) ? engine.degraded_note : ''
}

/**
 * Readiness of a sidebar section ('oxdna' | 'md') → { ready, missing:[{key,name}] }.
 * Drives whether a panel shows its real controls or the install gate.
 */
export function sectionSummary(status, key) {
  const sec = status && status.sections && status.sections[key]
  if (!sec) return { ready: true, missing: [] }
  const engines = (status && status.engines) || {}
  const missing = (sec.missing || []).map(k => ({ key: k, name: (engines[k] && engines[k].name) || k }))
  return { ready: !!sec.ready, missing }
}

/** Short gate banner text for a not-ready section. */
export function gateMessage(status, key) {
  const { ready, missing } = sectionSummary(status, key)
  if (ready) return ''
  const names = missing.map(m => m.name).join(' + ')
  return `${names} ${missing.length > 1 ? 'are' : 'is'} not installed.`
}
