/**
 * Joint Renderer — surface approximation, joint axis visualisation, and
 * face-click interaction for ClusterJoint definition.
 *
 * Surface approximation algorithm:
 *   1. Bundle axis D = normalised sum of helix (aEnd - aStart) vectors.
 *   2. Build local cross-section frame (U, V) ⊥ to D.
 *   3. Project ALL backbone positions for the cluster into (U, V, D) coordinates.
 *   4. For N=4: fit a bounding rectangle (actual extents in U/V) → rectangular box.
 *      For other N: circumscribing regular N-gon (max dist from centroid + margin).
 *   5. Extrude the polygon along D using the actual backbone axial extents.
 *   6. Build a flat-shaded closed prism BufferGeometry.
 *
 * Interaction (define mode):
 *   - Canvas shows semi-transparent surface mesh.
 *   - Mouse-move over a face shows a ghost arrow preview of the resulting joint axis.
 *   - Click on a face → face normal becomes the joint axis; joint created via API.
 *   - Escape key or `exitDefineMode()` cancels without creating a joint.
 *
 * Persistent indicators (shaft + ring + tips, orange) are always visible for
 * existing joints and live in a dedicated group separate from helix geometry.
 *
 * Public API:
 *   initJointRenderer(scene, camera, canvas, store, api)
 *   → {
 *       enterDefineMode(clusterId, onExit),
 *       exitDefineMode(),
 *       setExteriorPanels(on),  // boolean — lattice panels vs. regular polygon fallback
 *       rebuild(design),
 *       highlightJoint(jointId),
 *       clearHighlight(),
 *       dispose(),
 *     }
 *
 * Helix axis data:  store.getState().currentHelixAxes  → { [hid]: { start, end } }
 * Backbone data:    store.getState().currentGeometry   → [{helix_id, backbone_position}]
 */

import * as THREE from 'three'
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js'
import {
  BDNA_RISE_PER_BP,
  HONEYCOMB_ROW_PITCH,
  SQUARE_HELIX_SPACING,
} from '../constants.js'
import { buildClusterLookup } from './helix_renderer/palette.js'

// ── Constants ─────────────────────────────────────────────────────────────────
const SURFACE_COLOUR   = 0x4488ff   // lattice exterior panels
const POLYGON_COLOUR   = 0xff8844   // regular polygon overlay
const HULL_COLOUR      = 0x44ff88   // convex hull surface
const SURFACE_OPACITY  = 0.22
const PREVIEW_COLOUR   = 0xffffff

const PREV_SHAFT_R     = 0.13   // nm — arrow (hover preview + placed indicator)
const PREV_HALF_LEN    = 0.9    // nm — arrow barely protrudes above surface
const PREV_TIP_R       = 0.30   // nm
const PREV_TIP_H       = 0.72   // nm
const PREV_OPACITY     = 1.0

const SPRITE_SIZE  = 1.67  // nm — diameter of the checkerboard disc
const MIN_HC_FACES = 6
const MIN_SQ_FACES = 4
const CROSS_MARGIN = 1.0   // nm added around bounding extents
const AXIAL_MARGIN = 1.0   // nm added to each end along bundle axis

// Grid line settings
const GRID_PERIOD_HC = 7   // bp between static ring lines on honeycomb designs
const GRID_PERIOD_SQ = 8   // bp between static ring lines on square-lattice designs
const HOVER_RADIUS   = 2.0 // nm — axial fade radius for per-bp hover rings
// RGB float components for grid / hover ring colours
const GRID_R = 0x66 / 255, GRID_G = 0x99 / 255, GRID_B = 1.0  // #6699ff
const HOVER_R = 0x99 / 255, HOVER_G = 0xcc / 255, HOVER_B = 1.0  // #99ccff

const NEIGHBOR_TOL = 0.5   // nm — position-match tolerance for helix lookup

// ── 2D convex hull helpers ────────────────────────────────────────────────────

/**
 * Gift-wrapping (Jarvis march) 2D convex hull.
 * @param  {Array<{u:number,v:number}>} pts  input points (any order)
 * @returns {Array<{u:number,v:number}>}     CCW hull (subset of pts)
 */
function _convexHull2D(pts) {
  const n = pts.length
  if (n < 3) return pts.slice()

  // Find bottom-most (then left-most) point as start → guarantees CCW traversal
  let start = 0
  for (let i = 1; i < n; i++) {
    if (pts[i].v < pts[start].v || (pts[i].v === pts[start].v && pts[i].u < pts[start].u)) {
      start = i
    }
  }

  const hull = []
  let current = start
  do {
    hull.push(pts[current])
    let next = (current + 1) % n
    for (let i = 0; i < n; i++) {
      if (i === current) continue
      const ax = pts[next].u - pts[current].u, ay = pts[next].v - pts[current].v
      const bx = pts[i].u   - pts[current].u, by = pts[i].v   - pts[current].v
      const cross = ax * by - ay * bx
      // Negative cross → pts[i] is to the RIGHT of current→next → update next (CW scan
      // from the current direction → builds CCW hull)
      if (cross < 0 || (cross === 0 && bx * bx + by * by > ax * ax + ay * ay)) {
        next = i
      }
    }
    current = next
  } while (current !== start && hull.length <= n)

  return hull
}

/**
 * Expand a CCW convex hull outward by `margin` at each vertex and convert
 * to the {x,z} corner format used by the prism/panel surface builders
 * (local frame: X = U, Z = V).
 *
 * @param  {Array<{u,v}>} hull    CCW convex hull
 * @param  {number}       margin  outward expansion distance (nm)
 * @returns {Array<{x,z}>}
 */
function _expandHullCorners(hull, margin) {
  const n = hull.length
  const result = []
  for (let i = 0; i < n; i++) {
    const prev = hull[(i - 1 + n) % n]
    const curr = hull[i]
    const next = hull[(i + 1) % n]

    // Outward normals of the two edges meeting at curr
    // (for a CCW polygon the outward/right normal of edge A→B is (+dy, −dx) norm.)
    const e1x = curr.u - prev.u, e1y = curr.v - prev.v
    const e2x = next.u - curr.u, e2y = next.v - curr.v
    const l1  = Math.sqrt(e1x * e1x + e1y * e1y) || 1
    const l2  = Math.sqrt(e2x * e2x + e2y * e2y) || 1
    const n1x =  e1y / l1, n1y = -e1x / l1   // outward normal of edge prev→curr
    const n2x =  e2y / l2, n2y = -e2x / l2   // outward normal of edge curr→next

    // Bisector of the two outward normals
    const bx = n1x + n2x, by = n1y + n2y
    const bl = Math.sqrt(bx * bx + by * by) || 1

    result.push({ x: curr.u + (bx / bl) * margin, z: curr.v + (by / bl) * margin })
  }
  return result
}

// ── Scratch objects (never held across await) ─────────────────────────────────
const _v3  = new THREE.Vector3()
const _v3b = new THREE.Vector3()
const _Y   = new THREE.Vector3(0, 1, 0)
const _Z   = new THREE.Vector3(0, 0, 1)

// ── Prism geometry builder ─────────────────────────────────────────────────────

/**
 * Build a closed, flat-shaded prism BufferGeometry.
 *
 * @param {Array<{x:number, z:number}>} corners  CCW polygon corners in local XZ plane
 * @param {number} halfH  half-height along +Y axis
 */
function _buildPrismGeometry(corners, halfH) {
  const N = corners.length
  const cx = corners.map(c => c.x)
  const cz = corners.map(c => c.z)

  const positions = []
  const normals   = []
  const indices   = []

  // ── Lateral faces ─────────────────────────────────────────────────────────
  // Outward normal of CCW edge i→j in the XZ plane = cross((0,1,0), edge).normalise()
  // edge = (cx[j]-cx[i], 0, cz[j]-cz[i]) → normal = (cz[j]-cz[i], 0, -(cx[j]-cx[i]))
  for (let i = 0; i < N; i++) {
    const j    = (i + 1) % N
    const base = i * 4

    positions.push(
      cx[i], -halfH, cz[i],
      cx[j], -halfH, cz[j],
      cx[j],  halfH, cz[j],
      cx[i],  halfH, cz[i],
    )

    const dx = cx[j] - cx[i], dz = cz[j] - cz[i]
    const nl = Math.sqrt(dz * dz + dx * dx) || 1
    const nx = dz / nl, nz = -dx / nl
    for (let k = 0; k < 4; k++) normals.push(nx, 0, nz)

    indices.push(base, base + 1, base + 2, base, base + 2, base + 3)
  }

  // ── Bottom cap ────────────────────────────────────────────────────────────
  const botRingBase = 4 * N
  for (let i = 0; i < N; i++) {
    positions.push(cx[i], -halfH, cz[i])
    normals.push(0, -1, 0)
  }
  const botCentre = botRingBase + N
  positions.push(0, -halfH, 0)
  normals.push(0, -1, 0)
  for (let i = 0; i < N; i++) {
    const j = (i + 1) % N
    indices.push(botCentre, botRingBase + j, botRingBase + i)
  }

  // ── Top cap ───────────────────────────────────────────────────────────────
  const topRingBase = botCentre + 1
  for (let i = 0; i < N; i++) {
    positions.push(cx[i], halfH, cz[i])
    normals.push(0, 1, 0)
  }
  const topCentre = topRingBase + N
  positions.push(0, halfH, 0)
  normals.push(0, 1, 0)
  for (let i = 0; i < N; i++) {
    const j = (i + 1) % N
    indices.push(topCentre, topRingBase + i, topRingBase + j)
  }

  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geo.setAttribute('normal',   new THREE.Float32BufferAttribute(normals,   3))
  geo.setIndex(indices)
  return geo
}

// ── Lattice exterior panel helpers ────────────────────────────────────────────

/**
 * For each cluster helix enumerate its canonical lattice-neighbour positions
 * (6 for HC, 4 for SQ) in local (U, V) space.  Neighbours absent from the
 * cluster form exterior faces grouped by canonical direction.
 *
 * Returns an array of panel descriptors { nu, nv, rOffset, tMin, tMax }
 * sorted CCW by normal angle.  rOffset is placed at the midpoint between the
 * outermost cluster helix and its vacant neighbour.
 *
 * @param {string[]}       helixIds   cluster helix IDs
 * @param {object}         helixAxes  { [hid]: { start:[x,y,z], end:[x,y,z] } }
 * @param {string}         latticeType  'HONEYCOMB' | 'SQUARE'
 * @param {THREE.Vector3}  U          cross-section U axis
 * @param {THREE.Vector3}  V          cross-section V axis
 * @param {THREE.Vector3}  centroid   world-space centroid
 */
function _computeExteriorPanels(helixIds, helixAxes, latticeType, U, V, centroid) {
  const isHC  = latticeType?.toUpperCase() !== 'SQUARE'
  const pitch = isHC ? HONEYCOMB_ROW_PITCH : SQUARE_HELIX_SPACING

  // ── 1. Project cluster helix midpoints into local (U, V) ─────────────────
  const helixUV = []
  for (const hid of helixIds) {
    const ax = helixAxes[hid]
    if (!ax) continue
    const mid = new THREE.Vector3(
      (ax.start[0] + ax.end[0]) * 0.5,
      (ax.start[1] + ax.end[1]) * 0.5,
      (ax.start[2] + ax.end[2]) * 0.5,
    ).sub(centroid)
    helixUV.push({ u: mid.dot(U), v: mid.dot(V) })
  }
  if (helixUV.length < 2) return []

  // ── 2. Derive canonical direction set from actual inter-helix offsets ─────
  // Find one helix pair whose UV distance equals the lattice pitch (±tol).
  // atan2 of that vector, snapped to the nearest half-angStep increment, is the
  // reference angle.  This works regardless of which world axes form the lattice
  // plane (XY, XZ, or YZ) — no world-space delta vectors needed.
  const pitchLo2 = (pitch - NEIGHBOR_TOL) ** 2
  const pitchHi2 = (pitch + NEIGHBOR_TOL) ** 2
  const nDirs    = isHC ? 6 : 4
  const angStep  = isHC ? Math.PI / 3 : Math.PI / 2

  let refAngle = null
  outer:
  for (let i = 0; i < helixUV.length; i++) {
    for (let j = 0; j < helixUV.length; j++) {
      if (i === j) continue
      const du = helixUV[j].u - helixUV[i].u
      const dv = helixUV[j].v - helixUV[i].v
      const d2 = du * du + dv * dv
      if (d2 >= pitchLo2 && d2 <= pitchHi2) {
        // Snap raw angle to nearest multiple of angStep/2 to align with the
        // canonical grid (HC: 30° increments; SQ: 45° increments)
        const raw = Math.atan2(dv, du)
        refAngle  = Math.round(raw / (angStep * 0.5)) * (angStep * 0.5)
        break outer
      }
    }
  }
  if (refAngle === null) return []   // isolated helix or bad data

  const canonicalDirs = Array.from({ length: nDirs }, (_, k) => {
    const a = refAngle + k * angStep
    return { nu: Math.cos(a), nv: Math.sin(a) }
  })

  // ── 3. Enumerate vacant neighbour slots → exterior face bins ─────────────
  const tol2 = NEIGHBOR_TOL * NEIGHBOR_TOL
  const bins  = canonicalDirs.map(() => /** @type {{u:number,v:number}[]} */([]))

  for (const { u, v } of helixUV) {
    for (let di = 0; di < nDirs; di++) {
      const { nu, nv } = canonicalDirs[di]
      const cu = u + nu * pitch
      const cv = v + nv * pitch
      let occupied = false
      for (const { u: ou, v: ov } of helixUV) {
        if ((ou - cu) ** 2 + (ov - cv) ** 2 < tol2) { occupied = true; break }
      }
      if (!occupied) bins[di].push({ u, v })
    }
  }

  // ── 4. Build one panel descriptor per non-empty bin ──────────────────────
  // Only helices within half-pitch of rMax are "boundary-layer" contributors.
  // Interior helices that see a vacant slot due to HC structural holes land
  // inside the cluster and would inflate the panel far beyond its real extent.
  // The panel is then limited to ±PANEL_HALF nm around the boundary helices.
  const PANEL_HALF = 1.5   // nm — half-width in tangential direction

  const panels = []
  for (let di = 0; di < nDirs; di++) {
    const contributors = bins[di]
    if (!contributors.length) continue

    const { nu, nv } = canonicalDirs[di]
    const pu = -nv, pv = nu   // CCW perpendicular (tangent along the panel face)

    // First pass: find outermost radial position
    let rMax = -Infinity
    for (const { u, v } of contributors) {
      const r = u * nu + v * nv
      if (r > rMax) rMax = r
    }

    // Second pass: tangential span of boundary-layer helices only
    let tMin = Infinity, tMax = -Infinity
    for (const { u, v } of contributors) {
      const r = u * nu + v * nv
      if (r < rMax - pitch * 0.5) continue   // skip interior / HC-hole contributors
      const t = u * pu + v * pv
      if (t < tMin) tMin = t
      if (t > tMax) tMax = t
    }

    panels.push({
      nu, nv,
      rOffset: rMax + pitch * 0.5,   // offset to midpoint of the vacant gap
      tMin: tMin - PANEL_HALF,
      tMax: tMax + PANEL_HALF,
    })
  }

  return { panels, helixUV }
}

/**
 * Compute cap polygon corners from CCW-sorted panels.
 *
 * Each panel contributes two corners: its start and end edge endpoints in UV
 * space (at tMin and tMax respectively).  Adjacent panels are connected by a
 * straight chamfer edge — no line intersections.  This guarantees the polygon
 * is bounded by the actual helix tangential extents and eliminates the spike
 * artifacts that arise when adjacent panels have different rOffset values.
 *
 * @param {Array<{nu,nv,rOffset,tMin,tMax}>} panels  sorted CCW by normal angle
 * @returns {Array<{x,z}>}  polygon corners in local (U, V = X, Z) space
 */
function _panelPolygonCorners(panels) {
  const corners = []
  for (const { nu, nv, rOffset, tMin, tMax } of panels) {
    // Panel tangent direction pu = (-nv, nu) is the CCW perpendicular.
    // Corner at tMin = start of this panel in CCW traversal order.
    // Corner at tMax = end of this panel, connected to tMin of next panel.
    corners.push({ x: nu * rOffset - nv * tMin, z: nv * rOffset + nu * tMin })
    corners.push({ x: nu * rOffset - nv * tMax, z: nv * rOffset + nu * tMax })
  }
  return corners
}

/**
 * Build a closed mesh geometry from exterior panels + triangulated top/bottom caps.
 * Each panel is a flat quad; all vertices on a panel share the same face normal,
 * so raycasting yields the canonical lattice direction directly.
 *
 * @param {Array<{nu,nv,rOffset,tMin,tMax}>} panels
 * @param {Array<{x,z}>}  capCorners  polygon corners for top/bottom caps
 * @param {number}        halfH       half-height along local Y (axial)
 */
function _buildPanelSurface(panels, capCorners, halfH) {
  const positions = [], normals = [], indices = []

  // ── Lateral panels ─────────────────────────────────────────────────────────
  for (const { nu, nv, rOffset, tMin, tMax } of panels) {
    const pu = -nv, pv = nu                   // CCW perpendicular direction
    const rx = rOffset * nu, rz = rOffset * nv
    const px1 = tMin * pu, pz1 = tMin * pv
    const px2 = tMax * pu, pz2 = tMax * pv

    const base = positions.length / 3
    positions.push(
      rx + px1, -halfH, rz + pz1,   // 0 BL
      rx + px2, -halfH, rz + pz2,   // 1 BR
      rx + px2,  halfH, rz + pz2,   // 2 TR
      rx + px1,  halfH, rz + pz1,   // 3 TL
    )
    for (let k = 0; k < 4; k++) normals.push(nu, 0, nv)
    indices.push(base, base + 1, base + 2, base, base + 2, base + 3)
  }

  // ── Bottom cap ────────────────────────────────────────────────────────────
  if (capCorners.length >= 3) {
    const cx = capCorners.map(c => c.x), cz = capCorners.map(c => c.z)
    const Nc = cx.length

    const botBase = positions.length / 3
    for (let i = 0; i < Nc; i++) { positions.push(cx[i], -halfH, cz[i]); normals.push(0, -1, 0) }
    const botCentre = positions.length / 3
    positions.push(0, -halfH, 0); normals.push(0, -1, 0)
    for (let i = 0; i < Nc; i++) {
      const j = (i + 1) % Nc
      indices.push(botCentre, botBase + j, botBase + i)
    }

    // ── Top cap ───────────────────────────────────────────────────────────
    const topBase = positions.length / 3
    for (let i = 0; i < Nc; i++) { positions.push(cx[i], halfH, cz[i]); normals.push(0, 1, 0) }
    const topCentre = positions.length / 3
    positions.push(0, halfH, 0); normals.push(0, 1, 0)
    for (let i = 0; i < Nc; i++) {
      const j = (i + 1) % Nc
      indices.push(topCentre, topBase + i, topBase + j)
    }
  }

  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geo.setAttribute('normal',   new THREE.Float32BufferAttribute(normals,   3))
  geo.setIndex(indices)
  return geo
}

