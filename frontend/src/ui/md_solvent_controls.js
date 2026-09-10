/**
 * md_solvent_controls.js — the Visualizations card's Water / Ions / Periodic box
 * toggles, and the fetch+cache that feeds them.
 * Water is available only in live Display MD; trajectory playback loads ions/cell.
 *
 * Lives outside md_jobs_panel.js (already ~3.7k lines) because this is a cohesive
 * subsystem with its own state, its own DOM and its own network traffic. The panel
 * gains only an import, one factory init, and thin per-action wiring.
 *
 * Three things worth knowing before changing anything here:
 *
 * 1. **Water is bounded; ions never are.** A solvated origami is 70 k–880 k water
 *    molecules — at bulk density that is an opaque brick that hides the structure,
 *    quite apart from being unaffordable. The hydration shell is the useful view and
 *    the default. Ions top out around 15 k and are always drawn in full.
 *
 * 2. **Trajectory companions are prepared for the whole loaded trajectory.**
 *    Frames snap to their matching DNA frame; Play joins preparation and seeks
 *    wait for missing coordinates. Job, interval, and toggle changes invalidate
 *    the cache. Drawing-style changes reuse the same ion coordinates.
 *
 * 3. **Whole-box atomistic is the case that kills the tab.** ~32 MB/frame on a large
 *    job against a 1536 MB hard heap ceiling that terminates rather than degrades.
 *    `solventFetchPlan` prices it against the SAME budget the DNA prebuild uses, and
 *    the server-side `max_waters` cap is what actually enforces it.
 */

import { parseSolventBin } from '../scene/md_solvent_bin.js'
import { solventRepMode } from './md_display_state.js'
import { BROWSER_HEAP_CEILING_BYTES, FREE_RAM_SAFE_FRACTION } from './oxdna_display.js'
import { formatBytes } from './format_bytes.js'
import { ION_STYLE } from '../scene/md_solvent_overlay.js'

const LS = {
  water: 'nadoc:md-jobs-solvent-water',
  ions: 'nadoc:md-jobs-solvent-ions',
  box: 'nadoc:md-jobs-solvent-box',
  scope: 'nadoc:md-jobs-solvent-water-scope',
  shell: 'nadoc:md-jobs-solvent-shell',
}

/** Default window for the live-water memory estimate. Trajectory preparation uses
 * measured complete-frame bytes and batches up to 128 MiB instead. */
export const SOLVENT_CHUNK = 32

/** Bytes per molecule on the wire. */
const BYTES_PER_WATER = { sphere: 12, atomistic: 36 }

/** Wire species codes, in the order `ION_STYLE` is indexed by. Mirrors `SPECIES` in
 *  backend/core/md_solvent.py — a payload carries its own `speciesTable`, so this is
 *  only the fallback for one that doesn't. */
export const ION_SPECIES = ['NA', 'CL', 'MG', 'K', 'CA']

/**
 * Census of a solvent payload's ions, keyed by species name.
 *
 * The frame IS the census. Ions ride every payload in full — never bounded by the
 * hydration shell and never subject to the water cap (`extract_solvent_frame`, "Ions
 * (never bounded)") — so tallying the species codes gives the exact ion content of the
 * job's topology rather than an estimate of it.
 */
export function tallyIonSpecies(codes, speciesTable = null) {
  const table = speciesTable?.length ? speciesTable : ION_SPECIES
  const out = {}
  for (const k of table) out[k] = 0
  for (const c of codes || []) {
    const k = table[c]
    if (k !== undefined) out[k] += 1
  }
  return out
}

/**
 * Rough share of the cell's water that lands inside a shell of `shellAng`.
 *
 * ONLY used to price a fetch before one has been made — the moment a frame arrives
 * the real count replaces it. Calibrated against a measured 10hb run (4 Å → 17 %,
 * 5 Å → 30 %, 8 Å → 47 % of 69 688 molecules); it is a surface-to-volume quantity,
 * so it is optimistic for a large compact structure and pessimistic for a thin one.
 */
