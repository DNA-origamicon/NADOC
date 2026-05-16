/**
 * polymerize_panel.js — Sidebar panel for the Polymerize Origami feature.
 *
 * Lifecycle:
 *   - Hidden until Assembly → Polymerize Origami menu fires open().
 *   - When open, listens for orange joint-ring clicks (routed in via
 *     setSelectedJoint from main.js's _onAssemblyPointerDown — see the
 *     polymerizePanel.isOpen() guard there) and populates with the picked
 *     mate's controls. (Joint indicators are the orange shaft + arrowhead
 *     + ring drawn by _buildIndicator in assembly_joint_renderer.js; the
 *     ring is the drag handle for revolute joints.)
 *   - Close (X button, Esc key, or another menu item) clears selection.
 *
 * The panel mounts itself as a sibling immediately after #properties-section
 * in #left-panel so it sits visually right below the Properties panel.
 *
 * Eligibility ("identical parts"):
 *   Mirrors backend _sources_match — file-backed sources match by path;
 *   inline sources match when their design id is the same OR when a
 *   normalized dump compares equal. For UI purposes the check uses what the
 *   frontend already has (inst.source.type + path or inst.source.design.id),
 *   and we let the backend's stricter check be the source of truth at POST
 *   time (the panel re-enables itself based on the server response).
 */

import * as api from '../api/client.js'

const PANEL_HTML = `
  <h2 style="display:flex;align-items:center;justify-content:space-between">
    <span>Polymerize Origami</span>
    <button id="poly-close-btn" title="Close" style="background:none;border:none;color:#8b949e;font-size:18px;cursor:pointer;padding:0 4px;line-height:1">&times;</button>
  </h2>
  <div style="font-size:var(--text-xs);color:#484f58;text-transform:uppercase;letter-spacing:.05em;margin-bottom:2px">Mate</div>
  <select id="poly-mate-select" style="width:100%;background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:3px;padding:4px;font-size:var(--text-xs);margin-bottom:6px">
    <option value="">— Select a mate —</option>
  </select>
  <div id="poly-selection" style="font-size:var(--text-xs);color:#8b949e;margin-bottom:6px">
    Or click an orange joint indicator in the viewport.
  </div>
  <div id="poly-eligibility" style="font-size:var(--text-xs);margin-bottom:8px;min-height:16px"></div>
  <div class="def-row" style="margin-bottom:6px">
    <label style="width:96px">Chain length</label>
    <input type="number" id="poly-count" min="2" max="64" value="3" style="width:60px">
    <span class="unit" style="font-size:var(--text-xs);color:#8b949e;margin-left:4px">total</span>
  </div>
  <div style="font-size:var(--text-xs);color:#484f58;text-transform:uppercase;letter-spacing:.05em;margin:6px 0 2px">Direction</div>
  <div id="poly-direction" style="display:flex;gap:10px;margin-bottom:10px;font-size:var(--text-xs)">
    <label><input type="radio" name="poly-dir" value="forward" checked> Forward</label>
    <label><input type="radio" name="poly-dir" value="backward"> Backward</label>
    <label><input type="radio" name="poly-dir" value="both"> Both</label>
  </div>
  <div style="font-size:var(--text-xs);color:#484f58;text-transform:uppercase;letter-spacing:.05em;margin:6px 0 2px">To pattern</div>
  <div id="poly-pattern-hint" style="font-size:var(--text-xs);color:#8b949e;margin-bottom:4px">
    Optional. Tick any parts to clone alongside each new chain step. Mates between ticked parts and the seed mate's instances are replicated automatically.
  </div>
  <div id="poly-additional-list" style="max-height:140px;overflow-y:auto;border:1px solid #30363d;border-radius:3px;background:#0d1117;padding:3px 4px;margin-bottom:10px;font-size:var(--text-xs)">
    <div style="color:#484f58">— Select a mate to see candidates —</div>
  </div>
  <button id="poly-go-btn" class="panel-action-btn" disabled style="width:100%">Polymerize</button>
  <div id="poly-status" style="font-size:var(--text-xs);color:#8b949e;margin-top:6px;min-height:16px"></div>
`