// ── Bundle geometry helpers ────────────────────────────────────────────────────

/**
 * Compute all geometry needed to position and shape the cluster surface prism.
 *
 * Returns:
 *   { bundleDir, bundleMid, halfLen, rotQ, corners }
 * where:
 *   bundleMid  — world-space centre of the prism mesh
 *   rotQ       — quaternion rotating local (X, Y, Z) to world (U, D, V)
 *   corners    — [{x, z}] in local prism XZ ≡ world UV frame
 *
 * @param {object}   cluster          ClusterRigidTransform
 * @param {object}   helixAxes        { [hid]: { start:[x,y,z], end:[x,y,z] } }
 * @param {Array}    backbonePositions currentGeometry nucleotides (may be null/empty)
 * @param {number}   N                number of lateral faces
 * @param {number}   crossMargin      nm added around cross-section extents (default CROSS_MARGIN)
 * @param {number}   axialMargin      nm added to each axial end (default AXIAL_MARGIN)
 */
function _bundleGeometry(cluster, helixAxes, backbonePositions, N,
                         crossMargin = CROSS_MARGIN, axialMargin = AXIAL_MARGIN,
                         latticeType = null) {
  if (!helixAxes) return null

  // ── 1. Bundle axis direction ───────────────────────────────────────────────
  const dir = new THREE.Vector3()
  let axisCount = 0
  for (const hid of cluster.helix_ids) {
    const ax = helixAxes[hid]
    if (!ax) continue
    dir.add(_v3.set(...ax.end).sub(_v3b.set(...ax.start)))
    axisCount++
  }
  if (!axisCount || dir.lengthSq() < 1e-12) return null
  dir.normalize()

  // ── 2. Local cross-section frame (U, V) ⊥ D ──────────────────────────────
  const U = new THREE.Vector3()
  const cross = new THREE.Vector3().crossVectors(dir, _Y)
  if (cross.lengthSq() > 1e-4) {
    U.copy(cross).normalize()
  } else {
    U.crossVectors(dir, _Z).normalize()
  }
  const V = new THREE.Vector3().crossVectors(U, dir).normalize()  // right-handed: U×dir=V

  // ── 3. Collect positions to fit (backbone, fallback to axis endpoints) ────
  const helixSet = new Set(cluster.helix_ids)
  const pts = []

  // Helix IDs that contributed ≥1 dsDNA backbone point — used to restrict
  // the exterior panel computation to the double-stranded rigid body only,
  // excluding ssDNA connector and overhang-only helices from the cross-section.
  const dsHelixIds = new Set()

  if (backbonePositions?.length) {
    // Only include genuinely double-stranded positions.
    // Single-stranded nucleotides (overhangs, scaffold ends, loop/connecting segments)
    // are excluded by requiring that both backbone directions at a (helix, bp) position
    // have non-null strand coverage and neither belongs to an overhang domain.
    const dsCount = new Map()  // "hid:bp" → count of stranded, non-overhang nucleotides
    for (const nuc of backbonePositions) {
      if (!helixSet.has(nuc.helix_id) || !nuc.strand_id || nuc.overhang_id) continue
      const k = `${nuc.helix_id}:${nuc.bp_index}`
      dsCount.set(k, (dsCount.get(k) ?? 0) + 1)
    }
    for (const nuc of backbonePositions) {
      if (!helixSet.has(nuc.helix_id) || !nuc.strand_id || nuc.overhang_id) continue
      if ((dsCount.get(`${nuc.helix_id}:${nuc.bp_index}`) ?? 0) >= 2) {
        pts.push(new THREE.Vector3(...nuc.backbone_position))
        dsHelixIds.add(nuc.helix_id)
      }
    }
  }
  if (!pts.length) {
    // Axis-endpoint fallback: exclude very short connector helices (< 2 nm, roughly < 6 bp)
    // that would otherwise pull the hull centroid and extents away from the real bundle.
    const MIN_AXIS_LEN_SQ = 4.0  // 2 nm minimum
    const longAxes = []
    for (const hid of cluster.helix_ids) {
      const ax = helixAxes[hid]
      if (!ax) continue
      const lenSq = new THREE.Vector3(...ax.end).sub(new THREE.Vector3(...ax.start)).lengthSq()
      if (lenSq >= MIN_AXIS_LEN_SQ) longAxes.push(ax)
    }
    // If all helices are shorter than the threshold (pathological), include everything.
    const axesToUse = longAxes.length ? longAxes
      : cluster.helix_ids.map(hid => helixAxes[hid]).filter(Boolean)
    for (const ax of axesToUse) {
      pts.push(new THREE.Vector3(...ax.start), new THREE.Vector3(...ax.end))
    }
  }
  if (!pts.length) return null

  // ── 4. Compute centroid ────────────────────────────────────────────────────
  const centroid = new THREE.Vector3()
  for (const p of pts) centroid.add(p)
  centroid.divideScalar(pts.length)

  // ── 5. Project onto (U, V) and along D ────────────────────────────────────
  let minU = Infinity, maxU = -Infinity
  let minV = Infinity, maxV = -Infinity
  let minD = Infinity, maxD = -Infinity

  for (const p of pts) {
    const rel = _v3.copy(p).sub(centroid)
    const u = rel.dot(U), v = rel.dot(V), d = p.dot(dir)
    if (u < minU) minU = u;  if (u > maxU) maxU = u
    if (v < minV) minV = v;  if (v > maxV) maxV = v
    if (d < minD) minD = d;  if (d > maxD) maxD = d
  }

  const halfLen    = (maxD - minD) * 0.5 + axialMargin
  const axialMid   = (minD + maxD) * 0.5
  const bundleMid  = centroid.clone().addScaledVector(dir, axialMid - centroid.dot(dir))

  // ── 6. Rotation matrix: local (X, Y, Z) → world (U, D, V) ────────────────
  // This ensures local +X = U and local +Z = V, so prism corners in XZ ≡ UV.
  const rotQ = new THREE.Quaternion().setFromRotationMatrix(
    new THREE.Matrix4().makeBasis(U, dir, V)
  )

  // ── 7. Exterior panels — one per unoccupied lattice-neighbor direction ────────
  //
  // For each cluster helix, enumerate its canonical neighbour positions using
  // the lattice pitch geometry.  Any neighbour absent from the cluster forms an
  // exterior face.  Faces are grouped by canonical direction; each non-empty
  // group produces one rectangular panel.
  //
  // The top/bottom caps are built from the convex hull of helix UV positions
  // (expanded by crossMargin) rather than from panel line intersections.
  // Panel line intersections can produce spike corners far outside the cluster
  // for elongated or irregular clusters, while the hull always matches the
  // actual cluster cross-section.
  //
  // If fewer than 3 panels are found (degenerate or non-lattice cluster) we
  // fall back to the existing regular-polygon or bounding-rectangle approach.
  let corners, panels = null

  // Use only helices with dsDNA backbone positions for the exterior panel layout
  // so the cross-section doesn't extend into ssDNA connector / overhang rows.
  // Fall back to all cluster helices if backbone data isn't available.
  const panelHelixIds = dsHelixIds.size >= 3 ? [...dsHelixIds] : cluster.helix_ids
  const latticeResult = latticeType
    ? _computeExteriorPanels(panelHelixIds, helixAxes, latticeType, U, V, centroid)
    : null
  const rawPanels  = latticeResult?.panels  ?? []
  const rawHelixUV = latticeResult?.helixUV ?? []

  if (rawPanels.length >= 3) {
    rawPanels.sort((a, b) => Math.atan2(a.nv, a.nu) - Math.atan2(b.nv, b.nu))
    panels  = rawPanels
    // Cap corners = convex hull of helix UV positions, expanded outward.
    // This avoids the spike artefacts that line-intersection corners produce
    // for elongated or irregular clusters.
    const hull = _convexHull2D(rawHelixUV)
    corners = hull.length >= 3 ? _expandHullCorners(hull, crossMargin) : _panelPolygonCorners(rawPanels)
  } else {
    // Fallback: regular N-gon (existing behavior, used for non-lattice clusters)
    if (N === 4) {
      const hu = (maxU - minU) * 0.5 + crossMargin
      const hv = (maxV - minV) * 0.5 + crossMargin
      corners = [
        { x: -hu, z: -hv }, { x:  hu, z: -hv },
        { x:  hu, z:  hv }, { x: -hu, z:  hv },
      ]
    } else {
      let maxDist2 = 0
      for (const p of pts) {
        const rel = _v3.copy(p).sub(centroid)
        const u = rel.dot(U), v = rel.dot(V)
        const d2 = u * u + v * v
        if (d2 > maxDist2) maxDist2 = d2
      }
      const r = Math.sqrt(maxDist2) + crossMargin
      corners = Array.from({ length: N }, (_, i) => ({
        x: r * Math.cos(2 * Math.PI * i / N),
        z: r * Math.sin(2 * Math.PI * i / N),
      }))
    }
  }

  return { bundleDir: dir.clone(), bundleMid, halfLen, rotQ, corners, panels, axialMid }
}

// ── Axis indicator builders ────────────────────────────────────────────────────

function _orientQ(dir3) {
  const q = new THREE.Quaternion()
  const ax = new THREE.Vector3(...dir3).normalize()
  if (Math.abs(ax.dot(_Y)) < 0.9999) {
    q.setFromUnitVectors(_Y, ax)
  } else if (ax.y < 0) {
    q.setFromAxisAngle(_Z, Math.PI)
  }
  return { q, ax }
}

/** Persistent joint axis indicator — same style as the hover preview arrow. */
function _buildAxisIndicator(origin, direction) {
  const { q, ax } = _orientQ(direction)
  const group = new THREE.Group()
  group.name = 'clusterJointIndicator'
  group.userData.tag = 'cluster-joint-indicator'
  const mat   = new THREE.MeshBasicMaterial({ color: 0xffffff, depthTest: false, depthWrite: false, transparent: true })

  // Shaft
  const shaft = new THREE.Mesh(
    new THREE.CylinderGeometry(PREV_SHAFT_R, PREV_SHAFT_R, PREV_HALF_LEN * 2, 8),
    mat,
  )
  shaft.renderOrder = 9999
  group.add(shaft)

  // Arrowhead at the +Y tip
  const cone = new THREE.Mesh(new THREE.ConeGeometry(PREV_TIP_R, PREV_TIP_H, 8), mat)
  cone.position.y = PREV_HALF_LEN + PREV_TIP_H * 0.5
  cone.renderOrder = 9999
  group.add(cone)

  // Radial checkerboard sprite at axis_origin (base of arrow)
  const spriteMat = new THREE.MeshBasicMaterial({
    map: _buildCheckerTexture(), transparent: true,
    depthTest: false, depthWrite: false, side: THREE.DoubleSide,
  })
  const sprite = new THREE.Mesh(new THREE.PlaneGeometry(SPRITE_SIZE, SPRITE_SIZE), spriteMat)
  sprite.rotation.x  = -Math.PI / 2
  sprite.position.y  = -PREV_HALF_LEN
  sprite.renderOrder = 9999
  group.add(sprite)

  // Rotation ring — circumscribes the sprite square; drag to rotate the cluster.
  // Radius = half-diagonal of the sprite square so it sits just outside the disc.
  const ringMat  = new THREE.MeshBasicMaterial({ color: 0xffffff, depthTest: false, depthWrite: false, transparent: true })
  const ringMesh = new THREE.Mesh(
    new THREE.TorusGeometry(SPRITE_SIZE / 2 * Math.SQRT2, 0.08, 8, 48),
    ringMat,
  )
  ringMesh.rotation.x          = -Math.PI / 2       // perpendicular to axis direction
  ringMesh.position.y          = -PREV_HALF_LEN + 1  // 1 nm above the surface
  ringMesh.renderOrder         = 9999
  ringMesh.userData.isJointRing = true
  group.add(ringMesh)

  // Orient group so local +Y = direction; place centre PREV_HALF_LEN above origin
  // so the arrow base sits at axis_origin and tip points outward.
  group.quaternion.copy(q)
  group.position.copy(new THREE.Vector3(...origin)).addScaledVector(ax, PREV_HALF_LEN)
  group.renderOrder = 1000
  return group
}

/**
 * Build a radial checkerboard CanvasTexture for the surface sprite.
 * Alternates angular sectors and radial bands (polar chessboard).
 * Fades to transparent at the outer edge.
 */
function _buildCheckerTexture(size = 256, sectors = 8, rings = 4) {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const ctx    = canvas.getContext('2d')
  const cx = size / 2, cy = size / 2
  const maxR   = size / 2

  const imageData = ctx.createImageData(size, size)
  const data      = imageData.data

  // Colour A: white (255, 255, 255)
  // Colour B: dark grey (60, 60, 60)
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = x - cx, dy = y - cy
      const r  = Math.sqrt(dx * dx + dy * dy)
      if (r >= maxR) continue

      const normR  = r / maxR                                   // [0, 1)
      const angle  = Math.atan2(dy, dx) + Math.PI              // [0, 2π)
      const sector = Math.floor(angle / (2 * Math.PI / sectors))
      const band   = Math.floor(normR * rings)
      const isA    = (sector + band) % 2 === 0
      const fade   = Math.pow(1 - normR, 0.7)                  // smooth edge fade
      const lum    = isA ? 255 : 60

      const i      = (y * size + x) * 4
      data[i]     = lum
      data[i + 1] = lum
      data[i + 2] = lum
      data[i + 3] = Math.round(fade * 230)
    }
  }

  ctx.putImageData(imageData, 0, 0)
  return new THREE.CanvasTexture(canvas)
}

/** Ghost preview: short directional arrow shown on mouse-hover. */
function _buildPreviewMesh() {
  const group = new THREE.Group()
  const mat   = new THREE.MeshBasicMaterial({
    color: PREVIEW_COLOUR, transparent: true, opacity: PREV_OPACITY,
    depthTest: false, depthWrite: false,
  })

  // Shaft
  const shaft = new THREE.Mesh(
    new THREE.CylinderGeometry(PREV_SHAFT_R, PREV_SHAFT_R, PREV_HALF_LEN * 2, 8),
    mat,
  )
  shaft.renderOrder = 9999
  group.add(shaft)

  // Single arrowhead at the +Y tip
  const cone = new THREE.Mesh(new THREE.ConeGeometry(PREV_TIP_R, PREV_TIP_H, 8), mat)
  cone.position.y = PREV_HALF_LEN + PREV_TIP_H * 0.5
  cone.renderOrder = 9999
  group.add(cone)

  // Radial checkerboard sprite — flat disc lying on the surface.
  // PlaneGeometry default: XY plane, face normal = +Z.
  // After rotation.x = -π/2: XZ plane, face normal = +Y.
  // In the group's local frame +Y = outward face normal (world-space), so the
  // sprite lies flat against the surface.  position.y = -PREV_HALF_LEN moves it
  // back down from the group centre (which sits PREV_HALF_LEN above hit.point)
  // to the surface itself.
  const spriteMat = new THREE.MeshBasicMaterial({
    map: _buildCheckerTexture(), transparent: true,
    depthTest: false, depthWrite: false, side: THREE.DoubleSide,
  })
  const sprite = new THREE.Mesh(new THREE.PlaneGeometry(SPRITE_SIZE, SPRITE_SIZE), spriteMat)
  sprite.rotation.x  = -Math.PI / 2
  sprite.position.y  = -PREV_HALF_LEN
  sprite.renderOrder = 9999
  group.add(sprite)

  group.visible     = false
  group.renderOrder = 9999
  return group
}

// ── Ring line builders (module-level pure functions) ──────────────────────────

/**
 * Flat position array for one polygon ring at local Y = localY.
 * Returns 6 * N floats — N segments, 2 vertices (x,y,z) each.
 */
function _prismRingPositions(corners, localY) {
  const N   = corners.length
  const out = new Float32Array(N * 6)
  let i6 = 0
  for (let i = 0; i < N; i++) {
    const j = (i + 1) % N
    out[i6++] = corners[i].x; out[i6++] = localY; out[i6++] = corners[i].z
    out[i6++] = corners[j].x; out[i6++] = localY; out[i6++] = corners[j].z
  }
  return out
}

/**
 * Build static periodic grid rings — one LineSegments object.
 * @param {object} bg          result of _bundleGeometry
 * @param {number} periodBp    bp interval between rings
 * @param {number} risePerBp   nm per bp
 */
function _buildGridLines(bg, periodBp, risePerBp) {
  const { corners, halfLen, rotQ, bundleMid } = bg
  const periodNm = periodBp * risePerBp
  const positions = []

  for (let localY = -halfLen; localY <= halfLen + 1e-6; localY += periodNm) {
    const ring = _prismRingPositions(corners, localY)
    for (const v of ring) positions.push(v)
  }
  if (!positions.length) return null

  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  const mat = new THREE.LineBasicMaterial({
    color: new THREE.Color(GRID_R, GRID_G, GRID_B),
    transparent: true, opacity: 0.55,
    depthTest: false, depthWrite: false,
  })
  const lines = new THREE.LineSegments(geo, mat)
  lines.quaternion.copy(rotQ)
  lines.position.copy(bundleMid)
  lines.renderOrder = 102
  return lines
}

/**
 * Build per-bp hover grid — a LineSegments covering the full axial range, one
 * ring per bp, initially invisible (all vertex colours = 0).  Updated every
 * pointermove via _updateHoverGrid.
 *
 * @returns {{ lines: THREE.LineSegments, ringYs: Float32Array, vertsPerRing: number }}
 */
function _buildHoverLines(bg, risePerBp) {
  const { corners, halfLen, rotQ, bundleMid } = bg
  const N = corners.length

  // Pre-compute all ring Y positions (local space)
  const ringYsList = []
  for (let localY = -halfLen; localY <= halfLen + 1e-6; localY += risePerBp) {
    ringYsList.push(localY)
  }
  const ringYs      = new Float32Array(ringYsList)
  const vertsPerRing = N * 2                         // 2 verts per segment, N segments
  const totalVerts   = ringYs.length * vertsPerRing

  const pos = new Float32Array(totalVerts * 3)
  const col = new Float32Array(totalVerts * 3)  // initially all 0 → invisible on dark bg

  let vi = 0
  for (const localY of ringYs) {
    const ring = _prismRingPositions(corners, localY)
    pos.set(ring, vi * 3)
    vi += vertsPerRing
  }

  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  const colAttr = new THREE.Float32BufferAttribute(col, 3)
  colAttr.usage = THREE.DynamicDrawUsage
  geo.setAttribute('color', colAttr)

  const mat = new THREE.LineBasicMaterial({
    vertexColors: true, transparent: true, opacity: 1.0,
    depthTest: false, depthWrite: false,
  })
  const lines = new THREE.LineSegments(geo, mat)
  lines.quaternion.copy(rotQ)
  lines.position.copy(bundleMid)
  lines.renderOrder = 103
  lines.visible = false   // only visible when hovering

  return { lines, ringYs, vertsPerRing }
}

