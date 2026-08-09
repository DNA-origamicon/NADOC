/**
 * Compute-cluster (Alpine) connection UI — Phase 1 of the remote-execution backend.
 *
 * A small status chip (grey=disconnected, amber=connecting, green=connected,
 * amber=expired) mounted in the MD panel, plus a connect modal (host prefilled,
 * user, password, Duo Push/passcode). Talks to the Phase-1 backend routes
 * `/api/cluster/{status,connect,disconnect,profiles}`.
 *
 * Factory: `initClusterConnection({ mount, fetchImpl })` → `{ refresh, getState, dispose }`.
 * `main.js` gets only an import + a one-line init.
 *
 * Pure helpers (`chipStyleForState`, `whoLabel`, `connectPayload`) are exported for
 * unit tests — no DOM required.
 */

const STATE_STYLE = {
  disconnected: { label: 'Cluster: Disconnected', color: '#8b949e', bg: '#161b22', border: '#30363d', clickable: true },
  connecting:   { label: 'Cluster: Connecting…',  color: '#d29922', bg: '#1c1a10', border: '#9e7a1e', clickable: false },
  connected:    { label: 'Cluster: Connected',    color: '#3fb950', bg: '#12261a', border: '#238636', clickable: true },
  expired:      { label: 'Cluster: Reconnect',    color: '#d29922', bg: '#1c1a10', border: '#9e7a1e', clickable: true },
}

/** Pure: map a connection state string → chip visual style. */
export function chipStyleForState(state) {
  return STATE_STYLE[state] || STATE_STYLE.disconnected
}

/** Pure: human label for the connected identity, or '' when not connected. */
export function whoLabel(status) {
  if (!status || !status.who) return ''
  return String(status.who)
}

/** Pure: an actionable one-liner for an expired/failed session, from the status
 * snapshot's `error_kind` + `last_error`. Empty string when the session is fine. */
export function expiryMessage(status) {
  if (!status || (status.state !== 'expired' && status.state !== 'disconnected')) return ''
  if (!status.last_error && !status.error_kind) return ''
  const base = {
    timeout: 'Session timed out',
    network: 'Connection lost',
    auth: 'Authentication expired',
    permission: 'Permission denied',
    filesystem: 'Remote filesystem error',
  }[status.error_kind] || 'Session ended'
  return status.last_error ? `${base} — ${status.last_error}` : base
}

/** Pure: build the POST /cluster/connect body from raw form values. */
export function connectPayload({ clusterName = 'alpine', host = '', user = '', password = '', duoMethod = 'push' } = {}) {
  const body = { cluster_name: clusterName, user: user.trim(), password }
  const h = host.trim()
  if (h) body.host = h
  const duo = (duoMethod || 'push').trim()
  body.duo_method = duo || 'push'
  return body
}

// Instance counter: there can now be more than one chip on screen at once (the
// Clusters card and the Job Wizard's first step), and they must not collide on a DOM
// id or echo each other's broadcasts forever.
let _chipSeq = 0

