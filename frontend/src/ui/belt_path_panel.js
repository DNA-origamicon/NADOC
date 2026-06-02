/**
 * belt_path_panel.js — Sidebar panel for the "Define Belt Path" feature.
 *
 * An open belt wraps exactly two pulleys. Each pulley is defined by:
 *   - a revolute mate (gives the rotation axis), and
 *   - a rim connector on the rotating body (perpendicular distance to the axis
 *     = pulley radius; also fixes the belt contact phase).
 *
 * Interaction is viewport-driven (the dropdowns mirror/back up the picks):
 *   1. Pulley A — revolute mates glow emphasized; click one.
 *   2. Pulley A — a preview circle follows the mouse from that axis; click a rim
 *      connector to lock the radius.
 *   3–4. Same for pulley B.
 * When both pulleys are set the open belt is previewed as a glowing tube; Create
 * persists it. This phase is DISPLAY-ONLY — no part mating / animation yet.
 *
 * The panel mounts as a sibling after #assembly-panel.
 */
import * as api from '../api/client.js'
import { pulleyCenterRadius, computeBeltPath } from '../scene/belt_geometry.js'

const INPUT_CSS = 'width:100%;background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:3px;padding:4px;font-size:var(--text-xs)'
const LABEL_CSS = 'font-size:var(--text-xs);color:#484f58;text-transform:uppercase;letter-spacing:.05em;margin:8px 0 2px'

const PANEL_HTML = `
  <h2 style="display:flex;align-items:center;justify-content:space-between">
    <span>Define Belt Path</span>
    <button id="belt-close-btn" title="Close" style="background:none;border:none;color:#8b949e;font-size:18px;cursor:pointer;padding:0 4px;line-height:1">&times;</button>
  </h2>
  <div id="belt-hint" style="font-size:var(--text-xs);color:#8b949e;margin-bottom:6px;line-height:1.4"></div>

  <div style="${LABEL_CSS}">Pulley A — revolute mate</div>
  <select id="belt-joint-a" style="${INPUT_CSS}"></select>
  <div style="${LABEL_CSS}">Pulley A — rim connector</div>
  <select id="belt-conn-a" style="${INPUT_CSS}"></select>

  <div style="${LABEL_CSS}">Pulley B — revolute mate</div>
  <select id="belt-joint-b" style="${INPUT_CSS}"></select>
  <div style="${LABEL_CSS}">Pulley B — rim connector</div>
  <select id="belt-conn-b" style="${INPUT_CSS}"></select>

  <div style="${LABEL_CSS}">Name</div>
  <input type="text" id="belt-name" value="Belt" style="${INPUT_CSS}">

  <div id="belt-status" style="font-size:var(--text-xs);color:#8b949e;margin:8px 0;min-height:20px;line-height:1.4"></div>

  <div style="display:flex;gap:8px;margin-top:4px">
    <button id="belt-create-btn" class="panel-action-btn" disabled style="flex:1">Create</button>
    <button id="belt-cancel-btn" class="panel-action-btn" style="flex:1;background:#21262d">Cancel</button>
  </div>
`

