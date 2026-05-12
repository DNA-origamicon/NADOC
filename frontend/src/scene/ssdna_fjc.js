/**
 * ssDNA freely-jointed chain lookup — client-side cache + chord-fit transform.
 *
 * Schema (bin-based redesign): each lookup entry exposes an R_ee histogram
 * with `hist_bins` bins. Each non-empty bin carries one representative
 * shape (`rep_positions`) and per-Rg-bin counts (`rg_subcounts`) so the
 * linker-config modal can re-compute the Rg distribution under any R_ee
 * range crop without round-tripping the backend.
 *
 * Used by `overhang_link_arcs.js` to render the chosen bridge shape and
 * by `linker_config_modal.js` for the interactive shape picker.
 */

import * as THREE from 'three'

let _lookup = null
let _loadPromise = null
let _onLoaded = []

export function ensureLoaded() {
  if (_lookup) return Promise.resolve(_lookup)
  if (_loadPromise) return _loadPromise
  _loadPromise = fetch('/api/ssdna-fjc-lookup', {
    headers: { 'Accept': 'application/json' },
    cache: 'no-store',
  })
    .then(r => {
      if (!r.ok) throw new Error(`ssdna-fjc-lookup HTTP ${r.status}`)
      return r.json()
    })
    .then(payload => {
      _lookup = payload
      const cfgCount = payload?.metadata?.hist_bins
      if (cfgCount !== 40) {
        console.warn('[ssdna_fjc] unexpected hist_bins:', cfgCount,
          '(metadata:', payload?.metadata, ')')
      }
      const subs = _onLoaded.splice(0)
      for (const fn of subs) {
        try { fn(payload) } catch (e) { console.error('[ssdna_fjc] onLoaded subscriber threw:', e) }
      }
      return payload
    })
    .catch(err => {
      console.warn('[ssdna_fjc] lookup load failed; ss bridges will fall back to Bezier:', err)
      _loadPromise = null
      throw err
    })
  return _loadPromise
}

export function isLoaded() { return _lookup != null }

export function onLoaded(fn) {
  if (_lookup) { fn(_lookup); return () => {} }
  _onLoaded.push(fn)
  return () => { _onLoaded = _onLoaded.filter(f => f !== fn) }
}

export function metadata() { return _lookup?.metadata ?? null }

export function lookupEntry(nBp) {
  if (!_lookup) return null
  const key = String(Math.max(1, Math.round(nBp)))
  return _lookup.entries?.[key] ?? null
}

/** Convert an arbitrary bin index to the nearest occupied bin (with a rep
 *  shape). Returns null if the entry has no occupied bins. */
export function resolveBinIndex(nBp, binIndex) {
  const entry = lookupEntry(nBp)
  if (!entry) return null
  const bins = entry.bins ?? []
  if (!bins.length) return null
  const n = bins.length
  let raw = ((binIndex % n) + n) % n
  if (bins[raw]?.count > 0 && bins[raw]?.rep_positions) return raw
  for (let d = 1; d <= n; d++) {
    for (const cand of [raw - d, raw + d]) {
      if (cand >= 0 && cand < n && bins[cand]?.count > 0 && bins[cand]?.rep_positions) {
        return cand
      }
    }
  }
  return null
}

/** Bin whose midpoint R_ee is closest to the ensemble mean. */
export function defaultBinIndex(nBp) {
  const entry = lookupEntry(nBp)
  if (!entry) return null
  const mean = entry.r_ee_mean_nm ?? 0
  const edges = entry.r_ee_bin_edges_nm ?? []
  let best = -1
  let bestErr = Infinity
  for (let k = 0; k < edges.length - 1; k++) {
    const mid = 0.5 * (edges[k] + edges[k + 1])
    const err = Math.abs(mid - mean)
    if (err < bestErr) { bestErr = err; best = k }
  }
  return resolveBinIndex(nBp, best)
}