const HULL_OPACITY = 0.72

function _hullMeshPhong(opacity) {
  return new THREE.MeshPhongMaterial({
    color: HULL_COLOUR, transparent: true, opacity,
    side: THREE.DoubleSide, depthWrite: false, shininess: 60,
    specular: new THREE.Color(0x88ccff),
    polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
  })
}

// Drop extrusion blocks whose volume is below `fraction` of the total — removes
// tiny stub segments that clutter the hull. Takes [{geo, vol}], returns the geos
// to keep (disposing the dropped ones). Never returns empty: if every block is
// below threshold (e.g. many equal blocks), keeps the largest so the hull
// doesn't vanish.
function _filterSmallBlocks(boxes, fraction) {
  if (!boxes.length) return []
  const total = boxes.reduce((s, b) => s + b.vol, 0)
  const thresh = fraction * total
  let kept = boxes.filter(b => b.vol >= thresh)
  if (!kept.length) {
    let big = boxes[0]
    for (const b of boxes) if (b.vol > big.vol) big = b
    kept = [big]
  }
  const keptSet = new Set(kept)
  for (const b of boxes) if (!keptSet.has(b)) b.geo.dispose()
  return kept.map(b => b.geo)
}

// Like _filterSmallBlocks but returns the KEPT box RECORDS ({geo, vol, …}) so
// downstream per-cluster bucketing can still see helixIds/swept on survivors.
// Dropped boxes' geometries are disposed.
function _keepLargeBlocks(boxes, fraction) {
  if (!boxes.length) return []
  const total  = boxes.reduce((s, b) => s + b.vol, 0)
  const thresh = fraction * total
  let kept = boxes.filter(b => b.vol >= thresh)
  if (!kept.length) {
    let big = boxes[0]
    for (const b of boxes) if (b.vol > big.vol) big = b
    kept = [big]
  }
  const keptSet = new Set(kept)
  for (const b of boxes) if (!keptSet.has(b)) b.geo.dispose()
  return kept
}

// World matrix for a ClusterRigidTransform: p' = R·(p − pivot) + pivot + T.
// Returns null for an identity (no-op) transform so callers can skip baking.
function _clusterMatrix(cluster) {
  const T = cluster.translation || [0, 0, 0]
  const R = cluster.rotation    || [0, 0, 0, 1]
  const P = cluster.pivot       || [0, 0, 0]
  const isIdentity =
    Math.abs(T[0]) < 1e-9 && Math.abs(T[1]) < 1e-9 && Math.abs(T[2]) < 1e-9 &&
    Math.abs(R[0]) < 1e-9 && Math.abs(R[1]) < 1e-9 && Math.abs(R[2]) < 1e-9 &&
    Math.abs(R[3] - 1) < 1e-9
  if (isIdentity) return null
  const quat = new THREE.Quaternion(R[0], R[1], R[2], R[3])
  return new THREE.Matrix4()
    .makeTranslation(P[0] + T[0], P[1] + T[1], P[2] + T[2])
    .multiply(new THREE.Matrix4().makeRotationFromQuaternion(quat))
    .multiply(new THREE.Matrix4().makeTranslation(-P[0], -P[1], -P[2]))
}

// (helix_id, bp) → index into `clusters` (the supplied cluster subset), or -1 when
// that base belongs to no cluster in the subset. Resolves at DOMAIN granularity so
// a sub-helix (domain-level) cluster — including a partial-coverage "bridge" helix
// where only some domains move — is attributed correctly, base by base. Reuses the
// canonical buildClusterLookup (the same domain/bridge rule used for cluster colour)
// and maps its global cluster index onto the subset.
function _buildBpClusterResolver(design, clusters) {
  const lookup = buildClusterLookup(design)             // (nuc) → global cluster index
  const globalIdxById = new Map((design.cluster_transforms ?? []).map((c, i) => [c.id, i]))
  const subsetByGlobal = new Map()                      // global index → subset index
  clusters.forEach((c, si) => {
    const gi = globalIdxById.get(c.id)
    if (gi !== undefined) subsetByGlobal.set(gi, si)
  })

  // Per-helix sorted domain bp ranges so (helix, bp) maps to a (strand_id, domain_index).
  const domsByHelix = new Map()
  for (const s of (design.strands ?? [])) {
    const doms = s.domains ?? []
    for (let di = 0; di < doms.length; di++) {
      const d = doms[di]
      if (!d?.helix_id) continue
      const lo = Math.min(d.start_bp, d.end_bp), hi = Math.max(d.start_bp, d.end_bp)
      let arr = domsByHelix.get(d.helix_id)
      if (!arr) { arr = []; domsByHelix.set(d.helix_id, arr) }
      arr.push({ lo, hi, strand_id: s.id, domain_index: di })
    }
  }
  for (const arr of domsByHelix.values()) arr.sort((a, b) => a.lo - b.lo)

  return (helixId, bp) => {
    const arr = domsByHelix.get(helixId)
    let nuc = { helix_id: helixId }
    if (arr) {
      for (const d of arr) {
        if (bp >= d.lo && bp <= d.hi) { nuc = { helix_id: helixId, strand_id: d.strand_id, domain_index: d.domain_index }; break }
      }
    }
    const gi = lookup(nuc)
    return (gi != null && subsetByGlobal.has(gi)) ? subsetByGlobal.get(gi) : -1
  }
}

// Bundle frame for a set of helices: average axis direction → (U, dir, V),
// origin = centroid of helix midpoints. Same convention as _scanExtrusionGroup.
function _bundleFrame(helixIds, helixAxes) {
  const dir = new THREE.Vector3()
  const mids = []
  for (const hid of helixIds) {
    const ax = helixAxes[hid]
    if (!ax?.start || !ax?.end) continue
    const s = new THREE.Vector3(...ax.start), e = new THREE.Vector3(...ax.end)
    dir.add(e.clone().sub(s))
    mids.push(s.clone().add(e).multiplyScalar(0.5))
  }
  if (!mids.length) return null
  if (dir.lengthSq() < 1e-12) dir.set(0, 0, 1)
  dir.normalize()
  const U = new THREE.Vector3()
  const cz = new THREE.Vector3().crossVectors(dir, new THREE.Vector3(0, 1, 0))
  if (cz.lengthSq() > 1e-4) U.copy(cz).normalize()
  else U.crossVectors(dir, new THREE.Vector3(0, 0, 1)).normalize()
  const V = new THREE.Vector3().crossVectors(U, dir).normalize()
  const origin = new THREE.Vector3()
  for (const m of mids) origin.add(m)
  origin.divideScalar(mids.length)
  return { dir, U, V, origin }
}

/**
 * Color-coded overhang markers for the hull: one small flat quad per overhang,
 * snapped flush (parallel + slightly offset) to the lateral hull face nearest
 * its root, colored by the overhang strand's color. Merged into a single
 * vertex-colored mesh (one draw call). Returns a THREE.Group or null.
 *
 * Each cluster's bundle frame (U/dir/V) + cross-section rect (matching the
 * rendered boxes' faces, padded by half the helix spacing) determines the face
 * plane; the quad's normal is that face's normal so it lies parallel to it.
 */
function _buildOverhangMarkers(design, helixAxes, clusters, geometry, helixBp, hullMeshes) {
  const overhangs = design?.overhangs
  if (!overhangs?.length || !helixAxes || !clusters?.length || !hullMeshes?.length) return null

  const strandColor = new Map()
  for (const s of design.strands ?? []) if (s.color) strandColor.set(s.id, s.color)

  // Current (transformed) overhang nucleotide positions, grouped by overhang id
  // (NOT the stored base-frame pivot, which goes stale under cluster transforms).
  const ohNuc = new Map()
  for (const n of geometry ?? []) {
    if (!n.overhang_id || !n.backbone_position) continue
    let arr = ohNuc.get(n.overhang_id)
    if (!arr) { arr = []; ohNuc.set(n.overhang_id, arr) }
    arr.push(n.backbone_position)
  }

  // Per-cluster bundle frame (origin + axis dir, from dsDNA helices) for the
  // radial cast direction; helix → cluster index for every helix.
  const frames = []
  const helixToCluster = new Map()
  clusters.forEach((cl, ci) => {
    const allIds = cl.helix_ids ?? []
    for (const hid of allIds) if (!helixToCluster.has(hid)) helixToCluster.set(hid, ci)
    const dsIds = allIds.filter(hid => (helixBp?.get(hid) ?? 1) > 0)
    frames.push(_bundleFrame(dsIds.length ? dsIds : allIds, helixAxes))
  })

  // Hull meshes need an up-to-date world matrix for raycasting (boxes are baked
  // at identity, but cluster prism meshes carry a transform).
  for (const hm of hullMeshes) hm.updateWorldMatrix(true, false)

  const QUAD = 1.6, EPS = 0.08
  const col = new THREE.Color(), zAxis = new THREE.Vector3(0, 0, 1)
  const rc = new THREE.Raycaster()
  const root = new THREE.Vector3(), rel = new THREE.Vector3(), radial = new THREE.Vector3()
  const geos = []
  for (const oh of overhangs) {
    const ci = helixToCluster.get(oh.helix_id)
    if (ci == null) continue
    const fr = frames[ci]
    if (!fr) continue

    // Root = overhang nucleotide nearest the bundle axis (the junction); else
    // the current helix midpoint.
    let found = false
    const nucs = ohNuc.get(oh.id)
    if (nucs && nucs.length) {
      let bestR2 = Infinity
      for (const p of nucs) {
        rel.set(p[0], p[1], p[2]).sub(fr.origin)
        const r2 = rel.dot(fr.U) ** 2 + rel.dot(fr.V) ** 2
        if (r2 < bestR2) { bestR2 = r2; root.set(p[0], p[1], p[2]); found = true }
      }
    } else {
      const ax = helixAxes[oh.helix_id]
      if (ax?.start && ax?.end) {
        root.set((ax.start[0] + ax.end[0]) / 2, (ax.start[1] + ax.end[1]) / 2, (ax.start[2] + ax.end[2]) / 2)
        found = true
      }
    }
    if (!found) continue

    // Radial outward (perpendicular to the bundle axis).
    rel.copy(root).sub(fr.origin)
    radial.copy(rel).addScaledVector(fr.dir, -rel.dot(fr.dir))
    if (radial.lengthSq() < 1e-6) radial.copy(fr.U)
    radial.normalize()

    // Cast inward from outside the bundle, through the root, onto the hull —
    // the first hit IS the rendered surface, so the marker lands flush on it.
    rc.set(root.clone().addScaledVector(radial, 8), radial.clone().negate())
    let best = Infinity, hit = null
    for (const hm of hullMeshes) {
      const hits = rc.intersectObject(hm, false)
      if (hits.length && hits[0].distance < best) { best = hits[0].distance; hit = hits[0] }
    }
    if (!hit) continue

    const normal = hit.face
      ? hit.face.normal.clone().transformDirection(hit.object.matrixWorld).normalize()
      : radial.clone()
    if (normal.dot(radial) < 0) normal.negate()   // ensure outward-facing
    const center = hit.point.clone().addScaledVector(normal, EPS)

    const geo = new THREE.PlaneGeometry(QUAD, QUAD)
    geo.applyMatrix4(new THREE.Matrix4().makeRotationFromQuaternion(
      new THREE.Quaternion().setFromUnitVectors(zAxis, normal)))
    geo.translate(center.x, center.y, center.z)

    col.set(strandColor.get(oh.strand_id) || '#ff8800')
    const nv = geo.attributes.position.count
    const cArr = new Float32Array(nv * 3)
    for (let i = 0; i < nv; i++) { cArr[i * 3] = col.r; cArr[i * 3 + 1] = col.g; cArr[i * 3 + 2] = col.b }
    geo.setAttribute('color', new THREE.BufferAttribute(cArr, 3))
    geos.push(geo)
  }
  if (!geos.length) return null
  const merged = mergeGeometries(geos, false)
  geos.forEach(g => g.dispose())
  if (!merged) return null

  const mesh = new THREE.Mesh(merged, new THREE.MeshBasicMaterial({
    vertexColors: true, side: THREE.DoubleSide,
    polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
  }))
  mesh.renderOrder = 105
  const group = new THREE.Group()
  group.add(mesh)
  return group
}

// Solid neutral-grey material for the extrusion hull — opaque, lit, CAD-default
// look (no transparency, writes depth so it reads as a solid object).
function _extrusionMeshMat() {
  return new THREE.MeshPhongMaterial({
    color: 0x9a9a9a,
    side: THREE.DoubleSide,
    shininess: 16,
    specular: new THREE.Color(0x2a2a2a),
    polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
  })
}

// Distinct, well-separated hues for the per-cluster hull debug overlay.
const _HULL_DEBUG_PALETTE = [
  0xff5252, 0x40c4ff, 0x69f0ae, 0xffd740, 0xb388ff,
  0xff6e40, 0x18ffff, 0xeeff41, 0xff4081, 0x64ffda,
]

/**
 * Per-helix dsDNA base-pair counts for a design's geometry.
 * A base pair = a (helix, bp_index) position covered by ≥2 stranded,
 * non-overhang nucleotides (i.e. genuinely double-stranded).
 * Returns { helixBp: Map<helixId, bpCount>, totalBp }.
 */
function _dsBpByHelix(geometry) {
  const dsCount = new Map()   // "hid:bp" → covered-strand count
  for (const nuc of geometry ?? []) {
    if (!nuc.strand_id || nuc.overhang_id) continue
    const k = `${nuc.helix_id}:${nuc.bp_index}`
    dsCount.set(k, (dsCount.get(k) ?? 0) + 1)
  }
  const helixBp = new Map()
  for (const [k, c] of dsCount) {
    if (c < 2) continue
    const hid = k.slice(0, k.lastIndexOf(':'))
    helixBp.set(hid, (helixBp.get(hid) ?? 0) + 1)
  }
  let totalBp = 0
  for (const v of helixBp.values()) totalBp += v
  return { helixBp, totalBp }
}

/**
 * Per-helix dsDNA bp-INDEX range [minBp, maxBp] (inclusive) over genuinely
 * double-stranded positions (a (helix, bp_index) covered by ≥2 stranded,
 * non-overhang nucleotides). Unlike the feature-log op's length_bp/offset — which
 * goes STALE once scaffold routing / continuations extend the helices past the
 * original bundle — this reflects the part's ACTUAL axial extent, so the hull box
 * lines up with the cylinder/full rep (back-porch ends, staggered helix starts).
 * Returns Map<helixId, [minBp, maxBp]>.
 */
function _dsBpRangeByHelix(geometry) {
  const dsCount = new Map()   // "hid:bp" → covered-strand count
  for (const nuc of geometry ?? []) {
    if (!nuc.strand_id || nuc.overhang_id) continue
    dsCount.set(`${nuc.helix_id}:${nuc.bp_index}`, (dsCount.get(`${nuc.helix_id}:${nuc.bp_index}`) ?? 0) + 1)
  }
  const range = new Map()
  for (const [k, c] of dsCount) {
    if (c < 2) continue
    const i = k.lastIndexOf(':')
    const hid = k.slice(0, i), bp = +k.slice(i + 1)
    const r = range.get(hid)
    if (!r) range.set(hid, [bp, bp])
    else { if (bp < r[0]) r[0] = bp; if (bp > r[1]) r[1] = bp }
  }
  return range
}

/** Canvas-textured sprite for a cluster debug label (name + size %). */
function _makeClusterLabelSprite(text, colorHex) {
  const pad = 8, fontPx = 36
  const cv = document.createElement('canvas')
  const ctx = cv.getContext('2d')
  ctx.font = `bold ${fontPx}px sans-serif`
  const w = Math.ceil(ctx.measureText(text).width) + pad * 2
  const h = fontPx + pad * 2
  cv.width = w; cv.height = h
  ctx.font = `bold ${fontPx}px sans-serif`
  ctx.fillStyle = 'rgba(13,17,23,0.82)'
  ctx.fillRect(0, 0, w, h)
  ctx.strokeStyle = `#${colorHex.toString(16).padStart(6, '0')}`
  ctx.lineWidth = 4
  ctx.strokeRect(2, 2, w - 4, h - 4)
  ctx.fillStyle = '#fff'
  ctx.textBaseline = 'middle'
  ctx.fillText(text, pad, h / 2)
  const tex = new THREE.CanvasTexture(cv)
  tex.minFilter = THREE.LinearFilter
  const spr = new THREE.Sprite(new THREE.SpriteMaterial({
    map: tex, transparent: true, depthTest: false, depthWrite: false,
  }))
  spr.renderOrder = 102
  // Scale sprite to ~nm world size proportional to its aspect ratio.
  const worldH = 4.0
  spr.scale.set(worldH * (w / h), worldH, 1)
  return spr
}

/** Median nearest-neighbour distance among helix axis start points (≈ the
 *  lattice spacing). Used to size the per-helix occupancy boxes. */
function _helixSpacing(helixAxes, helixIds, fallback = 2.5) {
  const pts = []
  for (const hid of helixIds) {
    const ax = helixAxes[hid]
    if (ax?.start) pts.push(new THREE.Vector3(...ax.start))
  }
  if (pts.length < 2) return fallback
  const nn = []
  for (let i = 0; i < pts.length; i++) {
    let best = Infinity
    for (let j = 0; j < pts.length; j++) {
      if (i === j) continue
      const d = pts[i].distanceTo(pts[j])
      if (d < best) best = d
    }
    if (Number.isFinite(best)) nn.push(best)
  }
  if (!nn.length) return fallback
  nn.sort((a, b) => a - b)
  return nn[Math.floor(nn.length / 2)] || fallback
}

/**
 * Per-helix occupancy boxes for one cluster, merged into a single mesh.
 *
 * Each dsDNA helix (helixBp>0; pure ss/overhang helices skipped) becomes an
 * oriented box spanning its axis, cross-section = spacing*fill so inter-helix
 * grooves survive (the "toothy" surface).  All boxes share the cluster's bundle
 * (U, dir, V) frame so they stay co-aligned.  Helices of differing length yield
 * boxes of differing extent → axial teeth fall out for free.  Returns a
 * THREE.Group (merged mesh + edges) with userData.bundleMid / clusterName, or null.
 */
