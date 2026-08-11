/**
 * Occupancy-clouds panel section — owns its own DOM, parameters and network.
 *
 * The oxDNA jobs panel only tells it which job is selected and when to turn off; the
 * mutual-exclusion teardown against the other visualization modes stays in the panel,
 * because that is the panel's job.
 *
 * Division of labour for one occupancy view:
 *   backend      clusters the frames, returns N medoid frames + weights
 *   oxdnaDisplay moves the REAL model to rank 0 (the most likely configuration)
 *   overlay      draws ranks 1..N-1 as translucent ghosts
 *   this module  fetches, caches per parameter set, and renders the legend
 *
 * The legend is where the honesty lives. Populations from a run that never revisits a
 * state are meaningless, so `verdict` and `confidence.preliminary` are surfaced as plain
 * text rather than left in the JSON.
 */

import { anchorsToSelection } from '../scene/efield_math.js'
import { initOxdnaAnchorsSetup } from './oxdna_anchors_setup.js'

const C = { dim: '#8b949e', warn: '#d29922', bad: '#f85149', ok: '#3fb950' }

/** The scope picker is the SHARED anchor widget on its own id skeleton — chips, x-delete,
 *  Clear, the scrolling list and the purple halo all come for free, and the scope speaks
 *  the same descriptor vocabulary the engine anchor cards do. */
/** Every id this card binds, derived from one prefix. The oxDNA and NAMD panels are the
 *  same card twice over, so they share one factory and differ only by prefix — the same
 *  `ids`-override shape `initOxdnaAnchorsSetup` uses to serve five engine panels. */
export function occupancyIds(prefix = 'oxdna') {
  return {
    toggle: `${prefix}-jobs-occupancy-toggle`,
    params: `${prefix}-jobs-occupancy-params`,
    n: `${prefix}-jobs-occupancy-n`,
    basis: `${prefix}-jobs-occupancy-basis`,
    rerun: `${prefix}-jobs-occupancy-rerun`,
    status: `${prefix}-jobs-occupancy-status`,
    legend: `${prefix}-jobs-occupancy-legend`,
    scopeSel: `${prefix}-jobs-occupancy-scope`,
    scopeCard: `${prefix}-occupancy-scope-card`,
    fit: `${prefix}-jobs-occupancy-fit`,
    fitRow: `${prefix}-occupancy-fit-row`,
    scope: {
      add: `${prefix}-occupancy-scope-add`, clear: `${prefix}-occupancy-scope-clear`,
      list: `${prefix}-occupancy-scope-list`, status: `${prefix}-occupancy-scope-status`,
      glow: `${prefix}-occupancy-scope-glow`,
      toggle: `${prefix}-occupancy-scope-toggle`, arrow: `${prefix}-occupancy-scope-arrow`,
      body: `${prefix}-occupancy-scope-body`,
    },
  }
}

/** The reference frame a SCOPED run is re-superposed in before clustering. Mirrors the
 *  backend's `OCC_FIT_MODES`; anything else is a 400, so an unknown value clamps here. */
export const OCC_FIT_MODES = ['selection', 'local', 'global']

/** Clamp the UI parameters to what the route accepts. Pure. */
export function normalizeOccupancyParams({ nClusters = 0, basis = 'nt', maxFrames = 200,
                                           fit = 'selection' } = {}) {
  const n = Number.parseInt(nClusters, 10)
  return {
    nClusters: Number.isFinite(n) ? Math.min(6, Math.max(0, n)) : 0,
    basis: basis === 'bp' ? 'bp' : 'nt',
    maxFrames: Number.isFinite(+maxFrames) && +maxFrames > 0 ? Math.floor(+maxFrames) : 200,
    method: 'pca',
    fit: OCC_FIT_MODES.includes(fit) ? fit : 'selection',
  }
}

