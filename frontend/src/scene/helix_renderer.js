/**
 * Helix renderer — builds Three.js instanced objects from geometry API data.
 *
 * Uses THREE.InstancedMesh for all nucleotide components so the entire design
 * renders in 4 WebGL draw calls regardless of helix count or length:
 *   iSpheres  — backbone beads (all non-5′ nucleotides)
 *   iCubes    — 5′-end markers (one per strand)
 *   iCones    — strand-direction connectors
 *   iSlabs    — base-pair orientation slabs
 *
 * Entry shapes exposed in backboneEntries / coneEntries / slabEntries:
 *   backbone  { instMesh, id, nuc, pos, defaultColor }
 *   cone      { instMesh, id, fromNuc, toNuc, strandId,
 *               midPos, quat, coneHeight, coneRadius, defaultColor }
 *   slab      { instMesh, id, nuc, quat, bnDir, bbPos, defaultColor }
 *
 * Callers update instance colors/scales via the helper methods exposed on the
 * return object (setEntryColor, setBeadScale, setConeXZScale) rather than
 * accessing mesh.material directly.
 */

import * as THREE from 'three'

// ── Constants ─────────────────────────────────────────────────────────────────

const HELIX_RADIUS = 1.0   // nm — must match backend/core/constants.py

// ── Palette ───────────────────────────────────────────────────────────────────

const C = {
  scaffold_backbone: 0x29b6f6,
  scaffold_slab:     0x0277bd,
  scaffold_arrow:    0x0288d1,
  axis:              0x555566,
  highlight_red:     0xff3333,
  highlight_blue:    0x3399ff,
  highlight_yellow:  0xffdd00,
  highlight_magenta: 0xff00ff,
  highlight_orange:  0xff8c00,
  white:             0xffffff,
  dim:               0x15202e,
  unassigned:        0x445566,
}

const STAPLE_PALETTE = [
  0xff6b6b, 0xffd93d, 0x6bcb77, 0xf9844a, 0xa29bfe, 0xff9ff3,
  0x00cec9, 0xe17055, 0x74b9ff, 0x55efc4, 0xfdcb6e, 0xd63031,
]

function buildStapleColorMap(geometry) {
  const map = new Map()
  let idx = 0
  for (const nuc of geometry) {
    if (nuc.strand_id && !nuc.is_scaffold && !map.has(nuc.strand_id)) {
      map.set(nuc.strand_id, STAPLE_PALETTE[idx % STAPLE_PALETTE.length])
      idx++
    }
  }
  return map
}

function nucColor(nuc, stapleColorMap, customColors, loopSet) {
  if (!nuc.strand_id)  return C.unassigned
  if (nuc.is_scaffold) return C.scaffold_backbone
  if (loopSet.has(nuc.strand_id)) return C.highlight_red
  if (customColors[nuc.strand_id] != null) return customColors[nuc.strand_id]
  return stapleColorMap.get(nuc.strand_id) ?? C.unassigned
}
function nucSlabColor(nuc, stapleColorMap, customColors, loopSet) {
  if (!nuc.strand_id)  return C.unassigned
  if (nuc.is_scaffold) return C.scaffold_slab
  if (loopSet.has(nuc.strand_id)) return C.highlight_red
  if (customColors[nuc.strand_id] != null) return customColors[nuc.strand_id]
  return stapleColorMap.get(nuc.strand_id) ?? C.unassigned
}
function nucArrowColor(nuc, stapleColorMap, customColors, loopSet) {
  if (!nuc.strand_id)  return C.unassigned
  if (nuc.is_scaffold) return C.scaffold_arrow
  if (loopSet.has(nuc.strand_id)) return C.highlight_red
  if (customColors[nuc.strand_id] != null) return customColors[nuc.strand_id]
  return stapleColorMap.get(nuc.strand_id) ?? C.unassigned
}

// ── Shared geometries ─────────────────────────────────────────────────────────

export const BEAD_RADIUS  = 0.10
export const CONE_RADIUS  = 0.075

const Y_HAT       = new THREE.Vector3(0, 1, 0)
const ID_QUAT     = new THREE.Quaternion()

const GEO_SPHERE    = new THREE.SphereGeometry(BEAD_RADIUS, 10, 8)
const GEO_CUBE_5P   = new THREE.BoxGeometry(0.18, 0.18, 0.18)
const GEO_UNIT_BOX  = new THREE.BoxGeometry(1, 1, 1)
const GEO_UNIT_CONE = new THREE.ConeGeometry(1, 1, 8)