function _buildClusterBoxGroup(cluster, helixAxes, helixBp, spacing, boxFill) {
  // Bundle frame from the average axis direction (same convention as _bundleGeometry).
  const dir = new THREE.Vector3()
  let nDir = 0
  for (const hid of cluster.helix_ids) {
    const ax = helixAxes[hid]
    if (!ax?.start || !ax?.end) continue
    dir.add(new THREE.Vector3(...ax.end).sub(new THREE.Vector3(...ax.start)))
    nDir++
  }
  if (!nDir || dir.lengthSq() < 1e-12) return null
  dir.normalize()
  const U = new THREE.Vector3()
  const cz = new THREE.Vector3().crossVectors(dir, new THREE.Vector3(0, 1, 0))
  if (cz.lengthSq() > 1e-4) U.copy(cz).normalize()
  else U.crossVectors(dir, new THREE.Vector3(0, 0, 1)).normalize()
  const V = new THREE.Vector3().crossVectors(U, dir).normalize()
  const quat = new THREE.Quaternion().setFromRotationMatrix(
    new THREE.Matrix4().makeBasis(U, dir, V))   // local +Y → dir

  const w = Math.max(0.5, spacing * boxFill)
  const geos = []
  const centroid = new THREE.Vector3()
  let nMid = 0
  for (const hid of cluster.helix_ids) {
    if ((helixBp.get(hid) ?? 0) <= 0) continue   // skip pure ss / overhang helices
    const ax = helixAxes[hid]
    if (!ax?.start || !ax?.end) continue
    const s = new THREE.Vector3(...ax.start), e = new THREE.Vector3(...ax.end)
    const len = s.distanceTo(e)
    if (len < 1e-6) continue
    const mid = s.clone().add(e).multiplyScalar(0.5)
    centroid.add(mid); nMid++
    const geo = new THREE.BoxGeometry(w, len, w)   // length on local Y = bundle dir
    geo.applyMatrix4(new THREE.Matrix4().compose(mid, quat, new THREE.Vector3(1, 1, 1)))
    geos.push(geo)
  }
  if (!geos.length) return null
  centroid.divideScalar(nMid || 1)

  const merged = mergeGeometries(geos, false)
  geos.forEach(g => g.dispose())
  if (!merged) return null

  const group = new THREE.Group()
  group.userData.bundleMid   = centroid
  group.userData.clusterName = cluster.name || 'Cluster'
  const mesh = new THREE.Mesh(merged, _hullMeshPhong(0.9))
  mesh.renderOrder = 100
  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(merged, 1),
    new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.5, depthWrite: false }),
  )
  edges.renderOrder = 101
  group.add(mesh, edges)
  return group
}

// Feature-log ops that create an extrusion with a lattice cross-section.
const _EXTRUSION_OPS = new Set([
  'bundle-create', 'extrude-segment', 'extrude-continuation', 'extrude-deformed-continuation',
])

// bp per deformed-axis sample — MUST match backend deformation._AXIS_SAMPLE_STEP (7).
// Used to map an extrusion box's global bp range onto its helices' sample indices.
const _AXIS_SAMPLE_STEP = 7

// Plane → which world axis each lattice coordinate maps to.
// col → cross-section axis A, row → cross-section axis B, extrusion runs along the third.
const _PLANE_AXES = {
  XY: { col: 0, row: 1, ext: 2 },
  XZ: { col: 0, row: 2, ext: 1 },
  YZ: { col: 1, row: 2, ext: 0 },
}

// Split a list of [row, col] cells into 4-neighbour (Manhattan-1) connected
// components.  An extrusion that spans lattice-disconnected regions (e.g. the
// two arms of a hinge separated by an empty row gap) then renders as one hull
// block per region — mirroring the backend's per-region bundle clustering
// (Onshape-style: disjoint sketch regions → separate part bodies).  Cells in
// one contiguous region return a single component, so connected bundles are
// unaffected.
function _cellComponents(cells) {
  const key = (r, c) => `${r},${c}`
  const present = new Set(cells.map(([r, c]) => key(r, c)))
  const seen = new Set()
  const comps = []
  for (const [r0, c0] of cells) {
    if (seen.has(key(r0, c0))) continue
    const comp = []
    const stack = [[r0, c0]]
    seen.add(key(r0, c0))
    while (stack.length) {
      const [r, c] = stack.pop()
      comp.push([r, c])
      for (const [dr, dc] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const nk = key(r + dr, c + dc)
        if (present.has(nk) && !seen.has(nk)) { seen.add(nk); stack.push([r + dr, c + dc]) }
      }
    }
    comps.push(comp)
  }
  return comps
}

/**
 * One rectangular box per feature-log extrusion, merged into a single mesh.
 *
 * Each bundle-create / extrude-* entry carries the lattice ``cells`` it spans,
 * its ``length_bp``, the build ``plane``, and the axial ``offset_nm`` — enough
 * to reconstruct a rectangular cross-section (bounding rect of the cells) over
 * the extrusion's axial run.  Alternating cross-sections along the axis (e.g.
 * teeth: full ↔ half) reproduce the toothy silhouette directly from the build
 * history.  Coordinates are build-space (≈ world for as-built parts).
 *
 * Returns a THREE.Group (merged mesh + edges) or null when the design has no
 * extrusion history (e.g. a cadnano import).
 *
 * When ``opts.clusters`` is supplied (a subset of ClusterRigidTransforms), each
 * straight box is DECOMPOSED base-by-base: every cell × bp slice is attributed to
 * its owning cluster via a (helix, bp) resolver, and sub-boxes are emitted per
 * cluster per axial run. This handles helix-level clusters, full-coverage
 * domain-level clusters, AND sub-helix PARTIAL coverage (a box that straddles a
 * cluster boundary axially or across its cross-section splits cleanly). Each
 * sub-box has its cluster's rigid transform baked in. Deformed/swept boxes are
 * NOT decomposed or re-baked (their spine samples are already cluster-transformed
 * by the backend) — they're attributed whole, by majority.
 *   - ``opts.keyByCluster`` (design view): return a
 *     ``Map<clusterId|'__extrusions__', THREE.Group>`` so each cluster's hull is a
 *     separate keyed group the live cluster-gizmo drag (captureClusterBase /
 *     applyClusterTransform) and the post-commit rebuild both move.
 *   - otherwise (assembly): return ONE merged Group with the transforms baked in
 *     (the part is a single instance; no per-cluster keying needed).
 * ``opts.dsBpRange`` (Map<helixId,[minBp,maxBp]> from _dsBpRangeByHelix) overrides
 * each cell's axial extent with the helix's ACTUAL dsDNA span, so the box matches
 * the cylinder rep after scaffold routing / continuations move the real ends past
 * the stale bundle-create length_bp.
 * Without opts the legacy single-merged-Group behaviour is unchanged.
 */
function _buildExtrusionBoxes(design, helixAxes = null, curveTolNm = 0, opts = null) {
  const fl = design?.feature_log
  if (!Array.isArray(fl) || !fl.length) return null
  const isHC  = (design.lattice_type === 'HONEYCOMB')
  const spCol = SQUARE_HELIX_SPACING
  const spRow = isHC ? HONEYCOMB_ROW_PITCH : SQUARE_HELIX_SPACING

  // Deformed designs: sweep each box along its helices' deformed spine so the
  // bent comb is preserved (per-extrusion fidelity). cell→helix lookup is also
  // used for per-cluster box assignment, so build it unconditionally.
  const deformed = !!helixAxes && Object.values(helixAxes).some(a => (a?.samples?.length ?? 0) > 2)
  const cellToHelix = new Map()
  for (const h of (design.helices ?? [])) {
    if (h.grid_pos) cellToHelix.set(`${h.grid_pos[0]},${h.grid_pos[1]}`, h.id)
  }

  // Cluster-aware mode: a (helix, bp) → cluster-subset-index resolver drives the
  // straight-box decomposition (and majority attribution for swept boxes).
  const clusters = opts?.clusters ?? null
  const ownerAt  = (clusters?.length) ? _buildBpClusterResolver(design, clusters) : null
  // Actual per-helix dsDNA bp range (from geometry). When present it OVERRIDES the
  // feature-log op's length_bp/offset for each cell's axial extent — so the box
  // follows the real (post-routing) helix spans + stagger instead of the stale
  // build-time dimensions. Axial coord of a global bp index is bp·rise.
  const dsBpRange = opts?.dsBpRange ?? null

  // Emit one box geometry record. `clusterIdx` (subset index, -1 = none) is only
  // meaningful in cluster-aware mode.
  const pushBox = (geos, m, wCol, wRow, cCol, cRow, extCenter, axialLen, clusterIdx) => {
    const size = [0, 0, 0], pos = [0, 0, 0]
    size[m.col] = wCol;  size[m.row] = wRow;  size[m.ext] = axialLen
    pos[m.col]  = cCol;  pos[m.row]  = cRow;  pos[m.ext]  = extCenter
    const geo = new THREE.BoxGeometry(size[0], size[1], size[2])
    geo.translate(pos[0], pos[1], pos[2])
    geo.deleteAttribute('uv')   // keep attrs uniform with swept geos for mergeGeometries
    geos.push({ geo, vol: wCol * wRow * axialLen, clusterIdx, swept: false })
  }

  const geos = []
  for (const e of fl) {
    if (!_EXTRUSION_OPS.has(e.op_kind)) continue
    const p = e.params || {}
    const cells = p.cells
    const lenBp = p.length_bp || 0
    if (!Array.isArray(cells) || !cells.length || lenBp <= 0) continue

    const axialLen = lenBp * BDNA_RISE_PER_BP
    const offset   = (typeof p.offset_nm === 'number') ? p.offset_nm : 0
    const bpLo     = Math.round(offset / BDNA_RISE_PER_BP)
    const bpHi     = bpLo + lenBp
    const m        = _PLANE_AXES[p.plane] || _PLANE_AXES.XY
    const extOf    = (bp) => offset + (bp - bpLo) * BDNA_RISE_PER_BP   // axial coord of bp

    // One box per lattice-connected region of this extrusion's cells, so
    // disjoint regions (e.g. two hinge arms) become separate hull blocks.
    for (const compCells of _cellComponents(cells)) {
      let minR = Infinity, maxR = -Infinity, minC = Infinity, maxC = -Infinity
      for (const cell of compCells) {
        const r = cell[0], c = cell[1]
        if (r < minR) minR = r; if (r > maxR) maxR = r
        if (c < minC) minC = c; if (c > maxC) maxC = c
      }
      const wCol = (maxC - minC + 1) * spCol
      const wRow = (maxR - minR + 1) * spRow
      const boxHelixIds = compCells.map(([r, c]) => cellToHelix.get(`${r},${c}`)).filter(Boolean)

      // Curved path: sweep the box's rectangle along its helices' deformed spine.
      // Falls through to a straight box when the box isn't in the deformed arm.
      // (Swept geometry already carries the cluster transform in its samples, so
      // it isn't decomposed — only attributed whole, by majority, for keying.)
      if (deformed) {
        let sections = _boxSweptSections(design, helixAxes, boxHelixIds, bpLo, bpHi, wCol, wRow)
        if (sections) {
          sections = _decimateSections(sections, curveTolNm)
          let clusterIdx = -1
          if (ownerAt) {
            const mid = Math.floor((bpLo + bpHi) / 2), tally = new Map()
            for (const hid of boxHelixIds) { const ci = ownerAt(hid, mid); if (ci >= 0) tally.set(ci, (tally.get(ci) ?? 0) + 1) }
            let bestN = 0; for (const [ci, n] of tally) if (n > bestN) { bestN = n; clusterIdx = ci }
          }
          geos.push({ geo: _buildSweptHullGeometry(sections), vol: wCol * wRow * axialLen, clusterIdx, swept: true })
          continue
        }
      }

      if (!ownerAt) {
        // Legacy: one straight box for the whole region.
        const cCol = (minC + maxC) / 2 * spCol, cRow = (minR + maxR) / 2 * spRow
        pushBox(geos, m, wCol, wRow, cCol, cRow, offset + axialLen / 2, axialLen, -1)
        continue
      }

      // Cluster-aware: walk each cell's owner base-by-base into runs over the
      // cell's ACTUAL axial bp range (dsDNA extent when available, else the op
      // range), then split the region into axial segments at every owner/extent
      // boundary and, within each segment, into one sub-box per distinct owning
      // cluster (bounding rect of the cells PRESENT there). Handles axial cuts,
      // cross-section splits, AND staggered/extended helix ends.
      const axOf = dsBpRange ? (bp) => bp * BDNA_RISE_PER_BP : extOf
      const cellRuns = []                      // { r, c, lo, hi, runs: [{ s, e, ci }] }
      const bset = new Set()
      for (const [r, c] of compCells) {
        const hid = cellToHelix.get(`${r},${c}`)
        let lo = bpLo, hi = bpHi
        if (dsBpRange) {
          const dr = hid ? dsBpRange.get(hid) : null
          if (!dr) continue                    // no dsDNA on this helix → not in the hull
          lo = dr[0]; hi = dr[1] + 1           // [minBp, maxBp] inclusive → exclusive end
        }
        const runs = []
        if (!hid) { runs.push({ s: lo, e: hi, ci: -1 }) }
        else {
          let s = lo, prev = ownerAt(hid, lo)
          for (let bp = lo + 1; bp < hi; bp++) {
            const ci = ownerAt(hid, bp)
            if (ci !== prev) { runs.push({ s, e: bp, ci: prev }); s = bp; prev = ci }
          }
          runs.push({ s, e: hi, ci: prev })
        }
        for (const run of runs) { bset.add(run.s); bset.add(run.e) }
        cellRuns.push({ r, c, runs })
      }
      if (!cellRuns.length) continue
      const bnds = [...bset].sort((a, b) => a - b)
      for (let i = 0; i < bnds.length - 1; i++) {
        const lo = bnds[i], hi = bnds[i + 1]
        if (hi <= lo) continue
        const mid = (lo + hi) / 2
        const byCi = new Map()                 // ci → { minR, maxR, minC, maxC }
        for (const cr of cellRuns) {
          const run = cr.runs.find(rr => rr.s <= mid && rr.e >= mid)
          if (!run) continue                   // cell absent here (staggered end) → skip
          let b = byCi.get(run.ci)
          if (!b) { b = { minR: Infinity, maxR: -Infinity, minC: Infinity, maxC: -Infinity }; byCi.set(run.ci, b) }
          if (cr.r < b.minR) b.minR = cr.r; if (cr.r > b.maxR) b.maxR = cr.r
          if (cr.c < b.minC) b.minC = cr.c; if (cr.c > b.maxC) b.maxC = cr.c
        }
        const segAxial = (hi - lo) * BDNA_RISE_PER_BP
        const extCenter = (axOf(lo) + axOf(hi)) / 2
        for (const [ci, b] of byCi) {
          pushBox(geos, m,
            (b.maxC - b.minC + 1) * spCol, (b.maxR - b.minR + 1) * spRow,
            (b.minC + b.maxC) / 2 * spCol, (b.minR + b.maxR) / 2 * spRow,
            extCenter, segAxial, ci)
        }
      }
    }
  }
  if (!geos.length) return null

  // Global 5% small-block filter (declutter stubs), preserving box records so the
  // per-cluster split below can still read helixIds/swept on survivors.
  const keptRecs = _keepLargeBlocks(geos, 0.05)
  if (!keptRecs.length) return null

  // Merge a set of box records into a finished hull Group (mesh + edges).
  const buildGroup = (recs, name) => {
    if (!recs.length) return null
    const merged = mergeGeometries(recs.map(r => r.geo), false)
    recs.forEach(r => r.geo.dispose())
    if (!merged) return null
    const group = new THREE.Group()
    merged.computeBoundingBox()
    const c = new THREE.Vector3(); merged.boundingBox.getCenter(c)
    group.userData.bundleMid   = c
    group.userData.clusterName = name
    const mesh = new THREE.Mesh(merged, _extrusionMeshMat())
    mesh.renderOrder = 100
    const edges = new THREE.LineSegments(
      // 15° when curved → only facet boundaries + corner/cap edges (not every triangle);
      // 1° straight → crisp box edges.
      new THREE.EdgesGeometry(merged, deformed ? 15 : 1),
      new THREE.LineBasicMaterial({ color: 0x333333, transparent: true, opacity: 0.55, depthWrite: false }),
    )
    edges.renderOrder = 101
    group.add(mesh, edges)
    return group
  }

  const partName = design.metadata?.name || 'Part'

  // Legacy single-merged-Group path (no cluster info supplied).
  if (!ownerAt) return buildGroup(keptRecs, partName)

  // Bake each (straight) sub-box's owning-cluster transform. Swept boxes already
  // carry the transform in their spine samples — don't double-apply.
  for (const rec of keptRecs) {
    if (rec.swept || rec.clusterIdx < 0) continue
    const mtx = _clusterMatrix(clusters[rec.clusterIdx])
    if (mtx) rec.geo.applyMatrix4(mtx)
  }

  // Assembly path: one merged source hull with transforms baked (the part is a
  // single instance, so no per-cluster keying is needed).
  if (!opts.keyByCluster) return buildGroup(keptRecs, partName)

  // Design view: one keyed group per cluster (+ '__extrusions__' for unclustered),
  // so the live cluster-gizmo drag and post-commit rebuild both move each block.
  const buckets = new Map()   // key (cluster.id | '__extrusions__') → records
  for (const rec of keptRecs) {
    const key = rec.clusterIdx >= 0 ? clusters[rec.clusterIdx].id : '__extrusions__'
    if (!buckets.has(key)) buckets.set(key, [])
    buckets.get(key).push(rec)
  }
  const out = new Map()
  for (const [key, recs] of buckets) {
    const name = key === '__extrusions__' ? partName
      : (clusters.find(c => c.id === key)?.name || 'Cluster')
    const g = buildGroup(recs, name)
    if (g) out.set(key, g)
  }
  return out.size ? out : null
}

/**
 * Fallback extrusion reconstruction for designs with NO feature-log build
 * history (cadnano / scadnano imports).
 *
 * Scans the bundle along its axis; helix start/end positions are rounded to the
 * lattice crossover tick (7 HC / 8 SQ bp) so ragged per-helix ends don't spawn
 * junk segments.  Each axial run with a constant occupied cross-section becomes
 * one rectangular box (bounding rect of the present helices' cross-section
 * positions, padded by one cell).  Helices with no dsDNA (pure ss / overhang)
 * are excluded when geometry is available.  Returns a THREE.Group or null.
 */
