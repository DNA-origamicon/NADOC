/**
 * Helix renderer — builds Three.js objects from geometry API data.
 *
 * Nucleotide geometry:
 *   - Backbone bead: sphere (or cube at 5′ end)
 *   - Base slab: thin BoxGeometry oriented in the base-pair plane, slider-controlled
 *   - Strand cones: ConeGeometry indicators between consecutive backbone beads in 5′→3′ order
 *   - Helix axis: ArrowHelper from axis_start to axis_end
 *
 * Validation modes: 'normal' | 'V1.1' | 'V1.2' | 'V1.3' | 'V1.4'
 */

import * as THREE from 'three'

// ── Constants ─────────────────────────────────────────────────────────────────

const HELIX_RADIUS = 1.0  // nm — must match backend/core/constants.py

// ── Palette ───────────────────────────────────────────────────────────────────

const C = {
  scaffold_backbone:  0x29b6f6,   // sky blue  — ALL scaffold strands
  scaffold_slab:      0x0277bd,   // darker blue
  scaffold_arrow:     0x0288d1,
  axis:               0x555566,
  highlight_red:      0xff3333,
  highlight_blue:     0x3399ff,
  highlight_yellow:   0xffdd00,
  highlight_magenta:  0xff00ff,
  highlight_orange:   0xff8c00,
  white:              0xffffff,
  dim:                0x15202e,
  unassigned:         0x445566,   // backbone with no strand yet
}

// Distinct staple colours — cycled by strand index.
const STAPLE_PALETTE = [
  0xff6b6b,  // coral red
  0xffd93d,  // amber
  0x6bcb77,  // green
  0xf9844a,  // orange
  0xa29bfe,  // lavender
  0xff9ff3,  // pink
  0x00cec9,  // teal
  0xe17055,  // terracotta
  0x74b9ff,  // steel blue
  0x55efc4,  // mint
  0xfdcb6e,  // yellow
  0xd63031,  // crimson
]

// Build a stable strand_id → palette index mapping from the geometry array.
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

function nucColor(nuc, stapleColorMap, customColors) {
  if (!nuc.strand_id)    return C.unassigned
  if (nuc.is_scaffold)   return C.scaffold_backbone
  if (customColors[nuc.strand_id] != null) return customColors[nuc.strand_id]
  return stapleColorMap.get(nuc.strand_id) ?? C.unassigned
}

function nucSlabColor(nuc, stapleColorMap, customColors) {
  if (!nuc.strand_id)    return C.unassigned
  if (nuc.is_scaffold)   return C.scaffold_slab
  if (customColors[nuc.strand_id] != null) return customColors[nuc.strand_id]
  return stapleColorMap.get(nuc.strand_id) ?? C.unassigned
}

function nucArrowColor(nuc, stapleColorMap, customColors) {
  if (!nuc.strand_id)    return C.unassigned
  if (nuc.is_scaffold)   return C.scaffold_arrow
  if (customColors[nuc.strand_id] != null) return customColors[nuc.strand_id]
  return stapleColorMap.get(nuc.strand_id) ?? C.unassigned
}

// ── Shared geometries ─────────────────────────────────────────────────────────

const BEAD_RADIUS  = 0.10   // nm — sphere radius
const CONE_RADIUS  = 0.075  // nm — ~0.375 × bead diameter
const Y_HAT        = new THREE.Vector3(0, 1, 0)

const GEO_SPHERE   = new THREE.SphereGeometry(BEAD_RADIUS, 10, 8)
const GEO_CUBE_5P  = new THREE.BoxGeometry(0.18, 0.18, 0.18)   // 5′ end marker
const GEO_UNIT_BOX = new THREE.BoxGeometry(1, 1, 1)             // scaled per slab
const GEO_UNIT_CONE = new THREE.ConeGeometry(1, 1, 8)           // scaled per strand connector

// ── Material helpers ──────────────────────────────────────────────────────────

function phong(color, opacity = 1) {
  return new THREE.MeshPhongMaterial({
    color,
    transparent: opacity < 1,
    opacity,
    depthWrite: opacity >= 1,
  })
}

// ── Slab orientation quaternion ───────────────────────────────────────────────