function _pct(x) { return `${(100 * (x ?? 0)).toFixed(0)}%` }
/** Nanometres at 2 dp — the backend keeps 4 for precision, but a legend reading
 *  "spread 1.0667 nm" is noise where "1.07 nm" is the actual information. */
function _nm(x) { return Number.isFinite(x) ? x.toFixed(2) : '—' }
/** An effective-sample COUNT, not a length: 1 dp, and no trailing zero padding. */
function _count(x) { return Number.isFinite(x) ? String(Math.round(x * 10) / 10) : '—' }

/**
 * One-line summary of what the clustering concluded. Pure.
 *
 * Deliberately leads with the verdict rather than the cluster count: "3 states" from a
 * run that drifted once is a different claim from "3 states" the structure keeps
 * revisiting, and only the second one is about the design.
 */
export function occupancyStatusText(resp) {
  if (!resp) return { text: '', color: C.dim }
  if (!resp.ready) return { text: resp.reason || 'not ready', color: C.dim }

  const frames = `${resp.n_frames} frames`
  const torn = resp.n_frames_torn ? `, ${resp.n_frames_torn} torn rejected` : ''

  if (resp.verdict === 'unimodal') {
    return {
      text: `Single configuration — the ensemble is unimodal `
        + `(separation ${resp.silhouette?.toFixed(2)}). The flexibility map is the right view. `
        + `${frames}${torn}`,
      color: C.dim,
    }
  }
  if (resp.verdict === 'drift') {
    return {
      text: `Drift, not switching — the run moved one way through ${resp.k} shapes and never `
        + `came back (${resp.transitions} transition${resp.transitions === 1 ? '' : 's'}). `
        + `These are the start and end of a path, not configurations in equilibrium; `
        + `their frame counts are not likelihoods. Sample longer. ${frames}${torn}`,
      color: C.warn,
    }
  }
  return {
    text: `${resp.k} configurations, revisited ${resp.transitions} times. ${frames}${torn}`,
    color: C.ok,
  }
}

/**
 * Legend rows, most-populated first. Pure.
 * `colors[i]` of null means "this one is the real model in its design colours".
 */
export function clusterLegendRows(resp, colors) {
  if (!resp?.ready || !resp.clusters?.length) return []
  return resp.clusters.map((c, i) => ({
    rank: c.rank ?? i,
    color: colors?.[i] ?? null,
    populationPct: _pct(c.population),
    stderrPct: _pct(c.population_sem),
    nFrames: c.n_frames,
    visits: c.visits,
    spreadNm: c.rmsd_spread_nm,
    distanceNm: c.rmsd_to_top_nm,
  }))
}

const _hex6 = (hex) => `#${(hex ?? 0).toString(16).padStart(6, '0')}`

/**
 * One scrollable, interactive row per state. Pure — emits markup only; the controller
 * attaches ONE delegated listener to the container rather than N per-row ones, so
 * re-rendering the list can never leak handlers.
 *
 * Every state gets its own flat colour, including rank 0: the design's own per-strand
 * colouring is hidden while this view is up, because two superposed structures are only
 * readable if each is a single identifiable colour.
 */