function _scanExtrusionGroup(helixIds, helixAxes, helixBp, latticeType, name, tickBp) {
  if (!helixIds?.length || !helixAxes) return null
  const hasBp   = helixBp && helixBp.size > 0
  const include = (hid) => hasBp ? (helixBp.get(hid) ?? 0) > 0 : true

  const isHC = (latticeType === 'HONEYCOMB')
  // Per-lattice default margin (user-chosen for cleanest segmentation): 8 bp
  // for honeycomb, 7 bp for square. A slider value overrides via `tickBp`.
  const tickAxial = (tickBp || (isHC ? 8 : 7)) * BDNA_RISE_PER_BP

  // Bundle frame (avg axis dir → U, dir, V) + origin at the helix-midpoint centroid.
  const dir = new THREE.Vector3()
  const mids = [], ids = []
  for (const hid of helixIds) {
    const ax = helixAxes[hid]
    if (!ax?.start || !ax?.end || !include(hid)) continue
    const s = new THREE.Vector3(...ax.start), e = new THREE.Vector3(...ax.end)
    dir.add(e.clone().sub(s))
    mids.push({ s, e, mid: s.clone().add(e).multiplyScalar(0.5) })
    ids.push(hid)
  }
  if (!mids.length) return null
  if (dir.lengthSq() < 1e-12) dir.set(0, 0, 1)
  dir.normalize()
  const U = new THREE.Vector3()
  const cz = new THREE.Vector3().crossVectors(dir, new THREE.Vector3(0, 1, 0))
  if (cz.lengthSq() > 1e-4) U.copy(cz).normalize()
  else U.crossVectors(dir, new THREE.Vector3(0, 0, 1)).normalize()
  const V = new THREE.Vector3().crossVectors(U, dir).normalize()
  const origin = new THREE.Vector3()
  for (const m of mids) origin.add(m.mid)
  origin.divideScalar(mids.length)

  const spacing = _helixSpacing(helixAxes, ids)
  const roundTick = (a) => Math.round(a / tickAxial) * tickAxial

  // Per-helix axial span (rounded to ticks) + constant cross-section (u, v).
  const segs = []
  const bounds = new Set()
  for (const m of mids) {
    const a0 = m.s.clone().sub(origin).dot(dir)
    const a1 = m.e.clone().sub(origin).dot(dir)
    let lo = roundTick(Math.min(a0, a1)), hi = roundTick(Math.max(a0, a1))
    if (hi <= lo) hi = lo + tickAxial
    segs.push({
      lo, hi,
      u: m.mid.clone().sub(origin).dot(U),
      v: m.mid.clone().sub(origin).dot(V),
    })
    bounds.add(lo); bounds.add(hi)
  }
  const bnd = [...bounds].sort((x, y) => x - y)
  if (bnd.length < 2) return null

  // Bounding rect of present helices over each tick interval.
  const intervals = []
  for (let i = 0; i < bnd.length - 1; i++) {
    const b0 = bnd[i], b1 = bnd[i + 1], c = (b0 + b1) / 2
    let uMin = Infinity, uMax = -Infinity, vMin = Infinity, vMax = -Infinity, n = 0
    for (const s of segs) {
      if (s.lo <= c && s.hi >= c) {
        if (s.u < uMin) uMin = s.u; if (s.u > uMax) uMax = s.u
        if (s.v < vMin) vMin = s.v; if (s.v > vMax) vMax = s.v
        n++
      }
    }
    if (n) intervals.push({ b0, b1, uMin, uMax, vMin, vMax })
  }
  if (!intervals.length) return null

  // Merge consecutive intervals sharing the same rect.
  const merged = [], tol = 1e-3
  for (const iv of intervals) {
    const last = merged[merged.length - 1]
    if (last && Math.abs(last.b1 - iv.b0) < tol &&
        Math.abs(last.uMin - iv.uMin) < tol && Math.abs(last.uMax - iv.uMax) < tol &&
        Math.abs(last.vMin - iv.vMin) < tol && Math.abs(last.vMax - iv.vMax) < tol) {
      last.b1 = iv.b1
    } else merged.push({ ...iv })
  }

  const quat = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(U, dir, V))
  const geos = []
  for (const m of merged) {
    const len = m.b1 - m.b0
    if (len < 1e-6) continue
    const uExt = (m.uMax - m.uMin) + spacing
    const vExt = (m.vMax - m.vMin) + spacing
    const center = origin.clone()
      .addScaledVector(dir, (m.b0 + m.b1) / 2)
      .addScaledVector(U, (m.uMin + m.uMax) / 2)
      .addScaledVector(V, (m.vMin + m.vMax) / 2)
    const geo = new THREE.BoxGeometry(uExt, len, vExt)   // X=U, Y=dir, Z=V
    geo.applyMatrix4(new THREE.Matrix4().compose(center, quat, new THREE.Vector3(1, 1, 1)))
    geos.push({ geo, vol: uExt * vExt * len })
  }
  if (!geos.length) return null
  const keptGeos = _filterSmallBlocks(geos, 0.05)   // drop blocks < 5% of total volume
  const mergedGeo = mergeGeometries(keptGeos, false)
  keptGeos.forEach(g => g.dispose())
  if (!mergedGeo) return null

  const group = new THREE.Group()
  mergedGeo.computeBoundingBox()
  const ctr = new THREE.Vector3(); mergedGeo.boundingBox.getCenter(ctr)
  group.userData.bundleMid   = ctr
  group.userData.clusterName = name || 'Cluster'
  const mesh = new THREE.Mesh(mergedGeo, _extrusionMeshMat())
  mesh.renderOrder = 100
  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(mergedGeo, 1),
    new THREE.LineBasicMaterial({ color: 0x333333, transparent: true, opacity: 0.55, depthWrite: false }),
  )
  edges.renderOrder = 101
  group.add(mesh, edges)
  return group
}

/**
 * Return a copy of `helixAxes` with each helix's start/end trimmed to its dsDNA
 * extent — the axial span actually covered by base-paired (≥2 stranded,
 * non-overhang) nucleotides. Excludes ssDNA portions: scaffold without staples,
 * staple without scaffold (overhangs), and unpaired tails. dsDNA nucleotide
 * positions are projected onto each helix's axis line (length_bp is NOT a
 * reliable physical extent, so we use actual positions). Helices with no dsDNA
 * keep their original axis (they're dropped by the scan's helixBp include test).
 */
function _dsTrimmedAxes(geometry, helixAxes) {
  if (!geometry?.length || !helixAxes) return helixAxes
  const dsCount = new Map()
  for (const nuc of geometry) {
    if (!nuc.strand_id || nuc.overhang_id) continue
    const k = nuc.helix_id + ':' + nuc.bp_index
    dsCount.set(k, (dsCount.get(k) ?? 0) + 1)
  }
  const tRange = new Map()   // hid → [tLo, tHi] axis parameter of dsDNA nucleotides
  for (const nuc of geometry) {
    if (!nuc.strand_id || nuc.overhang_id || !nuc.backbone_position) continue
    if ((dsCount.get(nuc.helix_id + ':' + nuc.bp_index) ?? 0) < 2) continue
    const ax = helixAxes[nuc.helix_id]
    if (!ax?.start || !ax?.end) continue
    const s = ax.start, e = ax.end
    const dx = e[0] - s[0], dy = e[1] - s[1], dz = e[2] - s[2]
    const len2 = dx * dx + dy * dy + dz * dz
    if (len2 < 1e-12) continue
    const p = nuc.backbone_position
    const t = ((p[0] - s[0]) * dx + (p[1] - s[1]) * dy + (p[2] - s[2]) * dz) / len2
    const r = tRange.get(nuc.helix_id)
    if (!r) tRange.set(nuc.helix_id, [t, t])
    else { if (t < r[0]) r[0] = t; if (t > r[1]) r[1] = t }
  }
  const out = {}
  for (const hid in helixAxes) {
    const ax = helixAxes[hid]
    const r = tRange.get(hid)
    if (!ax?.start || !ax?.end || !r) { out[hid] = ax; continue }
    const s = ax.start, e = ax.end
    const tLo = Math.max(0, Math.min(1, r[0])), tHi = Math.max(0, Math.min(1, r[1]))
    const lerp = (t) => [s[0] + (e[0] - s[0]) * t, s[1] + (e[1] - s[1]) * t, s[2] + (e[2] - s[2]) * t]
    out[hid] = { ...ax, start: lerp(tLo), end: lerp(tHi) }
  }
  return out
}

// ── Spine-sections builder ────────────────────────────────────────────────────

/**
 * Build per-step cross-section data along the cluster spine using helixAxes samples.
 * Returns null if the cluster has no sampled helices or fewer than 2 steps.
 *
 * Each section: { center: Vector3, U: Vector3, V: Vector3, tangent: Vector3, corners: [{x,z}] }
 */
function _computeSpineSections(cluster, helixAxes, crossMargin = CROSS_MARGIN, axialMargin = AXIAL_MARGIN) {
  const sampledHelices = cluster.helix_ids.filter(hid => {
    const ax = helixAxes[hid]
    return ax?.samples && ax.samples.length > 2
  })
  if (!sampledHelices.length) return null

  let minLen = Infinity
  for (const hid of sampledHelices) {
    const n = helixAxes[hid].samples.length
    if (n < minLen) minLen = n
  }
  if (minLen < 2) return null

  const Yv = new THREE.Vector3(0, 1, 0)
  const Zv = new THREE.Vector3(0, 0, 1)

  function avgCenter(step) {
    const c = new THREE.Vector3()
    for (const hid of sampledHelices) {
      const s = helixAxes[hid].samples[step]
      c.x += s[0]; c.y += s[1]; c.z += s[2]
    }
    return c.divideScalar(sampledHelices.length)
  }

  const centers = []
  for (let i = 0; i < minLen; i++) centers.push(avgCenter(i))

  // Extend endpoints outward by axialMargin so the end-cap planes sit just
  // beyond the helix cylinder ends.  Without this, opaque cylinder geometry
  // co-planar with the cap partially fails the depth test from oblique angles,
  // creating a slanted-cutoff artefact on the transparent cap.
  if (axialMargin > 0 && minLen >= 2) {
    const t0   = new THREE.Vector3().subVectors(centers[1], centers[0]).normalize()
    const tEnd = new THREE.Vector3().subVectors(centers[minLen - 1], centers[minLen - 2]).normalize()
    centers[0].addScaledVector(t0, -axialMargin)
    centers[minLen - 1].addScaledVector(tEnd, axialMargin)
  }

  const sections = []
  for (let i = 0; i < minLen; i++) {
    const center = centers[i]

    // Tangent via centered/forward/backward difference.
    let tangent
    if (i === 0)          tangent = new THREE.Vector3().subVectors(centers[1], centers[0])
    else if (i === minLen - 1) tangent = new THREE.Vector3().subVectors(centers[i], centers[i - 1])
    else                  tangent = new THREE.Vector3().subVectors(centers[i + 1], centers[i - 1])
    if (tangent.lengthSq() < 1e-12) continue
    tangent.normalize()

    // Cross-section frame.
    let U = new THREE.Vector3().crossVectors(tangent, Yv)
    if (U.lengthSq() < 1e-4) U = new THREE.Vector3().crossVectors(tangent, Zv)
    U.normalize()
    const V = new THREE.Vector3().crossVectors(U, tangent).normalize()

    // Helix UV positions at this step.
    const helixUV = []
    for (const hid of sampledHelices) {
      const s   = helixAxes[hid].samples[i]
      const rel = new THREE.Vector3(s[0] - center.x, s[1] - center.y, s[2] - center.z)
      helixUV.push({ u: rel.dot(U), v: rel.dot(V) })
    }

    // Cross-section polygon.
    let corners = null
    if (helixUV.length >= 3) {
      const hull = _convexHull2D(helixUV)
      if (hull.length >= 3) corners = _expandHullCorners(hull, crossMargin)
    }
    if (!corners) {
      const r = crossMargin + 1.0
      corners = Array.from({ length: 6 }, (_, k) => ({
        x: r * Math.cos(2 * Math.PI * k / 6),
        z: r * Math.sin(2 * Math.PI * k / 6),
      }))
    }

    sections.push({ center, U, V, tangent, corners })
  }

  if (sections.length < 2) return null

  // Enforce corner count consistency — any section that differs gets a regular N-gon.
  const N0 = sections[0].corners.length
  for (let i = 1; i < sections.length; i++) {
    if (sections[i].corners.length === N0) continue
    const r = Math.max(...sections[i].corners.map(c => Math.sqrt(c.x * c.x + c.z * c.z)))
    sections[i].corners = Array.from({ length: N0 }, (_, k) => ({
      x: r * Math.cos(2 * Math.PI * k / N0),
      z: r * Math.sin(2 * Math.PI * k / N0),
    }))
  }

  return sections
}

/**
 * Build a flat-shaded BufferGeometry from an array of spine sections.
 * Lateral quads connect adjacent cross-section rings; start/end caps are fan-triangulated.
 */
function _buildSweptHullGeometry(sections) {
  const N = sections[0].corners.length
  const S = sections.length

  // World-space vertex positions: verts[i * N + j] = world position of corner j at step i.
  const verts = []
  for (let i = 0; i < S; i++) {
    const { center, U, V, corners } = sections[i]
    for (let j = 0; j < N; j++) {
      const c = corners[j]
      verts.push(new THREE.Vector3(
        center.x + c.x * U.x + c.z * V.x,
        center.y + c.x * U.y + c.z * V.y,
        center.z + c.x * U.z + c.z * V.z,
      ))
    }
  }

  const positions = [], normals = [], indices = []

  // ── Lateral faces ──────────────────────────────────────────────────────────
  for (let i = 0; i < S - 1; i++) {
    for (let j = 0; j < N; j++) {
      const jn  = (j + 1) % N
      const v00 = verts[i       * N + j ]
      const v01 = verts[i       * N + jn]
      const v10 = verts[(i + 1) * N + j ]
      const v11 = verts[(i + 1) * N + jn]
      const e1  = new THREE.Vector3().subVectors(v01, v00)
      const e2  = new THREE.Vector3().subVectors(v10, v00)
      const fn  = new THREE.Vector3().crossVectors(e1, e2)
      if (fn.lengthSq() < 1e-12) continue
      fn.normalize()
      // Ensure fn points outward from the spine center.
      // _convexHull2D winding is unspecified so check and flip if needed.
      const faceMid = new THREE.Vector3().addVectors(v00, v11).multiplyScalar(0.5)
      const toFace  = new THREE.Vector3().subVectors(faceMid, sections[i].center)
      const outward = fn.dot(toFace) >= 0
      if (!outward) fn.negate()
      const base = positions.length / 3
      // Vertex order must be CCW as seen from the outward (fn) side.
      // Original order (v00,v01,v11,v10) is CCW when fn = e1×e2 (outward).
      // When fn was negated, reverse to (v00,v10,v11,v01).
      if (outward) {
        positions.push(v00.x, v00.y, v00.z, v01.x, v01.y, v01.z, v11.x, v11.y, v11.z, v10.x, v10.y, v10.z)
      } else {
        positions.push(v00.x, v00.y, v00.z, v10.x, v10.y, v10.z, v11.x, v11.y, v11.z, v01.x, v01.y, v01.z)
      }
      for (let k = 0; k < 4; k++) normals.push(fn.x, fn.y, fn.z)
      indices.push(base, base + 1, base + 2, base, base + 2, base + 3)
    }
  }

  // ── Start cap (section 0, normal = −tangent) ──────────────────────────────
  {
    const ring = verts.slice(0, N)
    const ctr  = new THREE.Vector3()
    for (const v of ring) ctr.add(v)
    ctr.divideScalar(N)
    const capN = new THREE.Vector3()
      .subVectors(sections[1].center, sections[0].center).normalize().negate()
    const testCross = new THREE.Vector3().crossVectors(
      new THREE.Vector3().subVectors(ring[0], ctr),
      new THREE.Vector3().subVectors(ring[1], ctr),
    )
    const ccw = testCross.dot(capN) >= 0
    for (let j = 0; j < N; j++) {
      const jn       = (j + 1) % N
      const [va, vb] = ccw ? [ring[j], ring[jn]] : [ring[jn], ring[j]]
      const base     = positions.length / 3
      positions.push(ctr.x, ctr.y, ctr.z, va.x, va.y, va.z, vb.x, vb.y, vb.z)
      for (let k = 0; k < 3; k++) normals.push(capN.x, capN.y, capN.z)
      indices.push(base, base + 1, base + 2)
    }
  }

  // ── End cap (section S−1, normal = +tangent) ───────────────────────────────
  {
    const ring = verts.slice((S - 1) * N, S * N)
    const ctr  = new THREE.Vector3()
    for (const v of ring) ctr.add(v)
    ctr.divideScalar(N)
    const capN = new THREE.Vector3()
      .subVectors(sections[S - 1].center, sections[S - 2].center).normalize()
    const testCross = new THREE.Vector3().crossVectors(
      new THREE.Vector3().subVectors(ring[0], ctr),
      new THREE.Vector3().subVectors(ring[1], ctr),
    )
    const ccw = testCross.dot(capN) >= 0
    for (let j = 0; j < N; j++) {
      const jn       = (j + 1) % N
      const [va, vb] = ccw ? [ring[j], ring[jn]] : [ring[jn], ring[j]]
      const base     = positions.length / 3
      positions.push(ctr.x, ctr.y, ctr.z, va.x, va.y, va.z, vb.x, vb.y, vb.z)
      for (let k = 0; k < 3; k++) normals.push(capN.x, capN.y, capN.z)
      indices.push(base, base + 1, base + 2)
    }
  }

  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geo.setAttribute('normal',   new THREE.Float32BufferAttribute(normals,   3))
  geo.setIndex(indices)
  return geo
}

/**
 * Curvature-adaptive section thinning (Douglas–Peucker on the spine centers).
 * Keeps the two endpoints and any section whose center deviates more than
 * `tolNm` (perpendicular distance, nm) from the chord of its kept neighbours.
 * Straight runs collapse to 2 sections (1 facet); tight bends keep more —
 * the single intuitive "how polygon-y" knob.
 */
function _decimateSections(sections, tolNm) {
  const S = sections.length
  if (S <= 2 || !(tolNm > 0)) return sections
  const pts  = sections.map(s => s.center)
  const keep = new Array(S).fill(false)
  keep[0] = keep[S - 1] = true
  const stack = [[0, S - 1]]
  const ab = new THREE.Vector3(), ap = new THREE.Vector3(), cr = new THREE.Vector3()
  while (stack.length) {
    const [a, b] = stack.pop()
    if (b - a < 2) continue
    ab.subVectors(pts[b], pts[a]); const abLen = ab.length()
    let maxD = -1, maxI = -1
    for (let i = a + 1; i < b; i++) {
      ap.subVectors(pts[i], pts[a])
      const d = abLen < 1e-9 ? ap.length() : cr.crossVectors(ap, ab).length() / abLen
      if (d > maxD) { maxD = d; maxI = i }
    }
    if (maxD > tolNm && maxI > 0) { keep[maxI] = true; stack.push([a, maxI], [maxI, b]) }
  }
  return sections.filter((_, i) => keep[i])
}

/**
 * Build rectangular swept cross-sections for ONE extrusion box along the deformed
 * spine of its helices, over the box's global bp range [bpLo, bpHi].  Mirrors
 * _computeSpineSections but uses a fixed wCol×wRow rectangle (so the bent boxes
 * match the straight comb) and restricts to the box's sample-index sub-range.
 * Returns sections[] (>=2) or null (no sampled helices / range too short).
 */