// ── Reusable temporaries (never held across async boundaries) ─────────────────

const _tColor  = new THREE.Color()
const _tMatrix = new THREE.Matrix4()
const _tScale  = new THREE.Vector3()
const _tPos    = new THREE.Vector3()
const _physDir = new THREE.Vector3()   // physics position update scratch vector

// ── Instance update helpers ───────────────────────────────────────────────────

function _setInstColor(entry, hexColor) {
  entry.instMesh.setColorAt(entry.id, _tColor.setHex(hexColor))
  entry.instMesh.instanceColor.needsUpdate = true
}

/**
 * Set backbone bead scale (uniform).  Beads have no rotation so the matrix is
 * compose(pos, identity, (s,s,s)).
 */
function _setBeadScale(entry, s) {
  _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(s, s, s))
  entry.instMesh.setMatrixAt(entry.id, _tMatrix)
  entry.instMesh.instanceMatrix.needsUpdate = true
}

/**
 * Set cone XZ radius while preserving its stored midPos, quat, and coneHeight.
 */
function _setConeXZScale(entry, r) {
  _tMatrix.compose(entry.midPos, entry.quat, _tScale.set(r, entry.coneHeight, r))
  entry.instMesh.setMatrixAt(entry.id, _tMatrix)
  entry.instMesh.instanceMatrix.needsUpdate = true
}

// ── Slab helpers ──────────────────────────────────────────────────────────────

function slabQuaternion(bnDir, tanDir) {
  const tangential = new THREE.Vector3().crossVectors(tanDir, bnDir).normalize()
  const m = new THREE.Matrix4().makeBasis(tangential, tanDir, bnDir)
  return new THREE.Quaternion().setFromRotationMatrix(m)
}

function slabCenter(bbPos, bnDir, distance) {
  return bbPos.clone().addScaledVector(bnDir, HELIX_RADIUS - distance)
}

// ── Main builder ──────────────────────────────────────────────────────────────

