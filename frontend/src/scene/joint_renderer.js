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
import {
  BDNA_RISE_PER_BP,
  HONEYCOMB_ROW_PITCH,
  SQUARE_HELIX_SPACING,
} from '../constants.js'

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

  if (backbonePositions?.length) {
    for (const nuc of backbonePositions) {
      if (helixSet.has(nuc.helix_id)) pts.push(new THREE.Vector3(...nuc.backbone_position))
    }
  }
  if (!pts.length) {
    for (const hid of cluster.helix_ids) {
      const ax = helixAxes[hid]
      if (ax) { pts.push(new THREE.Vector3(...ax.start), new THREE.Vector3(...ax.end)) }
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

  const latticeResult = latticeType
    ? _computeExteriorPanels(cluster.helix_ids, helixAxes, latticeType, U, V, centroid)
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
    const { currentDesign } = store.getState()
    if (!currentDesign?.cluster_joints?.length) return
    const helixSet   = new Set(helixIds)
    const clusterSet = new Set()
    for (const ct of currentDesign.cluster_transforms ?? []) {
      if (ct.helix_ids.some(h => helixSet.has(h))) clusterSet.add(ct.id)
    }
    for (const joint of currentDesign.cluster_joints) {
      if (!clusterSet.has(joint.cluster_id)) continue
      const grp = _jointMeshes.get(joint.id)
      if (!grp) continue
      _cbJointBases.set(joint.id, { pos: grp.position.clone(), quat: grp.quaternion.clone() })
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
    if (!_cbJointBases.size) return
    for (const [jointId, base] of _cbJointBases) {
      const grp = _jointMeshes.get(jointId)
      if (!grp) continue
      _v3.copy(base.pos).sub(centerVec).applyQuaternion(incrRotQuat)
      grp.position.set(_v3.x + dummyPosVec.x, _v3.y + dummyPosVec.y, _v3.z + dummyPosVec.z)
      grp.quaternion.multiplyQuaternions(incrRotQuat, base.quat)
    }
  }

  // ── Hull representation (persistent solid hull per cluster) ──────────────────

  function _buildHullForCluster(cluster, helixAxes) {
    const bg = _bundleGeometry(cluster, helixAxes, null, MIN_HC_FACES,
                               _crossPaddingVal, _axialPaddingVal,
                               store.getState().currentDesign?.lattice_type ?? null)
    if (!bg) return null
    const geo = _buildPrismGeometry(bg.corners, bg.halfLen)

    // Phong shading — responds to the scene's ambient + directional lights.
    // polygonOffset pushes the solid surface behind the edge lines to avoid z-fighting.
    const mat = new THREE.MeshPhongMaterial({
      color: HULL_COLOUR,
      transparent: true, opacity: 0.72,
      side: THREE.DoubleSide,
      shininess: 60,
      specular: new THREE.Color(0x88ccff),
      polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
    })
    const mesh = new THREE.Mesh(geo, mat)
    mesh.quaternion.copy(bg.rotQ)
    mesh.position.copy(bg.bundleMid)
    mesh.renderOrder = 100

    // EdgesGeometry traces only hard edges (angle > threshold), giving clean
    // silhouette lines without the diagonals that WireframeGeometry produces.
    const edgeGeo = new THREE.EdgesGeometry(geo, 15)  // 15° threshold
    const edgeMat = new THREE.LineBasicMaterial({ color: 0x000000, linewidth: 1 })
    const edges   = new THREE.LineSegments(edgeGeo, edgeMat)
    edges.quaternion.copy(bg.rotQ)
    edges.position.copy(bg.bundleMid)
    edges.renderOrder = 101

    const group = new THREE.Group()
    group.add(mesh, edges)
    return group
  }

  function _rebuildHullRepr(design, helixAxes) {
    for (const grp of _hullReprMeshes.values()) {
      grp.traverse(o => { o.geometry?.dispose(); o.material?.dispose() })
      grp.parent?.remove(grp)
    }
    _hullReprMeshes.clear()
    if (!_hullReprActive || !design?.cluster_transforms?.length || !helixAxes) return
    for (const cluster of design.cluster_transforms) {
      const grp = _buildHullForCluster(cluster, helixAxes)
      if (grp) { scene.add(grp); _hullReprMeshes.set(cluster.id, grp) }
    }
  }

  function setHullRepr(on) {
    _hullReprActive = !!on
    const { currentDesign, currentHelixAxes } = store.getState()
    _rebuildHullRepr(currentDesign, currentHelixAxes)
  }

  // ── Joint axis indicator management ──────────────────────────────────────
  function rebuild(design) {
    for (const grp of _jointMeshes.values()) {
      grp.parent?.remove(grp)
      grp.traverse(o => {
        o.geometry?.dispose()
        if (o.material) { o.material.map?.dispose(); o.material.dispose() }
      })
    }
    _jointMeshes.clear()

    const { currentHelixAxes } = store.getState()
    _rebuildHullRepr(design, currentHelixAxes)

    if (!design?.cluster_joints?.length) return

    for (const joint of design.cluster_joints) {
      const grp = _buildAxisIndicator(joint.axis_origin, joint.axis_direction)
      _jointGroup.add(grp)
      _jointMeshes.set(joint.id, grp)
    }
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
      grp.traverse(o => { o.geometry?.dispose(); o.material?.dispose() })
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

  return { enterDefineMode, exitDefineMode, setExteriorPanels, setHullSurface, setRegularPolygon, setShowFill, setDebugOverlay, setHullRepr, rebuild, highlightJoint, clearHighlight, pickJoint, pickJointRing, captureClusterBase, applyClusterTransform, setVisible, isVisible, dispose, getPanels }
}