function _boxSweptSections(design, helixAxes, boxHelixIds, bpLo, bpHi, wCol, wRow) {
  const sampled = boxHelixIds.filter(hid => (helixAxes[hid]?.samples?.length ?? 0) > 2)
  if (!sampled.length) return null
  const repHelix = design.helices.find(h => h.id === sampled[0])
  const bs = repHelix?.bp_start ?? 0
  let nMin = Infinity
  for (const hid of sampled) nMin = Math.min(nMin, helixAxes[hid].samples.length)
  if (nMin < 2) return null
  const idxLo = Math.max(0, Math.min(nMin - 1, Math.round((bpLo - bs) / _AXIS_SAMPLE_STEP)))
  const idxHi = Math.max(0, Math.min(nMin - 1, Math.round((bpHi - bs) / _AXIS_SAMPLE_STEP)))
  if (idxHi - idxLo < 1) return null

  const Yv = new THREE.Vector3(0, 1, 0)
  const Zv = new THREE.Vector3(0, 0, 1)
  // Rectangle in the cross-section (U,V) plane — corner.x → U, corner.z → V.
  const corners = [
    { x:  wCol / 2, z:  wRow / 2 }, { x: -wCol / 2, z:  wRow / 2 },
    { x: -wCol / 2, z: -wRow / 2 }, { x:  wCol / 2, z: -wRow / 2 },
  ]
  // Build the centroid spine for the FULL range [0, idxHi] — NOT just the box's
  // [idxLo, idxHi].  The parallel-transport frame below must be anchored at the
  // bundle START (idx 0, tangent ≈ +Z, well-conditioned), so EVERY extrusion box
  // shares ONE consistent frame.  Seeding each box independently from its own
  // first section put the LAST box's seed right at the −Y pole (90° bend) →
  // degenerate → the whole final block was mis-rolled (the residual flip seen
  // even after the per-box smoothing fix).  We propagate from 0 but EMIT sections
  // only for idxLo..idxHi below.
  const centers = []
  for (let i = 0; i <= idxHi; i++) {
    const c = new THREE.Vector3()
    for (const hid of sampled) { const s = helixAxes[hid].samples[i]; c.x += s[0]; c.y += s[1]; c.z += s[2] }
    centers.push(c.divideScalar(sampled.length))
  }
  const M = centers.length
  // Rotation-minimizing (parallel-transport) cross-section frame.  The original
  // code rebuilt the box axes from `tangent × worldY` at EVERY section, which is
  // SINGULAR when the spine tangent nears the vertical axis: a bend that drives
  // the bundle toward world-up (teeth.nadoc: 90° bend at direction 270° → final
  // tangent ≈ −Y, verified) made the U axis collapse and flip ~90° on the last
  // box — the "sudden twist, wrong degree + direction" on the final segment.
  // Instead, seed U once at the bundle start, then carry it forward by the
  // minimal rotation between consecutive tangents.  No world-up reference → no
  // pole → no flip; for a planar bend U stays constant straight through the
  // formerly-singular end.  NOTE: this is a smooth swept envelope — it does NOT
  // roll by the bundle's material twist (the axis `samples` carry only spine
  // centers, no per-bp orientation); the visible coil comes from the spine path.
  const sections = []
  let prevT = null
  let U = null
  for (let k = 0; k < M; k++) {
    let tangent
    if (k === 0)          tangent = new THREE.Vector3().subVectors(centers[1], centers[0])
    else if (k === M - 1) tangent = new THREE.Vector3().subVectors(centers[k], centers[k - 1])
    else                  tangent = new THREE.Vector3().subVectors(centers[k + 1], centers[k - 1])
    if (tangent.lengthSq() < 1e-12) continue
    tangent.normalize()
    if (!U) {
      // Seed: any unit vector ⟂ tangent.  world-Y, falling back to world-Z when
      // the start tangent is itself near the Y pole.
      U = new THREE.Vector3().crossVectors(tangent, Yv)
      if (U.lengthSq() < 1e-4) U = new THREE.Vector3().crossVectors(tangent, Zv)
      U.normalize()
    } else {
      // Parallel-transport U across the tangent change: rotate about
      // (prevT × tangent) by the angle between the tangents, then re-orthogonalize.
      const axis = new THREE.Vector3().crossVectors(prevT, tangent)
      const sin  = axis.length()
      if (sin > 1e-9) {
        U.applyAxisAngle(axis.divideScalar(sin), Math.atan2(sin, prevT.dot(tangent)))
      }
      U.addScaledVector(tangent, -U.dot(tangent)).normalize()   // re-project ⟂ tangent
    }
    prevT = tangent
    // Propagate the frame through [0, idxLo) but only EMIT the box's own sections.
    if (k < idxLo) continue
    const V = new THREE.Vector3().crossVectors(U, tangent).normalize()
    sections.push({ center: centers[k], U: U.clone(), V, tangent, corners })
  }
  return sections.length >= 2 ? sections : null
}

// ── Public init ────────────────────────────────────────────────────────────────

