/**
 * Overhang Link Arcs.
 *
 * Draws a white tube arc in 3D for every entry in design.overhang_connections.
 * The arc anchors at the LINKER complement strand (`__lnk__<conn>__a` / `__b`),
 * not at the overhang itself — it emerges from the freshly-paired complement
 * nucleotide that sits at the user-specified attach end of the overhang.
 * ssDNA connections use the same visual language as crossover extra bases:
 * the saved linker length is rendered as bead+slab instances distributed along
 * a visible backbone arc. dsDNA connections render an ideal double-stranded
 * segment at the midpoint between anchors, with short arcs from each overhang
 * binding domain to the appropriate end of that segment.
 *
 * Pure visualisation — no interaction in v1.
 *
 * Usage:
 *   const arcs = initOverhangLinkArcs(scene)
 *   arcs.rebuild(design, geometry)
 *   arcs.dispose()
 */

import * as THREE from 'three'
import { BDNA_RISE_PER_BP } from '../constants.js'
import { CONE_RADIUS } from './helix_renderer.js'
import {
  bezierAt,
  bezierTangent,
  arcControlPoint,
  arcSlabQuaternion,
  SLAB_LENGTH,
  SLAB_WIDTH,
  SLAB_THICK,
  SLAB_OFFSET,
} from './crossover_connections.js'

const ARC_COLOR        = 0xffffff
const ARC_TUBE_RADIUS  = 0.30   // nm — visibly thicker than backbone beads (0.10)
const ARC_TUBE_SEGS    = 48
const ARC_TUBE_RADSEG  = 10
const ARC_HEIGHT_FRAC  = 0.30   // Bézier control offset = chord_length × this, perpendicular to chord
const DEBUG = true   // logs to console when rebuild runs; toggle off when stable
const SS_BEAD_RADIUS   = 0.10   // nm — matches crossover extra-base beads
const SS_ARC_RADIUS    = 0.055  // nm — thin backbone through ssDNA linker beads
const DS_ARC_RADIUS    = 0.065  // nm — connector from OH binding domain to ds segment
const DS_COARSE_RADIUS = 0.32   // nm — cylinder-mode-only duplex domain stand-in
const GEO_SS_BEAD      = new THREE.SphereGeometry(SS_BEAD_RADIUS, 8, 6)
const GEO_SS_SLAB      = new THREE.BoxGeometry(1, 1, 1)
const GEO_DS_CONE      = new THREE.ConeGeometry(1, 1, 8)
const HELIX_RADIUS     = 1.0
const BDNA_TWIST_RAD   = 34.3 * Math.PI / 180
const MINOR_GROOVE_RAD = 150 * Math.PI / 180
const Y_HAT            = new THREE.Vector3(0, 1, 0)

