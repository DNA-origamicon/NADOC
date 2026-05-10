/**
 * MD Segmentation Overlay
 *
 * Bins the loaded design into 21 bp windows (one HC crossover period) and
 * colours each window by how well its staple-crossover count matches the
 * design's dominant (modal) period:
 *
 *   green           — identical to modal count  → safe for periodic MD cell
 *   yellow → red    — deviation from modal       → seam, routing exception, etc.
 *   red (solid end) — helix endpoints land here  → end-cap region
 *
 * Each window is rendered as a translucent full-cross-section slab oriented
 * perpendicular to the dominant helix axis.
 */

import * as THREE from 'three'
import { BDNA_RISE_PER_BP } from '../constants.js'

const PERIOD_BP  = 21          // HC crossover repeat period
const SLAB_PAD   = 2.0         // nm of XY padding beyond helix bounding box
const OPACITY    = 0.18
const EDGE_OPACITY = 0.50

// ── colour helpers ────────────────────────────────────────────────────────────

function _lerpColor(c1, c2, t) {
  const r = Math.round(((c1 >> 16) & 0xff) + (((c2 >> 16) & 0xff) - ((c1 >> 16) & 0xff)) * t)
  const g = Math.round(((c1 >>  8) & 0xff) + (((c2 >>  8) & 0xff) - ((c1 >>  8) & 0xff)) * t)
  const b = Math.round(( c1        & 0xff) + (( c2        & 0xff) - ( c1        & 0xff)) * t)
  return (r << 16) | (g << 8) | b
}

function _mode(arr) {
  const counts = {}
  let best = 0, modal = arr[0]
  for (const v of arr) {
    const n = (counts[v] = (counts[v] ?? 0) + 1)
    if (n > best) { best = n; modal = v }
  }
  return modal
}

// ── segmentation logic ────────────────────────────────────────────────────────

export function computeSegments(design) {
  const bpMin = Math.min(...design.helices.map(h => h.bp_start))
  const bpMax = Math.max(...design.helices.map(h => h.bp_start + h.length_bp))

  // Snap window grid to period boundary
  const winStart = Math.floor(bpMin / PERIOD_BP) * PERIOD_BP

  const windows = []
  for (let bp = winStart; bp < bpMax; bp += PERIOD_BP) {
    const bpEnd = bp + PERIOD_BP

    // Count crossovers with any endpoint inside this window
    let xoverCount = 0
    for (const xo of design.crossovers) {
      const iA = xo.half_a.index, iB = xo.half_b.index
      if ((iA >= bp && iA < bpEnd) || (iB >= bp && iB < bpEnd)) xoverCount++
    }

    // Flag windows that contain an open helix endpoint
    let hasOpenEnd = false
    for (const h of design.helices) {
      const hs = h.bp_start, he = h.bp_start + h.length_bp
      if ((hs >= bp && hs < bpEnd) || (he > bp && he <= bpEnd)) {
        hasOpenEnd = true
        break
      }
    }

    windows.push({ bp, bpEnd, xoverCount, hasOpenEnd })
  }

  // Modal crossover count from interior (non-end) windows
  const innerCounts = windows.filter(w => !w.hasOpenEnd).map(w => w.xoverCount)
  const modal  = innerCounts.length ? _mode(innerCounts) : 0
  const maxDev = innerCounts.length
    ? Math.max(...innerCounts.map(c => Math.abs(c - modal)), 1)
    : 1

  for (const w of windows) {
    const dev = Math.abs(w.xoverCount - modal)
    w.deviation = dev
    w.modal     = modal
    if (w.hasOpenEnd) {
      w.category = 'end'
      w.color    = 0xff4444
    } else if (dev === 0) {
      w.category = 'periodic'
      w.color    = 0x44cc66
    } else {
      w.category = 'deviant'
      w.color    = _lerpColor(0xffdd00, 0xff4444, Math.min(dev / maxDev, 1))
    }
  }

  return { windows, modal, maxDev }
}

// ── scene overlay ─────────────────────────────────────────────────────────────

