/**
 * "Strand Animation" right-sidebar section — un/hybridization of an overhang +
 * its binder, driving the REAL beads (see overhang_strand_anim.js).
 *
 * A persistent dropdown selects which overhang (one that has a binder) is
 * animated: it autofills when the user clicks an overhang in the 3D view / list,
 * but KEEPS its selection when the user clicks away. Controls gray out until a
 * valid overhang is bound. N + radius are read-only (fixed by the overhang).
 */

import { createParamState } from '../strand-anim/params.js'
import { createPhiTicker } from '../strand-anim/ticker.js'
import { initOverhangStrandAnim, findBinderStrand } from '../scene/overhang_strand_anim.js'
import { primaryOverhangId } from '../scene/selection_model.js'

export function initStrandAnimPanel(store, { getHelixCtrl, getGeometry, getDesign, getScene, api, getAnimContext }) {
  const heading = document.getElementById('strand-anim-heading')
  const arrow   = document.getElementById('strand-anim-arrow')
  const body    = document.getElementById('strand-anim-body')
  const hintEl  = document.getElementById('strand-anim-hint')
  const root    = document.getElementById('strand-anim-controls')
  if (!heading || !body || !root) return null

  const paramState = createParamState({ mode: 'unzip', form: 'helical', thetaDeg: 30, invaderSplayDeg: 30, exitAngleDeg: 0, armPull: 1.0, unwindScale: 1.0, dispGap: 1.0 })
  const driver = initOverhangStrandAnim({ getHelixCtrl, getGeometry, getDesign, getScene })

  let _enabled = false
  let _collapsed = true
  let _hasToehold = false
  let _activeId = null          // dropdown value = persistent overhang under animation
  const _inputs = []
  let _roN, _roR, _playBtn, _phiInput, _phiNum, _ovhgSelect
  let _addKfBtn, _updKfBtn, _capHintEl

  // ── condensed control builders ──────────────────────────────────────────────
  function _row(label) {
    const r = document.createElement('div')
    r.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:4px;font-size:11px;color:#c9d1d9'
    if (label != null) {
      const l = document.createElement('span'); l.textContent = label
      l.style.cssText = 'flex:0 0 92px;color:#8b949e'; r.appendChild(l)
    }
    root.appendChild(r)
    return r
  }
  function _commit(key, val) {
    paramState.set(key, val)
    if (_enabled) driver.setPhi(paramState.get('phi'), paramState.snapshot())
  }
  function _num(label, key, { min, max, step, unit } = {}) {
    const r = _row(label)
    const inp = document.createElement('input')
    inp.type = 'number'; inp.value = paramState.get(key)
    if (min != null) inp.min = min; if (max != null) inp.max = max; if (step != null) inp.step = step
    inp.style.cssText = 'width:64px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;border-radius:3px;padding:1px 4px'
    inp.addEventListener('input', () => _commit(key, parseFloat(inp.value)))
    r.appendChild(inp)
    if (unit) { const u = document.createElement('span'); u.textContent = unit; u.style.color = '#6e7681'; r.appendChild(u) }
    _inputs.push({ el: inp, key })
    return inp
  }
  function _range(label, key, { min, max, step } = {}) {
    const r = _row(label)
    const inp = document.createElement('input')
    inp.type = 'range'; inp.min = min; inp.max = max; inp.step = step; inp.value = paramState.get(key)
    inp.style.cssText = 'flex:1;accent-color:#58a6ff'
    const num = document.createElement('span')
    num.textContent = Number(paramState.get(key)).toFixed(2)
    num.style.cssText = 'width:3em;text-align:right;color:#6e7681'
    inp.addEventListener('input', () => { num.textContent = Number(inp.value).toFixed(2); _commit(key, parseFloat(inp.value)) })
    r.appendChild(inp); r.appendChild(num)
    _inputs.push({ el: inp, key, num })
    return inp
  }
  function _select(label, key, options) {
    const r = _row(label)
    const sel = document.createElement('select')
    sel.style.cssText = 'flex:1;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;border-radius:3px;padding:1px 4px'
    for (const o of options) { const op = document.createElement('option'); op.value = o.value; op.textContent = o.label; sel.appendChild(op) }
    sel.value = paramState.get(key)
    sel.addEventListener('change', () => _commit(key, sel.value))
    r.appendChild(sel)
    _inputs.push({ el: sel, key })
    return sel
  }
  function _check(label, key) {
    const r = _row(null)
    const lab = document.createElement('label')
    lab.style.cssText = 'display:flex;align-items:center;gap:6px;cursor:pointer'
    const inp = document.createElement('input'); inp.type = 'checkbox'; inp.checked = !!paramState.get(key)
    inp.addEventListener('change', () => _commit(key, inp.checked))
    lab.appendChild(inp); lab.appendChild(document.createTextNode(label))
    r.appendChild(lab)
    _inputs.push({ el: inp, key })
    return inp
  }
  function _readonly(label) {
    const r = _row(label)
    const v = document.createElement('span'); v.textContent = '—'; v.style.color = '#6e7681'
    v.title = 'Fixed by the selected overhang'
    r.appendChild(v)
    return v
  }

  // ── overhang dropdown (persistent; NOT part of the grayed controls) ──────────
  {
    const r = _row('Overhang')
    _ovhgSelect = document.createElement('select')
    _ovhgSelect.style.cssText = 'flex:1;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;border-radius:3px;padding:1px 4px'
    _ovhgSelect.addEventListener('change', () => _bind(_ovhgSelect.value || null))
    r.appendChild(_ovhgSelect)
  }

  // ── animation controls ──────────────────────────────────────────────────────
  _select('Mode', 'mode', [{ label: 'Unzip', value: 'unzip' }, { label: 'Toehold displacement', value: 'displacement' }])
  _select('Form', 'form', [{ label: 'Helical', value: 'helical' }, { label: 'Straight', value: 'straight' }])
  _phiInput = _range('φ', 'phi', { min: 0, max: 1, step: 0.001 })
  _phiNum = _inputs[_inputs.length - 1].num
  {
    const r = _row(null)
    _playBtn = document.createElement('button')
    _playBtn.textContent = '▶ Play'
    _playBtn.style.cssText = 'padding:2px 10px;background:#238636;border:none;border-radius:3px;color:#fff;cursor:pointer;font-size:11px'
    _playBtn.addEventListener('click', () => ticker.toggle())
    const reset = document.createElement('button')
    reset.textContent = 'Reset'
    reset.style.cssText = 'padding:2px 10px;background:#30363d;border:none;border-radius:3px;color:#c9d1d9;cursor:pointer;font-size:11px'
    reset.addEventListener('click', () => { ticker.stop(); _setPhi(1) })
    r.appendChild(_playBtn); r.appendChild(reset)
  }
  // ── capture into the Animation-tab keyframe timeline ─────────────────────────
  {
    const r = _row(null)
    _addKfBtn = document.createElement('button')
    _addKfBtn.textContent = '+ Add keyframe'
    _addKfBtn.title = 'Append a new keyframe in the Animation tab at the current φ (saves these settings for this overhang)'
    _addKfBtn.style.cssText = 'padding:2px 8px;background:#1f6feb;border:none;border-radius:3px;color:#fff;cursor:pointer;font-size:11px'
    _addKfBtn.addEventListener('click', () => _capture('add'))
    _updKfBtn = document.createElement('button')
    _updKfBtn.textContent = 'Update last'
    _updKfBtn.title = 'Overwrite the most recent keyframe with this overhang at the current φ'
    _updKfBtn.style.cssText = 'padding:2px 8px;background:#30363d;border:none;border-radius:3px;color:#c9d1d9;cursor:pointer;font-size:11px'
    _updKfBtn.addEventListener('click', () => _capture('update'))
    r.appendChild(_addKfBtn); r.appendChild(_updKfBtn)
  }
  {
    _capHintEl = document.createElement('div')
    _capHintEl.style.cssText = 'font-size:10px;color:#6e7681;margin:-2px 0 4px;min-height:12px'
    root.appendChild(_capHintEl)
  }
  _select('Direction', 'direction', [{ label: 'Dehybridize (1→0)', value: 'dehybridize' }, { label: 'Hybridize (0→1)', value: 'hybridize' }])
  _num('Speed', 'speed', { min: 0.02, max: 2, step: 0.02, unit: 'φ/s' })
  _select('Easing', 'easing', ['linear', 'ease-in', 'ease-out', 'ease-in-out'].map(v => ({ label: v, value: v })))
  _check('Loop', 'loop')
  _check('Bounce (ping-pong)', 'bounce')
  _num('Melt width', 'meltBp', { min: 0, max: 6, step: 0.25, unit: 'bp' })
  _num('Splay angle', 'thetaDeg', { min: 0, max: 85, step: 1, unit: '°' })
  _num('Invader splay', 'invaderSplayDeg', { min: 0, max: 85, step: 1, unit: '°' })
  _num('Exit angle', 'exitAngleDeg', { min: -180, max: 180, step: 1, unit: '°' })
  _num('ssDNA stretch', 'armPull', { min: 1, max: 2.5, step: 0.05, unit: '×' })
  _num('Unwind', 'unwindScale', { min: -2, max: 2, step: 0.1, unit: '×' })
  _num('Branch gap', 'dispGap', { min: 0, max: 4, step: 0.25, unit: 'bp' })
  _roN = _readonly('Base pairs (N)')
  _roR = _readonly('Radius R (nm)')

  // ── ticker ──────────────────────────────────────────────────────────────────
  const ticker = createPhiTicker({
    getState: () => paramState.snapshot(),
    setPhi: (phi) => _setPhi(phi),
    onState: (playing) => { _playBtn.textContent = playing ? '⏸ Pause' : '▶ Play' },
  })
  function _setPhi(phi) {
    paramState.set('phi', phi)
    if (_enabled) driver.setPhi(phi, paramState.snapshot())
    _phiInput.value = phi
    if (_phiNum) _phiNum.textContent = Number(phi).toFixed(2)
  }

  function _setEnabled(on) {
    _enabled = on
    for (const { el } of _inputs) el.style.opacity = on ? '1' : '0.45'
    for (const { el } of _inputs) el.disabled = !on
    for (const btn of [_playBtn, _addKfBtn, _updKfBtn]) {
      if (!btn) continue
      btn.disabled = !on
      btn.style.opacity = on ? '1' : '0.45'
    }
  }

  function _capHint(msg) { if (_capHintEl) _capHintEl.textContent = msg }

  // Persist this overhang's setup + write its φ into a keyframe in the Animation tab.
  // mode: 'add' = append a new keyframe; 'update' = overwrite the most recent one.
  async function _capture(mode) {
    if (!_enabled || !_activeId || !api) return
    const ctx = getAnimContext?.()
    if (!ctx || !ctx.isDesignMode) { _capHint('Switch to the design Animation tab first.'); return }
    if (!ctx.animId) { _capHint('Select or create an animation in the Animation tab first.'); return }
    if (mode === 'update' && !ctx.lastKfId) { _capHint('No keyframe yet — use “Add keyframe”.'); return }
    const setup = paramState.snapshot()
    setup.binder_strand_id = findBinderStrand(store.getState().currentDesign, _activeId)
    const phi = paramState.get('phi')
    try {
      await api.patchOverhangStrandAnimSetup(_activeId, setup)
      if (mode === 'add') {
        await api.createKeyframe(ctx.animId, { strand_anim_phi: { [_activeId]: phi } })
        _capHint(`Added keyframe at φ=${Number(phi).toFixed(2)}.`)
      } else {
        const merged = { ...ctx.lastKfPhi, [_activeId]: phi }
        await api.updateKeyframe(ctx.animId, ctx.lastKfId, { strand_anim_phi: merged })
        _capHint(`Updated last keyframe (φ=${Number(phi).toFixed(2)}).`)
      }
    } catch (e) {
      _capHint('Capture failed — see console.')
      console.error('[strand-anim] capture failed', e)
    }
  }

  // ── overhang dropdown population (preserve current selection if still valid) ──
  function _rebuildOptions() {
    const design = store.getState().currentDesign
    const ovhgs = (design?.overhangs ?? []).filter(o => findBinderStrand(design, o.id))
    _ovhgSelect.innerHTML = ''
    const ph = document.createElement('option'); ph.value = ''; ph.textContent = '— select an overhang —'
    _ovhgSelect.appendChild(ph)
    for (const o of ovhgs) {
      const op = document.createElement('option'); op.value = o.id; op.textContent = o.label ?? o.id
      _ovhgSelect.appendChild(op)
    }
    if (_activeId && ovhgs.some(o => o.id === _activeId)) _ovhgSelect.value = _activeId
    else { _ovhgSelect.value = ''; if (_activeId) _activeId = null }
  }

  // ── bind the driver to an overhang (or gray out) ─────────────────────────────
  function _bind(id) {
    ticker.stop()
    driver.clear()
    _activeId = id || null
    if (_ovhgSelect.value !== (_activeId ?? '')) _ovhgSelect.value = _activeId ?? ''
    if (!_activeId || _collapsed) {
      _setEnabled(false)
      if (!_activeId && !_collapsed) hintEl.textContent = 'Select an overhang with a binder to animate.'
      return
    }
    const design = store.getState().currentDesign
    const binderId = findBinderStrand(design, _activeId)
    if (!binderId) { hintEl.textContent = 'Selected overhang has no binder strand.'; _setEnabled(false); return }
    const res = driver.bind(_activeId, binderId)
    if (!res.ok) { hintEl.textContent = `Cannot animate: ${res.reason}.`; _setEnabled(false); return }
    _hasToehold = !!res.hasToehold
    const label = design?.overhangs?.find(o => o.id === _activeId)?.label ?? _activeId
    const note = (paramState.get('mode') === 'displacement' && !_hasToehold)
      ? ' — no toehold; make the binder shorter than the overhang' : ''
    hintEl.textContent = `Animating overhang ${label} ↔ binder${note}.`
    _roN.textContent = String(res.N)
    _roR.textContent = res.R.toFixed(2)
    _setEnabled(true)
    _setPhi(paramState.get('phi'))
  }

  // Re-bind (refresh hint + frame) when the mode changes.
  paramState.subscribe((k) => { if (k === 'mode' && _enabled) _bind(_activeId) })

  _setEnabled(false)
  _rebuildOptions()

  // ── collapse ────────────────────────────────────────────────────────────────
  function _applyCollapse() {
    body.style.display = _collapsed ? 'none' : ''
    arrow.classList.toggle('is-collapsed', _collapsed)
    if (_collapsed) { ticker.stop(); driver.clear(); _setEnabled(false) }
    else { _rebuildOptions(); _bind(_activeId) }
  }
  _applyCollapse()
  heading.addEventListener('click', () => { _collapsed = !_collapsed; _applyCollapse() })

  // ── store subscription ──────────────────────────────────────────────────────
  store.subscribe((s, prev) => {
    if (s.currentDesign !== prev.currentDesign) _rebuildOptions()
    if (_collapsed) return
    // Autofill from a NEW selection — but sticky: only set, never clear.
    if (s.selection !== prev.selection) {
      const sel = primaryOverhangId(s)
      if (sel && sel !== _activeId && findBinderStrand(s.currentDesign, sel)) { _bind(sel); return }
    }
    // Re-bind to the persisted overhang when the design/geometry changes.
    if ((s.currentDesign !== prev.currentDesign || s.currentGeometry !== prev.currentGeometry) && _activeId) {
      _bind(_activeId)
    }
  })

  return { dispose: () => { ticker.stop(); driver.dispose() } }
}