export function estimateShellFraction(shellAng) {
  const a = Math.max(0, Number(shellAng) || 0)
  return Math.max(0, Math.min(1, 0.06 * a))
}

/**
 * Fraction of the machine's memory allowance solvent may claim.
 *
 * The DNA all-atom prebuild is sizing itself against the SAME ceiling at the same
 * time; if each helped itself to the whole thing they would jointly overshoot it,
 * and `BROWSER_HEAP_CEILING_BYTES` is a hard tab kill rather than a slowdown. Half
 * each is the simple split — the DNA is the thing being studied, so it should never
 * be squeezed out by its solvent.
 */
export const SOLVENT_BUDGET_SHARE = 0.5

/**
 * Pure: what a solvent fetch would cost, and whether it has to be capped.
 *
 * `scope` is 'shell' | 'all' — NOT 'box'; `box` here is the periodic-cell toggle.
 * `availableBytes` is the host's MemAvailable (null = unknown, in which case only
 * the heap ceiling applies — an unknown machine is never assumed to be a large one).
 * The budget covers the whole cached WINDOW (`chunk` frames), not a single frame,
 * because that is what is actually resident while scrubbing.
 *
 * @returns {{needed:boolean, atomistic:boolean, nWaterEst:number, bytesPerFrame:number,
 *            maxWaters:number|null, capped:boolean, budgetBytes:number,
 *            limitedBy:'ram'|'heap'|null}}
 */
export function solventFetchPlan({
  repMode = 'off', water = false, ions = false, box = false,
  scope = 'shell', shellAng = 5, nWatersTotal = 0, nIons = 0,
  nFrames = 1, availableBytes = null, chunk = SOLVENT_CHUNK,
  share = SOLVENT_BUDGET_SHARE,
} = {}) {
  const needed = repMode !== 'off' && (water || ions || box)
  const atomistic = repMode === 'atomistic'
  const perMol = BYTES_PER_WATER[atomistic ? 'atomistic' : 'sphere']

  const nWaterEst = !water ? 0
    : (scope === 'all' ? nWatersTotal
                       : Math.round(nWatersTotal * estimateShellFraction(shellAng)))
  const fixedPerFrame = (ions ? nIons * 12 : 0) + (box ? 96 : 0)

  // Which ceiling binds — computed here rather than read off prebuildMemoryPlan,
  // whose `limitedBy` is null unless ITS OWN frame count was capped.
  const avail = Number(availableBytes)
  const ramLimit = Number.isFinite(avail) && avail > 0
    ? avail * FREE_RAM_SAFE_FRACTION : Infinity
  const limitedBy = ramLimit < BROWSER_HEAP_CEILING_BYTES ? 'ram' : 'heap'
  const budgetBytes = Math.min(BROWSER_HEAP_CEILING_BYTES, ramLimit) * share

  const window = Math.max(1, Math.min(chunk, nFrames || 1))
  const affordableWaters = Math.max(
    0, Math.floor((budgetBytes / window - fixedPerFrame) / perMol))

  const capped = water && nWaterEst > affordableWaters
  const maxWaters = capped ? Math.max(1, affordableWaters) : null
  const nWater = capped ? maxWaters : nWaterEst

  return {
    needed, atomistic, nWaterEst,
    bytesPerFrame: nWater * perMol + fixedPerFrame,
    maxWaters, capped, budgetBytes,
    limitedBy: capped ? limitedBy : null,
  }
}

const _LIMIT_WHY = { ram: 'free RAM', heap: 'browser memory limit', budget: 'memory budget' }

