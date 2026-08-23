/**
 * oxDNA display controller.
 *
 * Two display modes, both Physical-layer / display-state only (topology is never
 * touched), and mutually exclusive (they share the one bead-position overlay):
 *
 *  - "OxDNA display" (displayJob): deform the NADOC model to a job's last relaxed
 *    configuration via designRenderer.applyFemPositions(...).
 *  - "Flexibility map" (displayRmsf): deform the model to the per-base AVERAGE
 *    position over the production trajectory and recolour each backbone bead by
 *    its RMSF (root-mean-square fluctuation) — rigid = dark, flexible = bright —
 *    via designRenderer.applyScalarColors(...).
 *  - "Deviation map" (displayDeviation) and "Strain map" (displayStrain): the same
 *    mean structure recoloured by, respectively, each base's distance from its
 *    DESIGNED position (green→red) and its SIGNED local strain — backbone-FENE or
 *    Watson–Crick — on a diverging ramp (blue = compressed, white = relaxed,
 *    red = stretched).  Both take a pre-fetched payload; CG beads only.
 *
 * Toggling either off restores the model via applyFemPositions(null) +
 * clearScalarColors().
 *
 * Factory: initOxdnaDisplay({ designRenderer, api }) → controller.
 */

import { strideIndices, nearestOf } from '../scene/trajectory_range.js'
import { colormapHex } from './colormaps.js'
import { expandStampFrames, stampTopologyMatches } from '../scene/atomistic_stamp.js'
import { parseSurfaceBin } from '../scene/surface_bin.js'
import { parseAtomisticBundleBin } from '../scene/atomistic_bundle_bin.js'

/**
 * Pure mapping: a /oxdna/jobs/{id}/display response → applyFemPositions updates.
 * Returns [] for a not-ready / empty response.  Kept pure for unit testing.
 */
export function toFemUpdates(displayResponse) {
  if (!displayResponse || !displayResponse.ready || !Array.isArray(displayResponse.positions)) {
    return []
  }
  return displayResponse.positions.map((p) => {
    const out = {
      helix_id: p.helix_id, bp_index: p.bp_index, direction: p.direction,
      copy: p.copy ?? 0, backbone_position: p.backbone_position,
      nx: p.nx, ny: p.ny, nz: p.nz,
    }
    if (Array.isArray(p.cm_position)) out.cm_position = p.cm_position
    if (Array.isArray(p.base_position)) out.base_position = p.base_position
    if (p.exact_sites === true) out.exact_sites = true
    if (p.tx !== undefined) { out.tx = p.tx; out.ty = p.ty; out.tz = p.tz }
    return out
  })
}

/** Pure: viridis colour for t∈[0,1] as a 0xRRGGBB int (rigid→flexible ramp).
 *  Delegates to the shared colormap registry so the flex map, its legend, and the
 *  colormap picker can never drift apart. */
export function viridisHex(t) { return colormapHex('viridis', t) }

/**
 * Pure: a /oxdna/jobs/{id}/rmsf response → { updates, colorByKey, min, max }.
 * RMSF is scaled to [loBound, hiBound] (values outside clamp to the endpoints);
 * when bounds are omitted it defaults to the design's own min→max RMSF so
 * rigid-vs-flexible contrast is maximised.  colorByKey maps "helix:bp:dir" →
 * viridis hex.  Returns null for a not-ready / empty response.
 */
export function rmsfColorMap(resp, loBound, hiBound, cmap = 'viridis') {
  if (!resp || !resp.ready || !Array.isArray(resp.positions) || !resp.positions.length) {
    return null
  }
  const dataLo = Number.isFinite(resp.min_rmsf) ? resp.min_rmsf : 0
  const dataHi = Number.isFinite(resp.max_rmsf) ? resp.max_rmsf : 0
  const lo = Number.isFinite(loBound) ? loBound : dataLo
  const hi = Number.isFinite(hiBound) ? hiBound : dataHi
  const span = hi - lo
  const updates = []
  const colorByKey = {}
  for (const p of resp.positions) {
    const update = {
      helix_id: p.helix_id, bp_index: p.bp_index, direction: p.direction, copy: p.copy ?? 0,
      backbone_position: p.backbone_position, nx: p.nx, ny: p.ny, nz: p.nz,
    }
    if (Array.isArray(p.base_position)) update.base_position = p.base_position
    if (p.tx !== undefined) { update.tx = p.tx; update.ty = p.ty; update.tz = p.tz }
    updates.push(update)
    const t = span > 1e-9 ? (p.rmsf - lo) / span : 0.0   // colormapHex clamps to [0,1]
    const hex = colormapHex(cmap, t)
    // 4-part key → each loop copy's bead/slab/cone; 3-part alias (copy 0 only) keeps
    // 3-part consumers working (crossover-arc recolour, which lands on real nucleotides).
    colorByKey[`${p.helix_id}:${p.bp_index}:${p.direction}:${p.copy ?? 0}`] = hex
    if ((p.copy ?? 0) === 0) colorByKey[`${p.helix_id}:${p.bp_index}:${p.direction}`] = hex
  }
  return { updates, colorByKey, min: dataLo, max: dataHi }
}

/** Pure: per-vertex RMSF floats → flat RGB Float32Array (0-1), viridis over
 *  [lo,hi] (values outside clamp).  Lets the surface use the SAME ramp/scale as
 *  the beads + atomistic.  Kept pure for unit testing. */
export function rmsfToVertexColors(rmsf, lo, hi, cmap = 'viridis') {
  const span = hi - lo
  const out = new Float32Array((rmsf?.length || 0) * 3)
  for (let i = 0; i < (rmsf?.length || 0); i++) {
    const t = span > 1e-9 ? (rmsf[i] - lo) / span : 0
    const hex = colormapHex(cmap, t)
    out[i * 3]     = ((hex >> 16) & 0xFF) / 255
    out[i * 3 + 1] = ((hex >> 8) & 0xFF) / 255
    out[i * 3 + 2] = (hex & 0xFF) / 255
  }
  return out
}

// Deviation ramp: green (matches design) → amber → red (far from design).  A
// good→bad ramp reads more naturally than viridis for "how wrong is each base".
// Sourced from the shared registry ('devramp') so map + legend + picker agree.
export function deviationHex(t) { return colormapHex('devramp', t) }

/** Pure: deviation-map response → {updates, colorByKey, min, max} (mirrors
 *  rmsfColorMap, but reads per-nucleotide `deviation` and colours green→red). */
export function deviationColorMap(resp, loBound, hiBound, cmap = 'devramp') {
  if (!resp || !resp.ready || !Array.isArray(resp.positions) || !resp.positions.length) {
    return null
  }
  const dataLo = Number.isFinite(resp.min_deviation) ? resp.min_deviation : 0
  const dataHi = Number.isFinite(resp.max_deviation) ? resp.max_deviation : 0
  const lo = Number.isFinite(loBound) ? loBound : dataLo
  const hi = Number.isFinite(hiBound) ? hiBound : dataHi
  const span = hi - lo
  const updates = []
  const colorByKey = {}
  for (const p of resp.positions) {
    updates.push({
      helix_id: p.helix_id, bp_index: p.bp_index, direction: p.direction, copy: p.copy ?? 0,
      backbone_position: p.backbone_position, nx: p.nx, ny: p.ny, nz: p.nz,
    })
    const t = span > 1e-9 ? (p.deviation - lo) / span : 0.0
    const hex = colormapHex(cmap, t)
    colorByKey[`${p.helix_id}:${p.bp_index}:${p.direction}:${p.copy ?? 0}`] = hex
    if ((p.copy ?? 0) === 0) colorByKey[`${p.helix_id}:${p.bp_index}:${p.direction}`] = hex
  }
  return { updates, colorByKey, min: dataLo, max: dataHi }
}

/**
 * Pure: symmetric default colour bounds for a SIGNED strain payload, so a diverging
 * colormap's midpoint lands exactly on 0 (relaxed) and compression/tension read as
 * opposite colours rather than both as "low".
 *
 * The half-width is the backend's ROBUST `display_abs_strain`, not the max: a handful of
 * melted WC pairs read several hundred percent and would otherwise flatten the entire
 * structure onto the midpoint colour.  Those outliers still saturate the ramp's end
 * (colormapHex clamps).  The percentile behind it is per-metric and lives in
 * `oxdna_health._STRAIN_DISPLAY_PERCENTILE` — backbone strain is FENE-bounded, WC strain
 * is not.  Falls back to abs_max_strain, then to |min|/|max|, then to ±1 for a degenerate
 * (all-zero / missing) payload.
 */
/**
 * Pure: the mean + true data range a strain payload should REPORT, from whichever
 * population is on screen.  With ssDNA excluded these must come from the `dsdna` block, or
 * the panel would quote a mean and range for bases it is no longer colouring.
 */
export function strainStats(resp, dsOnly = false) {
  const src = (dsOnly && resp?.dsdna) ? resp.dsdna : resp
  return { mean: src?.mean_strain, dataMin: src?.min_strain, dataMax: src?.max_strain }
}

export function strainBounds(resp, dsOnly = false) {
  // With ssDNA excluded, scale on the duplex subset's own stats — otherwise one flailing
  // overhang sets the range for the duplex the user is actually inspecting.
  const src = (dsOnly && resp?.dsdna) ? resp.dsdna : resp
  const cands = [src?.display_abs_strain, src?.abs_max_strain]
  let a = cands.find((v) => Number.isFinite(v) && Math.abs(v) > 1e-12)
  if (!Number.isFinite(a)) {
    a = Math.max(Math.abs(src?.min_strain ?? 0), Math.abs(src?.max_strain ?? 0))
  }
  return Math.abs(a) > 1e-12 ? { lo: -Math.abs(a), hi: Math.abs(a) } : { lo: -1, hi: 1 }
}

/**
 * Pure: strain-map response → {updates, colorByKey, min, max, nColored}.  Mirrors
 * deviationColorMap but reads the SIGNED per-nucleotide `strain` and defaults to symmetric
 * ± bounds so 0 sits at the diverging colormap's midpoint.  `min`/`max` are the bounds
 * actually used for colour — the legend must match the beads.
 *
 * MOVE LIST vs COLOUR LIST — they are deliberately different sets.  `updates` carries EVERY
 * position so the whole structure deforms to the simulated mean together; a bead left out
 * would stay at its DESIGN coordinates while its neighbours move (the `wc` map measures only
 * paired bases, so that would strand every ssDNA overhang, scaffold loop and extension tail
 * in mid-air).  `colorByKey` carries only what should be coloured: nucleotides with a finite
 * strain, and — when `dsOnly` — only those the design intends to be duplex.  Everything else
 * rides along uncoloured, keeping its native strand colour.
 */
export function strainColorMap(resp, loBound, hiBound, cmap = 'coolwarm', { dsOnly = false } = {}) {
  if (!resp || !resp.ready || !Array.isArray(resp.positions) || !resp.positions.length) {
    return null
  }
  const dflt = strainBounds(resp, dsOnly)
  const lo = Number.isFinite(loBound) ? loBound : dflt.lo
  const hi = Number.isFinite(hiBound) ? hiBound : dflt.hi
  const span = hi - lo
  const updates = []
  const colorByKey = {}
  let nColored = 0
  for (const p of resp.positions) {
    updates.push({
      helix_id: p.helix_id, bp_index: p.bp_index, direction: p.direction, copy: p.copy ?? 0,
      backbone_position: p.backbone_position, nx: p.nx, ny: p.ny, nz: p.nz,
    })
    if (!Number.isFinite(p.strain)) continue     // unmeasured — moves, but takes no colour
    if (dsOnly && p.ss) continue                 // designed ssDNA — excluded by request
    const t = span > 1e-12 ? (p.strain - lo) / span : 0.5   // colormapHex clamps to [0,1]
    const hex = colormapHex(cmap, t)
    colorByKey[`${p.helix_id}:${p.bp_index}:${p.direction}:${p.copy ?? 0}`] = hex
    if ((p.copy ?? 0) === 0) colorByKey[`${p.helix_id}:${p.bp_index}:${p.direction}`] = hex
    nColored++
  }
  return { updates, colorByKey, min: lo, max: hi, nColored }
}

