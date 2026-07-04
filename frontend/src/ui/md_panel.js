/**
 * ui/md_panel.js — Molecular Dynamics panel.
 *
 * A server-side config picker loads a NADOC/NAMD MD manifest or .namd/.conf.
 * The backend resolves PSF/PDB/DCD paths and streams frames through /ws/md-run.
 * Trajectory streaming goes through /ws/md-run.
 *
 * Repr modes:
 *   "nadoc"     → designRenderer.applyFemPositions(updates)
 *   "beads"     → mdOverlay.update(positions, beadRadius, opacity)
 *   "ballstick" → atomisticRenderer.update({atoms, bonds:[]})
 */

import { getSectionCollapsed, setSectionCollapsed } from './section_collapse_state.js'
import {
  targetStreamMode,
  sceneUsesAtomistic,
  sceneUsesNativeCg,
  canReapplyFrame,
  decideReload,
  nextLivePollAction,
  restorePlan,
} from './md_display_state.js'

const _WS_URL  = `ws://${location.host}/ws/md-run`
const _BASE_FPS = 10   // target fps at 1× speed
const _MAX_LOG  = 200  // max output lines retained

// ── Colour palette (matches NADOC dark theme) ────────────────────────────────
const _C = {
  bg:     '#161b22', bg2:  '#0d1117',
  border: '#30363d', dim:  '#484f58',
  muted:  '#8b949e', text: '#c9d1d9',
  accent: '#58a6ff', ok:   '#3fb950',
  warn:   '#d29922', err:  '#f85149',
}

// ── Tiny helpers ─────────────────────────────────────────────────────────────
function _fmtSize(bytes) {
  if (bytes < 1024)       return bytes + ' B'
  if (bytes < 1048576)    return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1048576).toFixed(1) + ' MB'
}

function _basename(path) {
  return path ? path.replace(/\\/g, '/').split('/').pop() : ''
}

function _emitMdDisplayEvent(detail) {
  window.dispatchEvent(new CustomEvent('nadoc:md-display-state', { detail }))
}

function _activeSceneRepresentation() {
  const map = {
    'menu-view-hull-prism': 'hull-prism',
    'menu-view-detail-cylinders': 'cylinders',
    'menu-view-detail-beads': 'beads',
    'menu-view-detail-full': 'full',
    'menu-view-surface': 'surface',
    'menu-view-atomistic-vdw': 'vdw',
    'menu-view-atomistic-ballstick': 'ballstick',
  }
  for (const [id, repr] of Object.entries(map)) {
    if (document.getElementById(id)?.classList.contains('is-checked')) return repr
  }
  return 'full'
}