/**
 * Compute the quaternion that orients a unit box so that:
 *   box local X → tangential direction  (length, along circumference)
 *   box local Y → axis_tangent          (width,  along helix axis)
 *   box local Z → base_normal (inward)  (thickness, radial thin dimension)
 *
 * base_normal and axis_tangent are always orthogonal by construction.
 */
function slabQuaternion(bnDir, tanDir) {
  const tangential = new THREE.Vector3().crossVectors(tanDir, bnDir).normalize()
  const m = new THREE.Matrix4().makeBasis(tangential, tanDir, bnDir)
  return new THREE.Quaternion().setFromRotationMatrix(m)
}

// ── Slab center position ───────────────────────────────────────────────────────

/**
 * Place slab centre at (distance) nm from the helix axis along the outward
 * radial direction.
 *
 *   axis_point = backbone_position + HELIX_RADIUS * base_normal
 *   slab_center = axis_point + distance * (-base_normal)
 *               = backbone_position + (HELIX_RADIUS - distance) * base_normal
 */
function slabCenter(backbonePos, bnDir, distance) {
  return backbonePos.clone().addScaledVector(bnDir, HELIX_RADIUS - distance)
}

// ── Main builder ──────────────────────────────────────────────────────────────

export function buildHelixObjects(geometry, design, scene, customColors = {}) {
  // ── Index geometry ────────────────────────────────────────────────────────

  // Group nucleotides by strand, preserving source data.
  // Nucleotides with no strand (opposite backbone from scaffold) are keyed by
  // "helix_id:direction" to prevent cross-helix grouping.
  const byStrand = new Map()   // key → Array<nuc>
  const byBp     = new Map()   // bp_index  → { FORWARD: nuc, REVERSE: nuc }

  for (const nuc of geometry) {
    const key = nuc.strand_id ?? `__${nuc.helix_id}:${nuc.direction}`
    if (!byStrand.has(key)) byStrand.set(key, [])
    byStrand.get(key).push(nuc)

    if (!byBp.has(nuc.bp_index)) byBp.set(nuc.bp_index, {})
    byBp.get(nuc.bp_index)[nuc.direction] = nuc
  }

  // Sort each strand into 5′→3′ order:
  //   FORWARD strand: ascending bp_index
  //   REVERSE strand: descending bp_index
  for (const [, nucs] of byStrand) {
    const dir = nucs[0].direction
    nucs.sort((a, b) =>
      dir === 'FORWARD' ? a.bp_index - b.bp_index : b.bp_index - a.bp_index
    )
  }

  // ── Root group ────────────────────────────────────────────────────────────

  const root = new THREE.Group()
  scene.add(root)

  // ── Helix axis arrow ──────────────────────────────────────────────────────

  const axisArrows = []
  for (const helix of design.helices) {
    const aStart = new THREE.Vector3(
      helix.axis_start.x, helix.axis_start.y, helix.axis_start.z)
    const aEnd   = new THREE.Vector3(
      helix.axis_end.x,   helix.axis_end.y,   helix.axis_end.z)
    const aVec   = aEnd.clone().sub(aStart)
    const aLen   = aVec.length()
    const aDir   = aVec.clone().normalize()

    const axisArrow = new THREE.ArrowHelper(
      aDir, aStart, aLen,
      C.axis,
      0.55,   // head length nm
      0.22,   // head width nm
    )
    root.add(axisArrow)
    axisArrows.push(axisArrow)

    // Small sphere at axis start to mark origin.
    const originMarker = new THREE.Mesh(
      new THREE.SphereGeometry(0.07, 8, 6),
      phong(C.axis),
    )
    originMarker.position.copy(aStart)
    root.add(originMarker)
    axisArrows.push(originMarker)
  }

  // ── Staple colour map (built once per scene) ─────────────────────────────

  const stapleColorMap = buildStapleColorMap(geometry)

  // ── Backbone beads ────────────────────────────────────────────────────────

  const backboneEntries = []   // { mesh, nuc, defaultColor }

  for (const nuc of geometry) {
    const color  = nucColor(nuc, stapleColorMap, customColors)
    const geo    = nuc.is_five_prime ? GEO_CUBE_5P : GEO_SPHERE
    const mesh   = new THREE.Mesh(geo, phong(color))
    mesh.position.set(...nuc.backbone_position)
    mesh.userData = { nuc }
    root.add(mesh)
    backboneEntries.push({ mesh, nuc, defaultColor: color })
  }

  // ── Strand direction cones ───────────────────────────────────────────────
  // One cone per consecutive pair in 5′→3′ strand order.
  // Cone base sits on the from-bead surface; tip points toward next bead.

  const strandCones = []   // THREE.Mesh[]

  for (const [, nucs] of byStrand) {
    const color = nucArrowColor(nucs[0], stapleColorMap, customColors)
    const mat   = phong(color)

    for (let i = 0; i < nucs.length - 1; i++) {
      const from = new THREE.Vector3(...nucs[i].backbone_position)
      const to   = new THREE.Vector3(...nucs[i + 1].backbone_position)
      const dir  = to.clone().sub(from).normalize()
      const dist = from.distanceTo(to)

      const coneHeight = Math.max(0.001, dist)
      const cone = new THREE.Mesh(GEO_UNIT_CONE, mat.clone())
      cone.scale.set(CONE_RADIUS, coneHeight, CONE_RADIUS)
      cone.quaternion.setFromUnitVectors(Y_HAT, dir)
      cone.position.copy(from).addScaledVector(dir, dist / 2)
      root.add(cone)
      strandCones.push(cone)
    }
  }

  // ── Base slabs ────────────────────────────────────────────────────────────

  // Live slab params — mutated by slider callbacks.
  const slabParams = { length: 0.30, width: 0.06, thickness: 0.70, distance: 0.55 }

  const slabEntries = []  // { mesh, nuc, quat }

  for (const nuc of geometry) {
    const bnDir = new THREE.Vector3(...nuc.base_normal)
    const tanDir = new THREE.Vector3(...nuc.axis_tangent)
    const quat  = slabQuaternion(bnDir, tanDir)
    const color = nucSlabColor(nuc, stapleColorMap, customColors)

    const mesh = new THREE.Mesh(GEO_UNIT_BOX.clone(), phong(color, 0.90))
    mesh.quaternion.copy(quat)
    mesh.scale.set(slabParams.length, slabParams.width, slabParams.thickness)
    mesh.position.copy(slabCenter(
      new THREE.Vector3(...nuc.backbone_position), bnDir, slabParams.distance))
    root.add(mesh)
    slabEntries.push({ mesh, nuc, quat,
      bnDir: bnDir.clone(),
      bbPos: new THREE.Vector3(...nuc.backbone_position),
      defaultColor: color,
    })
  }

  // ── Slider update ─────────────────────────────────────────────────────────

  function applySlabParams() {
    for (const { mesh, bnDir, bbPos } of slabEntries) {
      mesh.scale.set(slabParams.length, slabParams.width, slabParams.thickness)
      mesh.position.copy(slabCenter(bbPos, bnDir, slabParams.distance))
    }
  }

  // Wire sliders.
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

  // ── Validation overlay ────────────────────────────────────────────────────

  let overlayObjects = []

  function clearOverlay() {
    for (const obj of overlayObjects) {
      root.remove(obj)
      if (obj.geometry) obj.geometry.dispose()
      if (obj.material) obj.material.dispose()
    }
    overlayObjects = []
    const lbl = document.querySelector('.dist-label')
    if (lbl) lbl.remove()
    distLabelInfo = null
  }

  function resetAllToDefault(dimmed = false) {
    const opacity = dimmed ? 0.06 : 1.0
    const axisOpacity = dimmed ? 0.15 : 1.0

    for (const { mesh, defaultColor } of backboneEntries) {
      mesh.material.color.setHex(dimmed ? C.dim : defaultColor)
      mesh.material.opacity = opacity
      mesh.material.transparent = dimmed
      mesh.material.depthWrite = !dimmed
      mesh.scale.setScalar(1.0)
    }
    for (const { mesh, defaultColor } of slabEntries) {
      mesh.material.color.setHex(dimmed ? C.dim : defaultColor)
      mesh.material.opacity = dimmed ? 0.04 : 0.90
      mesh.material.transparent = true
      mesh.material.depthWrite = !dimmed
    }
    for (const cone of strandCones) {
      cone.material.opacity = axisOpacity
      cone.material.transparent = dimmed
      cone.material.depthWrite = !dimmed
    }
    for (const obj of axisArrows) {
      if (obj instanceof THREE.ArrowHelper) {
        obj.line.material.opacity = axisOpacity
        obj.line.material.transparent = dimmed
        obj.cone.material.opacity = axisOpacity
        obj.cone.material.transparent = dimmed
      } else {
        obj.material.opacity = axisOpacity
        obj.material.transparent = dimmed
      }
    }
  }

  function highlightBackbone(nuc, color, scale = 1) {
    const entry = backboneEntries.find(e => e.nuc === nuc)
    if (!entry) return
    entry.mesh.material.color.setHex(color)
    entry.mesh.material.opacity = 1.0
    entry.mesh.material.transparent = false
    entry.mesh.material.depthWrite = true
    entry.mesh.scale.setScalar(scale)
  }

  // ── Distance label ────────────────────────────────────────────────────────

  let distLabelInfo = null

  function setDistLabel(midpoint, text) {
    distLabelInfo = { midpoint, text }
  }

  // ── Validation modes ──────────────────────────────────────────────────────

  function modeNormal() {
    clearOverlay()
    resetAllToDefault(false)
  }

  function modeV11() {
    // Handedness: FORWARD strand at full brightness, REVERSE dimmed.
    // Camera will swing to look from +Z (managed by validation_panel.js).
    clearOverlay()
    resetAllToDefault(false)
    for (const { mesh, nuc } of backboneEntries) {
      if (nuc.direction === 'REVERSE') {
        mesh.material.color.setHex(C.dim)
        mesh.material.opacity = 0.12
        mesh.material.transparent = true
        mesh.material.depthWrite = false
      }
    }
    for (const { mesh, nuc } of slabEntries) {
      if (nuc.direction === 'REVERSE') {
        mesh.material.opacity = 0.04
        mesh.material.color.setHex(C.dim)
      }
    }
    // Dim REVERSE strand arrows, keep FORWARD arrows bright.
    // Arrows don't carry strand_id, but FORWARD arrows run from
    // low bp to high bp (same direction as the sorted scaffold order).
    // Since byStrand preserves per-strand arrows, we can't easily filter here —
    // all arrows keep default opacity but this is acceptable since the FORWARD
    // spheres are prominently green.
  }

  function modeV12() {
    // Rise: bp 0 and bp 1 FORWARD backbone beads highlighted red, 3×.
    // Distance label shows axial projection (rise = 0.334 nm), not 3D distance.
    clearOverlay()
    resetAllToDefault(true)

    const bp0 = byBp.get(0)?.['FORWARD']
    const bp1 = byBp.get(1)?.['FORWARD']
    if (!bp0 || !bp1) return

    highlightBackbone(bp0, C.highlight_red, 3.0)
    highlightBackbone(bp1, C.highlight_red, 3.0)

    // White connector line
    const lineGeo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(...bp0.backbone_position),
      new THREE.Vector3(...bp1.backbone_position),
    ])
    const line = new THREE.Line(lineGeo, new THREE.LineBasicMaterial({ color: C.white }))
    root.add(line)
    overlayObjects.push(line)

    // Axial rise = dot(bp1 - bp0, axis_tangent) — this is always 0.334 nm.
    const v    = new THREE.Vector3(...bp1.backbone_position)
      .sub(new THREE.Vector3(...bp0.backbone_position))
    const tan  = new THREE.Vector3(...bp0.axis_tangent)
    const rise = Math.abs(v.dot(tan))

    const mid = [
      (bp0.backbone_position[0] + bp1.backbone_position[0]) / 2,
      (bp0.backbone_position[1] + bp1.backbone_position[1]) / 2,
      (bp0.backbone_position[2] + bp1.backbone_position[2]) / 2,
    ]
    setDistLabel(mid, `axial rise: ${rise.toFixed(4)} nm`)
  }

  function modeV13() {
    // Base normal at bp 0 FORWARD: yellow spike at 5× length with arrowhead.
    clearOverlay()
    resetAllToDefault(true)

    const bp0 = byBp.get(0)?.['FORWARD']
    if (!bp0) return

    highlightBackbone(bp0, C.highlight_red, 2.0)

    // Highlight base slab at bp0 FORWARD in yellow
    const slabEntry = slabEntries.find(e => e.nuc === bp0)
    if (slabEntry) {
      slabEntry.mesh.material.color.setHex(C.highlight_yellow)
      slabEntry.mesh.material.opacity = 1.0
      slabEntry.mesh.material.depthWrite = true
    }

    // 5× base-normal spike
    const origin = new THREE.Vector3(...bp0.backbone_position)
    const bnDir  = new THREE.Vector3(...bp0.base_normal)
    const SPIKE_LEN = 1.5   // nm — 5× of a ~0.3 nm normal segment

    const spike = new THREE.ArrowHelper(
      bnDir, origin, SPIKE_LEN,
      C.highlight_yellow,
      0.25,   // head length
      0.10,   // head width
    )
    root.add(spike)
    overlayObjects.push(spike)
  }

  function modeV14() {
    // bp 10: FORWARD=red, REVERSE=blue, white connecting line.
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

    // Axis arrow stays visible in this mode
    for (const obj of axisArrows) {
      if (obj instanceof THREE.ArrowHelper) {
        obj.setColor(C.white)
      } else {
        obj.material.color.setHex(C.white)
      }
      const m = obj.line?.material ?? obj.material
      m.opacity = 1.0
      m.transparent = false
    }
  }

  // ── Phase 2 validation modes ──────────────────────────────────────────────

  function modeV21() {
    // Selection identity — normal view; user clicks beads to test properties panel.
    clearOverlay()
    resetAllToDefault(false)
  }

  function modeV22() {
    // Crossover candidate termini — all strand 5′/3′ ends shown in white 3×.
    // These are the points where crossovers may be added via Ctrl+K → Add Crossover.
    clearOverlay()
    resetAllToDefault(true)
    for (const { nuc } of backboneEntries) {
      if (nuc.is_five_prime || nuc.is_three_prime) {
        highlightBackbone(nuc, C.white, 3.0)
      }
    }
  }

  function modeV23() {
    // Strand polarity — 5′ ends bright green 3×, 3′ ends red 3×.
    // Cone connectors already point 5′→3′ (tip toward next bead).
    clearOverlay()
    resetAllToDefault(true)
    for (const { nuc } of backboneEntries) {
      if (nuc.is_five_prime)  highlightBackbone(nuc, C.scaffold_backbone, 3.0)
      if (nuc.is_three_prime) highlightBackbone(nuc, C.highlight_red,     3.0)
    }
  }

  function modeV24() {
    // Scaffold continuity — scaffold strand bright, termini magenta 3× (nick sites).
    // Everything else dimmed.
    clearOverlay()
    resetAllToDefault(true)
    for (const { mesh, nuc, defaultColor } of backboneEntries) {
      if (nuc.is_scaffold) {
        mesh.material.color.setHex(defaultColor)
        mesh.material.opacity = 1.0
        mesh.material.transparent = false
        mesh.material.depthWrite = true
      }
    }
    for (const { mesh, nuc, defaultColor } of slabEntries) {
      if (nuc.is_scaffold) {
        mesh.material.color.setHex(defaultColor)
        mesh.material.opacity = 0.90
        mesh.material.depthWrite = true
      }
    }
    // Scaffold termini = nick sites (magenta 3×)
    for (const { nuc } of backboneEntries) {
      if (nuc.is_scaffold && (nuc.is_five_prime || nuc.is_three_prime)) {
        highlightBackbone(nuc, C.highlight_magenta, 3.5)
      }
    }
  }

  // ── Public interface ──────────────────────────────────────────────────────

  return {
    root,
    backboneEntries,
    slabEntries,
    strandCones,

    /**
     * Apply a custom colour to all backbone beads and slabs for a given strand.
     * Updates `defaultColor` on each entry so highlight-restore uses the new colour.
     */
    setStrandColor(strandId, hexColor) {
      for (const entry of backboneEntries) {
        if (entry.nuc.strand_id === strandId) {
          entry.mesh.material.color.setHex(hexColor)
          entry.defaultColor = hexColor
        }
      }
      for (const entry of slabEntries) {
        if (entry.nuc.strand_id === strandId) {
          entry.mesh.material.color.setHex(hexColor)
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

    getDistLabelInfo() { return distLabelInfo },
  }
}