/**
 * Pure: turn one composite-trajectory frame (flat float list) + the shared key
 * list into applyFemPositions updates.  keys = [[helix,bp,dir], …]; frame holds
 * Current frames hold 9 floats per key (backbone site, a1, a3). Legacy cached frames
 * with 6 floats (backbone+a1) remain readable, but cannot reconstruct live slab axes.
 */
export function framesToUpdates(keys, frame) {
  if (!Array.isArray(keys) || (!Array.isArray(frame) && !ArrayBuffer.isView(frame))) return []
  const stride = keys.length && frame.length >= keys.length * 9 ? 9 : 6
  const updates = []
  for (let j = 0; j < keys.length; j++) {
    const o = j * stride
    const update = {
      helix_id: keys[j][0], bp_index: keys[j][1], direction: keys[j][2],
      copy: keys[j][3] ?? 0,   // 4th key element = loop-copy index (absent → 0)
      backbone_position: [frame[o], frame[o + 1], frame[o + 2]],
      nx: frame[o + 3], ny: frame[o + 4], nz: frame[o + 5],
    }
    if (stride === 9) {
      update.tx = frame[o + 6]; update.ty = frame[o + 7]; update.tz = frame[o + 8]
      update.base_position = oxdnaBaseSiteFromBackbone(update)
      update.cm_position = oxdnaCmFromBackbone(update)
      update.exact_sites = true
    }
    updates.push(update)
  }
  return updates
}

/** Invert oxDNA's backbone-site offset to recover the rigid-body centre. */
export function oxdnaCmFromBackbone(p) {
  const ux = p.nx, uy = p.ny, uz = p.nz
  const vx = p.tx, vy = p.ty, vz = p.tz
  const a2 = [vy * uz - vz * uy, vz * ux - vx * uz, vx * uy - vy * ux]
  return p.backbone_position.map((value, i) =>
    value + (0.34 * [ux, uy, uz][i] - 0.3408 * a2[i]) * 0.8518)
}

/** Reconstruct oxDNA's base interaction site from backbone-site + a1/a3. */
export function oxdnaBaseSiteFromBackbone(p) {
  const ux = p.nx, uy = p.ny, uz = p.nz
  const vx = p.tx, vy = p.ty, vz = p.tz
  // a2 = a3 × a1; base - backbone = (0.74*a1 - 0.3408*a2) * 0.8518 nm.
  const a2x = vy * uz - vz * uy
  const a2y = vz * ux - vx * uz
  const a2z = vx * uy - vy * ux
  const bb = p.backbone_position
  return [
    bb[0] + (0.74 * ux - 0.3408 * a2x) * 0.8518,
    bb[1] + (0.74 * uy - 0.3408 * a2y) * 0.8518,
    bb[2] + (0.74 * uz - 0.3408 * a2z) * 0.8518,
  ]
}

/** Build { [attachmentId]: number[16] } (row-major 4×4) from a /display response's
 *  `proteins` list — the per-protein relaxed-pose transforms.  Pure. */
export function proteinTransformMap(displayResponse) {
  const out = {}
  for (const p of (displayResponse?.proteins || [])) {
    if (p?.attachment_id && Array.isArray(p.transform) && p.transform.length === 16) {
      out[p.attachment_id] = p.transform
    }
  }
  return out
}

/**
 * Pure: which renderer a scene representation drives.
 *   vdw / ballstick → 'atomistic'   (atomistic_renderer)
 *   surface         → 'surface'     (surface_renderer)
 *   everything else (full/beads/cylinders/hull/…) → 'cg'  (helix beads/slabs)
 * Decides whether an oxDNA display overlay needs a heavy-rep reconstruction.
 */
export function repKind(repr) {
  if (repr === 'vdw' || repr === 'ballstick' || repr === 'stick') return 'atomistic'
  if (repr === 'surface') return 'surface'
  return 'cg'
}

// Heavy-rep "coarse" snap-GRID size (per job): the scrubber snaps to the nearest of
// this many evenly-spaced frames, and each grid frame is reconstructed + cached LAZILY
// on first visit (one all-atom rebuild ≈ several seconds — so a small grid, fetched one
// frame at a time, NOT a big upfront bake that would block for minutes). "fine" bypasses
// the grid and reconstructs the exact scrubbed frame on demand (slowest — warning-gated).
const _COARSE_ATOM_CAP = 12
const _COARSE_SURF_CAP = 8

// Granularity the prebuild budget is rounded down to. The budget comes from the host's
// MemAvailable and is only ever a rough "how much can we spare" — quantising it keeps the
// derived grid size STABLE across calls, so a representation change can't silently resize
// the grid and refetch frames it already holds. See prebuildHeavy.
const _BUDGET_QUANTUM = 128 * 1024 * 1024

// When the backend can stream COORDINATES ONLY against a topology fetched once (the MD
// path — see md_viz_adapter), a whole all-atom trajectory can be held in memory and the
// grid stops being a compromise. What it cannot be is unbounded: a frame costs
// n_serials x 3 x 4 bytes as a Float32Array, which on a 300 k-atom origami (serials run
// to ~469 k) is 5.4 MB. This budget is the ceiling on ALL cached frames together;
// past it the grid falls back to evenly-spaced sampling and says so.
// A 64-bit browser tab will not hand out an unbounded JS heap however much RAM the box
// has — the ceiling is typically a couple of GB, and hitting it is an unrecoverable tab
// crash, not a slowdown. So free RAM is necessary but never sufficient, and this is the
// ceiling that applies even on a machine with memory to spare (and the fallback budget
// when the host's free memory can't be read at all).
export const BROWSER_HEAP_CEILING_BYTES = 1536 * 1024 * 1024
const _ATOM_PREBUILD_BUDGET_BYTES = BROWSER_HEAP_CEILING_BYTES
// Never take more than this share of what the OS says is available: the browser also
// needs room for the scene and the rest of the page, and pushing a machine into swap is
// worse than a coarser trajectory.
export const FREE_RAM_SAFE_FRACTION = 0.5
// Serial span per nucleotide, measured on VoltronCore (469 350 serials / 14 774 nt).
// Lets the panel price a prebuild from the trajectory payload alone, BEFORE the ~30 s
// topology fetch reveals the exact span.
export const SERIALS_PER_NUCLEOTIDE_EST = 32
/** Pure: bytes one cached coordinate frame costs (Float32 xyz per serial). Falls back to
 *  the per-nucleotide estimate when the exact serial span isn't known yet. */
export function atomFrameBytes({ nSerials = 0, nNucleotides = 0 } = {}) {
  const serials = Number(nSerials) > 0
    ? Number(nSerials)
    : Math.max(0, Number(nNucleotides) || 0) * SERIALS_PER_NUCLEOTIDE_EST
  return Math.max(0, Math.round(serials)) * 3 * 4
}
/** Pure: how many frames of an `nSerials`-serial structure fit the prebuild budget.
 *  ≥1 always — one frame is what "show me this frame" needs at minimum. */
export function affordableAtomFrames(nSerials, nFrames,
                                     budgetBytes = _ATOM_PREBUILD_BUDGET_BYTES) {
  const per = Math.max(1, Number(nSerials) || 0) * 3 * 4      // Float32 xyz per serial
  const n = Math.max(0, Math.floor(Number(nFrames)) || 0)
  if (!n) return 0
  return Math.max(1, Math.min(n, Math.floor(budgetBytes / per)))
}
/**
 * Pure: what an all-atom prebuild would cost, what this machine can actually spare, and
 * which limit binds. `availableBytes` is the host's MemAvailable (null = unknown, in
 * which case only the fixed budget and the heap ceiling apply — an unknown machine is
 * not assumed to be a large one).
 *
 * Returns `{ wantBytes, budgetBytes, frames, capped, limitedBy, frameBytes }`;
 * `limitedBy` is 'ram' | 'heap' | 'budget' | null and is what the warning names.
 */
export function prebuildMemoryPlan({
  nFrames, nSerials = 0, nNucleotides = 0, availableBytes = null,
  fixedBudget = _ATOM_PREBUILD_BUDGET_BYTES,
  heapCeiling = BROWSER_HEAP_CEILING_BYTES,
  safeFraction = FREE_RAM_SAFE_FRACTION,
} = {}) {
  const frameBytes = atomFrameBytes({ nSerials, nNucleotides })
  const total = Math.max(0, Math.floor(Number(nFrames)) || 0)
  const wantBytes = total * frameBytes
  const limits = [['heap', Math.min(fixedBudget, heapCeiling)]]
  const avail = Number(availableBytes)
  if (Number.isFinite(avail) && avail > 0) limits.push(['ram', avail * safeFraction])
  let limitedBy = null
  let budgetBytes = Infinity
  for (const [name, v] of limits) {
    if (v < budgetBytes) { budgetBytes = v; limitedBy = name }
  }
  const frames = frameBytes > 0 && total > 0
    ? affordableAtomFrames(frameBytes / 12, total, budgetBytes)
    : total
  const capped = frames < total
  return { wantBytes, budgetBytes, frames, capped, frameBytes,
           limitedBy: capped ? limitedBy : null }
}

