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
import { showConfirm } from './primitives/confirm.js'

const PANEL_HTML = `
  <h2 style="display:flex;align-items:center;justify-content:space-between">
    <span>Polymerize Origami</span>
    <button id="poly-close-btn" title="Close" style="background:none;border:none;color:#8b949e;font-size:18px;cursor:pointer;padding:0 4px;line-height:1">&times;</button>
  </h2>
  <div style="font-size:var(--text-xs);color:#484f58;text-transform:uppercase;letter-spacing:.05em;margin-bottom:2px">Mate</div>
  <select id="poly-mate-select" style="width:100%;background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:3px;padding:4px;font-size:var(--text-xs);margin-bottom:6px">
    <option value="">— Select a mate or periodic part —</option>
  </select>
  <div id="poly-selection" style="font-size:var(--text-xs);color:#8b949e;margin-bottom:6px">
    Or click an orange joint indicator in the viewport.
  </div>
  <div id="poly-eligibility" style="font-size:var(--text-xs);margin-bottom:8px;min-height:16px"></div>
  <div class="def-row" style="margin-bottom:6px">
    <label style="width:96px">Chain length</label>
    <input type="number" id="poly-count" min="2" value="3" style="width:60px">
    <span class="unit" style="font-size:var(--text-xs);color:#8b949e;margin-left:4px">total</span>
  </div>
  <div id="poly-direction-label" style="font-size:var(--text-xs);color:#484f58;text-transform:uppercase;letter-spacing:.05em;margin:6px 0 2px">Direction</div>
  <div id="poly-direction" style="display:flex;gap:10px;margin-bottom:10px;font-size:var(--text-xs)">
    <label><input type="radio" name="poly-dir" value="forward" checked> Forward</label>
    <label><input type="radio" name="poly-dir" value="backward"> Backward</label>
    <label><input type="radio" name="poly-dir" value="both"> Both</label>
  </div>
  <div id="poly-pattern-section">
    <div style="font-size:var(--text-xs);color:#484f58;text-transform:uppercase;letter-spacing:.05em;margin:6px 0 2px">To pattern</div>
    <div id="poly-pattern-hint" style="font-size:var(--text-xs);color:#8b949e;margin-bottom:4px">
      Optional. Tick any parts to clone alongside each new chain step. Mates between ticked parts and the seed mate's instances are replicated automatically.
    </div>
    <div id="poly-pattern-actions" style="display:none;gap:12px;margin-bottom:4px">
      <button id="poly-select-all" type="button" style="background:none;border:none;color:#58a6ff;cursor:pointer;font-size:var(--text-xs);padding:0">Select all</button>
      <button id="poly-select-none" type="button" style="background:none;border:none;color:#58a6ff;cursor:pointer;font-size:var(--text-xs);padding:0">Select none</button>
    </div>
    <div id="poly-additional-list" style="max-height:140px;overflow-y:auto;border:1px solid #30363d;border-radius:3px;background:#0d1117;padding:3px 4px;margin-bottom:10px;font-size:var(--text-xs)">
      <div style="color:#484f58">— Select a mate to see candidates —</div>
    </div>
  </div>
  <div id="poly-cost-preview" style="font-size:var(--text-xs);color:#8b949e;margin-bottom:4px;min-height:14px"></div>
  <div id="poly-closure" style="font-size:var(--text-xs);margin-bottom:6px;min-height:14px;display:none">
    <span id="poly-closure-text"></span>
    <button id="poly-closure-snap" type="button" style="margin-left:6px;background:none;border:none;color:#58a6ff;cursor:pointer;font-size:var(--text-xs);padding:0;display:none">Snap κ to close</button>
  </div>
  <button id="poly-go-btn" class="panel-action-btn" disabled style="width:100%">Polymerize</button>
  <div id="poly-status" style="font-size:var(--text-xs);color:#8b949e;margin-top:6px;min-height:16px"></div>
`