export function initJointRenderer(scene, camera, canvas, store, api) {
  let _definingCluster  = null
  let _surfaceMesh      = null   // THREE.Mesh — solid fill, used for raycasting
  let _surfaceWire      = null   // THREE.LineSegments — wireframe overlay
  let _surfaceGrid      = null   // THREE.LineSegments — periodic bp grid rings
  let _surfaceHover     = null   // THREE.LineSegments — per-bp hover rings (vertex-coloured)
  let _surfaceMesh2     = null   // THREE.Mesh — regular polygon overlay (optional)
  let _surfaceWire2     = null   // THREE.LineSegments — wireframe for regular polygon
  let _hullMesh         = null   // THREE.Mesh — convex hull surface (matches grid ring shape)
  let _hullWire         = null   // THREE.LineSegments — hull wireframe
  let _primaryPanels    = null   // bg.panels array from primary build, for debug lookup

  // ── Hull representation (independent of define mode) ──────────────────────
  let _hullReprActive   = false
  const _hullReprMeshes = new Map()  // clusterId → THREE.Mesh
  // Clusters whose dsDNA base-pair count is below this fraction of the whole
  // origami are not drawn — small clusters clutter the hull view. Tunable.
  let _hullMinSizeFraction = 0.10
  // Debug overlay: distinct color + centroid label per cluster, and excluded
  // clusters drawn faintly so the size threshold can be tuned visually.
  let _hullClusterDebug    = false
  // Hull geometry mode (toggle via window.nadocHull.mode()):
  //   'extrusions' = one rectangular box per feature-log extrusion (default;
  //                  reproduces teeth from the build history),
  //   'boxes'      = per-helix occupancy boxes merged per cluster,
  //   'prism'      = legacy per-cluster convex bundle prism.
  let _hullMode            = 'extrusions'
  // Box cross-section width as a fraction of inter-helix spacing. <1 leaves
  // visible grooves between helices (the "toothy" surface).
  let _occBoxFill          = 0.82
  // Extrusion-scan margin (bp): helix ends are rounded to this tick before
  // detecting cross-section boundaries. Larger = coarser (fewer, longer boxes);
  // smaller = finer. null → per-lattice default (set in _scanExtrusionGroup);
  // a number (from the slider) overrides it.
  let _hullScanTickBp      = null
  // Curved-hull facet tolerance (nm): max deviation of a flat facet from the true
  // deformed spine before it's subdivided. Larger = blockier/cheaper. Slider-driven.
  let _hullCurveTolNm      = 1.0
  let _bundleInfo       = null   // { bundleDir, axialMid, ringYs, vertsPerRing }
  let _surfaceDetail    = MIN_HC_FACES
  let _onExitCb         = null   // callback supplied by caller of enterDefineMode
  let _pointerDownAt    = null   // {x, y} recorded on pointerdown; used to suppress orbit-release clicks
  let _hoverRafId       = null   // rAF handle — throttles hover grid to one GPU upload per frame

  // ── Appearance state (fixed defaults — no longer user-adjustable) ───────────
  const _surfaceOpacityVal = SURFACE_OPACITY
  const _crossPaddingVal   = CROSS_MARGIN
  const _axialPaddingVal   = AXIAL_MARGIN
  let _wireframeVal        = false
  let _useExteriorPanels   = false           // lattice exterior panels
  let _useRegularPolygon   = false           // regular polygon overlay
  let _useHullSurface      = true            // convex hull surface (matches grid rings)
  let _showFill            = true            // solid fill visible; when false only grid rings show
  let _showDebug           = false           // live panel debug overlay

  // ── Debug overlay DOM ──────────────────────────────────────────────────────
  const _dbgEl = document.createElement('div')
  _dbgEl.style.cssText = [
    'position:fixed;bottom:12px;left:12px;z-index:9999',
    'background:rgba(0,0,0,0.72);color:#c9d1d9;font:11px/1.5 monospace',
    'padding:8px 10px;border-radius:5px;border:1px solid #30363d',
    'pointer-events:none;white-space:pre;display:none',
  ].join(';')
  document.body.appendChild(_dbgEl)

  function _dbgShow(lines) { _dbgEl.textContent = lines.join('\n'); _dbgEl.style.display = '' }
  function _dbgHide()      { _dbgEl.style.display = 'none' }

  const _jointGroup    = new THREE.Group()
  const _previewMesh   = _buildPreviewMesh()
  let _jointMeshes     = new Map()
  // Snapshot of group position/quaternion for each joint, captured at gizmo drag-start.
  // Keyed by joint id.  Used by applyClusterTransform to compute incremental motion.
  let _cbJointBases    = new Map()   // jointId → { pos: THREE.Vector3, quat: THREE.Quaternion }
  // Same snapshot for hull-prism groups (one per cluster, in _hullReprMeshes).
  // Lets applyClusterTransform translate/rotate the hull rigidly with the
  // moving cluster instead of leaving it stranded at its build-time pose.
  let _cbHullBases     = new Map()   // clusterId → { pos, quat }

  scene.add(_jointGroup)
  scene.add(_previewMesh)

  // Shared raycaster for surface interaction
  const _rc = new THREE.Raycaster()

  // ── NDC helper ──────────────────────────────────────────────────────────────
  function _ndc(e) {
    const r = canvas.getBoundingClientRect()
    return new THREE.Vector2(
      ((e.clientX - r.left) / r.width)  * 2 - 1,
      -((e.clientY - r.top)  / r.height) * 2 + 1,
    )
  }

  // ── Surface mesh helpers ────────────────────────────────────────────────────
  function _buildSurface(clusterId, N, latticeType, colour = SURFACE_COLOUR) {
    const { currentDesign, currentHelixAxes, currentGeometry } = store.getState()
    const cluster = currentDesign?.cluster_transforms?.find(c => c.id === clusterId)
    if (!cluster) return null

    const bg = _bundleGeometry(cluster, currentHelixAxes, currentGeometry, N, _crossPaddingVal, _axialPaddingVal, latticeType)
    if (!bg) return null

    if (bg.panels) {
      console.debug('[nadoc:joint] Exterior panels for cluster', clusterId, '→', bg.panels.map(p => ({
        angle: `${Math.round(Math.atan2(p.nv, p.nu) * 180 / Math.PI)}°`,
        n: [+p.nu.toFixed(3), +p.nv.toFixed(3)],
        rOffset: +p.rOffset.toFixed(2),
        width:   +(p.tMax - p.tMin).toFixed(2),
      })))
    }

    const geo = bg.panels
      ? _buildPanelSurface(bg.panels, bg.corners, bg.halfLen)
      : _buildPrismGeometry(bg.corners, bg.halfLen)

    // Solid fill — depthWrite:false prevents the transparent mesh from occluding
    // helix geometry at the same depth.
    const mat = new THREE.MeshBasicMaterial({
      color: colour, transparent: true, opacity: _showFill ? _surfaceOpacityVal : 0,
      side: THREE.DoubleSide, depthTest: true, depthWrite: false,
    })
    const mesh = new THREE.Mesh(geo, mat)
    mesh.quaternion.copy(bg.rotQ)
    mesh.position.copy(bg.bundleMid)
    mesh.renderOrder = 100
    mesh.userData.clusterId = clusterId

    // Wireframe overlay — separate LineSegments so it's always on top when visible.
    const wireGeo = new THREE.WireframeGeometry(geo)
    const wireMat = new THREE.LineBasicMaterial({
      color: colour, transparent: true,
      opacity: Math.min(1, _surfaceOpacityVal * 3),
      depthTest: false, depthWrite: false,
    })
    const wire = new THREE.LineSegments(wireGeo, wireMat)
    wire.quaternion.copy(bg.rotQ)
    wire.position.copy(bg.bundleMid)
    wire.renderOrder = 101
    wire.visible = _wireframeVal

    // Periodic grid rings (every GRID_PERIOD_HC / GRID_PERIOD_SQ bp).
    const lattice   = currentDesign?.lattice_type ?? 'honeycomb'
    const periodBp  = lattice === 'square' ? GRID_PERIOD_SQ : GRID_PERIOD_HC
    const grid = _buildGridLines(bg, periodBp, BDNA_RISE_PER_BP)

    // Per-bp hover rings (vertex colours updated on pointermove).
    const hoverResult = _buildHoverLines(bg, BDNA_RISE_PER_BP)

    // Hull surface — convex hull prism matching the grid ring cross-section.
    // Always built: used as a visible surface when _useHullSurface is on, and as
    // a silent raycast fallback for hull-corner gaps when exterior panels are on.
    const hullGeo  = _buildPrismGeometry(bg.corners, bg.halfLen)
    const hullMat  = new THREE.MeshBasicMaterial({
      color: HULL_COLOUR, transparent: true, opacity: 0,
      side: THREE.DoubleSide, depthTest: true, depthWrite: false,
    })
    const hullMesh = new THREE.Mesh(hullGeo, hullMat)
    hullMesh.quaternion.copy(bg.rotQ)
    hullMesh.position.copy(bg.bundleMid)
    hullMesh.renderOrder = 100
    hullMesh.userData.clusterId = clusterId

    const hullWireGeo = new THREE.WireframeGeometry(hullGeo)
    const hullWireMat = new THREE.LineBasicMaterial({
      color: HULL_COLOUR, transparent: true, opacity: 0,
      depthTest: false, depthWrite: false,
    })
    const hullWire = new THREE.LineSegments(hullWireGeo, hullWireMat)
    hullWire.quaternion.copy(bg.rotQ)
    hullWire.position.copy(bg.bundleMid)
    hullWire.renderOrder = 101

    return { mesh, wire, grid, hoverResult, bg, hullMesh, hullWire }
  }

  function _showSurface(clusterId, N) {
    _removeSurface()
    const { currentDesign } = store.getState()
    const designLattice = currentDesign?.lattice_type ?? null

    // Primary build: always runs — provides grid rings, hover rings, and hull geometry.
    const r = _buildSurface(clusterId, N, designLattice)
    if (r) {
      _surfaceMesh   = r.mesh
      _surfaceWire   = r.wire
      _surfaceGrid   = r.grid
      _surfaceHover  = r.hoverResult.lines
      _hullMesh      = r.hullMesh
      _hullWire      = r.hullWire
      _primaryPanels = r.bg.panels ?? null
      _bundleInfo    = {
        bundleDir:    r.bg.bundleDir,
        axialMid:     r.bg.axialMid,
        ringYs:       r.hoverResult.ringYs,
        vertsPerRing: r.hoverResult.vertsPerRing,
      }
      // Exterior panels solid fill
      _surfaceMesh.material.opacity = (_useExteriorPanels && _showFill) ? _surfaceOpacityVal : 0
      // Hull surface solid fill
      _hullMesh.material.opacity = (_useHullSurface && _showFill) ? _surfaceOpacityVal : 0
      _hullWire.material.opacity = (_useHullSurface && _showFill) ? Math.min(1, _surfaceOpacityVal * 3) : 0

      scene.add(_surfaceMesh, _surfaceWire)
      scene.add(_hullMesh, _hullWire)
      if (_surfaceGrid) scene.add(_surfaceGrid)
      scene.add(_surfaceHover)
    }

    // Regular polygon surface (null latticeType forces polygon path)
    if (_useRegularPolygon) {
      const r2 = _buildSurface(clusterId, N, null, POLYGON_COLOUR)
      if (r2) {
        _surfaceMesh2 = r2.mesh
        _surfaceWire2 = r2.wire
        scene.add(_surfaceMesh2, _surfaceWire2)
        // Dispose unused hull/grid/hover from secondary build
        r2.hullMesh.geometry.dispose(); r2.hullMesh.material.dispose()
        r2.hullWire.geometry.dispose(); r2.hullWire.material.dispose()
        if (r2.grid) { r2.grid.geometry.dispose(); r2.grid.material.dispose() }
        r2.hoverResult.lines.geometry.dispose(); r2.hoverResult.lines.material.dispose()
      }
    }
  }

  function _removeSurface() {
    for (const obj of [_surfaceMesh, _surfaceWire, _surfaceGrid, _surfaceHover, _surfaceMesh2, _surfaceWire2, _hullMesh, _hullWire]) {
      if (obj) {
        obj.geometry.dispose()
        obj.material.dispose()
        obj.parent?.remove(obj)
      }
    }
    _surfaceMesh = _surfaceWire = _surfaceGrid = _surfaceHover = null
    _surfaceMesh2 = _surfaceWire2 = _hullMesh = _hullWire = null
    _primaryPanels = null
    _bundleInfo  = null
  }

  // ── Face normal extraction ──────────────────────────────────────────────────
  function _getFaceHit(e) {
    _rc.setFromCamera(_ndc(e), camera)

    function _resolveHit(hit, source) {
      const mesh = hit.object
      const nm   = new THREE.Matrix3().getNormalMatrix(mesh.matrixWorld)
      const worldNormal = hit.face.normal.clone().applyMatrix3(nm).normalize()
      const toCamera = new THREE.Vector3().subVectors(camera.position, hit.point)
      if (worldNormal.dot(toCamera) < 0) worldNormal.negate()

      // Match world normal back to the closest panel (UV-projected)
      let matchedPanel = null
      if (_primaryPanels && _bundleInfo) {
        const U = new THREE.Vector3(1, 0, 0)  // local frame — panel nu/nv are in UV
        const V = new THREE.Vector3(0, 0, 1)
        const nu2d = worldNormal.dot(U), nv2d = worldNormal.dot(V)
        let bestDot = -Infinity
        for (const p of _primaryPanels) {
          const d = nu2d * p.nu + nv2d * p.nv
          if (d > bestDot) { bestDot = d; matchedPanel = p }
        }
      }

      return { point: hit.point, normal: worldNormal, source, matchedPanel }
    }

    // Hull surface takes exclusive priority when toggled on.
    if (_useHullSurface) {
      if (_hullMesh) {
        const hits = _rc.intersectObject(_hullMesh)
        if (hits.length && hits[0].face) return _resolveHit(hits[0], 'Hull surface')
      }
      return null
    }

    // Hull off — use exterior panels and/or regular polygon.
    // Hull mesh still acts as a silent gap-filler for exterior panels.
    const primTargets = [_surfaceMesh, _surfaceMesh2].filter(Boolean)
    if (primTargets.length) {
      const hits = _rc.intersectObjects(primTargets)
      if (hits.length && hits[0].face) {
        const src = hits[0].object === _surfaceMesh2 ? 'Regular polygon' : 'Exterior panels'
        return _resolveHit(hits[0], src)
      }
    }

    if (_hullMesh) {
      const hits = _rc.intersectObject(_hullMesh)
      if (hits.length && hits[0].face) return _resolveHit(hits[0], 'Hull surface (gap fallback)')
    }

    return null
  }

  // ── Hover grid updater ──────────────────────────────────────────────────────
  function _updateHoverGrid(hitPoint) {
    if (!_bundleInfo || !_surfaceHover) return
    const { bundleDir, axialMid, ringYs, vertsPerRing } = _bundleInfo

    // Convert hit world position to local Y on the prism.
    const localYHit = hitPoint.dot(bundleDir) - axialMid

    const colAttr = _surfaceHover.geometry.attributes.color
    const col     = colAttr.array
    let   vi      = 0  // vertex index into col array

    for (let ri = 0; ri < ringYs.length; ri++) {
      const dist  = Math.abs(ringYs[ri] - localYHit)
      const fade  = Math.max(0, 1 - dist / HOVER_RADIUS)
      const r = HOVER_R * fade, g = HOVER_G * fade, b = HOVER_B * fade
      for (let k = 0; k < vertsPerRing; k++, vi++) {
        col[vi * 3]     = r
        col[vi * 3 + 1] = g
        col[vi * 3 + 2] = b
      }
    }
    colAttr.needsUpdate = true
    _surfaceHover.visible = true
  }

  function _clearHoverGrid() {
    if (_hoverRafId !== null) { cancelAnimationFrame(_hoverRafId); _hoverRafId = null }
    if (!_surfaceHover) return
    _surfaceHover.visible = false
  }

  // ── Mouse-move: ghost preview + hover grid ──────────────────────────────────
  function _onSurfaceMove(e) {
    const hit = _getFaceHit(e)
    if (!hit) {
      _previewMesh.visible = false
      _clearHoverGrid()
      _dbgHide()
      return
    }
    // Ghost arrow: orient along outward face normal, offset so tip starts at surface.
    const { q } = _orientQ([hit.normal.x, hit.normal.y, hit.normal.z])
    _previewMesh.quaternion.copy(q)
    _previewMesh.position.copy(hit.point).addScaledVector(hit.normal, PREV_HALF_LEN)
    _previewMesh.visible = true

    const _hovPt = hit.point.clone()
    if (_hoverRafId !== null) cancelAnimationFrame(_hoverRafId)
    _hoverRafId = requestAnimationFrame(() => { _hoverRafId = null; _updateHoverGrid(_hovPt) })

    if (_showDebug) {
      const n  = hit.normal
      const az = Math.atan2(n.x, n.z) * 180 / Math.PI   // horizontal angle in XZ
      const el = Math.asin(Math.max(-1, Math.min(1, n.y))) * 180 / Math.PI
      const lines = [
        `source : ${hit.source}`,
        `normal : (${n.x.toFixed(3)}, ${n.y.toFixed(3)}, ${n.z.toFixed(3)})`,
        `azimuth: ${az.toFixed(1)}°   elev: ${el.toFixed(1)}°`,
        `point  : (${hit.point.x.toFixed(2)}, ${hit.point.y.toFixed(2)}, ${hit.point.z.toFixed(2)})`,
      ]
      if (hit.matchedPanel) {
        const p = hit.matchedPanel
        const panelAng = Math.atan2(p.nv, p.nu) * 180 / Math.PI
        lines.push(
          `── matched panel ──`,
          `angle  : ${panelAng.toFixed(1)}°`,
          `normal : (${p.nu.toFixed(3)}, ${p.nv.toFixed(3)})`,
          `rOffset: ${p.rOffset.toFixed(3)} nm`,
          `width  : ${(p.tMax - p.tMin).toFixed(3)} nm`,
          `tRange : [${p.tMin.toFixed(3)}, ${p.tMax.toFixed(3)}]`,
        )
      }
      _dbgShow(lines)
    }
  }

  // ── Drag guard: ignore clicks that followed an orbit drag ──────────────────
  const DRAG_THRESHOLD_PX = 6  // pixels — any movement beyond this = orbit, not click

  function _onPointerDown(e) {
    _pointerDownAt = { x: e.clientX, y: e.clientY }
  }

  function _wasDrag(e) {
    if (!_pointerDownAt) return false
    const dx = e.clientX - _pointerDownAt.x
    const dy = e.clientY - _pointerDownAt.y
    return (dx * dx + dy * dy) > DRAG_THRESHOLD_PX * DRAG_THRESHOLD_PX
  }

  // ── Click: create joint ─────────────────────────────────────────────────────
  function _onSurfaceClick(e) {
    if (_wasDrag(e)) return   // user was orbiting — do not place joint
    const hit = _getFaceHit(e)
    if (!hit) return
    const clusterId     = _definingCluster
    const surfaceDetail = _surfaceDetail
    exitDefineMode()
    api.createJoint(clusterId, {
      axis_origin:    [hit.point.x, hit.point.y, hit.point.z],
      axis_direction: [hit.normal.x, hit.normal.y, hit.normal.z],
      surface_detail: surfaceDetail,
    })
  }

  // ── Escape key ─────────────────────────────────────────────────────────────
  function _onKeyDown(e) {
    if (e.key === 'Escape') {
      e.preventDefault()
      exitDefineMode()
    }
  }

  // ── Define mode ────────────────────────────────────────────────────────────
  /**
   * Enter surface-click mode for joint definition.
   * @param {string}        clusterId
   * @param {function|null} onExit  — called when mode exits (click or Escape)
   */
  function enterDefineMode(clusterId, onExit = null) {
    exitDefineMode()
    _definingCluster = clusterId
    _onExitCb        = onExit

    const { currentDesign } = store.getState()
    const lattice  = currentDesign?.lattice_type ?? 'honeycomb'
    _surfaceDetail = lattice === 'square' ? MIN_SQ_FACES : MIN_HC_FACES

    _showSurface(clusterId, _surfaceDetail)
    canvas.style.cursor = 'crosshair'
    canvas.addEventListener('pointerdown',  _onPointerDown)
    canvas.addEventListener('pointermove',  _onSurfaceMove)
    canvas.addEventListener('click',        _onSurfaceClick)
    document.addEventListener('keydown',    _onKeyDown)
  }

  function exitDefineMode() {
    if (_hoverRafId !== null) { cancelAnimationFrame(_hoverRafId); _hoverRafId = null }
    _removeSurface()
    _previewMesh.visible = false
    canvas.removeEventListener('pointerdown',  _onPointerDown)
    canvas.removeEventListener('pointermove',  _onSurfaceMove)
    canvas.removeEventListener('click',        _onSurfaceClick)
    document.removeEventListener('keydown',    _onKeyDown)
    canvas.style.cursor = ''
    _definingCluster  = null
    _pointerDownAt    = null

    const cb = _onExitCb
    _onExitCb = null
    cb?.()
  }

  /** Toggle lattice exterior panels solid fill on/off. Grid rings always remain visible. */
  function setExteriorPanels(on) {
    _useExteriorPanels = !!on
    if (_surfaceMesh) {
      _surfaceMesh.material.opacity = (_useExteriorPanels && _showFill) ? _surfaceOpacityVal : 0
    }
  }

  /** Toggle hull surface on/off. */
  function setHullSurface(on) {
    _useHullSurface = !!on
    if (_hullMesh) {
      _hullMesh.material.opacity = (_useHullSurface && _showFill) ? _surfaceOpacityVal : 0
      _hullWire.material.opacity = (_useHullSurface && _showFill) ? Math.min(1, _surfaceOpacityVal * 3) : 0
    }
  }

  /** Toggle regular polygon surface on/off (can be shown alongside exterior panels). */
  function setRegularPolygon(on) {
    _useRegularPolygon = !!on
    if (_definingCluster) _showSurface(_definingCluster, _surfaceDetail)
  }

  /** Toggle solid fill on/off. When off, only the grid rings (cluster outline) remain visible.
   *  The mesh stays in the scene at opacity=0 so face-click raycasting still works. */
  /** Toggle live panel debug overlay on/off. */
  function setDebugOverlay(on) {
    _showDebug = !!on
    if (!_showDebug) _dbgHide()
  }

  function setShowFill(on) {
    _showFill = !!on
    if (_surfaceMesh)  _surfaceMesh.material.opacity  = (_useExteriorPanels && _showFill) ? _surfaceOpacityVal : 0
    if (_surfaceMesh2) _surfaceMesh2.material.opacity = _showFill ? _surfaceOpacityVal : 0
    if (_hullMesh) {
      _hullMesh.material.opacity = (_useHullSurface && _showFill) ? _surfaceOpacityVal : 0
      _hullWire.material.opacity = (_useHullSurface && _showFill) ? Math.min(1, _surfaceOpacityVal * 3) : 0
    }
  }

  // ── Joint indicator live-transform (follows cluster gizmo drag) ─────────────

  /**
   * Snapshot the current group position/quaternion for every joint whose cluster
   * contains any of the given helix IDs.  Call at gizmo drag-start (same timing
   * as helixCtrl.captureClusterBase).
   * @param {string[]} helixIds
   */
  function captureClusterBase(helixIds) {
    _cbJointBases.clear()
    _cbHullBases.clear()
    const { currentDesign } = store.getState()
    if (!currentDesign) return
    const helixSet   = new Set(helixIds)
    const clusterSet = new Set()
    for (const ct of currentDesign.cluster_transforms ?? []) {
      if (ct.helix_ids.some(h => helixSet.has(h))) clusterSet.add(ct.id)
    }
    if (currentDesign.cluster_joints?.length) {
      for (const joint of currentDesign.cluster_joints) {
        if (!clusterSet.has(joint.cluster_id)) continue
        const grp = _jointMeshes.get(joint.id)
        if (!grp) continue
        _cbJointBases.set(joint.id, { pos: grp.position.clone(), quat: grp.quaternion.clone() })
      }
    }
    // Hull-prism groups: one per cluster in _hullReprMeshes (when hull repr is on).
    // Snapshot every hull whose cluster intersects the moving helix set so the
    // applyClusterTransform pass below can rigidly transform the prism.
    for (const clusterId of clusterSet) {
      const grp = _hullReprMeshes.get(clusterId)
      if (!grp) continue
      _cbHullBases.set(clusterId, { pos: grp.position.clone(), quat: grp.quaternion.clone() })
    }
  }

  /**
   * Apply the same incremental rigid transform that helixCtrl.applyClusterTransform
   * applies to backbone beads, moving the joint indicator groups in sync.
   *
   * Formula: pos' = R_incr*(base − center) + dummyPos
   *
   * @param {string[]}         helixIds
   * @param {THREE.Vector3}    centerVec
   * @param {THREE.Vector3}    dummyPosVec
   * @param {THREE.Quaternion} incrRotQuat
   */
  function applyClusterTransform(_helixIds, centerVec, dummyPosVec, incrRotQuat) {
    for (const [jointId, base] of _cbJointBases) {
      const grp = _jointMeshes.get(jointId)
      if (!grp) continue
      _v3.copy(base.pos).sub(centerVec).applyQuaternion(incrRotQuat)
      grp.position.set(_v3.x + dummyPosVec.x, _v3.y + dummyPosVec.y, _v3.z + dummyPosVec.z)
      grp.quaternion.multiplyQuaternions(incrRotQuat, base.quat)
    }
    // Hull-prism groups: same rigid-transform formula. Inner panel/cap meshes
    // sit at world-space positions (set at build), so applying the standard
    // pos' = R*(pos - center) + dummy formula on the OUTER group reproduces
    // the cluster's transform on every child mesh exactly.
    for (const [clusterId, base] of _cbHullBases) {
      const grp = _hullReprMeshes.get(clusterId)
      if (!grp) continue
      _v3.copy(base.pos).sub(centerVec).applyQuaternion(incrRotQuat)
      grp.position.set(_v3.x + dummyPosVec.x, _v3.y + dummyPosVec.y, _v3.z + dummyPosVec.z)
      grp.quaternion.multiplyQuaternions(incrRotQuat, base.quat)
    }
  }

  // ── Hull representation (persistent solid hull per cluster) ──────────────────

  function _buildHullForCluster(cluster, helixAxes, ctx) {
    // 'extrusions' mode (no feature log → per-cluster scan): one bundle frame
    // per cluster, scanned along its own axis.
    if (_hullMode === 'extrusions' && ctx) {
      return _scanExtrusionGroup(cluster.helix_ids, ctx.scanAxes ?? helixAxes, ctx.helixBp, ctx.latticeType, cluster.name, ctx.scanTickBp)
    }
    // 'boxes' mode: per-helix occupancy boxes (grooves + axial teeth preserved).
    if (_hullMode === 'boxes' && ctx) {
      return _buildClusterBoxGroup(cluster, helixAxes, ctx.helixBp, ctx.spacing, _occBoxFill)
    }
    const { currentGeometry, currentDesign } = store.getState()
    const bg = _bundleGeometry(cluster, helixAxes, currentGeometry, MIN_HC_FACES,
                               _crossPaddingVal, _axialPaddingVal,
                               currentDesign?.lattice_type ?? null)
    if (!bg) return null

    const group = new THREE.Group()
    // Stash centroid + name so the debug overlay can place a label and so
    // disposal/styling can reach the prism without re-deriving geometry.
    group.userData.bundleMid   = bg.bundleMid.clone()
    group.userData.clusterName = cluster.name || 'Cluster'

    // Detect curved cluster: any helix has samples with more than 2 points.
    const isCurved = cluster.helix_ids.some(hid => (helixAxes[hid]?.samples?.length ?? 0) > 2)

    if (isCurved) {
      const sections = _computeSpineSections(cluster, helixAxes, _crossPaddingVal, _axialPaddingVal)
      if (sections) {
        // Curved hull — fully deformed shape; starts fully visible (t=1 initial state).
        const curvedGeo   = _buildSweptHullGeometry(sections)
        const curvedMesh  = new THREE.Mesh(curvedGeo, _hullMeshPhong(HULL_OPACITY))
        curvedMesh.renderOrder = 100
        const curvedEdgeMat = new THREE.LineBasicMaterial({ color: 0x000000, linewidth: 1, transparent: true, opacity: 1, depthWrite: false })
        const curvedEdges  = new THREE.LineSegments(new THREE.EdgesGeometry(curvedGeo, 15), curvedEdgeMat)
        curvedEdges.renderOrder = 101

        // Straight hull proxy — positioned at deformed axis midpoint, starts invisible (t=1).
        const straightGeo  = bg.panels
          ? _buildPanelSurface(bg.panels, bg.corners, bg.halfLen)
          : _buildPrismGeometry(bg.corners, bg.halfLen)
        const straightMesh = new THREE.Mesh(straightGeo, _hullMeshPhong(0))
        straightMesh.quaternion.copy(bg.rotQ)
        straightMesh.position.copy(bg.bundleMid)
        straightMesh.renderOrder = 100
        const straightEdgeMat = new THREE.LineBasicMaterial({ color: 0x000000, linewidth: 1, transparent: true, opacity: 0, depthWrite: false })
        const straightEdges   = new THREE.LineSegments(new THREE.EdgesGeometry(straightGeo, 15), straightEdgeMat)
        straightEdges.quaternion.copy(bg.rotQ)
        straightEdges.position.copy(bg.bundleMid)
        straightEdges.renderOrder = 101

        group.userData.curvedMesh    = curvedMesh
        group.userData.curvedEdges   = curvedEdges
        group.userData.straightMesh  = straightMesh
        group.userData.straightEdges = straightEdges
        group.add(curvedMesh, curvedEdges, straightMesh, straightEdges)
        return group
      }
    }

    // Straight hull (non-curved cluster, or curved sections failed to compute).
    const geo     = bg.panels
      ? _buildPanelSurface(bg.panels, bg.corners, bg.halfLen)
      : _buildPrismGeometry(bg.corners, bg.halfLen)
    const mesh    = new THREE.Mesh(geo, _hullMeshPhong(HULL_OPACITY))
    mesh.quaternion.copy(bg.rotQ)
    mesh.position.copy(bg.bundleMid)
    mesh.renderOrder = 100
    const edgeGeo = new THREE.EdgesGeometry(geo, 15)
    const edgeMat = new THREE.LineBasicMaterial({ color: 0x000000, linewidth: 1, depthWrite: false })
    const edges   = new THREE.LineSegments(edgeGeo, edgeMat)
    edges.quaternion.copy(bg.rotQ)
    edges.position.copy(bg.bundleMid)
    edges.renderOrder = 101
    group.add(mesh, edges)
    return group
  }

  function _rebuildHullRepr(design, helixAxes) {
    for (const grp of _hullReprMeshes.values()) {
      grp.traverse(o => { o.material?.map?.dispose(); o.geometry?.dispose(); o.material?.dispose() })
      grp.parent?.remove(grp)
    }
    _hullReprMeshes.clear()
    if (!_hullReprActive || !design) return

    // Axes for both the scan and the markers: dsDNA-trimmed in extrusions mode
    // (so ssDNA is excluded), full otherwise. Sharing them keeps the markers'
    // bundle frame identical to the rendered boxes' frame.
    const _scanAxes = (_hullMode === 'extrusions')
      ? _dsTrimmedAxes(store.getState().currentGeometry, helixAxes) : helixAxes

    // dsDNA base-pair counts per helix — drives ss exclusion (markers + hull
    // must use the same helix set so marker faces match the rendered boxes).
    const { helixBp, totalBp } = _dsBpByHelix(store.getState().currentGeometry)

    // Cluster selection — drop "whole-part" clusters (is_default OR ≥90% of
    // helices) that would enclose/duplicate the finer geometry clusters; fall
    // back to all clusters when no finer ones exist.
    const _totalHelices = (design.helices ?? []).length
    const _isWholePart  = (c) => c.is_default ||
      (_totalHelices > 0 && c.helix_ids.length >= 0.9 * _totalHelices)
    const _finer        = (design.cluster_transforms ?? []).filter(c => !_isWholePart(c))
    const _renderClusters = _finer.length ? _finer : (design.cluster_transforms ?? [])
    const _spacing = _helixSpacing(_scanAxes, (design.helices ?? []).map(h => h.id))

    // ── Build the hull ───────────────────────────────────────────────────────
    // Extrusion mode: NADOC-built parts use the feature-log build history,
    // split per finer cluster (so moved clusters follow their transform) with
    // everything else in '__extrusions__'. Imported parts (no build history)
    // fall through to the per-cluster cross-section scan (own frame + scan).
    let _hullDone = false
    if (_hullMode === 'extrusions') {
      // Split out finer clusters big enough to matter (≥ _hullMinSizeFraction of
      // dsDNA bp); small ones + the whole-part cluster keep their boxes in
      // '__extrusions__' so nothing vanishes. Each split cluster gets its own
      // keyed hull group whose boxes carry that cluster's rigid transform — so a
      // moved cluster's block follows on both live drag and post-commit rebuild
      // (parity with the cadnano per-cluster scan path).
      const _fracOf = (cl) => {
        if (totalBp <= 0) return 1
        let bp = 0; for (const hid of cl.helix_ids) bp += (helixBp.get(hid) ?? 0)
        return bp / totalBp
      }
      const _splitClusters = _finer.filter(c => _fracOf(c) >= _hullMinSizeFraction)

      // Pass RAW helixAxes (with .samples) — not _scanAxes (dsDNA-trimmed) — so a
      // deformed design sweeps each box along its spine. curveTol drives faceting.
      // dsBpRange gives each box its real (post-routing) dsDNA axial extent so the
      // hull lines up with the cylinder rep (back-porch ends, staggered starts).
      const _dsBpRange = _dsBpRangeByHelix(store.getState().currentGeometry)
      const fl = _buildExtrusionBoxes(design, helixAxes, _hullCurveTolNm,
        _splitClusters.length ? { clusters: _splitClusters, keyByCluster: true, dsBpRange: _dsBpRange } : null)
      if (fl instanceof Map) {
        for (const [key, grp] of fl) { scene.add(grp); _hullReprMeshes.set(key, grp) }
        _hullDone = true
      } else if (fl) {
        scene.add(fl); _hullReprMeshes.set('__extrusions__', fl); _hullDone = true
      } else if (!design.cluster_transforms?.length) {
        const grp = _scanExtrusionGroup((design.helices ?? []).map(h => h.id),
          _scanAxes, helixBp, design.lattice_type, design.metadata?.name, _hullScanTickBp)
        if (grp) { scene.add(grp); _hullReprMeshes.set('__extrusions__', grp) }
        _hullDone = true
      }
      // else: fall through to the per-cluster loop.
    }

    if (!_hullDone && design.cluster_transforms?.length && helixAxes) {
      // Per-cluster dsDNA base-pair fraction, used to drop clusters too small to
      // be worth a prism (and to label them in debug mode).
      const fractionOf = (cluster) => {
        if (totalBp <= 0) return 1
        let bp = 0
        for (const hid of cluster.helix_ids) bp += (helixBp.get(hid) ?? 0)
        return bp / totalBp
      }
      const ctx = { helixBp, spacing: _spacing, latticeType: design.lattice_type, scanTickBp: _hullScanTickBp, scanAxes: _scanAxes }

      let colorIdx = 0
      _renderClusters.forEach((cluster) => {
        const frac     = fractionOf(cluster)
        const excluded = frac < _hullMinSizeFraction
        // Normal mode: skip small clusters. Debug mode: still build them, faint.
        if (excluded && !_hullClusterDebug) return

        const grp = _buildHullForCluster(cluster, helixAxes, ctx)
        if (!grp) return
        grp.userData.bpFraction = frac
        grp.userData.excluded   = excluded

        if (_hullClusterDebug) {
          const color = _HULL_DEBUG_PALETTE[colorIdx++ % _HULL_DEBUG_PALETTE.length]
          // Curved groups carry both a visible curved mesh and a hidden straight
          // proxy — only restyle the visible one so the proxy stays hidden.
          const meshes = grp.userData.curvedMesh
            ? [grp.userData.curvedMesh]
            : (() => { const m = []; grp.traverse(o => { if (o.isMesh) m.push(o) }); return m })()
          for (const o of meshes) {
            if (!o.material?.color) continue
            o.material.color.setHex(color)
            o.material.transparent = true   // grey extrusion mat is opaque by default
            o.material.opacity = excluded ? 0.12 : 0.45
            o.material.wireframe = excluded
          }
          const pct = Math.round(frac * 100)
          const label = _makeClusterLabelSprite(
            `${grp.userData.clusterName} — ${pct}%${excluded ? ' (excl)' : ''}`, color)
          if (grp.userData.bundleMid) label.position.copy(grp.userData.bundleMid)
          grp.add(label)
        }

        scene.add(grp)
        _hullReprMeshes.set(cluster.id, grp)
      })
    }

    // ── Overhang markers ──────────────────────────────────────────────────────
    // Raycast each overhang against the BUILT hull surface so the quad lands
    // exactly on the rendered face (robust to per-segment cross-section,
    // dsDNA-trim, 5% filter, and cluster transforms).
    const _hullMeshes = []
    for (const [k, g] of _hullReprMeshes) {
      if (k === '__ovhg_markers__') continue
      g.traverse(o => { if (o.isMesh && o.geometry) _hullMeshes.push(o) })
    }
    const _markerClusters = _renderClusters.length
      ? _renderClusters
      : [{ helix_ids: (design.helices ?? []).map(h => h.id) }]
    const markers = _buildOverhangMarkers(design, _scanAxes, _markerClusters,
      store.getState().currentGeometry, helixBp, _hullMeshes)
    if (markers) { scene.add(markers); _hullReprMeshes.set('__ovhg_markers__', markers) }
  }

  function setHullRepr(on) {
    _hullReprActive = !!on
    const { currentDesign, currentHelixAxes } = store.getState()
    _rebuildHullRepr(currentDesign, currentHelixAxes)
  }

  /** Toggle the per-cluster hull debug overlay (distinct colors + size-% labels,
   *  excluded clusters shown faint). Rebuilds if hull repr is active. */
  function setHullClusterDebug(on) {
    _hullClusterDebug = !!on
    if (_hullReprActive) {
      const { currentDesign, currentHelixAxes } = store.getState()
      _rebuildHullRepr(currentDesign, currentHelixAxes)
    }
    return _hullClusterDebug
  }

  /** Minimum cluster size (dsDNA bp fraction of the whole origami, 0..1) to draw
   *  a hull prism. Clusters below this are excluded. Rebuilds if active. */
  function setHullMinSizeFraction(frac) {
    if (typeof frac === 'number' && frac >= 0 && frac <= 1) _hullMinSizeFraction = frac
    if (_hullReprActive) {
      const { currentDesign, currentHelixAxes } = store.getState()
      _rebuildHullRepr(currentDesign, currentHelixAxes)
    }
    return _hullMinSizeFraction
  }

  /** Hull geometry mode: 'boxes' (per-helix occupancy, default) or 'prism'
   *  (legacy convex bundle). Optionally set the box fill fraction (0..1).
   *  Rebuilds if active. */
  function setHullMode(mode, boxFill) {
    if (mode === 'boxes' || mode === 'prism' || mode === 'extrusions') _hullMode = mode
    if (typeof boxFill === 'number' && boxFill > 0 && boxFill <= 1) _occBoxFill = boxFill
    if (_hullReprActive) {
      const { currentDesign, currentHelixAxes } = store.getState()
      _rebuildHullRepr(currentDesign, currentHelixAxes)
    }
    return { mode: _hullMode, boxFill: _occBoxFill }
  }

  /** Extrusion-scan margin in bp — helix ends are rounded to this tick before
   *  cross-section boundaries are detected (extrusions mode, scan path).
   *  Larger = coarser segmentation. Rebuilds if active. */
  function setHullScanTick(bp) {
    if (typeof bp === 'number' && bp >= 1 && bp <= 128) _hullScanTickBp = bp
    if (_hullReprActive) {
      const { currentDesign, currentHelixAxes } = store.getState()
      _rebuildHullRepr(currentDesign, currentHelixAxes)
    }
    return _hullScanTickBp
  }

  // Curved-hull facet detail: max facet deviation from the true spine, in nm.
  // Larger = blockier/cheaper. Rebuilds the hull if active. Returns the value.
  function setHullCurveDetail(nm) {
    if (typeof nm === 'number' && nm >= 0 && nm <= 20) _hullCurveTolNm = nm
    if (_hullReprActive) {
      const { currentDesign, currentHelixAxes } = store.getState()
      _rebuildHullRepr(currentDesign, currentHelixAxes)
    }
    return _hullCurveTolNm
  }

  /**
   * Cross-fade hull prism between straight (t=0) and curved/deformed (t=1) state.
   * Only affects clusters that have both curvedMesh and straightMesh (bent clusters).
   */
  function applyDeformLerp(t) {
    for (const grp of _hullReprMeshes.values()) {
      const { curvedMesh, curvedEdges, straightMesh, straightEdges } = grp.userData
      if (!curvedMesh || !straightMesh) continue
      curvedMesh.material.opacity    = t * HULL_OPACITY
      straightMesh.material.opacity  = (1 - t) * HULL_OPACITY
      if (curvedEdges)   curvedEdges.material.opacity   = t
      if (straightEdges) straightEdges.material.opacity = 1 - t
    }
  }

  // ── Joint axis indicator management ──────────────────────────────────────
  // rebuild() is called from the cluster_joints store subscriber, which fires
  // whenever the cluster_joints array reference changes — including after
  // every cluster transform commit, because joint world axes (axis_origin /
  // axis_direction) are derived from cluster_transforms by the backend's
  // _inject_joint_world_axes. Plan B's skipGeometry path leaves
  // currentHelixAxes UNCHANGED on commit, so rebuilding hulls from those
  // stale axes here would snap hulls back to pre-commit positions and undo
  // the per-frame transform that applyClusterTransform applied during the
  // gizmo drag. Hulls are now updated rigidly by applyClusterTransform and
  // rebuilt only when their underlying inputs (currentHelixAxes,
  // cluster_transforms count) actually change — see the dedicated
  // currentHelixAxes subscriber wired in main.js.
  function rebuild(design) {
    for (const grp of _jointMeshes.values()) {
      grp.parent?.remove(grp)
      grp.traverse(o => {
        o.geometry?.dispose()
        if (o.material) { o.material.map?.dispose(); o.material.dispose() }
      })
    }
    _jointMeshes.clear()

    if (!design?.cluster_joints?.length) return

    for (const joint of design.cluster_joints) {
      const grp = _buildAxisIndicator(joint.axis_origin, joint.axis_direction)
      _jointGroup.add(grp)
      _jointMeshes.set(joint.id, grp)
    }
  }

  /** Rebuild hull-prism geometry from the current design + helix axes.
   *  Use this when something hull-relevant actually changed (helix axes
   *  refreshed via getGeometry, cluster added/removed, hull repr toggled).
   *  DO NOT call this on every cluster_joints update — it would destroy
   *  the hulls that applyClusterTransform just translated. */
  function rebuildHulls(design = null) {
    const state = store.getState()
    _rebuildHullRepr(design ?? state.currentDesign, state.currentHelixAxes)
  }

  function highlightJoint(jointId) {
    for (const [id, grp] of _jointMeshes) {
      const col = id === jointId ? 0xffff88 : 0xffffff
      // Skip materials with a texture map (the checkerboard sprite)
      grp.traverse(o => { if (o.isMesh && !o.material.map) o.material.color.setHex(col) })
    }
  }

  function clearHighlight() { highlightJoint(null) }

  /**
   * Raycast only the rotation ring on each joint indicator.
   * Returns the joint ID if the ring is hit, null otherwise.
   */
  function pickJointRing(e) {
    if (!_jointMeshes.size) return null
    _rc.setFromCamera(_ndc(e), camera)
    const rings = []
    for (const grp of _jointMeshes.values()) {
      grp.traverse(o => { if (o.isMesh && o.userData.isJointRing) rings.push(o) })
    }
    if (!rings.length) return null
    const hits = _rc.intersectObjects(rings, false)
    if (!hits.length) return null
    let obj = hits[0].object.parent
    while (obj) {
      for (const [jointId, grp] of _jointMeshes) {
        if (obj === grp) return jointId
      }
      obj = obj.parent
    }
    return null
  }

  /**
   * Raycast against all persistent joint indicator meshes.
   * Returns the joint ID (string) of the first hit, or null if none.
   * Ignores sprite meshes (those with a texture map).
   */
  function pickJoint(e) {
    if (!_jointMeshes.size) return null
    _rc.setFromCamera(_ndc(e), camera)
    const targets = []
    for (const grp of _jointMeshes.values()) {
      // Exclude sprite (has map) and rotation ring (isJointRing) — shaft/cone only
      grp.traverse(o => { if (o.isMesh && !o.material.map && !o.userData.isJointRing) targets.push(o) })
    }
    if (!targets.length) return null
    const hits = _rc.intersectObjects(targets, false)
    if (!hits.length) return null
    // Walk up the hierarchy to find the owning joint group
    let obj = hits[0].object
    while (obj) {
      for (const [jointId, grp] of _jointMeshes) {
        if (obj === grp) return jointId
      }
      obj = obj.parent
    }
    return null
  }

  /**
   * Raycast against every mesh of every joint indicator (shaft, cone, sprite,
   * ring). Used to make the whole joint icon selectable as a single target.
   * Returns the joint ID of the first hit, or null if none.
   */
  function pickJointAny(e) {
    if (!_jointMeshes.size) return null
    _rc.setFromCamera(_ndc(e), camera)
    const targets = []
    for (const grp of _jointMeshes.values()) {
      grp.traverse(o => { if (o.isMesh) targets.push(o) })
    }
    if (!targets.length) return null
    const hits = _rc.intersectObjects(targets, false)
    if (!hits.length) return null
    let obj = hits[0].object
    while (obj) {
      for (const [jointId, grp] of _jointMeshes) {
        if (obj === grp) return jointId
      }
      obj = obj.parent
    }
    return null
  }

  function dispose() {
    exitDefineMode()
    _previewMesh.traverse(o => {
      o.geometry?.dispose()
      if (o.material) { o.material.map?.dispose(); o.material.dispose() }
    })
    _previewMesh.parent?.remove(_previewMesh)
    for (const grp of _jointMeshes.values()) {
      grp.parent?.remove(grp)
      grp.traverse(o => {
        o.geometry?.dispose()
        if (o.material) { o.material.map?.dispose(); o.material.dispose() }
      })
    }
    _jointMeshes.clear()
    _jointGroup.parent?.remove(_jointGroup)
    for (const grp of _hullReprMeshes.values()) {
      grp.traverse(o => { o.material?.map?.dispose(); o.geometry?.dispose(); o.material?.dispose() })
      grp.parent?.remove(grp)
    }
    _hullReprMeshes.clear()
  }

  function setVisible(on) { _jointGroup.visible = on }
  function isVisible()    { return _jointGroup.visible }

  /**
   * Debug helper: recompute and return the exterior panel data for the cluster
   * currently in define mode.  Call from browser DevTools console while the
   * joint surface is visible.
   *
   * Returns null if not in define mode.
   * Returns { clusterId, latticeType, panels, corners, halfLen, helixCount }
   */
  function getPanels() {
    if (!_definingCluster) {
      console.warn('[nadoc:joint] getPanels(): no define mode active — enter joint-define mode first')
      return null
    }
    const { currentDesign, currentHelixAxes } = store.getState()
    const cluster = currentDesign?.cluster_transforms?.find(c => c.id === _definingCluster)
    if (!cluster || !currentHelixAxes) return null
    const lt = _useExteriorPanels ? (currentDesign?.lattice_type ?? null) : null
    const bg = _bundleGeometry(cluster, currentHelixAxes, null, _surfaceDetail,
                               _crossPaddingVal, _axialPaddingVal, lt)
    if (!bg) return null

    const result = {
      clusterId:   _definingCluster,
      latticeType: lt,
      panels:      bg.panels ?? null,
      corners:     bg.corners,
      halfLen:     bg.halfLen,
      helixCount:  cluster.helix_ids.length,
    }

    if (bg.panels) {
      console.group('[nadoc:joint] getPanels() — cluster ' + _definingCluster)
      console.log('latticeType:', lt, '   helices:', cluster.helix_ids.length)
      console.table(bg.panels.map(p => ({
        angle_deg:    Math.round(Math.atan2(p.nv, p.nu) * 180 / Math.PI),
        normal_u:     +p.nu.toFixed(4),
        normal_v:     +p.nv.toFixed(4),
        rOffset_nm:   +p.rOffset.toFixed(3),
        tMin_nm:      +p.tMin.toFixed(3),
        tMax_nm:      +p.tMax.toFixed(3),
        width_nm:     +(p.tMax - p.tMin).toFixed(3),
      })))
      console.groupEnd()
    } else {
      console.log('[nadoc:joint] getPanels(): cluster uses fallback N-gon (not lattice-based)')
    }
    return result
  }

  return { enterDefineMode, exitDefineMode, setExteriorPanels, setHullSurface, setRegularPolygon, setShowFill, setDebugOverlay, setHullRepr, setHullClusterDebug, setHullMinSizeFraction, setHullMode, setHullScanTick, setHullCurveDetail, applyDeformLerp, rebuild, rebuildHulls, highlightJoint, clearHighlight, pickJoint, pickJointRing, pickJointAny, captureClusterBase, applyClusterTransform, setVisible, isVisible, dispose, getPanels }
}

