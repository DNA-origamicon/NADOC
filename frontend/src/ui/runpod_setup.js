/**
 * RunPod first-time-setup wizard.
 *
 * WHY THIS EXISTS: the RunPod backend (connect / preflight / launch) has always worked,
 * but nothing in the UI ever called it — a new user had no path to enter a key, and no
 * guidance on the prerequisites that produce a SILENTLY BILLING, broken pod (no credit,
 * an SSH key not registered in Settings, no network volume carrying the patched NAMD).
 * This wizard walks them through each one and validates the result against the existing
 * pre-flight gate.
 *
 * The wizard GUIDES and VALIDATES; it does not provision. Building the patched multi-arch
 * NAMD onto a network volume is a one-time terminal step (experiments/exp43_runpod_bench/
 * build_multiarch_namd.py) — the wizard links to it and lets the user pick the finished
 * volume from a dropdown.
 *
 * Pure helpers (validateApiKeyFormat, balanceStatus, volumeOptions, setupStepState) are
 * exported for unit tests — no DOM, no network. The factory owns the modal + the fetches.
 *
 * The API key is NEVER persisted on the frontend. We hold it in a closure variable for the
 * modal's lifetime so the finalize-with-volume call can re-send it, then it is dropped.
 * The backend owns storage: it reads $RUNPOD_API_KEY / ~/.runpod_key at startup and
 * connects itself, so this modal is usually only needed once, or to switch accounts.
 */

import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'

const LINKS = {
  billing: 'https://www.runpod.io/console/user/billing',
  settings: 'https://www.runpod.io/console/user/settings',
  storage: 'https://www.runpod.io/console/user/storage',
}

// ── Pure ─────────────────────────────────────────────────────────────────────

/** Pure: does the key look plausible before we spend a round-trip on it?
 *  Mirrors the backend `min_length=8`. */
export function validateApiKeyFormat(key) {
  return typeof key === 'string' && key.trim().length >= 8
}

/** Pure: turn the /runpod/balance payload into a level + one-liner.
 *  RunPod destroys every pod the instant the balance hits zero. */
export function balanceStatus(balance) {
  if (!balance || balance.available !== true) {
    return { level: 'unknown', text: `Balance: unknown${balance?.reason ? ` — ${balance.reason}` : ''}` }
  }
  const usd = Number(balance.balance) || 0
  if (usd <= 0) {
    return { level: 'warn', text: 'No credit — RunPod destroys every pod at $0. Add credit before renting.' }
  }
  if (usd < 25) {
    return { level: 'warn', text: `Balance: $${usd.toFixed(2)} — low. A multi-day run can outlast this.` }
  }
  return { level: 'ok', text: `Balance: $${usd.toFixed(2)}` }
}

/** Pure: map the account's volumes to <select> options. */
export function volumeOptions(volumes) {
  return (volumes ?? []).map(v => {
    const name = v.name || v.id
    const size = v.size_gb != null ? `${v.size_gb} GB` : '? GB'
    const dc = v.data_center_id ? ` (${v.data_center_id})` : ''
    return { value: v.id, label: `${name} — ${size}${dc}` }
  })
}

/** Pure: per-step status for the checklist — 'done' | 'blocked' | 'pending'. */
export function setupStepState({ connected, balance, sshPresent, volumeId, s3Configured, preflight } = {}) {
  const credit =
    !balance || balance.available !== true ? 'pending'
      : (Number(balance.balance) || 0) > 0 ? 'done' : 'blocked'
  return {
    credit,
    apikey: connected ? 'done' : 'pending',
    ssh: sshPresent === true ? 'done' : sshPresent === false ? 'blocked' : 'pending',
    volume: volumeId ? 'done' : 'pending',
    s3: s3Configured === true ? 'done' : 'pending',
    verify: preflight?.ok ? 'done' : preflight ? 'blocked' : 'pending',
  }
}

// ── Factory ──────────────────────────────────────────────────────────────────

const _C = { ok: '#3fb950', warn: '#d29922', bad: '#f85149', dim: '#8b949e', fg: '#c9d1d9', link: '#58a6ff' }
const _DOT = { done: _C.ok, blocked: _C.bad, pending: _C.dim }

const _esc = (s) =>
  String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