export function occupancyStateRowsHtml(resp, colors, visible) {
  const rows = clusterLegendRows(resp, colors)
  if (!rows.length) return ''

  // A drift's frame split is an artefact of where the run stopped, not a likelihood.
  const drift = resp.verdict === 'drift'

  return rows.map((r, i) => {
    const weight = drift ? `${r.nFrames} frames` : `${r.populationPct} ± ${r.stderrPct}`
    const extra = [
      `spread ${_nm(r.spreadNm)} nm`,
      r.distanceNm > 0 ? `${_nm(r.distanceNm)} nm from state 1` : null,
      Number.isFinite(r.visits) ? `${r.visits} visit${r.visits === 1 ? '' : 's'}` : null,
    ].filter(Boolean).join(' · ')
    const on = visible?.[i] !== false
    // The controls stay on the baseline while the text wraps — the panel is narrow and
    // `nowrap` silently clipped the per-state stats off the right edge.
    return `<div class="occ-state-row" data-occ-rank="${i}" `
      + 'style="display:flex;align-items:flex-start;gap:5px;padding:2px 1px">'
      + `<input type="checkbox" data-occ-vis="${i}"${on ? ' checked' : ''} `
      + `title="Show or hide state ${i + 1}" style="cursor:pointer;margin-top:1px;flex:none">`
      + `<input type="color" data-occ-color="${i}" value="${_hex6(colors?.[i])}" `
      + `title="Colour for state ${i + 1}" `
      + 'style="width:18px;height:14px;padding:0;border:1px solid #30363d;background:none;'
      + 'cursor:pointer;margin-top:1px;flex:none">'
      + '<span style="font-size:var(--text-xs);color:#c9d1d9;min-width:0;flex:1">'
      + `state ${i + 1} — ${weight}`
      + `<span style="color:${C.dim}"> · ${extra}</span></span></div>`
  }).join('')
}

/** How a scoped run was re-superposed, in the user's words. Pure.
 *  Returns '' for an unscoped run — there is no sub-region whose frame could differ. */
export function occupancyFitLabel(resp) {
  if (!resp?.scoped) return ''
  if (resp.fit === 'local') return `junction frame (${resp.n_fit_points ?? 0} duplex points)`
  if (resp.fit === 'selection') return `fitted on the selection (${resp.n_fit_points ?? 0} points)`
  if (resp.fit === 'global') return 'whole-structure frame'
  return ''
}

/** The footer under the list: what the clustering saw, and how well it was sampled. */
export function occupancyFooterHtml(resp) {
  if (!resp?.ready) return ''
  const pc = resp.variance_explained?.[0]
  const fit = occupancyFitLabel(resp)
  const foot = `<div style="font-size:var(--text-xs);color:${C.dim};margin-top:3px">`
    + `PC1 ${_pct(pc)} of variance · separation ${resp.silhouette?.toFixed(2)}`
    + `${resp.basis === 'bp' ? ' · base-pair midpoints' : ''}`
    + `${fit ? ` · ${fit}` : ''}</div>`

  // A fit mode that DEGRADED says so, or the reading is wrong in a way nothing on screen
  // would reveal — the same contract `basis` has when "bp" falls back to "nt".
  const fitNote = resp.fit_note
    ? `<div style="font-size:var(--text-xs);color:${C.warn};margin-top:2px">${resp.fit_note}</div>`
    : ''

  // The single most important line in the feature: without enough independent visits the
  // populations above are decoration.
  const conf = resp.confidence
  const drift = resp.verdict === 'drift'
  const warn = conf?.preliminary
    ? `<div style="font-size:var(--text-xs);color:${C.warn};margin-top:2px">`
      + `⚠ only ${_count(conf.n_eff)} effectively independent samples — `
      + `${drift ? 'the run has not sampled either state repeatedly' : 'populations are not converged'}. `
      + 'Sample longer before quoting them.</div>'
    : ''
  return foot + fitNote + warn
}

