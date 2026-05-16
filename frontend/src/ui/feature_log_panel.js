/**
 * Feature Log panel — unified timeline of geometry operations with a vertical
 * notch slider for seeking to any prior feature state.
 *
 * Layout: left rail (20 px) with a draggable thumb + notch ticks, right column
 * with F0 row (always present) and feature rows (F1..FN).
 *
 * Slider positions:
 *   F0 notch → seekFeatures(-2)  — no features active (initial design)
 *   FN notch → seekFeatures(N-1) — log entries 0..N-1 active
 *
 * Each feature row shows: "FN: Bend" or "FN: move/rotate [cluster]".
 *
 * @param {object} store
 * @param {object} opts.api — API module (seekFeatures)
 */

import { showPersistentToast, dismissToast } from './toast.js'
import { getSectionCollapsed, setSectionCollapsed } from './section_collapse_state.js'

export function initFeatureLogPanel(store, { api, onEditFeature, onAnimateConfiguration, onOpenOverhangsManager }) {
  const panelBody = document.getElementById('feature-log-panel-body')
  const heading   = document.getElementById('feature-log-panel-heading')
  const arrow     = document.getElementById('feature-log-panel-arrow')
  const titleEl   = heading?.querySelector('span')
  if (!panelBody || !heading) return

  let _collapsed    = getSectionCollapsed('feature-log', 'feature-log-panel', false)
  let _latestDesign = null
  let _latestAssembly = null
  let _notchYs      = []   // [y-centre-px] for F0, F1..FN relative to rail
  let _notchKeys    = []   // parallel: { position: int, sub_position: int|null }
  let _isSeeking    = false

  // Apply persisted collapse state to DOM before initial render.
  panelBody.style.display = _collapsed ? 'none' : ''
  if (arrow) arrow.classList.toggle('is-collapsed', _collapsed)

  // Per-cluster expansion state. Persists across renders within this panel
  // session but not across reloads. Keyed by cluster.id.
  const _clusterExpanded = new Map()

  // ── Part context ──────────────────────────────────────────────────────────────
  let _partInstanceId = null
  let _partPatchFn    = null
  let _assemblyPartInstanceId = null
  // True when the target dropdown is on the special "Assembly" entry — the
  // panel then displays assembly.feature_log and seeks via seekAssemblyFeatures.
  let _assemblyFeatureMode = false

  // ── Collapse / expand ──────────────────────────────────────────────────────
  heading.addEventListener('click', () => {
    _collapsed = !_collapsed
    panelBody.style.display = _collapsed ? 'none' : ''
    arrow.classList.toggle('is-collapsed', _collapsed)
    setSectionCollapsed('feature-log', 'feature-log-panel', _collapsed)
    if (!_collapsed) { _renderCurrentView(); _positionRail() }
  })

  // ── DOM structure ──────────────────────────────────────────────────────────
  // fl-wrap: flex row; fl-rail on left, fl-list on right.
  const wrap = document.createElement('div')
  wrap.style.cssText = 'display:flex;gap:0;position:relative'

  const loadoutBar = document.createElement('div')
  loadoutBar.style.cssText = 'display:flex;align-items:center;gap:5px;margin-bottom:8px'

  const assemblyTargetBar = document.createElement('div')
  assemblyTargetBar.style.cssText = 'display:none;align-items:center;gap:6px;margin-bottom:8px'
  const assemblyTargetLabel = document.createElement('span')
  assemblyTargetLabel.textContent = 'Target'
  assemblyTargetLabel.style.cssText = 'font-size:var(--text-xs);color:#6e7681;flex-shrink:0'
  const assemblyTargetSelect = document.createElement('select')
  assemblyTargetSelect.title = 'Select assembly or part feature log'
  assemblyTargetSelect.style.cssText = [
    'flex:1;min-width:0;background:#0d1117;border:1px solid #30363d',
    'border-radius:4px;color:#c9d1d9;padding:4px 6px',
    'font-family:var(--font-ui);font-size:11px',
  ].join(';')
  assemblyTargetBar.append(assemblyTargetLabel, assemblyTargetSelect)

  const loadoutSelect = document.createElement('select')
  loadoutSelect.title = 'Select loadout'
  loadoutSelect.style.cssText = [
    'flex:1;min-width:0;background:#0d1117;border:1px solid #30363d',
    'border-radius:4px;color:#c9d1d9;padding:4px 6px',
    'font-family:var(--font-ui);font-size:11px',
  ].join(';')

  const loadoutAddBtn = document.createElement('button')
  loadoutAddBtn.textContent = '+'
  loadoutAddBtn.title = 'Create loadout'
  loadoutAddBtn.style.cssText = 'background:#0d2a3d;border:1px solid #1f6feb;color:#58a6ff;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 7px;flex-shrink:0'

  const loadoutRenameBtn = document.createElement('button')
  loadoutRenameBtn.textContent = '✎'
  loadoutRenameBtn.title = 'Rename loadout'
  loadoutRenameBtn.style.cssText = 'background:#21262d;border:1px solid #30363d;color:#8b949e;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 6px;flex-shrink:0'

  const loadoutDeleteBtn = document.createElement('button')
  loadoutDeleteBtn.textContent = '×'
  loadoutDeleteBtn.title = 'Delete loadout'
  loadoutDeleteBtn.style.cssText = 'background:#2d1515;border:1px solid #c93c3c;color:#c93c3c;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 6px;flex-shrink:0'

  loadoutBar.append(loadoutSelect, loadoutAddBtn, loadoutRenameBtn, loadoutDeleteBtn)

  const toolbar = document.createElement('div')
  toolbar.style.cssText = 'display:none;margin-bottom:8px'
  const captureCfgBtn = document.createElement('button')
  captureCfgBtn.className = 'panel-action-btn'
  captureCfgBtn.style.cssText = 'width:100%'
  captureCfgBtn.textContent = '+ Capture Configuration'
  toolbar.appendChild(captureCfgBtn)

  const _editStyle   = 'background:#21262d;border:1px solid #30363d;color:#8b949e;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'
  const _saveStyle   = 'background:#162420;border:1px solid #3fb950;color:#3fb950;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'
  const _goStyle     = 'background:#0d2a3d;border:1px solid #1f6feb;color:#58a6ff;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'
  const _updateStyle = 'background:#1f2d0d;border:1px solid #588a1e;color:#8ec550;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'
  const _delStyle    = 'background:#2d1515;border:1px solid #c93c3c;color:#c93c3c;border-radius:3px;font-size:11px;line-height:1.4;cursor:pointer;padding:3px 5px;flex-shrink:0'

  // Rail
  const rail = document.createElement('div')
  rail.id = 'fl-rail'
  rail.style.cssText = 'width:20px;flex-shrink:0;position:relative;user-select:none'

  // Track line (vertical centred line running full height of rail)
  const track = document.createElement('div')
  track.style.cssText = [
    'position:absolute;left:9px;top:0;bottom:0;width:2px',
    'background:#30363d;border-radius:1px',
  ].join(';')
  rail.appendChild(track)

  // Thumb (draggable circle)
  const thumb = document.createElement('div')
  thumb.style.cssText = [
    'position:absolute;left:4px;width:12px;height:12px',
    'border-radius:50%;background:#58a6ff;border:2px solid #0d1117',
    'cursor:grab;z-index:2;transform:translateY(-50%)',
    'box-shadow:0 0 0 2px #1f6feb',
  ].join(';')
  rail.appendChild(thumb)

  // List column
  const list = document.createElement('div')
  list.id = 'fl-list'
  list.style.cssText = 'flex:1;min-width:0'

  wrap.append(rail, list)
  panelBody.innerHTML = ''
  panelBody.append(assemblyTargetBar, loadoutBar, toolbar, wrap)

  function _isAssemblyConfigMode() {
    return false
  }

  function _isAssemblyFeatureMode() {
    const s = store.getState()
    return _assemblyFeatureMode && !!s.assemblyActive && !!s.currentAssembly
  }

  function _isAssemblyPartMode() {
    const s = store.getState()
    return !_partInstanceId && !!_assemblyPartInstanceId && !!s.assemblyActive && !!s.currentAssembly
  }

  function _activePartTargetId() {
    return _partInstanceId || (_isAssemblyPartMode() ? _assemblyPartInstanceId : null)
  }

  function _renderCurrentView() {
    const s = store.getState()
    if (_isAssemblyFeatureMode()) {
      _rebuildAssemblyFeatureLog(s.currentAssembly)
    } else if (!_partInstanceId && s.assemblyActive && s.currentAssembly && !_assemblyPartInstanceId) {
      _renderAssemblyPartPrompt()
    } else {
      _rebuild(_latestDesign)
    }
  }

  function _refreshTitle() {
    if (titleEl) titleEl.textContent = 'Feature Log'
    assemblyTargetBar.style.display = (store.getState().assemblyActive && store.getState().currentAssembly) ? 'flex' : 'none'
    toolbar.style.display = 'none'
    loadoutBar.style.display = _latestDesign ? 'flex' : 'none'
    rail.style.display = ''
    _renderAssemblyTargetControls()
    _renderLoadoutControls()
  }

  function _renderAssemblyTargetControls() {
    if (assemblyTargetBar.style.display === 'none') return
    const assembly = store.getState().currentAssembly
    const current = _assemblyFeatureMode
      ? '__assembly__'
      : (_assemblyPartInstanceId ?? '__assembly__')
    assemblyTargetSelect.innerHTML = ''
    const asmOpt = document.createElement('option')
    asmOpt.value = '__assembly__'
    asmOpt.textContent = `Assembly: ${assembly?.metadata?.name || 'Untitled'}`
    assemblyTargetSelect.appendChild(asmOpt)
    for (const inst of assembly?.instances ?? []) {
      const opt = document.createElement('option')
      opt.value = inst.id
      opt.textContent = inst.name || inst.id
      assemblyTargetSelect.appendChild(opt)
    }
    assemblyTargetSelect.value = [...assemblyTargetSelect.options].some(o => o.value === current)
      ? current
      : '__assembly__'
  }

  function _renderAssemblyPartPrompt() {
    _refreshTitle()
    list.innerHTML = '<div style="color:#484f58;font-size:11px;padding:3px 6px">Select a part to edit its feature log.</div>'
    _notchYs = []
    rail.querySelectorAll('.fl-notch').forEach(n => n.remove())
    thumb.style.top = '0px'
  }

  function _currentLoadouts() {
    const design = _latestDesign
    const loadouts = design?.loadouts ?? []
    if (loadouts.length) return loadouts
    return [{ id: '__implicit_loadout_1__', name: 'Loadout 1' }]
  }

  function _activeLoadoutId() {
    const loadouts = _currentLoadouts()
    const active = _latestDesign?.active_loadout_id
    return loadouts.some(l => l.id === active) ? active : loadouts[0]?.id
  }

  function _renderLoadoutControls() {
    const loadouts = _currentLoadouts()
    const activeId = _activeLoadoutId()
    loadoutSelect.innerHTML = ''
    for (const loadout of loadouts) {
      const opt = document.createElement('option')
      opt.value = loadout.id
      opt.textContent = loadout.name || 'Loadout'
      loadoutSelect.appendChild(opt)
    }
    if (activeId) loadoutSelect.value = activeId
    const canRename = !!activeId
    const canDelete = activeId && activeId !== '__implicit_loadout_1__' && loadouts.length > 1
    loadoutRenameBtn.disabled = !canRename
    loadoutRenameBtn.style.opacity = canRename ? '1' : '0.45'
    loadoutDeleteBtn.disabled = !canDelete
    loadoutDeleteBtn.style.opacity = (!loadoutDeleteBtn.disabled) ? '1' : '0.45'
  }

  loadoutSelect.addEventListener('change', async () => {
    const id = loadoutSelect.value
    if (!id || id === '__implicit_loadout_1__' || id === _activeLoadoutId()) return
    const partId = _activePartTargetId()
    const result = partId && api.selectInstanceLoadout
      ? await api.selectInstanceLoadout(partId, id)
      : await api.selectLoadout?.(id)
    if (result?.design) {
      _latestDesign = result.design
      if (!_collapsed) _rebuild(_latestDesign)
    }
  })

  loadoutAddBtn.addEventListener('click', async () => {
    const n = (_latestDesign?.loadouts?.length ?? 1) + 1
    const partId = _activePartTargetId()
    const result = partId && api.createInstanceLoadout
      ? await api.createInstanceLoadout(partId, `Loadout ${n}`)
      : await api.createLoadout?.(`Loadout ${n}`)
    if (result?.design) {
      _latestDesign = result.design
      if (!_collapsed) _rebuild(_latestDesign)
    }
  })

  loadoutRenameBtn.addEventListener('click', async () => {
    const id = _activeLoadoutId()
    if (!id) return
    const current = _currentLoadouts().find(l => l.id === id)?.name ?? 'Loadout'
    const next = window.prompt('Loadout name:', current)
    if (next == null) return
    const name = next.trim()
    if (!name || name === current) return
    const partId = _activePartTargetId()
    const result = partId && api.renameInstanceLoadout
      ? await api.renameInstanceLoadout(partId, id, name)
      : await api.renameLoadout?.(id, name)
    if (result?.design) {
      _latestDesign = result.design
      if (!_collapsed) _rebuild(_latestDesign)
    }
  })

  loadoutDeleteBtn.addEventListener('click', async () => {
    const id = _activeLoadoutId()
    if (!id || id === '__implicit_loadout_1__') return
    const loadouts = _currentLoadouts()
    if (loadouts.length <= 1) return
    const name = loadouts.find(l => l.id === id)?.name ?? 'this loadout'
    const ok = window.confirm(`Delete "${name}"?`)
    if (!ok) return
    const partId = _activePartTargetId()
    const result = partId && api.deleteInstanceLoadout
      ? await api.deleteInstanceLoadout(partId, id)
      : await api.deleteLoadout?.(id)
    if (result?.design) {
      _latestDesign = result.design
      if (!_collapsed) _rebuild(_latestDesign)
    }
  })

  assemblyTargetSelect.addEventListener('change', async () => {
    const value = assemblyTargetSelect.value
    if (value === '__assembly__') {
      _assemblyFeatureMode = true
      _assemblyPartInstanceId = null
      _latestDesign = null
      _latestAssembly = store.getState().currentAssembly
      _refreshTitle()
      if (!_collapsed) _rebuildAssemblyFeatureLog(_latestAssembly)
      return
    }
    _assemblyFeatureMode = false
    await _selectAssemblyPart(value)
  })

  captureCfgBtn.addEventListener('click', async () => {
    const assembly = store.getState().currentAssembly
    if (!assembly) return
    const n = (assembly.configurations?.length ?? 0) + 1
    await api.createAssemblyConfiguration?.(`Config ${n}`)
  })

  async function _selectAssemblyPart(instanceId) {
    if (!instanceId) return
    _assemblyPartInstanceId = instanceId
    _latestDesign = null
    _refreshTitle()
    list.innerHTML = '<div style="color:#484f58;font-size:11px;padding:3px 6px">Loading part feature log…</div>'
    try {
      const result = await api.getInstanceDesign?.(instanceId)
      if (_assemblyPartInstanceId !== instanceId) return
      _latestDesign = result?.design ?? null
      _refreshTitle()
      if (!_collapsed) _rebuild(_latestDesign)
    } catch (err) {
      _log('assembly part feature log load ERROR instance=', instanceId, err)
    }
  }

  // ── ResizeObserver — reposition rail when layout changes ──────────────────
  const _ro = new ResizeObserver(() => { if (!_collapsed) _positionRail() })
  _ro.observe(wrap)

  // ── Debug ──────────────────────────────────────────────────────────────────
  const DBG = true   // set false to silence
  function _log(...args) { if (DBG) console.log('[FL]', ...args) }

  // Expose a snapshot function for manual inspection in DevTools:
  // NADOC_FL_DEBUG() → logs current notchYs, cursor, rail rect, row rects
  window.NADOC_FL_DEBUG = () => {
    const railRect = rail.getBoundingClientRect()
    const rows     = [...list.querySelectorAll('[data-fl-row]')]
    console.group('[FL] Feature Log Debug Snapshot')
    console.log('rail rect:', { top: railRect.top, height: railRect.height, width: railRect.width })
    console.log('_notchYs:', _notchYs)
    console.log('cursor:', _latestDesign?.feature_log_cursor)
    console.log('feature_log length:', _latestDesign?.feature_log?.length)
    console.log('deformations count:', _latestDesign?.deformations?.length)
    rows.forEach((r, i) => {
      const rr = r.getBoundingClientRect()
      console.log(`  row[${i}] data-fl-row=${r.dataset.flRow} top=${rr.top.toFixed(1)} h=${rr.height.toFixed(1)}`)
    })
    console.groupEnd()
  }

  // ── Seek ───────────────────────────────────────────────────────────────────
  // Latest seek requested while one was in-flight; null = none queued.
  // Stored as { position, sub_position } so the queued request preserves
  // mid-cluster sub-position.
  let _pendingSeekPos = null

  async function _seek(position, subPosition = null) {
    if (_isSeeking) {
      _log('seek QUEUED (in-flight replaced), pos=', position, 'sub=', subPosition)
      _pendingSeekPos = { position, sub_position: subPosition }
      return
    }
    _isSeeking = true
    _log('seek START pos=', position, 'sub=', subPosition)
    let label
    if (position === -2) {
      label = 'F0 — initial'
    } else if (subPosition != null && subPosition >= 0) {
      label = `F${position + 1}-${subPosition + 1}`
    } else {
      label = `F${position + 1}`
    }
    showPersistentToast(`Loading ${label}…`)
    try {
      if (_isAssemblyFeatureMode() && api.seekAssemblyFeatures) {
        const result = await api.seekAssemblyFeatures(position)
        if (result?.assembly) {
          _latestAssembly = result.assembly
          _rebuildAssemblyFeatureLog(_latestAssembly)
        }
      } else if (_isAssemblyPartMode() && api.seekInstanceFeatures) {
        const result = await api.seekInstanceFeatures(_assemblyPartInstanceId, position, subPosition)
        if (result?.design) {
          _latestDesign = result.design
          _rebuild(_latestDesign)
        }
      } else if (_partInstanceId && _partPatchFn) {
        await _partPatchFn(d => { d.feature_log_cursor = position })
      } else {
        const result = await api.seekFeatures(position, subPosition)
        const d = result?.design
        _log('seek DONE pos=', position, 'sub=', subPosition,
             '→ cursor=', d?.feature_log_cursor, 'deforms=', d?.deformations?.length)
      }
    } catch (err) {
      _log('seek ERROR pos=', position, 'sub=', subPosition, err)
    } finally {
      _isSeeking = false
      if (_pendingSeekPos === null) dismissToast()
      // Flush any position requested while this seek was in-flight.
      if (_pendingSeekPos !== null) {
        const next = _pendingSeekPos
        _pendingSeekPos = null
        _log('seek FLUSH pending pos=', next.position, 'sub=', next.sub_position)
        _seek(next.position, next.sub_position)
      }
    }
  }

  async function _seekAssemblyConfig(index) {
    const cfg = _latestAssembly?.configurations?.[index]
    if (!cfg || _isSeeking) {
      if (_isSeeking) _pendingSeekPos = index
      return
    }
    _isSeeking = true
    showPersistentToast(`Loading ${cfg.name ?? `Config ${index + 1}`}…`)
    try {
      await api.restoreAssemblyConfiguration?.(cfg.id)
    } catch (err) {
      _log('assembly config seek ERROR index=', index, err)
    } finally {
      _isSeeking = false
      if (_pendingSeekPos === null) dismissToast()
      if (_pendingSeekPos !== null) {
        const next = _pendingSeekPos
        _pendingSeekPos = null
        _seekAssemblyConfig(next)
      }
    }
  }

  async function _animateAssemblyConfig(cfg) {
    if (!cfg) return
    if (onAnimateConfiguration) {
      await onAnimateConfiguration(cfg)
    } else {
      await api.restoreAssemblyConfiguration?.(cfg.id)
    }
  }

  // ── Notch positioning ──────────────────────────────────────────────────────
  /**
   * Measure the Y-centre of each row (F0 row + feature rows) relative to rail,
   * place notch ticks, and position the thumb at the current cursor.
   */
  function _positionRail() {
    if (!_latestDesign && !_latestAssembly) { _log('_positionRail: no timeline state, skip'); return }
    // Use wrap as the Y reference — rail has zero intrinsic height (all children
    // are position:absolute), but wrap always has height from the list column.
    const wrapRect = wrap.getBoundingClientRect()
    _log('_positionRail: wrap rect h=', wrapRect.height, 'w=', wrapRect.width)
    if (!wrapRect.height) {
      _log('_positionRail: BAIL — wrap height is 0 (panel not visible)')
      return
    }

    // Gather rows in order: F0 row is always first child of list. Each row's
    // data-fl-row encodes the seek target: a bare integer is a top-level
    // position; "K.j" syntax is a sub_position within cluster K (J=child idx).
    const rows = list.querySelectorAll('[data-fl-row]')
    _notchYs = []
    _notchKeys = []
    for (const row of rows) {
      const r = row.getBoundingClientRect()
      const y = r.top + r.height / 2 - wrapRect.top
      const flRow = row.dataset.flRow
      let key
      if (typeof flRow === 'string' && flRow.includes('.')) {
        // Sub-row: "K.j" → position K-1 (0-indexed), sub_position j
        const [kStr, jStr] = flRow.split('.', 2)
        key = { position: parseInt(kStr, 10) - 1, sub_position: parseInt(jStr, 10) }
      } else {
        // Top-level row: F0=0 maps to position=-2; F1=1 → position=0; etc.
        const flN = parseInt(flRow, 10)
        key = { position: flN === 0 ? -2 : flN - 1, sub_position: null }
      }
      _log(`  row data-fl-row=${flRow} top=${r.top.toFixed(1)} h=${r.height.toFixed(1)} → notchY=${y.toFixed(1)} key=${JSON.stringify(key)}`)
      _notchYs.push(y)
      _notchKeys.push(key)
    }
    _log('_positionRail: _notchYs=', _notchYs, '_notchKeys=', _notchKeys)

    // Remove old notch ticks (keep track + thumb).
    rail.querySelectorAll('.fl-notch').forEach(n => n.remove())

    // Draw notch ticks
    _notchYs.forEach((y, i) => {
      const notch = document.createElement('div')
      notch.className = 'fl-notch'
      notch.style.cssText = [
        `position:absolute;left:3px;top:${y}px`,
        'width:14px;height:3px;transform:translateY(-50%)',
        'background:#30363d;border-radius:2px;z-index:1',
      ].join(';')
      notch.dataset.notchIndex = i
      rail.insertBefore(notch, thumb)
    })

    _updateThumb()
  }

  /** Move thumb to the notch for the current cursor position. */
  function _updateThumb() {
    if (!_notchYs.length) return
    if (_isAssemblyConfigMode()) {
      const configs = _latestAssembly?.configurations ?? []
      const cursorId = _latestAssembly?.configuration_cursor
      let notchIdx = configs.findIndex(c => c.id === cursorId)
      if (notchIdx < 0) notchIdx = Math.max(0, configs.length - 1)
      thumb.style.top = `${_notchYs[notchIdx] ?? 0}px`
      return
    }
    if (_isAssemblyFeatureMode()) {
      const cursor = _latestAssembly?.feature_log_cursor ?? -1
      let notchIdx
      if (cursor === -2)    notchIdx = 0
      else if (cursor < 0)  notchIdx = _notchYs.length - 1
      else                  notchIdx = Math.min(cursor + 1, _notchYs.length - 1)
      thumb.style.top = `${_notchYs[notchIdx] ?? 0}px`
      return
    }
    if (!_latestDesign) return
    const cursor    = _latestDesign.feature_log_cursor      ?? -1
    const subCursor = _latestDesign.feature_log_sub_cursor  ?? null

    // Look up the matching notch via the parallel _notchKeys array. This
    // handles the dynamic notch ordering when clusters are expanded
    // (sub-notches inflate the array, so cursor + 1 no longer maps to
    // F_{cursor+1}'s notch).
    let notchIdx = -1
    if (cursor === -2) {
      notchIdx = 0
    } else if (cursor < 0) {
      notchIdx = _notchYs.length - 1
    } else {
      // Match {position: cursor, sub_position: subCursor}. If subCursor is
      // null the cluster header (or non-cluster entry) is the target;
      // otherwise the matching sub-notch is.
      notchIdx = _notchKeys.findIndex(
        k => k && k.position === cursor && k.sub_position === subCursor,
      )
      if (notchIdx < 0) {
        // Fallback: cluster's header notch (sub_position null), or last notch.
        notchIdx = _notchKeys.findIndex(k => k && k.position === cursor && k.sub_position == null)
      }
      if (notchIdx < 0) {
        notchIdx = Math.min(cursor + 1, _notchYs.length - 1)
      }
    }
    const y = _notchYs[notchIdx] ?? 0
    thumb.style.top = `${y}px`
  }

  // ── Thumb drag ─────────────────────────────────────────────────────────────
  let _dragNotch = -1

  thumb.addEventListener('pointerdown', _startDrag)

  function _startDrag(e) {
    e.preventDefault()
    e.stopPropagation()
    thumb.style.cursor = 'grabbing'
    document.body.style.cursor = 'grabbing'
    // Record which notch the thumb is currently at (so we don't seek if released without moving).
    let _initialNotch
    if (_isAssemblyConfigMode()) {
      const configs = _latestAssembly?.configurations ?? []
      const cursorId = _latestAssembly?.configuration_cursor
      _initialNotch = configs.findIndex(c => c.id === cursorId)
      if (_initialNotch < 0) _initialNotch = Math.max(0, configs.length - 1)
    } else if (_isAssemblyFeatureMode()) {
      const cursor = _latestAssembly?.feature_log_cursor ?? -1
      if (cursor === -2)        _initialNotch = 0
      else if (cursor < 0)      _initialNotch = _notchYs.length - 1
      else                      _initialNotch = Math.min(cursor + 1, _notchYs.length - 1)
    } else {
      const cursor    = _latestDesign?.feature_log_cursor      ?? -1
      const subCursor = _latestDesign?.feature_log_sub_cursor  ?? null
      if (cursor === -2)     _initialNotch = 0
      else if (cursor < 0)   _initialNotch = _notchYs.length - 1
      else {
        // Use _notchKeys (parallel to _notchYs) so sub-notch positions are
        // honoured when a cluster is expanded.
        let idx = _notchKeys.findIndex(
          k => k && k.position === cursor && k.sub_position === subCursor,
        )
        if (idx < 0) {
          idx = _notchKeys.findIndex(k => k && k.position === cursor && k.sub_position == null)
        }
        if (idx < 0) idx = Math.min(cursor + 1, _notchYs.length - 1)
        _initialNotch = idx
      }
    }
    _log('drag START — _notchYs=', _notchYs, 'initialNotch=', _initialNotch)

    function onMove(me) {
      const y = me.clientY - wrap.getBoundingClientRect().top
      if (!_notchYs.length) { _log('drag MOVE — _notchYs empty, no snap possible'); return }
      // Find closest notch
      let closest = 0
      let minDist = Infinity
      _notchYs.forEach((ny, i) => {
        const d = Math.abs(ny - y)
        if (d < minDist) { minDist = d; closest = i }
      })
      _log(`drag MOVE y=${y.toFixed(1)} → closest notch ${closest}`)
      if (closest !== _dragNotch) {
        _dragNotch = closest
        // Move thumb immediately for visual feedback — no seek yet.
        thumb.style.top = `${_notchYs[closest]}px`
      }
    }

    function onUp() {
      thumb.style.cursor = 'grab'
      document.body.style.cursor = ''
      document.removeEventListener('pointermove', onMove)
      document.removeEventListener('pointerup', onUp)
      // Fire seek only on release, and only if the notch moved from where it started.
      const finalNotch = _dragNotch !== -1 ? _dragNotch : _initialNotch
      if (finalNotch !== _initialNotch) {
        if (_isAssemblyConfigMode()) {
          _log('drag RELEASE at config notch', finalNotch)
          _seekAssemblyConfig(finalNotch)
        } else {
          // Use the parallel _notchKeys array so sub-position notches inside
          // expanded clusters seek to the right (cluster, sub_position).
          const key = _notchKeys[finalNotch]
          if (key) {
            _log('drag RELEASE at notch', finalNotch, '→ seeking', key)
            _seek(key.position, key.sub_position)
          } else {
            // Fallback for legacy paths that didn't populate _notchKeys.
            const pos = finalNotch === 0 ? -2 : finalNotch - 1
            _log('drag RELEASE at notch', finalNotch, '→ seeking pos=', pos, '(legacy fallback)')
            _seek(pos)
          }
        }
      } else {
        _log('drag RELEASE — notch unchanged, no seek')
      }
      _dragNotch = -1
    }

    document.addEventListener('pointermove', onMove)
    document.addEventListener('pointerup', onUp)
  }

  // ── Rebuild list ───────────────────────────────────────────────────────────
  function _rebuild(design) {
    _refreshTitle()
    if (_isAssemblyConfigMode()) {
      _rebuildAssembly(store.getState().currentAssembly)
      return
    }
    list.innerHTML = ''
    const log    = design?.feature_log ?? []
    const cursor = design?.feature_log_cursor ?? -1
    _log('_rebuild: log.length=', log.length, 'cursor=', cursor, 'deforms=', design?.deformations?.length)

    // F0 row — always present, never suppressed
    const f0Row = document.createElement('div')
    f0Row.dataset.flRow = '0'
    f0Row.style.cssText = 'font-size:11px;color:#6e7681;padding:3px 6px;border-radius:3px'
    f0Row.textContent = 'F0 — initial'
    list.appendChild(f0Row)

    if (!log.length) {
      _positionRail()
      return
    }

    const clusterMap = Object.fromEntries(
      (design?.cluster_transforms ?? []).map(c => [c.id, c])
    )
    const deformIds  = new Set((design?.deformations ?? []).map(d => d.id))
    const overhangIds = new Set((design?.overhangs    ?? []).map(o => o.id))

    /**
     * A delta entry is "broken" when its target ID(s) no longer exist in the
     * current design — typically because a snapshot revert or auto-op removed
     * them. The seek code silently no-ops broken entries; we surface a warning
     * icon so the user knows nothing visible will happen if they activate one.
     */
    function _brokenReason(entry) {
      if (entry.feature_type === 'deformation') {
        if (entry.op_snapshot) return null   // self-contained, applies regardless
        if (!deformIds.has(entry.deformation_id)) {
          return 'Deformation target removed; this feature can no longer be applied.'
        }
      } else if (entry.feature_type === 'cluster_op') {
        if (!clusterMap[entry.cluster_id]) {
          return 'Cluster removed; this transform can no longer be applied.'
        }
      } else if (entry.feature_type === 'overhang_rotation') {
        const ids = entry.overhang_ids ?? []
        if (ids.length && ids.every(id => !overhangIds.has(id))) {
          return 'All target overhangs were removed; this rotation no longer applies.'
        }
      }
      return null
    }

    log.forEach((entry, i) => {
      // Skip any legacy checkpoint entries (stripped by backend validator but guard here too).
      if (entry.feature_type === 'checkpoint') return

      const suppressed = cursor >= 0 && i > cursor
      const brokenReason = _brokenReason(entry)

      const row = document.createElement('div')
      row.dataset.flRow = i + 1   // F0=0, F1=1, ...
      row.style.cssText = [
        'display:flex;align-items:center;gap:6px',
        'padding:3px 6px;font-size:11px;border-radius:3px',
        suppressed ? 'opacity:0.35' : 'opacity:1',
      ].join(';')

      // Optional warning icon (rendered before the type icon when the entry's
      // target no longer exists in the design).
      let warnIcon = null
      if (brokenReason) {
        warnIcon = document.createElement('span')
        warnIcon.textContent = '⚠'
        warnIcon.title = brokenReason
        warnIcon.style.cssText = 'flex-shrink:0;color:#d29922;cursor:help'
      }

      const icon  = document.createElement('span')
      icon.style.flexShrink = '0'
      const label = document.createElement('span')
      label.style.cssText = [
        'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap',
        brokenReason ? 'color:#8b6914' : 'color:#c9d1d9',
      ].join(';')

      const delBtn = document.createElement('button')
      delBtn.textContent = '×'
      delBtn.title = 'Delete this feature'
      delBtn.style.cssText = [
        'background:#2d1515;border:1px solid #c93c3c;color:#c93c3c',
        'border-radius:3px;font-size:var(--text-xs);line-height:1.4',
        'padding:3px 4px;cursor:pointer;flex-shrink:0',
      ].join(';')
      delBtn.addEventListener('click', e => {
        e.stopPropagation()
        if (_isAssemblyPartMode() && _latestDesign && api.patchInstanceDesign) {
          const design = JSON.parse(JSON.stringify(_latestDesign))
          design.feature_log?.splice(i, 1)
          api.patchInstanceDesign(_assemblyPartInstanceId, JSON.stringify(design))
            .then(result => {
              if (result) {
                _latestDesign = design
                _rebuild(_latestDesign)
              }
            })
        } else if (_partInstanceId && _partPatchFn) {
          _partPatchFn(d => { d.feature_log?.splice(i, 1) })
        } else {
          api.deleteFeature(i)
        }
      })

      if (entry.feature_type === 'deformation') {
        const op   = entry.op_snapshot
        const kind = op?.type ? (op.type.charAt(0).toUpperCase() + op.type.slice(1)) : 'Deform'
        icon.textContent  = op?.type === 'bend' ? '↪' : '↺'
        label.textContent = `F${i + 1}: ${kind}`

        if (!suppressed && op) {
          const editBtn = document.createElement('button')
          editBtn.textContent = '✎'
          editBtn.title = 'Edit this feature'
          editBtn.style.cssText = [
            'background:#21262d;border:1px solid #30363d;color:#8b949e',
            'border-radius:3px;font-size:var(--text-xs);line-height:1.4',
            'padding:3px 5px;cursor:pointer;flex-shrink:0',
          ].join(';')
          editBtn.addEventListener('click', e => {
            e.stopPropagation()
            onEditFeature?.(entry, i)
          })
          row.append(icon, label, editBtn, delBtn)
        } else {
          row.append(icon, label, delBtn)
        }
      } else if (entry.feature_type === 'overhang_rotation') {
        const ids  = entry.overhang_ids ?? []
        const lbls = entry.labels ?? []
        const displayLbl = ids.length === 1
          ? (lbls[0] ? `"${lbls[0]}"` : ids[0])
          : `${ids.length} overhangs`
        icon.textContent  = '⟳'
        label.textContent = `F${i + 1}: Orient ${displayLbl}`

        if (!suppressed) {
          const editBtn = document.createElement('button')
          editBtn.textContent = '✎'
          editBtn.title = 'Edit this orientation feature'
          editBtn.style.cssText = [
            'background:#21262d;border:1px solid #30363d;color:#8b949e',
            'border-radius:3px;font-size:var(--text-xs);line-height:1.4',
            'padding:3px 5px;cursor:pointer;flex-shrink:0',
          ].join(';')
          editBtn.addEventListener('click', e => {
            e.stopPropagation()
            onEditFeature?.(entry, i)
          })
          row.append(icon, label, editBtn, delBtn)
        } else {
          row.append(icon, label, delBtn)
        }
      } else if (entry.feature_type === 'routing-cluster') {
        // Fine Routing cluster: collapsible, contains minor mutation children.
        const isExpanded = _clusterExpanded.get(entry.id) === true
        const childCount = entry.children?.length ?? 0
        const isEvicted  = !!entry.evicted

        const chevron = document.createElement('span')
        // Header sits BELOW its sub-rows when expanded (it represents the
        // cluster's POST-state — all children applied — which by the slider's
        // top-to-bottom = earlier-to-later convention belongs at the bottom of
        // the cluster's section). So the open chevron points UP toward the
        // sub-rows above.
        chevron.textContent = isExpanded ? '▲' : '▶'
        chevron.style.cssText = 'flex-shrink:0;color:#8b949e;cursor:pointer;font-size:9px;width:10px;text-align:center'
        chevron.title = isExpanded ? 'Collapse Fine Routing' : 'Expand Fine Routing'
        chevron.addEventListener('click', e => {
          e.stopPropagation()
          _clusterExpanded.set(entry.id, !isExpanded)
          _rebuild(_latestDesign)
          // DOM laid out → measure rail notches in next frame.
          requestAnimationFrame(_positionRail)
        })

        icon.textContent  = '◇'
        icon.style.color  = '#a371f7'
        label.textContent = `F${i + 1}: ${entry.label} (${childCount})`
        row.title = `${entry.label} — ${childCount} sub-step${childCount === 1 ? '' : 's'}`

        const revertBtn = document.createElement('button')
        revertBtn.textContent = '↶'
        revertBtn.title = isEvicted
          ? 'Cluster snapshot evicted — cannot revert'
          : `Revert to before this Fine Routing cluster`
        revertBtn.disabled = isEvicted
        revertBtn.style.cssText = [
          isEvicted
            ? 'background:#1c1c1c;border:1px solid #444;color:#666;cursor:not-allowed'
            : 'background:#2d2410;border:1px solid #d29922;color:#d29922;cursor:pointer',
          'border-radius:3px;font-size:var(--text-xs);line-height:1.4',
          'padding:3px 5px;flex-shrink:0',
        ].join(';')
        if (!isEvicted) {
          revertBtn.addEventListener('click', async e => {
            e.stopPropagation()
            const ok = window.confirm(
              `Revert this Fine Routing cluster?\n\n` +
              `Removes all ${childCount} sub-step${childCount === 1 ? '' : 's'} ` +
              `and any later log entries.\n\n(Ctrl-Z restores.)`
            )
            if (!ok) return
            const resp = await api.revertToBeforeFeature(i)
            if (resp == null) {
              const err = store.getState().lastError
              window.alert(`Revert failed: ${err?.message || 'unknown error'}`)
            }
          })
        }

        // Header row: chevron + icon + label + revert + delete.
        row.append(chevron, icon, label, revertBtn, delBtn)

        // Defer broken-marker insertion (handled by the post-loop block).
        if (warnIcon) row.insertBefore(warnIcon, row.firstChild)

        // Expanded sub-rows render BEFORE the header so the header sits at
        // the bottom of the cluster's section. Slider top-to-bottom maps to
        // earlier-to-later state: sub-rows are intermediate states; the
        // header is the cluster's POST-state (= all children applied).
        if (isExpanded) {
          (entry.children ?? []).forEach((child, j) => {
            const subRow = document.createElement('div')
            // data-fl-row uses dotted notation for sub-positions; the rail
            // measurement loop picks them up automatically.
            subRow.dataset.flRow = `${i + 1}.${j}`
            subRow.style.cssText = [
              'display:flex;align-items:center;gap:6px',
              'padding:2px 6px 2px 22px;font-size:11px;border-radius:3px',
              'color:#8b949e',
            ].join(';')
            const subDot = document.createElement('span')
            subDot.textContent = '·'
            subDot.style.cssText = 'flex-shrink:0;color:#484f58;width:8px;text-align:center'
            const subLbl = document.createElement('span')
            subLbl.style.cssText = 'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'
            subLbl.textContent = `F${i + 1}-${j + 1}: ${child.label}`
            subRow.title = subLbl.textContent
            subRow.append(subDot, subLbl)
            list.appendChild(subRow)
          })
        }
        // Header appended LAST so it sits at the bottom of its section.
        list.appendChild(row)

        // Skip the generic post-loop append + warnIcon insert (we already did them).
        return
      } else if (entry.feature_type === 'snapshot') {
        // Auto-op snapshot entry: revertable, with pre-state design payload.
        icon.textContent  = '◆'
        icon.style.color  = '#58a6ff'
        label.textContent = `F${i + 1}: ${entry.label || entry.op_kind}`
        const sizeKb = entry.snapshot_size_bytes ? Math.round(entry.snapshot_size_bytes / 1024) : 0
        const paramSummary = (() => {
          if (!entry.params) return ''
          const keys = Object.keys(entry.params).slice(0, 3)
          if (!keys.length) return ''
          return ' · ' + keys.map(k => `${k}=${JSON.stringify(entry.params[k])}`).join(' ')
        })()
        row.title = `${entry.label}${paramSummary} — ${sizeKb} KB pre-state snapshot`

        const revertBtn = document.createElement('button')
        revertBtn.textContent = '↶'
        const isEvicted = !!entry.evicted
        revertBtn.title = isEvicted
          ? 'Snapshot evicted to save space — cannot revert'
          : `Revert to before ${entry.label}`
        revertBtn.disabled = isEvicted
        revertBtn.style.cssText = [
          isEvicted
            ? 'background:#1c1c1c;border:1px solid #444;color:#666;cursor:not-allowed'
            : 'background:#2d2410;border:1px solid #d29922;color:#d29922;cursor:pointer',
          'border-radius:3px;font-size:var(--text-xs);line-height:1.4',
          'padding:3px 5px;flex-shrink:0',
        ].join(';')
        if (!isEvicted) {
          revertBtn.addEventListener('click', async e => {
            e.stopPropagation()
            const ok = window.confirm(
              `Revert to before "${entry.label}"?\n\n` +
              `This restores the design to its state before this operation ran, ` +
              `and removes all feature-log entries from this point onward.\n\n` +
              `(You can undo this with Ctrl-Z.)`
            )
            if (!ok) return
            const resp = await api.revertToBeforeFeature(i)
            if (resp == null) {
              const err = store.getState().lastError
              window.alert(`Revert failed: ${err?.message || 'unknown error'}`)
            }
          })
        }

        // Edit button: visible for editable snapshot kinds. Most kinds gate
        // the button on "latest snapshot in the log" (the backend's
        // edit-feature endpoint requires that). The 'linker-add' kind opens
        // the Overhangs Manager modal locally instead, so it doesn't share
        // that constraint — the user can adjust a linker any time.
        const _EDIT_REPLAY_KINDS = new Set([
          'bundle-create', 'extrude-segment', 'extrude-continuation',
          'extrude-deformed-continuation', 'overhang-extrude',
        ])
        const isLinkerAdd = entry.op_kind === 'linker-add'
        const isEditable = (_EDIT_REPLAY_KINDS.has(entry.op_kind) || isLinkerAdd) && !isEvicted
        const hasLaterSnapshot = isEditable && log.slice(i + 1).some(e => e.feature_type === 'snapshot')
        // linker-add isn't a topology replay — Overhangs Manager just opens —
        // so a later snapshot is fine.
        const editAllowed = isEditable && (isLinkerAdd || !hasLaterSnapshot)

        let editBtn = null
        if (isEditable) {
          editBtn = document.createElement('button')
          editBtn.textContent = '✎'
          editBtn.title = editAllowed
            ? (isLinkerAdd
                ? `Open Overhangs Manager for this linker`
                : `Edit ${entry.label} parameters (currently length_bp=${entry.params?.length_bp ?? '?'})`)
            : 'Cannot edit: a later snapshot exists. Revert to this point first.'
          editBtn.disabled = !editAllowed
          editBtn.style.cssText = [
            editAllowed
              ? 'background:#21262d;border:1px solid #30363d;color:#8b949e;cursor:pointer'
              : 'background:#1c1c1c;border:1px solid #444;color:#666;cursor:not-allowed',
            'border-radius:3px;font-size:var(--text-xs);line-height:1.4',
            'padding:3px 5px;flex-shrink:0',
          ].join(';')
          if (editAllowed) {
            editBtn.addEventListener('click', async e => {
              e.stopPropagation()
              if (isLinkerAdd) {
                // Open Overhangs Manager preselected on the linker's two
                // overhangs so the user lands directly on the relevant row.
                const ovhgIds = [entry.params?.overhang_a_id, entry.params?.overhang_b_id]
                  .filter(Boolean)
                onOpenOverhangsManager?.(ovhgIds)
                return
              }
              const current = entry.params?.length_bp
              if (current == null) {
                window.alert(`This op has no length_bp parameter to edit.`)
                return
              }
              const raw = window.prompt(
                `Edit ${entry.label}\n\n` +
                `New length_bp (current: ${current}):`,
                String(current)
              )
              if (raw == null) return
              const newLen = parseInt(raw, 10)
              if (!Number.isFinite(newLen) || newLen === current) return
              const newParams = { ...entry.params, length_bp: newLen }
              const resp = await api.editFeature(i, newParams)
              if (resp == null) {
                const err = store.getState().lastError
                window.alert(`Edit failed: ${err?.message || 'unknown error'}`)
              }
            })
          }
        }

        if (editBtn) {
          row.append(icon, label, editBtn, revertBtn, delBtn)
        } else {
          row.append(icon, label, revertBtn, delBtn)
        }
      } else {
        const cluster = clusterMap[entry.cluster_id]
        // `source` is set by ops other than the manual move/rotate UI — e.g.
        // 'relax' from Relax-Linker, 'bind-relax'/'unbind-revert' from the
        // OverhangBinding bound-toggle — so the user can tell at a glance
        // which entries came from which path. Manual entries leave source
        // unset.
        let iconText = '↕'
        let humanSource = entry.source
        if (entry.source === 'bind-relax')        { iconText = '🔗'; humanSource = 'bind' }
        else if (entry.source === 'unbind-revert') { iconText = '🔓'; humanSource = 'unbind' }
        icon.textContent = iconText
        const sourcePrefix = humanSource ? `(${humanSource}) ` : ''
        label.textContent = `F${i + 1}: ${sourcePrefix}move/rotate${cluster ? `  ${cluster.name}` : ''}`

        if (!suppressed) {
          const editBtn = document.createElement('button')
          editBtn.textContent = '✎'
          editBtn.title = 'Edit this move/rotate feature'
          editBtn.style.cssText = [
            'background:#21262d;border:1px solid #30363d;color:#8b949e',
            'border-radius:3px;font-size:var(--text-xs);line-height:1.4',
            'padding:3px 5px;cursor:pointer;flex-shrink:0',
          ].join(';')
          editBtn.addEventListener('click', e => {
            e.stopPropagation()
            onEditFeature?.(entry, i)
          })
          row.append(icon, label, editBtn, delBtn)
        } else {
          row.append(icon, label, delBtn)
        }
      }

      // Insert the warning icon ahead of the type icon if the entry is broken.
      if (warnIcon) row.insertBefore(warnIcon, row.firstChild)

      list.appendChild(row)
    })

    _positionRail()
    _applyHighlights()
  }

  function _rebuildAssembly(assembly) {
    _refreshTitle()
    _latestAssembly = assembly
    list.innerHTML = ''
    const configs = assembly?.configurations ?? []
    if (!configs.length) {
      const empty = document.createElement('div')
      empty.style.cssText = 'color:#484f58;font-size:11px;padding:3px 6px'
      empty.textContent = 'No configurations captured.'
      list.appendChild(empty)
      _notchYs = []
      rail.querySelectorAll('.fl-notch').forEach(n => n.remove())
      thumb.style.top = '0px'
      return
    }
    configs.forEach((cfg, i) => {
      const row = document.createElement('div')
      row.style.cssText = [
        'display:flex;align-items:center;gap:6px',
        'padding:3px 6px;font-size:11px;border-radius:3px',
        cfg.id === assembly.configuration_cursor ? 'background:#161b22' : '',
      ].join(';')
      row.title = 'Click to restore this configuration'
      const icon = document.createElement('span')
      icon.textContent = '◆'
      icon.style.color = '#58a6ff'
      const label = document.createElement('span')
      label.style.cssText = 'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#c9d1d9'
      const count = cfg.instance_states?.length ?? 0
      label.textContent = `${cfg.name ?? `Config ${i + 1}`} — ${count} part${count === 1 ? '' : 's'}`
      row.addEventListener('click', () => _seekAssemblyConfig(i))

      const goBtn = document.createElement('button')
      goBtn.textContent = '▶'
      goBtn.title = 'Animate to this configuration'
      goBtn.style.cssText = _goStyle
      goBtn.addEventListener('click', async e => {
        e.stopPropagation()
        await _animateAssemblyConfig(cfg)
      })

      const overwriteBtn = document.createElement('button')
      overwriteBtn.textContent = '⟳'
      overwriteBtn.title = 'Overwrite configuration with current assembly state'
      overwriteBtn.style.cssText = _updateStyle
      overwriteBtn.addEventListener('click', async e => {
        e.stopPropagation()
        await api.updateAssemblyConfiguration?.(cfg.id, { overwrite_current: true })
      })

      const editBtn = document.createElement('button')
      editBtn.textContent = '✎'
      editBtn.title = 'Rename configuration'
      editBtn.style.cssText = _editStyle

      function _enterEdit(e) {
        e.stopPropagation()
        const inp = document.createElement('input')
        inp.type = 'text'
        inp.value = cfg.name ?? `Config ${i + 1}`
        inp.style.cssText = 'flex:1;min-width:0;box-sizing:border-box;' +
          'background:#0d1117;border:1px solid #30363d;border-radius:4px;' +
          'color:#c9d1d9;padding:2px 5px;font-family:var(--font-ui);font-size:11px;'
        label.replaceWith(inp)
        inp.focus()
        inp.select()
        editBtn.textContent = '✓'
        editBtn.title = 'Save name'
        editBtn.style.cssText = _saveStyle

        async function _save() {
          const oldName = cfg.name ?? `Config ${i + 1}`
          const newName = inp.value.trim() || oldName
          inp.replaceWith(label)
          label.textContent = `${newName} — ${count} part${count === 1 ? '' : 's'}`
          editBtn.textContent = '✎'
          editBtn.title = 'Rename configuration'
          editBtn.style.cssText = _editStyle
          editBtn.onclick = _enterEdit
          if (newName !== oldName) await api.updateAssemblyConfiguration?.(cfg.id, { name: newName })
        }

        inp.addEventListener('keydown', e2 => {
          e2.stopPropagation()
          if (e2.key === 'Enter') { e2.preventDefault(); _save() }
          if (e2.key === 'Escape') {
            inp.replaceWith(label)
            editBtn.textContent = '✎'
            editBtn.title = 'Rename configuration'
            editBtn.style.cssText = _editStyle
            editBtn.onclick = _enterEdit
          }
        })
        editBtn.onclick = e2 => { e2.stopPropagation(); _save() }
      }
      editBtn.onclick = _enterEdit

      const delBtn = document.createElement('button')
      delBtn.textContent = '×'
      delBtn.title = 'Delete configuration'
      delBtn.style.cssText = _delStyle
      delBtn.addEventListener('click', async e => {
        e.stopPropagation()
        await api.deleteAssemblyConfiguration?.(cfg.id)
      })

      row.append(icon, label, goBtn, overwriteBtn, editBtn, delBtn)
      list.appendChild(row)
    })
    _notchYs = []
    rail.querySelectorAll('.fl-notch').forEach(n => n.remove())
    thumb.style.top = '0px'
  }

  // ── Assembly feature log (target dropdown = "Assembly") ────────────────────
  function _rebuildAssemblyFeatureLog(assembly) {
    _latestAssembly = assembly
    _refreshTitle()
    list.innerHTML = ''
    const log    = assembly?.feature_log ?? []
    const cursor = assembly?.feature_log_cursor ?? -1

    // F0 row — always present.
    const f0 = document.createElement('div')
    f0.dataset.flRow = '0'
    f0.style.cssText = 'font-size:11px;color:#6e7681;padding:3px 6px;border-radius:3px'
    f0.textContent = 'F0 — initial'
    list.appendChild(f0)

    if (!log.length) {
      _positionRail()
      return
    }

    // Op kinds the backend's /assembly/features/{i}/edit route knows how to
    // re-run. Stays in sync with _EDITABLE_OP_KINDS in backend/api/assembly.py.
    const editableOpKinds = new Set([
      'assembly-polymerize',
      'assembly-overhang-connection-add',
      'assembly-overhang-connection-patch',
    ])

    const isLatest = i => i === log.length - 1

    log.forEach((entry, i) => {
      const suppressed = cursor >= 0 && i > cursor
      const row = document.createElement('div')
      row.dataset.flRow = i + 1
      row.style.cssText = [
        'display:flex;align-items:center;gap:6px',
        'padding:3px 6px;font-size:11px;border-radius:3px',
        suppressed ? 'opacity:0.35' : 'opacity:1',
      ].join(';')

      const icon  = document.createElement('span')
      icon.style.flexShrink = '0'
      icon.textContent = '◆'
      icon.style.color = '#58a6ff'

      const label = document.createElement('span')
      label.style.cssText = 'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#c9d1d9'
      label.textContent = `F${i + 1}: ${entry.label || entry.op_kind || 'op'}`
      label.title = entry.label || entry.op_kind || ''

      row.append(icon, label)

      // ── Revert button — restore pre-state + truncate from i onward ────
      const revertBtn = document.createElement('button')
      revertBtn.textContent = '↶'
      revertBtn.title = `Revert to before F${i + 1} (drops all later entries)`
      revertBtn.style.cssText = [
        'background:#2d2410;border:1px solid #d29922;color:#d29922',
        'border-radius:3px;font-size:var(--text-xs);line-height:1.4',
        'padding:3px 5px;cursor:pointer;flex-shrink:0',
      ].join(';')
      revertBtn.addEventListener('click', async e => {
        e.stopPropagation()
        const ok = window.confirm(
          `Revert to before F${i + 1}?\n\nThis drops every entry from F${i + 1} ` +
          `onward. Ctrl-Z restores them.`,
        )
        if (!ok) return
        const resp = await api.revertAssemblyToBeforeFeature(i)
        if (resp == null) {
          const err = store.getState().lastError
          window.alert(`Revert failed: ${err?.message || 'unknown error'}`)
        }
      })

      // ── Edit button — supported op kinds, latest entry only ──────────
      if (editableOpKinds.has(entry.op_kind) && isLatest(i) && !suppressed) {
        const editBtn = document.createElement('button')
        editBtn.textContent = '✎'
        editBtn.title = `Edit F${i + 1}`
        editBtn.style.cssText = [
          'background:#21262d;border:1px solid #30363d;color:#8b949e',
          'border-radius:3px;font-size:var(--text-xs);line-height:1.4',
          'padding:3px 5px;cursor:pointer;flex-shrink:0',
        ].join(';')
        editBtn.addEventListener('click', async e => {
          e.stopPropagation()
          const newParams = await _promptEditAssemblyEntry(entry)
          if (!newParams) return
          const resp = await api.editAssemblyFeature(i, newParams)
          if (resp == null) {
            const err = store.getState().lastError
            window.alert(`Edit failed: ${err?.message || 'unknown error'}`)
          }
        })
        row.appendChild(editBtn)
      }

      // ── Delete button — surgical when later entries are replayable ────
      const delBtn = document.createElement('button')
      delBtn.textContent = '×'
      delBtn.title = isLatest(i)
        ? `Delete F${i + 1}`
        : `Delete F${i + 1} (replays later entries; fails if any aren't replayable)`
      delBtn.style.cssText = [
        'background:#2d1515;border:1px solid #c93c3c;color:#c93c3c',
        'border-radius:3px;font-size:var(--text-xs);line-height:1.4',
        'padding:3px 4px;cursor:pointer;flex-shrink:0',
      ].join(';')
      delBtn.addEventListener('click', async e => {
        e.stopPropagation()
        const isMid = !isLatest(i)
        const msg = isMid
          ? `Delete F${i + 1}?\n\nLater entries will be replayed against the ` +
            `pre-state. If any later op isn't replayable, the delete is ` +
            `rejected and the assembly is unchanged.`
          : `Delete F${i + 1}?\n\nUndoes the most recent assembly op (Ctrl-Z restores).`
        if (!window.confirm(msg)) return
        const resp = await api.deleteAssemblyFeature(i)
        if (resp == null) {
          const err = store.getState().lastError
          window.alert(`Delete failed: ${err?.message || 'unknown error'}`)
        }
      })

      row.append(revertBtn, delBtn)
      // Click anywhere else in the row → scrub the slider to this entry.
      row.addEventListener('click', () => _seek(i))
      list.appendChild(row)
    })

    _positionRail()
  }

  /**
   * Lightweight prompt for editing an assembly feature-log entry.
   * Returns a params object suitable for POST /assembly/features/{i}/edit
   * (i.e. only the fields the user changed), or null if cancelled.
   *
   * - assembly-polymerize: prompts for count + direction.
   * - assembly-overhang-connection-{add,patch}: prompts for length_value,
   *   length_unit, bridge_sequence.
   */
  async function _promptEditAssemblyEntry(entry) {
    const params = entry.params || {}
    if (entry.op_kind === 'assembly-polymerize') {
      const cur = String(params.count ?? 3)
      const countRaw = window.prompt(`Chain length (>= 2):`, cur)
      if (countRaw == null) return null
      const count = parseInt(countRaw, 10)
      if (!(count >= 2)) { window.alert('Chain length must be >= 2.'); return null }
      const dirCur = params.direction ?? 'forward'
      const dirRaw = window.prompt(`Direction (forward / backward / both):`, dirCur)
      if (dirRaw == null) return null
      const direction = dirRaw.trim().toLowerCase()
      if (!['forward', 'backward', 'both'].includes(direction)) {
        window.alert('Direction must be forward, backward, or both.')
        return null
      }
      return { count, direction }
    }
    if (entry.op_kind === 'assembly-overhang-connection-add' ||
        entry.op_kind === 'assembly-overhang-connection-patch') {
      const lvCur = String(params.length_value ?? 0)
      const lvRaw = window.prompt(`length_value:`, lvCur)
      if (lvRaw == null) return null
      const length_value = parseFloat(lvRaw)
      if (!isFinite(length_value)) { window.alert('length_value must be a number.'); return null }
      const unitCur = params.length_unit ?? 'bp'
      const unitRaw = window.prompt(`length_unit (bp / nm):`, unitCur)
      if (unitRaw == null) return null
      const length_unit = unitRaw.trim().toLowerCase()
      if (!['bp', 'nm'].includes(length_unit)) { window.alert('length_unit must be bp or nm.'); return null }
      const seqCur = params.bridge_sequence ?? ''
      const seqRaw = window.prompt(`bridge_sequence (blank for none):`, seqCur)
      if (seqRaw == null) return null
      const bridge_sequence = seqRaw.trim() || null
      return { length_value, length_unit, bridge_sequence }
    }
    window.alert(`Edit not supported for ${entry.op_kind}.`)
    return null
  }

  // ── Selection-driven highlighting ──────────────────────────────────────────
  // When the user selects a strand / domain / cluster / overhang, every feature
  // log entry whose payload references the selected ID(s) gets a green outline.
  // Outline (not border) is used so the row layout doesn't shift when the
  // highlight toggles.

  function _collectSelectedIds(state, design) {
    const ids = new Set()
    if (state.activeClusterId) ids.add(state.activeClusterId)

    const sel = state.selectedObject
    if (sel) {
      if (sel.type === 'strand') {
        ids.add(sel.id)
        const strand = design?.strands?.find(s => s.id === sel.id)
        for (const d of strand?.domains ?? []) {
          if (d.overhang_id) ids.add(d.overhang_id)
          if (d.helix_id)    ids.add(d.helix_id)
        }
      } else if (sel.type === 'domain') {
        const sid = sel.data?.strand_id
        if (sid) ids.add(sid)
        if (sel.data?.overhang_id) ids.add(sel.data.overhang_id)
        if (sel.data?.helix_id)    ids.add(sel.data.helix_id)
      } else if (sel.type === 'helix') {
        ids.add(sel.id)
      }
    }

    for (const sid of state.multiSelectedStrandIds ?? []) {
      ids.add(sid)
      const strand = design?.strands?.find(s => s.id === sid)
      for (const d of strand?.domains ?? []) {
        if (d.overhang_id) ids.add(d.overhang_id)
        if (d.helix_id)    ids.add(d.helix_id)
      }
    }
    for (const dom of state.multiSelectedDomainIds ?? []) {
      ids.add(dom.strandId)
      const strand = design?.strands?.find(s => s.id === dom.strandId)
      const d = strand?.domains?.[dom.domainIndex]
      if (d?.overhang_id) ids.add(d.overhang_id)
      if (d?.helix_id)    ids.add(d.helix_id)
    }
    for (const oid of state.multiSelectedOverhangIds ?? []) {
      ids.add(oid)
    }
    return ids
  }

  function _scanForIds(obj, idSet) {
    if (obj == null) return false
    if (typeof obj === 'string') return idSet.has(obj)
    if (Array.isArray(obj))      return obj.some(v => _scanForIds(v, idSet))
    if (typeof obj === 'object') return Object.values(obj).some(v => _scanForIds(v, idSet))
    return false
  }

  function _entryMatches(entry, idSet) {
    if (!entry || idSet.size === 0) return false
    switch (entry.feature_type) {
      case 'deformation':
        if (entry.deformation_id && idSet.has(entry.deformation_id)) return true
        return _scanForIds(entry.op_snapshot, idSet)
      case 'cluster_op':
        return idSet.has(entry.cluster_id)
      case 'overhang_rotation':
        return (entry.overhang_ids ?? []).some(oid => idSet.has(oid)) ||
               (entry.sub_domain_ids ?? []).some(sid => sid && idSet.has(sid))
      case 'snapshot':
        return _scanForIds(entry.params, idSet)
      case 'routing-cluster':
        return (entry.children ?? []).some(c => _scanForIds(c.params, idSet))
    }
    return false
  }

  const _HIGHLIGHT_STYLE = '2px solid #3fb950'

  function _applyHighlights() {
    if (_collapsed) return
    if (_isAssemblyConfigMode()) return
    const state  = store.getState()
    const design = _latestDesign
    const log    = design?.feature_log ?? []
    const ids    = _collectSelectedIds(state, design)

    list.querySelectorAll('[data-fl-row]').forEach(row => {
      const flRow = row.dataset.flRow
      let matched = false
      if (typeof flRow === 'string' && flRow.includes('.')) {
        // Sub-row: "K.j" → log[K-1].children[j]
        const [kStr, jStr] = flRow.split('.', 2)
        const k = parseInt(kStr, 10) - 1
        const j = parseInt(jStr, 10)
        const child = log[k]?.children?.[j]
        matched = child ? _scanForIds(child.params, ids) : false
      } else {
        const flN = parseInt(flRow, 10)
        if (flN > 0) matched = _entryMatches(log[flN - 1], ids)
      }
      if (matched) {
        row.style.outline = _HIGHLIGHT_STYLE
        row.style.outlineOffset = '-2px'
      } else {
        row.style.removeProperty('outline')
        row.style.removeProperty('outline-offset')
      }
    })
  }

  store.subscribeSlice('selection', () => { _applyHighlights() })

  // ── Reactivity ─────────────────────────────────────────────────────────────
  store.subscribeSlice('design', (n, p) => {
    if (_partInstanceId) return   // part context overrides design context
    if (store.getState().assemblyActive) return
    if (n.currentDesign === p.currentDesign) return
    const prev = p.currentDesign
    const next = n.currentDesign
    _log('store update: cursor', prev?.feature_log_cursor, '→', next?.feature_log_cursor,
         '| deforms', prev?.deformations?.length, '→', next?.deformations?.length)
    _latestDesign = next
    if (!_collapsed) { _rebuild(_latestDesign) }
  })

  store.subscribeSlice('assembly', (n, p) => {
    if (n.assemblyActive) {
      _partInstanceId = null
      _partPatchFn = null
    } else if (_partInstanceId) return
    if (n.currentAssembly === p.currentAssembly && n.assemblyActive === p.assemblyActive) return
    _latestAssembly = n.currentAssembly
    if (!n.assemblyActive) {
      _assemblyPartInstanceId = null
      _assemblyFeatureMode = false
    } else if (_assemblyPartInstanceId) {
      const stillExists = n.currentAssembly?.instances?.some(i => i.id === _assemblyPartInstanceId)
      if (!stillExists) {
        _assemblyPartInstanceId = null
        _latestDesign = null
        _assemblyFeatureMode = true   // default back to assembly target
      } else if (n.currentAssembly !== p.currentAssembly) {
        _selectAssemblyPart(_assemblyPartInstanceId)
        return
      }
    } else if (n.assemblyActive && !p.assemblyActive) {
      // Just entered assembly mode and nothing was previously selected →
      // default the target dropdown to "Assembly".
      _assemblyFeatureMode = true
    }
    _refreshTitle()
    if (!_collapsed) {
      if (n.assemblyActive && n.currentAssembly) _renderCurrentView()
      else _rebuild(store.getState().currentDesign)
    }
  })

  _latestDesign = store.getState().currentDesign
  _latestAssembly = store.getState().currentAssembly
  // If we mount while assembly mode is already active (e.g. page reload),
  // default the target to "Assembly".
  if (store.getState().assemblyActive && store.getState().currentAssembly) {
    _assemblyFeatureMode = true
  }
  _refreshTitle()
  _renderCurrentView()

  function setPartContext(instanceId, design, patchFn) {
    _partInstanceId = instanceId
    _partPatchFn    = patchFn
    _latestDesign   = design
    _refreshTitle()
    if (!_collapsed) _rebuild(_latestDesign)
  }

  function clearPartContext() {
    _partInstanceId = null
    _partPatchFn    = null
    _latestDesign   = store.getState().currentDesign
    _latestAssembly = store.getState().currentAssembly
    _refreshTitle()
    if (!_collapsed) _renderCurrentView()
  }

  return { setPartContext, clearPartContext }
}