export function initMdSegmentationOverlay(scene) {
  const _group = new THREE.Group()
  _group.visible = false
  scene.add(_group)

  function _refHelix(design) {
    // Use the helix with the greatest axial span as the axis reference
    let best = null, bestLen = -Infinity
    for (const h of design.helices) {
      const dx = h.axis_end.x - h.axis_start.x
      const dy = h.axis_end.y - h.axis_start.y
      const dz = h.axis_end.z - h.axis_start.z
      const len = Math.sqrt(dx*dx + dy*dy + dz*dz)
      if (len > bestLen) { bestLen = len; best = h }
    }
    return best
  }

  function _bpToPos(bp, ref) {
    const t = (bp - ref.bp_start) / ref.length_bp
    return new THREE.Vector3(
      ref.axis_start.x + t * (ref.axis_end.x - ref.axis_start.x),
      ref.axis_start.y + t * (ref.axis_end.y - ref.axis_start.y),
      ref.axis_start.z + t * (ref.axis_end.z - ref.axis_start.z),
    )
  }

  function _rebuild(design) {
    while (_group.children.length) {
      const c = _group.children[0]
      c.geometry?.dispose()
      c.material?.dispose()
      _group.remove(c)
    }
    if (!design?.crossovers?.length || !design?.helices?.length) return

    const { windows } = computeSegments(design)
    const ref = _refHelix(design)

    // Axis direction unit vector
    const axisDir = new THREE.Vector3(
      ref.axis_end.x - ref.axis_start.x,
      ref.axis_end.y - ref.axis_start.y,
      ref.axis_end.z - ref.axis_start.z,
    ).normalize()

    // Quaternion that rotates Z → axisDir (BoxGeometry depth is along Z)
    const slabQuat = new THREE.Quaternion().setFromUnitVectors(
      new THREE.Vector3(0, 0, 1), axisDir,
    )

    // XY bounding box (perpendicular to axis — use all helix endpoint positions)
    let xMin = Infinity, xMax = -Infinity
    let yMin = Infinity, yMax = -Infinity
    for (const h of design.helices) {
      for (const p of [h.axis_start, h.axis_end]) {
        xMin = Math.min(xMin, p.x); xMax = Math.max(xMax, p.x)
        yMin = Math.min(yMin, p.y); yMax = Math.max(yMax, p.y)
      }
    }
    const slabW = (xMax - xMin) + SLAB_PAD * 2
    const slabH = (yMax - yMin) + SLAB_PAD * 2
    const cx    = (xMin + xMax) / 2
    const cy    = (yMin + yMax) / 2

    for (const w of windows) {
      const posStart = _bpToPos(w.bp,    ref)
      const posEnd   = _bpToPos(w.bpEnd, ref)
      const posCenter = posStart.clone().add(posEnd).multiplyScalar(0.5)
      const depth = posStart.distanceTo(posEnd)

      // Translucent fill
      const geo = new THREE.BoxGeometry(slabW, slabH, depth)
      const mat = new THREE.MeshBasicMaterial({
        color:       w.color,
        transparent: true,
        opacity:     w.hasOpenEnd ? OPACITY * 1.6 : OPACITY,
        depthWrite:  false,
        side:        THREE.DoubleSide,
      })
      const mesh = new THREE.Mesh(geo, mat)
      mesh.position.set(cx, cy, posCenter.z)
      mesh.quaternion.copy(slabQuat)
      _group.add(mesh)

      // Wireframe outline
      const edgeGeo = new THREE.EdgesGeometry(geo)
      const edgeMat = new THREE.LineBasicMaterial({
        color:       w.color,
        transparent: true,
        opacity:     EDGE_OPACITY,
      })
      const edges = new THREE.LineSegments(edgeGeo, edgeMat)
      edges.position.copy(mesh.position)
      edges.quaternion.copy(slabQuat)
      _group.add(edges)
    }
  }

  return {
    show(design)   { _group.visible = true;  _rebuild(design) },
    hide()         { _group.visible = false },
    isVisible()    { return _group.visible },
    toggle(design) {
      if (_group.visible) { this.hide(); return false }
      this.show(design); return true
    },
    rebuild(design) { if (_group.visible) _rebuild(design) },
  }
}
