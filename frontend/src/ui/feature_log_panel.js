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
 * Each feature row shows: "FN: Bend bp A–B" or "FN: Cluster transform".
 *
 * @param {object} store
 * @param {object} opts.api — API module (seekFeatures)
 */

import { showPersistentToast, dismissToast } from './toast.js'

export function initFeatureLogPanel(store, { api, onEditFeature }) {
  const panelBody = document.getElementById('feature-log-panel-body')
  const heading   = document.getElementById('feature-log-panel-heading')
  const arrow     = document.getElementById('feature-log-panel-arrow')
  if (!panelBody || !heading) return

  let _collapsed    = false
  let _latestDesign = null
  let _notchYs      = []   // [y-centre-px] for F0, F1..FN relative to rail
  let _isSeeking    = false

  // ── Collapse / expand ──────────────────────────────────────────────────────
  heading.addEventListener('click', () => {
    _collapsed = !_collapsed
    panelBody.style.display = _collapsed ? 'none' : ''
    arrow.textContent = _collapsed ? '▶' : '▼'
    if (!_collapsed) { _rebuild(_latestDesign); _positionRail() }
  })

  // ── DOM structure ──────────────────────────────────────────────────────────
  // fl-wrap: flex row; fl-rail on left, fl-list on right.
  const wrap = document.createElement('div')
  wrap.style.cssText = 'display:flex;gap:0;position:relative'

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
  panelBody.appendChild(wrap)

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
      const result = await api.seekFeatures(position)
      const d = result?.design
      _log('seek DONE pos=', position, '→ cursor=', d?.feature_log_cursor, 'deforms=', d?.deformations?.length)
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

  // ── Notch positioning ──────────────────────────────────────────────────────
  /**
   * Measure the Y-centre of each row (F0 row + feature rows) relative to rail,
   * place notch ticks, and position the thumb at the current cursor.
   */
  function _positionRail() {
    if (!_latestDesign) { _log('_positionRail: no design, skip'); return }
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
    if (!_latestDesign || !_notchYs.length) return
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
    const cursor = _latestDesign?.feature_log_cursor ?? -1
    let _initialNotch
    if (cursor === -2)     _initialNotch = 0
    else if (cursor < 0)   _initialNotch = _notchYs.length - 1
    else                   _initialNotch = Math.min(cursor + 1, _notchYs.length - 1)
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
        const pos = finalNotch === 0 ? -2 : finalNotch - 1
        _log('drag RELEASE at notch', finalNotch, '→ seeking pos=', pos)
        _seek(pos)
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
    list.innerHTML = ''
    const log    = design?.feature_log ?? []
    const cursor = design?.feature_log_cursor ?? -1
    _log('_rebuild: log.length=', log.length, 'cursor=', cursor, 'deforms=', design?.deformations?.length)

    // F0 row — always present, never suppressed
    const f0Row = document.createElement('div')
    f0Row.dataset.flRow = '0'
    f0Row.style.cssText = 'font-size:11px;color:#6e7681;padding:4px 6px;border-radius:3px'
    f0Row.textContent = 'F0 — initial'
    list.appendChild(f0Row)

    if (!log.length) {
      _positionRail()
      return
    }

    const clusterMap = Object.fromEntries(
      (design?.cluster_transforms ?? []).map(c => [c.id, c])
    )

    log.forEach((entry, i) => {
      // Skip any legacy checkpoint entries (stripped by backend validator but guard here too).
      if (entry.feature_type === 'checkpoint') return

      const suppressed = cursor >= 0 && i > cursor

      const row = document.createElement('div')
      row.dataset.flRow = i + 1   // F0=0, F1=1, ...
      row.style.cssText = [
        'display:flex;align-items:center;gap:6px',
        'padding:4px 6px;font-size:11px;border-radius:3px',
        suppressed ? 'opacity:0.35' : 'opacity:1',
      ].join(';')

      const icon  = document.createElement('span')
      icon.style.flexShrink = '0'
      const label = document.createElement('span')
      label.style.cssText = 'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#c9d1d9'

      const delBtn = document.createElement('button')
      delBtn.textContent = '×'
      delBtn.title = 'Delete this feature'
      delBtn.style.cssText = [
        'background:#2d1515;border:1px solid #c93c3c;color:#c93c3c',
        'border-radius:3px;font-size:10px;line-height:1.4',
        'padding:1px 4px;cursor:pointer;flex-shrink:0',
      ].join(';')
      delBtn.addEventListener('click', e => {
        e.stopPropagation()
        api.deleteFeature(i)
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
            'border-radius:3px;font-size:10px;line-height:1.4',
            'padding:1px 5px;cursor:pointer;flex-shrink:0',
          ].join(';')
          editBtn.addEventListener('click', e => {
            e.stopPropagation()
            onEditFeature?.(entry, i)
          })
          row.append(icon, label, editBtn, delBtn)
        } else {
          row.append(icon, label, delBtn)
        }
      } else {
        const cluster = clusterMap[entry.cluster_id]
        icon.textContent  = '⟳'
        label.textContent = `F${i + 1}: Cluster transform${cluster ? `  ${cluster.name}` : ''}`
        row.append(icon, label, delBtn)
      }

      list.appendChild(row)
    })

    _positionRail()
  }

  // ── Reactivity ─────────────────────────────────────────────────────────────
  store.subscribeSlice('design', (n, p) => {
    if (n.currentDesign === p.currentDesign) return
    const prev = p.currentDesign
    const next = n.currentDesign
    _log('store update: cursor', prev?.feature_log_cursor, '→', next?.feature_log_cursor,
         '| deforms', prev?.deformations?.length, '→', next?.deformations?.length)
    _latestDesign = next
    if (!_collapsed) { _rebuild(_latestDesign) }
  })

  _latestDesign = store.getState().currentDesign
  _rebuild(_latestDesign)
}