export function initPolymerizePanel(store) {
  // ── Build panel DOM and mount below #properties-section ────────────────────
  const panel = document.createElement('div')
  panel.id = 'polymerize-panel'
  panel.className = 'panel-section'
  panel.style.display = 'none'
  panel.innerHTML = PANEL_HTML

  const propertiesSection = document.getElementById('properties-section')
  if (propertiesSection) propertiesSection.after(panel)
  else document.body.appendChild(panel)

  const mateSelect    = panel.querySelector('#poly-mate-select')
  const selectionEl   = panel.querySelector('#poly-selection')
  const eligibilityEl = panel.querySelector('#poly-eligibility')
  const countInput    = panel.querySelector('#poly-count')
  const goBtn         = panel.querySelector('#poly-go-btn')
  const statusEl      = panel.querySelector('#poly-status')
  const closeBtn      = panel.querySelector('#poly-close-btn')
  const additionalListEl = panel.querySelector('#poly-additional-list')

  let _open                = false
  let _selectedJointId     = null
  // Set of instance ids the user wants to clone alongside the seed pair.
  let _additionalSelected  = new Set()

  // ── Eligibility check ──────────────────────────────────────────────────────
  function _sourcesIdenticalish(instA, instB) {
    const sA = instA?.source, sB = instB?.source
    if (!sA || !sB) return false
    if (sA.type !== sB.type) return false
    if (sA.type === 'file')   return sA.path === sB.path
    if (sA.type === 'inline') return sA.design?.id === sB.design?.id
    return false
  }

  function _findJoint(asm, jointId) {
    return asm?.joints?.find(j => j.id === jointId) ?? null
  }
  function _findInstance(asm, instId) {
    return asm?.instances?.find(i => i.id === instId) ?? null
  }

  function _rebuildAdditionalList(assembly, selectedJoint) {
    additionalListEl.innerHTML = ''
    if (!selectedJoint) {
      const empty = document.createElement('div')
      empty.style.cssText = 'color:#484f58'
      empty.textContent = '— Select a mate to see candidates —'
      additionalListEl.appendChild(empty)
      return
    }
    const seedIds = new Set([selectedJoint.instance_a_id, selectedJoint.instance_b_id].filter(Boolean))
    const candidates = (assembly?.instances ?? []).filter(i => !seedIds.has(i.id))
    if (!candidates.length) {
      const empty = document.createElement('div')
      empty.style.cssText = 'color:#484f58'
      empty.textContent = '— No other parts to add to the pattern —'
      additionalListEl.appendChild(empty)
      return
    }
    // Prune selected ids that no longer exist (e.g. user deleted a part).
    const liveIds = new Set(candidates.map(i => i.id))
    for (const id of [..._additionalSelected]) {
      if (!liveIds.has(id)) _additionalSelected.delete(id)
    }
    for (const inst of candidates) {
      const row = document.createElement('label')
      row.style.cssText = 'display:flex;align-items:center;gap:6px;padding:2px 0;cursor:pointer'
      const cb = document.createElement('input')
      cb.type    = 'checkbox'
      cb.checked = _additionalSelected.has(inst.id)
      cb.addEventListener('change', () => {
        if (cb.checked) _additionalSelected.add(inst.id)
        else            _additionalSelected.delete(inst.id)
      })
      const nameSpan = document.createElement('span')
      nameSpan.style.cssText = 'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'
      nameSpan.textContent = inst.name
      nameSpan.title       = inst.name
      row.append(cb, nameSpan)
      additionalListEl.appendChild(row)
    }
  }

  function _rebuildMateDropdown(assembly) {
    // Preserve the currently selected option across rebuilds.
    const prev = _selectedJointId
    mateSelect.innerHTML = ''
    const placeholder = document.createElement('option')
    placeholder.value = ''
    placeholder.textContent = '— Select a mate —'
    mateSelect.appendChild(placeholder)

    const joints    = assembly?.joints    ?? []
    const instances = assembly?.instances ?? []
    const instById = Object.fromEntries(instances.map(i => [i.id, i]))
    if (!joints.length) {
      placeholder.textContent = '— No mates in this assembly —'
      mateSelect.disabled = true
      return
    }
    mateSelect.disabled = false
    for (const j of joints) {
      const a = instById[j.instance_a_id]?.name ?? '(world)'
      const b = instById[j.instance_b_id]?.name ?? '(world)'
      const opt = document.createElement('option')
      opt.value = j.id
      opt.textContent = `${j.name}: ${a} ↔ ${b}`
      mateSelect.appendChild(opt)
    }
    mateSelect.value = prev && joints.some(j => j.id === prev) ? prev : ''
  }

  function _renderStateFromStore() {
    if (!_open) return
    const state    = store.getState()
    const assembly = state.currentAssembly
    _rebuildMateDropdown(assembly)
    const joint = _selectedJointId ? _findJoint(assembly, _selectedJointId) : null
    _rebuildAdditionalList(assembly, joint)
    if (!_selectedJointId) {
      selectionEl.textContent = 'Or click an orange joint indicator in the viewport.'
      selectionEl.style.color = '#8b949e'
      eligibilityEl.textContent = ''
      goBtn.disabled = true
      return
    }
    if (!joint) {
      selectionEl.textContent = 'Selected mate no longer exists. Pick another.'
      selectionEl.style.color = '#f85149'
      eligibilityEl.textContent = ''
      goBtn.disabled = true
      return
    }
    const instA = _findInstance(assembly, joint.instance_a_id)
    const instB = _findInstance(assembly, joint.instance_b_id)
    if (!instA || !instB) {
      selectionEl.style.color = '#8b949e'
      selectionEl.textContent = `Mate: ${joint.name}`
      eligibilityEl.style.color = '#f85149'
      eligibilityEl.textContent = '✗ Polymerize requires a mate between two instances.'
      goBtn.disabled = true
      return
    }
    selectionEl.style.color = '#8b949e'
    selectionEl.textContent = `Mate: ${joint.name} — ${instA.name} ↔ ${instB.name}`
    if (_sourcesIdenticalish(instA, instB)) {
      eligibilityEl.style.color = '#3fb950'
      eligibilityEl.textContent = '✓ Identical parts — polymerize enabled.'
      goBtn.disabled = false
    } else {
      // Yellow / amber — warning rather than hard error. The backend will
      // 422 either way; we make it visually clear that the mate exists but
      // the chain math only makes sense between identical parts.
      eligibilityEl.style.color = '#d29922'
      eligibilityEl.textContent = '⚠ Warning: parts are not identical — polymerization needs the same part on both sides.'
      goBtn.disabled = true
    }
  }

  mateSelect.addEventListener('change', () => {
    _selectedJointId = mateSelect.value || null
    // Selecting a different mate clears the pattern checklist — the
    // candidate set changes when the seed pair changes.
    _additionalSelected = new Set()
    statusEl.textContent = ''
    _renderStateFromStore()
  })

  store.subscribe((newState, prevState) => {
    if (!_open) return
    if (newState.currentAssembly !== prevState.currentAssembly) _renderStateFromStore()
  })

  // Warn before kicking off a polymerize that would create a lot of new
  // instances. Empirically the frontend renderer starts struggling around
  // ~8 heavy instances; cheap defaults (the backend forces 'cylinders' on
  // new clones) help, but the cost still adds up for very large parts.
  const _COST_WARN_THRESHOLD = 10  // new instances added by this op

  function _estimatedNewInstanceCount(count, direction, n_additionals) {
    // count includes the existing pair (which isn't new). Each "step"
    // produces 1 new primary + `n_additionals` additional clones.
    const new_total = Math.max(0, count - 2)
    // direction='both' splits the new_total between sides; the per-step
    // clone count is identical either way, so the total new instances is
    // new_total × (1 + n_additionals) regardless of direction.
    return new_total * (1 + n_additionals)
  }

  // ── Polymerize button ──────────────────────────────────────────────────────
  goBtn.addEventListener('click', async () => {
    if (!_selectedJointId) return
    const count     = Math.max(2, Math.min(64, parseInt(countInput.value, 10) || 2))
    const direction = panel.querySelector('input[name="poly-dir"]:checked')?.value || 'forward'
    const additional_instance_ids = [..._additionalSelected]
    const projected = _estimatedNewInstanceCount(count, direction, additional_instance_ids.length)
    if (projected >= _COST_WARN_THRESHOLD) {
      const ok = window.confirm(
        `This polymerize will add ${projected} new part instances ` +
        `(chain ${count}${additional_instance_ids.length ? `, ${additional_instance_ids.length} pattern part(s)` : ''}).\n\n` +
        `New clones default to the cheap 'cylinders' renderer to keep the ` +
        `assembly openable. You can upgrade any individual clone to 'full' ` +
        `via its rep picker afterwards.\n\nContinue?`
      )
      if (!ok) return
    }
    goBtn.disabled = true
    statusEl.style.color = '#8b949e'
    const patSuffix = additional_instance_ids.length
      ? ` + ${additional_instance_ids.length} pattern part(s)` : ''
    statusEl.textContent = `Polymerizing… (${count} total, ${direction}${patSuffix})`
    const res = await api.polymerizeAssembly({
      joint_id: _selectedJointId, count, direction, additional_instance_ids,
    })
    if (!res) {
      const err = store.getState().lastError
      statusEl.style.color = '#f85149'
      statusEl.textContent = err?.message || 'Polymerize failed.'
    } else {
      statusEl.style.color = '#3fb950'
      statusEl.textContent = `Chain extended to ${count} (${direction}${patSuffix}).`
    }
    _renderStateFromStore()
  })

  // ── Open / close ───────────────────────────────────────────────────────────
  function open() {
    if (_open) return
    _open = true
    _selectedJointId = null
    statusEl.textContent = ''
    panel.style.display = ''
    _renderStateFromStore()
    document.addEventListener('keydown', _onKey)
  }

  function close() {
    if (!_open) return
    _open = false
    _selectedJointId = null
    panel.style.display = 'none'
    document.removeEventListener('keydown', _onKey)
  }

  function _onKey(e) {
    if (e.key === 'Escape') close()
  }

  closeBtn.addEventListener('click', close)

  function setSelectedJoint(jointId) {
    if (!_open) return
    _selectedJointId = jointId
    statusEl.textContent = ''
    _renderStateFromStore()
  }

  function isOpen() { return _open }

  return { open, close, isOpen, setSelectedJoint }
}