export function buildHelixObjects(geometry, design, scene, customColors = {}, loopStrandIds = [], helixAxes = null) {
  const loopSet = new Set(loopStrandIds)

  // ── Index geometry ─────────────────────────────────────────────────────────

  const byStrand = new Map()
  const byBp     = new Map()

  for (const nuc of geometry) {
    const key = nuc.strand_id ?? `__${nuc.helix_id}:${nuc.direction}`
    if (!byStrand.has(key)) byStrand.set(key, [])
    byStrand.get(key).push(nuc)

    if (!byBp.has(nuc.bp_index)) byBp.set(nuc.bp_index, {})
    byBp.get(nuc.bp_index)[nuc.direction] = nuc
  }

  for (const [, nucs] of byStrand) {
    nucs.sort((a, b) => {
      const di = (a.domain_index ?? 0) - (b.domain_index ?? 0)
      if (di !== 0) return di
      return a.direction === 'FORWARD' ? a.bp_index - b.bp_index : b.bp_index - a.bp_index
    })
  }

  // ── Root group ─────────────────────────────────────────────────────────────

  const root = new THREE.Group()
  scene.add(root)

  // ── Helix axis arrows (cylinder shaft + cone head, individually built) ──────
  // Using CylinderGeometry instead of ArrowHelper so shaft thickness is scalable
  // for the deformation tool mode (where thick arrows are needed for usability).

  const AXIS_SHAFT_R  = 0.05   // normal shaft radius (nm)
  const AXIS_HEAD_LEN = 0.55   // cone height (nm)
  const AXIS_HEAD_RAD = 0.22   // cone base radius (nm)
  const _AY = new THREE.Vector3(0, 1, 0)

  const axisArrows = []   // each: { shaft, head, origin, isCurved }

  for (const helix of design.helices) {
    const axDef    = helixAxes?.[helix.id]
    const samples  = axDef?.samples
    const isCurved = samples != null && samples.length > 2

    const aStart = axDef
      ? new THREE.Vector3(...axDef.start)
      : new THREE.Vector3(helix.axis_start.x, helix.axis_start.y, helix.axis_start.z)
    const aEnd   = axDef
      ? new THREE.Vector3(...axDef.end)
      : new THREE.Vector3(helix.axis_end.x,   helix.axis_end.y,   helix.axis_end.z)

    // Arrowhead direction: last segment of the (possibly curved) axis
    const lastDir = (isCurved && samples.length >= 2)
      ? new THREE.Vector3(...samples[samples.length - 1])
          .sub(new THREE.Vector3(...samples[samples.length - 2])).normalize()
      : aEnd.clone().sub(aStart).normalize()

    const headMat = new THREE.MeshPhongMaterial({ color: C.axis })
    const head = new THREE.Mesh(
      new THREE.ConeGeometry(AXIS_HEAD_RAD, AXIS_HEAD_LEN, 8),
      headMat,
    )
    head.position.copy(aEnd)
    head.quaternion.setFromUnitVectors(_AY, lastDir)
    root.add(head)

    let shaft      // THREE.Mesh (cylinder) for straight | TubeGeometry mesh for curved
    let arrowGroup = null   // only set for straight helices

    if (isCurved) {
      // Smooth tube along the deformed helical axis (CatmullRom through sample points)
      const pts   = samples.map(s => new THREE.Vector3(...s))
      const curve = new THREE.CatmullRomCurve3(pts)
      const segs  = Math.max(samples.length * 4, 16)
      const geo   = new THREE.TubeGeometry(curve, segs, AXIS_SHAFT_R, 6, false)
      shaft = new THREE.Mesh(geo, new THREE.MeshPhongMaterial({ color: C.axis }))
      root.add(shaft)
    } else {
      // Straight: single cylinder in a group so it can be positioned via rotation
      const aVec     = aEnd.clone().sub(aStart)
      const aLen     = aVec.length()
      const aDir     = aVec.clone().normalize()
      const shaftLen = Math.max(0.01, aLen - AXIS_HEAD_LEN)

      const shaftMat = new THREE.MeshPhongMaterial({ color: C.axis })
      shaft = new THREE.Mesh(
        new THREE.CylinderGeometry(AXIS_SHAFT_R, AXIS_SHAFT_R, shaftLen, 8),
        shaftMat,
      )
      shaft.position.set(0, shaftLen / 2, 0)

      arrowGroup = new THREE.Group()
      arrowGroup.position.copy(aStart)
      arrowGroup.quaternion.setFromUnitVectors(_AY, aDir)
      arrowGroup.add(shaft)
      root.add(arrowGroup)
    }

    const originMat = new THREE.MeshPhongMaterial({ color: C.axis })
    const origin = new THREE.Mesh(new THREE.SphereGeometry(0.07, 8, 6), originMat)
    origin.position.copy(aStart)
    root.add(origin)

    axisArrows.push({
      shaft, head, origin, isCurved,
      helixId: helix.id,
      arrowGroup,
      aStart: aStart.clone(),
      aEnd:   aEnd.clone(),
    })
  }

  // ── Staple colour map ──────────────────────────────────────────────────────

  const stapleColorMap = buildStapleColorMap(geometry)

  // ── Backbone beads (InstancedMesh) ────────────────────────────────────────

  const sphereNucs  = geometry.filter(n => !n.is_five_prime)
  const cubeNucs    = geometry.filter(n =>  n.is_five_prime)

  const iSpheres = new THREE.InstancedMesh(
    GEO_SPHERE, new THREE.MeshPhongMaterial({ color: 0xffffff }), sphereNucs.length)
  const iCubes   = new THREE.InstancedMesh(
    GEO_CUBE_5P, new THREE.MeshPhongMaterial({ color: 0xffffff }), Math.max(1, cubeNucs.length))
  iSpheres.name = 'backboneSpheres'
  iCubes.name   = 'backboneCubes'
  root.add(iSpheres)
  root.add(iCubes)

  const backboneEntries = []
  let sphereId = 0, cubeId = 0

  for (const nuc of geometry) {
    const color = nucColor(nuc, stapleColorMap, customColors, loopSet)
    const pos   = new THREE.Vector3(...nuc.backbone_position)
    _tMatrix.compose(pos, ID_QUAT, _tScale.set(1, 1, 1))

    if (nuc.is_five_prime) {
      iCubes.setMatrixAt(cubeId, _tMatrix)
      iCubes.setColorAt(cubeId, _tColor.setHex(color))
      backboneEntries.push({ instMesh: iCubes, id: cubeId, nuc, pos, defaultColor: color })
      cubeId++
    } else {
      iSpheres.setMatrixAt(sphereId, _tMatrix)
      iSpheres.setColorAt(sphereId, _tColor.setHex(color))
      backboneEntries.push({ instMesh: iSpheres, id: sphereId, nuc, pos, defaultColor: color })
      sphereId++
    }
  }

  iSpheres.instanceMatrix.needsUpdate = true
  iSpheres.instanceColor.needsUpdate  = true
  iCubes.instanceMatrix.needsUpdate   = true
  iCubes.instanceColor.needsUpdate    = true

  // ── Strand direction cones (InstancedMesh) ────────────────────────────────

  let totalCones = 0
  for (const [, nucs] of byStrand) totalCones += Math.max(0, nucs.length - 1)

  const iCones = new THREE.InstancedMesh(
    GEO_UNIT_CONE, new THREE.MeshPhongMaterial({ color: 0xffffff }), Math.max(1, totalCones))
  iCones.name = 'strandCones'
  root.add(iCones)

  const coneEntries = []
  let coneId = 0

  for (const [, nucs] of byStrand) {
    const color = nucArrowColor(nucs[0], stapleColorMap, customColors, loopSet)
    for (let i = 0; i < nucs.length - 1; i++) {
      const from   = new THREE.Vector3(...nucs[i].backbone_position)
      const to     = new THREE.Vector3(...nucs[i + 1].backbone_position)
      const dir    = to.clone().sub(from)
      const dist   = dir.length()
      const coneHeight = Math.max(0.001, dist)
      const midPos = from.clone().addScaledVector(dir.clone().normalize(), dist / 2)
      const quat   = new THREE.Quaternion().setFromUnitVectors(Y_HAT, dir.clone().normalize())

      _tMatrix.compose(midPos, quat, _tScale.set(CONE_RADIUS, coneHeight, CONE_RADIUS))
      iCones.setMatrixAt(coneId, _tMatrix)
      iCones.setColorAt(coneId, _tColor.setHex(color))

      coneEntries.push({
        instMesh: iCones, id: coneId,
        fromNuc: nucs[i], toNuc: nucs[i + 1],
        strandId: nucs[i].strand_id,
        midPos, quat, coneHeight,
        coneRadius: CONE_RADIUS,
        defaultColor: color,
      })
      coneId++
    }
  }

  iCones.instanceMatrix.needsUpdate = true
  iCones.instanceColor.needsUpdate  = true

  // ── Base slabs (InstancedMesh) ────────────────────────────────────────────

  const slabParams = { length: 0.30, width: 0.06, thickness: 0.70, distance: 0.55 }

  const iSlabs = new THREE.InstancedMesh(
    GEO_UNIT_BOX,
    new THREE.MeshPhongMaterial({ color: 0xffffff, transparent: true, opacity: 0.90 }),
    Math.max(1, geometry.length),
  )
  iSlabs.name = 'baseSlabs'
  root.add(iSlabs)

  const slabEntries = []
  let slabId = 0

  for (const nuc of geometry) {
    const bnDir  = new THREE.Vector3(...nuc.base_normal)
    const tanDir = new THREE.Vector3(...nuc.axis_tangent)
    const quat   = slabQuaternion(bnDir, tanDir)
    const color  = nucSlabColor(nuc, stapleColorMap, customColors, loopSet)
    const bbPos  = new THREE.Vector3(...nuc.backbone_position)
    const center = slabCenter(bbPos, bnDir, slabParams.distance)

    _tMatrix.compose(center, quat, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
    iSlabs.setMatrixAt(slabId, _tMatrix)
    iSlabs.setColorAt(slabId, _tColor.setHex(color))

    slabEntries.push({ instMesh: iSlabs, id: slabId, nuc, quat, bnDir, bbPos, defaultColor: color })
    slabId++
  }

  iSlabs.instanceMatrix.needsUpdate = true
  iSlabs.instanceColor.needsUpdate  = true

  // ── Slider update ──────────────────────────────────────────────────────────

  function applySlabParams() {
    for (const entry of slabEntries) {
      const center = slabCenter(entry.bbPos, entry.bnDir, slabParams.distance)
      _tMatrix.compose(center, entry.quat, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
      iSlabs.setMatrixAt(entry.id, _tMatrix)
    }
    iSlabs.instanceMatrix.needsUpdate = true
  }

  const sliderDefs = [
    { id: 'sl-length',    val: 'sv-length',    key: 'length'    },
    { id: 'sl-width',     val: 'sv-width',     key: 'width'     },
    { id: 'sl-thickness', val: 'sv-thickness', key: 'thickness' },
    { id: 'sl-distance',  val: 'sv-distance',  key: 'distance'  },
  ]
  for (const { id, val, key } of sliderDefs) {
    const input = document.getElementById(id)
    const label = document.getElementById(val)
    if (!input) continue
    input.addEventListener('input', () => {
      slabParams[key] = parseFloat(input.value)
      label.textContent = parseFloat(input.value).toFixed(2)
      applySlabParams()
    })
  }

  // ── Validation overlay ─────────────────────────────────────────────────────

  let overlayObjects = []
  let distLabelInfo  = null

  function clearOverlay() {
    for (const obj of overlayObjects) {
      root.remove(obj)
      if (obj.geometry) obj.geometry.dispose()
      if (obj.material) obj.material.dispose()
    }
    overlayObjects = []
    document.querySelector('.dist-label')?.remove()
    distLabelInfo = null
  }

  // ── Reset helpers ──────────────────────────────────────────────────────────

  /**
   * Reset all instance colours and bead scales.
   *
   * dimmed=true  →  colour all instances with C.dim (dark slate) to indicate
   *                 they are "background".  A validation mode then selectively
   *                 re-colours its highlighted subset.
   * dimmed=false →  restore each instance to its defaultColor.
   */
  function resetAllToDefault(dimmed = false) {
    const dimHex = C.dim
    for (const entry of backboneEntries) {
      _setInstColor(entry, dimmed ? dimHex : entry.defaultColor)
      _setBeadScale(entry, 1.0)
    }
    for (const entry of coneEntries) {
      _setInstColor(entry, dimmed ? dimHex : entry.defaultColor)
      _setConeXZScale(entry, CONE_RADIUS)
    }
    for (const entry of slabEntries) {
      _setInstColor(entry, dimmed ? dimHex : entry.defaultColor)
    }
    const axisOpacity = dimmed ? 0.15 : 1.0
    for (const { shaft, head, origin } of axisArrows) {
      for (const m of [shaft?.material, head.material, origin.material]) {
        if (!m) continue
        m.opacity     = axisOpacity
        m.transparent = dimmed
      }
    }
  }

  function highlightBackbone(nuc, color, scale = 1) {
    const entry = backboneEntries.find(e => e.nuc === nuc)
    if (!entry) return
    _setInstColor(entry, color)
    _setBeadScale(entry, scale)
  }

  function setDistLabel(midpoint, text) {
    distLabelInfo = { midpoint, text }
  }

  // ── Validation modes ───────────────────────────────────────────────────────

  function modeNormal() { clearOverlay(); resetAllToDefault(false) }
  function modeV21()    { clearOverlay(); resetAllToDefault(false) }

  function modeV11() {
    clearOverlay()
    resetAllToDefault(false)
    for (const entry of backboneEntries) {
      if (entry.nuc.direction === 'REVERSE') _setInstColor(entry, C.dim)
    }
    for (const entry of slabEntries) {
      if (entry.nuc.direction === 'REVERSE') _setInstColor(entry, C.dim)
    }
  }

  function modeV12() {
    clearOverlay()
    resetAllToDefault(true)
    const bp0 = byBp.get(0)?.['FORWARD']
    const bp1 = byBp.get(1)?.['FORWARD']
    if (!bp0 || !bp1) return
    highlightBackbone(bp0, C.highlight_red, 3.0)
    highlightBackbone(bp1, C.highlight_red, 3.0)
    const lineGeo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(...bp0.backbone_position),
      new THREE.Vector3(...bp1.backbone_position),
    ])
    const line = new THREE.Line(lineGeo, new THREE.LineBasicMaterial({ color: C.white }))
    root.add(line)
    overlayObjects.push(line)
    const v   = new THREE.Vector3(...bp1.backbone_position).sub(new THREE.Vector3(...bp0.backbone_position))
    const tan = new THREE.Vector3(...bp0.axis_tangent)
    const mid = [
      (bp0.backbone_position[0] + bp1.backbone_position[0]) / 2,
      (bp0.backbone_position[1] + bp1.backbone_position[1]) / 2,
      (bp0.backbone_position[2] + bp1.backbone_position[2]) / 2,
    ]
    setDistLabel(mid, `axial rise: ${Math.abs(v.dot(tan)).toFixed(4)} nm`)
  }

  function modeV13() {
    clearOverlay()
    resetAllToDefault(true)
    const bp0 = byBp.get(0)?.['FORWARD']
    if (!bp0) return
    highlightBackbone(bp0, C.highlight_red, 2.0)
    const se = slabEntries.find(e => e.nuc === bp0)
    if (se) _setInstColor(se, C.highlight_yellow)
    const spike = new THREE.ArrowHelper(
      new THREE.Vector3(...bp0.base_normal),
      new THREE.Vector3(...bp0.backbone_position),
      1.5, C.highlight_yellow, 0.25, 0.10,
    )
    root.add(spike)
    overlayObjects.push(spike)
  }

  function modeV14() {
    clearOverlay()
    resetAllToDefault(true)
    const bp10f = byBp.get(10)?.['FORWARD']
    const bp10r = byBp.get(10)?.['REVERSE']
    if (!bp10f || !bp10r) return
    highlightBackbone(bp10f, C.highlight_red,  3.0)
    highlightBackbone(bp10r, C.highlight_blue, 3.0)
    const lineGeo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(...bp10f.backbone_position),
      new THREE.Vector3(...bp10r.backbone_position),
    ])
    const line = new THREE.Line(lineGeo, new THREE.LineBasicMaterial({ color: C.white }))
    root.add(line)
    overlayObjects.push(line)
    for (const { shaft, head, origin } of axisArrows) {
      for (const m of [shaft?.material, head.material, origin.material]) {
        if (!m) continue
        m.color.setHex(C.white)
        m.opacity     = 1.0
        m.transparent = false
      }
    }
  }

  function modeV22() {
    clearOverlay()
    resetAllToDefault(true)
    for (const entry of backboneEntries) {
      if (entry.nuc.is_five_prime || entry.nuc.is_three_prime) highlightBackbone(entry.nuc, C.white, 3.0)
    }
  }

  function modeV23() {
    clearOverlay()
    resetAllToDefault(true)
    for (const entry of backboneEntries) {
      if (entry.nuc.is_five_prime)  highlightBackbone(entry.nuc, C.scaffold_backbone, 3.0)
      if (entry.nuc.is_three_prime) highlightBackbone(entry.nuc, C.highlight_red,     3.0)
    }
  }

  function modeV24() {
    clearOverlay()
    resetAllToDefault(true)
    for (const entry of backboneEntries) {
      if (entry.nuc.is_scaffold) _setInstColor(entry, entry.defaultColor)
    }
    for (const entry of slabEntries) {
      if (entry.nuc.is_scaffold) _setInstColor(entry, entry.defaultColor)
    }
    for (const entry of backboneEntries) {
      if (entry.nuc.is_scaffold && (entry.nuc.is_five_prime || entry.nuc.is_three_prime)) {
        highlightBackbone(entry.nuc, C.highlight_magenta, 3.5)
      }
    }
  }

  // ── Physics position update (moves the actual instanced meshes) ───────────

  // Fast lookup: nuc object → backboneEntry, and key string → backboneEntry.
  const _nucToEntry = new Map()
  const _keyToEntry = new Map()
  for (const entry of backboneEntries) {
    _nucToEntry.set(entry.nuc, entry)
    const n = entry.nuc
    _keyToEntry.set(`${n.helix_id}:${n.bp_index}:${n.direction}`, entry)
  }

  /**
   * Move backbone beads, cones, and slabs to the XPBD-relaxed positions.
   * Called every physics frame (~10 fps).
   *
   * @param {Array<{helix_id, bp_index, direction, backbone_position}>} updates
   */
  function applyPhysicsPositions(updates) {
    // 1. Update backbone entry positions.
    for (const upd of updates) {
      const entry = _keyToEntry.get(`${upd.helix_id}:${upd.bp_index}:${upd.direction}`)
      if (!entry) continue
      const bp = upd.backbone_position
      entry.pos.set(bp[0], bp[1], bp[2])
      _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(1, 1, 1))
      entry.instMesh.setMatrixAt(entry.id, _tMatrix)
    }
    iSpheres.instanceMatrix.needsUpdate = true
    iCubes.instanceMatrix.needsUpdate   = true

    // 2. Recompute cone midpoints and orientations from updated endpoints.
    for (const cone of coneEntries) {
      const fe = _nucToEntry.get(cone.fromNuc)
      const te = _nucToEntry.get(cone.toNuc)
      if (!fe || !te) continue
      _physDir.copy(te.pos).sub(fe.pos)
      const dist = _physDir.length()
      const h    = Math.max(0.001, dist)
      _physDir.divideScalar(dist || 1)
      cone.midPos.copy(fe.pos).addScaledVector(_physDir, dist * 0.5)
      cone.quat.setFromUnitVectors(Y_HAT, _physDir)
      cone.coneHeight = h
      _tMatrix.compose(cone.midPos, cone.quat, _tScale.set(cone.coneRadius, h, cone.coneRadius))
      iCones.setMatrixAt(cone.id, _tMatrix)
    }
    iCones.instanceMatrix.needsUpdate = true

    // 3. Recompute slab centers (orientation unchanged — bnDir is geometric).
    for (const slab of slabEntries) {
      const entry = _nucToEntry.get(slab.nuc)
      if (!entry) continue
      slab.bbPos.copy(entry.pos)
      const center = slabCenter(slab.bbPos, slab.bnDir, slabParams.distance)
      _tMatrix.compose(center, slab.quat, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
      iSlabs.setMatrixAt(slab.id, _tMatrix)
    }
    iSlabs.instanceMatrix.needsUpdate = true
  }

  /**
   * Revert all instanced meshes to their original B-DNA geometric positions.
   * Called when physics mode is toggled off, or after unfold animation returns to t=0.
   */
  function revertToGeometry() {
    for (const entry of backboneEntries) {
      const bp = entry.nuc.backbone_position
      entry.pos.set(bp[0], bp[1], bp[2])
      _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(1, 1, 1))
      entry.instMesh.setMatrixAt(entry.id, _tMatrix)
    }
    iSpheres.instanceMatrix.needsUpdate = true
    iCubes.instanceMatrix.needsUpdate   = true

    for (const cone of coneEntries) {
      const bp1 = cone.fromNuc.backbone_position
      const bp2 = cone.toNuc.backbone_position
      _physDir.set(bp2[0] - bp1[0], bp2[1] - bp1[1], bp2[2] - bp1[2])
      const dist = _physDir.length()
      const h    = Math.max(0.001, dist)
      _physDir.divideScalar(dist || 1)
      cone.midPos.set(
        (bp1[0] + bp2[0]) * 0.5,
        (bp1[1] + bp2[1]) * 0.5,
        (bp1[2] + bp2[2]) * 0.5,
      )
      cone.quat.setFromUnitVectors(Y_HAT, _physDir)
      cone.coneHeight = h
      _tMatrix.compose(cone.midPos, cone.quat, _tScale.set(cone.coneRadius, h, cone.coneRadius))
      iCones.setMatrixAt(cone.id, _tMatrix)
    }
    iCones.instanceMatrix.needsUpdate = true

    for (const slab of slabEntries) {
      const bp = slab.nuc.backbone_position
      slab.bbPos.set(bp[0], bp[1], bp[2])
      const center = slabCenter(slab.bbPos, slab.bnDir, slabParams.distance)
      _tMatrix.compose(center, slab.quat, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
      iSlabs.setMatrixAt(slab.id, _tMatrix)
    }
    iSlabs.instanceMatrix.needsUpdate = true

    // Reset axis arrows to geometric positions.
    for (const arrow of axisArrows) {
      if (arrow.isCurved) {
        arrow.shaft.position.set(0, 0, 0)
      } else {
        arrow.arrowGroup.position.copy(arrow.aStart)
      }
      arrow.head.position.copy(arrow.aEnd)
      arrow.origin.position.copy(arrow.aStart)
    }
  }

  /**
   * Translate all geometry to the 2D unfolded layout at lerp factor t (0=3D, 1=unfolded).
   * Called every animation frame during the unfold/refold transition.
   *
   * @param {Map<string, THREE.Vector3>} helixOffsets  helix_id → translation vector
   * @param {number} t  lerp factor in [0, 1]
   * @returns {Array<{from: THREE.Vector3, to: THREE.Vector3}>}  cross-helix connections
   *          (unfolded positions at the current t, for drawing arc overlays)
   */
  function applyUnfoldOffsets(helixOffsets, t) {
    // 1. Backbone beads.
    for (const entry of backboneEntries) {
      const off  = helixOffsets.get(entry.nuc.helix_id)
      const orig = entry.nuc.backbone_position
      entry.pos.set(
        orig[0] + (off ? off.x * t : 0),
        orig[1] + (off ? off.y * t : 0),
        orig[2] + (off ? off.z * t : 0),
      )
      _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(1, 1, 1))
      entry.instMesh.setMatrixAt(entry.id, _tMatrix)
    }
    iSpheres.instanceMatrix.needsUpdate = true
    iCubes.instanceMatrix.needsUpdate   = true

    // 2. Cones — hide cross-helix cones (they become arcs in unfold view).
    const crossHelixConns = []
    for (const cone of coneEntries) {
      const fe = _nucToEntry.get(cone.fromNuc)
      const te = _nucToEntry.get(cone.toNuc)
      if (!fe || !te) continue

      const isCrossHelix = cone.fromNuc.helix_id !== cone.toNuc.helix_id

      _physDir.copy(te.pos).sub(fe.pos)
      const dist = _physDir.length()
      const h    = Math.max(0.001, dist)
      _physDir.divideScalar(dist || 1)
      cone.midPos.copy(fe.pos).addScaledVector(_physDir, dist * 0.5)
      cone.quat.setFromUnitVectors(Y_HAT, _physDir)
      cone.coneHeight = h

      const r = isCrossHelix ? 0 : cone.coneRadius   // hide cross-helix cones
      _tMatrix.compose(cone.midPos, cone.quat, _tScale.set(r, h, r))
      iCones.setMatrixAt(cone.id, _tMatrix)

      if (isCrossHelix) crossHelixConns.push({ from: fe.pos.clone(), to: te.pos.clone(), color: cone.defaultColor })
    }
    iCones.instanceMatrix.needsUpdate = true

    // 3. Slabs.
    for (const slab of slabEntries) {
      const entry = _nucToEntry.get(slab.nuc)
      if (!entry) continue
      slab.bbPos.copy(entry.pos)
      const center = slabCenter(slab.bbPos, slab.bnDir, slabParams.distance)
      _tMatrix.compose(center, slab.quat, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
      iSlabs.setMatrixAt(slab.id, _tMatrix)
    }
    iSlabs.instanceMatrix.needsUpdate = true

    // 4. Axis arrows.
    for (const arrow of axisArrows) {
      const off = helixOffsets.get(arrow.helixId)
      const ox  = off ? off.x * t : 0
      const oy  = off ? off.y * t : 0
      const oz  = off ? off.z * t : 0

      if (arrow.isCurved) {
        arrow.shaft.position.set(ox, oy, oz)
      } else {
        arrow.arrowGroup.position.set(
          arrow.aStart.x + ox,
          arrow.aStart.y + oy,
          arrow.aStart.z + oz,
        )
      }
      arrow.head.position.set(arrow.aEnd.x + ox, arrow.aEnd.y + oy, arrow.aEnd.z + oz)
      arrow.origin.position.set(arrow.aStart.x + ox, arrow.aStart.y + oy, arrow.aStart.z + oz)
    }

    return crossHelixConns
  }

  // ── Public interface ───────────────────────────────────────────────────────

  return {
    root,
    backboneEntries,
    coneEntries,
    slabEntries,

    // Instance update helpers — used by selection_manager.js and design_renderer.js
    setEntryColor:  _setInstColor,
    setBeadScale:   _setBeadScale,
    setConeXZScale: _setConeXZScale,

    setStrandColor(strandId, hexColor) {
      for (const entry of backboneEntries) {
        if (entry.nuc.strand_id === strandId) {
          _setInstColor(entry, hexColor)
          entry.defaultColor = hexColor
        }
      }
      for (const entry of slabEntries) {
        if (entry.nuc.strand_id === strandId) {
          _setInstColor(entry, hexColor)
          entry.defaultColor = hexColor
        }
      }
      for (const entry of coneEntries) {
        if (entry.strandId === strandId) {
          _setInstColor(entry, hexColor)
          entry.defaultColor = hexColor
        }
      }
    },

    setMode(mode) {
      switch (mode) {
        case 'normal': modeNormal(); break
        case 'V1.1':  modeV11();    break
        case 'V1.2':  modeV12();    break
        case 'V1.3':  modeV13();    break
        case 'V1.4':  modeV14();    break
        case 'V2.1':  modeV21();    break
        case 'V2.2':  modeV22();    break
        case 'V2.3':  modeV23();    break
        case 'V2.4':  modeV24();    break
      }
    },

    /**
     * Thicken/brighten axis arrows for the bend/twist deformation tool.
     * active=true  → fat cyan shafts (easy to click near)
     * active=false → restore thin grey shafts
     */
    setDeformMode(active) {
      const scaleXZ = active ? (0.18 / AXIS_SHAFT_R) : 1.0   // 0.18/0.05 = 3.6×
      const color   = active ? 0x88ccff : C.axis
      for (const { shaft, head, origin, isCurved } of axisArrows) {
        // Only scale the cylinder shaft for straight axes; curved LINE has no scale
        if (shaft && !isCurved) shaft.scale.set(scaleXZ, 1, scaleXZ)
        for (const m of [shaft?.material, head.material, origin.material]) {
          if (!m) continue
          m.color.setHex(color)
          m.opacity     = 1.0
          m.transparent = false
        }
      }
    },

    getDistLabelInfo() { return distLabelInfo },

    applyPhysicsPositions,
    revertToGeometry,
    applyUnfoldOffsets,
  }
}