export function initMdSolventControls({
  api, getSolventOverlay = null, getBoxOverlay = null, simulationGraphene = false,
  getCurrentRepr = null, getAvailableBytes = () => null,
  // The live "Display MD" stream. Its frames arrive over the job WebSocket rather
  // than the REST route, so solvent for that view is requested with `setSolvent`
  // and pushed back through `liveBlob` — no fetching or caching on this side.
  getLiveDisplay = null,
} = {}) {
  const waterToggle = document.getElementById('md-jobs-water-toggle')
  const ionsToggle = document.getElementById('md-jobs-ions-toggle')
  const boxToggle = document.getElementById('md-jobs-box-toggle')
  const waterOpts = document.getElementById('md-jobs-water-opts')
  const scopeShell = document.getElementById('md-jobs-water-scope-shell')
  const scopeBox = document.getElementById('md-jobs-water-scope-box')
  const shellInput = document.getElementById('md-jobs-water-shell')
  const countEl = document.getElementById('md-jobs-water-count')
  const legendEl = document.getElementById('md-jobs-ions-legend')
  const statusEl = document.getElementById('md-jobs-solvent-status')
  const root = document.getElementById('md-jobs-solvent-opts')
  if (!root) return null

  let _jobId = null
  let _stride = null
  let _nFrames = 0
  let _meta = null              // /solvent-meta for _jobId
  let _measuredSpecies = null   // real ion census, once a frame has landed
  let _cache = new Map()        // frame index → parsed frame
  let _frameIdx = 0
  let _inflight = null
  let _generation = 0
  let _preparation = null
  let _frameBytes = 0
  let _enabled = false
  let _measuredWater = null     // real molecule count, once a frame has landed
  let _live = false             // driven by the WS stream rather than the REST route
  let _keyframeOptions = false  // authored companions may exist without a DNA rep

  // ── settings ──────────────────────────────────────────────────────────────
  const _read = (k, d) => { try { return localStorage.getItem(k) ?? d } catch { return d } }
  const _write = (k, v) => { try { localStorage.setItem(k, v) } catch { /* private mode */ } }

  function _restore() {
    if (waterToggle) waterToggle.checked = _read(LS.water, '') === 'true'
    if (ionsToggle) ionsToggle.checked = _read(LS.ions, '') === 'true'
    if (boxToggle) boxToggle.checked = _read(LS.box, '') === 'true'
    const scope = _read(LS.scope, 'shell')
    if (scopeBox && scope === 'all') scopeBox.checked = true
    else if (scopeShell) scopeShell.checked = true
    const shell = parseFloat(_read(LS.shell, ''))
    if (shellInput && Number.isFinite(shell) && shell > 0) shellInput.value = String(shell)
  }

  function _persist() {
    if (_live) _write(LS.water, String(!!waterToggle?.checked))
    _write(LS.ions, String(!!ionsToggle?.checked))
    _write(LS.box, String(!!boxToggle?.checked))
    _write(LS.scope, _scope())
    _write(LS.shell, String(_shellAng()))
  }

  // 'all' rather than 'box': the periodic-CELL toggle is already called `box`, and
  // the two meanings collide badly in solventFetchPlan's argument list.
  const _scope = () => (scopeBox?.checked ? 'all' : 'shell')
  function _shellAng() {
    const v = parseFloat(shellInput?.value ?? '')
    return Number.isFinite(v) && v > 0 ? Math.min(30, v) : 5
  }
  const _repMode = () => {
    const normal = solventRepMode(getCurrentRepr?.())
    return (_keyframeOptions || simulationGraphene) && normal === 'off' ? 'sphere' : normal
  }
  // Graphene rides the cell channel even when the optional box outline is hidden.
  const _waterOn = () => _live && !!waterToggle?.checked
  const _anyOn = () => !!(simulationGraphene || _waterOn() || ionsToggle?.checked || boxToggle?.checked)

  function _requestSig() {
    const mode = _repMode()
    return [_jobId, _live || mode === 'off' ? mode : 'sphere',
            _waterOn() ? _scope() : null, _waterOn() ? _shellAng() : null, _stride,
            _waterOn(), !!ionsToggle?.checked, !!boxToggle?.checked].join('|')
  }

  function _setStatus(text, color = '#8b949e') {
    if (statusEl) { statusEl.textContent = text; statusEl.style.color = color }
  }

  // ── readouts ──────────────────────────────────────────────────────────────
  function _plan() {
    return solventFetchPlan({
      repMode: _repMode(),
      water: _waterOn(), ions: !!ionsToggle?.checked, box: simulationGraphene || !!boxToggle?.checked,
      scope: _scope(), shellAng: _shellAng(),
      nWatersTotal: _meta?.n_waters ?? 0, nIons: _meta?.n_ions ?? 0,
      nFrames: _nFrames || 1, availableBytes: getAvailableBytes?.() ?? null,
    })
  }

  function _renderCount() {
    if (waterOpts) waterOpts.style.display = _waterOn() ? '' : 'none'
    if (!countEl) return
    if (!_waterOn() || !_meta?.n_waters) { countEl.textContent = ''; return }
    const p = _plan()
    const total = _meta.n_waters
    const shown = _measuredWater ?? p.nWaterEst
    const approx = _measuredWater == null ? '~' : ''
    const parts = [
      _scope() === 'all'
        ? `${total.toLocaleString()} molecules`
        : `${approx}${shown.toLocaleString()} of ${total.toLocaleString()} molecules`,
      `${formatBytes(p.bytesPerFrame)}/frame`,
    ]
    if (p.capped) parts.push(`capped at ${p.maxWaters.toLocaleString()} (${_LIMIT_WHY[p.limitedBy] || 'memory'})`)
    countEl.textContent = parts.join(' · ')
    countEl.style.color = p.capped ? '#d29922' : '#8b949e'
  }

  function _renderLegend() {
    if (!legendEl) return
    // A LANDED FRAME OUTRANKS THE METADATA. The legend and the render read two different
    // sources: the render draws the ions MDAnalysis finds in the PSF, while this reads
    // the counts `charge_audit.json` recorded at package-build time. They disagree
    // whenever the audit is missing/unready (`species: {}` — zero of everything) or the
    // job's counter-ion isn't one of the three the audit tracks, and the panel then
    // asserted "no ions in this job" over a screen full of ions. Ions are never shell-
    // bounded and never capped, so a frame is an exact census: trust it, fall back to the
    // audit only before one exists, and say NOTHING when neither can back a claim.
    const species = _measuredSpecies ?? (_meta?.ready ? _meta.species : null)
    const on = !!ionsToggle?.checked && !!species
    legendEl.style.display = on ? '' : 'none'
    if (!on) return
    // Only species this job actually contains — a legend entry for an absent ion is
    // a claim the render can't back up.
    const rows = ION_SPECIES
      .map((k, i) => [k, i])
      .filter(([k]) => (species[k] || 0) > 0)
      .map(([k, i]) => {
        const s = ION_STYLE[i]
        return `<span style="display:inline-flex;align-items:center;gap:3px;margin-right:8px">`
          + `<span style="width:8px;height:8px;border-radius:50%;background:#${s.color.toString(16).padStart(6, '0')}"></span>`
          + `${s.name} ${species[k].toLocaleString()}</span>`
      })
    legendEl.innerHTML = rows.join('') || '<span>no ions in this job</span>'
  }

  /** The solvent request for the current toggle state, in wire form. */
  function _request() {
    const p = _plan()
    return {
      water: _waterOn(),
      ions: !!ionsToggle?.checked,
      box: simulationGraphene || !!boxToggle?.checked,
      shellAng: _scope() === 'all' ? null : _shellAng(),
      atomistic: p.atomistic,
      maxWaters: p.maxWaters,
    }
  }

  /** Push the current toggle state to the live stream (snake_case on the wire). */
  function _pushLive() {
    const send = getLiveDisplay?.()?.setSolvent
    if (!send) return
    if (!_enabled || !_anyOn() || _repMode() === 'off') { send.call(null, null); return }
    const r = _request()
    send.call(null, {
      water: r.water, ions: r.ions, box: r.box,
      shell_ang: r.shellAng, atomistic: r.atomistic, max_waters: r.maxWaters,
    })
  }

  // ── fetch ─────────────────────────────────────────────────────────────────
  function _invalidate() {
    _generation++
    _preparation = null
    _frameBytes = 0
    _cache = new Map()
    _measuredWater = null
  }

  function _fetchMissing(i) {
    if (_live || !_jobId || !_enabled || !_anyOn() || _repMode() === 'off') return
    if (_inflight) return _inflight
    // Show and measure one frame first, then prepare all remaining frames in
    // byte-bounded batches, amortizing the backend's per-request topology setup.
    const foreground = !_cache.has(i)
    const want = foreground ? [i]
      : Array.from({ length: _nFrames }, (_, k) => k).filter(k => !_cache.has(k))
        .slice(0, Math.max(1, Math.floor(128 * 1024 * 1024 / Math.max(1, _frameBytes))))
    if (!want.length) return
    const generation = _generation
    const task = _fetchBatch(want, generation)
    _inflight = task
    void task.finally(() => { if (_inflight === task) _inflight = null })
    return task
  }

  async function _fetchBatch(want, generation) {
    const p = _plan()
    const sig = _requestSig()
    const ionsOn = !!ionsToggle?.checked
    try {
      const buf = await api.getMdFramesSolventBin(_jobId, want, {
        stride: _stride,
        water: false,
        ions: ionsOn,
        box: simulationGraphene || !!boxToggle?.checked,
        shellAng: _scope() === 'all' ? null : _shellAng(),
        atomistic: false, // Trajectory companions contain no water; ion coordinates are unchanged by representation.
        maxWaters: p.maxWaters,
      })
      // A toggle/rep/shell change mid-flight makes this payload the wrong shape.
      if (generation !== _generation || sig !== _requestSig() || !_enabled || _live) return false
      const parsed = parseSolventBin(buf)
      if (!parsed || want.some(k => !parsed.frames.has(k))) {
        _setStatus('Ion/box frames are missing. Retry playback to reload them.', '#d29922')
        return false
      }
      getSolventOverlay?.()?.setIonSpecies(parsed.ionSpecies)
      // Only a payload that ASKED for ions can speak to what the job contains — one
      // fetched with the toggle off carries an empty species array for the obvious
      // reason, and caching that as "no ions" is the bug this guard exists for.
      if (ionsOn) {
        _measuredSpecies = tallyIonSpecies(parsed.ionSpecies, parsed.speciesTable)
        _renderLegend()
      }
      const first = parsed.frames.values().next().value
      // Measure the complete payload, including graphene, before preparing all
      // frames. The metadata's ion count alone misses most of P1's bytes.
      _frameBytes = Math.max(_frameBytes, Math.ceil(buf.byteLength / parsed.frames.size))
      if (_frameBytes * Math.max(1, _nFrames) > _plan().budgetBytes) {
        _setStatus(`Ion/box trajectory needs ${formatBytes(_frameBytes * _nFrames)}. Increase the frame interval to fit memory.`, '#d29922')
        return false
      }
      for (const [id, f] of parsed.frames) _cache.set(id, f)
      if (first) _measuredWater = first.nWater
      _renderCount()
      _setStatus(parsed.capped
        ? `Solvent ready · capped at ${first?.nWater?.toLocaleString?.() ?? ''} molecules/frame`
        : 'Solvent ready', parsed.capped ? '#d29922' : '#3fb950')
      _draw(_frameIdx)
      return true
    } catch {
      if (generation === _generation) _setStatus('Ion/box load failed. Retry playback to reload.', '#d29922')
      return false
    }
  }

  const _needsFrames = () => _enabled && !_live && _anyOn() && _repMode() !== 'off' && !!_jobId

  /** One background preparation shared by Play and scrubbing. Every frame must
   * be present: a nearby window is not a complete playable trajectory. */
  function prepareAll() {
    if (!_needsFrames()) return Promise.resolve(true)
    if (_preparation?.generation === _generation) return _preparation.promise
    const generation = _generation
    const live = () => generation === _generation && _needsFrames()
    const promise = (async () => {
      while (live()) {
        // A stale request from the previous settings must finish before starting
        // the next worker; otherwise the backend kills the competing request.
        if (_inflight) { await _inflight; if (!live()) return false }
        const total = Math.max(1, _nFrames)
        if (_cache.size >= total) {
          _setStatus(`Ions / box ready · ${total}/${total} frames`, '#3fb950')
          return true
        }
        const pending = _fetchMissing(_frameIdx)
        _setStatus(`Preparing ions / box · ${_cache.size}/${total} frames…`, '#58a6ff')
        if (await pending === false) return false
      }
      return false
    })()
    _preparation = { generation, promise }
    void promise.finally(() => {
      if (_preparation?.promise === promise) _preparation = null
    })
    return promise
  }

  /** Gate a scene seek without drawing ions ahead of the DNA. */
  function ensureFrame(i) {
    if (!_needsFrames() || _cache.has(i | 0)) return true
    const generation = _generation
    return prepareAll().then(ok => ok && generation === _generation && _cache.has(i | 0))
  }

  // ── draw ──────────────────────────────────────────────────────────────────
  function _draw(i) {
    const ov = getSolventOverlay?.()
    const bx = getBoxOverlay?.()
    const f = _cache.get(i)
    if (!f) return false
    // SNAP: solvent is drawn at the frame it belongs to and never interpolated —
    // molecule k of frame i is a different molecule from molecule k of frame i+1.
    if (ov) {
      ov.setMode(_repMode(), ['ballstick', 'stick'].includes(getCurrentRepr?.()))
      ov.setWaterVisible(_waterOn())
      ov.setIonsVisible(!!ionsToggle?.checked)
      ov.setFrame(f)
    }
    if (bx) {
      if (boxToggle?.checked) bx.setCorners(f.box)
      else bx.hide()
    }
    return true
  }

  function _clearScene() {
    getSolventOverlay?.()?.clear()
    getBoxOverlay?.()?.hide()
  }

  function _refresh() {
    if (!_live && waterToggle) waterToggle.checked = false
    _persist()
    _renderCount()
    _renderLegend()
    if (!_enabled || !_anyOn() || _repMode() === 'off') {
      _clearScene(); _setStatus('')
      if (_live) _pushLive()
      return
    }
    if (_live) {
      // The live stream pushes frames on its own schedule; just tell it what to
      // include and let the next frame carry it. No cache — there is only ever
      // one frame in flight.
      _setStatus('Solvent on next frame…', '#58a6ff')
      _pushLive()
      return
    }
    _invalidate()
    _clearScene()
    void prepareAll()
  }

  // ── wiring ────────────────────────────────────────────────────────────────
  _restore()
  for (const el of [waterToggle, ionsToggle, boxToggle, scopeShell, scopeBox]) {
    el?.addEventListener('change', _refresh)
  }
  // Typing re-prices for free; committing re-fetches.
  shellInput?.addEventListener('input', () => { _measuredWater = null; _renderCount() })
  shellInput?.addEventListener('change', _refresh)

  // A rep change MAY flip between two different WIRE payloads (3 vs 9 floats per
  // molecule) — when it does the cache must be dropped, not just re-rendered.  But
  // solventRepMode() collapses the seven scene reps onto three modes, so most rep
  // changes don't touch the wire format at all: full↔beads are both 'sphere', and
  // cylinders/hull-prism/surface are all 'off'.  Refetching every buffered frame on
  // those is pure waste — re-derive the mode and only invalidate when it moved.
  //
  // vdw↔ballstick is the third case: same 'atomistic' payload, but the overlay draws
  // O–H bonds only for ballstick, so it needs a REDRAW of the cached frame and no fetch.
  // Seeded by setEnabled(), never at wiring time: main.js's `getCurrentRepr` closes over
  // a `let` declared further down in the same function, so reading it during this
  // factory's construction is a temporal-dead-zone throw that takes the app boot with it
  // (`?.` does not save you). Null here means the controls were never enabled, so there
  // is nothing on screen to invalidate either way.
  let _lastRepMode   = null
  let _lastBallstick = null
  window.addEventListener('nadoc:representation-change', () => {
    if (!_enabled || _lastRepMode === null) return
    const mode = _repMode()
    const ballstick = ['ballstick', 'stick'].includes(getCurrentRepr?.())
    const modeChanged      = mode !== _lastRepMode
    const ballstickChanged = ballstick !== _lastBallstick
    const wireChanged = _live ? modeChanged : (mode === 'off') !== (_lastRepMode === 'off')
    _lastRepMode   = mode
    _lastBallstick = ballstick
    if (wireChanged) { _refresh(); return }
    if (modeChanged || ballstickChanged) _draw(_frameIdx) // same ions, new drawing style
  })

  return {
    /** Apply companions authored on an animation keyframe. Water stays off. The
     * sphere fallback is required by graphene-only documents, which have no native
     * DNA representation to select an ordinary solvent draw mode. */
    setKeyframeOptions({ ions = false, box = false } = {}) {
      _keyframeOptions = true
      if (waterToggle) waterToggle.checked = false
      if (ionsToggle) ionsToggle.checked = !!ions
      if (boxToggle) boxToggle.checked = !!box
      _refresh()
    },
    /** Point the controls at a job + its trajectory density. */
    async setJob(jobId, { stride = null, nFrames = 0, frameIdx = null } = {}) {
      const changed = jobId !== _jobId
      const reset = changed || stride !== _stride || nFrames !== _nFrames
      if (reset) _invalidate()
      _jobId = jobId
      _stride = stride
      _nFrames = nFrames
      if (reset && frameIdx === null) _frameIdx = 0
      if (frameIdx !== null && Number.isFinite(Number(frameIdx))) {
        _frameIdx = Math.max(0, Number(frameIdx) | 0)
      }
      if (changed) {
        _meta = null
        _measuredSpecies = null
        _measuredWater = null
        _cache = new Map()
      }
      // Retry while the answer is "not ready": a package still being built has no
      // charge audit yet and reports zero water and zero ions, and caching THAT for the
      // life of the panel is how the readouts end up contradicting the screen.
      const generation = _generation
      if (jobId && !_meta?.ready) {
        const meta = await api.getMdSolventMeta(jobId).catch(() => null)
        if (generation !== _generation || jobId !== _jobId) return
        _meta = meta
      }
      _renderCount()
      _renderLegend()
      if (_enabled && _anyOn()) _refresh()
    },

    /**
     * Enable the controls. `transport` says which view is driving:
     *   'traj' — the REST trajectory route, fetched + cached here
     *   'live' — the "Display MD" WebSocket, which pushes frames at us
     */
    setEnabled(on, transport = 'traj') {
      const was = _enabled
      const wasLive = _live
      _enabled = !!on
      if (!on) { _generation++; _preparation = null }
      if (simulationGraphene) window.dispatchEvent(new CustomEvent(
        "nadoc:graphene-md-active", { detail: { active: _enabled } }))
      if (!_enabled) _keyframeOptions = false
      _live = _enabled && transport === 'live'
      if (waterToggle) {
        waterToggle.checked = _live ? _read(LS.water, '') === 'true' : false
      }
      _renderCount()
      if (_live !== wasLive) { _cache = new Map(); _measuredWater = null }
      // Only ask for the representation when it can matter. The panel gates these
      // controls once during its own construction, and main.js's `getCurrentRepr`
      // closes over a `let` declared FURTHER DOWN in the same function — reading it
      // then is a temporal-dead-zone throw that takes the whole app boot with it.
      const mode = _enabled ? _repMode() : 'off'
      // Safe moment to seed the rep-change comparison (post-boot, past the TDZ above):
      // whatever is fetched from here on was fetched under THIS mode, so the listener
      // can tell a real wire-format flip from a rep change that doesn't touch it.
      if (_enabled) {
        _lastRepMode   = mode
        _lastBallstick = ['ballstick', 'stick'].includes(getCurrentRepr?.())
      }
      const ok = _enabled && mode !== 'off'
      const why = mode === 'off'
        ? 'Solvent is drawn in the Beads, Full, VDW and Ball-and-stick representations'
        : 'Select an MD job and turn on Display MD or View trajectory'
      for (const el of [waterToggle, ionsToggle, boxToggle]) {
        if (!el) continue
        const waterBlocked = el === waterToggle && !_live
        const allowed = ok && !waterBlocked
        el.disabled = !allowed
        if (waterBlocked) el.title = 'Water is unavailable for full trajectories. Use Display MD to view water.'
        else if (el === waterToggle) el.removeAttribute('title')
        const lab = el.closest('label')
        if (lab) {
          lab.style.opacity = allowed ? '1' : '0.5'
          lab.style.cursor = allowed ? 'pointer' : 'not-allowed'
          lab.title = waterBlocked ? el.title : allowed ? '' : why
        }
      }
      if (root) root.style.opacity = ok ? '1' : '0.6'
      if (!ok) {
        _clearScene(); _setStatus('')
        if (wasLive) _pushLive()      // tell the stream to stop sending
      } else if ((!was || _live !== wasLive) && _anyOn()) {
        _refresh()
      }
    },

    /** Draw frame `i`; prepare missing companions without displaying stale ones. */
    showFrame(i) {
      _frameIdx = i | 0
      if (!_enabled || !_anyOn() || _repMode() === 'off') return
      if (!_draw(_frameIdx)) { _clearScene(); void prepareAll() }
    },

    /** Wait until the requested companion frame is drawable. Video exporters call
     * this after seeking so they never capture before an async solvent chunk lands. */
    async settleFrame(i, timeoutMs = 120_000) {
      const frame = i | 0
      if (!_enabled || !_anyOn() || _repMode() === 'off') return true
      if (_draw(frame)) return true
      _frameIdx = frame
      const generation = _generation
      let timer
      try {
        const ready = await Promise.race([ensureFrame(frame),
          new Promise(resolve => { timer = setTimeout(() => resolve(false), timeoutMs) })])
        return ready && generation === _generation && _draw(frame)
      } finally { clearTimeout(timer) }
    },

    /**
     * A solvent blob pushed by the live WebSocket. One frame, already current —
     * drawn immediately and never cached, because the live view only ever shows
     * the latest frame.
     */
    liveBlob(buf) {
      if (!_enabled || !_live) return
      const parsed = parseSolventBin(buf)
      if (!parsed) { _setStatus('No solvent in this frame', '#d29922'); return }
      const frame = parsed.frames.values().next().value
      if (!frame) return
      getSolventOverlay?.()?.setIonSpecies(parsed.ionSpecies)
      if (ionsToggle?.checked) {
        _measuredSpecies = tallyIonSpecies(parsed.ionSpecies, parsed.speciesTable)
        _renderLegend()
      }
      _measuredWater = frame.nWater
      _cache = new Map([[_frameIdx, frame]])
      _draw(_frameIdx)
      _renderCount()
      _setStatus(parsed.capped
        ? `Solvent · capped at ${frame.nWater.toLocaleString()} molecules`
        : 'Solvent on', parsed.capped ? '#d29922' : '#3fb950')
    },

    /** Tear down: hide everything and cancel any server-side analysis. */
    clear() {
      _generation++
      _preparation = null
      _clearScene()
      _setStatus('')
      _cache = new Map()
      _measuredWater = null
      if (_live) _pushLive()
      if (_jobId) api.cancelMdAnalysis?.(_jobId, 'solvent')
    },

    isAnyOn: _anyOn,
    prepareAll,
    ensureFrame,
    plan: _plan,
  }
}