export function initOxdnaDisplay({
  designRenderer, api, proteinRenderer = null,
  getAtomisticRenderer = null, getSurfaceRenderer = null,
  getCurrentRepr = null, onRestoreDesignHeavy = null, onHeavyStatus = null,
  applyOxdnaFrame = null,
  onFrame = null,
  // Called from stopAndRestore() so the occupancy overlay drops its ghost copies at the
  // same moment the real model reverts — otherwise turning the view off leaves the
  // superposed configurations floating around a design that no longer matches them.
  onOccupancyClear = null,
  // Real relaxed surface capture strands (per-strand world-nm bead lists) from a displayed
  // job → drives the results overlay (replaces the seed preview). Null clears it.
  onSurfaceStrands = null,
  // Live surface params (probe radius / colour mode) from the Surface-options sidebar, so
  // the overlay surface honours them instead of the backend defaults.  () => ({...}).
  getSurfaceParams = () => ({}),
  // Fired after a heavy (atomistic) frame's atoms are applied — lets the caller hide
  // the CG model exactly when the reconstructed atoms land (so switching full→atomistic
  // while this overlay is active shows no "native flash").
  onHeavyApplied = () => {},
}) {
  // Single chokepoint for the bead-position overlay: applies the frame to the rigid
  // design mesh AND forwards it to any per-frame consumer (onFrame) — e.g. flexible
  // ssDNA arcs, whose beads are excluded from the rigid mesh and must be redrawn at
  // simulated positions.  Pass null to restore the design (both revert).
  // Last relaxed CG overlay applied — re-applied when a CG rep is restored so the switch's
  // arc-layout pass can't leave extra-base / extension beads stranded at native positions.
  let _lastCgUpdates = null
  const _applyFem = (updates) => {
    _lastCgUpdates = updates
    const handledByOxdna = getCurrentRepr?.() === 'oxdna' && applyOxdnaFrame?.(updates) === true
    if (!handledByOxdna) designRenderer?.applyFemPositions(updates)
    onFrame?.(updates)
  }
  let _active = false
  let _jobId = null
  let _mode = null     // 'relaxed' | 'rmsf' | 'deviation' | 'strain' | 'trajectory' | 'occupancy'
  let _rmsfResp = null // cached /rmsf payload so the scale can recolour without re-fetching
  let _devResp = null  // cached /deviation payload so the scale can recolour without re-fetching
  let _strainResp = null // cached /strain payload (same reason)
  let _rmsfCmap = 'viridis'    // active flex-map colormap (widget-driven)
  let _devCmap  = 'devramp'    // active deviation-map colormap (widget-driven)
  let _strainCmap = 'coolwarm' // active strain-map colormap (diverging — 0 at the midpoint)
  let _strainDsOnly = false    // strain map: colour designed-duplex bases only (ssDNA rides uncoloured)
  let _devBounds = null
  let _strainBounds = null
  let _traj = null     // cached /trajectory payload {keys, frames, markers, n_frames, stages}
  // The surface-strand coordinates currently exposed by the backend are the job's latest
  // simulated result.  RMSF + trajectory payloads contain only design-keyed origami beads,
  // so cache the companion /display result and inject those real strands before either mode
  // applies its CG positions.  This replaces a stale setup preview without refetching on every
  // trajectory scrub or flex-map re-toggle.
  const _surfaceStrandsByJob = new Map()
  // Monotonic token: bumped by every display call AND by stopAndRestore, so an
  // async fetch (live-follow poll / job-switch) that resolves AFTER the overlay
  // was turned off or superseded by a newer call bails instead of re-applying
  // stale positions (the "toggle off but sim positions stay" desync).
  let _epoch = 0
  let _loadAbort = null
  function _beginLoad() {
    _loadAbort?.abort()
    _loadAbort = new AbortController()
    return _loadAbort.signal
  }
  function _cancelLoad() {
    _loadAbort?.abort()
    _loadAbort = null
    _epoch++
  }

  // ── Heavy reps (atomistic / surface) ───────────────────────────────────────
  // The CG overlay above is applied via designRenderer.applyFemPositions; when the
  // scene is in an atomistic or surface representation we ALSO reconstruct that
  // heavy geometry from the same relaxed/rmsf/trajectory frame and push it into
  // the atomistic/surface renderer (display-state only, never topology).
  let _align = true          // last align flag from displayJob (relaxed only)
  // Composite scope of the loaded trajectory: 'lineage' (sparse, whole ancestor chain)
  // or 'job' (full, this job's own frames only).  Every heavy per-frame fetch must repeat
  // it — frame indices only mean the same thing within one scope.
  let _trajScope = 'lineage'
  // Frame INTERVAL the loaded trajectory was built with (MD only — every Nth frame of each
  // segment).  undefined = the backend's own default budget.  Same rule as _trajScope: a
  // frame index only means the same thing within one interval.
  let _trajStride
  // Serial span of the job's heavy-atom set (from the topology fetch) — sizes one cached
  // coordinate frame, hence how many the prebuild budget affords. 0 = not known yet.
  let _atomSerials = 0
  // Byte ceiling for ALL cached atomistic frames. Narrowed by the panel to what this
  // machine can actually spare (free RAM / browser heap); the constant is the fallback.
  let _atomBudget = _ATOM_PREBUILD_BUDGET_BYTES
  // Does this backend amortize its per-request setup across a batch of frame indices?
  // MD does (one context build serves the whole call); oxDNA rebuilds each frame
  // independently and is deliberately fetched one at a time.
  const _heavyBatch = api?.heavyBatch === true
  let _frameIdx = 0          // current trajectory frame (for re-apply on rep change)
  let _granularity = 'coarse'  // 'coarse' = downsample+snap | 'fine' = exact frame
  let _playing = false       // play loop running → force coarse (every frame must be instant)
  let _prebuildToken = 0     // bumped to cancel an in-flight prebuildHeavy
  let _heavyActive = false   // a heavy overlay is up → restore design reps on stop
  // A second monotonic token: bumped on every heavy apply so only the LATEST
  // reconstruction (rapid scrub / rep toggle) wins — out-of-order fetches bail.
  let _heavyToken = 0
  // Per-job coarse bakes: {keys:[idx…], byIdx:Map<idx,data>}. Cleared on job
  // switch / granularity flip / stop.
  let _bakedAtom = null
  let _bakedSurf = null
  // Bytes one surface frame's vertex array costs, learned from the first one fetched.
  // 0 = unknown, in which case the grid falls back to the fixed _COARSE_SURF_CAP.
  let _surfFrameBytes = 0
  // jobId whose atomistic ATOMS/BONDS the renderer currently holds.  The relaxed
  // positions are serial-indexed against the JOB's design snapshot, which can differ
  // from the design now loaded in the app (edited after the job ran) — applying them
  // onto the active-design atoms maps every serial to the wrong atom (scrambled
  // colours/bonds/positions).  So before overlaying any oxDNA atomistic frame we
  // REBUILD the renderer from the job's own atomistic model (once per job).
  let _atomTopoJob = null
  // Topology fetched (bundle atoms+bonds) but NOT yet painted — held so the native mesh
  // rebuild and the relaxed applyPositionLerp happen in one tick (no native-position flash).
  let _pendingTopoModel = null
  let _pendingTopoJob = null   // job _pendingTopoModel was fetched for (legacy path sets no descriptor)
  // Whether the held/applied topology carries its bond list. VDW fetches without bonds;
  // a later flip to ball-and-stick must re-fetch rather than draw sticks-less atoms.
  let _atomTopoBonds = false
  // Fast CG→atomistic path: the design-fixed stamp descriptor (atom_nuc / atom_local /
  // nonrigid_serials), fetched once per job.  Lets the relaxed atomistic frame ship as
  // per-nucleotide (origin,R) + a small non-rigid set and be expanded client-side
  // (scene/atomistic_stamp.js) instead of a slow all-atom rebuild + serialise.  Absent
  // on the MD adapter (no stamp endpoints) → that path falls through to the legacy route.
  let _stampDesc    = null   // last fetched descriptor payload
  let _stampDescJob = null   // job the descriptor belongs to
  // Flexibility-map cache + scale, KEPT across toggle-off so re-toggling the same
  // job shows the already-computed map instantly (no recompute).  _rmsfBounds is the
  // active RMSF colour scale shared by beads + atomistic + surface (null = data
  // min→max).  _lastSurfRmsf holds the active flex-surface per-vertex RMSF so the
  // scale widget can recolour the mesh without a re-fetch.
  let _rmsfCache = null     // {jobId, resp}
  let _rmsfBounds = null    // {lo,hi} | null
  let _lastSurfRmsf = null  // number[] | null

  function _repKind() { return repKind(getCurrentRepr?.()) }

  /** Active RMSF colour scale: the user's widget range, else the design's full range. */
  function _activeBounds() {
    if (_rmsfBounds) return _rmsfBounds
    const lo = Number.isFinite(_rmsfResp?.min_rmsf) ? _rmsfResp.min_rmsf : 0
    const hi = Number.isFinite(_rmsfResp?.max_rmsf) ? _rmsfResp.max_rmsf : 0
    return { lo, hi }
  }

  /** FETCH (not render) the JOB's topology (atoms+bonds) + stamp descriptor so the
   *  relaxed positions line up serial-for-serial.  Prefers the COMBINED display bundle
   *  (topology + stamp descriptor, ONE disk-cached build) and caches the descriptor as
   *  a side effect; falls back to the legacy atomistic-model route (and, for the MD
   *  adapter which has neither, becomes a no-op → heavy rep stays off as before).
   *  Returns false if it could not.
   *
   *  IMPORTANT: this NO LONGER calls ar.update().  Painting the renderer at the bundle's
   *  NATIVE positions here — then awaiting the multi-second relaxed-frame build before
   *  moving the atoms — is exactly the "atomistic redraws at native, extra bases jump to
   *  their original spots, THEN the sim positions load" flash.  The render is deferred to
   *  `_applyJobTopology`, which the caller runs in the SAME synchronous tick as
   *  applyPositionLerp, so the native rebuild is overwritten before the browser paints. */
  async function _ensureJobAtomistic(ar, epoch) {
    // VDW draws spheres only — skip the bond list (megabytes of pairs it never reads).
    // If the user later flips vdw→ballstick we DO need them, so a bond-less hold does
    // not satisfy a bonds-needed call: re-fetch and re-apply rather than render
    // ball-and-stick with no sticks.
    const needBonds = ar?.getMode?.() !== 'vdw'
    const haveBonds = !needBonds || _atomTopoBonds
    if (_atomTopoJob === _jobId && haveBonds) return true   // already applied for this job
    if (_pendingTopoModel && _pendingTopoJob === _jobId && haveBonds) return true   // already fetched
    // FASTEST: the columnar/binary bundle — ~7× smaller than the JSON one AND it decodes
    // into typed-array views instead of ~330k JavaScript objects, which is where the
    // multi-second stall actually lived. Carries bonds unconditionally (only ~3 MB packed),
    // so it satisfies both reps in one fetch. Null → older server / unpackable → JSON below.
    if (typeof api.getOxdnaAtomisticDisplayBundleBin === 'function') {
      const buf = await api.getOxdnaAtomisticDisplayBundleBin(_jobId).catch(() => null)
      if (epoch !== _epoch) return false
      const c = parseAtomisticBundleBin(buf)
      if (c) {
        _pendingTopoModel = c        // the renderer AND the stamp expansion read it directly
        _pendingTopoJob = _jobId
        _stampDesc = c; _stampDescJob = _jobId
        _atomTopoBonds = true
        _atomTopoJob = null          // differs from whatever the renderer holds → re-apply
        return true
      }
    }
    let model = null
    if (typeof api.getOxdnaAtomisticDisplayBundle === 'function') {
      const b = await api.getOxdnaAtomisticDisplayBundle(_jobId, { bonds: needBonds }).catch(() => null)
      if (epoch !== _epoch) return false
      if (b?.atoms?.length) {
        model = b
        if (Array.isArray(b.atom_nuc)) { _stampDesc = b; _stampDescJob = _jobId }   // descriptor rides along
      }
    }
    if (!model && typeof api.getOxdnaAtomisticModel === 'function') {
      model = await api.getOxdnaAtomisticModel(_jobId)
      if (epoch !== _epoch) return false
    }
    if (!model?.atoms?.length) return false
    // Serial span sizes one cached coordinate frame → how many the prebuild can afford.
    // Only re-grid when it actually changed: an engine that reports none (oxDNA) must not
    // have its already-cached frames thrown away by a topology re-fetch.
    const nSer = Number(model.n_serials) || 0
    if (nSer !== _atomSerials) { _atomSerials = nSer; _bakedAtom = null }
    _pendingTopoModel = { atoms: model.atoms, bonds: model.bonds || [] }   // hold, don't paint
    _pendingTopoJob = _jobId
    // A source that DECLARES it has no bonds (NAMD renders its atoms unbonded) already
    // gave us everything there is, so a later vdw→ballstick flip must not trigger a
    // "fetch the bonds" round trip that would re-do a ~30 s reconstruction for nothing.
    // Note this is an explicit declaration, NOT an empty bond list: oxDNA's VDW fetch
    // also comes back bondless, and there the warm-ahead re-fetch is exactly right.
    // ...and a model that ALREADY carries bonds is equally complete, whatever repr asked
    // for it. NAMD's REST model ships sticks unconditionally as of 2026-07-31, so without
    // this clause a vdw→ballstick flip would re-fetch bonds it is already holding.
    _atomTopoBonds = needBonds || model.bonds_available === false
      || (model.bonds?.length > 0)
    _atomTopoJob = null    // this model differs from whatever the renderer holds → re-apply it
    return true
  }

  /** Apply the fetched topology to the renderer (ar.update = native mesh rebuild).
   *  SYNCHRONOUS by contract: the caller MUST run ar.applyPositionLerp immediately after,
   *  in the same tick with no await between, so the native positions this rebuild lays
   *  down are overwritten before the browser paints a frame (no native flash). */
  function _applyJobTopology(ar) {
    if (_atomTopoJob === _jobId) return true            // renderer already holds this job
    if (!_pendingTopoModel) return false
    ar.update(_pendingTopoModel)
    _atomTopoJob = _jobId
    _heavyActive = true                                 // restore design reps on stop
    return true
  }

  /** Flat all-atom XYZ for the relaxed-display frame, FAST path first: ensure the job
   *  topology + stamp descriptor (one bundle fetch), fetch the compact per-nucleotide
   *  frames, and expand `origin + R·local` client-side; if the stamp path is
   *  unavailable or the topology hash mismatches, fall back to the legacy
   *  /display-atomistic full-flat route.  Epoch/live-guarded by the caller. */
  async function _relaxedAtomisticFlat(epoch, live) {
    const ar = getAtomisticRenderer?.()
    if (ar && ar.getMode?.() !== 'off') await _ensureJobAtomistic(ar, epoch)   // topology + descriptor
    if (!live()) return null
    const desc = (_stampDescJob === _jobId) ? _stampDesc : null
    if (desc && typeof api.getOxdnaDisplayAtomisticFrames === 'function') {
      const fr = await api.getOxdnaDisplayAtomisticFrames(_jobId, _align)
      if (!live()) return null
      if (fr?.ready && stampTopologyMatches(desc, fr)) {
        const flat = expandStampFrames(desc, fr)
        if (flat) return flat            // ChimeraX-speed: no per-atom network payload
      }
    }
    const r = await api.getOxdnaDisplayAtomistic(_jobId, _align)   // legacy fallback
    return (live() && r?.ready) ? r.atomistic : null
  }

  // ── Heavy-payload memo (relaxed + RMSF) ─────────────────────────────────────────
  // Trajectory frames are already cached per grid cell (bake.byIdx); relaxed and RMSF
  // were not, and a representation change re-runs _applyHeavy.  So flipping F6<->F7 —
  // vdw to ball-and-stick, which changes the renderer's GEOMETRY and not one coordinate
  // — re-downloaded the entire all-atom payload (megabytes) every press.  There is
  // exactly one payload per (job, align, mode, kind), so memo it.
  //
  // Keyed by job+align, and dropped wholesale when the job changes, so the map holds at
  // most one job's worth.  What it must NOT survive is data that can have MOVED under it:
  // a running job accumulates production frames, which is what refresh() exists for —
  // that clears the memo explicitly.
  let _heavyMemo = new Map()
  let _heavyMemoJob = null
  async function _memoHeavy(kind, produce) {
    if (_heavyMemoJob !== _jobId) { _heavyMemo.clear(); _heavyMemoJob = _jobId }
    const key = `${_align}|${_mode}|${kind}`
    if (_heavyMemo.has(key)) return _heavyMemo.get(key)
    const v = await produce()
    if (v) _heavyMemo.set(key, v)   // never cache a null/superseded result
    return v
  }

  /**
   * Is a relaxed/RMSF re-apply going to be INSTANT — i.e. can the spinner be skipped?
   *
   * The memo is necessary but NOT sufficient: `_pushAtomistic` also needs the job topology
   * in the renderer, and vdw→ballstick deliberately does not accept a bond-less hold
   * (`_ensureJobAtomistic`), so that exact flip re-fetches the bundle even with the
   * coordinates already in hand.  Answering on the memo alone would have made the one
   * switch most likely to be slow the one switch with no indicator.
   */
  function _heavyWarm(kind) {
    if (_heavyMemoJob !== _jobId) return false
    if (!_heavyMemo.has(`${_align}|${_mode}|${kind}`)) return false
    if (kind !== 'atomistic') return true
    const ar = getAtomisticRenderer?.()
    const needBonds = ar?.getMode?.() !== 'vdw'
    return _atomTopoJob === _jobId && (!needBonds || _atomTopoBonds)
  }

  async function _pushAtomistic(arr, epoch, live, colorByKey = null) {
    const ar = getAtomisticRenderer?.()
    // arr may be a plain Array (legacy flat route) OR a Float32Array (fast stamp
    // expansion) — accept both array-likes, reject only null/empty.
    if (!ar || ar.getMode?.() === 'off' || !arr || !arr.length) return
    if (!(await _ensureJobAtomistic(ar, epoch))) return   // FETCH topology (no paint)
    if (live && !live()) return
    // Render native + relax in ONE synchronous tick — the native rebuild is overwritten
    // before the browser paints, so the atoms appear directly at their simulated positions.
    _applyJobTopology(ar)
    ar.applyPositionLerp(arr, arr, 0, null, [], null)
    // Flexibility map → recolour atoms by RMSF; any other mode → drop the overlay.
    if (colorByKey) ar.applyScalarColors?.(colorByKey)
    else ar.clearScalarColors?.()
    _heavyActive = true
    onHeavyApplied()   // atoms are live → the caller can now hide the CG model (no flash)
    _warmBonds()       // VDW skipped the bonds → fetch them off the critical path
  }

  /** VDW painted without bonds. Pull them in the background so a later flip to
   *  ball-and-stick repaints from the held model instead of stalling on a re-fetch.
   *  Fire-and-forget; the renderer is NOT touched (VDW ignores bonds anyway) — clearing
   *  _atomTopoJob just tells _applyJobTopology to repaint on the next push. */
  let _bondWarmJob = null
  function _warmBonds() {
    if (_atomTopoBonds || !_jobId || _bondWarmJob === _jobId) return
    if (typeof api.getOxdnaAtomisticDisplayBundle !== 'function') return
    const jobId = _bondWarmJob = _jobId
    api.getOxdnaAtomisticDisplayBundle(jobId, { bonds: true }).then((b) => {
      if (jobId !== _jobId || !b?.atoms?.length) return
      _pendingTopoModel = { atoms: b.atoms, bonds: b.bonds || [] }
      _pendingTopoJob = jobId
      _atomTopoBonds = true
      _atomTopoJob = null      // next push repaints (with bonds) in its usual single tick
    }).catch(() => { if (_bondWarmJob === jobId) _bondWarmJob = null })   // allow a retry
  }

  function _pushSurface(data, rmsf = false) {
    const sr = getSurfaceRenderer?.()
    if (!sr || sr.getMode?.() === 'off' || !data?.vertices?.length) return
    if (rmsf && Array.isArray(data.vertex_rmsf)) {
      const { lo, hi } = _activeBounds()
      data.vertex_colors = rmsfToVertexColors(data.vertex_rmsf, lo, hi, _rmsfCmap)
      data.scalar = true                 // force the scalar colours through any colour mode
      _lastSurfRmsf = data.vertex_rmsf   // cache for live scale recolour
    } else {
      _lastSurfRmsf = null
    }
    sr.applyPositionLerp(data, data, 0)
    _heavyActive = true
    onHeavyApplied()   // surface is live → caller can hide the CG model (no native flash)
  }

  /** Relaxed-display surface mesh, BINARY path first (compact + no million-number
   *  JSON.parse); falls back to the legacy JSON route when the binary endpoint is absent
   *  (e.g. the MD viz adapter) or returns nothing. */
  async function _relaxedSurfaceMesh(live) {
    const params = getSurfaceParams() || {}   // sidebar probe radius / colour mode
    if (typeof api.getOxdnaDisplaySurfaceBin === 'function') {
      const buf = await api.getOxdnaDisplaySurfaceBin(_jobId, _align, params)
      if (!live()) return null
      const mesh = parseSurfaceBin(buf)
      if (mesh) return mesh
    }
    const r = await api.getOxdnaDisplaySurface(_jobId, _align, params)
    return (live() && r?.ready) ? r.surface : null
  }

  // Heavy reconstruction is slow (one all-atom rebuild per frame). Announce when one
  // is in flight so the panel can show a "building…" spinner instead of looking frozen.
  function _setHeavyBusy(building, kind) {
    onHeavyStatus?.({ building, kind, mode: _mode })
  }

  // Which api route _applyHeavy would call for (current mode, kind). One table, read by
  // both the capability check and nothing else — keep it in step with _applyHeavy's tree.
  const _HEAVY_ROUTE = {
    relaxed:    { atomistic: 'getOxdnaDisplayAtomistic', surface: 'getOxdnaDisplaySurface' },
    rmsf:       { atomistic: 'getOxdnaRmsfAtomistic',    surface: 'getOxdnaRmsfSurface' },
    trajectory: { atomistic: 'getOxdnaFramesAtomistic',  surface: 'getOxdnaFramesSurface' },
  }

  /**
   * Can this controller actually PRODUCE `kind` ('atomistic'|'surface') in its current
   * mode?  The injected `api` is the authority, not the engine name: md_viz_adapter maps
   * the trajectory heavy routes but deliberately NOT the flexibility-map ones, so a NAMD
   * RMSF view can deliver neither.  Asking the api directly means a route added to the
   * adapter later starts working with no change here.
   *
   * This is what stops the caller deferring the design's heavy build to an overlay that
   * will never deliver — which would leave a blank surface / empty atoms on screen.
   */
  function _canDeliverHeavy(kind) {
    const route = _HEAVY_ROUTE[_mode]?.[kind]
    return !!route && typeof api?.[route] === 'function'
  }

  /** Ensure the coarse snap-grid for the active trajectory job is DEFINED for `kind`
   *  (cheap — just the index list; frames are fetched lazily on visit). Returns the
   *  bake object {grid:[idx…], byIdx:Map<idx,data>} or null. */
  function _ensureGrid(kind) {
    const n = _traj?.n_frames || _traj?.frames?.length || 0
    if (n <= 0) return null
    if (kind === 'atomistic') {
      if (!_bakedAtom) {
        // With a coordinates-only stream the grid is bounded by MEMORY, not by how long
        // one reconstruction takes — so ask for every frame the budget allows instead of
        // the fixed 12-cell compromise. `capped` drives the panel's honesty about it.
        const cap = _atomSerials > 0
          ? affordableAtomFrames(_atomSerials, n, _atomBudget)
          : _COARSE_ATOM_CAP
        _bakedAtom = {
          grid: strideIndices(0, n - 1, cap), byIdx: new Map(),
          cap, capped: cap < n, total: n,
        }
      }
      return _bakedAtom
    }
    if (!_bakedSurf) {
      // Same reasoning as the atomistic grid above, which the surface one never got:
      // the bound is MEMORY, not reconstruction time, so ask for as many frames as the
      // budget allows rather than a fixed 8-cell compromise. Until one frame has been
      // fetched we don't know what a mesh costs, so start at the old fixed cap and
      // re-grid once `_surfFrameBytes` is known (see `_noteSurfFrameBytes`).
      //
      // This is what made a 501-frame trajectory export as EIGHT distinct surface
      // shapes: the CG beads moved every frame, the surface snapped to the nearest of
      // 8 grid cells, and nothing said so.
      const cap = _surfFrameBytes > 0
        ? affordableAtomFrames(_surfFrameBytes / 12, n, _surfBudget())
        : _COARSE_SURF_CAP
      _bakedSurf = {
        grid: strideIndices(0, n - 1, cap), byIdx: new Map(),
        cap, capped: cap < n, total: n,
      }
    }
    return _bakedSurf
  }

  /** Budget for the SURFACE bake. Shares the caller-supplied prebuild budget with the
   *  atomistic bake — only one heavy rep is visible at a time, so they never both hold
   *  a full trajectory. */
  function _surfBudget() { return _atomBudget }

  /**
   * Learn what one surface frame costs, from the first one that arrives, and re-grid if
   * the budget now affords materially more frames.
   *
   * Re-gridding keeps every frame already fetched: `strideIndices` is a superset walk
   * (a denser grid over the same span re-includes the old endpoints only when they line
   * up), so entries are carried across by index rather than assumed.
   */
  function _noteSurfFrameBytes(data) {
    if (_surfFrameBytes > 0 || !data) return
    const len = data?.length ?? data?.vertices?.length ?? 0
    if (!(len > 0)) return
    _surfFrameBytes = len * 4          // Float32 per component after _narrowFrame
    const n = _traj?.n_frames || _traj?.frames?.length || 0
    if (!_bakedSurf || n <= 0) return
    const cap = affordableAtomFrames(_surfFrameBytes / 12, n, _surfBudget())
    if (cap <= _bakedSurf.cap) return  // no better than what we already have
    const kept = _bakedSurf.byIdx
    _bakedSurf = {
      grid: strideIndices(0, n - 1, cap),
      byIdx: new Map([...kept].filter(([g]) => g >= 0)),
      cap, capped: cap < n, total: n,
    }
  }

  /** Lazily fetch + cache ONE coarse-grid frame's heavy data. One network rebuild per
   *  distinct grid cell (then served from cache on revisits). Epoch-guarded. */
  /** Flat coordinate arrays arrive as plain JS number arrays (8 B/element). Holding a
   *  whole trajectory that way costs twice what it needs to, so narrow to Float32 —
   *  ~5e-5 nm resolution at origami scale, far below anything drawable. Meshes/objects
   *  pass through untouched. */
  function _narrowFrame(data) {
    if (!Array.isArray(data)) return data
    return Float32Array.from(data)
  }

  /** Fetch + cache heavy data for MANY grid cells in ONE request.
   *
   *  One request per frame is what made this slow: the MD analysis rebuilds its context
   *  (PSF parse + model) per CALL — ~32 s on a 300 k-atom system against ~2.8 s per
   *  extra frame — so N separate fetches paid that N times. Epoch-guarded. */
  // Serialises heavy frame fetches for THIS controller. The MD backend treats
  // (job_id, kind) as a single-slot resource: `md_analysis_runner.run_analysis` starts by
  // KILLING any in-flight analysis for the same key, so a second overlapping request does
  // not queue behind the first — it murders it, and the victim returns 500 ("analysis
  // worker died without a result").
  //
  // Two of our own callers legitimately want frames at the same moment: `prebuildHeavy`'s
  // chunk loop and `_applyHeavy`'s single-frame fetch for whatever the user is looking at.
  // Overlap them and the prebuild chunk dies mid-play, which is what put a 500 in the
  // console and stalled the play button on ⏳ for seconds before the loop recovered.
  //
  // A queue, not a drop: both callers are already epoch/token-guarded, so anything that
  // became irrelevant while it waited re-checks and bails cheaply on its own. Superseding
  // stays the BACKEND's job for a genuinely new intent (a view toggled off aborts its
  // fetch); it must not be triggered by this controller racing itself.
  let _frameFetchQueue = Promise.resolve()
  function _queueFrameFetch(fn) {
    const run = _frameFetchQueue.then(fn, fn)
    // Keep the chain alive after a rejection, but let the caller see the error.
    _frameFetchQueue = run.then(() => {}, () => {})
    return run
  }

  const _bakeFor = (kind) => (kind === 'atomistic' ? _bakedAtom : _bakedSurf)

  async function _coarseFrames(kind, gridIdxs, epoch) {
    if (!gridIdxs.some((g) => !_bakeFor(kind)?.byIdx.has(g))) return
    return _queueFrameFetch(async () => {
      // Re-read the bake and re-filter INSIDE the queue. Both can move while we wait: the
      // other caller may have fetched exactly these cells (re-asking would be a pointless
      // round trip), and a re-grid may have REPLACED the bake object entirely — writing
      // results into the one captured on entry would drop them into an orphan.
      const bake = _bakeFor(kind)
      if (!bake || epoch !== _epoch) return
      const want = gridIdxs.filter((g) => !bake.byIdx.has(g))
      if (!want.length) return
      // _trajStride is repeated on every heavy fetch for the same reason _trajScope is:
      // a composite frame index only addresses the same frame within one interval.
      const resp = kind === 'atomistic'
        ? await api.getOxdnaFramesAtomistic(_jobId, want, _align, _trajScope, _trajStride)
        : await api.getOxdnaFramesSurface(_jobId, want, { stride: _trajStride }, _align, _trajScope)
      if (epoch !== _epoch) return
      let first = null
      for (const g of want) {
        const data = resp?.[String(g)]
        if (!data) continue
        const narrowed = _narrowFrame(data)
        bake.byIdx.set(g, narrowed)
        if (first === null) first = narrowed
      }
      // AFTER the writes, never inside the loop: learning the frame size can re-grid,
      // which REPLACES `_bakedSurf`, and the remaining writes would then land in an
      // orphaned bake (the same hazard this function's header warns about). The re-grid
      // carries `bake.byIdx` across, so everything just written survives.
      if (kind === 'surface' && first !== null) _noteSurfFrameBytes(first)
    })
  }

  async function _coarseFrame(kind, gridIdx, epoch) {
    const bake = kind === 'atomistic' ? _bakedAtom : _bakedSurf
    if (bake.byIdx.has(gridIdx)) return bake.byIdx.get(gridIdx)
    await _coarseFrames(kind, [gridIdx], epoch)
    if (epoch !== _epoch) return null
    return bake.byIdx.get(gridIdx) || null
  }

  /** Mark playback on/off. While on, the heavy path forces coarse (every played frame
   *  must hit a cached grid cell), and turning it off cancels an in-flight prebuild. */
  function setPlaying(on) {
    _playing = !!on
    if (!on) _prebuildToken++   // stop prebuildHeavy if it's still grinding
  }

  /** Pre-build EVERY coarse playback frame for the active heavy rep so the play loop
   *  runs smoothly instead of stalling one slow rebuild at a time. No-op for CG (frames
   *  are instant). Reports progress via onProgress(done, total). The first cell is built
   *  alone (warms the server-side alignment cache), then the rest a few at a time so a
   *  dozen all-atom rebuilds overlap. Returns {ok, n}; ok=false if cancelled. */
  async function prebuildHeavy(onProgress, { budgetBytes = null } = {}) {
    if (_mode !== 'trajectory') return { ok: true, n: 0 }
    // The caller may narrow the budget to what THIS machine can spare (it is the one
    // that talks to the user about it); the built-in constant is the fallback ceiling.
    //
    // QUANTISED first: the caller reads MemAvailable, which moves constantly, and an
    // unrounded budget makes the affordable-frame count jitter by a frame or two between
    // otherwise identical calls — enough to resize the grid and refetch. Rounding down to
    // a whole quantum makes the budget a stable function of "roughly how much RAM is
    // free", which is all the precision this decision ever had.
    if (Number.isFinite(budgetBytes) && budgetBytes > 0) {
      budgetBytes = Math.max(_BUDGET_QUANTUM,
                             Math.floor(budgetBytes / _BUDGET_QUANTUM) * _BUDGET_QUANTUM)
    }
    if (Number.isFinite(budgetBytes) && budgetBytes > 0 && budgetBytes !== _atomBudget) {
      _atomBudget = budgetBytes
      // Re-grid ONLY when the new ceiling actually changes how many frames fit.
      //
      // Hardening, not an observed failure: the previous `budgetBytes !== _atomBudget`
      // test compared RAW BYTES derived from the host's MemAvailable, so any wobble in
      // free memory discarded the whole bake — and with it every already-fetched frame,
      // which the MD jobs panel's `nadoc:representation-change` prebuild would then
      // re-download. Dropping correct megabytes because free RAM moved is never right;
      // the only thing that justifies a re-grid is a different NUMBER of frames.
      const n = _traj?.n_frames || _traj?.frames?.length || 0
      const nextCap = _atomSerials > 0 && n > 0
        ? affordableAtomFrames(_atomSerials, n, budgetBytes)
        : null
      if (!_bakedAtom || nextCap === null || nextCap !== _bakedAtom.cap) _bakedAtom = null
      // Same test for the surface grid, which shares the budget. Only a different
      // NUMBER of frames justifies discarding fetched meshes (see the note above).
      const nextSurf = _surfFrameBytes > 0 && n > 0
        ? affordableAtomFrames(_surfFrameBytes / 12, n, budgetBytes)
        : null
      if (_bakedSurf && nextSurf !== null && nextSurf !== _bakedSurf.cap) _bakedSurf = null
    }
    const kind = _repKind()
    if (kind === 'cg') return { ok: true, n: 0 }   // CG plays instantly — nothing to bake
    // Size the grid BEFORE building it: how many frames fit the budget depends on the
    // structure's serial span, which only the topology fetch knows. Without this the
    // grid would be built at the fallback 12 and the prebuild would silently under-fill.
    if (kind === 'atomistic') {
      const ar = getAtomisticRenderer?.()
      if (ar && ar.getMode?.() !== 'off') await _ensureJobAtomistic(ar, _epoch)
    }
    // For SURFACE the grid size depends on what one mesh costs, which is only known
    // once a mesh has arrived. Fetch cell 0 first so `_noteSurfFrameBytes` can re-grid,
    // then read the grid — otherwise the prebuild plans against the blind fallback of 8
    // cells and every frame beyond them is left to a one-at-a-time lazy fetch.
    if (kind === 'surface' && _surfFrameBytes === 0) {
      const seed = _ensureGrid(kind)
      if (seed?.grid?.length) await _coarseFrame(kind, seed.grid[0], _epoch)
    }
    const bake = _ensureGrid(kind)
    if (!bake || !bake.grid.length) return { ok: false, n: 0 }
    const epoch = _epoch
    const token = ++_prebuildToken
    const live = () => epoch === _epoch && token === _prebuildToken
    const total = bake.grid.length
    let done = bake.grid.filter((g) => bake.byIdx.has(g)).length
    onProgress?.(done, total)
    const todo = bake.grid.filter((g) => !bake.byIdx.has(g))
    // Warming one cell alone first pays off only when the per-request setup is CACHED
    // server-side for the requests that follow (oxDNA's alignment cache). On the batching
    // backend that setup is per-call and not cached, so a lone warm-up frame is a whole
    // extra context build — precisely the cost this is meant to avoid.
    if (todo.length && !_heavyBatch) {
      await _coarseFrame(kind, todo[0], epoch)
      if (!live()) return { ok: false, n: total }
      done++; onProgress?.(done, total)
    }
    const rest = _heavyBatch ? todo : todo.slice(1)
    if (_heavyBatch) {
      // Only where the backend amortizes its per-CALL setup across the batch (MD: the
      // analysis context is a ~30 s PSF parse + model build, against ~0.2 s per extra
      // frame in the same call). oxDNA reconstructs each frame independently, so
      // batching there would just trade many short waits for one long one — hence the
      // capability flag rather than a blanket change.
      //
      // Chunks are ordered by distance from the PLAYHEAD and re-sorted between chunks,
      // so the frames around where the user is actually looking arrive first and a seek
      // mid-build redirects the remaining work — the "buffer from here" behaviour, as
      // close as this backend allows. The fixed per-request cost is why the chunk is
      // large: every extra chunk is another whole context build.
      const CHUNK = 32
      let queue = rest.slice()
      while (queue.length && live()) {
        queue.sort((a, b) => Math.abs(a - _frameIdx) - Math.abs(b - _frameIdx))
        const chunk = queue.slice(0, CHUNK)
        queue = queue.slice(CHUNK)
        await _coarseFrames(kind, chunk, epoch)
        if (live()) { done += chunk.length; onProgress?.(done, total) }
      }
    } else {
      let next = 0
      const worker = async () => {
        while (next < rest.length && live()) {
          const g = rest[next++]
          await _coarseFrame(kind, g, epoch)
          if (live()) { done++; onProgress?.(done, total) }
        }
      }
      await Promise.all(Array.from({ length: Math.min(3, rest.length) }, worker))
    }
    return { ok: live(), n: total, capped: !!bake.capped, cap: bake.cap,
             frames: bake.grid.length, trajFrames: bake.total ?? total }
  }

  /** Reconstruct + apply the heavy rep for the CURRENT mode/frame (no-op in CG).
   *  Token-guarded: only the newest call applies, so rapid scrubbing / rep flips
   *  never paint a stale frame. */
  async function _applyHeavy() {
    if (!_active || !_jobId) return
    const kind = _repKind()
    if (kind === 'cg') return
    // Keep the capability guard explicit: an engine/mode added without its matching
    // heavy endpoint must never silently leave the design's equilibrium atoms on screen.
    if (!_canDeliverHeavy(kind)) {
      onHeavyStatus?.({ building: false, kind, mode: _mode, unsupported: true })
      return
    }
    const epoch = _epoch
    const token = ++_heavyToken
    const live = () => epoch === _epoch && token === _heavyToken
    // During playback, force coarse even if the dropdown says fine — a fine rebuild per
    // tick (~seconds each) would stall the loop; play steps the pre-built coarse frames.
    const useFine = _granularity === 'fine' && !_playing
    // Skip the spinner only when the payload is already in hand (instant): a cached
    // trajectory grid cell, or a memoised relaxed/RMSF payload.
    let busy = true
    if (_mode === 'trajectory' && !useFine) {
      const bake = _ensureGrid(kind)
      const g = bake ? nearestOf(bake.grid, _frameIdx) : null
      busy = !(bake && g != null && bake.byIdx.has(g))
    } else if (_mode === 'relaxed' || _mode === 'rmsf') {
      busy = !_heavyWarm(kind)
    }
    if (busy) _setHeavyBusy(true, kind)
    try {
      if (_mode === 'relaxed') {
        if (kind === 'atomistic') {
          const flat = await _memoHeavy(kind, () => _relaxedAtomisticFlat(epoch, live))
          if (live() && flat) await _pushAtomistic(flat, epoch, live)
        } else {
          const mesh = await _memoHeavy(kind, () => _relaxedSurfaceMesh(live))
          if (live() && mesh) _pushSurface(mesh)
        }
      } else if (_mode === 'rmsf') {
        if (kind === 'atomistic') {
          const r = await _memoHeavy(kind,
            () => api.getOxdnaRmsfAtomistic(_jobId, { align: _align }))
          if (live() && r?.ready) {
            const { lo, hi } = _activeBounds()
            const m = rmsfColorMap(_rmsfResp, lo, hi, _rmsfCmap)   // same ramp/scale as the beads
            await _pushAtomistic(r.atomistic, epoch, live, m?.colorByKey || null)
          }
        } else {
          const r = await _memoHeavy(kind,
            () => api.getOxdnaRmsfSurface(_jobId, {}, { align: _align }))
          if (live() && r?.ready) _pushSurface(r.surface, true)   // colour by per-vertex RMSF
        }
      } else if (_mode === 'trajectory') {
        const idx = _frameIdx
        if (useFine) {
          if (kind === 'atomistic') {
            const r = await api.getOxdnaFramesAtomistic(_jobId, [idx], _align, _trajScope, _trajStride)
            if (live()) await _pushAtomistic(r?.[String(idx)], epoch, live)
          } else {
            const r = await api.getOxdnaFramesSurface(_jobId, [idx], { stride: _trajStride }, _align, _trajScope)
            if (live()) _pushSurface(r?.[String(idx)])
          }
        } else {
          const bake = _ensureGrid(kind)
          if (!bake || !bake.grid.length) return
          const g = nearestOf(bake.grid, idx)
          if (g == null) return
          const data = await _coarseFrame(kind, g, epoch)   // cached → instant; else one rebuild
          if (!live() || !data) return
          if (kind === 'atomistic') await _pushAtomistic(data, epoch, live); else _pushSurface(data)
        }
      }
    } catch { /* transient fetch failure → leave heavy rep as-is */
    } finally { if (busy && live()) _setHeavyBusy(false, kind) }
  }

  /**
   * Hand the heavy rep back to the DESIGN without discarding this job's caches.
   *
   * For a caller that INTERLEAVES job frames with design frames — the animation player,
   * whose keyframes mix trajectory segments with feature-log segments. `stopAndRestore()`
   * is wrong there: it throws away the trajectory and every prebuilt frame, so the next
   * trajectory keyframe re-downloads the lot. Doing nothing is also wrong: the renderer
   * holds the JOB's atom set, and design coordinates written onto it map every serial to
   * the wrong atom once the design has been edited since the job ran.
   *
   * So: restore the design's heavy rep and forget which topology is PAINTED, but keep the
   * fetched topology held (`_pendingTopoModel`) and both frame bakes. The next job frame
   * repaints from the held model in its usual single tick — no refetch, no flash.
   */
  function releaseHeavyToDesign() {
    if (!_heavyActive && _atomTopoJob === null) return
    getAtomisticRenderer?.()?.clearScalarColors?.()
    onRestoreDesignHeavy?.()
    _heavyActive = false
    _atomTopoJob = null
  }

  /**
   * Restore the DESIGN display but KEEP this job's trajectory and frame bakes.
   *
   * `stopAndRestore()` is the "done with this job" teardown: it drops `_traj`, both
   * coarse bakes and the held topology, so coming back costs the whole download again —
   * on a 16 k-nt origami that is a 370 MB composite trajectory. The animation player
   * stops SHOWING a trajectory every time playback ends but is not done with it (the
   * user presses Play again), which is exactly the case this exists for.
   *
   * Pairs with `resumeTrajectory(jobId)`. While suspended the controller reports
   * `isActive() === false`, so the design owns the display and `drivesHeavy()` correctly
   * declines to defer to us; `mode()`/`activeJobId()` still name what is held.
   *
   * Memory: one job's trajectory stays resident, the same as leaving the panel's
   * trajectory view open. A job switch or `stopAndRestore()` frees it.
   */
  function suspendToDesign() {
    if (!_active) return
    _heavyToken++       // and any in-flight heavy reconstruction
    _prebuildToken++    // and any in-flight playback prebuild
    _playing = false
    _setHeavyBusy(false, null)
    _active = false     // BEFORE the restore, same ordering reason as stopAndRestore
    designRenderer?.clearScalarColors?.()
    onOccupancyClear?.()
    _applyFem(null)
    onSurfaceStrands?.(null)
    proteinRenderer?.clearOxdnaTransforms?.()
    releaseHeavyToDesign()
    // KEPT: _traj, _jobId, _mode, _bakedAtom, _bakedSurf, _pendingTopoModel, _atomSerials.
  }

  /** Re-activate a trajectory suspended by `suspendToDesign()` and show its last frame.
   *  False when this controller isn't holding that job — the caller must load it.
   *
   *  `spec` (optional `{scope, stride}`) is the RESOLUTION the caller needs. A frame
   *  index only means the same thing within one resolution, so resuming a job held at a
   *  different scope/stride would silently address other frames — say no and make the
   *  caller reload. Omit it to resume whatever is held (the jobs panels' behaviour). */
  function resumeTrajectory(jobId, spec = null) {
    if (_active || _mode !== 'trajectory' || !_traj || _jobId !== jobId) return false
    if (spec && !trajSpecMatches(spec)) return false
    _active = true
    showFrame(_frameIdx)
    return true
  }

  /** The composite resolution the held trajectory was loaded at. `scope` is the oxDNA
   *  lineage/job distinction; `stride` the MD frame interval (undefined = backend
   *  default). Callers that cache frame INDICES must compare this before reusing. */
  function trajSpec() { return { scope: _trajScope, stride: _trajStride } }

  /** True when the held trajectory's resolution matches `spec`. Fields left undefined on
   *  `spec` are "don't care", so `{scope:'job'}` ignores stride (oxDNA has none). */
  function trajSpecMatches(spec = {}) {
    const norm = (v) => (v == null ? null : v)
    if ('scope'  in spec && norm(spec.scope)  !== norm(_trajScope))  return false
    if ('stride' in spec && norm(spec.stride) !== norm(_trajStride)) return false
    return true
  }

  function _restoreHeavy() {
    // Drop the flex-map overlay BEFORE the design rebuild — otherwise the scalar
    // colours (keyed by helix:bp:dir, which the design's own atoms also match)
    // would repaint the restored design atoms by stale RMSF.
    getAtomisticRenderer?.()?.clearScalarColors?.()
    // Rebuild the design heavy rep unconditionally (self-gates in _restoreDesignHeavy:
    // no-op unless an atomistic/surface mode is on).  NOT gated on _heavyActive — during
    // the deferred-build window the overlay hasn't pushed atoms yet (_heavyActive false)
    // but the heavy rep IS active with the CG showing, so turning off must still restore
    // the DESIGN surface/atoms rather than leave the CG up (rep appearing to revert).
    onRestoreDesignHeavy?.()
    _heavyActive = false
    _bakedAtom = null
    _bakedSurf = null
    _heavyMemo.clear()    // and the relaxed/RMSF payload memo
    _heavyMemoJob = null
    _atomSerials = 0      // next job re-measures its own per-frame cost
    _atomBudget = _ATOM_PREBUILD_BUDGET_BYTES
    _atomTopoJob = null   // next job display rebuilds the renderer from its own topology
    _pendingTopoModel = null   // drop the held (native) model so the next job re-fetches
    _pendingTopoJob = null
    _atomTopoBonds = false
    _bondWarmJob = null
    _stampDescJob = null  // and re-fetches the stamp descriptor for that job
    _lastSurfRmsf = null
  }

  // Warm-ahead: while the user views the CG relaxed structure, build + disk-cache the
  // atomistic topology bundle in the background so a later switch to an atomistic rep is
  // instant instead of paying the cold build on the click. Fire-and-forget, once per job;
  // the server route is idempotent + single-flighted so this never duplicates a real fetch.
  let _warmedBundleJob = null
  function _warmAtomisticBundle(jobId) {
    if (!jobId || jobId === _warmedBundleJob) return
    if (typeof api.getOxdnaAtomisticDisplayBundle !== 'function') return
    _warmedBundleJob = jobId
    // Warm the BINARY route: it builds + disk-caches the JSON bundle AND the packed blob,
    // so the real click pays neither. (The warm's own response is discarded — that's why
    // it's worth warming the cheaper of the two.)
    const warm = (typeof api.getOxdnaAtomisticDisplayBundleBin === 'function')
      ? api.getOxdnaAtomisticDisplayBundleBin(jobId)
      : api.getOxdnaAtomisticDisplayBundle(jobId, { bonds: false })
    Promise.resolve(warm).catch(() => null)
      .then((r) => { if (!r) _warmedBundleJob = null })   // failed → allow a retry later
  }

  /** Fetch the latest relaxed frame for jobId and deform the model to it.
   *  `align` (default true) superposes onto the design pose; false shows the
   *  structure in its own simulation frame (e.g. settled on a hard surface). */
  async function displayJob(jobId, align = true) {
    if (!jobId || !designRenderer) return { ok: false, reason: 'no job' }
    const epoch = ++_epoch
    const signal = _beginLoad()
    const resp = await api.getOxdnaDisplay(jobId, { align, signal })
    if (epoch !== _epoch) return { ok: false, reason: 'superseded' }   // off/newer call won
    const updates = toFemUpdates(resp)
    if (!updates.length) {
      // Switching to a job with no relaxed frame yet: clear any stale overlay left
      // from a previously-displayed job so we don't keep showing its positions.
      if (_active && _jobId !== jobId) {
        _applyFem(null)
        designRenderer.clearScalarColors?.()
        proteinRenderer?.clearOxdnaTransforms?.()
        _active = false; _mode = null; _jobId = null
      }
      onSurfaceStrands?.(null)
      return { ok: false, reason: resp?.ready === false ? 'no relaxed frame yet' : 'empty' }
    }
    designRenderer.clearScalarColors?.()   // leaving a flexibility map → restore bead colours
    // Inject the capture strands FIRST — setExtraNucleotides rebuilds the geometry (which
    // resets origami beads to design positions), so it must run BEFORE the origami FEM move
    // (applyFemPositions moves beads in-place, no rebuild) or the overlay would be clobbered.
    onSurfaceStrands?.(resp.surface_strands || null)   // real strands replace the seed preview
    _surfaceStrandsByJob.set(jobId, resp.surface_strands || null)
    _applyFem(updates)
    // Hybrid (protein) jobs: move each protein to its relaxed pose (design→relaxed
    // rigid 4×4 from the backend); DNA-only jobs send no proteins → clears to design.
    proteinRenderer?.applyOxdnaTransforms?.(proteinTransformMap(resp))
    _active = true
    _mode = 'relaxed'
    _jobId = jobId
    _align = align
    _warmAtomisticBundle(jobId)   // prebuild the atomistic bundle off the click path
    _applyHeavy()   // atomistic/surface follow when the scene is in a heavy rep
    return { ok: true, n: updates.length, stage: resp.stage_name }
  }

  /** Ensure non-relaxed display modes use the REAL job strands, never the setup preview.
   *  setExtraNucleotides rebuilds the CG geometry, so callers MUST await this before _applyFem. */
  async function _applyJobSurfaceStrands(jobId, align, epoch, signal) {
    if (!onSurfaceStrands) return true
    if (_surfaceStrandsByJob.has(jobId)) {
      onSurfaceStrands(_surfaceStrandsByJob.get(jobId))
      return epoch === _epoch
    }
    const display = await api.getOxdnaDisplay(jobId, { align, signal })
    if (epoch !== _epoch) return false
    const strands = display?.surface_strands || null
    _surfaceStrandsByJob.set(jobId, strands)
    onSurfaceStrands(strands)
    return true
  }

  /**
   * Apply an ALREADY-FETCHED live-session frame (a positions payload, same shape
   * as a /display response's `positions`) directly to the model — the ephemeral
   * "Live" oxDNA mode (oxdna_live_controller.js).  No network fetch here: the
   * controller polls /oxdna/live/{id}/frame and hands the positions in, so the
   * bead overlay updates in near real time as the field is steered.  Shares the
   * one bead overlay + epoch with the other modes (mutually exclusive — turning
   * Live on supersedes a relaxed/flex/traj overlay and vice-versa).  Heavy reps
   * (atomistic/surface) are NOT reconstructed for live frames — they need a job's
   * topology model, which an ephemeral session has none of; live is a CG preview.
   * Returns true if a frame was applied.
   */
  function displayLiveFrame(positions) {
    if (!designRenderer || !Array.isArray(positions) || !positions.length) return false
    const updates = toFemUpdates({ ready: true, positions })
    if (!updates.length) return false
    _epoch++   // supersede any in-flight relaxed/flex/traj fetch
    _cancelLoad()
    designRenderer.clearScalarColors?.()
    _applyFem(updates)
    proteinRenderer?.clearOxdnaTransforms?.()
    _active = true
    _mode = 'live'
    _jobId = null
    return true
  }

  /**
   * Fetch the production flexibility map for jobId, deform the model to the
   * average structure, and recolour beads by RMSF (rigid→flexible).
   */
  /**
   * Occupancy clouds: move the design to the MOST POPULATED configuration.
   *
   * This owns only rank 0 — the real model, which alone carries strand colours, hidden
   * staples, rep overrides, crossover arcs and protein poses. The remaining states are
   * translucent ghosts owned by scene/occupancy_overlay.js, which the caller drives with
   * the same response.
   *
   * It must be a `_mode` even though it paints no scalar map: `_mode` is what every peer
   * view's teardown switches on, so a mode-less occupancy display would survive being
   * "turned off" and leave the design stuck on a medoid.
   */
  async function displayOccupancy(jobId, resp) {
    if (!jobId || !designRenderer) return { ok: false, reason: 'no job' }
    if (!resp?.ready) return { ok: false, reason: resp?.reason || 'not ready' }
    const top = resp.clusters?.[0]
    if (!top?.frame?.length || !resp.keys?.length) {
      return { ok: false, reason: 'no configurations' }
    }
    const epoch = ++_epoch
    if (!await _applyJobSurfaceStrands(jobId, true, epoch, null)) {
      return { ok: false, reason: 'superseded' }
    }
    _applyFem(framesToUpdates(resp.keys, top.frame))
    _active = true
    _mode = 'occupancy'
    _jobId = jobId
    // No _applyHeavy(): ghosts are coarse-grained only, and drivesHeavy() already returns
    // false outside relaxed|rmsf|trajectory, so the design's own heavy build proceeds.
    return { ok: true, verdict: resp.verdict, k: resp.k, nClusters: resp.clusters.length }
  }

  async function displayRmsf(jobId, { refetch = false, align = true } = {}) {
    if (!jobId || !designRenderer) return { ok: false, reason: 'no job' }
    const epoch = ++_epoch
    if (refetch) _surfaceStrandsByJob.delete(jobId) // running job may have moved its caps too
    // Re-use the cached flex map for this job (instant re-toggle) unless a refetch
    // is forced (e.g. refresh after more production frames accumulated).
    let resp
    let signal = null
    if (!refetch && _rmsfCache && _rmsfCache.jobId === jobId && _rmsfCache.align === align) {
      resp = _rmsfCache.resp
    } else {
      signal = _beginLoad()
      resp = await api.getOxdnaRmsf(jobId, { align, signal })
      if (epoch !== _epoch) return { ok: false, reason: 'superseded' }
    }
    const map = rmsfColorMap(resp, undefined, undefined, _rmsfCmap)
    if (!map) {
      return { ok: false, reason: resp?.reason || 'not ready' }
    }
    _rmsfCache = { jobId, align, resp }   // keep across toggle-off
    _rmsfResp = resp
    _rmsfBounds = null             // fresh display → default data-range scale
    // This may rebuild the CG renderer. It therefore belongs immediately before the FEM
    // move, matching displayJob's surface-strand integration order.
    if (!await _applyJobSurfaceStrands(jobId, align, epoch, signal)) {
      return { ok: false, reason: 'superseded' }
    }
    _applyFem(map.updates)
    designRenderer.applyScalarColors(map.colorByKey)
    _active = true
    _mode = 'rmsf'
    _jobId = jobId
    _align = align
    _applyHeavy()   // atomistic/surface follow when the scene is in a heavy rep
    return {
      ok: true, n: map.updates.length, min: map.min, max: map.max, mean: resp.mean_rmsf,
      nFrames: resp.n_frames, confidence: resp.confidence, running: !!resp.production_running,
    }
  }

  /**
   * Render a DEVIATION map: a job's time-averaged mean structure, each bead recoloured
   * green→red by its distance from the designed position.  Takes a PRE-FETCHED response
   * from GET /oxdna/jobs/{id}/deviation.  CG beads only (v1 — no heavy reps).  Returns
   * {ok, n, min, max, mean, nFrames}.
   */
  function displayDeviation(resp) {
    if (!designRenderer) return { ok: false, reason: 'no renderer' }
    _epoch++
    const map = deviationColorMap(resp, undefined, undefined, _devCmap)
    if (!map) return { ok: false, reason: resp?.reason || 'not ready' }
    _devResp = resp   // cache so the scale widget can recolour without re-fetching
    _devBounds = { lo: map.min, hi: map.max }
    _applyFem(map.updates)
    designRenderer.applyScalarColors(map.colorByKey)
    _active = true
    _mode = 'deviation'
    _jobId = null   // autorefine-scoped (spans the run's final job), not one job id
    return {
      ok: true, n: map.updates.length, min: map.min, max: map.max,
      mean: resp.mean_deviation, nFrames: resp.n_frames,
    }
  }

  /**
   * Render a STRAIN map: a job's time-averaged mean structure, each bead recoloured by
   * its SIGNED local strain (blue = compressed, white = relaxed, red = stretched).
   * Takes a PRE-FETCHED response from GET /oxdna/jobs/{id}/strain.  CG beads only
   * (mirrors the deviation map — no heavy reps).  Returns {ok, n, min, max, mean,
   * absMax, metric, nFrames}.
   */
  function displayStrain(resp) {
    if (!designRenderer) return { ok: false, reason: 'no renderer' }
    _epoch++
    const map = strainColorMap(resp, undefined, undefined, _strainCmap, { dsOnly: _strainDsOnly })
    if (!map) return { ok: false, reason: resp?.reason || 'not ready' }
    _strainResp = resp   // cache so the scale widget can recolour without re-fetching
    _strainBounds = { lo: map.min, hi: map.max }
    _applyFem(map.updates)
    designRenderer.applyScalarColors(map.colorByKey)
    _active = true
    _mode = 'strain'
    _jobId = null   // pre-fetched payload (like deviation) — the panel owns the job id
    return {
      ok: true, n: map.nColored, nMoved: map.updates.length, min: map.min, max: map.max,
      // mean / data range follow whichever population is coloured (see strainStats).
      ...strainStats(resp, _strainDsOnly),
      absMax: resp.abs_max_strain, metric: resp.metric,
      // Fraction of bond samples discarded as outside the FENE window — a PBC-unwrap
      // artifact in late frames of long/resumed runs, not physics.  Surfaced so a map
      // built from a poorly-reconstructed trajectory can't look as solid as a clean one.
      rejectedFraction: resp.rejected_fraction ?? 0,
      framesTorn: resp.n_frames_torn ?? 0,
      // n_strain_frames = frames the strain was averaged over (its own bounded walk);
      // n_frames = frames behind the mean structure the beads are drawn at.
      nFrames: resp.n_strain_frames ?? resp.n_frames,
    }
  }

  /**
   * Recolour the active STRAIN map to a custom range [lo, hi] on colormap `cmap` —
   * driven by the workspace scale widget.  CG beads only.  No-op unless the strain
   * map is active and its data is cached.
   */
  function recolorStrain(lo, hi, cmap) {
    if (_mode !== 'strain' || !_strainResp || !designRenderer) return false
    if (cmap) _strainCmap = cmap
    const map = strainColorMap(_strainResp, lo, hi, _strainCmap, { dsOnly: _strainDsOnly })
    if (!map) return false
    _strainBounds = { lo: map.min, hi: map.max }
    designRenderer.applyScalarColors(map.colorByKey)
    return true
  }

  /**
   * Include or exclude DESIGNED ssDNA (overhangs, unstapled scaffold loops, extension tails,
   * extra-base inserts) from the strain colouring — so only regions meant to be duplex light
   * up, and a disrupted one is not competing with ssDNA that is floppy by design.  Positions
   * are untouched: excluded bases still ride to their simulated coordinates, they just keep
   * their native colour.  Recolours from the cached payload, so the toggle is instant.
   *
   * Colours are CLEARED first: applyScalarColors leaves keys it isn't given alone, so
   * without this the ssDNA beads would keep the colour the previous pass gave them.  Bounds
   * reset to the new subset's default, since the duplex-only range is usually much tighter.
   * Returns the new {min, max, n} for the legend, or null when the map isn't active.
   */
  function setStrainDsdnaOnly(on) {
    _strainDsOnly = !!on
    if (_mode !== 'strain' || !_strainResp || !designRenderer) return null
    const map = strainColorMap(_strainResp, undefined, undefined, _strainCmap,
                               { dsOnly: _strainDsOnly })
    if (!map) return null
    _strainBounds = { lo: map.min, hi: map.max }
    designRenderer.clearScalarColors?.()
    designRenderer.applyScalarColors(map.colorByKey)
    return { min: map.min, max: map.max, n: map.nColored,
             ...strainStats(_strainResp, _strainDsOnly) }
  }

  /**
   * Recolour the active flexibility map to a custom RMSF range [lo, hi] (values
   * outside clamp to the endpoints) — driven by the workspace scale widget.
   * Positions are untouched (only colours change).  No-op unless the RMSF map is
   * the active overlay and its data is cached.
   */
  function recolorRmsf(lo, hi, cmap) {
    if (_mode !== 'rmsf' || !_rmsfResp || !designRenderer) return false
    if (cmap) _rmsfCmap = cmap
    const map = rmsfColorMap(_rmsfResp, lo, hi, _rmsfCmap)
    if (!map) return false
    _rmsfBounds = { lo: Number.isFinite(lo) ? lo : _activeBounds().lo,
                    hi: Number.isFinite(hi) ? hi : _activeBounds().hi }
    designRenderer.applyScalarColors(map.colorByKey)
    // Keep the active heavy rep in sync with the scale (no re-fetch).
    const kind = _repKind()
    if (kind === 'atomistic') {
      const ar = getAtomisticRenderer?.()
      if (ar && ar.getMode?.() !== 'off') ar.applyScalarColors?.(map.colorByKey)
    } else if (kind === 'surface' && _lastSurfRmsf) {
      const sr = getSurfaceRenderer?.()
      if (sr && sr.getMode?.() !== 'off') {
        sr.applyScalarVertexColors?.(rmsfToVertexColors(_lastSurfRmsf, _rmsfBounds.lo, _rmsfBounds.hi, _rmsfCmap))
      }
    }
    return true
  }

  /**
   * Recolour the active DEVIATION map to a custom range [lo, hi] on colormap `cmap`
   * — driven by the workspace scale widget.  CG beads only (deviation has no heavy
   * rep).  No-op unless the deviation map is active and its data is cached.
   */
  function recolorDeviation(lo, hi, cmap) {
    if (_mode !== 'deviation' || !_devResp || !designRenderer) return false
    if (cmap) _devCmap = cmap
    const map = deviationColorMap(_devResp, lo, hi, _devCmap)
    if (!map) return false
    _devBounds = { lo: Number.isFinite(lo) ? lo : map.min,
                   hi: Number.isFinite(hi) ? hi : map.max }
    designRenderer.applyScalarColors(map.colorByKey)
    return true
  }

  /**
   * Fetch the composite trajectory (relaxation + all production runs) for jobId,
   * cache it, and show the first frame.  Returns metadata for the player
   * (n_frames + stage markers).  The actual scrubbing is driven by showFrame().
   */
  async function loadTrajectory(jobId, align = true, scope = 'lineage', stride = undefined) {
    if (!jobId || !designRenderer) return { ok: false, reason: 'no job' }
    const epoch = ++_epoch
    const signal = _beginLoad()
    const resp = await api.getOxdnaTrajectory(jobId, { align, signal, scope, stride })
    if (epoch !== _epoch) return { ok: false, reason: 'superseded' }
    if (!resp?.ready || !Array.isArray(resp.frames) || !resp.frames.length) {
      return { ok: false, reason: resp?.reason || 'no trajectory yet' }
    }
    _traj = resp
    _bakedAtom = null     // new job → drop the previous job's heavy bakes
    _bakedSurf = null
    designRenderer.clearScalarColors?.()
    _active = true
    _mode = 'trajectory'
    _jobId = jobId
    _align = align
    _trajScope = scope
    _trajStride = stride
    // Replace setup-preview strands before showFrame's FEM move; otherwise the rebuild
    // leaves the origami at design coordinates and the preview caps at seed coordinates.
    if (!await _applyJobSurfaceStrands(jobId, align, epoch, signal)) {
      return { ok: false, reason: 'superseded' }
    }
    showFrame(0)
    return { ok: true, n_frames: resp.n_frames, markers: resp.markers || [], stages: resp.stages || [] }
  }

  /** Deform the model to composite-trajectory frame i (clamped). No-op off mode. */
  function showFrame(i) {
    if (_mode !== 'trajectory' || !_traj || !designRenderer) return
    const n = _traj.frames.length
    const idx = Math.max(0, Math.min(n - 1, i | 0))
    _frameIdx = idx
    _applyFem(framesToUpdates(_traj.keys, _traj.frames[idx]))
    _applyHeavy()   // atomistic/surface follow the scrub (coarse=snap, fine=exact)
  }

  /** Switch heavy-rep reconstruction granularity. 'fine' rebuilds the exact frame
   *  on every scrub (accurate, can be very slow); 'coarse' snaps to a downsampled
   *  bake. Re-applies the current frame in the new granularity. */
  function setGranularity(g) {
    const next = g === 'fine' ? 'fine' : 'coarse'
    if (next === _granularity) return
    _granularity = next
    _bakedAtom = null   // coarse bakes are granularity-specific → drop
    _bakedSurf = null
    if (_active) _applyHeavy()
  }

  /** Re-apply the current overlay's heavy rep after the scene representation
   *  changed (the new atomistic/surface mesh is built from the design — overlay it
   *  with the active oxDNA frame). No-op when nothing is displayed. */
  function reapplyForRepr() {
    if (!_active) return
    // Restoring a CG rep: setCGVisible → refreshArcVisibility may have re-driven the
    // extra-base / connector arcs from NATIVE geometry.  Re-apply the last relaxed overlay
    // so __xb__ extra-base beads and __ext_ extension tails return to their simulated
    // positions with the rest of the structure (idempotent for the already-relaxed duplex).
    if (_repKind() === 'cg') {
      if (_lastCgUpdates) _applyFem(_lastCgUpdates)
      return
    }
    _applyHeavy()
  }

  /** Re-fetch the current job's frame (e.g. after a stage completes). */
  async function refresh() {
    if (!_active || !_jobId) return { ok: false, reason: 'not active' }
    // A running job accumulates production frames, so the memoised relaxed/RMSF payloads
    // for THIS (job, align) are exactly what refresh exists to re-fetch.
    _heavyMemo.clear()
    if (_mode === 'trajectory') {
      _surfaceStrandsByJob.delete(_jobId) // refresh both origami frames and latest real caps
      return loadTrajectory(_jobId, _align, _trajScope, _trajStride)
    }
    // refresh re-fetches: more production frames may have accumulated → bypass cache.
    return _mode === 'rmsf'
      ? displayRmsf(_jobId, { refetch: true, align: _align })
      : displayJob(_jobId, _align)
  }

  /** Clear the overlay (positions + colours) and restore the design. */
  function stopAndRestore() {
    _epoch++   // cancel any in-flight display fetch so it can't re-apply after we restore
    _cancelLoad() // also terminate the HTTP/body transfer and release browser resources
    _heavyToken++   // and any in-flight heavy reconstruction
    _prebuildToken++   // and any in-flight playback prebuild
    _playing = false
    _setHeavyBusy(false, null)   // clear any "building…" spinner the cancelled fetch left up
    if (!_active) return
    // Clear the active/mode state BEFORE restoring the heavy rep.  _restoreHeavy →
    // onRestoreDesignHeavy re-applies the current atomistic/surface mode, and that path
    // checks drivesHeavy() to decide whether to DEFER to this overlay (keep the CG up) —
    // if we're still "active" it would defer and blank the design surface/atoms, making
    // the representation appear to revert to full/CG.  Turning the display off must leave
    // the heavy rep showing the plain DESIGN geometry, not fall back to CG.
    _active = false
    _mode = null
    _jobId = null
    designRenderer?.clearScalarColors?.()
    onOccupancyClear?.()   // drop any superposed configuration ghosts with the model
    _applyFem(null)
    onSurfaceStrands?.(null)   // drop the real strands → seed preview resumes
    proteinRenderer?.clearOxdnaTransforms?.()   // proteins back to design pose
    _restoreHeavy()   // atomistic/surface back to the plain design (rebuild from design)
    _rmsfResp = null
    _strainResp = null
    _traj = null
  }

  return {
    displayJob,
    displayLiveFrame,
    displayRmsf,
    displayOccupancy,
    displayDeviation,
    displayStrain,
    recolorRmsf,
    recolorDeviation,
    recolorStrain,
    setStrainDsdnaOnly,
    strainDsdnaOnly: () => _strainDsOnly,
    loadTrajectory,
    showFrame,
    refresh,
    stopAndRestore,
    setGranularity,
    setPlaying,
    prebuildHeavy,
    releaseHeavyToDesign,
    suspendToDesign,
    resumeTrajectory,
    trajSpec,
    trajSpecMatches,
    reapplyForRepr,
    granularity: () => _granularity,
    isActive: () => _active,
    mode: () => _mode,
    activeJobId: () => _jobId,
    alignment: () => _align,
    cancelPendingLoad: _cancelLoad,
    trajectoryInfo: () => (_mode === 'trajectory' && _traj?.frames?.length)
      // atomSerials/nNucleotides let a caller price an all-atom prebuild: the exact
      // serial span once the topology has been fetched, the nucleotide count (which the
      // trajectory payload always carries) as the estimate before that.
      ? { frame: _frameIdx + 1, total: _traj.frames.length,
          atomSerials: _atomSerials, nNucleotides: _traj.n_nucleotides || 0 }
      : null,
    coloringInfo: () => {
      const resp = _mode === 'rmsf' ? _rmsfResp
        : _mode === 'deviation' ? _devResp
        : _mode === 'strain' ? _strainResp : null
      if (!resp?.positions?.length) return null
      // Per scalar mode: the attribute name exported to ChimeraX/photo paths, its
      // colour bounds (the ones the beads actually used), and the per-nucleotide value.
      const spec = _mode === 'rmsf' ? {
        attribute: 'rmsf', title: 'RMSF', unit: 'nm', colormap: _rmsfCmap,
        bounds: _activeBounds(), value: p => p.rmsf,
      } : _mode === 'deviation' ? {
        attribute: 'deviation', title: 'Deviation', unit: 'nm', colormap: _devCmap,
        bounds: _devBounds || {
          lo: Number.isFinite(resp.min_deviation) ? resp.min_deviation : 0,
          hi: Number.isFinite(resp.max_deviation) ? resp.max_deviation : 1,
        },
        value: p => p.deviation,
      } : {
        attribute: 'strain',
        title: resp.metric === 'wc' ? 'WC pair strain' : 'Backbone strain',
        // Dimensionless (Δ/L0), not a length — export consumers scale it as a fraction.
        unit: 'fraction', colormap: _strainCmap,
        bounds: _strainBounds || strainBounds(resp, _strainDsOnly),
        value: p => p.strain,
        // Export exactly what is DRAWN: unmeasured bases and, when the ssDNA filter is on,
        // designed-ssDNA bases carry no colour, so they carry no exported value either.
        keep: p => Number.isFinite(p.strain) && !(_strainDsOnly && p.ss),
      }
      const keep = spec.keep || (() => true)
      return {
        attribute: spec.attribute, title: spec.title, unit: spec.unit,
        colormap: spec.colormap, lo: spec.bounds.lo, hi: spec.bounds.hi,
        values: resp.positions.filter(keep).map(p => ({
          helix_id: p.helix_id, bp_index: p.bp_index, direction: p.direction,
          copy: p.copy ?? 0, value: spec.value(p),
        })),
      }
    },
    // True when this overlay is active in a mode that REBUILDS the atomistic renderer
    // from the job's atoms (relaxed / rmsf / trajectory) — NOT the CG-only modes
    // (live / deviation / strain), which would leave an atomistic switch with nothing to show.
    // Used to suppress the design "native flash" on full→atomistic.
    /**
     * Will this overlay REBUILD the heavy rep from the job (rather than let the design's
     * own heavy build stand)?  Callers use it to skip the design build entirely — the
     * multi-second "native flash" of the un-simulated structure.
     *
     * Pass the kind the caller is about to build ('atomistic' | 'surface') and the answer
     * accounts for what this controller's api can actually deliver in its current mode.
     * Omitting it keeps the old "any heavy mode" answer.
     */
    drivesHeavy: (kind = null) => {
      if (!_active) return false
      if (_mode !== 'relaxed' && _mode !== 'rmsf' && _mode !== 'trajectory') return false
      return kind ? _canDeliverHeavy(kind) : true
    },
  }
}