export function initBeltPathPanel(store, { jointRenderer, onOpen, onClose }) {
  const panel = document.createElement('div')
  panel.id = 'belt-path-panel'
  panel.className = 'panel-section'
  panel.style.display = 'none'
  panel.innerHTML = PANEL_HTML

  const assemblyPanel = document.getElementById('assembly-panel')
  const propsSection  = document.getElementById('properties-section')
  ;(assemblyPanel ?? propsSection ?? document.body).after?.(panel)
  if (!panel.parentNode) document.body.appendChild(panel)

  const jointASel = panel.querySelector('#belt-joint-a')
  const jointBSel = panel.querySelector('#belt-joint-b')
  const connASel  = panel.querySelector('#belt-conn-a')
  const connBSel  = panel.querySelector('#belt-conn-b')
  const nameInput = panel.querySelector('#belt-name')
  const statusEl  = panel.querySelector('#belt-status')
  const hintEl    = panel.querySelector('#belt-hint')
  const createBtn = panel.querySelector('#belt-create-btn')
  const cancelBtn = panel.querySelector('#belt-cancel-btn')
  const closeBtn  = panel.querySelector('#belt-close-btn')

  let _open = false
  let _editId = null   // belt id when editing an existing path (Apply); null = create

  // ── Dropdown population ─────────────────────────────────────────────────────
  function _populateJointSelect(sel) {
    const options = jointRenderer.enumerateRevoluteEndpoints()
    const prev = sel.value
    sel.innerHTML = ''
    const ph = document.createElement('option')
    ph.value = ''; ph.textContent = '— select revolute mate —'
    sel.appendChild(ph)
    for (const item of options) {
      const opt = document.createElement('option')
      opt.value = _endpointValue(item)
      opt.textContent = item.text
      sel.appendChild(opt)
    }
    sel.value = prev
  }

  function _endpointValue(ep) {
    // Key order must match the markers' endpoint (jointId, instanceId, side).
    return JSON.stringify({ jointId: ep.jointId, instanceId: ep.instanceId, side: ep.side })
  }

  function _populateConnSelect(sel, instanceId) {
    const map = jointRenderer.getConnectorDataMap()
    sel.innerHTML = ''
    const ph = document.createElement('option')
    ph.value = ''; ph.textContent = '— select rim connector —'
    sel.appendChild(ph)
    let any = false
    for (const [key, data] of map) {
      if (instanceId && data.instanceId !== instanceId) continue
      any = true
      const opt = document.createElement('option')
      opt.value = key
      opt.textContent = `${data.instanceLabel} : ${data.label}`
      sel.appendChild(opt)
    }
    if (!any && instanceId) {
      for (const [key, data] of map) {
        const opt = document.createElement('option')
        opt.value = key
        opt.textContent = `${data.instanceLabel} : ${data.label}`
        sel.appendChild(opt)
      }
    }
  }

  function _selectedEndpoint(sel) {
    if (!sel.value) return null
    try { return JSON.parse(sel.value) } catch { return null }
  }

  // ── Geometry resolution ─────────────────────────────────────────────────────
  function _resolvePulley(jointSel, connSel) {
    const ep = _selectedEndpoint(jointSel)
    if (!ep) return { error: 'Select a revolute mate.' }
    const asm = store.getState().currentAssembly
    const joint = asm?.joints?.find(j => j.id === ep.jointId)
    if (!joint) return { error: 'Mate not found.' }
    if (!connSel.value) return { error: 'Select a rim connector.' }
    const conn = jointRenderer.getConnectorDataMap().get(connSel.value)
    if (!conn) return { error: 'Connector not found.' }
    const { center, radius } = pulleyCenterRadius(joint.axis_origin, joint.axis_direction, conn.worldPos)
    return {
      endpoint: ep, connectorKey: connSel.value, connectorLabel: conn.label,
      instanceId: conn.instanceId, axisDir: joint.axis_direction,
      center, radius, connectorWorld: conn.worldPos,
    }
  }

  // ── Phase state machine ─────────────────────────────────────────────────────
  // Phase is derived from which dropdowns are filled. The renderer renders the
  // emphasized markers / mouse circle for the active phase; picks fill dropdowns.
  function _phaseInfo() {
    const epA = _selectedEndpoint(jointASel)
    if (!epA)        return { phase: 'joint', which: 'a' }
    if (!connASel.value) return { phase: 'rim', which: 'a', jointId: epA.jointId, instanceId: epA.instanceId }
    const epB = _selectedEndpoint(jointBSel)
    if (!epB)        return { phase: 'joint', which: 'b', exclude: [epA.jointId] }
    if (!connBSel.value) return { phase: 'rim', which: 'b', jointId: epB.jointId, instanceId: epB.instanceId }
    return { phase: 'done' }
  }

  let _last = { pa: null, pb: null }

  function _lockGeom(p) {
    return { connKey: p.connectorKey, center: [p.center.x, p.center.y, p.center.z], axisDir: p.axisDir, radius: p.radius }
  }

  function _applyPhase() {
    _last = { pa: null, pb: null }
    createBtn.disabled = true

    // Lock each fully-specified pulley's circle + selected-connector highlight so
    // both circles stay drawn (and stay highlighted) until Create/Apply.
    const pa = (jointASel.value && connASel.value) ? _resolvePulley(jointASel, connASel) : null
    const pb = (jointBSel.value && connBSel.value) ? _resolvePulley(jointBSel, connBSel) : null
    jointRenderer.beltSetPulley('a', pa && !pa.error ? _lockGeom(pa) : null)
    jointRenderer.beltSetPulley('b', pb && !pb.error ? _lockGeom(pb) : null)

    const info = _phaseInfo()
    if (info.phase === 'done') {
      jointRenderer.beltSetPhase('idle')
      const epA = _selectedEndpoint(jointASel), epB = _selectedEndpoint(jointBSel)
      if (epA && epB && epA.jointId === epB.jointId) return _fail('Pulley A and B must use different revolute mates.')
      if (!pa || pa.error || !pb || pb.error) return _fail((pa && pa.error) || (pb && pb.error) || 'Incomplete.')
      const belt = computeBeltPath(
        { center: pa.center, radius: pa.radius, axisDir: pa.axisDir },
        { center: pb.center, radius: pb.radius, axisDir: pb.axisDir })
      if (belt.error) return _fail(belt.error)
      jointRenderer.setBeltPreview(belt.points)
      _last = { pa, pb }
      createBtn.disabled = false
      hintEl.textContent = `Belt ready. Adjust any pulley, or press ${_editId ? 'Apply' : 'Create'}.`
      const warn = belt.warning ? ` ⚠ ${belt.warning}` : ''
      statusEl.innerHTML =
        `r<sub>A</sub> = ${pa.radius.toFixed(1)} nm, r<sub>B</sub> = ${pb.radius.toFixed(1)} nm, ` +
        `center distance = ${belt.distance.toFixed(1)} nm.${warn}`
      return
    }

    // Not done — drive the picker and clear the tube preview.
    jointRenderer.setBeltPreview(null)
    if (info.phase === 'joint') {
      jointRenderer.beltSetPhase('joint', { excludeJointIds: info.exclude ?? [] })
      hintEl.textContent = `Click a glowing revolute mate for pulley ${info.which.toUpperCase()}.`
    } else {
      jointRenderer.beltSetPhase('rim', { jointId: info.jointId, instanceId: info.instanceId })
      hintEl.textContent = `Pulley ${info.which.toUpperCase()}: move to set the radius (snaps near a connector), then click a rim connector.`
    }
    statusEl.textContent = ''
  }

  function _fail(msg) {
    jointRenderer.setBeltPreview(null)
    createBtn.disabled = true
    statusEl.innerHTML = msg ? `<span style="color:#f85149">${msg}</span>` : ''
  }

  // ── Viewport pick callbacks ─────────────────────────────────────────────────
  function _onJointPick(endpoint) {
    const info = _phaseInfo()
    if (info.phase !== 'joint') return
    const sel = info.which === 'a' ? jointASel : jointBSel
    const connSel = info.which === 'a' ? connASel : connBSel
    // Ensure the option exists, then select it.
    const val = _endpointValue(endpoint)
    if (![...sel.options].some(o => o.value === val)) {
      const opt = document.createElement('option'); opt.value = val
      opt.textContent = endpoint.instanceId?.slice(0, 6) ?? 'Pulley'
      sel.appendChild(opt)
    }
    sel.value = val
    connSel.value = ''
    _populateConnSelect(connSel, endpoint.instanceId)
    _applyPhase()
  }

  function _onRimPick(conn) {
    const info = _phaseInfo()
    if (info.phase !== 'rim') return
    const connSel = info.which === 'a' ? connASel : connBSel
    const key = `${conn.instanceId}::${conn.label}`
    if (![...connSel.options].some(o => o.value === key)) {
      const opt = document.createElement('option'); opt.value = key
      opt.textContent = `${conn.instanceLabel} : ${conn.label}`
      connSel.appendChild(opt)
    }
    connSel.value = key
    _applyPhase()
  }

  // ── Manual dropdown changes (mirror the pick flow) ──────────────────────────
  jointASel.addEventListener('change', () => {
    connASel.value = ''
    _populateConnSelect(connASel, _selectedEndpoint(jointASel)?.instanceId)
    _applyPhase()
  })
  jointBSel.addEventListener('change', () => {
    connBSel.value = ''
    _populateConnSelect(connBSel, _selectedEndpoint(jointBSel)?.instanceId)
    _applyPhase()
  })
  connASel.addEventListener('change', _applyPhase)
  connBSel.addEventListener('change', _applyPhase)

  createBtn.addEventListener('click', async () => {
    if (!_last.pa || !_last.pb) return
    createBtn.disabled = true
    const body = {
      name: (nameInput.value || 'Belt').trim(),
      pulley_a: _pulleyBody(_last.pa),
      pulley_b: _pulleyBody(_last.pb),
    }
    // Edit mode → PATCH the existing belt; otherwise create a new one. Nothing
    // is sent to the backend until this Create/Apply, so Cancel/Escape reverts.
    const res = _editId ? await api.patchBeltPath(_editId, body) : await api.createBeltPath(body)
    if (res === null) {
      const err = store.getState().lastError
      statusEl.innerHTML = `<span style="color:#f85149">${err?.message ?? 'Failed to save belt path.'}</span>`
      createBtn.disabled = false
      return
    }
    close()
  })

  function _pulleyBody(p) {
    return {
      joint_id: p.endpoint.jointId, side: p.endpoint.side, instance_id: p.instanceId,
      connector_label: p.connectorLabel, radius: p.radius,
      center_world: [p.center.x, p.center.y, p.center.z], connector_world: p.connectorWorld,
    }
  }

  cancelBtn.addEventListener('click', () => close())
  closeBtn.addEventListener('click', () => close())

  // Prefill the four dropdowns from a stored BeltPath (edit mode).
  function _prefill(belt) {
    const set = (jointSel, connSel, pulley) => {
      const ep = { jointId: pulley.joint_id, instanceId: pulley.instance_id, side: pulley.side ?? 'b' }
      const val = _endpointValue(ep)
      if (![...jointSel.options].some(o => o.value === val)) {
        const opt = document.createElement('option'); opt.value = val; opt.textContent = pulley.instance_id?.slice(0, 6) ?? 'Pulley'
        jointSel.appendChild(opt)
      }
      jointSel.value = val
      _populateConnSelect(connSel, pulley.instance_id)
      const key = `${pulley.instance_id}::${pulley.connector_label}`
      if (![...connSel.options].some(o => o.value === key)) {
        const opt = document.createElement('option'); opt.value = key; opt.textContent = pulley.connector_label ?? key
        connSel.appendChild(opt)
      }
      connSel.value = key
    }
    set(jointASel, connASel, belt.pulley_a)
    set(jointBSel, connBSel, belt.pulley_b)
  }

  // ── Open / close ────────────────────────────────────────────────────────────
  function open(belt = null) {
    if (_open) return
    _open = true
    _editId = belt?.id ?? null
    createBtn.textContent = _editId ? 'Apply' : 'Create'
    jointRenderer.enterBeltDefineMode({
      onJointPick: _onJointPick,
      onRimPick:   _onRimPick,
      onCancel:    () => close(),
    })
    _populateJointSelect(jointASel)
    _populateJointSelect(jointBSel)
    if (belt) {
      nameInput.value = belt.name ?? 'Belt'
      _prefill(belt)
    } else {
      jointASel.value = ''; jointBSel.value = ''
      _populateConnSelect(connASel, null)
      _populateConnSelect(connBSel, null)
      nameInput.value = 'Belt'
    }
    statusEl.textContent = ''
    panel.style.display = ''
    onOpen?.()   // e.g. suppress the persistent belt tubes (panel previews live)
    _applyPhase()
  }

  function close() {
    if (!_open) return
    _open = false
    _editId = null
    createBtn.textContent = 'Create'
    jointRenderer.exitBeltDefineMode()
    panel.style.display = 'none'
    onClose?.()
  }

  return { open, close, isOpen: () => _open }
}