export function initOverhangLinkArcs(scene) {
  const group = new THREE.Group()
  group.name = 'overhangLinkArcs'
  scene.add(group)
  const _raycaster = new THREE.Raycaster()
  const _ndc = new THREE.Vector2()
  let _ssEntries = []
  let _highlightedIds = new Set()
  let _detailLevel = 0
  let _cgVisible = true

  function rebuild(design, geometry) {
    _clear()
    if (!design || !geometry) {
      if (DEBUG) console.debug('[overhangLinkArcs] skip rebuild — design=%o geometry=%o', !!design, !!geometry)
      return
    }
    // geometry from the store is the bare nucleotides array, not a wrapped object.
    const nucs = Array.isArray(geometry) ? geometry : (geometry.nucleotides ?? [])
    const conns = design.overhang_connections ?? []
    if (DEBUG) console.debug('[overhangLinkArcs] rebuild: %d connection(s), %d nucs in geometry', conns.length, nucs.length)
    if (conns.length === 0) return
    const nucsByOvhg   = _indexNucsByOverhang(nucs)
    const nucsByStrand = _indexNucsByStrand(nucs)
    const strandById   = new Map((design.strands ?? []).map(s => [s.id, s]))

    for (const conn of conns) {
      const a = _linkerAttachAnchor(nucsByOvhg, nucsByStrand, conn.id, 'a',
                                    conn.overhang_a_id, conn.overhang_a_attach)
      const b = _linkerAttachAnchor(nucsByOvhg, nucsByStrand, conn.id, 'b',
                                    conn.overhang_b_id, conn.overhang_b_attach)
      if (!a || !b) {
        if (DEBUG) console.debug('[overhangLinkArcs] conn %s: missing positions  a=%o  b=%o', conn.name ?? conn.id, !!a, !!b)
        continue
      }
      if (DEBUG) console.debug('[overhangLinkArcs] conn %s: arc from (%s,%s,%s) to (%s,%s,%s)',
        conn.name ?? conn.id,
        a.pos.x.toFixed(2), a.pos.y.toFixed(2), a.pos.z.toFixed(2),
        b.pos.x.toFixed(2), b.pos.y.toFixed(2), b.pos.z.toFixed(2))
      const colorA = _strandCssToHex(strandById.get(`__lnk__${conn.id}__a`)?.color) ?? ARC_COLOR
      const colorB = _strandCssToHex(strandById.get(`__lnk__${conn.id}__b`)?.color) ?? ARC_COLOR
      if (conn.linker_type === 'ss') {
        const color = colorA
        const ssGroup = _makeSsLinkerMeshes(conn, a, b, color)
        ssGroup.userData.connId = conn.id
        ssGroup.userData.strandIds = _linkerStrandIds(conn.id)
        group.add(ssGroup)
        const entry = {
          connId: conn.id,
          strandIds: _linkerStrandIds(conn.id),
          group: ssGroup,
          kind: 'ss',
          beads: ssGroup.getObjectByName('overhangSsLinkerBeads'),
          slabs: ssGroup.getObjectByName('overhangSsLinkerSlabs'),
          backbone: ssGroup.getObjectByName('overhangSsLinkerBackboneArc'),
          pickables: [
            ssGroup.getObjectByName('overhangSsLinkerBackboneArc'),
            ssGroup.getObjectByName('overhangSsLinkerBeads'),
          ].filter(Boolean),
          defaultColor: color,
          defaultScale: 1.0,
        }
        _ssEntries.push(entry)
      } else {
        const dsGroup = _makeDsLinkerMeshes(conn, a, b, colorA, colorB)
        dsGroup.userData.connId = conn.id
        dsGroup.userData.strandIds = _linkerStrandIds(conn.id)
        group.add(dsGroup)
        _ssEntries.push({
          connId: conn.id,
          strandIds: _linkerStrandIds(conn.id),
          group: dsGroup,
          kind: 'ds',
          beads: dsGroup.getObjectByName('overhangDsLinkerBeads'),
          slabs: dsGroup.getObjectByName('overhangDsLinkerSlabs'),
          cones: dsGroup.getObjectByName('overhangDsLinkerCones'),
          backbone: dsGroup.getObjectByName('overhangDsConnectorArcA'),
          coarse: dsGroup.getObjectByName('overhangDsCoarseCylinder'),
          connectorArcs: [
            dsGroup.getObjectByName('overhangDsConnectorArcA'),
            dsGroup.getObjectByName('overhangDsConnectorArcB'),
          ].filter(Boolean),
          pickables: [
            dsGroup.getObjectByName('overhangDsConnectorArcA'),
            dsGroup.getObjectByName('overhangDsConnectorArcB'),
            dsGroup.getObjectByName('overhangDsLinkerBeads'),
            dsGroup.getObjectByName('overhangDsCoarseCylinder'),
          ].filter(Boolean),
          defaultColor: colorA,
          defaultScale: 1.0,
        })
      }
    }
    if (DEBUG) console.debug('[overhangLinkArcs] rebuild done — group has %d children', group.children.length)
    _applyHighlight()
    _applyDetailVisibility()
  }

  function dispose() {
    _clear()
    if (group.parent) group.parent.remove(group)
  }

  function _clear() {
    _ssEntries = []
    while (group.children.length) {
      const m = group.children[0]
      group.remove(m)
      _disposeRenderable(m)
    }
  }

  function hitTest(clientX, clientY, camera, canvas, thresholdPx = 12) {
    if (!_ssEntries.length || !camera || !canvas) return null
    const rect = canvas.getBoundingClientRect()
    _ndc.x = ((clientX - rect.left) / rect.width) * 2 - 1
    _ndc.y = -((clientY - rect.top) / rect.height) * 2 + 1
    _raycaster.setFromCamera(_ndc, camera)

    const objects = []
    for (const e of _ssEntries) {
      objects.push(...(e.pickables ?? []))
    }
    const hits = _raycaster.intersectObjects(objects, false)
    if (hits.length) {
      const entry = _ssEntries.find(e => (e.pickables ?? []).includes(hits[0].object))
      if (entry) return { connId: entry.connId, strandIds: entry.strandIds, strandId: entry.strandIds[0] }
    }

    // TubeGeometry ray hits can be fussy when viewed edge-on, so also test the
    // projected arc midpoint. This mirrors the crossover arc debug path and is
    // intentionally screen-space; it makes ss linker selection reliable after
    // reloads and camera changes.
    const w = rect.width, h = rect.height
    const p = new THREE.Vector3()
    let best = null
    let bestDist = thresholdPx
    for (const e of _ssEntries) {
      if (!e.backbone) continue
      e.backbone.geometry.boundingSphere ?? e.backbone.geometry.computeBoundingSphere()
      p.copy(e.backbone.geometry.boundingSphere.center).applyMatrix4(e.backbone.matrixWorld).project(camera)
      const px = (p.x * 0.5 + 0.5) * w
      const py = (-p.y * 0.5 + 0.5) * h
      const d = Math.hypot(px - (clientX - rect.left), py - (clientY - rect.top))
      if (d < bestDist) { bestDist = d; best = e }
    }
    return best ? { connId: best.connId, strandIds: best.strandIds, strandId: best.strandIds[0] } : null
  }

  function setHighlightedStrands(strandIds) {
    _highlightedIds = new Set(strandIds ?? [])
    _applyHighlight()
  }

  function setDetailLevel(level) {
    _cgVisible = true
    _detailLevel = Number.isFinite(level) ? level : 0
    _applyDetailVisibility()
  }

  function setRepresentation(repr) {
    if (repr === 'full' || repr === 'beads' || repr === 'cylinders') {
      setDetailLevel({ full: 0, beads: 1, cylinders: 2 }[repr])
      return
    }
    _cgVisible = false
    _applyDetailVisibility()
  }

  function setVisible(visible) {
    _cgVisible = !!visible
    _applyDetailVisibility()
  }

  function _applyDetailVisibility() {
    group.visible = _cgVisible
    if (!_cgVisible) return
    const full = _detailLevel <= 0
    const coarse = _detailLevel >= 2
    for (const e of _ssEntries) {
      if (e.beads) e.beads.visible = !coarse
      if (e.slabs) e.slabs.visible = full
      if (e.cones) e.cones.visible = !coarse
      if (e.coarse) e.coarse.visible = coarse
      if (e.kind === 'ss' && e.backbone) e.backbone.visible = true
      for (const arc of e.connectorArcs ?? []) arc.visible = true
    }
  }

  function _applyHighlight() {
    for (const e of _ssEntries) {
      const on = e.strandIds.some(id => _highlightedIds.has(id))
      _scaleSsBeads(e.beads, on ? 1.3 : 1.0)
      e.group?.traverse?.((obj) => {
        if (!obj.material?.color) return
        const defaultColor = obj.userData?.defaultColor ?? e.defaultColor
        obj.material.color.setHex(on ? 0xff4444 : defaultColor)
      })
    }
  }

  return { rebuild, dispose, group, hitTest, setHighlightedStrands, setDetailLevel, setRepresentation, setVisible }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _disposeRenderable(root) {
  root.traverse?.((obj) => {
    if (obj.geometry && obj.geometry !== GEO_SS_BEAD && obj.geometry !== GEO_SS_SLAB && obj.geometry !== GEO_DS_CONE) {
      obj.geometry.dispose()
    }
    if (obj.material) {
      if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose())
      else obj.material.dispose()
    }
  })
}

