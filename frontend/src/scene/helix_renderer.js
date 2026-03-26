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
  overhang:          0xf5a623,   // amber — single-stranded overhang domains
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
    if (nuc.strand_id && nuc.strand_type !== 'scaffold' && !map.has(nuc.strand_id)) {
      map.set(nuc.strand_id, STAPLE_PALETTE[idx % STAPLE_PALETTE.length])
      idx++
    }
  }
  return map
}

function nucColor(nuc, stapleColorMap, customColors, loopSet) {
  if (!nuc.strand_id)  return C.unassigned
  if (nuc.strand_type === 'scaffold') return C.scaffold_backbone
  if (loopSet.has(nuc.strand_id)) return C.highlight_red
  if (customColors[nuc.strand_id] != null) return customColors[nuc.strand_id]
  return stapleColorMap.get(nuc.strand_id) ?? C.unassigned
}
function nucSlabColor(nuc, stapleColorMap, customColors, loopSet) {
  if (!nuc.strand_id)  return C.unassigned
  if (nuc.strand_type === 'scaffold') return C.scaffold_slab
  if (loopSet.has(nuc.strand_id)) return C.highlight_red
  if (customColors[nuc.strand_id] != null) return customColors[nuc.strand_id]
  return stapleColorMap.get(nuc.strand_id) ?? C.unassigned
}
function nucArrowColor(nuc, stapleColorMap, customColors, loopSet) {
  if (!nuc.strand_id)  return C.unassigned
  if (nuc.strand_type === 'scaffold') return C.scaffold_arrow
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

// ── Deform-lerp slab scratch (reused per-frame, never held across awaits) ─────
const _slabAxisDir = new THREE.Vector3()
const _slabProj    = new THREE.Vector3()
const _slabBnS     = new THREE.Vector3()   // straight base-normal
const _slabTanS    = new THREE.Vector3()   // straight tangential (for basis)
const _slabCenterS = new THREE.Vector3()   // straight slab center
const _slabCenterD = new THREE.Vector3()   // deformed slab center
const _slabCenterL = new THREE.Vector3()   // lerped slab center
const _slabQuatS      = new THREE.Quaternion()
const _slabQuatL      = new THREE.Quaternion()
const _slabBasis      = new THREE.Matrix4()
const _straightHeadQ  = new THREE.Quaternion()  // scratch for arrowhead lerp

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
    if (nuc.strand_id) {
      if (!byStrand.has(nuc.strand_id)) byStrand.set(nuc.strand_id, [])
      byStrand.get(nuc.strand_id).push(nuc)
    }

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

  const axisArrows = []   // each: { shafts, head, origin, isCurved }

  // Returns merged scaffold bp coverage intervals for a helix, sorted ascending.
  // Falls back to [[bpStart, bpStart+lengthBp-1]] if no scaffold strands found.
  function _scaffoldIntervals(helixId, bpStart, lengthBp) {
    const ivs = []
    for (const strand of design.strands) {
      if (strand.strand_type !== 'scaffold') continue
      for (const dom of strand.domains) {
        if (dom.helix_id !== helixId) continue
        const lo = Math.min(dom.start_bp, dom.end_bp)
        const hi = Math.max(dom.start_bp, dom.end_bp)
        ivs.push([lo, hi])
      }
    }
    if (!ivs.length) return [[bpStart, bpStart + lengthBp - 1]]
    ivs.sort((a, b) => a[0] - b[0])
    const merged = []
    for (const [lo, hi] of ivs) {
      if (merged.length && lo <= merged[merged.length - 1][1] + 1)
        merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], hi)
      else
        merged.push([lo, hi])
    }
    return merged
  }

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

    let shaft        // THREE.Mesh for the primary shaft (curved tube or straight cylinder)
    let shafts       // all shaft meshes: [shaft] for curved, multi for straight with gaps
    let straightShaft = null  // straight-axis placeholder used when lerping t → 0
    let arrowGroup = null     // only set for straight helices

    if (isCurved) {
      // Smooth tube along the deformed helical axis (CatmullRom through sample points)
      const pts   = samples.map(s => new THREE.Vector3(...s))
      const curve = new THREE.CatmullRomCurve3(pts)
      const segs  = Math.max(samples.length * 4, 16)
      const geo   = new THREE.TubeGeometry(curve, segs, AXIS_SHAFT_R, 6, false)
      shaft = new THREE.Mesh(geo, new THREE.MeshPhongMaterial({ color: C.axis }))
      shafts = [shaft]
      root.add(shaft)

      // Straight-axis placeholder — visible only when deform lerp is active (t < 1).
      // A unit-height cylinder; scale.y and position are set in applyDeformLerp.
      straightShaft = new THREE.Mesh(
        new THREE.CylinderGeometry(AXIS_SHAFT_R, AXIS_SHAFT_R, 1, 8),
        new THREE.MeshPhongMaterial({ color: C.axis, transparent: true, opacity: 0 }),
      )
      root.add(straightShaft)
    } else {
      // Straight: one cylinder per scaffold coverage interval, all in one group
      const aVec = aEnd.clone().sub(aStart)
      const aLen = aVec.length()
      const aDir = aVec.clone().normalize()

      arrowGroup = new THREE.Group()
      arrowGroup.position.copy(aStart)
      arrowGroup.quaternion.setFromUnitVectors(_AY, aDir)
      root.add(arrowGroup)

      const intervals = _scaffoldIntervals(helix.id, helix.bp_start, helix.length_bp)
      const lastBp    = helix.bp_start + helix.length_bp - 1
      const shafts_   = []
      for (const [lo, hi] of intervals) {
        const t0     = (lo - helix.bp_start) / helix.length_bp
        const t1     = (hi - helix.bp_start + 1) / helix.length_bp
        const isLast = hi >= lastBp
        const yStart = t0 * aLen
        const yEnd   = t1 * aLen - (isLast ? AXIS_HEAD_LEN : 0)
        const segLen = Math.max(0.01, yEnd - yStart)
        const seg    = new THREE.Mesh(
          new THREE.CylinderGeometry(AXIS_SHAFT_R, AXIS_SHAFT_R, segLen, 8),
          new THREE.MeshPhongMaterial({ color: C.axis }),
        )
        seg.position.set(0, yStart + segLen / 2, 0)
        arrowGroup.add(seg)
        shafts_.push(seg)
      }
      shafts = shafts_
      shaft  = shafts[0] ?? null   // backward-compat reference for isCurved branches
    }

    const originMat = new THREE.MeshPhongMaterial({ color: C.axis })
    const origin = new THREE.Mesh(new THREE.SphereGeometry(0.07, 8, 6), originMat)
    origin.position.copy(aStart)
    root.add(origin)

    axisArrows.push({
      shaft, shafts, head, origin, isCurved,
      helixId: helix.id,
      arrowGroup,
      straightShaft,                   // null for straight helices
      headQuat: head.quaternion.clone(), // deformed orientation (t=1 anchor)
      aStart: aStart.clone(),
      aEnd:   aEnd.clone(),
    })
  }

  // ── Staple colour map ──────────────────────────────────────────────────────

  const stapleColorMap = buildStapleColorMap(geometry)

  // ── Backbone beads (InstancedMesh) ────────────────────────────────────────

  const assignedGeometry = geometry.filter(n => n.strand_id)
  const sphereNucs  = assignedGeometry.filter(n => !n.is_five_prime)
  const cubeNucs    = assignedGeometry.filter(n =>  n.is_five_prime)

  const iSpheres = new THREE.InstancedMesh(
    GEO_SPHERE, new THREE.MeshPhongMaterial({ color: 0xffffff }), Math.max(1, sphereNucs.length))
  const iCubes   = new THREE.InstancedMesh(
    GEO_CUBE_5P, new THREE.MeshPhongMaterial({ color: 0xffffff }), Math.max(1, cubeNucs.length))
  iSpheres.frustumCulled = false
  iCubes.frustumCulled   = false
  iSpheres.name = 'backboneSpheres'
  iCubes.name   = 'backboneCubes'
  root.add(iSpheres)
  root.add(iCubes)

  const backboneEntries = []
  let sphereId = 0, cubeId = 0

  for (const nuc of assignedGeometry) {
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
  iCones.frustumCulled = false
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

      // Cross-helix connections are rendered as arcs; hide the cone.
      const isCrossHelix = nucs[i].helix_id !== nucs[i + 1].helix_id
      const r = isCrossHelix ? 0 : CONE_RADIUS
      _tMatrix.compose(midPos, quat, _tScale.set(r, coneHeight, r))
      iCones.setMatrixAt(coneId, _tMatrix)
      iCones.setColorAt(coneId, _tColor.setHex(color))

      coneEntries.push({
        instMesh: iCones, id: coneId,
        fromNuc: nucs[i], toNuc: nucs[i + 1],
        strandId: nucs[i].strand_id,
        midPos, quat, coneHeight,
        coneRadius: isCrossHelix ? 0 : CONE_RADIUS,
        isCrossHelix,
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
    Math.max(1, assignedGeometry.length),
  )
  iSlabs.frustumCulled = false
  iSlabs.name = 'baseSlabs'
  root.add(iSlabs)

  const slabEntries = []
  let slabId = 0

  for (const nuc of assignedGeometry) {
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
      // Cross-helix cones stay hidden (rendered as arc lines instead).
      if (!entry.isCrossHelix) _setConeXZScale(entry, CONE_RADIUS)
    }
    for (const entry of slabEntries) {
      _setInstColor(entry, dimmed ? dimHex : entry.defaultColor)
    }
    const axisOpacity = dimmed ? 0.15 : 1.0
    for (const { shafts, head, origin } of axisArrows) {
      for (const m of [...(shafts ?? []).map(s => s.material), head.material, origin.material]) {
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
    for (const { shafts, head, origin } of axisArrows) {
      for (const m of [...(shafts ?? []).map(s => s.material), head.material, origin.material]) {
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
      if (entry.nuc.strand_type === 'scaffold') _setInstColor(entry, entry.defaultColor)
    }
    for (const entry of slabEntries) {
      if (entry.nuc.strand_type === 'scaffold') _setInstColor(entry, entry.defaultColor)
    }
    for (const entry of backboneEntries) {
      if (entry.nuc.strand_type === 'scaffold' && (entry.nuc.is_five_prime || entry.nuc.is_three_prime)) {
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
  /**
   * Restore all geometry to its canonical 3D positions.
   *
   * When straightPosMap / straightAxesMap are supplied (deform view is OFF),
   * straight positions are used as the base so the scene stays in the
   * non-deformed state.  Without those maps the raw (possibly deformed)
   * backbone_position values are used instead.
   *
   * @param {Map<string,THREE.Vector3>|null} straightPosMap
   * @param {Map<string,{start,end}>|null}  straightAxesMap
   */
  function revertToGeometry(straightPosMap = null, straightAxesMap = null) {
    const useStraight = !!(straightPosMap && straightAxesMap)

    // 1. Backbone beads.
    for (const entry of backboneEntries) {
      const nuc = entry.nuc
      let bx, by, bz
      if (useStraight) {
        const sp = straightPosMap.get(`${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`)
        bx = sp ? sp.x : nuc.backbone_position[0]
        by = sp ? sp.y : nuc.backbone_position[1]
        bz = sp ? sp.z : nuc.backbone_position[2]
      } else {
        const bp = nuc.backbone_position
        bx = bp[0]; by = bp[1]; bz = bp[2]
      }
      entry.pos.set(bx, by, bz)
      _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(1, 1, 1))
      entry.instMesh.setMatrixAt(entry.id, _tMatrix)
    }
    iSpheres.instanceMatrix.needsUpdate = true
    iCubes.instanceMatrix.needsUpdate   = true

    // 2. Cones — derived from bead positions so no separate map lookup needed.
    for (const cone of coneEntries) {
      const fe = _nucToEntry.get(cone.fromNuc)
      const te = _nucToEntry.get(cone.toNuc)
      let h
      if (fe && te) {
        _physDir.copy(te.pos).sub(fe.pos)
        const dist = _physDir.length()
        h = Math.max(0.001, dist)
        _physDir.divideScalar(dist || 1)
        cone.midPos.copy(fe.pos).addScaledVector(_physDir, dist * 0.5)
        cone.quat.setFromUnitVectors(Y_HAT, _physDir)
        cone.coneHeight = h
      } else {
        // Fallback to raw positions if entry lookup fails.
        const bp1 = cone.fromNuc.backbone_position
        const bp2 = cone.toNuc.backbone_position
        _physDir.set(bp2[0] - bp1[0], bp2[1] - bp1[1], bp2[2] - bp1[2])
        const dist = _physDir.length()
        h = Math.max(0.001, dist)
        _physDir.divideScalar(dist || 1)
        cone.midPos.set(
          (bp1[0] + bp2[0]) * 0.5,
          (bp1[1] + bp2[1]) * 0.5,
          (bp1[2] + bp2[2]) * 0.5,
        )
        cone.quat.setFromUnitVectors(Y_HAT, _physDir)
        cone.coneHeight = h
      }
      // Keep cross-helix cones hidden; they are rendered as arc lines.
      const r = cone.isCrossHelix ? 0 : cone.coneRadius
      _tMatrix.compose(cone.midPos, cone.quat, _tScale.set(r, h, r))
      iCones.setMatrixAt(cone.id, _tMatrix)
    }
    iCones.instanceMatrix.needsUpdate = true

    // 3. Slabs.
    for (const slab of slabEntries) {
      const nuc = slab.nuc
      let center_, quat_
      if (useStraight) {
        const key = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
        const sp  = straightPosMap.get(key)
        const sa  = straightAxesMap.get(nuc.helix_id)
        if (sp && sa) {
          _slabAxisDir.copy(sa.end).sub(sa.start).normalize()
          const axisProj = (sp.x - sa.start.x) * _slabAxisDir.x
                         + (sp.y - sa.start.y) * _slabAxisDir.y
                         + (sp.z - sa.start.z) * _slabAxisDir.z
          _slabProj.copy(sa.start).addScaledVector(_slabAxisDir, axisProj)
          _slabBnS.copy(_slabProj).sub(sp).normalize()
          _slabTanS.crossVectors(_slabAxisDir, _slabBnS).normalize()
          _slabBasis.makeBasis(_slabTanS, _slabAxisDir, _slabBnS)
          _slabQuatS.setFromRotationMatrix(_slabBasis)
          slab.bbPos.copy(sp)
          center_ = slabCenter(slab.bbPos, _slabBnS, slabParams.distance)
          quat_   = _slabQuatS
        } else {
          slab.bbPos.set(nuc.backbone_position[0], nuc.backbone_position[1], nuc.backbone_position[2])
          center_ = slabCenter(slab.bbPos, slab.bnDir, slabParams.distance)
          quat_   = slab.quat
        }
      } else {
        const bp = nuc.backbone_position
        slab.bbPos.set(bp[0], bp[1], bp[2])
        center_ = slabCenter(slab.bbPos, slab.bnDir, slabParams.distance)
        quat_   = slab.quat
      }
      _tMatrix.compose(center_, quat_, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
      iSlabs.setMatrixAt(slab.id, _tMatrix)
    }
    iSlabs.instanceMatrix.needsUpdate = true

    // 4. Axis arrows.
    for (const arrow of axisArrows) {
      const sa = useStraight ? straightAxesMap.get(arrow.helixId) : null
      const baseStart = sa ? sa.start : arrow.aStart
      const baseEnd   = sa ? sa.end   : arrow.aEnd

      if (arrow.isCurved) {
        arrow.shaft.position.set(0, 0, 0)
        // When deform is off (useStraight), show the straight cylinder shaft;
        // when reverting to full deformed view, show the tube shaft.
        if (arrow.shaft?.material) {
          arrow.shaft.material.opacity     = useStraight ? 0 : 1
          arrow.shaft.material.transparent = useStraight
        }
        if (arrow.straightShaft?.material) {
          arrow.straightShaft.material.transparent = true
          arrow.straightShaft.material.opacity = useStraight ? 1 : 0
          if (sa) {
            arrow.straightShaft.position.set(
              (sa.start.x + sa.end.x) * 0.5,
              (sa.start.y + sa.end.y) * 0.5,
              (sa.start.z + sa.end.z) * 0.5,
            )
          }
        }
        // Restore straight arrowhead orientation when deform is off.
        if (useStraight && sa) {
          _physDir.copy(sa.end).sub(sa.start).normalize()
          _straightHeadQ.setFromUnitVectors(Y_HAT, _physDir)
          arrow.head.quaternion.copy(_straightHeadQ)
        } else {
          arrow.head.quaternion.copy(arrow.headQuat)
        }
      } else {
        arrow.arrowGroup.position.copy(baseStart)
      }
      arrow.head.position.copy(baseEnd)
      arrow.origin.position.copy(baseStart)
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
  function applyUnfoldOffsets(helixOffsets, t, straightPosMap, straightAxesMap) {
    // 1. Backbone beads.
    for (const entry of backboneEntries) {
      // Extra-base beads (synthetic __xb_ helix) are handled by applyUnfoldOffsetsExtraBases.
      if (entry.nuc.helix_id.startsWith('__xb_')) continue
      const off = helixOffsets.get(entry.nuc.helix_id)
      const nuc = entry.nuc
      let bx, by, bz
      if (straightPosMap) {
        const sp = straightPosMap.get(`${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`)
        bx = sp ? sp.x : nuc.backbone_position[0]
        by = sp ? sp.y : nuc.backbone_position[1]
        bz = sp ? sp.z : nuc.backbone_position[2]
      } else {
        bx = nuc.backbone_position[0]
        by = nuc.backbone_position[1]
        bz = nuc.backbone_position[2]
      }
      entry.pos.set(
        bx + (off ? off.x * t : 0),
        by + (off ? off.y * t : 0),
        bz + (off ? off.z * t : 0),
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

      if (isCrossHelix) crossHelixConns.push({
        from: fe.pos.clone(), to: te.pos.clone(), color: cone.defaultColor,
        fromHelixId: cone.fromNuc.helix_id, toHelixId: cone.toNuc.helix_id,
      })
    }
    iCones.instanceMatrix.needsUpdate = true

    // 3. Slabs — use straight bnDir/quaternion when straight maps are available.
    for (const slab of slabEntries) {
      // Extra-base slabs handled by applyUnfoldOffsetsExtraBases.
      if (slab.nuc.helix_id.startsWith('__xb_')) continue
      const entry = _nucToEntry.get(slab.nuc)
      if (!entry) continue

      const nuc = slab.nuc
      const key = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
      const sp  = straightPosMap?.get(key)
      const sa  = straightAxesMap?.get(nuc.helix_id)

      let center_, quat_
      if (sp && sa) {
        // Compute straight base-normal via axis projection (same logic as applyDeformLerp at t=0).
        _slabAxisDir.copy(sa.end).sub(sa.start).normalize()
        const axisProj = (sp.x - sa.start.x) * _slabAxisDir.x
                       + (sp.y - sa.start.y) * _slabAxisDir.y
                       + (sp.z - sa.start.z) * _slabAxisDir.z
        _slabProj.copy(sa.start).addScaledVector(_slabAxisDir, axisProj)
        _slabBnS.copy(_slabProj).sub(sp).normalize()
        _slabTanS.crossVectors(_slabAxisDir, _slabBnS).normalize()
        _slabBasis.makeBasis(_slabTanS, _slabAxisDir, _slabBnS)
        _slabQuatS.setFromRotationMatrix(_slabBasis)

        // Straight center + unfold offset (entry.pos already incorporates the offset).
        _slabCenterS.copy(sp).addScaledVector(_slabBnS, HELIX_RADIUS - slabParams.distance)
        _slabCenterS.x += entry.pos.x - sp.x
        _slabCenterS.y += entry.pos.y - sp.y
        _slabCenterS.z += entry.pos.z - sp.z

        center_ = _slabCenterS
        quat_   = _slabQuatS
      } else {
        slab.bbPos.copy(entry.pos)
        center_ = slabCenter(slab.bbPos, slab.bnDir, slabParams.distance)
        quat_   = slab.quat
      }

      slab.bbPos.copy(entry.pos)
      _tMatrix.compose(center_, quat_, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
      iSlabs.setMatrixAt(slab.id, _tMatrix)
    }
    iSlabs.instanceMatrix.needsUpdate = true

    // 4. Axis arrows.
    for (const arrow of axisArrows) {
      const off = helixOffsets.get(arrow.helixId)
      const ox  = off ? off.x * t : 0
      const oy  = off ? off.y * t : 0
      const oz  = off ? off.z * t : 0

      // Use straight axis endpoints as base when available (unfold must show straight geometry).
      const sa         = straightAxesMap?.get(arrow.helixId)
      const baseStart  = sa ? sa.start : arrow.aStart
      const baseEnd    = sa ? sa.end   : arrow.aEnd

      if (arrow.isCurved) {
        // Curved tube (shaft) is invisible at t=0 (deform off) — translate cosmetically.
        arrow.shaft.position.set(ox, oy, oz)
        // straightShaft is the visible element: reposition it at the straight midpoint + offset.
        if (arrow.straightShaft && sa) {
          arrow.straightShaft.position.set(
            (sa.start.x + sa.end.x) * 0.5 + ox,
            (sa.start.y + sa.end.y) * 0.5 + oy,
            (sa.start.z + sa.end.z) * 0.5 + oz,
          )
        }
      } else {
        arrow.arrowGroup.position.set(
          baseStart.x + ox, baseStart.y + oy, baseStart.z + oz,
        )
      }
      arrow.head.position.set(baseEnd.x + ox, baseEnd.y + oy, baseEnd.z + oz)
      arrow.origin.position.set(baseStart.x + ox, baseStart.y + oy, baseStart.z + oz)
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

    /**
     * Show or hide all staple (non-scaffold) geometry.
     * Uses scale=0 to hide instances without rebuilding.
     */
    setStapleVisibility(visible) {
      for (const entry of backboneEntries) {
        if (entry.nuc.strand_type === 'scaffold') continue
        _setBeadScale(entry, visible ? 1.0 : 0)
      }
      for (const entry of coneEntries) {
        if (entry.strandId === null) continue
        const isScaffold = backboneEntries.find(e => e.nuc.strand_id === entry.strandId)?.nuc?.strand_type === 'scaffold'
        if (isScaffold) continue
        const r = (!visible || entry.isCrossHelix) ? 0 : entry.coneRadius
        _setConeXZScale(entry, r)
      }
      for (const entry of slabEntries) {
        if (entry.nuc.strand_type === 'scaffold') continue
        const s = slabParams
        const center = slabCenter(entry.bbPos, entry.bnDir, s.distance)
        if (visible) {
          _tMatrix.compose(center, entry.quat, _tScale.set(s.length, s.width, s.thickness))
        } else {
          _tMatrix.compose(center, entry.quat, _tScale.set(0, 0, 0))
        }
        iSlabs.setMatrixAt(entry.id, _tMatrix)
      }
      iSlabs.instanceMatrix.needsUpdate = true
    },

    /**
     * Isolate a single staple strand: dim all other non-scaffold instances.
     * Pass null to un-isolate and restore default colours.
     */
    setIsolatedStrand(strandId) {
      if (strandId === null) {
        // Restore defaults
        for (const entry of backboneEntries) {
          if (entry.nuc.strand_type !== 'scaffold') _setInstColor(entry, entry.defaultColor)
        }
        for (const entry of coneEntries) {
          if (backboneEntries.find(e => e.nuc.strand_id === entry.strandId)?.nuc?.strand_type !== 'scaffold') {
            _setInstColor(entry, entry.defaultColor)
          }
        }
        for (const entry of slabEntries) {
          if (entry.nuc.strand_type !== 'scaffold') _setInstColor(entry, entry.defaultColor)
        }
      } else {
        const DIM = C.dim
        for (const entry of backboneEntries) {
          if (entry.nuc.strand_type === 'scaffold') continue
          _setInstColor(entry, entry.nuc.strand_id === strandId ? entry.defaultColor : DIM)
        }
        for (const entry of coneEntries) {
          const isScaff = backboneEntries.find(e => e.nuc.strand_id === entry.strandId)?.nuc?.strand_type === 'scaffold'
          if (isScaff) continue
          _setInstColor(entry, entry.strandId === strandId ? entry.defaultColor : DIM)
        }
        for (const entry of slabEntries) {
          if (entry.nuc.strand_type === 'scaffold') continue
          _setInstColor(entry, entry.nuc.strand_id === strandId ? entry.defaultColor : DIM)
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
      for (const { shafts, head, origin, isCurved } of axisArrows) {
        // Only scale the cylinder shafts for straight axes; curved TubeGeometry has no scale
        if (!isCurved) for (const s of (shafts ?? [])) s.scale.set(scaleXZ, 1, scaleXZ)
        for (const m of [...(shafts ?? []).map(s => s.material), head.material, origin.material]) {
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

    /**
     * Lerp all geometry from straight positions to deformed positions.
     *
     * @param {Map<string, THREE.Vector3>} straightPosMap
     *   Key: "helix_id:bp_index:direction" → straight backbone position (t=0 anchor).
     * @param {Map<string, {start:THREE.Vector3, end:THREE.Vector3}>} straightAxesMap
     *   Key: helix_id → straight axis start/end (t=0 anchor for arrows).
     * @param {number} t  lerp factor in [0, 1]; 0 = straight, 1 = deformed
     */
    applyDeformLerp(straightPosMap, straightAxesMap, t) {
      // 1. Backbone beads
      for (const entry of backboneEntries) {
        const nuc = entry.nuc
        const key = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
        const sp  = straightPosMap.get(key)
        const dp  = nuc.backbone_position  // deformed [x, y, z]
        if (sp && dp) {
          entry.pos.set(
            sp.x + (dp[0] - sp.x) * t,
            sp.y + (dp[1] - sp.y) * t,
            sp.z + (dp[2] - sp.z) * t,
          )
        } else if (dp) {
          entry.pos.set(dp[0], dp[1], dp[2])
        }
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(1, 1, 1))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
      }
      iSpheres.instanceMatrix.needsUpdate = true
      iCubes.instanceMatrix.needsUpdate   = true

      // 2. Cones — cross-helix cones have coneRadius=0 so they stay hidden as arcs.
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

      // 3. Slabs — lerp both center and orientation between straight (t=0) and deformed (t=1)
      for (const slab of slabEntries) {
        const entry = _nucToEntry.get(slab.nuc)
        if (!entry) continue

        const nuc = slab.nuc
        const key = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
        const sp  = straightPosMap?.get(key)
        const sa  = straightAxesMap?.get(nuc.helix_id)

        let slabCenter_, slabQuat_
        if (sp && sa) {
          // Straight base-normal: project sp onto axis, take inward radial component.
          // base_normal points from backbone TOWARD the helix axis (inward), matching
          // how slab.bnDir is defined in the deformed geometry.
          _slabAxisDir.copy(sa.end).sub(sa.start).normalize()
          const axisProj = (sp.x - sa.start.x) * _slabAxisDir.x
                         + (sp.y - sa.start.y) * _slabAxisDir.y
                         + (sp.z - sa.start.z) * _slabAxisDir.z
          _slabProj.copy(sa.start).addScaledVector(_slabAxisDir, axisProj)
          _slabBnS.copy(_slabProj).sub(sp).normalize()  // inward: axis-projection → backbone

          // Straight quaternion: basis(tangential, axisDir, bnDir_straight)
          _slabTanS.crossVectors(_slabAxisDir, _slabBnS).normalize()
          _slabBasis.makeBasis(_slabTanS, _slabAxisDir, _slabBnS)
          _slabQuatS.setFromRotationMatrix(_slabBasis)

          // Straight center = sp + bnDir_straight * (HELIX_RADIUS - distance)
          _slabCenterS.copy(sp).addScaledVector(_slabBnS, HELIX_RADIUS - slabParams.distance)

          // Deformed center = nuc.backbone_position + bnDir_deformed * (HELIX_RADIUS - distance)
          const dp = nuc.backbone_position
          _slabCenterD.set(dp[0], dp[1], dp[2]).addScaledVector(slab.bnDir, HELIX_RADIUS - slabParams.distance)

          // Lerp center; slerp quaternion.
          _slabCenterL.lerpVectors(_slabCenterS, _slabCenterD, t)
          _slabQuatL.copy(_slabQuatS).slerp(slab.quat, t)

          slabCenter_ = _slabCenterL
          slabQuat_   = _slabQuatL
        } else {
          // No straight data available — stay at deformed orientation.
          slab.bbPos.copy(entry.pos)
          slabCenter_ = slabCenter(slab.bbPos, slab.bnDir, slabParams.distance)
          slabQuat_   = slab.quat
        }

        slab.bbPos.copy(entry.pos)  // keep in sync for non-deform-lerp methods
        _tMatrix.compose(slabCenter_, slabQuat_, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
        iSlabs.setMatrixAt(slab.id, _tMatrix)
      }
      iSlabs.instanceMatrix.needsUpdate = true

      // 4. Axis arrows — lerp from straight to deformed.
      //    Curved shafts (TubeGeometry) cannot be morphed, so fade them in with t.
      for (const arrow of axisArrows) {
        const sa  = straightAxesMap?.get(arrow.helixId)
        const sx0 = sa ? sa.start.x + (arrow.aStart.x - sa.start.x) * t : arrow.aStart.x
        const sy0 = sa ? sa.start.y + (arrow.aStart.y - sa.start.y) * t : arrow.aStart.y
        const sz0 = sa ? sa.start.z + (arrow.aStart.z - sa.start.z) * t : arrow.aStart.z
        const sx1 = sa ? sa.end.x   + (arrow.aEnd.x   - sa.end.x)   * t : arrow.aEnd.x
        const sy1 = sa ? sa.end.y   + (arrow.aEnd.y   - sa.end.y)   * t : arrow.aEnd.y
        const sz1 = sa ? sa.end.z   + (arrow.aEnd.z   - sa.end.z)   * t : arrow.aEnd.z

        if (arrow.isCurved) {
          // Cross-fade curved tube (t=1) ↔ straight cylinder (t=0).
          const mat = arrow.shaft?.material
          if (mat) { mat.transparent = true; mat.opacity = t }

          if (arrow.straightShaft && sa) {
            // Position/orient the straight shaft between the lerped axis endpoints.
            _physDir.set(sx1 - sx0, sy1 - sy0, sz1 - sz0)
            const sLen = _physDir.length()
            if (sLen > 0.001) {
              _physDir.divideScalar(sLen)
              arrow.straightShaft.position.set(
                (sx0 + sx1) * 0.5, (sy0 + sy1) * 0.5, (sz0 + sz1) * 0.5,
              )
              arrow.straightShaft.quaternion.setFromUnitVectors(Y_HAT, _physDir)
              arrow.straightShaft.scale.set(1, sLen, 1)
              arrow.straightShaft.material.transparent = true
              arrow.straightShaft.material.opacity = 1 - t
              // Slerp arrowhead between straight direction (t=0) and deformed (t=1).
              _straightHeadQ.setFromUnitVectors(Y_HAT, _physDir)
              arrow.head.quaternion.copy(_straightHeadQ).slerp(arrow.headQuat, t)
            }
          }

          arrow.head.position.set(sx1, sy1, sz1)
          arrow.origin.position.set(sx0, sy0, sz0)
        } else {
          arrow.arrowGroup.position.set(sx0, sy0, sz0)
          arrow.head.position.set(sx1, sy1, sz1)
          arrow.origin.position.set(sx0, sy0, sz0)
        }
      }
    },

    /**
     * Return cross-helix backbone connections at their current world positions.
     * Used by unfold_view.js to build arc overlays for the 3D view.
     */
    getCrossHelixConnections() {
      // When extra-base (__xb_) nucleotides are inserted between domain_a and
      // domain_b, the strand's consecutive-nuc pairs become:
      //   real_a → xb1 → xb2 → ... → xbN → real_b
      // instead of the original real_a → real_b.
      // The xb beads render as spheres/slabs; the arc must still connect the
      // two real anchor nucleotides.  We precompute the exit nuc for each
      // __xb_ chain so we can substitute it when emitting the arc.

      // xbExitMap: xb_helix_id → real toNuc that follows the chain
      const xbExitMap = new Map()
      for (const cone of coneEntries) {
        if (!cone.isCrossHelix) continue
        if (cone.fromNuc.helix_id.startsWith('__xb_') && !cone.toNuc.helix_id.startsWith('__xb_')) {
          xbExitMap.set(cone.fromNuc.helix_id, cone.toNuc)
        }
      }

      const conns = []
      for (const cone of coneEntries) {
        if (!cone.isCrossHelix) continue
        // Skip purely intra-__xb__ connections and __xb__→real exits
        // (exits are already captured via xbExitMap above).
        if (cone.fromNuc.helix_id.startsWith('__xb_')) continue

        let fn = cone.fromNuc
        let tn = cone.toNuc

        if (tn.helix_id.startsWith('__xb_')) {
          // real → __xb_ entry: find the real destination at the other end of the chain.
          const realTo = xbExitMap.get(tn.helix_id)
          if (!realTo) continue   // chain exit not found — skip
          tn = realTo
        }

        // Use backbone_position (the deformed geometry position) rather than
        // fe.pos (the current rendered position, which may be at straight
        // coordinates if deform view is off at the time this is called).
        // This ensures from3D/to3D in arc entries always represent the deformed
        // state so the deform lerp can interpolate correctly.
        const fp = fn.backbone_position
        const tp = tn.backbone_position
        conns.push({
          from:        new THREE.Vector3(fp[0], fp[1], fp[2]),
          to:          new THREE.Vector3(tp[0], tp[1], tp[2]),
          color:       cone.defaultColor,
          fromHelixId: fn.helix_id,
          toHelixId:   tn.helix_id,
          strandId:    cone.strandId,
          fromNuc:     fn,
          toNuc:       tn,
        })
      }
      return conns
    },

    /** Returns the raw axisArrows array for debug hit-testing. */
    getAxisArrows() { return axisArrows },

    /**
     * Animate extra-base (crossover loop) beads and slabs during the unfold transition.
     *
     * @param {Map<string, {bezierAt: (t:number) => THREE.Vector3}>} xbArcMap
     *   Maps crossover_bases_id → object with bezierAt(t) returning a world position
     *   on the crossover's unfold arc at parameter t ∈ [0,1].
     * @param {number} unfoldT  Animation progress 0 (3D) → 1 (unfold).
     */
    applyUnfoldOffsetsExtraBases(xbArcMap, unfoldT) {
      // Backbone beads.
      for (const entry of backboneEntries) {
        const nuc = entry.nuc
        if (!nuc.helix_id.startsWith('__xb_')) continue
        const arc = xbArcMap?.get(nuc.crossover_bases_id)
        const gx = nuc.backbone_position[0]
        const gy = nuc.backbone_position[1]
        const gz = nuc.backbone_position[2]
        if (arc) {
          const unfoldPos = arc.bezierAt(nuc.crossover_bases_t)
          entry.pos.set(
            gx + (unfoldPos.x - gx) * unfoldT,
            gy + (unfoldPos.y - gy) * unfoldT,
            gz + (unfoldPos.z - gz) * unfoldT,
          )
        } else {
          entry.pos.set(gx, gy, gz)
        }
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(1, 1, 1))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
      }
      iSpheres.instanceMatrix.needsUpdate = true
      iCubes.instanceMatrix.needsUpdate   = true

      // Base slabs.
      for (const slab of slabEntries) {
        const nuc = slab.nuc
        if (!nuc.helix_id.startsWith('__xb_')) continue
        const entry = _nucToEntry.get(nuc)
        if (!entry) continue
        slab.bbPos.copy(entry.pos)
        const center_ = slabCenter(slab.bbPos, slab.bnDir, slabParams.distance)
        _tMatrix.compose(center_, slab.quat, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
        iSlabs.setMatrixAt(slab.id, _tMatrix)
      }
      iSlabs.instanceMatrix.needsUpdate = true
    },
  }
}