export function binPositions(nBp, binIndex) {
  const idx = resolveBinIndex(nBp, binIndex)
  if (idx == null) return null
  return lookupEntry(nBp).bins[idx].rep_positions
}

export function binRee(nBp, binIndex) {
  const idx = resolveBinIndex(nBp, binIndex)
  if (idx == null) return null
  return lookupEntry(nBp).bins[idx].rep_r_ee_nm
}

export function binRg(nBp, binIndex) {
  const idx = resolveBinIndex(nBp, binIndex)
  if (idx == null) return null
  return lookupEntry(nBp).bins[idx].rep_rg_nm
}

/** Return the Rg histogram counts for samples whose R_ee falls inside
 *  [rEeMin, rEeMax] — by summing `rg_subcounts` of bins in the range. */
export function filteredRgHistogram(nBp, rEeMin, rEeMax) {
  const entry = lookupEntry(nBp)
  if (!entry) return null
  const edges = entry.r_ee_bin_edges_nm ?? []
  const bins = entry.bins ?? []
  const rgEdges = entry.rg_bin_edges_nm ?? []
  const nRg = rgEdges.length - 1
  if (nRg <= 0) return null
  const out = new Array(nRg).fill(0)
  for (let k = 0; k < bins.length; k++) {
    const lo = edges[k], hi = edges[k + 1]
    if (hi < rEeMin - 1e-9 || lo > rEeMax + 1e-9) continue
    const sub = bins[k]?.rg_subcounts ?? []
    for (let j = 0; j < nRg; j++) {
      out[j] += sub[j] ?? 0
    }
  }
  return { bin_edges_nm: rgEdges, counts: out }
}

/**
 * Anisotropic stretch + rotate + translate canonical positions onto the
 * live anchor chord A→B. y, z preserved; x scaled so the last bead lands
 * at chord_length along the chord direction.
 */
export function transformToChord(canonical, anchorA, anchorB, rEe) {
  const chord = new THREE.Vector3().subVectors(anchorB, anchorA)
  const chordLen = chord.length()
  if (rEe < 1e-9 || chordLen < 1e-9) {
    return canonical.map(() => anchorA.clone())
  }
  const k = chordLen / rEe
  const target = chord.clone().normalize()
  const src = new THREE.Vector3(1, 0, 0)

  const axis = new THREE.Vector3().crossVectors(src, target)
  const sin = axis.length()
  const cos = src.dot(target)
  let rot
  if (sin < 1e-12) {
    rot = cos > 0
      ? new THREE.Matrix3().identity()
      : new THREE.Matrix3().set(-1, 0, 0,  0, -1, 0,  0, 0, 1)
  } else {
    axis.divideScalar(sin)
    const x = axis.x, y = axis.y, z = axis.z
    const C = 1 - cos
    rot = new THREE.Matrix3().set(
      cos + x*x*C,     x*y*C - z*sin,  x*z*C + y*sin,
      y*x*C + z*sin,   cos + y*y*C,    y*z*C - x*sin,
      z*x*C - y*sin,   z*y*C + x*sin,  cos + z*z*C,
    )
  }

  const out = new Array(canonical.length)
  const tmp = new THREE.Vector3()
  for (let i = 0; i < canonical.length; i++) {
    const [cx, cy, cz] = canonical[i]
    tmp.set(cx * k, cy, cz).applyMatrix3(rot).add(anchorA)
    out[i] = tmp.clone()
  }
  return out
}

/** Convenience: world-frame chain for a given (n_bp, binIndex) between anchors. */
export function fjcChainBetween(nBp, anchorA, anchorB, binIndex = null) {
  const idx = binIndex == null ? defaultBinIndex(nBp) : resolveBinIndex(nBp, binIndex)
  if (idx == null) return null
  const positions = binPositions(nBp, idx)
  const rEe = binRee(nBp, idx)
  if (!positions || rEe == null) return null
  return transformToChord(positions, anchorA, anchorB, rEe)
}