/**
 * @param {object}   deps
 * @param {Element}  deps.mount        container the "Set up RunPod" button renders into
 * @param {Function} deps.fetchImpl    fetch (injectable for tests)
 * @param {Function} deps.onConnected  called after a green pre-flight, so the caller can
 *                                     refresh its own RunPod status/gate
 */
export function initRunpodSetup({ mount, fetchImpl = fetch, onConnected = () => {} } = {}) {
  let _apiKey = ''
  let _keySource = 'none'
  let _editingApi = false
  let _connected = false
  let _balance = null
  let _ssh = null            // { present, public_key } | null
  let _volumes = []
  let _volumeId = ''
  let _preflight = null
  let _s3 = null
  let _s3AccessKey = ''
  let _s3SecretKey = ''
  let _s3Error = ''
  let _editingS3 = false
  let _busy = ''             // '' | 'verify' | 'volume' | 'preflight'
  let _verifyError = ''
  let _modal = null

  async function _post(path, body) {
    const res = await fetchImpl(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    })
    const json = await res.json().catch(() => ({}))
    return { status: res.status, ok: res.ok, body: json }
  }

  async function _get(path) {
    const res = await fetchImpl(path)
    const json = await res.json().catch(() => ({}))
    return { status: res.status, ok: res.ok, body: json }
  }

  async function verifyKey() {
    if (!validateApiKeyFormat(_apiKey)) return
    _busy = 'verify'; _render()
    const r = await _post('/api/runpod/connect', { api_key: _apiKey.trim() })
    _busy = ''
    if (!r.ok) {
      _connected = false
      _verifyError = r.body?.detail || `HTTP ${r.status}`
      _render()
      return
    }
    _verifyError = ''
    _connected = true
    _keySource = 'manual'
    _editingApi = false
    // The key is now held server-side, so these three unlock together.
    const [bal, vols, ssh, s3] = await Promise.all([
      _get('/api/runpod/balance'),
      _get('/api/runpod/volumes'),
      _get('/api/runpod/ssh-public-key'),
      _get('/api/runpod/s3/status'),
    ])
    _balance = bal.body
    _volumes = vols.body?.volumes ?? []
    _ssh = ssh.body
    _s3 = s3.body
    _render()
  }

  async function configureS3() {
    if (!_volumeId || !_s3AccessKey.trim() || !_s3SecretKey.trim()) return
    _busy = 's3'; _s3Error = ''; _render()
    const r = await _post('/api/runpod/s3/configure', {
      access_key: _s3AccessKey.trim(), secret_key: _s3SecretKey.trim(),
    })
    _busy = ''
    if (r.ok) {
      _s3 = r.body
      _s3AccessKey = ''; _s3SecretKey = ''
      _editingS3 = false
    } else {
      _s3Error = r.body?.detail || `HTTP ${r.status}`
    }
    _render()
  }

  async function selectVolume(id) {
    _volumeId = id
    if (!id) { _render(); return }
    _busy = 'volume'; _render()
    const r = await _post('/api/runpod/volume', { network_volume_id: id })
    if (!r.ok) _verifyError = r.body?.detail || `Could not save volume (HTTP ${r.status})`
    _busy = ''
    _render()
  }

  async function _loadExistingSetup() {
    _busy = 'loading'; _render()
    try {
      const [status, s3] = await Promise.all([
        _get('/api/runpod/status'), _get('/api/runpod/s3/status'),
      ])
      _s3 = s3.ok ? s3.body : null
      if (status.ok && status.body?.connected) {
        _connected = true
        _keySource = status.body.key_source || 'configured'
        _volumeId = status.body.network_volume_id || ''
        const [bal, vols, ssh] = await Promise.all([
          _get('/api/runpod/balance'), _get('/api/runpod/volumes'),
          _get('/api/runpod/ssh-public-key'),
        ])
        _balance = bal.body
        _volumes = vols.body?.volumes ?? []
        _ssh = ssh.body
      }
    } catch {
      // The blank/missing-key state remains actionable when the backend is unavailable.
    } finally {
      _busy = ''
      _render()
    }
  }

  async function _runPreflight() {
    _busy = 'preflight'; _render()
    const r = await _post('/api/runpod/preflight', {})
    _busy = ''
    _preflight = r.body
    _render()
    if (_preflight?.ok) onConnected(_preflight)
  }

  function _copyPubKey() {
    if (_ssh?.public_key && navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(_ssh.public_key).catch(() => {})
    }
  }

  function _stepRow(status, n, title) {
    return `<span style="display:inline-flex;align-items:center;gap:5px;font-size:11px;color:${_C.fg}">
      <span style="width:8px;height:8px;border-radius:50%;background:${_DOT[status]};display:inline-block"></span>
      ${n}. ${title}</span>`
  }

  function _checklist() {
    const s = setupStepState({
      connected: _connected, balance: _balance, sshPresent: _ssh?.present,
      volumeId: _volumeId, s3Configured: _s3?.configured, preflight: _preflight,
    })
    return `<div style="display:flex;flex-wrap:wrap;gap:10px 16px;padding:8px 10px;background:#0d1117;
      border:1px solid #30363d;border-radius:6px;margin-bottom:12px">
      ${_stepRow(s.credit, 1, 'Credit')}
      ${_stepRow(s.apikey, 2, 'API key')}
      ${_stepRow(s.ssh, 3, 'SSH key')}
      ${_stepRow(s.volume, 4, 'Volume')}
      ${_stepRow(s.s3, 5, 'S3 transfer')}
      ${_stepRow(s.verify, 6, 'Pre-flight')}
    </div>`
  }

  function _link(href, text) {
    return `<a href="${href}" target="_blank" rel="noopener" style="color:${_C.link}">${text}</a>`
  }

  function _section(n, title, inner) {
    return `<div style="margin-bottom:14px">
      <div style="font-size:12px;font-weight:600;color:${_C.fg};margin-bottom:5px">${n}. ${title}</div>
      <div style="font-size:11px;color:${_C.dim};line-height:1.5">${inner}</div>
    </div>`
  }

  function _balanceLine() {
    if (!_connected) return ''
    const b = balanceStatus(_balance)
    const col = b.level === 'ok' ? _C.ok : b.level === 'warn' ? _C.warn : _C.dim
    return `<div style="margin-top:5px;color:${col}">${_esc(b.text)}</div>`
  }

  function _sshBlock() {
    if (!_connected) return `<span style="color:${_C.dim}">Verify your API key first.</span>`
    if (!_ssh || _ssh.present === false || !_ssh.public_key) {
      return `No local key found. Create one in a terminal:
        <div style="margin-top:4px;font-family:monospace;background:#0d1117;border:1px solid #30363d;
          border-radius:4px;padding:6px;color:${_C.fg}">ssh-keygen -t ed25519</div>
        then re-open this wizard.`
    }
    return `Paste this public key into ${_link(LINKS.settings, 'RunPod Settings → SSH Public Keys')}
      (RunPod injects it at pod creation — a pod without it refuses every login):
      <div style="margin-top:4px;display:flex;gap:6px;align-items:flex-start">
        <textarea readonly id="rp-setup-pubkey" style="flex:1;height:46px;resize:none;font-family:monospace;
          font-size:10px;background:#0d1117;border:1px solid #30363d;border-radius:4px;color:${_C.fg};
          padding:6px">${_esc(_ssh.public_key)}</textarea>
        <button id="rp-setup-copy" style="font-size:11px;padding:4px 8px;background:#21262d;border:1px solid #30363d;
          color:${_C.fg};border-radius:4px;cursor:pointer">Copy</button>
      </div>`
  }

  function _volumeBlock() {
    if (!_connected) return `<span style="color:${_C.dim}">Verify your API key first.</span>`
    const opts = volumeOptions(_volumes)
    const rows = [`<option value="">— select a volume —</option>`]
      .concat(opts.map(o => `<option value="${_esc(o.value)}" ${o.value === _volumeId ? 'selected' : ''}>${_esc(o.label)}</option>`))
    const empty = opts.length === 0
      ? `<div style="margin-top:4px;color:${_C.warn}">No volumes on this account yet — create one in
          ${_link(LINKS.storage, 'RunPod → Storage')}.</div>`
      : ''
    return `The volume must carry the patched multi-arch NAMD + packages (a one-time build —
      see <code>experiments/exp43_runpod_bench/build_multiarch_namd.py</code>). Create it in
      ${_link(LINKS.storage, 'RunPod → Storage')}, then pick it here:
      <div style="margin-top:5px">
        <select id="rp-setup-volume" style="width:100%;font-size:11px;background:#0d1117;border:1px solid #30363d;
          color:${_C.fg};border-radius:4px;padding:5px">${rows.join('')}</select>
      </div>${empty}
      ${_busy === 'volume' ? `<div style="margin-top:4px;color:${_C.dim}">saving…</div>` : ''}`
  }

  function _preflightBlock() {
    const canRun = _connected && !!_volumeId && _s3?.configured === true
    const rows = (_preflight?.checks ?? []).map(c =>
      `<div style="display:flex;gap:6px;align-items:baseline">
        <span style="color:${c.ok ? _C.ok : _C.bad};width:10px">${c.ok ? '✓' : '✗'}</span>
        <span style="color:${_C.fg};min-width:130px">${_esc(c.label)}</span>
        <span style="color:${_C.dim}">${_esc(c.detail ?? '')}</span>
      </div>`).join('')
    return `Run the pre-flight gate — it proves the job can actually launch (key, volume, SSH,
      GPU arch, stock) before anything is rented. Podless transfer must be configured first,
      so a long result download cannot keep the GPU billing:
      <div style="margin-top:6px">
        <button id="rp-setup-preflight" ${canRun ? '' : 'disabled'}
          style="font-size:11px;padding:5px 10px;border-radius:4px;cursor:${canRun ? 'pointer' : 'not-allowed'};
          background:${canRun ? '#238636' : '#21262d'};border:1px solid ${canRun ? '#2ea043' : '#30363d'};
          color:${canRun ? '#fff' : '#484f58'}">${_busy === 'preflight' ? 'checking…' : 'Run pre-flight'}</button>
      </div>
      ${rows ? `<div style="margin-top:8px;display:flex;flex-direction:column;gap:2px">${rows}</div>` : ''}
      ${_preflight?.ok ? `<div style="margin-top:8px;color:${_C.ok};font-weight:600">✓ You're ready — RunPod jobs can now launch.</div>` : ''}`
  }

  function _s3Block() {
    const configured = _s3?.configured
    if (configured && !_editingS3) return `✓ Podless volume transfer is configured${_s3.access_key_hint ? ` (${_esc(_s3.access_key_hint)})` : ''}.
      This is an additional credential used only for direct volume uploads and downloads;
      the RunPod API key above still manages pods and billing.
      <button id="rp-setup-s3-change" style="margin-left:6px;font-size:10px;padding:2px 6px;background:#21262d;
        border:1px solid #30363d;color:${_C.fg};border-radius:3px;cursor:pointer">Replace S3 key</button>`
    if (!_connected || !_volumeId) return `<span style="color:${_C.dim}">Connect and select a volume first.</span>`
    return `RunPod's S3 key is <b>additional to</b>, not a replacement for, the API key above. In
      ${_link(LINKS.settings, 'RunPod → Settings')}, expand <b>S3 API Keys</b>, choose
      <b>Create an S3 API key</b>, then save both values: the access key/user ID begins
      <code>user_</code> and the secret begins <code>rps_</code>. RunPod shows the secret only once.
      NADOC validates access to the selected volume without renting compute and stores the pair in
      <code>~/.config/nadoc/runpod_s3.json</code> with owner-only permissions.
      <div style="margin-top:6px;display:grid;grid-template-columns:1fr 1fr auto;gap:6px">
        <input id="rp-setup-s3-access" autocomplete="off" placeholder="user_…" value="${_esc(_s3AccessKey)}"
          style="font:11px monospace;background:#0d1117;border:1px solid #30363d;color:${_C.fg};border-radius:4px;padding:6px">
        <input id="rp-setup-s3-secret" type="password" autocomplete="new-password" placeholder="rps_…" value="${_esc(_s3SecretKey)}"
          style="font:11px monospace;background:#0d1117;border:1px solid #30363d;color:${_C.fg};border-radius:4px;padding:6px">
        <button id="rp-setup-s3-verify" style="font-size:11px;padding:5px 10px;background:#1f6feb;border:1px solid #388bfd;color:#fff;border-radius:4px;cursor:pointer">
          ${_busy === 's3' ? 'checking…' : 'Verify & save'}</button>
      </div>
      ${_s3Error ? `<div style="margin-top:5px;color:${_C.bad}">${_esc(_s3Error)}</div>` : ''}`
  }

  function _apiBlock() {
    if (_connected && !_editingApi) return `✓ API access is already configured (${_esc(_keySource)}).
      This key manages pods, balance, stock, and volumes.
      <button id="rp-setup-api-change" style="margin-left:6px;font-size:10px;padding:2px 6px;background:#21262d;
        border:1px solid #30363d;color:${_C.fg};border-radius:3px;cursor:pointer">Use a different API key</button>`
    return `Create a key at ${_link(LINKS.settings, 'RunPod → Settings → API Keys')},
      paste it below, and verify. Saving it to <code>~/.runpod_key</code> (chmod 600) lets NADOC
      reconnect by itself on every restart — and kill a pod left billing after a crash.
      <div style="margin-top:6px;display:flex;gap:6px;align-items:center">
        <input id="rp-setup-key" type="password" placeholder="rp_..." value="${_esc(_apiKey)}"
          style="flex:1;font-size:11px;font-family:monospace;background:#0d1117;border:1px solid #30363d;
          color:${_C.fg};border-radius:4px;padding:6px">
        <button id="rp-setup-verify" style="font-size:11px;padding:5px 10px;background:#1f6feb;border:1px solid #388bfd;
          color:#fff;border-radius:4px;cursor:pointer">${_busy === 'verify' ? 'verifying…' : 'Verify'}</button>
      </div>${_verifyError ? `<div style="margin-top:5px;color:${_C.bad}">${_esc(_verifyError)}</div>` : ''}`
  }

  function _render() {
    if (!_modal) return
    const body = _modal.body
    body.innerHTML = `
      ${_checklist()}
      ${_section(1, 'Add credit', `RunPod bills per second and destroys every pod at $0 balance.
        Add credit at ${_link(LINKS.billing, 'RunPod → Billing')}.${_balanceLine()}`)}
      ${_section(2, 'API key', _apiBlock())}
      ${_section(3, 'Register your SSH key', _sshBlock())}
      ${_section(4, 'Network volume', _volumeBlock())}
      ${_section(5, 'Podless uploads and downloads', _s3Block())}
      ${_section(6, 'Verify the pipeline', _preflightBlock())}
    `

    const keyInput = body.querySelector('#rp-setup-key')
    if (keyInput) keyInput.addEventListener('input', (e) => { _apiKey = e.target.value })
    body.querySelector('#rp-setup-verify')?.addEventListener('click', () => verifyKey())
    body.querySelector('#rp-setup-api-change')?.addEventListener('click', () => { _editingApi = true; _render() })
    body.querySelector('#rp-setup-copy')?.addEventListener('click', () => _copyPubKey())
    body.querySelector('#rp-setup-volume')?.addEventListener('change', (e) => selectVolume(e.target.value))
    body.querySelector('#rp-setup-s3-access')?.addEventListener('input', (e) => { _s3AccessKey = e.target.value })
    body.querySelector('#rp-setup-s3-secret')?.addEventListener('input', (e) => { _s3SecretKey = e.target.value })
    body.querySelector('#rp-setup-s3-verify')?.addEventListener('click', () => configureS3())
    body.querySelector('#rp-setup-s3-change')?.addEventListener('click', () => { _editingS3 = true; _render() })
    body.querySelector('#rp-setup-preflight')?.addEventListener('click', () => _runPreflight())
  }

  function openWizard() {
    _verifyError = ''
    _modal = createModal({
      title: 'Set up RunPod',
      size: 'lg',
      body: document.createElement('div'),
      actions: [createButton({ label: 'Close', onClick: () => _modal.close() })],
      onClose: () => { _apiKey = ''; _s3AccessKey = ''; _s3SecretKey = ''; _modal = null },
    })
    _render()
    _modal.open()
    _loadExistingSetup()
  }

  function _renderButton() {
    if (!mount) return
    mount.innerHTML = `
      <button id="rp-setup-open" title="First-time RunPod setup — API key, SSH key, volume, pre-flight"
        style="font-size:11px;padding:4px 9px;background:#21262d;border:1px solid #30363d;color:${_C.fg};
        border-radius:4px;cursor:pointer">Set up RunPod…</button>`
    mount.querySelector('#rp-setup-open')?.addEventListener('click', () => openWizard())
  }

  _renderButton()

  return {
    open: openWizard,
    dispose: () => { if (_modal) _modal.close() },
  }
}