export function initOccupancyControls({
  api, getOverlay, getDisplay, getSelectedJobId, getAnchorSelection = null, onStatus = null,
  engine = 'oxdna', ids = null, fetchOccupancy = null,
} = {}) {
  const id = ids ?? occupancyIds(engine === 'md' ? 'md' : 'oxdna')
  const $ = (x) => (typeof document === 'undefined' ? null : document.getElementById(x))
  const toggle = $(id.toggle)
  const params = $(id.params)
  const nSel = $(id.n)
  const basisSel = $(id.basis)
  const rerunBtn = $(id.rerun)
  const scopeSel = $(id.scopeSel)
  const scopeCard = $(id.scopeCard)
  const fitSel = $(id.fit)
  const fitRow = $(id.fitRow)
  const statusEl = $(id.status)
  const legendEl = $(id.legend)

  // How this engine talks to its backend. Injected rather than branched on, because the
  // two clients have genuinely different signatures (oxDNA takes an options object, MD is
  // positional (id, signal, opts)) and neither should leak in here.
  const _fetch = fetchOccupancy ?? (({ jobId, params: p, selection, refetch, signal }) => (
    selection
      ? api.postOxdnaOccupancy(jobId, { ...p, refetch, selection, signal })
      : api.getOxdnaOccupancy(jobId, { ...p, refetch, signal })))

  let _abort = null
  let _active = false
  let _generation = 0   // invalidates response, display and overlay work as one transaction
  let _cache = null     // { jobId, key, resp }
  let _lastResp = null
  // Per-state user choices, indexed by rank. Kept OUTSIDE the response cache so they
  // survive a recompute — a user who recoloured state 2 does not want it reset because
  // they nudged the frame count.
  let _colors = []
  let _hidden = new Set()

  function _setStatus(text, color = C.dim) {
    if (statusEl) { statusEl.textContent = text; statusEl.style.color = color }
    onStatus?.({ text, color })
  }

  function _paramKey(jobId, p, sel) {
    // The scope is part of the identity of the analysis — two different regions are two
    // different clusterings and must never share a cached result. So is the fit frame:
    // the same region re-superposed differently is a different question.
    return `${jobId}|${p.nClusters}|${p.basis}|${p.maxFrames}|${p.method}|${p.fit}`
      + `|${JSON.stringify(sel)}`
  }

  /** The parameters for THIS request. `fit` only means anything for a scoped run — an
   *  unscoped one is the whole-structure fit by definition, so it is pinned to 'global'
   *  rather than left to vary the cache key over a value the backend ignores. */
  function params_(sel = undefined) {
    const p = normalizeOccupancyParams({
      nClusters: nSel?.value ?? 0,
      basis: basisSel?.value ?? 'nt',
      fit: fitSel?.value ?? 'selection',
    })
    // Base-pair midpoints contain duplex pairs only. Crossover inserts and extension
    // tails are synthetic, unpaired sites, so a scoped `bp` request cannot contain any
    // of the things the user picked (and used to come back as a failed request). Keep
    // the selection intact by using nucleotide coordinates for every synthetic scope.
    if ((sel?.extra_bases?.length ?? 0) || (sel?.extensions?.length ?? 0)) p.basis = 'nt'
    if (sel === null) p.fit = 'global'
    return p
  }

  // Instantiated, not copied: initOxdnaAnchorsSetup already drives five engine panels
  // off an `ids` override, and `engine: 'occupancy'` gives this card its own halo channel.
  const _scope = initOxdnaAnchorsSetup({
    ids: id.scope,
    engine: engine === 'md' ? 'md-occupancy' : 'occupancy',
    getSelection: getAnchorSelection,
    onChange: () => { if (_active && scopeSel?.value === 'selection') refresh() },
  })

  /** The scope the user picked, or null for the whole structure. */
  function selection_() {
    if (scopeSel?.value !== 'selection') return null
    return anchorsToSelection(_scope?.getAnchors?.() ?? [])
  }

  function _syncScopeCard() {
    const on = scopeSel?.value === 'selection'
    if (scopeCard) scopeCard.style.display = on ? '' : 'none'
    // The fit frame is a property of a SCOPED analysis; on the whole structure there is
    // nothing to re-superpose, so showing the control there would only invite a setting
    // that does nothing.
    if (fitRow) fitRow.style.display = on ? '' : 'none'
  }
  _syncScopeCard()

  // The shared widget collapses itself on init (every engine's anchor card ships
  // collapsed). Here the whole card is already gated by the "Analyse:" selector, so
  // arriving at a collapsed body would just be an extra click — open it once, leaving it
  // collapsible for anyone who wants the room back.
  const _scopeBody = $(id.scope.body)
  if (_scopeBody && _scopeBody.style.display === 'none') $(id.scope.toggle)?.click()

  async function refresh({ refetch = false } = {}) {
    const jobId = getSelectedJobId?.()
    if (!jobId) return { ok: false, reason: 'no job' }

    const sel = selection_()
    const p = params_(sel)
    const key = _paramKey(jobId, p, sel)

    // Becoming active must happen BEFORE the cache short-circuit: a re-toggle after off()
    // hits the cache, and returning early would leave the parameter controls hidden and
    // the module marked inactive while the view is plainly on screen.
    _active = true
    const generation = ++_generation
    _claimOverlay()

    if (scopeSel?.value === 'selection' && !sel) {
      getOverlay?.()?.clear()
      _setStatus('Pick clusters, strands or bases in the 3D view, then "Add selection to scope".',
                 C.warn)
      return { ok: false, reason: 'empty scope' }
    }

    if (!refetch && _cache?.key === key) return _apply(_cache.resp, generation)

    _abort?.abort()
    const request = new AbortController()
    _abort = request
    _setStatus('Clustering configurations…')
    if (legendEl) legendEl.style.display = 'none'

    let resp
    try {
      resp = await _fetch({ jobId, params: p, selection: sel, refetch, signal: request.signal })
    } catch (e) {
      if (e?.name === 'AbortError') return { ok: false, reason: 'aborted' }
      _setStatus(`Occupancy failed: ${e?.message ?? e}`, C.bad)
      return { ok: false, reason: 'error' }
    }
    // The shared API client deliberately converts an aborted fetch to null. Scope edits
    // can issue several refreshes in quick succession (especially when adding multiple
    // picked bases), so distinguish that intentional cancellation from a real null
    // response or the older request races in and overwrites the new status with
    // "Occupancy request failed".
    if (request.signal.aborted) return { ok: false, reason: 'aborted' }
    if (!resp) { _setStatus('Occupancy request failed', C.bad); return { ok: false, reason: 'error' } }

    _cache = { jobId, key, resp }
    return _apply(resp, generation)
  }

  async function _apply(resp, generation = _generation) {
    if (!_active || generation !== _generation) return { ok: false, reason: 'superseded' }
    _lastResp = resp
    const s = occupancyStatusText(resp)
    _setStatus(s.text, s.color)

    if (!resp?.ready) {
      getOverlay?.()?.clear()
      if (legendEl) legendEl.style.display = 'none'
      return { ok: false, reason: resp?.reason || 'not ready' }
    }

    const jobId = getSelectedJobId?.()
    const r = await getDisplay?.()?.displayOccupancy?.(jobId, resp)
    if (!_active || generation !== _generation) {
      // displayOccupancy may have awaited cap/surface setup before moving the real model.
      // If off() won that race, remove anything the late completion just applied.
      getDisplay?.()?.stopAndRestore?.()
      getOverlay?.()?.clear()
      return { ok: false, reason: 'superseded' }
    }
    if (r && !r.ok) return r

    const overlay = getOverlay?.()
    const n = resp.clusters.length

    // Seed any colour the user has not chosen from the palette, then hand the full
    // per-rank arrays over so a rebuild reproduces exactly what was on screen.
    const defaults = overlay?.defaultColors?.(n) ?? []
    for (let i = 0; i < n; i++) if (_colors[i] == null) _colors[i] = defaults[i]
    _colors.length = n
    const visible = Array.from({ length: n }, (_, i) => !_hidden.has(i))

    // Only a genuinely multimodal ensemble gets superposed copies. Drawing the ends of a
    // drift as separate "configurations" would be the exact lie the verdict prevents.
    let states = 0
    if (resp.verdict === 'switching') {
      const built = await overlay?.setClusters(resp, { colors: _colors, visible })
      if (!_active || generation !== _generation) {
        overlay?.clear()
        getDisplay?.()?.stopAndRestore?.()
        return { ok: false, reason: 'superseded' }
      }
      states = built?.states ?? 0
    } else {
      overlay?.clear()
    }

    _renderList(resp, states ? _colors : null, visible)
    return { ok: true, verdict: resp.verdict, states, ghosts: states }
  }

  /** Rebuild the scrollable state list. Colours are null when nothing was drawn, so the
   *  rows never advertise a colour that is not in the scene. */
  function _renderList(resp, colors, visible) {
    if (!legendEl) return
    const rows = colors
      ? occupancyStateRowsHtml(resp, colors, visible)
      : ''
    legendEl.innerHTML = rows + occupancyFooterHtml(resp)
    legendEl.style.display = legendEl.innerHTML ? '' : 'none'
  }

  /** Per-rank colours/toggles only mean something for a FIXED clustering — after a
   *  re-cluster, "state 3" is a different structure, so the choices are dropped. */
  function _resetChoices() {
    _colors = []
    _hidden = new Set()
  }

  // One overlay serves both engine panels, so two active cards would fight over it and
  // the loser's list would keep describing states that are no longer on screen. Whichever
  // card runs last wins the overlay and tells the other to stand down.
  const _OCC_ACTIVE_EVENT = 'nadoc:occupancy-active'
  if (typeof window !== 'undefined') {
    window.addEventListener(_OCC_ACTIVE_EVENT, (e) => {
      if (e?.detail?.engine && e.detail.engine !== engine && _active) off()
    })
  }
  function _claimOverlay() {
    if (typeof window === 'undefined') return
    window.dispatchEvent(new CustomEvent(_OCC_ACTIVE_EVENT, { detail: { engine } }))
  }

  function off() {
    _generation++
    _abort?.abort()
    _abort = null
    _active = false
    _lastResp = null
    _resetChoices()
    getOverlay?.()?.clear()
    // Parameter choices remain editable while the visualization is off. In particular,
    // keep the scope picker and fit control consistent with the visible Analyse value.
    _syncScopeCard()
    if (legendEl) { legendEl.style.display = 'none'; legendEl.innerHTML = '' }
    _setStatus('')
  }

  // ONE delegated listener for the whole list — the rows are re-rendered on every
  // refresh, so per-row handlers would leak on each rebuild.
  legendEl?.addEventListener('change', (e) => {
    const t = e.target
    const overlay = getOverlay?.()
    if (!t || !overlay) return

    const visRank = t.getAttribute?.('data-occ-vis')
    if (visRank != null) {
      const rank = Number(visRank)
      if (t.checked) _hidden.delete(rank)
      else _hidden.add(rank)
      overlay.setStateVisible?.(rank, t.checked)
      return
    }

    const colRank = t.getAttribute?.('data-occ-color')
    if (colRank != null) {
      const rank = Number(colRank)
      const hex = parseInt(String(t.value).replace('#', ''), 16)
      if (!Number.isFinite(hex)) return
      _colors[rank] = hex
      // Recolouring rebuilds that one copy (the tint is baked in at build time so it
      // survives at cylinder LOD) — a beat on a large design, but only for one state.
      overlay.setStateColor?.(rank, hex)
    }
  })

  scopeSel?.addEventListener('change', () => {
    _syncScopeCard()
    _resetChoices()
    if (_active) refresh()
  })
  nSel?.addEventListener('change', () => { _resetChoices(); if (_active) refresh() })
  basisSel?.addEventListener('change', () => { _resetChoices(); if (_active) refresh() })
  // A different fit frame is a different clustering, so the per-state colours/visibility
  // are dropped with it — "state 2" fitted locally is not "state 2" fitted globally.
  fitSel?.addEventListener('change', () => { _resetChoices(); if (_active) refresh() })
  rerunBtn?.addEventListener('click', () => { if (_active) refresh({ refetch: true }) })

  return {
    refresh,
    off,
    isActive: () => _active,
    params: params_,
    lastResponse: () => _lastResp,
    setStatus: (t, c = C.warn) => _setStatus(t, c),
    toggleEl: () => toggle,
    scope: () => _scope,
    selection: selection_,
  }
}