function _indexNucsByOverhang(nucs) {
  const map = new Map()
  for (const n of nucs) {
    if (!n.overhang_id) continue
    let arr = map.get(n.overhang_id)
    if (!arr) { arr = []; map.set(n.overhang_id, arr) }
    arr.push(n)
  }
  return map
}

function _indexNucsByStrand(nucs) {
  const map = new Map()
  for (const n of nucs) {
    if (!n.strand_id) continue
    let arr = map.get(n.strand_id)
    if (!arr) { arr = []; map.set(n.strand_id, arr) }
    arr.push(n)
  }
  return map
}

function _vec3(p) {
  return p ? new THREE.Vector3(p[0], p[1], p[2]) : null
}

function _linkerStrandIds(connId) {
  return [`__lnk__${connId}__a`, `__lnk__${connId}__b`]
}

function _strandCssToHex(css) {
  if (typeof css !== 'string' || !/^#[0-9a-fA-F]{6}$/.test(css)) return null
  return parseInt(css.slice(1), 16)
}

function _scaleSsBeads(beads, scale) {
  if (!beads) return
  const m = new THREE.Matrix4()
  const pos = new THREE.Vector3()
  const q = new THREE.Quaternion()
  const scl = new THREE.Vector3(scale, scale, scale)
  for (let i = 0; i < beads.count; i++) {
    beads.getMatrixAt(i, m)
    pos.setFromMatrixPosition(m)
    beads.setMatrixAt(i, m.compose(pos, q, scl))
  }
  beads.instanceMatrix.needsUpdate = true
}

function _makeTubeMesh(points, radius, color, name, opacity = 0.85) {
  const curve = points.length === 3
    ? new THREE.QuadraticBezierCurve3(points[0], points[1], points[2])
    : new THREE.LineCurve3(points[0], points[1])
  const mesh = new THREE.Mesh(
    new THREE.TubeGeometry(curve, ARC_TUBE_SEGS, radius, 8, false),
    new THREE.MeshBasicMaterial({ color, transparent: opacity < 1, opacity }),
  )
  mesh.name = name
  mesh.userData.defaultColor = color
  return mesh
}

function _makeCylinderBetween(a, b, radius, color, name, opacity = 0.85) {
  const dir = b.clone().sub(a)
  const len = dir.length()
  const geom = new THREE.CylinderGeometry(1, 1, 1, 12)
  const mat = new THREE.MeshBasicMaterial({ color, transparent: opacity < 1, opacity })
  const mesh = new THREE.Mesh(geom, mat)
  mesh.name = name
  mesh.userData.defaultColor = color
  if (len > 1e-6) {
    mesh.position.copy(a).add(b).multiplyScalar(0.5)
    mesh.quaternion.setFromUnitVectors(Y_HAT, dir.normalize())
    mesh.scale.set(radius, len, radius)
  }
  return mesh
}

function _frameFromAxis(axisDir, preferredNormal = null) {
  const z = axisDir.clone().normalize()
  let x = preferredNormal?.clone?.() ?? new THREE.Vector3(0, 0, 1)
  x.addScaledVector(z, -x.dot(z))
  if (x.lengthSq() < 1e-6) {
    x = Math.abs(z.z) < 0.9 ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(1, 0, 0)
    x.addScaledVector(z, -x.dot(z))
  }
  x.normalize()
  const y = new THREE.Vector3().crossVectors(z, x).normalize()
  return { x, y, z }
}

function _quadraticCtrlBetween(a, b, axisDir) {
  const ctrl = new THREE.Vector3()
  const chord = b.clone().sub(a)
  const len = chord.length() || 1
  let bow = chord.clone().cross(axisDir)
  if (bow.lengthSq() < 1e-6) bow = chord.clone().cross(new THREE.Vector3(0, 0, 1))
  if (bow.lengthSq() < 1e-6) bow = chord.clone().cross(new THREE.Vector3(1, 0, 0))
  bow.normalize().multiplyScalar(len * 0.25)
  return ctrl.copy(a).add(b).multiplyScalar(0.5).add(bow)
}

export function linkerLengthToBases(conn) {
  const value = Number(conn?.length_value)
  if (!Number.isFinite(value) || value <= 0) return 1
  if (conn?.length_unit === 'nm') return Math.max(1, Math.round(value / BDNA_RISE_PER_BP))
  return Math.max(1, Math.round(value))
}

/**
 * Find the OH nucleotide that sits at the user-chosen attach end:
 *   free_end → the strand-terminal nucleotide (5'/3' tip of the overhang).
 *   root     → the OH nucleotide farthest from the tip in bp space
 *              (= the one nearest the bundle junction).
 * Returns the nuc object (so we can read both its position and bp_index), or
 * null if the OH has no nucs in geometry yet.
 */
function _ohAttachNuc(nucsByOvhg, ovhgId, attach) {
  const nucs = nucsByOvhg.get(ovhgId)
  if (!nucs || nucs.length === 0) return null
  const tip = nucs.find(n => n.is_five_prime || n.is_three_prime) ?? nucs[0]
  if (attach !== 'root' || nucs.length < 2) return tip
  let target = tip, bestDist = -1
  for (const n of nucs) {
    const d = Math.abs((n.bp_index ?? 0) - (tip.bp_index ?? 0))
    if (d > bestDist) { bestDist = d; target = n }
  }
  return target
}

/**
 * Anchor position for one side of the arc, picked off the LINKER complement
 * strand rather than the overhang itself.
 *
 * Strategy: locate the OH nucleotide at the chosen attach end (helix_id +
 * bp_index); then find the linker complement nucleotide at the same helix
 * and bp (the antiparallel partner). The arc thus emerges from the linker
 * strand bead instead of the overhang bead.
 *
 * Falls back to the OH nucleotide position when the linker strand has no
 * geometry (e.g. synthetic test seed where the OverhangSpec lacks a backing
 * domain), so the arc still draws something useful.
 */
export function resolveLinkerAttachAnchor(nucs, connId, side, ovhgId, attach) {
  return _linkerAttachAnchor(_indexNucsByOverhang(nucs), _indexNucsByStrand(nucs), connId, side, ovhgId, attach)
}

function _linkerAttachAnchor(nucsByOvhg, nucsByStrand, connId, side, ovhgId, attach) {
  const ohNuc = _ohAttachNuc(nucsByOvhg, ovhgId, attach)
  if (!ohNuc) return null

  const linkerStrandId = `__lnk__${connId}__${side}`
  const linkerNucs = (nucsByStrand.get(linkerStrandId) ?? [])
    .filter(n => !(n.helix_id ?? '').startsWith('__lnk__'))   // drop bridge nucs (virtual helix)

  // Anchor at the COMPLEMENT'S 3' end (the bead at the END of the
  // complement domain in 5'→3' walk order on its real helix). The bridge
  // tube's first/last bead snaps to this anchor — they're sequential
  // nucleotides on the same strand, so they should be colocalized.
  // Implementation: among the complement nucs on the OH's helix, pick the
  // one farthest from the OH's tip in bp index — that's the OPPOSITE end
  // of the complement domain (= the complement's 3' end relative to the
  // bridge attachment).
  let chosen = null
  if (linkerNucs.length) {
    const sameHelix = linkerNucs.filter(n => n.helix_id === ohNuc.helix_id)
    if (sameHelix.length) {
      const tipBp = ohNuc.bp_index
      chosen = sameHelix.reduce((best, n) =>
        Math.abs(n.bp_index - tipBp) > Math.abs(best.bp_index - tipBp) ? n : best,
        sameHelix[0])
    } else {
      chosen = linkerNucs.find(n => n.is_three_prime) ?? linkerNucs[linkerNucs.length - 1]
    }
  }
  const nuc = chosen ?? ohNuc
  const pos = _vec3(nuc.backbone_position ?? nuc.base_position)
  return pos ? { pos, nuc, usedLinkerComplement: chosen != null } : null
}

function _makeArcMesh(a, b) {
  const chord = b.clone().sub(a)
  const len   = chord.length() || 1
  // Pick a perpendicular: cross with +Z (or +X if chord is parallel to Z) to
  // get a stable arc plane. Bend the curve away from the structure.
  const up = new THREE.Vector3(0, 0, 1)
  let perp = chord.clone().cross(up)
  if (perp.lengthSq() < 1e-6) perp = chord.clone().cross(new THREE.Vector3(1, 0, 0))
  perp.normalize().multiplyScalar(len * ARC_HEIGHT_FRAC)
  const mid = a.clone().add(b).multiplyScalar(0.5).add(perp)

  const curve = new THREE.QuadraticBezierCurve3(a, mid, b)
  const tube  = new THREE.TubeGeometry(curve, ARC_TUBE_SEGS, ARC_TUBE_RADIUS, ARC_TUBE_RADSEG, false)
  const mat   = new THREE.MeshBasicMaterial({ color: ARC_COLOR, transparent: true, opacity: 0.85 })
  return new THREE.Mesh(tube, mat)
}

function _fallbackArcControlPoint(posA, posB, out) {
  const chord = posB.clone().sub(posA)
  const len = chord.length() || 1
  const up = new THREE.Vector3(0, 0, 1)
  let perp = chord.clone().cross(up)
  if (perp.lengthSq() < 1e-6) perp = chord.clone().cross(new THREE.Vector3(1, 0, 0))
  perp.normalize().multiplyScalar(len * ARC_HEIGHT_FRAC)
  return out.copy(posA).add(posB).multiplyScalar(0.5).add(perp)
}

function _hasArcFrame(nuc) {
  return Array.isArray(nuc?.axis_tangent) && Array.isArray(nuc?.base_normal)
}

function _makeSsLinkerMeshes(conn, anchorA, anchorB, color = ARC_COLOR) {
  const baseCount = linkerLengthToBases(conn)
  const group = new THREE.Group()
  group.name = 'overhangSsLinkerBases'
  group.userData = {
    debugType: 'overhangSsLinkerBases',
    baseCount,
    connId: conn.id,
    defaultColor: color,
  }

  const beadMat = new THREE.MeshPhongMaterial({ color })
  const slabMat = new THREE.MeshPhongMaterial({ color, transparent: true, opacity: 0.90 })
  const beads = new THREE.InstancedMesh(GEO_SS_BEAD, beadMat, baseCount)
  const slabs = new THREE.InstancedMesh(GEO_SS_SLAB, slabMat, baseCount)
  beads.frustumCulled = false
  slabs.frustumCulled = false
  beads.name = 'overhangSsLinkerBeads'
  slabs.name = 'overhangSsLinkerSlabs'

  const posA = anchorA.pos
  const posB = anchorB.pos
  const ctrl = new THREE.Vector3()
  const pt = new THREE.Vector3()
  const tan = new THREE.Vector3()
  const slabOffsetDir = new THREE.Vector3(0, 0, 1)
  const quat = new THREE.Quaternion()
  const mat = new THREE.Matrix4()
  const scl = new THREE.Vector3()
  const idQuat = new THREE.Quaternion()
  const slabPt = new THREE.Vector3()

  if (_hasArcFrame(anchorA.nuc) && _hasArcFrame(anchorB.nuc)) {
    arcControlPoint(posA, posB, anchorA.nuc, anchorB.nuc, ctrl)
    slabOffsetDir.set(
      anchorA.nuc.base_normal[0] + anchorB.nuc.base_normal[0],
      anchorA.nuc.base_normal[1] + anchorB.nuc.base_normal[1],
      anchorA.nuc.base_normal[2] + anchorB.nuc.base_normal[2],
    )
    if (slabOffsetDir.lengthSq() < 1e-9) slabOffsetDir.set(...anchorA.nuc.base_normal)
    slabOffsetDir.normalize()
  } else {
    // Important debug note: synthetic/linker fixture geometry can lack the
    // axis_tangent/base_normal fields that crossover extra-base rendering uses.
    // Keep the ss linker visible with the legacy arc plane in that case.
    _fallbackArcControlPoint(posA, posB, ctrl)
    slabOffsetDir.copy(ctrl).sub(posA).add(ctrl.clone().sub(posB)).normalize()
  }

  const curve = new THREE.QuadraticBezierCurve3(posA, ctrl, posB)
  const backbone = new THREE.Mesh(
    new THREE.TubeGeometry(curve, ARC_TUBE_SEGS, SS_ARC_RADIUS, 8, false),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.85 }),
  )
  backbone.name = 'overhangSsLinkerBackboneArc'

  for (let i = 1; i <= baseCount; i++) {
    const idx = i - 1
    const t = i / (baseCount + 1)
    bezierAt(posA, ctrl, posB, t, pt)
    mat.compose(pt, idQuat, scl.set(1, 1, 1))
    beads.setMatrixAt(idx, mat)

    bezierTangent(posA, ctrl, posB, t, tan)
    if (tan.lengthSq() < 1e-9) tan.subVectors(posB, posA)
    tan.normalize()
    arcSlabQuaternion(tan, slabOffsetDir, quat)
    slabPt.copy(pt).addScaledVector(slabOffsetDir, SLAB_OFFSET)
    mat.compose(slabPt, quat, scl.set(SLAB_LENGTH, SLAB_WIDTH, SLAB_THICK))
    slabs.setMatrixAt(idx, mat)
  }

  beads.instanceMatrix.needsUpdate = true
  slabs.instanceMatrix.needsUpdate = true
  group.add(backbone, beads, slabs)
  return group
}