export function initMdPanel(store, { designRenderer, mdOverlay, atomisticRenderer, onRestoreDesignHeavy }) {
  // ── DOM refs ──────────────────────────────────────────────────────────────
  const panel          = document.getElementById('md-panel')
  const heading        = document.getElementById('md-panel-heading')
  const arrow          = document.getElementById('md-panel-arrow')
  const body           = document.getElementById('md-panel-body')

  const configNameEl   = document.getElementById('md-config-name')
  const configBrowseBtn = document.getElementById('md-config-browse')
  const loadBtn        = document.getElementById('md-load-btn')

  const outputHeading  = document.getElementById('md-output-heading')
  const outputArrow    = document.getElementById('md-output-arrow')
  const outputBody     = document.getElementById('md-output-body')
  const outputLog      = document.getElementById('md-output-log')

  const metricsBlock   = document.getElementById('md-metrics-block')
  const statFrames     = document.getElementById('md-stat-frames')
  const statNs         = document.getElementById('md-stat-ns')
  const statNsday      = document.getElementById('md-stat-nsday')
  const statTemp       = document.getElementById('md-stat-temp')
  const controls       = document.getElementById('md-controls')
  const scrubber       = document.getElementById('md-scrubber')
  const timeCur        = document.getElementById('md-time-cur')
  const timeTot        = document.getElementById('md-time-tot')
  const playBtn        = document.getElementById('md-play-btn')
  const loopBtn        = document.getElementById('md-loop-btn')
  const liveBtn        = document.getElementById('md-live-btn')
  const speedSel       = document.getElementById('md-speed')
  const strideInput    = document.getElementById('md-stride')
  const reprSel        = document.getElementById('md-repr')
  const opacitySlider  = document.getElementById('md-opacity')
  const opacityVal     = document.getElementById('md-opacity-val')
  const beadSizeRow    = document.getElementById('md-bead-size-row')
  const beadSizeSlider = document.getElementById('md-bead-size')
  const beadSizeVal    = document.getElementById('md-bead-size-val')
  const ampSlider      = document.getElementById('md-amp')
  const ampVal         = document.getElementById('md-amp-val')
  const showNadocChk   = document.getElementById('md-show-nadoc')
  const liveBarWrap    = document.getElementById('md-live-bar-wrap')
  const liveBar        = document.getElementById('md-live-bar')
  const liveCountdown  = document.getElementById('md-live-countdown')
  const statusLine     = document.getElementById('md-status-line')

  if (!panel) return

  // ── State ──────────────────────────────────────────────────────────────────
  let _configPath = null  // abs path to NAMD manifest/config
  let _browseDir = ''     // last directory visited in file browser

  let _ws        = null
  let _reopenTimer = null   // debounce handle: coalesce bursty _openWebSocket calls
  let _wsSig     = null     // config|mode of the last opened socket (skip redundant reopen)
  let _loadInFlight   = false  // true between sending 'load' and receiving 'ready'/'error'
  let _loadConfigPath = null   // config path of the in-flight load (for decideReload)
  let _nFrames   = 0
  let _curFrame  = 0
  let _dtPs      = null
  let _nstComp   = null
  let _totalNs   = null
  let _playing   = false
  let _loop      = false
  let _live      = false
  let _collapsed = getSectionCollapsed('dynamics', 'md-panel', true)
  let _outCollapsed = true

  // Apply persisted collapse state to DOM.
  body.style.display = _collapsed ? 'none' : ''
  if (arrow) arrow.classList.toggle('is-collapsed', _collapsed)
  let _playTimer = null
  let _liveTimer    = null
  let _liveRafId    = null    // requestAnimationFrame id for countdown bar
  let _livePollAt   = 0       // performance.now() when last get_latest was sent
  let _livePollSentAt = 0     // performance.now() of the outstanding get_latest (timeout tracking)
  const _LIVE_INTERVAL = 5000 // must match the setInterval below
  const _LIVE_POLL_TIMEOUT = 15000 // a get_latest is "stuck" after ~3 missed intervals
  let _repr      = 'nadoc'
  let _opacity   = 1.0
  let _beadSize  = 1.0
  let _stride    = 1
  let _speed     = 1.0
  let _amp       = 1.0   // displacement amplification factor (1 = no amp)
  let _showNadoc = true   // mirrors #md-show-nadoc checkbox
  let _latestOnReady = false
  let _latestOnceOnReady = false
  let _autoDisplayActive = false
  let _displayVisible = true
  let _lastFrameMsg = null
  let _sceneRepr = _activeSceneRepresentation()

  // ── Panel collapse ────────────────────────────────────────────────────────
  heading.addEventListener('click', () => {
    _collapsed = !_collapsed
    body.style.display = _collapsed ? 'none' : ''
    arrow.classList.toggle('is-collapsed', _collapsed)
    setSectionCollapsed('dynamics', 'md-panel', _collapsed)
  })

  // ── Output section collapse ───────────────────────────────────────────────
  outputHeading?.addEventListener('click', () => {
    _outCollapsed = !_outCollapsed
    if (outputBody)  outputBody.style.display  = _outCollapsed ? 'none' : ''
    if (outputArrow) outputArrow.textContent   = _outCollapsed ? '▶' : '▼'
  })

  // ── Output log ────────────────────────────────────────────────────────────
  function _log(msg, type = 'info') {
    if (!outputLog) return
    // Trim oldest entries to keep DOM lean.
    while (outputLog.childElementCount >= _MAX_LOG)
      outputLog.removeChild(outputLog.firstChild)

    const colors = { info: _C.muted, ok: _C.ok, warn: _C.warn, error: _C.err }
    const line = document.createElement('div')
    line.style.color = colors[type] ?? _C.muted
    const ts = new Date().toLocaleTimeString('en', { hour12: false })
    line.textContent = `[${ts}] ${msg}`
    outputLog.appendChild(line)
    outputLog.scrollTop = outputLog.scrollHeight
  }

  // ── File browser modal ────────────────────────────────────────────────────
  async function _openFileBrowser(extensions, title, onSelect) {
    // extensions: array like ['.gro', '.tpr'] or ['.xtc']
    let _dir    = _browseDir || ''
    let _closed = false

    const overlay = document.createElement('div')
    overlay.style.cssText = 'position:fixed;inset:0;z-index:400;background:rgba(0,0,0,0.75);display:flex;align-items:center;justify-content:center'

    const modal = document.createElement('div')
    modal.style.cssText = [
      `background:${_C.bg};border:1px solid ${_C.border};border-radius:8px`,
      'width:480px;max-height:65vh;display:flex;flex-direction:column',
      'font-family:var(--font-ui);font-size:11px;overflow:hidden',
    ].join(';')

    // Header
    const hdr = document.createElement('div')
    hdr.style.cssText = `display:flex;align-items:center;justify-content:space-between;padding:12px 14px 8px;border-bottom:1px solid ${_C.border}`
    const hdrTitle = document.createElement('span')
    hdrTitle.textContent = title
    hdrTitle.style.cssText = `color:${_C.text};font-size:12px;font-weight:500`
    const closeX = document.createElement('button')
    closeX.textContent = '×'
    closeX.style.cssText = `background:none;border:none;color:${_C.muted};font-size:18px;cursor:pointer;padding:0;line-height:1`
    closeX.addEventListener('click', _close)
    hdr.append(hdrTitle, closeX)

    // Path bar
    const pathBar = document.createElement('div')
    pathBar.style.cssText = [
      `padding:5px 14px;border-bottom:1px solid ${_C.border};`,
      `color:${_C.muted};font-size:var(--text-xs);white-space:nowrap;overflow:hidden;text-overflow:ellipsis`,
    ].join('')

    // Filter hint
    const filterHint = document.createElement('div')
    filterHint.style.cssText = `padding:2px 14px;font-size:var(--text-xs);color:${_C.dim};border-bottom:1px solid ${_C.border}`
    filterHint.textContent = `Showing: ${extensions.join(', ')} and folders`

    // File list
    const listEl = document.createElement('div')
    listEl.style.cssText = 'flex:1;overflow-y:auto;padding:3px 6px;min-height:80px'

    // Footer
    const footer = document.createElement('div')
    footer.style.cssText = `padding:8px 14px;border-top:1px solid ${_C.border};display:flex;justify-content:flex-end`
    const cancelBtn = document.createElement('button')
    cancelBtn.textContent = 'Cancel'
    cancelBtn.style.cssText = [
      `font-size:var(--text-xs);padding:3px 12px;background:${_C.bg};`,
      `border:1px solid ${_C.border};color:${_C.text};border-radius:3px;cursor:pointer`,
    ].join('')
    cancelBtn.addEventListener('click', _close)
    footer.appendChild(cancelBtn)

    modal.append(hdr, pathBar, filterHint, listEl, footer)
    overlay.appendChild(modal)
    overlay.addEventListener('click', e => { if (e.target === overlay) _close() })

    function _close() {
      if (_closed) return
      _closed = true
      document.body.removeChild(overlay)
    }

    async function _navigate(dir) {
      listEl.textContent = ''
      const loading = document.createElement('div')
      loading.style.cssText = `color:${_C.dim};padding:10px 8px`
      loading.textContent = 'Loading…'
      listEl.appendChild(loading)

      const extParam = extensions.join(',')
      try {
        const resp = await fetch(`/api/md/browse?dir=${encodeURIComponent(dir)}&ext=${encodeURIComponent(extParam)}`)
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
        const data = await resp.json()
        _dir = data.path
        _browseDir = _dir
        pathBar.textContent = _dir
        pathBar.title = _dir
        _renderEntries(data.entries)
      } catch (e) {
        listEl.textContent = ''
        const err = document.createElement('div')
        err.style.cssText = `color:${_C.err};padding:8px`
        err.textContent = 'Error: ' + e.message
        listEl.appendChild(err)
      }
    }

    function _renderEntries(entries) {
      listEl.textContent = ''
      if (!entries.length) {
        const empty = document.createElement('div')
        empty.style.cssText = `color:${_C.dim};padding:10px 8px;font-size:var(--text-xs)`
        empty.textContent = 'Empty directory'
        listEl.appendChild(empty)
        return
      }
      for (const entry of entries) {
        const row = document.createElement('div')
        row.style.cssText = [
          'display:flex;align-items:center;gap:7px;padding:5px 6px;border-radius:3px;cursor:pointer',
        ].join('')
        row.addEventListener('mouseenter', () => { row.style.background = _C.bg })
        row.addEventListener('mouseleave', () => { row.style.background = '' })

        const icon = document.createElement('span')
        icon.textContent = entry.type === 'dir' ? '📁' : '📄'
        icon.style.cssText = 'font-size:11px;flex-shrink:0;opacity:0.8'

        const name = document.createElement('span')
        name.textContent = entry.name
        name.title = entry.path
        name.style.cssText = [
          'flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap',
          `color:${entry.type === 'dir' ? _C.text : _C.accent}`,
        ].join(';')

        row.append(icon, name)

        if (entry.type === 'file' && entry.size != null) {
          const size = document.createElement('span')
          size.style.cssText = `color:${_C.dim};font-size:var(--text-xs);flex-shrink:0`
          size.textContent = _fmtSize(entry.size)
          row.appendChild(size)
        }

        if (entry.type === 'dir') {
          row.addEventListener('click', () => _navigate(entry.path))
        } else {
          row.addEventListener('click', () => {
            if (_closed) return
            _close()
            onSelect(entry.path, entry.name)
          })
        }
        listEl.appendChild(row)
      }
    }

    document.body.appendChild(overlay)
    await _navigate(_dir)
  }

  // ── localStorage persistence ──────────────────────────────────────────────
  const _LS_KEY = 'nadoc_md_paths'

  function _persistPaths() {
    try {
      localStorage.setItem(_LS_KEY, JSON.stringify({
        configPath: _configPath,
      }))
    } catch (_) {}
  }

  function _loadPersistedPaths() {
    try {
      const raw = localStorage.getItem(_LS_KEY)
      if (!raw) return
      const { configPath, topoPath } = JSON.parse(raw)
      const path = configPath || topoPath
      if (path) _setConfigPath(path, _basename(path))
    } catch (_) {}
  }

  // ── File picker wiring ────────────────────────────────────────────────────
  function _setConfigPath(path, name) {
    _configPath = path
    if (configNameEl) {
      configNameEl.textContent = name || _basename(path)
      configNameEl.title = path
      configNameEl.style.color = _C.text
    }
    _browseDir = path.replace(/[^/\\]+$/, '')
    _updateLoadBtn()
    _persistPaths()
  }

  function _updateLoadBtn() {
    const ready = !!_configPath
    if (!loadBtn) return
    loadBtn.disabled = !ready
    loadBtn.style.color  = ready ? _C.text  : _C.dim
    loadBtn.style.cursor = ready ? 'pointer' : 'not-allowed'
  }

  configBrowseBtn?.addEventListener('click', () => {
    if (_configPath) _browseDir = _configPath.replace(/[^/\\]+$/, '')
    _openFileBrowser(['.json', '.namd', '.conf'], 'Select MD Config / Manifest', _setConfigPath)
  })

  // ── Load ──────────────────────────────────────────────────────────────────
  loadBtn?.addEventListener('click', () => {
    if (!_configPath) return
    _displayVisible = true
    _autoDisplayActive = false
    _log(`Loading config: ${_basename(_configPath)}`, 'info')
    _openWebSocket()
  })

  // Debounced entry point.  Each open tears down any in-flight socket and fires a
  // fresh server-side `load`, which rebuilds the (large) atomistic model.  Bursts
  // of re-opens (rapid representation toggles, event-driven refreshes) used to
  // stack N concurrent server builds — coalesce them into a single open so only
  // the latest survives.  The backend cache (atomistic_cache.py) is the real
  // safety net; this just stops us asking for redundant work.
  function _openWebSocket() {
    if (_reopenTimer) clearTimeout(_reopenTimer)
    _reopenTimer = setTimeout(() => { _reopenTimer = null; _openWebSocketNow() }, 120)
  }

  function _openWebSocketNow() {
    // Skip a redundant reopen: same config + mode and the socket is already
    // connecting/open — the existing load already covers this request.
    const sig = `${_configPath}|${_repr}`
    if (_wsSig === sig && _ws &&
        (_ws.readyState === WebSocket.CONNECTING || _ws.readyState === WebSocket.OPEN)) {
      return
    }
    _wsSig = sig
    if (_ws) {
      _ws.onclose = null
      _ws.close()
      _ws = null
    }
    _setPlaying(false)
    _setLive(false)
    if (statusLine) statusLine.textContent = 'Connecting…'

    try {
      _ws = new WebSocket(_WS_URL)
    } catch (e) {
      _log('WebSocket failed: ' + e.message, 'error')
      return
    }

    _ws.onopen = () => {
      _emitMdDisplayEvent({ state: 'loading', message: 'Loading MD trajectory...' })
      _loadInFlight   = true
      _loadConfigPath = _configPath
      _ws.send(JSON.stringify({
        action:          'load',
        config_path:     _configPath,
        mode:            _repr,
        design:          store?.getState?.().currentDesign ?? null,
      }))
      if (statusLine) statusLine.textContent = 'Loading…'
    }

    _ws.onmessage = ev => {
      let msg
      try { msg = JSON.parse(ev.data) } catch { return }
      _handleMessage(msg)
    }

    _ws.onerror = () => _log('WebSocket error.', 'error')
    _ws.onclose = () => {
      _loadInFlight = false
      _setPlaying(false)
      _setLive(false)
      _restoreDesign()
    }
  }

  // ── NADOC model visibility ────────────────────────────────────────────────
  function _setShowNadoc(v) {
    _showNadoc = v
    if (showNadocChk) showNadocChk.checked = v
    designRenderer?.setDesignVisible(v)
  }

  // Stop an MD display and revert to the design's equilibrium pose — WITHOUT ever
  // changing the user's chosen representation.  A CG scene drops back to the native
  // bead-and-slab design; an atomistic/surface scene keeps that heavy representation,
  // rebuilt from the design (onRestoreDesignHeavy) so it persists across toggling
  // Display MD / flexibility map / trajectory (mirrors the mdViz flex/traj stop path).
  function _restoreDesign() {
    _stopLiveBar()
    mdOverlay?.dispose?.()
    designRenderer?.applyFemPositions(null)   // always drop MD-displaced CG positions
    const { showNativeCg, rebuildHeavy } = restorePlan(_sceneRepr)
    if (showNativeCg) {
      atomisticRenderer?.setMode?.('off')
      _setShowNadoc(true)
    } else {
      _setShowNadoc(false)               // hide the CG design under the heavy rep
      if (rebuildHeavy) onRestoreDesignHeavy?.()
    }
  }

  showNadocChk?.addEventListener('change', () => {
    _setShowNadoc(showNadocChk.checked)
  })

  // ── Message handler ───────────────────────────────────────────────────────
  function _handleMessage(msg) {
    if (msg.type === 'log') {
      _log(msg.message, 'info')
      return
    }

    if (msg.type === 'ready') {
      _loadInFlight = false
      _nFrames = msg.n_frames
      _dtPs    = msg.dt_ps
      _nstComp = msg.nstxout_comp
      _totalNs = msg.total_ns

      if (scrubber) {
        scrubber.min   = 0
        scrubber.max   = Math.max(0, _nFrames - 1)
        scrubber.value = 0
      }

      const fps  = msg.ns_per_day   != null ? msg.ns_per_day.toFixed(2) + ' ns/day' : '—'
      const temp = msg.temperature_k != null ? msg.temperature_k.toFixed(1) + ' K'   : '—'
      const ns   = _totalNs          != null ? _totalNs.toFixed(3) + ' ns'           : '—'
      if (statFrames) statFrames.textContent = `Frames: ${_nFrames}  ·  P-atoms: ${msg.n_p_atoms}`
      if (statNs)     statNs.textContent     = `Total: ${ns}`
      if (statNsday)  statNsday.textContent  = `Speed: ${fps}`
      if (statTemp)   statTemp.textContent   = `Temperature: ${temp}`
      if (metricsBlock) metricsBlock.style.display = ''
      if (controls)     controls.style.display     = ''
      if (timeTot) timeTot.textContent = _totalNs != null ? _totalNs.toFixed(3) + ' ns' : (_nFrames - 1) + ' fr'
      if (statusLine) statusLine.textContent = `Ready — ${_nFrames} frames`

      _log(`Ready: ${_nFrames} frames, ${ns}, ${temp}`, 'ok')
      if (msg.trajectory_path) _log(`Trajectory: ${_basename(msg.trajectory_path)}`, 'info')
      _emitMdDisplayEvent({
        state: 'ready',
        message: `Loaded ${_nFrames} MD frames`,
        nFrames: _nFrames,
        totalNs: _totalNs,
      })
      if (msg.warnings && msg.warnings.length > 0) {
        for (const w of msg.warnings) _log(`Warning: ${w}`, 'warn')
      }
      if (_latestOnReady) {
        _latestOnReady = false
        if (_latestOnceOnReady) {
          _latestOnceOnReady = false
          _sendPoll()
        } else {
          _setLive(true)
        }
      } else {
        _seekFrame(0)
      }
    }

    if (msg.type === 'frame') {
      // Live polling (dcd_fast) discovers frames appended after load — grow the
      // scrubber range so the user can scrub into them (the backend lazily reloads
      // the Universe when a seek lands beyond its original length).
      if (msg.n_frames && msg.n_frames > _nFrames) {
        _nFrames = msg.n_frames
        if (scrubber) scrubber.max = Math.max(0, _nFrames - 1)
        if (statusLine && !_live) statusLine.textContent = `Ready — ${_nFrames} frames`
      }
      _updateTimeline(msg.frame_idx)
      _lastFrameMsg = msg
      if (_displayVisible) {
        _applyFrame(msg)
        _emitMdDisplayEvent({
          state: 'frame',
          message: `Displaying frame ${msg.frame_idx + 1}/${msg.n_frames ?? _nFrames}`,
          frameIdx: msg.frame_idx,
          nFrames: msg.n_frames ?? _nFrames,
          nPositions: msg.positions?.length ?? msg.atoms?.length ?? 0,
        })
      }
      if (_live) {
        // Frame landed: clear the "fetching" state and restart the countdown.
        _livePendingPoll = false
        _livePollAt      = performance.now()
      }
    }

    if (msg.type === 'error') {
      _loadInFlight = false
      _log('Error: ' + msg.message, 'error')
      if (statusLine) statusLine.textContent = 'Error — see Output'
      _emitMdDisplayEvent({ state: 'error', message: msg.message })
    }
  }

  // ── Apply frame to scene ──────────────────────────────────────────────────
  function _applyFrame(msg) {
    console.log(`[MD] _applyFrame frame=${msg.frame_idx} pos=${msg.positions?.length ?? 0} repr=${_repr} amp=${_amp} live=${_live}`)
    if (_repr === 'nadoc') {
      if (!msg.positions) return
      designRenderer?.applyFemPositions(
        msg.positions.map(p => ({
          helix_id:          p.helix_id,
          bp_index:          p.bp_index,
          direction:         p.direction,
          backbone_position: [p.x, p.y, p.z],
          nx: p.nx, ny: p.ny, nz: p.nz,
        })),
        _amp
      )
    } else if (_repr === 'beads') {
      if (!msg.positions) return
      mdOverlay?.update(msg.positions, _beadSize * 0.15, _opacity)
    } else if (_repr === 'ballstick') {
      if (!msg.atoms) return
      atomisticRenderer?.setMode(_sceneRepr === 'vdw' ? 'vdw' : 'ballstick')
      atomisticRenderer?.update({ atoms: msg.atoms, bonds: msg.bonds ?? [] })
    }
  }

  // ── Timeline ──────────────────────────────────────────────────────────────
  function _frameTons(idx) {
    if (_dtPs == null || _nstComp == null) return null
    return idx * _nstComp * _dtPs / 1000
  }

  function _updateTimeline(idx) {
    _curFrame = idx
    if (scrubber) scrubber.value = idx
    const ns = _frameTons(idx)
    if (timeCur) timeCur.textContent = ns != null ? ns.toFixed(3) + ' ns' : idx + ' fr'
  }

  function _seekFrame(idx) {
    if (!_ws || _ws.readyState !== WebSocket.OPEN) return
    _ws.send(JSON.stringify({ action: 'seek', frame_idx: idx }))
  }

  scrubber?.addEventListener('input', () => {
    _setPlaying(false)
    _seekFrame(parseInt(scrubber.value))
  })

  // ── Playback ──────────────────────────────────────────────────────────────
  function _tick() {
    if (!_playing || _live) return
    let next = _curFrame + _stride
    if (next >= _nFrames) {
      if (_loop) { next = 0 } else { _setPlaying(false); return }
    }
    _seekFrame(next)
  }

  function _setPlaying(v) {
    _playing = v
    clearInterval(_playTimer)
    if (_playing && !_live) {
      const fps = Math.max(1, _BASE_FPS * _speed)
      _playTimer = setInterval(_tick, 1000 / fps)
    }
    if (playBtn) playBtn.innerHTML = _playing ? '&#9646;&#9646; Pause' : '&#9654; Play'
  }

  playBtn?.addEventListener('click', () => { if (!_live) _setPlaying(!_playing) })

  function _setLoop(v) {
    _loop = v
    if (loopBtn) loopBtn.style.color = _loop ? _C.accent : _C.muted
  }
  loopBtn?.addEventListener('click', () => _setLoop(!_loop))

  // _livePendingPoll: true while we've sent get_latest and haven't received a frame yet.
  // The bar shows a "fetching" pulse in this state so the user can distinguish
  // "waiting for data" from "counting down to next poll".
  let _livePendingPoll = false

  function _sendPoll() {
    if (_ws?.readyState === WebSocket.OPEN) {
      _ws.send(JSON.stringify({ action: 'get_latest' }))
      _livePendingPoll = true   // enter waiting state; bar switches to pulse
      _livePollSentAt  = performance.now()
    }
  }

  // Per-interval pacing for live polling: never stack get_latest on top of an
  // outstanding one (a slow GROMACS load_new poll would back up), and if a poll
  // never returns, surface it and re-poll instead of pulsing "Fetching…" forever.
  function _livePollTick() {
    if (!_live) return
    const action = nextLivePollAction({
      pending:  _livePendingPoll,
      waitedMs: performance.now() - _livePollSentAt,
      timeoutMs: _LIVE_POLL_TIMEOUT,
    })
    if (action === 'send') {
      _sendPoll()
    } else if (action === 'timeout') {
      _log('Live poll timed out — no frame returned; retrying.', 'warn')
      if (statusLine) statusLine.textContent = 'Live poll stalled — retrying…'
      _livePendingPoll = false   // clear the stuck state so the bar leaves "Fetching…"
      _sendPoll()
    }
    // 'skip' → an outstanding poll is still within the timeout; wait.
  }

  function _tickLiveBar() {
    if (!_live) return
    if (_livePendingPoll) {
      // Pulse the bar while waiting for the frame to arrive.
      const pulse = 0.5 + 0.5 * Math.sin(performance.now() / 250)
      if (liveBar)       liveBar.style.width       = `${pulse * 100}%`
      if (liveCountdown) liveCountdown.textContent = 'Fetching…'
    } else {
      // Count down from LIVE_INTERVAL to 0 since the last frame landed.
      const elapsed   = performance.now() - _livePollAt
      const frac      = Math.min(1, elapsed / _LIVE_INTERVAL)
      const remaining = Math.max(0, (_LIVE_INTERVAL - elapsed) / 1000)
      if (liveBar)       liveBar.style.width       = `${(1 - frac) * 100}%`
      if (liveCountdown) liveCountdown.textContent = remaining.toFixed(1) + ' s'
    }
    _liveRafId = requestAnimationFrame(_tickLiveBar)
  }

  function _startLiveBar() {
    cancelAnimationFrame(_liveRafId)
    if (liveBarWrap) liveBarWrap.style.display = ''
    _livePollAt      = performance.now()
    _livePendingPoll = false
    _tickLiveBar()
  }

  function _stopLiveBar() {
    cancelAnimationFrame(_liveRafId)
    _liveRafId       = null
    _livePendingPoll = false
    if (liveBarWrap)   liveBarWrap.style.display   = 'none'
    if (liveBar)       liveBar.style.width          = '100%'
    if (liveCountdown) liveCountdown.textContent    = _LIVE_INTERVAL / 1000 + '.0 s'
  }

  function _setLive(v) {
    _live = v
    clearInterval(_liveTimer)
    if (_live) {
      _setPlaying(false)
      _startLiveBar()
      _sendPoll()          // immediately request the latest frame
      _liveTimer = setInterval(_livePollTick, _LIVE_INTERVAL)
    } else {
      _stopLiveBar()
    }
    if (liveBtn)  liveBtn.style.color  = _live ? _C.accent : _C.muted
    if (scrubber) scrubber.disabled    = _live
    if (playBtn)  playBtn.disabled     = _live
  }
  liveBtn?.addEventListener('click', () => _setLive(!_live))

  // Thin closures over the live _sceneRepr around the shared pure helpers
  // (md_display_state.js) so the decision logic is unit-tested in one place.
  function _sceneUsesNativeCg() { return sceneUsesNativeCg(_sceneRepr) }
  function _sceneUsesAtomistic() { return sceneUsesAtomistic(_sceneRepr) }
  function _targetStreamMode() { return targetStreamMode(_sceneRepr) }

  function _reapplyCachedFrame() {
    if (!_autoDisplayActive || !_lastFrameMsg) return
    if (!canReapplyFrame(_repr, _sceneRepr)) return
    if (_sceneUsesNativeCg()) designRenderer?.setDesignVisible(true)
    _applyFrame(_lastFrameMsg)
  }

  window.addEventListener('nadoc:representation-change', evt => {
    _sceneRepr = evt.detail?.representation ?? _activeSceneRepresentation()
    if (!_autoDisplayActive) return
    const nextMode = _targetStreamMode()
    const modeChanged = _repr !== nextMode
    _repr = nextMode
    if (_sceneUsesNativeCg() || _sceneUsesAtomistic()) {
      requestAnimationFrame(() => {
        if (modeChanged && _configPath) {
          _lastFrameMsg = null
          _latestOnReady = true
          _openWebSocket()
          return
        }
        _reapplyCachedFrame()
        if (_ws?.readyState === WebSocket.OPEN) _sendPoll()
      })
    }
  })

  // ── Speed / stride / repr / sliders ──────────────────────────────────────
  speedSel?.addEventListener('change', () => {
    _speed = parseFloat(speedSel.value) || 1
    if (_playing) { _setPlaying(false); _setPlaying(true) }
  })

  strideInput?.addEventListener('change', () => {
    _stride = Math.max(1, parseInt(strideInput.value) || 1)
  })

  reprSel?.addEventListener('change', () => {
    _repr = reprSel.value
    if (beadSizeRow) beadSizeRow.style.display = _repr === 'beads' ? '' : 'none'
    if (_repr !== 'beads')     mdOverlay?.dispose()
    if (_repr !== 'ballstick') atomisticRenderer?.setMode('off')
    // Revert MD-displaced positions when leaving nadoc mode.
    if (_repr !== 'nadoc')     designRenderer?.applyFemPositions(null)
    // Re-apply user's show/hide preference for the NADOC model.
    designRenderer?.setDesignVisible(_showNadoc)
    if (_configPath) _openWebSocket()
  })

  opacitySlider?.addEventListener('input', () => {
    _opacity = parseFloat(opacitySlider.value)
    if (opacityVal) opacityVal.textContent = _opacity.toFixed(2)
    mdOverlay?.setOpacity(_opacity)
  })

  beadSizeSlider?.addEventListener('input', () => {
    _beadSize = parseFloat(beadSizeSlider.value)
    if (beadSizeVal) beadSizeVal.textContent = _beadSize.toFixed(1) + '×'
  })

  ampSlider?.addEventListener('input', () => {
    _amp = parseFloat(ampSlider.value)
    if (ampVal) ampVal.textContent = _amp.toFixed(0) + '×'
  })

  // Restore paths from previous session.
  _loadPersistedPaths()

  return {
    displayLatest(configPath, { forceReload = false, live = true } = {}) {
      if (!configPath) return
      const nextMode = _targetStreamMode()
      const action = decideReload({
        wsState: _ws?.readyState ?? null,
        loadInFlight: _loadInFlight,
        loadConfigPath: _loadConfigPath,
        currentConfig: _configPath,
        requestedConfig: configPath,
        modeChanged: _repr !== nextMode,
        forceReload,
      })
      _autoDisplayActive = true
      _displayVisible = true
      _repr = nextMode
      _latestOnReady = true
      _latestOnceOnReady = !live
      if (beadSizeRow) beadSizeRow.style.display = 'none'
      if (_sceneUsesNativeCg()) {
        mdOverlay?.dispose?.()
        atomisticRenderer?.setMode?.('off')
        _setShowNadoc(true)
      } else if (_sceneUsesAtomistic()) {
        mdOverlay?.dispose?.()
        designRenderer?.applyFemPositions(null)
        designRenderer?.setDesignVisible(false)
        atomisticRenderer?.setMode?.(_sceneRepr)
      }
      _setConfigPath(configPath, _basename(configPath))
      // A load for this exact target is already in flight — let the pending
      // 'ready' apply the (now updated) latest/live flags; do NOT tear down the
      // mid-handshake socket (that caused NS_BINDING_ABORTED).
      if (action === 'wait-in-flight') return
      if (action === 'reuse-open') {
        _setLive(live)
        if (_lastFrameMsg) _reapplyCachedFrame()
        else _sendPoll()
        return
      }
      _openWebSocket()
    },

    prewarmLatest(configPath, { forceReload = false } = {}) {
      if (!configPath) return
      const nextMode = _targetStreamMode()
      const action = decideReload({
        wsState: _ws?.readyState ?? null,
        loadInFlight: _loadInFlight,
        loadConfigPath: _loadConfigPath,
        currentConfig: _configPath,
        requestedConfig: configPath,
        modeChanged: _repr !== nextMode,
        forceReload,
      })
      _displayVisible = false
      _autoDisplayActive = false
      _repr = nextMode
      _latestOnReady = true
      _latestOnceOnReady = true
      _setConfigPath(configPath, _basename(configPath))
      if (action === 'wait-in-flight') return
      if (action === 'reuse-open') {
        // Socket already warm — no load event will fire, so signal readiness
        // explicitly for the toggle's indicator dot.
        _emitMdDisplayEvent({ state: 'ready', message: 'MD display warm' })
        _setLive(false)
        _sendPoll()
        return
      }
      _openWebSocket()
    },

    requestLatest() {
      if (_ws?.readyState === WebSocket.OPEN) _sendPoll()
    },

    stopPrewarm() {
      if (_displayVisible || _autoDisplayActive) return
      _latestOnReady = false
      _latestOnceOnReady = false
      _setLive(false)
      if (_reopenTimer) { clearTimeout(_reopenTimer); _reopenTimer = null }
      _wsSig = null
      if (_ws) {
        try {
          _ws.onclose = null
          _ws.close()
        } catch { /* ok */ }
        _ws = null
      }
    },

    stopAndRestore() {
      _lastFrameMsg = null
      _latestOnReady = false
      _latestOnceOnReady = false
      _setPlaying(false)
      _setLive(false)
      _displayVisible = true
      if (_reopenTimer) { clearTimeout(_reopenTimer); _reopenTimer = null }
      _wsSig = null
      if (_ws) {
        try {
          _ws.onclose = null
          _ws.close()
        } catch { /* ok */ }
        _ws = null
      }
      _restoreDesign()
      _autoDisplayActive = false
    },

    // Toggle-off variant of stopAndRestore: revert the scene to native positions but
    // KEEP the display socket + cached frame warm.  Switching back to prewarm then
    // shows 'ready' instantly (no 143 MB PSF re-parse) and re-toggling re-applies the
    // cached frame with no reload.  Returns true when a warm socket was retained.
    stopDisplayKeepWarm() {
      _setPlaying(false)
      _setLive(false)
      _displayVisible = false
      _autoDisplayActive = false
      _latestOnReady = false
      _latestOnceOnReady = false
      _restoreDesign()   // reverts positions; does not touch _ws / _lastFrameMsg
      return !!(_ws && (_ws.readyState === WebSocket.OPEN ||
                        _ws.readyState === WebSocket.CONNECTING))
    },
  }
}