export function initPolymerizePanel(store, { isInstancePeriodic, getBeltFillCount, onPolymerizeBelt } = {}) {
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
  const patternSectionEl = panel.querySelector('#poly-pattern-section')
  const patternActionsEl = panel.querySelector('#poly-pattern-actions')
  const selectAllBtn     = panel.querySelector('#poly-select-all')
  const selectNoneBtn    = panel.querySelector('#poly-select-none')
  const costPreviewEl    = panel.querySelector('#poly-cost-preview')
  const closureEl        = panel.querySelector('#poly-closure')
  const closureTextEl    = panel.querySelector('#poly-closure-text')
  const closureSnapBtn   = panel.querySelector('#poly-closure-snap')

  // Select all / none for the "to pattern" checklist. Toggle each checkbox and
  // fire its change event so the per-row handler + cost preview stay in sync.
  function _setAllAdditional(on) {
    for (const cb of additionalListEl.querySelectorAll('input[type="checkbox"]')) {
      if (cb.checked !== on) { cb.checked = on; cb.dispatchEvent(new Event('change', { bubbles: true })) }
    }
  }
  selectAllBtn.addEventListener('click', () => _setAllAdditional(true))
  selectNoneBtn.addEventListener('click', () => _setAllAdditional(false))


  let _open                = false
  let _selectedJointId     = null
  // When set, the dropdown's "via periodic boundary" option is selected: chain
  // grows from this single instance via POST /assembly/polymerize-periodic
  // (no mate). Mutually exclusive with _selectedJointId.
  let _periodicInstanceId  = null
  // When set, a belt-rider seed is selected: repeat it around the belt loop via
  // onPolymerizeBelt. Mutually exclusive with _selectedJointId/_periodicInstanceId.
  let _beltRiderId         = null
  let _beltCountPrefilled  = false   // so we pre-fill the auto count only once per selection
  // Set of instance ids the user wants to clone alongside the seed pair.
  let _additionalSelected  = new Set()

  // A part is periodic when its design carries an is_periodic_seam forced
  // ligation. Inline sources embed the design (read it directly); file-backed
  // sources resolve through the injected renderer-cache check.
  function _instanceIsPeriodic(inst) {
    const embedded = inst?.source?.design?.forced_ligations
    if (embedded) return embedded.some(fl => fl.is_periodic_seam)
    return isInstancePeriodic ? !!isInstancePeriodic(inst.id) : false
  }
  function _periodicInstances(assembly) {
    return (assembly?.instances ?? []).filter(_instanceIsPeriodic)
  }

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
    patternActionsEl.style.display = 'none'
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
    patternActionsEl.style.display = 'flex'
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
    const prev = _periodicInstanceId ? `periodic:${_periodicInstanceId}` : (_selectedJointId || '')
    mateSelect.innerHTML = ''
    const placeholder = document.createElement('option')
    placeholder.value = ''
    placeholder.textContent = '— Select a mate or periodic part —'
    mateSelect.appendChild(placeholder)

    const joints    = assembly?.joints    ?? []
    const instances = assembly?.instances ?? []
    const instById = Object.fromEntries(instances.map(i => [i.id, i]))
    const periodic = _periodicInstances(assembly)

    if (!joints.length && !periodic.length) {
      placeholder.textContent = '— No mates or periodic parts —'
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
    // Periodic parts: one synthetic entry each — polymerize with no mate.
    for (const inst of periodic) {
      const opt = document.createElement('option')
      opt.value = `periodic:${inst.id}`
      opt.textContent = `${inst.name} — via periodic boundary`
      mateSelect.appendChild(opt)
    }
    // Belt riders: one entry each — repeat the part around the belt loop.
    const beltById = Object.fromEntries((assembly?.belt_paths ?? []).map(b => [b.id, b]))
    const riders = assembly?.belt_riders ?? []
    if (riders.length) mateSelect.disabled = false
    for (const r of riders) {
      const part = instById[r.instance_id]
      const belt = beltById[r.belt_path_id]
      const opt = document.createElement('option')
      opt.value = `beltrider:${r.id}`
      opt.textContent = `${part?.name ?? 'part'} on ${belt?.name ?? 'belt'} — around belt loop`
      mateSelect.appendChild(opt)
    }
    const valid = prev && (
      joints.some(j => j.id === prev) ||
      (prev.startsWith('periodic:') && periodic.some(i => `periodic:${i.id}` === prev)) ||
      (prev.startsWith('beltrider:') && riders.some(r => `beltrider:${r.id}` === prev))
    )
    mateSelect.value = valid ? prev : ''
  }

  // Direction radios + their label — hidden in belt mode (a closed loop has no
  // forward/backward; copies are distributed evenly around it).
  const dirSectionEls = () => [panel.querySelector('#poly-direction'), panel.querySelector('#poly-direction-label')]

  function _renderStateFromStore() {
    if (!_open) return
    const state    = store.getState()
    const assembly = state.currentAssembly
    _rebuildMateDropdown(assembly)

    // ── Belt-loop mode (seed = a belt rider) ─────────────────────────────────
    if (_beltRiderId) {
      patternSectionEl.style.display = 'none'
      for (const el of dirSectionEls()) if (el) el.style.display = 'none'
      const fill = getBeltFillCount?.(_beltRiderId)
      if (!fill) {
        selectionEl.style.color = '#f85149'
        selectionEl.textContent = 'Belt rider unavailable — re-attach the part, then try again.'
        eligibilityEl.textContent = ''
        goBtn.disabled = true
        costPreviewEl.textContent = ''
        return
      }
      // Pre-fill the count with the auto edge-to-edge fill (once per selection).
      if (!_beltCountPrefilled) { countInput.value = String(fill.count); _beltCountPrefilled = true }
      selectionEl.style.color = '#8b949e'
      selectionEl.textContent = 'Repeat this part around the belt loop.'
      eligibilityEl.style.color = '#3fb950'
      eligibilityEl.textContent =
        `✓ Auto: ${fill.count} copies fill the loop edge-to-edge (spacing ≈ ${fill.spacingNm.toFixed(1)} nm). Adjust count if needed.`
      goBtn.disabled = false
      const n = Math.max(2, parseInt(countInput.value, 10) || 2)
      costPreviewEl.style.color = 'var(--color-text-muted)'
      costPreviewEl.textContent = `Projected: ${n - 1} new instance${n - 1 === 1 ? '' : 's'} (chain of ${n} around the loop).`
      closureEl.style.display = 'none'
      return
    }
    for (const el of dirSectionEls()) if (el) el.style.display = ''

    // ── Periodic-part mode (no mate) ─────────────────────────────────────────
    if (_periodicInstanceId) {
      patternSectionEl.style.display = 'none'   // periodic has no "to pattern" support
      const inst = _findInstance(assembly, _periodicInstanceId)
      if (!inst) {
        selectionEl.style.color = '#f85149'
        selectionEl.textContent = 'Periodic part no longer exists. Pick another.'
        eligibilityEl.textContent = ''
        goBtn.disabled = true
        return
      }
      selectionEl.style.color = '#8b949e'
      selectionEl.textContent = `Periodic: ${inst.name} (via periodic boundary)`
      eligibilityEl.style.color = '#3fb950'
      eligibilityEl.textContent = '✓ Periodic part — chain grows from this single copy (no mate needed).'
      goBtn.disabled = false
      _updateCostPreview()
      return
    }
    patternSectionEl.style.display = ''

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
      _updateCostPreview()
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
    const v = mateSelect.value || ''
    _periodicInstanceId = null
    _selectedJointId = null
    _beltRiderId = null
    if (v.startsWith('periodic:')) {
      _periodicInstanceId = v.slice('periodic:'.length)
    } else if (v.startsWith('beltrider:')) {
      _beltRiderId = v.slice('beltrider:'.length)
      _beltCountPrefilled = false
    } else {
      _selectedJointId = v || null
    }
    // Selecting a different mate clears the pattern checklist — the
    // candidate set changes when the seed pair changes.
    _additionalSelected = new Set()
    statusEl.textContent = ''
    _renderStateFromStore()
  })

  // ── Live cost preview ──────────────────────────────────────────────────────
  // Shows projected new-instance count under current settings, colored by
  // threshold. Re-runs on any input change so the user can adjust before
  // committing. Replaces the previous blocking confirm() at moderate counts.
  function _updateCostPreview() {
    if (goBtn.disabled || (!_selectedJointId && !_periodicInstanceId)) { costPreviewEl.textContent = ''; return }
    const count     = Math.max(2, parseInt(countInput.value, 10) || 2)
    const direction = panel.querySelector('input[name="poly-dir"]:checked')?.value || 'forward'
    const n_add     = _periodicInstanceId ? 0 : _additionalSelected.size
    // Periodic: single seed → count-1 new copies (no pattern parts).
    const projected = _periodicInstanceId ? (count - 1)
                    : _estimatedNewInstanceCount(count, direction, n_add)
    const color = projected >= 20 ? '#f85149'
              : projected >= _COST_WARN_THRESHOLD ? '#d29922'
              : 'var(--color-text-muted)'
    costPreviewEl.style.color = color
    const patSuffix = n_add ? ` + ${n_add} pattern part(s) per step` : ''
    costPreviewEl.textContent = projected === 0
      ? `No new instances (chain already ${count}).`
      : `Projected: ${projected} new instance${projected === 1 ? '' : 's'} (cylinders)${patSuffix}.`
    _updateClosurePreview(count)
  }

  // Last-fetched closure suggestion for the snap button. Refreshed by
  // _updateClosurePreview; null when the part isn't periodic or the user
  // isn't on the periodic path.
  let _lastClosureSuggestion = null

  async function _updateClosurePreview(count) {
    if (!_periodicInstanceId) { closureEl.style.display = 'none'; _lastClosureSuggestion = null; return }
    closureEl.style.display = ''
    closureTextEl.textContent = 'Computing closure…'
    closureTextEl.style.color = '#8b949e'
    closureSnapBtn.style.display = 'none'
    try {
      const res = await api.getInstancePeriodicClosure(_periodicInstanceId, count)
      if (!res) { closureTextEl.textContent = ''; return }
      const angle = res.rotation_residual_deg ?? 0
      const trans = res.translation_residual_nm ?? 0
      _lastClosureSuggestion = res.suggested_curvature_deg_per_bp ?? null
      const closed = angle < 0.5 && trans < 0.5
      closureTextEl.style.color = closed ? '#3fb950' : '#d29922'
      closureTextEl.textContent = closed
        ? `Chain closes: residual ${angle.toFixed(2)}° / ${trans.toFixed(2)} nm.`
        : `Chain does NOT close: residual ${angle.toFixed(2)}° / ${trans.toFixed(2)} nm.`
      closureSnapBtn.style.display = (!closed && _lastClosureSuggestion != null) ? '' : 'none'
    } catch {
      closureTextEl.textContent = ''
      _lastClosureSuggestion = null
    }
  }

  closureSnapBtn.addEventListener('click', async () => {
    if (_lastClosureSuggestion == null || !_periodicInstanceId) return
    // Apply the suggested κ to the part's single bend op, then refresh.
    const design = await api.getInstanceDesign?.(_periodicInstanceId)
    const bendOps = (design?.design?.deformations ?? []).filter(op => op?.params?.kind === 'bend')
    if (bendOps.length !== 1) {
      closureTextEl.textContent = 'Snap not available (need exactly one bend op).'
      return
    }
    const op = bendOps[0]
    closureSnapBtn.disabled = true
    try {
      await api.updateDeformation?.(op.id, {
        kind: 'bend',
        curvature_deg_per_bp: _lastClosureSuggestion,
        direction_deg: op.params.direction_deg ?? 0,
      })
      _updateClosurePreview(Math.max(2, parseInt(countInput.value, 10) || 2))
    } finally {
      closureSnapBtn.disabled = false
    }
  })

  countInput.addEventListener('input', () => { if (_beltRiderId) _renderStateFromStore(); else _updateCostPreview() })
  panel.querySelectorAll('input[name="poly-dir"]').forEach(r =>
    r.addEventListener('change', _updateCostPreview),
  )
  // Hook into the additional-list rebuild so checkbox changes also update.
  additionalListEl.addEventListener('change', _updateCostPreview)

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
    const count     = Math.max(2, parseInt(countInput.value, 10) || 2)
    const direction = panel.querySelector('input[name="poly-dir"]:checked')?.value || 'forward'

    // ── Belt-loop path: repeat the seed rider around the belt ────────────────
    if (_beltRiderId) {
      if ((count - 1) >= 20) {
        const ok = await showConfirm({
          title: 'Large polymerize',
          message: `This will add ${count - 1} new part instances around the belt loop.`,
          confirmLabel: 'Polymerize',
        })
        if (!ok) return
      }
      goBtn.disabled = true
      statusEl.style.color = '#8b949e'
      statusEl.textContent = `Polymerizing ${count} copies around the belt…`
      await onPolymerizeBelt?.(_beltRiderId, count)
      const err = store.getState().lastError
      if (err?.message) { statusEl.style.color = '#f85149'; statusEl.textContent = err.message }
      else { statusEl.style.color = '#3fb950'; statusEl.textContent = `Polymerized ${count} copies around the belt.` }
      goBtn.disabled = false
      _renderStateFromStore()
      return
    }

    // ── Periodic path: single seed, no mate ──────────────────────────────────
    if (_periodicInstanceId) {
      const projected = count - 1
      if (projected >= 20) {
        const ok = await showConfirm({
          title: 'Large polymerize',
          message: `This will add ${projected} new part instances (chain ${count}). ` +
                   `New clones default to the cheap 'cylinders' renderer.`,
          confirmLabel: 'Polymerize',
        })
        if (!ok) return
      }
      goBtn.disabled = true
      statusEl.style.color = '#8b949e'
      statusEl.textContent = `Polymerizing… (${count} total, ${direction}, via periodic boundary)`
      const res = await api.polymerizePeriodicAssembly({
        instance_id: _periodicInstanceId, count, direction,
      })
      if (!res) {
        const err = store.getState().lastError
        statusEl.style.color = '#f85149'
        statusEl.textContent = err?.message || 'Polymerize failed.'
      } else {
        statusEl.style.color = '#3fb950'
        statusEl.textContent = `Chain extended to ${count} (${direction}, via periodic boundary).`
      }
      _renderStateFromStore()
      return
    }

    if (!_selectedJointId) return
    const additional_instance_ids = [..._additionalSelected]
    const projected = _estimatedNewInstanceCount(count, direction, additional_instance_ids.length)
    // Mid-range counts (10–19) are surfaced via the inline cost preview's
    // amber colour; only catastrophic counts get a blocking confirm.
    if (projected >= 20) {
      const ok = await showConfirm({
        title: 'Large polymerize',
        message:
          `This polymerize will add ${projected} new part instances ` +
          `(chain ${count}${additional_instance_ids.length ? `, ${additional_instance_ids.length} pattern part(s)` : ''}).\n\n` +
          `New clones default to the cheap 'cylinders' renderer to keep the ` +
          `assembly openable.`,
        confirmLabel: 'Polymerize',
      })
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
  // `opts.periodicInstanceId` pre-selects that part's "via periodic boundary"
  // dropdown entry (used when opening from a right-click on a periodic part).
  function open(opts = {}) {
    _open = true
    _selectedJointId = null
    _periodicInstanceId = opts?.periodicInstanceId || null
    _beltRiderId = null
    _beltCountPrefilled = false
    statusEl.textContent = ''
    panel.style.display = ''
    _renderStateFromStore()
    document.addEventListener('keydown', _onKey)
  }

  function close() {
    if (!_open) return
    _open = false
    _selectedJointId = null
    _periodicInstanceId = null
    _beltRiderId = null
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
    _periodicInstanceId = null
    _beltRiderId = null
    statusEl.textContent = ''
    _renderStateFromStore()
  }

  function isOpen() { return _open }

  return { open, close, isOpen, setSelectedJoint }
}
