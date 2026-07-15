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
 *
 * Toggling either off restores the model via applyFemPositions(null) +
 * clearScalarColors().
 *
 * Factory: initOxdnaDisplay({ designRenderer, api }) → controller.
 */

import { strideIndices, nearestOf } from '../scene/trajectory_range.js'
import { colormapHex } from './colormaps.js'
import { expandStampFrames, stampTopologyMatches } from '../scene/atomistic_stamp.js'

/**
 * Pure mapping: a /oxdna/jobs/{id}/display response → applyFemPositions updates.
 * Returns [] for a not-ready / empty response.  Kept pure for unit testing.
 */
export function toFemUpdates(displayResponse) {
  if (!displayResponse || !displayResponse.ready || !Array.isArray(displayResponse.positions)) {
    return []
  }
  return displayResponse.positions.map((p) => ({
    helix_id:          p.helix_id,
    bp_index:          p.bp_index,
    direction:         p.direction,
    copy:              p.copy ?? 0,   // loop-copy index → addresses the exact loop bead
    backbone_position: p.backbone_position,
    nx: p.nx, ny: p.ny, nz: p.nz,
  }))
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
    updates.push({
      helix_id: p.helix_id, bp_index: p.bp_index, direction: p.direction, copy: p.copy ?? 0,
      backbone_position: p.backbone_position, nx: p.nx, ny: p.ny, nz: p.nz,
    })
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
 * Pure: turn one composite-trajectory frame (flat float list) + the shared key
 * list into applyFemPositions updates.  keys = [[helix,bp,dir], …]; frame holds
 * 6 floats per key (backbone x,y,z then a1 nx,ny,nz).  Kept pure for testing.
 */
export function framesToUpdates(keys, frame) {
  if (!Array.isArray(keys) || !Array.isArray(frame)) return []
  const updates = []
  for (let j = 0; j < keys.length; j++) {
    const o = j * 6
    updates.push({
      helix_id: keys[j][0], bp_index: keys[j][1], direction: keys[j][2],
      copy: keys[j][3] ?? 0,   // 4th key element = loop-copy index (absent → 0)
      backbone_position: [frame[o], frame[o + 1], frame[o + 2]],
      nx: frame[o + 3], ny: frame[o + 4], nz: frame[o + 5],
    })
  }
  return updates
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
  if (repr === 'vdw' || repr === 'ballstick') return 'atomistic'
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

export function initOxdnaDisplay({
  designRenderer, api, proteinRenderer = null,
  getAtomisticRenderer = null, getSurfaceRenderer = null,
  getCurrentRepr = null, onRestoreDesignHeavy = null, onHeavyStatus = null,
  onFrame = null,
  // Fired after a heavy (atomistic) frame's atoms are applied — lets the caller hide
  // the CG model exactly when the reconstructed atoms land (so switching full→atomistic
  // while this overlay is active shows no "native flash").
  onHeavyApplied = () => {},
}) {
  // Single chokepoint for the bead-position overlay: applies the frame to the rigid
  // design mesh AND forwards it to any per-frame consumer (onFrame) — e.g. flexible
  // ssDNA arcs, whose beads are excluded from the rigid mesh and must be redrawn at
  // simulated positions.  Pass null to restore the design (both revert).
  const _applyFem = (updates) => {
    designRenderer?.applyFemPositions(updates)
    onFrame?.(updates)
  }
  let _active = false
  let _jobId = null
  let _mode = null     // 'relaxed' | 'rmsf' | 'deviation' | 'trajectory'
  let _rmsfResp = null // cached /rmsf payload so the scale can recolour without re-fetching
  let _devResp = null  // cached /deviation payload so the scale can recolour without re-fetching
  let _rmsfCmap = 'viridis'    // active flex-map colormap (widget-driven)
  let _devCmap  = 'devramp'    // active deviation-map colormap (widget-driven)
  let _traj = null     // cached /trajectory payload {keys, frames, markers, n_frames, stages}
  // Monotonic token: bumped by every display call AND by stopAndRestore, so an
  // async fetch (live-follow poll / job-switch) that resolves AFTER the overlay
  // was turned off or superseded by a newer call bails instead of re-applying
  // stale positions (the "toggle off but sim positions stay" desync).
  let _epoch = 0

  // ── Heavy reps (atomistic / surface) ───────────────────────────────────────
  // The CG overlay above is applied via designRenderer.applyFemPositions; when the
  // scene is in an atomistic or surface representation we ALSO reconstruct that
  // heavy geometry from the same relaxed/rmsf/trajectory frame and push it into
  // the atomistic/surface renderer (display-state only, never topology).
  let _align = true          // last align flag from displayJob (relaxed only)
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
  // jobId whose atomistic ATOMS/BONDS the renderer currently holds.  The relaxed
  // positions are serial-indexed against the JOB's design snapshot, which can differ
  // from the design now loaded in the app (edited after the job ran) — applying them
  // onto the active-design atoms maps every serial to the wrong atom (scrambled
  // colours/bonds/positions).  So before overlaying any oxDNA atomistic frame we
  // REBUILD the renderer from the job's own atomistic model (once per job).
  let _atomTopoJob = null
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

  /** Ensure the atomistic renderer holds the JOB's topology (atoms+bonds), so the
   *  relaxed positions line up serial-for-serial.  Prefers the COMBINED display bundle
   *  (topology + stamp descriptor, ONE disk-cached build) and caches the descriptor as
   *  a side effect; falls back to the legacy atomistic-model route (and, for the MD
   *  adapter which has neither, becomes a no-op → heavy rep stays off as before).
   *  Returns false if it could not. */
  async function _ensureJobAtomistic(ar, epoch) {
    if (_atomTopoJob === _jobId) return true            // already rebuilt for this job
    let model = null
    if (typeof api.getOxdnaAtomisticDisplayBundle === 'function') {
      const b = await api.getOxdnaAtomisticDisplayBundle(_jobId).catch(() => null)
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
    ar.update({ atoms: model.atoms, bonds: model.bonds || [] })
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

  async function _pushAtomistic(arr, epoch, live, colorByKey = null) {
    const ar = getAtomisticRenderer?.()
    // arr may be a plain Array (legacy flat route) OR a Float32Array (fast stamp
    // expansion) — accept both array-likes, reject only null/empty.
    if (!ar || ar.getMode?.() === 'off' || !arr || !arr.length) return
    if (!(await _ensureJobAtomistic(ar, epoch))) return
    if (live && !live()) return
    ar.applyPositionLerp(arr, arr, 0, null, [], null)
    // Flexibility map → recolour atoms by RMSF; any other mode → drop the overlay.
    if (colorByKey) ar.applyScalarColors?.(colorByKey)
    else ar.clearScalarColors?.()
    _heavyActive = true
    onHeavyApplied()   // atoms are live → the caller can now hide the CG model (no flash)
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
  }

  // Heavy reconstruction is slow (one all-atom rebuild per frame). Announce when one
  // is in flight so the panel can show a "building…" spinner instead of looking frozen.
  function _setHeavyBusy(building, kind) {
    onHeavyStatus?.({ building, kind, mode: _mode })
  }

  /** Ensure the coarse snap-grid for the active trajectory job is DEFINED for `kind`
   *  (cheap — just the index list; frames are fetched lazily on visit). Returns the
   *  bake object {grid:[idx…], byIdx:Map<idx,data>} or null. */
  function _ensureGrid(kind) {
    const n = _traj?.n_frames || _traj?.frames?.length || 0
    if (n <= 0) return null
    if (kind === 'atomistic') {
      if (!_bakedAtom) _bakedAtom = { grid: strideIndices(0, n - 1, _COARSE_ATOM_CAP), byIdx: new Map() }
      return _bakedAtom
    }
    if (!_bakedSurf) _bakedSurf = { grid: strideIndices(0, n - 1, _COARSE_SURF_CAP), byIdx: new Map() }
    return _bakedSurf
  }

  /** Lazily fetch + cache ONE coarse-grid frame's heavy data. One network rebuild per
   *  distinct grid cell (then served from cache on revisits). Epoch-guarded. */
  async function _coarseFrame(kind, gridIdx, epoch) {
    const bake = kind === 'atomistic' ? _bakedAtom : _bakedSurf
    if (bake.byIdx.has(gridIdx)) return bake.byIdx.get(gridIdx)
    const resp = kind === 'atomistic'
      ? await api.getOxdnaFramesAtomistic(_jobId, [gridIdx])
      : await api.getOxdnaFramesSurface(_jobId, [gridIdx])
    if (epoch !== _epoch) return null
    const data = resp?.[String(gridIdx)] || null
    if (data) bake.byIdx.set(gridIdx, data)
    return data
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
  async function prebuildHeavy(onProgress) {
    if (_mode !== 'trajectory') return { ok: true, n: 0 }
    const kind = _repKind()
    if (kind === 'cg') return { ok: true, n: 0 }   // CG plays instantly — nothing to bake
    const bake = _ensureGrid(kind)
    if (!bake || !bake.grid.length) return { ok: false, n: 0 }
    const epoch = _epoch
    const token = ++_prebuildToken
    const live = () => epoch === _epoch && token === _prebuildToken
    const total = bake.grid.length
    let done = bake.grid.filter((g) => bake.byIdx.has(g)).length
    onProgress?.(done, total)
    const todo = bake.grid.filter((g) => !bake.byIdx.has(g))
    if (todo.length) {                       // first cell alone → warms the alignment cache
      await _coarseFrame(kind, todo[0], epoch)
      if (!live()) return { ok: false, n: total }
      done++; onProgress?.(done, total)
    }
    const rest = todo.slice(1)
    let next = 0
    const worker = async () => {
      while (next < rest.length && live()) {
        const g = rest[next++]
        await _coarseFrame(kind, g, epoch)
        if (live()) { done++; onProgress?.(done, total) }
      }
    }
    await Promise.all(Array.from({ length: Math.min(3, rest.length) }, worker))
    return { ok: live(), n: total }
  }

  /** Reconstruct + apply the heavy rep for the CURRENT mode/frame (no-op in CG).
   *  Token-guarded: only the newest call applies, so rapid scrubbing / rep flips
   *  never paint a stale frame. */
  async function _applyHeavy() {
    if (!_active || !_jobId) return
    const kind = _repKind()
    if (kind === 'cg') return
    const epoch = _epoch
    const token = ++_heavyToken
    const live = () => epoch === _epoch && token === _heavyToken
    // During playback, force coarse even if the dropdown says fine — a fine rebuild per
    // tick (~seconds each) would stall the loop; play steps the pre-built coarse frames.
    const useFine = _granularity === 'fine' && !_playing
    // Skip the spinner only when a trajectory grid cell is already cached (instant).
    let busy = true
    if (_mode === 'trajectory' && !useFine) {
      const bake = _ensureGrid(kind)
      const g = bake ? nearestOf(bake.grid, _frameIdx) : null
      busy = !(bake && g != null && bake.byIdx.has(g))
    }
    if (busy) _setHeavyBusy(true, kind)
    try {
      if (_mode === 'relaxed') {
        if (kind === 'atomistic') {
          const flat = await _relaxedAtomisticFlat(epoch, live)
          if (live() && flat) await _pushAtomistic(flat, epoch, live)
        } else {
          const r = await api.getOxdnaDisplaySurface(_jobId, _align)
          if (live() && r?.ready) _pushSurface(r.surface)
        }
      } else if (_mode === 'rmsf') {
        if (kind === 'atomistic') {
          const r = await api.getOxdnaRmsfAtomistic(_jobId)
          if (live() && r?.ready) {
            const { lo, hi } = _activeBounds()
            const m = rmsfColorMap(_rmsfResp, lo, hi, _rmsfCmap)   // same ramp/scale as the beads
            await _pushAtomistic(r.atomistic, epoch, live, m?.colorByKey || null)
          }
        } else {
          const r = await api.getOxdnaRmsfSurface(_jobId)
          if (live() && r?.ready) _pushSurface(r.surface, true)   // colour by per-vertex RMSF
        }
      } else if (_mode === 'trajectory') {
        const idx = _frameIdx
        if (useFine) {
          if (kind === 'atomistic') {
            const r = await api.getOxdnaFramesAtomistic(_jobId, [idx])
            if (live()) await _pushAtomistic(r?.[String(idx)], epoch, live)
          } else {
            const r = await api.getOxdnaFramesSurface(_jobId, [idx])
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

  function _restoreHeavy() {
    // Drop the flex-map overlay BEFORE the design rebuild — otherwise the scalar
    // colours (keyed by helix:bp:dir, which the design's own atoms also match)
    // would repaint the restored design atoms by stale RMSF.
    getAtomisticRenderer?.()?.clearScalarColors?.()
    if (_heavyActive) { onRestoreDesignHeavy?.(); _heavyActive = false }
    _bakedAtom = null
    _bakedSurf = null
    _atomTopoJob = null   // next job display rebuilds the renderer from its own topology
    _stampDescJob = null  // and re-fetches the stamp descriptor for that job
    _lastSurfRmsf = null
  }

  /** Fetch the latest relaxed frame for jobId and deform the model to it.
   *  `align` (default true) superposes onto the design pose; false shows the
   *  structure in its own simulation frame (e.g. settled on a hard surface). */
  async function displayJob(jobId, align = true) {
    if (!jobId || !designRenderer) return { ok: false, reason: 'no job' }
    const epoch = ++_epoch
    const resp = await api.getOxdnaDisplay(jobId, align)
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
      return { ok: false, reason: resp?.ready === false ? 'no relaxed frame yet' : 'empty' }
    }
    designRenderer.clearScalarColors?.()   // leaving a flexibility map → restore bead colours
    _applyFem(updates)
    // Hybrid (protein) jobs: move each protein to its relaxed pose (design→relaxed
    // rigid 4×4 from the backend); DNA-only jobs send no proteins → clears to design.
    proteinRenderer?.applyOxdnaTransforms?.(proteinTransformMap(resp))
    _active = true
    _mode = 'relaxed'
    _jobId = jobId
    _align = align
    _applyHeavy()   // atomistic/surface follow when the scene is in a heavy rep
    return { ok: true, n: updates.length, stage: resp.stage_name }
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
  async function displayRmsf(jobId, { refetch = false } = {}) {
    if (!jobId || !designRenderer) return { ok: false, reason: 'no job' }
    const epoch = ++_epoch
    // Re-use the cached flex map for this job (instant re-toggle) unless a refetch
    // is forced (e.g. refresh after more production frames accumulated).
    let resp
    if (!refetch && _rmsfCache && _rmsfCache.jobId === jobId) {
      resp = _rmsfCache.resp
    } else {
      resp = await api.getOxdnaRmsf(jobId)
      if (epoch !== _epoch) return { ok: false, reason: 'superseded' }
    }
    const map = rmsfColorMap(resp, undefined, undefined, _rmsfCmap)
    if (!map) {
      return { ok: false, reason: resp?.reason || 'not ready' }
    }
    _rmsfCache = { jobId, resp }   // keep across toggle-off
    _rmsfResp = resp
    _rmsfBounds = null             // fresh display → default data-range scale
    _applyFem(map.updates)
    designRenderer.applyScalarColors(map.colorByKey)
    _active = true
    _mode = 'rmsf'
    _jobId = jobId
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
    designRenderer.applyScalarColors(map.colorByKey)
    return true
  }

  /**
   * Fetch the composite trajectory (relaxation + all production runs) for jobId,
   * cache it, and show the first frame.  Returns metadata for the player
   * (n_frames + stage markers).  The actual scrubbing is driven by showFrame().
   */
  async function loadTrajectory(jobId) {
    if (!jobId || !designRenderer) return { ok: false, reason: 'no job' }
    const epoch = ++_epoch
    const resp = await api.getOxdnaTrajectory(jobId)
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
    if (_active) _applyHeavy()
  }

  /** Re-fetch the current job's frame (e.g. after a stage completes). */
  async function refresh() {
    if (!_active || !_jobId) return { ok: false, reason: 'not active' }
    if (_mode === 'trajectory') return loadTrajectory(_jobId)
    // refresh re-fetches: more production frames may have accumulated → bypass cache.
    return _mode === 'rmsf' ? displayRmsf(_jobId, { refetch: true }) : displayJob(_jobId)
  }

  /** Clear the overlay (positions + colours) and restore the design. */
  function stopAndRestore() {
    _epoch++   // cancel any in-flight display fetch so it can't re-apply after we restore
    _heavyToken++   // and any in-flight heavy reconstruction
    _prebuildToken++   // and any in-flight playback prebuild
    _playing = false
    _setHeavyBusy(false, null)   // clear any "building…" spinner the cancelled fetch left up
    if (!_active) return
    designRenderer?.clearScalarColors?.()
    _applyFem(null)
    proteinRenderer?.clearOxdnaTransforms?.()   // proteins back to design pose
    _restoreHeavy()   // atomistic/surface back to the plain design (rebuild from design)
    _active = false
    _mode = null
    _jobId = null
    _rmsfResp = null
    _traj = null
  }

  return {
    displayJob,
    displayLiveFrame,
    displayRmsf,
    displayDeviation,
    recolorRmsf,
    recolorDeviation,
    loadTrajectory,
    showFrame,
    refresh,
    stopAndRestore,
    setGranularity,
    setPlaying,
    prebuildHeavy,
    reapplyForRepr,
    granularity: () => _granularity,
    isActive: () => _active,
    mode: () => _mode,
    activeJobId: () => _jobId,
    // True when this overlay is active in a mode that REBUILDS the atomistic renderer
    // from the job's atoms (relaxed / rmsf / trajectory) — NOT the CG-only modes
    // (live / deviation), which would leave an atomistic switch with nothing to show.
    // Used to suppress the design "native flash" on full→atomistic.
    drivesHeavy: () => _active && (_mode === 'relaxed' || _mode === 'rmsf' || _mode === 'trajectory'),
  }
}
