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

export function initFeatureLogPanel(store, { api, onEditFeature, onAnimateConfiguration }) {
  const panelBody = document.getElementById('feature-log-panel-body')
  const heading   = document.getElementById('feature-log-panel-heading')
  const arrow     = document.getElementById('feature-log-panel-arrow')
  const titleEl   = heading?.querySelector('span')
  if (!panelBody || !heading) return

  let _collapsed    = false
  let _latestDesign = null
  let _latestAssembly = null
  let _notchYs      = []   // [y-centre-px] for F0, F1..FN relative to rail
  let _isSeeking    = false

  // ── Part context ──────────────────────────────────────────────────────────────
  let _partInstanceId = null
  let _partPatchFn    = null

  // ── Collapse / expand ──────────────────────────────────────────────────────
  heading.addEventListener('click', () => {
    _collapsed = !_collapsed
    panelBody.style.display = _collapsed ? 'none' : ''
    arrow.classList.toggle('is-collapsed', _collapsed)
    if (!_collapsed) { _rebuild(_latestDesign); _positionRail() }
  })

  // ── DOM structure ──────────────────────────────────────────────────────────
  // fl-wrap: flex row; fl-rail on left, fl-list on right.
  const wrap = document.createElement('div')
  wrap.style.cssText = 'display:flex;gap:0;position:relative'

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
  panelBody.append(toolbar, wrap)

  function _isAssemblyConfigMode() {
    const s = store.getState()
    return !_partInstanceId && !!s.assemblyActive && !!s.currentAssembly
  }

  function _refreshTitle() {
    if (titleEl) titleEl.textContent = _isAssemblyConfigMode() ? 'Configuration Snapshot' : 'Feature Log'
    toolbar.style.display = _isAssemblyConfigMode() ? '' : 'none'
    rail.style.display = _isAssemblyConfigMode() ? 'none' : ''
  }

  captureCfgBtn.addEventListener('click', async () => {
    const assembly = store.getState().currentAssembly
    if (!assembly) return
    const n = (assembly.configurations?.length ?? 0) + 1
    await api.createAssemblyConfiguration?.(`Config ${n}`)
  })

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
  let _pendingSeekPos = null   // latest position requested while a seek was in-flight

  async function _seek(position) {
    if (_isSeeking) {
      _log('seek QUEUED (in-flight replaced), pos=', position)
      _pendingSeekPos = position
      return
    }
    _isSeeking = true
    _log('seek START pos=', position)
    const label = position === -2 ? 'F0 — initial' : `F${position + 1}`
    showPersistentToast(`Loading ${label}…`)
    try {
      if (_partInstanceId && _partPatchFn) {
        await _partPatchFn(d => { d.feature_log_cursor = position })
      } else {
        const result = await api.seekFeatures(position)
        const d = result?.design
        _log('seek DONE pos=', position, '→ cursor=', d?.feature_log_cursor, 'deforms=', d?.deformations?.length)
      }
    } catch (err) {
      _log('seek ERROR pos=', position, err)
    } finally {
      _isSeeking = false
      if (_pendingSeekPos === null) dismissToast()
      // Flush any position requested while this seek was in-flight.
      if (_pendingSeekPos !== null) {
        const next = _pendingSeekPos
        _pendingSeekPos = null
        _log('seek FLUSH pending pos=', next)
        _seek(next)
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

    // Gather rows in order: F0 row is always first child of list.
    const rows = list.querySelectorAll('[data-fl-row]')
    _notchYs = []
    for (const row of rows) {
      const r = row.getBoundingClientRect()
      const y = r.top + r.height / 2 - wrapRect.top
      _log(`  row data-fl-row=${row.dataset.flRow} top=${r.top.toFixed(1)} h=${r.height.toFixed(1)} → notchY=${y.toFixed(1)}`)
      _notchYs.push(y)
    }
    _log('_positionRail: _notchYs=', _notchYs)

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
    if (!_latestDesign) return
    const cursor = _latestDesign.feature_log_cursor ?? -1
    // cursor=-2 → F0 (index 0); cursor=-1 or ≥last → last notch; cursor=N → notch N+1
    let notchIdx
    if (cursor === -2) {
      notchIdx = 0
    } else if (cursor < 0) {
      notchIdx = _notchYs.length - 1
    } else {
      notchIdx = Math.min(cursor + 1, _notchYs.length - 1)
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
    } else {
      const cursor = _latestDesign?.feature_log_cursor ?? -1
      if (cursor === -2)     _initialNotch = 0
      else if (cursor < 0)   _initialNotch = _notchYs.length - 1
      else                   _initialNotch = Math.min(cursor + 1, _notchYs.length - 1)
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
          const pos = finalNotch === 0 ? -2 : finalNotch - 1
          _log('drag RELEASE at notch', finalNotch, '→ seeking pos=', pos)
          _seek(pos)
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
        if (_partInstanceId && _partPatchFn) {
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

        // Edit button: only visible for extrusion-kind snapshots and only when
        // this is the LATEST snapshot in the log (matches backend constraint).
        const _EDITABLE_KINDS = new Set([
          'bundle-create', 'extrude-segment', 'extrude-continuation',
          'extrude-deformed-continuation', 'overhang-extrude',
        ])
        const isEditable = _EDITABLE_KINDS.has(entry.op_kind) && !isEvicted
        const hasLaterSnapshot = isEditable && log.slice(i + 1).some(e => e.feature_type === 'snapshot')
        const editAllowed = isEditable && !hasLaterSnapshot

        let editBtn = null
        if (isEditable) {
          editBtn = document.createElement('button')
          editBtn.textContent = '✎'
          editBtn.title = editAllowed
            ? `Edit ${entry.label} parameters (currently length_bp=${entry.params?.length_bp ?? '?'})`
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
        icon.textContent  = '↕'
        label.textContent = `F${i + 1}: move/rotate${cluster ? `  ${cluster.name}` : ''}`

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
    _refreshTitle()
    if (!_collapsed) {
      if (n.assemblyActive && n.currentAssembly) _rebuildAssembly(n.currentAssembly)
      else _rebuild(store.getState().currentDesign)
    }
  })

  _latestDesign = store.getState().currentDesign
  _latestAssembly = store.getState().currentAssembly
  _refreshTitle()
  _rebuild(_latestDesign)

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
    if (!_collapsed) _rebuild(_latestDesign)
  }

  return { setPartContext, clearPartContext }
}
