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

/** Pure: is the backend's RunPod session up?
 *
 *  Narrower than `runpodCanLaunch`: that needs EVERY gate green (volume, SSH key, stock,
 *  sizing) because it rents a GPU. Reaching an already-running pod needs only the API
 *  session, so a job whose display is fetching snapshots must not be blocked by, say, a
 *  card being out of stock. */
export function runpodConnected(preflight) {
  return !!preflight?.checks?.find(c => c.key === 'api_key')?.ok
}

/** Pure: chip state for the connection box, mirroring the Alpine chip's vocabulary. */
export function runpodChipState(preflight) {
  if (!preflight) return { state: 'unknown', label: 'runpod: —' }
  const connected = runpodConnected(preflight)
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
const _esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

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

/** Pure: what the live-pod list says, in one line. `null` when nothing is billing.
 *
 *  THE LEAK CHECK. `GET /runpod/pods` has always documented itself as the place a lost pod
 *  id shows up — "anything in this list is billing right now" — and said the UI surfaces it
 *  with a terminate button. It did not: nothing in the frontend called that endpoint or
 *  `/runpod/pods/{id}/terminate`, so the wizard's own "N pods already billing… check the
 *  Clusters card" warning pointed at a card with no pod list and no way to kill one. */
export function podBillingSummary(pods) {
  const live = (pods ?? []).filter(p => p?.id)
  if (!live.length) return null
  // Rounded: this is money, only ever displayed, and summing floats gives things like
  // 2.7299999999999995 for rates that each have two decimals.
  const perHour = Math.round(
    live.reduce((a, p) => a + (Number(p.cost_per_hr) || 0), 0) * 100) / 100
  return {
    count: live.length,
    usdPerHour: perHour,
    text: `${live.length} pod${live.length === 1 ? '' : 's'} billing`
      + (perHour ? ` · $${perHour.toFixed(2)}/hr` : ''),
  }
}

/** Pure: one row per live pod. Each carries its id in `data-pod-id` so the factory can
 *  wire Terminate without re-deriving which row is which. */
export function renderPodRows(pods) {
  return (pods ?? [])
    .filter(p => p?.id)
    .map(p => {
      const rate = Number(p.cost_per_hr)
      // Escaped: id and status come straight from the RunPod API, and this goes into
      // innerHTML. Nothing else in this file interpolates third-party strings.
      const id = _esc(p.id)
      return (
        `<div data-pod-id="${id}" style="display:flex;gap:6px;align-items:center;` +
        `padding:3px 0;border-top:1px solid #21262d">` +
        `<span style="color:#c9d1d9;font-family:monospace;font-size:10px">${id}</span>` +
        `<span style="color:#8b949e;font-size:10px">${_esc(p.status ?? '')}</span>` +
        `<span style="color:#d29922;font-size:10px;margin-left:auto">` +
        `${isFinite(rate) && rate ? `$${rate.toFixed(2)}/hr` : ''}</span>` +
        `<button data-terminate="${id}" title="Destroy this pod now. Billing stops; ` +
        `completed steps stay on the network volume, so the run can be resumed." ` +
        `style="font-size:10px;padding:2px 6px;background:#2d1214;border:1px solid #6e2c2c;` +
        `color:#f85149;border-radius:3px;cursor:pointer">Terminate</button>` +
        `</div>`
      )
    })
    .join('')
}

const _num = value => value == null || value === '' ? NaN : Number(value)
const _money = value => Number.isFinite(_num(value)) ? `$${_num(value).toFixed(2)}` : '—'

/** Selected-job billing view. Empty for a deselection or a non-RunPod job. */
export function runpodJobCostView(job, { balance = null, pods = [], nowMs = Date.now() } = {}) {
  if (!job || job.execution_target !== 'runpod') return null
  const sessions = Array.isArray(job.runpod_billing_sessions) ? job.runpod_billing_sessions : []
  let spent = 0
  for (const s of sessions) {
    const fixed = _num(s?.cost_usd)
    if (Number.isFinite(fixed)) { spent += fixed; continue }
    const rate = _num(s?.usd_per_hour)
    const start = _num(s?.started_at)
    const end = _num(s?.ended_at) || nowMs / 1000
    if (Number.isFinite(rate) && Number.isFinite(start) && end >= start) {
      spent += rate * (end - start) / 3600
    }
  }
  const finalCost = _num(job.runpod_final_cost_usd)
  if (job.status === 'completed') {
    return {
      completed: true,
      rows: [['Actual final cost', _money(Number.isFinite(finalCost) ? finalCost : spent)]],
    }
  }
  const pod = (pods || []).find(p => p?.id && p.id === job.runpod_pod_id)
  const currentRate = _num(pod?.cost_per_hr ?? job.runpod_current_rate_usd_per_hour)
  const bal = balance?.available === true ? _num(balance.balance) : NaN
  return {
    completed: false,
    rows: [
      ['Current balance', _money(bal)],
      ['Estimated total cost', _money(job.runpod_estimated_cost_usd)],
      ['Rented GPU rate', Number.isFinite(currentRate) ? `${_money(currentRate)}/hr` : 'Not rented'],
      ['Spent on this job', _money(spent)],
    ],
  }
}

export function renderRunpodJobCost(job, state) {
  const view = runpodJobCostView(job, state)
  if (!view) return ''
  return `<div data-runpod-job-cost style="margin-top:6px;border:1px solid #30363d;`+
    `border-radius:4px;padding:6px;background:#090c10">`+
    `<div style="font-size:10px;color:#c9d1d9;font-weight:600;margin-bottom:4px">`+
    `${view.completed ? 'RunPod cost' : 'Selected job cost'}</div>`+
    view.rows.map(([label, value]) => `<div style="display:flex;justify-content:space-between;`+
      `gap:12px;font-size:10px;line-height:1.55"><span style="color:#8b949e">${label}</span>`+
      `<span style="color:#c9d1d9;font-family:var(--font-mono)">${value}</span></div>`).join('')+
    `</div>`
}

/**
 * Factory. Owns the pre-flight state and the DOM inside the Clusters card.
 *
 * @param {object}   deps
 * @param {Element}  deps.mount        container to render into
 * @param {Function} deps.fetchImpl    fetch (injectable for tests)
 * @param {Function} deps.onChange     called with the latest preflight whenever it changes
 * @param {Function} deps.confirmImpl  async (message) => boolean, for the Terminate guard
 */
export function initRunpodStatus({
  mount, fetchImpl = fetch, onChange = () => {},
  confirmImpl = (msg) => Promise.resolve(globalThis.confirm?.(msg) ?? false),
} = {}) {
  let _preflight = null
  let _pods = []
  let _balance = null
  let _job = null
  let _busy = false
  let _killing = null

  function _render() {
    if (!mount) return
    const chip = runpodChipState(_preflight)
    const gpus = runpodGpuSummary(_preflight)
    const billing = podBillingSummary(_pods)
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
      ${
        billing
          ? `<div style="margin-top:6px;border:1px solid rgba(248,81,73,.35);border-radius:4px;
               background:rgba(248,81,73,.08);padding:5px 6px">
               <div style="font-size:10px;color:#f85149;margin-bottom:2px">
                 ⚠ ${billing.text} — this is spending money right now.
               </div>
               ${renderPodRows(_pods)}
             </div>`
          : ''
      }
      ${renderRunpodJobCost(_job, { balance: _balance, pods: _pods })}
    `
    mount.querySelector('#runpod-refresh-btn')?.addEventListener('click', () => refresh())
    for (const btn of mount.querySelectorAll('[data-terminate]')) {
      btn.addEventListener('click', () => terminate(btn.getAttribute('data-terminate')))
      if (_killing) { btn.disabled = true; btn.textContent = _killing === btn.getAttribute('data-terminate') ? 'terminating…' : 'Terminate' }
    }
  }

  /** Live pods, or [] when there is no session to ask.  Never throws: a leak check that
   *  errors is worse than one that is blank, and this runs on every pre-flight.
   *
   *  Gated on the pre-flight already saying we are connected. `/runpod/pods` 400s without
   *  a session ("enter an API key first"), and calling it anyway logged a console error on
   *  every single pre-flight — including the overwhelmingly common case of never having
   *  used RunPod at all. This repo's commit gate is zero console errors, so a check that
   *  cannot succeed must not be attempted. Nothing is lost: with no session there is no
   *  client to list pods with, and the reconnect nudge is what covers an orphaned pod. */
  async function _refreshPods() {
    if (runpodChipState(_preflight).state !== 'connected') { _pods = []; return }
    try {
      const res = await fetchImpl('/api/runpod/pods')
      if (!res.ok) { _pods = []; return }
      _pods = (await res.json())?.pods ?? []
    } catch {
      _pods = []
    }
  }

  async function _refreshBalance() {
    if (!runpodConnected(_preflight)) { _balance = null; return }
    try {
      const res = await fetchImpl('/api/runpod/balance')
      _balance = res.ok ? await res.json() : null
    } catch { _balance = null }
  }

  /** Destroy one pod. Confirmed first — this is irreversible and ends a paid run.  It does
   *  NOT lose work: every completed step's .coor is on the network volume, which outlives
   *  the pod, so the job resumes from there (runpod_supervisor's auto-resume relies on the
   *  same property). */
  async function terminate(podId) {
    if (!podId || _killing) return
    const pod = _pods.find(p => p.id === podId)
    const rate = Number(pod?.cost_per_hr)
    const ok = await confirmImpl(
      `Terminate pod ${podId}?\n\n`
      + `Billing stops immediately${isFinite(rate) && rate ? ` (currently $${rate.toFixed(2)}/hr)` : ''}. `
      + 'Steps that already finished are on the network volume and are not lost — the run '
      + 'can be resumed onto a fresh pod.',
    )
    if (!ok) return
    _killing = podId
    _render()
    try {
      await fetchImpl(`/api/runpod/pods/${encodeURIComponent(podId)}/terminate`, { method: 'POST' })
    } catch {
      /* idempotent server-side; the refresh below is the source of truth */
    } finally {
      _killing = null
      await _refreshPods()
      await _refreshBalance()
      _render()
    }
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
      // The leak check rides the pre-flight rather than owning a poller: a pod is only
      // ever created by a launch from this app, so re-checking when the user asks about
      // RunPod is often enough — and it costs one request, not a standing timer.
      await _refreshPods()
      await _refreshBalance()
      _render()
      onChange(_preflight)
    }
    return _preflight
  }

  _render()

  return {
    refresh,
    setJob(job) { _job = job || null; _render() },
    async refreshBilling() { await Promise.all([_refreshPods(), _refreshBalance()]); _render() },
    get preflight() {
      return _preflight
    },
    get pods() {
      return _pods
    },
    billing: () => podBillingSummary(_pods),
    terminate,
    canLaunch: () => runpodCanLaunch(_preflight),
    blockReason: () => runpodBlockReason(_preflight),
    chip: () => runpodChipState(_preflight),
  }
}