function _makeDsLinkerMeshes(conn, anchorA, anchorB, colorA = ARC_COLOR, colorB = ARC_COLOR) {
  const baseCount = linkerLengthToBases(conn)
  const group = new THREE.Group()
  group.name = 'overhangDsLinkerSegment'
  group.userData = {
    debugType: 'overhangDsLinkerSegment',
    baseCount,
    connId: conn.id,
    purpose: 'Two linker strands bind each other for the assigned length; connector arcs attach their strand starts to the overhang-binding complement domains.',
  }

  const posA = anchorA.pos
  const posB = anchorB.pos
  const mid = posA.clone().add(posB).multiplyScalar(0.5)
  const chord = posB.clone().sub(posA)
  let axisDir = chord.lengthSq() > 1e-9 ? chord.normalize() : new THREE.Vector3(0, 0, 1)
  if (axisDir.lengthSq() < 1e-9) axisDir = new THREE.Vector3(0, 0, 1)

  const preferredNormal = _hasArcFrame(anchorA.nuc)
    ? new THREE.Vector3(...anchorA.nuc.base_normal)
    : null
  const frame = _frameFromAxis(axisDir, preferredNormal)
  const visualLength = Math.max(baseCount - 1, 1) * BDNA_RISE_PER_BP
  const axisStart = mid.clone().addScaledVector(frame.z, -visualLength * 0.5)
  const axisEnd = axisStart.clone().addScaledVector(frame.z, visualLength)

  const totalNucs = baseCount * 2
  const beadMat = new THREE.MeshPhongMaterial({ color: ARC_COLOR })
  const slabMat = new THREE.MeshPhongMaterial({ color: ARC_COLOR, transparent: true, opacity: 0.90 })
  const beads = new THREE.InstancedMesh(GEO_SS_BEAD, beadMat, totalNucs)
  const slabs = new THREE.InstancedMesh(GEO_SS_SLAB, slabMat, totalNucs)
  const cones = new THREE.InstancedMesh(
    GEO_DS_CONE,
    new THREE.MeshPhongMaterial({ color: ARC_COLOR }),
    Math.max(1, Math.max(0, baseCount - 1) * 2),
  )
  beads.frustumCulled = false
  slabs.frustumCulled = false
  cones.frustumCulled = false
  beads.name = 'overhangDsLinkerBeads'
  slabs.name = 'overhangDsLinkerSlabs'
  cones.name = 'overhangDsLinkerCones'

  const strandAPoints = []
  const strandBPoints = []
  const mat = new THREE.Matrix4()
  const scl = new THREE.Vector3()
  const q = new THREE.Quaternion()
  const slabPt = new THREE.Vector3()
  const color = new THREE.Color()
  let idx = 0

  // Boundary beads sit at axis_start / axis_end (radial = 0) so they
  // colocalize with their anchor (complement's 3' end) when the chord
  // matches visualLength. Interior beads keep the full HELIX_RADIUS so
  // the tube reads as proper helical B-DNA. (The snap-to-posA we tried
  // earlier hid the relax progress — pre-relax should show a clear gap
  // between the bridge boundary bead and the anchor; only after relax
  // does chord = visualLength make axis_start = posA, collapsing the gap.)
  for (let i = 0; i < baseCount; i++) {
    const axisPt = axisStart.clone().addScaledVector(frame.z, i * BDNA_RISE_PER_BP)
    const ang = i * BDNA_TWIST_RAD
    const radialA = frame.x.clone().multiplyScalar(Math.cos(ang))
      .addScaledVector(frame.y, Math.sin(ang))
    const radialB = frame.x.clone().multiplyScalar(Math.cos(ang + MINOR_GROOVE_RAD))
      .addScaledVector(frame.y, Math.sin(ang + MINOR_GROOVE_RAD))
    const radA = (i === 0)             ? 0 : HELIX_RADIUS
    const radB = (i === baseCount - 1) ? 0 : HELIX_RADIUS
    const bbA = axisPt.clone().addScaledVector(radialA, radA)
    const bbB = axisPt.clone().addScaledVector(radialB, radB)
    const bnA = bbB.clone().sub(bbA).normalize()
    const bnB = bnA.clone().multiplyScalar(-1)
    strandAPoints.push(bbA)
    strandBPoints.push(bbB)

    // Strand A bridge is FORWARD (0 -> length-1); strand B bridge is REVERSE
    // in topology, but geometrically it occupies the complementary backbone.
    for (const [bb, bn, c] of [[bbA, bnA, colorA], [bbB, bnB, colorB]]) {
      mat.compose(bb, new THREE.Quaternion(), scl.set(1, 1, 1))
      beads.setMatrixAt(idx, mat)
      beads.setColorAt(idx, color.setHex(c))

      arcSlabQuaternion(frame.z, bn, q)
      slabPt.copy(bb).addScaledVector(bn, SLAB_OFFSET)
      mat.compose(slabPt, q, scl.set(SLAB_LENGTH, SLAB_WIDTH, SLAB_THICK))
      slabs.setMatrixAt(idx, mat)
      slabs.setColorAt(idx, color.setHex(c))
      idx++
    }
  }

  beads.instanceMatrix.needsUpdate = true
  slabs.instanceMatrix.needsUpdate = true
  if (beads.instanceColor) beads.instanceColor.needsUpdate = true
  if (slabs.instanceColor) slabs.instanceColor.needsUpdate = true

  let coneIdx = 0
  function addCone(from, to, c) {
    const dir = to.clone().sub(from)
    const dist = dir.length()
    if (dist < 1e-6) return
    const unit = dir.clone().divideScalar(dist)
    const mid = from.clone().addScaledVector(unit, dist * 0.5)
    const quat = new THREE.Quaternion().setFromUnitVectors(Y_HAT, unit)
    mat.compose(mid, quat, scl.set(CONE_RADIUS, Math.max(0.001, dist), CONE_RADIUS))
    cones.setMatrixAt(coneIdx, mat)
    cones.setColorAt(coneIdx, color.setHex(c))
    coneIdx++
  }
  for (let i = 0; i < baseCount - 1; i++) {
    addCone(strandAPoints[i], strandAPoints[i + 1], colorA)
    // Topology for strand B is reverse on this bridge, so the direction cue runs
    // from high bp to low bp even though the geometric points are stored low→high.
    addCone(strandBPoints[i + 1], strandBPoints[i], colorB)
  }
  if (coneIdx === 0) {
    mat.compose(mid, new THREE.Quaternion(), scl.set(0, 0, 0))
    cones.setMatrixAt(0, mat)
  }
  cones.instanceMatrix.needsUpdate = true
  if (cones.instanceColor) cones.instanceColor.needsUpdate = true

  const aStart = strandAPoints[0]
  const aEnd = strandAPoints[strandAPoints.length - 1]
  const bStart = strandBPoints[strandBPoints.length - 1]
  const bEnd = strandBPoints[0]
  group.userData.dsConnectorEnds = { aStart, aEnd, bStart, bEnd }

  // Connector arcs: only drawn when the boundary bead actually sits off
  // the OH-side anchor — which only happens during legacy/non-snapped
  // builds. With the boundary snap above, aStart == posA and bStart ==
  // posB; the would-be tube collapses to zero length and TubeGeometry
  // degenerates, so skip the draw call entirely.
  const ARC_EPSILON = 1e-3
  if (posA.distanceTo(aStart) > ARC_EPSILON) {
    group.add(_makeTubeMesh([posA, _quadraticCtrlBetween(posA, aStart, frame.z), aStart], DS_ARC_RADIUS, colorA, 'overhangDsConnectorArcA'))
  }
  if (posB.distanceTo(bStart) > ARC_EPSILON) {
    group.add(_makeTubeMesh([posB, _quadraticCtrlBetween(posB, bStart, frame.z), bStart], DS_ARC_RADIUS, colorB, 'overhangDsConnectorArcB'))
  }
  // Cylinder LOD needs a helix-domain surrogate, but keep it hidden for
  // Full/Beads so ds linkers still have only one visible connector arc per
  // strand in those representations.
  const coarse = _makeCylinderBetween(axisStart, axisEnd, DS_COARSE_RADIUS, colorA, 'overhangDsCoarseCylinder', 0.75)
  coarse.visible = false
  group.add(coarse)
  group.add(beads, cones, slabs)
  return group
}