// ── Shared geometry utilities — imported by assembly_joint_renderer.js ────────
// These are pure module-level functions; calling them from another module works
// correctly because they close over the same module-scope constants and helpers.
export {
  _bundleGeometry         as buildBundleGeometry,
  _buildPrismGeometry     as buildPrismGeometry,
  _buildPanelSurface      as buildPanelSurface,
  _buildPreviewMesh       as buildJointPreviewMesh,
  _buildGridLines         as buildGridLines,
  _buildHoverLines        as buildJointHoverLines,
  _computeSpineSections   as buildSpineSections,
  _buildSweptHullGeometry as buildSweptHullGeometry,
  _hullMeshPhong          as buildHullMeshPhong,
  _buildExtrusionBoxes    as buildExtrusionBoxes,
  _scanExtrusionGroup     as scanExtrusionGroup,
  _dsTrimmedAxes          as dsTrimmedAxes,
  _dsBpByHelix            as dsBpByHelix,
  _dsBpRangeByHelix       as dsBpRangeByHelix,
  _buildOverhangMarkers   as buildOverhangMarkers,
  HULL_OPACITY,
  SURFACE_COLOUR, SURFACE_OPACITY,
  CROSS_MARGIN, AXIAL_MARGIN,
  PREV_HALF_LEN,
  MIN_HC_FACES, MIN_SQ_FACES,
  GRID_PERIOD_HC, GRID_PERIOD_SQ,
  HOVER_RADIUS, HOVER_R, HOVER_G, HOVER_B,
}
