/**
 * RunPod status + pre-flight, rendered inside the Clusters card.
 *
 * WHY THIS EXISTS: a pod bills from the moment it is created. Every check below maps to
 * a failure that ALREADY cost a real, billing pod — a wrong-architecture GPU that boots
 * and dies at step 0; a missing SSH key on a pod that refuses every connection; no
 * network volume, so the pod has neither NAMD nor any packages. The job of this panel is
 * to turn each of those into a red row BEFORE anything is rented, and to keep the Run
 * button disabled until they are all green.
 *
 * Pure core (chip state, row rendering, gating) is separated from the factory so the
 * decisions are unit-tested without a DOM or a network.
 */

/** Pure: chip state for the connection box, mirroring the Alpine chip's vocabulary. */
export function runpodChipState(preflight) {
  if (!preflight) return { state: 'unknown', label: 'runpod: —' }
  const connected = preflight.checks?.find(c => c.key === 'api_key')?.ok
  if (!connected) return { state: 'disconnected', label: 'runpod: disconnected' }
  if (!preflight.ok) return { state: 'warn', label: 'runpod: not ready' }
  return { state: 'connected', label: 'runpod: ready' }
}

/** Pure: can a job be launched on RunPod right now? */
export function runpodCanLaunch(preflight) {
  return !!preflight?.ok
}

/** Pure: why the Run button is disabled — shown as its tooltip, so the user is never
 *  left guessing which check failed. */
export function runpodBlockReason(preflight) {
  if (!preflight) return 'RunPod pre-flight has not run yet'
  const failed = (preflight.checks ?? []).filter(c => !c.ok)
  if (!failed.length) return ''
  return failed.map(c => `${c.label}: ${c.detail}`).join('\n')
}

/** Pure: the GPU line — which cards we would ask for, and whether they are in stock.
 *  Only sm_89 cards are ever offered (the patched NAMD build is single-arch), so this
 *  list is deliberately short. */
export function runpodGpuSummary(preflight) {
  const gpus = preflight?.gpus ?? []
  if (!gpus.length) return ''
  return gpus
    .map(g => `${g.label} ${g.available ? `(${g.stock})` : '(none)'} $${g.usd_per_hour}/hr`)
    .join(' · ')
}

const _ICON = ok => (ok ? '✓' : '✗')
const _COLOR = ok => (ok ? '#3fb950' : '#f85149')

/** Pure: the check rows as HTML. */
export function renderPreflightRows(preflight) {
  const checks = preflight?.checks ?? []
  if (!checks.length) return '<div style="color:#8b949e">No pre-flight yet.</div>'
  return checks
    .map(
      c =>
        `<div style="display:flex;gap:6px;align-items:baseline">` +
        `<span style="color:${_COLOR(c.ok)};width:10px">${_ICON(c.ok)}</span>` +
        `<span style="color:#c9d1d9;min-width:120px">${c.label}</span>` +
        `<span style="color:#8b949e">${c.detail ?? ''}</span>` +
        `</div>`,
    )
    .join('')
}

/**
 * Factory. Owns the pre-flight state and the DOM inside the Clusters card.
 *
 * @param {object}   deps
 * @param {Element}  deps.mount        container to render into
 * @param {Function} deps.fetchImpl    fetch (injectable for tests)
 * @param {Function} deps.onChange     called with the latest preflight whenever it changes
 */
export function initRunpodStatus({ mount, fetchImpl = fetch, onChange = () => {} } = {}) {
  let _preflight = null
  let _busy = false

  function _render() {
    if (!mount) return
    const chip = runpodChipState(_preflight)
    const gpus = runpodGpuSummary(_preflight)
    mount.innerHTML = `
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:5px">
        <span style="font-size:var(--text-xs);color:${_COLOR(chip.state === 'connected')}">
          ● ${chip.label}
        </span>
        <button id="runpod-refresh-btn" style="font-size:10px;padding:2px 6px;background:#161b22;
          border:1px solid #30363d;color:#8b949e;border-radius:3px;cursor:pointer">
          ${_busy ? 'checking…' : 'Re-check'}
        </button>
      </div>
      ${gpus ? `<div style="font-size:10px;color:#8b949e;margin-bottom:5px">GPU: ${gpus}</div>` : ''}
      <div style="font-size:10px;display:flex;flex-direction:column;gap:2px">
        ${renderPreflightRows(_preflight)}
      </div>
      ${
        _preflight?.note
          ? `<div style="font-size:9px;color:#6e7681;margin-top:5px;line-height:1.35">${_preflight.note}</div>`
          : ''
      }
    `
    mount.querySelector('#runpod-refresh-btn')?.addEventListener('click', () => refresh())
  }

  /** Ask the backend whether a job could run right now. Never throws — a network failure
   *  is a FAILED pre-flight, not an exception that leaves the UI in limbo. */
  async function refresh(nAtoms = null) {
    _busy = true
    _render()
    try {
      const res = await fetchImpl('/api/runpod/preflight', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(nAtoms ? { n_atoms: nAtoms } : {}),
      })
      _preflight = await res.json()
    } catch {
      _preflight = {
        ok: false,
        checks: [{ key: 'api_key', ok: false, label: 'RunPod', detail: 'backend unreachable' }],
        gpus: [],
        note: '',
      }
    } finally {
      _busy = false
      _render()
      onChange(_preflight)
    }
    return _preflight
  }

  _render()

  return {
    refresh,
    get preflight() {
      return _preflight
    },
    canLaunch: () => runpodCanLaunch(_preflight),
    blockReason: () => runpodBlockReason(_preflight),
    chip: () => runpodChipState(_preflight),
  }
}