export function initClusterConnection({ mount, fetchImpl = fetch } = {}) {
  if (!mount) return { refresh: async () => {}, getState: () => 'disconnected', dispose: () => {} }

  const instanceId = `cc${++_chipSeq}`

  let state = 'disconnected'
  let status = { state: 'disconnected', who: null, host: null }
  let defaultHost = 'login.rc.colorado.edu'

  const chip = document.createElement('button')
  chip.type = 'button'
  // The first chip keeps the canonical id (selectors and tests use it); any additional
  // chip gets a unique one, because duplicate ids silently break querySelector.
  chip.id = _chipSeq === 1 ? 'md-cluster-chip' : `md-cluster-chip-${instanceId}`
  chip.style.cssText =
    'width:100%;text-align:left;font-size:var(--text-xs);padding:4px 8px;border-radius:3px;cursor:pointer;font-weight:600'
  mount.appendChild(chip)

  const _json = async (r) => { try { return await r.json() } catch { return {} } }

  // True while we are mirroring a sibling chip, to suppress the echo.
  let adopting = false

  /**
   * Adopt another chip's state.  Signing in through the Job Wizard has to light up the
   * Clusters card and vice versa: only the chip that owns the live session polls, so
   * without this a second chip would sit on a stale "Disconnected" indefinitely.
   */
  function adopt(detail) {
    if (!detail || detail.source === instanceId) return
    const next = detail.state || 'disconnected'
    const nextWho = detail.status?.who ?? null
    if (next === state && nextWho === (status?.who ?? null)) return
    state = next
    status = detail.status || { state: next, who: null, host: null }
    adopting = true
    try { render() } finally { adopting = false }
  }

  function render() {
    const s = chipStyleForState(state)
    const who = whoLabel(status)
    chip.textContent = who && state === 'connected' ? `Cluster: ${who}` : s.label
    chip.style.color = s.color
    chip.style.background = s.bg
    chip.style.border = `1px solid ${s.border}`
    chip.style.cursor = s.clickable ? 'pointer' : 'default'
    chip.disabled = !s.clickable
    const expiry = expiryMessage(status)
    chip.title =
      state === 'connected' ? 'Click to disconnect from the cluster'
      : state === 'expired' ? `${expiry || 'Session expired'} — click to reconnect`
      : expiry ? `${expiry} — click to reconnect`
      : 'Click to connect to the CU Alpine cluster'
    // Notify listeners (e.g. the MD panel's Alpine run-target toggle) so they can
    // enable/disable promptly on connect/disconnect/expiry.  `source` lets sibling
    // chips tell our broadcast from their own; adopting a sibling's state must not
    // re-broadcast or two chips would ping-pong forever.
    if (!adopting) {
      window.dispatchEvent(new CustomEvent('nadoc:cluster-state-change',
        { detail: { state, status, source: instanceId } }))
    }
  }

  async function refresh() {
    try {
      const r = await fetchImpl('/api/cluster/status')
      status = await _json(r)
      state = status.state || 'disconnected'
    } catch {
      /* leave last-known state; backend unreachable */
    }
    render()
    return state
  }

  async function loadDefaultHost() {
    try {
      const r = await fetchImpl('/api/cluster/profiles')
      const j = await _json(r)
      const alpine = (j.profiles || []).find((p) => p.name === 'alpine') || (j.profiles || [])[0]
      if (alpine && alpine.host) defaultHost = alpine.host
    } catch { /* keep hardcoded default */ }
  }

  // ── connect modal ────────────────────────────────────────────────────────────
  function openModal() {
    const overlay = document.createElement('div')
    overlay.style.cssText =
      'position:fixed;inset:0;background:rgba(0,0,0,0.55);z-index:10000;display:flex;align-items:center;justify-content:center'
    const box = document.createElement('div')
    box.style.cssText =
      'background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:16px;width:320px;font-size:var(--text-xs);color:#c9d1d9'
    box.innerHTML = `
      <div style="font-weight:600;font-size:13px;margin-bottom:10px">Connect to Alpine (CURC)</div>
      <label style="display:block;margin-bottom:2px;color:#8b949e">Host</label>
      <input id="cl-host" value="${defaultHost}" style="width:100%;margin-bottom:8px;background:#161b22;border:1px solid #30363d;color:#c9d1d9;border-radius:3px;padding:4px 6px">
      <label style="display:block;margin-bottom:2px;color:#8b949e">Username</label>
      <input id="cl-user" autocomplete="username" style="width:100%;margin-bottom:8px;background:#161b22;border:1px solid #30363d;color:#c9d1d9;border-radius:3px;padding:4px 6px">
      <label style="display:block;margin-bottom:2px;color:#8b949e">Password</label>
      <input id="cl-pass" type="password" autocomplete="current-password" style="width:100%;margin-bottom:8px;background:#161b22;border:1px solid #30363d;color:#c9d1d9;border-radius:3px;padding:4px 6px">
      <label style="display:block;margin-bottom:2px;color:#8b949e">Duo — "push" or 6-digit passcode</label>
      <input id="cl-duo" value="push" style="width:100%;margin-bottom:10px;background:#161b22;border:1px solid #30363d;color:#c9d1d9;border-radius:3px;padding:4px 6px">
      <div id="cl-err" style="color:#f85149;min-height:14px;margin-bottom:8px"></div>
      <div style="display:flex;gap:6px;justify-content:flex-end">
        <button id="cl-cancel" style="padding:4px 10px;background:#161b22;border:1px solid #30363d;color:#c9d1d9;border-radius:3px;cursor:pointer">Cancel</button>
        <button id="cl-go" style="padding:4px 10px;background:#12261a;border:1px solid #238636;color:#3fb950;border-radius:3px;cursor:pointer;font-weight:600">Connect</button>
      </div>`
    overlay.appendChild(box)
    document.body.appendChild(overlay)

    // The same login modal is opened from both the sidebar chip and the Job Wizard
    // chip. Keep every keystroke entered into its credentials fields from reaching
    // the document-level shortcut registry (some shortcuts intentionally remain
    // active in ordinary inputs).
    box.querySelectorAll('input').forEach(input => {
      input.addEventListener('keydown', e => e.stopPropagation())
    })

    const close = () => overlay.remove()
    const errEl = box.querySelector('#cl-err')
    box.querySelector('#cl-cancel').onclick = close
    overlay.onclick = (e) => { if (e.target === overlay) close() }
    box.querySelector('#cl-user').focus()

    box.querySelector('#cl-go').onclick = async () => {
      errEl.textContent = ''
      const payload = connectPayload({
        host: box.querySelector('#cl-host').value,
        user: box.querySelector('#cl-user').value,
        password: box.querySelector('#cl-pass').value,
        duoMethod: box.querySelector('#cl-duo').value,
      })
      if (!payload.user || !payload.password) {
        errEl.textContent = 'Username and password are required.'
        return
      }
      state = 'connecting'; render()
      errEl.textContent = 'Waiting for Duo approval…'
      try {
        const r = await fetchImpl('/api/cluster/connect', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        if (!r.ok) {
          const j = await _json(r)
          errEl.textContent = j.detail || `Connect failed (${r.status})`
          await refresh()
          return
        }
        status = await _json(r)
        state = status.state || 'connected'
        render()
        close()
      } catch (e) {
        errEl.textContent = `Connect failed: ${e?.message || e}`
        await refresh()
      }
    }
  }

  async function disconnect() {
    try { await fetchImpl('/api/cluster/disconnect', { method: 'POST' }) } catch { /* ignore */ }
    await refresh()
  }

  chip.onclick = () => {
    if (state === 'connected') disconnect()
    else openModal()
  }

  // initial paint + async status/profile fetch
  render()
  loadDefaultHost()
  refresh()

  // Poll status while connected so a backend-detected expiry (a supervisor SSH op
  // that hit a broken pipe / timeout and flipped the session to EXPIRED) surfaces
  // on the chip without waiting for a user action. Cheap local call; only fires
  // while connected — once expired/disconnected the user must act.
  const pollTimer = setInterval(() => { if (state === 'connected') refresh() }, 15000)

  const onSiblingState = (e) => adopt(e?.detail)
  window.addEventListener('nadoc:cluster-state-change', onSiblingState)

  return {
    refresh,
    getState: () => state,
    dispose: () => {
      clearInterval(pollTimer)
      window.removeEventListener('nadoc:cluster-state-change', onSiblingState)
      chip.remove()
    },
  }
}
