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

const HELIX_RADIUS    = 1.0    // nm — must match backend/core/constants.py
const BDNA_RISE_PER_BP = 0.334  // nm/bp — must match backend/core/constants.py

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

// Canonical palette — must match backend/core/constants.py STAPLE_PALETTE
// and frontend/src/cadnano-editor/pathview.js STAPLE_PALETTE exactly.
const STAPLE_PALETTE = [
  0xff6b6b, 0xffd93d, 0x6bcb77, 0xf9844a, 0xa29bfe, 0xff9ff3,
  0x00cec9, 0xe17055, 0x74b9ff, 0x55efc4, 0xfdcb6e, 0xd63031,
]

// Coloring-mode palettes. Base colours mirror sequence_overlay.LETTER_DEFS.
const BASE_COLORS = { A: 0x44dd88, T: 0xff5555, G: 0xffcc00, C: 0x55aaff }

/**
 * Build a per-nucleotide letter lookup ('A'|'T'|'G'|'C') for the given design.
 * Mirrors the assignment logic in sequence_overlay.js so on-bead colours
 * match the letter sprites exactly.  Nucs without an assigned letter are absent.
 *
 * @param {object} design
 * @param {Array}  nucs    nucleotide objects whose .strand_id, .domain_index,
 *                         .bp_index, .direction, .overhang_id are populated.
 * @returns {Map<object,'A'|'T'|'G'|'C'>}
 */
export function buildNucLetterMap(design, nucs) {
  const nucLetter = new Map()
  if (!design) return nucLetter

  const seqMap = new Map()
  for (const s of (design.strands ?? [])) if (s.sequence) seqMap.set(s.id, s.sequence)
  if (seqMap.size) {
    const byStrand = new Map()
    for (const nuc of nucs) {
      if (!nuc.strand_id) continue
      if (!byStrand.has(nuc.strand_id)) byStrand.set(nuc.strand_id, [])
      byStrand.get(nuc.strand_id).push(nuc)
    }
    for (const arr of byStrand.values()) {
      arr.sort((a, b) => {
        const di = (a.domain_index ?? 0) - (b.domain_index ?? 0)
        if (di !== 0) return di
        return a.direction === 'FORWARD' ? a.bp_index - b.bp_index : b.bp_index - a.bp_index
      })
    }
    for (const [sid, arr] of byStrand) {
      const seq = seqMap.get(sid)
      if (!seq) continue
      for (let i = 0; i < arr.length; i++) {
        const ch = seq[i]?.toUpperCase()
        if (ch && 'ATGC'.includes(ch)) nucLetter.set(arr[i], ch)
      }
    }
  }

  const ovhgSeqMap = new Map()
  for (const o of (design.overhangs ?? [])) if (o.sequence) ovhgSeqMap.set(o.id, o.sequence)
  if (ovhgSeqMap.size) {
    const byOvhg = new Map()
    for (const nuc of nucs) {
      if (!nuc.overhang_id) continue
      if (!byOvhg.has(nuc.overhang_id)) byOvhg.set(nuc.overhang_id, [])
      byOvhg.get(nuc.overhang_id).push(nuc)
    }
    for (const [oid, arr] of byOvhg) {
      const seq = ovhgSeqMap.get(oid)
      if (!seq) continue
      arr.sort((a, b) =>
        a.direction === 'FORWARD' ? a.bp_index - b.bp_index : b.bp_index - a.bp_index)
      for (let i = 0; i < arr.length; i++) {
        if (nucLetter.has(arr[i])) continue
        const ch = seq[i]?.toUpperCase()
        if (ch && 'ATGC'.includes(ch)) nucLetter.set(arr[i], ch)
      }
    }
  }
  return nucLetter
}

/**
 * Build a (nuc-or-domain) → cluster-index lookup.  Mirrors the membership rule
 * used by assembly_renderer._clusterMemberFilter: domain-level entries (bridges)
 * win over the helix-level fallback.
 *
 * @param {object} design
 * @returns {(nuc:object) => number|undefined}
 */
function buildClusterLookup(design) {
  const clusters = design?.cluster_transforms ?? []
  if (!clusters.length) return () => undefined

  const helixToCluster  = new Map()   // helix_id → cluster_index
  const domainToCluster = new Map()   // "strand_id:domain_index" → cluster_index
  const strands = design?.strands ?? []

  // Bucket strand domains by helix once so the per-helix coverage check below
  // is cheap when a cluster lists hundreds of domain_ids.
  const domainsByHelix = new Map()
  for (const s of strands) {
    for (let di = 0; di < (s.domains ?? []).length; di++) {
      const d = s.domains[di]
      if (!d?.helix_id) continue
      let arr = domainsByHelix.get(d.helix_id)
      if (!arr) { arr = []; domainsByHelix.set(d.helix_id, arr) }
      arr.push({ key: `${s.id}:${di}`, helix_id: d.helix_id })
    }
  }

  for (let i = 0; i < clusters.length; i++) {
    const c = clusters[i]
    if (c.domain_ids?.length) {
      const keys = new Set()
      for (const dr of c.domain_ids) {
        const k = `${dr.strand_id}:${dr.domain_index}`
        keys.add(k)
        domainToCluster.set(k, i)
      }
      // A helix is "owned" by this cluster when every strand domain on it
      // appears in keys (full coverage). It's a "bridge" only when SOME of
      // its domains are in keys and others aren't (partial coverage). Mirrors
      // the corrected backend `_overhang_owning_cluster_id` rule.
      for (const hid of (c.helix_ids ?? [])) {
        const arr = domainsByHelix.get(hid) ?? []
        let allCovered = true
        for (const d of arr) {
          if (!keys.has(d.key)) { allCovered = false; break }
        }
        if (allCovered) helixToCluster.set(hid, i)
      }
    } else {
      for (const hid of (c.helix_ids ?? [])) helixToCluster.set(hid, i)
    }
  }
  return (nuc) => {
    if (nuc?.strand_id != null && nuc?.domain_index != null) {
      const k = `${nuc.strand_id}:${nuc.domain_index}`
      if (domainToCluster.has(k)) return domainToCluster.get(k)
    }
    return helixToCluster.get(nuc?.helix_id)
  }
}

export function buildStapleColorMap(geometry, design) {
  const strands    = design?.strands   ?? []
  const crossovers = design?.crossovers ?? []

  // Index only staple strands so scaffold topology changes don't shift palette slots.
  const stapleStrands = strands.filter(s => s.strand_type === 'staple')

  // Union-find: strands connected by crossovers share a palette color.
  const parent = Array.from({length: stapleStrands.length}, (_, i) => i)
  function find(i) { return parent[i] === i ? i : (parent[i] = find(parent[i])) }
  function union(a, b) { if (a >= 0 && b >= 0) parent[find(a)] = find(b) }

  for (const xo of crossovers) {
    const sA = stapleStrands.findIndex(s => s.domains.some(d =>
      d.helix_id  === xo.half_a.helix_id && d.direction === xo.half_a.strand &&
      Math.min(d.start_bp, d.end_bp) <= xo.half_a.index &&
      xo.half_a.index <= Math.max(d.start_bp, d.end_bp)))
    const sB = stapleStrands.findIndex(s => s.domains.some(d =>
      d.helix_id  === xo.half_b.helix_id && d.direction === xo.half_b.strand &&
      Math.min(d.start_bp, d.end_bp) <= xo.half_b.index &&
      xo.half_b.index <= Math.max(d.start_bp, d.end_bp)))
    union(sA, sB)
  }

  // Use the component root's array index as the palette index — mirrors the 2D pathview's
  // strandColor(strands[root], root) which uses `root` directly so that the same strand always
  // maps to the same palette entry regardless of geometry traversal order.
  const strandIdxOf = new Map(stapleStrands.map((s, i) => [s.id, i]))
  const map = new Map()   // strand_id → hex color

  for (const nuc of geometry) {
    if (!nuc.strand_id || nuc.strand_type === 'scaffold' || map.has(nuc.strand_id)) continue
    const si         = strandIdxOf.get(nuc.strand_id) ?? -1
    const paletteIdx = si >= 0 ? find(si) : map.size
    map.set(nuc.strand_id, STAPLE_PALETTE[paletteIdx % STAPLE_PALETTE.length])
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
const GEO_UNIT_CYL  = new THREE.CylinderGeometry(1.125, 1.125, 1, 8)  // LOD level-2 domain cylinder (r=2.25nm/2)
const GEO_HALF_CYL  = new THREE.CylinderGeometry(1.125, 1.125, 1, 8, 1, false, 0, Math.PI)  // LOD overhang half-cylinder
const GEO_FLUORO_SPHERE = new THREE.SphereGeometry(0.25, 12, 10)       // fluorophore modification bead

// Modification type → Three.js hex color (display color in the 3D scene)
const MODIFICATION_COLORS = {
  cy3:     0xff8c00,
  cy5:     0xcc0000,
  fam:     0x00cc00,
  tamra:   0xcc00cc,
  bhq1:    0x444444,
  bhq2:    0x666666,
  atto488: 0x00ffcc,
  atto550: 0xffaa00,
  biotin:  0xeeeeee,
}

/**
 * Fluorescence-mode emission colors — approximate actual fluorophore emission
 * wavelengths for use in the Fluorescence View toggle.
 * BHQ-1, BHQ-2 (quenchers) and Biotin (non-fluorescent) are omitted; the
 * absence of an entry signals "no glow for this modification".
 */
export const FLUORO_EMISSION_COLORS = new Map([
  ['cy3',     0xddff00],   // ~570 nm  yellow-green
  ['cy5',     0xff1a1a],   // ~670 nm  deep red
  ['fam',     0x00ff66],   // ~520 nm  bright green
  ['tamra',   0xff6600],   // ~580 nm  orange
  ['atto488', 0x11ff55],   // ~520 nm  green
  ['atto550', 0xbbff00],   // ~576 nm  yellow-green
])

// ── Reusable temporaries (never held across async boundaries) ─────────────────

const _tColor  = new THREE.Color()
const _tMatrix = new THREE.Matrix4()
const _tScale  = new THREE.Vector3()
const _tPos    = new THREE.Vector3()
const _physDir  = new THREE.Vector3()   // physics position update scratch vector
const _physDir2 = new THREE.Vector3()   // second scratch for applyPositionLerp
const _saDir   = new THREE.Vector3()   // straight-axis direction scratch (applyUnfoldOffsets)
// Axis-segment per-bp-range scratch (reused inside applyPositionLerp's
// straight-helix segment recomputation loop).
const _segS_from = new THREE.Vector3()
const _segE_from = new THREE.Vector3()
const _segS_to   = new THREE.Vector3()
const _segE_to   = new THREE.Vector3()
const _segS      = new THREE.Vector3()
const _segE      = new THREE.Vector3()

// ── Cluster-transform scratch (reused per-frame) ──────────────────────────────
const _clusterV = new THREE.Vector3()
const _clusterQ = new THREE.Quaternion()


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
const _cylQ           = new THREE.Quaternion()  // scratch for helix cylinder LOD

// ── Instance update helpers ───────────────────────────────────────────────────

function _setInstColor(entry, hexColor) {
  entry.instMesh.setColorAt(entry.id, _tColor.setHex(hexColor))
  if (entry.instMesh.instanceColor) entry.instMesh.instanceColor.needsUpdate = true
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

  // ── Helix axis sticks ──────────────────────────────────────────────────────
  // Each scaffold domain (or fallback domain) on a helix becomes one world-space
  // cylinder mesh. This lets cluster transforms with domain_ids move only the
  // segments that belong to the cluster, while leaving other segments in place.
  // Curved (deformed) helices keep a single TubeGeometry + a straight-cylinder
  // placeholder used by the deform-lerp transition.

  const AXIS_SHAFT_R  = 0.05   // shaft radius (nm)
  const _AY = new THREE.Vector3(0, 1, 0)

  const axisArrows = []   // each: see push() below
  let _axisArrowsVisible = true  // set false by cadnano mode; respected by setDetailLevel

  // Returns per-domain axis segments for a helix, sorted ascending by bp_lo.
  // Each segment carries its owning strand+domain identity for cluster filtering.
  // Prefers scaffold strand domains; falls back to all strand domains (for stub
  // helices); falls back further to a single full-helix segment with no identity.
  function _axisDomainSegments(helix) {
    const cands = []
    for (const strand of design.strands ?? []) {
      if (strand.strand_type !== 'scaffold') continue
      for (let di = 0; di < (strand.domains ?? []).length; di++) {
        const dom = strand.domains[di]
        if (dom.helix_id !== helix.id) continue
        cands.push({ strand, di, dom })
      }
    }
    if (!cands.length) {
      for (const strand of design.strands ?? []) {
        for (let di = 0; di < (strand.domains ?? []).length; di++) {
          const dom = strand.domains[di]
          if (dom.helix_id !== helix.id) continue
          cands.push({ strand, di, dom })
        }
      }
    }
    if (!cands.length) {
      return [{
        strandId:    null,
        domainIndex: -1,
        ovhgId:      null,
        bp_lo:       helix.bp_start,
        bp_hi:       helix.bp_start + helix.length_bp - 1,
      }]
    }
    cands.sort((a, b) => Math.min(a.dom.start_bp, a.dom.end_bp) - Math.min(b.dom.start_bp, b.dom.end_bp))
    const seen = new Set()
    const out = []
    for (const { strand, di, dom } of cands) {
      const lo = Math.min(dom.start_bp, dom.end_bp)
      const hi = Math.max(dom.start_bp, dom.end_bp)
      const key = `${lo}:${hi}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push({
        strandId:    strand.id,
        domainIndex: di,
        ovhgId:      dom.overhang_id ?? null,
        bp_lo:       lo,
        bp_hi:       hi,
      })
    }
    return out
  }

  for (const helix of design.helices) {
    // Skip linker virtual helices (`__lnk__<conn>`). Their bridge half is
    // rendered by overhang_link_arcs as a synthesized duplex / bead-string,
    // not as a regular helix axis stick — drawing one here produces stray
    // black lines floating between the two clusters at the linker midpoint.
    if (helix.id?.startsWith('__lnk__')) continue
    const axDef     = helixAxes?.[helix.id]
    const tubeSamp  = axDef?.samples
    const isCurved  = tubeSamp != null && tubeSamp.length > 2

    const aStart = axDef
      ? new THREE.Vector3(...axDef.start)
      : new THREE.Vector3(helix.axis_start.x, helix.axis_start.y, helix.axis_start.z)
    const aEnd   = axDef
      ? new THREE.Vector3(...axDef.end)
      : new THREE.Vector3(helix.axis_end.x,   helix.axis_end.y,   helix.axis_end.z)

    let shaft         = null   // TubeGeometry mesh (curved helices only)
    let straightShaft = null   // unit cylinder placeholder, only for curved helices' deform lerp
    const segments    = []     // per-domain world-space cylinder meshes (straight helices)

    if (isCurved) {
      const pts   = tubeSamp.map(s => new THREE.Vector3(...s))
      const curve = new THREE.CatmullRomCurve3(pts)
      const segs  = Math.max(tubeSamp.length * 4, 16)
      const geo   = new THREE.TubeGeometry(curve, segs, AXIS_SHAFT_R, 6, false)
      shaft = new THREE.Mesh(geo, new THREE.MeshPhongMaterial({ color: C.axis }))
      root.add(shaft)

      straightShaft = new THREE.Mesh(
        new THREE.CylinderGeometry(AXIS_SHAFT_R, AXIS_SHAFT_R, 1, 8),
        new THREE.MeshPhongMaterial({ color: C.axis, transparent: true, opacity: 0 }),
      )
      straightShaft.userData.skipBounds = true
      root.add(straightShaft)
    } else {
      // Straight helix: one world-space cylinder per scaffold domain (no merging).
      // Backend supplies pre-transformed per-segment endpoints when present
      // (axDef.segments); otherwise compute from the helix's straight axis. The
      // backend path covers cluster transforms and partial-coverage clusters
      // correctly; the local fallback only applies to designs without a backend
      // axes payload.
      const aVec = aEnd.clone().sub(aStart)
      const aLen = aVec.length()
      const aDir = aLen > 0.001 ? aVec.clone().normalize() : _AY.clone()

      const backendSegs = axDef?.segments
      const domSegs = backendSegs?.length ? null : _axisDomainSegments(helix)
      const segCount = backendSegs?.length ?? domSegs.length
      for (let i = 0; i < segCount; i++) {
        const bs = backendSegs?.[i]
        const ds = bs ?? domSegs[i]
        const ovhgEntry = ds.ovhgId && axDef?.ovhgAxes ? axDef.ovhgAxes[ds.ovhgId] : null
        let ws, we
        if (bs && bs.start && bs.end) {
          ws = new THREE.Vector3(...bs.start)
          we = new THREE.Vector3(...bs.end)
        } else if (ovhgEntry) {
          ws = new THREE.Vector3(...ovhgEntry.start)
          we = new THREE.Vector3(...ovhgEntry.end)
        } else {
          const tStart = (ds.bp_lo - helix.bp_start) * BDNA_RISE_PER_BP
          const tEnd   = (ds.bp_hi - helix.bp_start + 1) * BDNA_RISE_PER_BP
          ws = aStart.clone().addScaledVector(aDir, tStart)
          we = aStart.clone().addScaledVector(aDir, tEnd)
        }
        const wsDir = we.clone().sub(ws)
        const wsLen = wsDir.length()
        const adjLen = Math.max(0.01, wsLen)
        const wsUnit = wsLen > 0.001 ? wsDir.clone().normalize() : aDir.clone()
        const mesh = new THREE.Mesh(
          new THREE.CylinderGeometry(AXIS_SHAFT_R, AXIS_SHAFT_R, adjLen, 8),
          new THREE.MeshPhongMaterial({ color: C.axis }),
        )
        mesh.position.copy(ws.clone().addScaledVector(wsUnit, adjLen * 0.5))
        mesh.quaternion.setFromUnitVectors(_AY, wsUnit)
        root.add(mesh)
        // Normalise key names since backend uses snake_case while our local
        // helper emits camelCase.
        segments.push({
          mesh,
          strandId:    bs ? bs.strand_id    : ds.strandId,
          domainIndex: bs ? bs.domain_index : ds.domainIndex,
          ovhgId:      bs ? bs.ovhg_id      : ds.ovhgId,
          bp_lo:       ds.bp_lo,
          bp_hi:       ds.bp_hi,
          adjLen,
          wsStart:     ws.clone(),
          wsEnd:       we.clone(),
        })
      }
    }

    axisArrows.push({
      helixId: helix.id,
      isCurved,
      shaft,                              // tube mesh for curved helices, null otherwise
      straightShaft,                      // straight-cylinder placeholder for curved deform lerp
      segments,                           // per-domain world-space meshes (straight helices)
      aStart: aStart.clone(),
      aEnd:   aEnd.clone(),
      samples: isCurved ? tubeSamp : null,
      bpStart: helix.bp_start,
      bpLen:   helix.length_bp,
    })
  }

  // Reposition every per-domain segment of a straight helix along the axis line
  // (baseStart → baseEnd). Used by revertToGeometry, applyUnfoldOffsets, and
  // applyDeformLerp; all three need to keep segments aligned to a recomputed axis.
  // Mesh geometry length is fixed at build time, so this only translates+rotates;
  // bp ranges are static so segLen ≈ build-time length under any rigid axis change.
  const _segDir = new THREE.Vector3()
  const _segQ   = new THREE.Quaternion()
  function _layStraightSegments(arrow, baseStart, baseEnd) {
    if (arrow.isCurved || !arrow.segments?.length) return
    _segDir.set(baseEnd.x - baseStart.x, baseEnd.y - baseStart.y, baseEnd.z - baseStart.z)
    const dlen = _segDir.length()
    if (dlen < 0.001) return
    _segDir.divideScalar(dlen)
    _segQ.setFromUnitVectors(_AY, _segDir)
    for (const seg of arrow.segments) {
      const tS = (seg.bp_lo - arrow.bpStart) * BDNA_RISE_PER_BP
      const tE = (seg.bp_hi - arrow.bpStart + 1) * BDNA_RISE_PER_BP
      const wsX = baseStart.x + _segDir.x * tS
      const wsY = baseStart.y + _segDir.y * tS
      const wsZ = baseStart.z + _segDir.z * tS
      const weX = baseStart.x + _segDir.x * tE
      const weY = baseStart.y + _segDir.y * tE
      const weZ = baseStart.z + _segDir.z * tE
      seg.wsStart.set(wsX, wsY, wsZ)
      seg.wsEnd.set(weX, weY, weZ)
      seg.mesh.position.set(
        (wsX + weX) * 0.5,
        (wsY + weY) * 0.5,
        (wsZ + weZ) * 0.5,
      )
      seg.mesh.quaternion.copy(_segQ)
    }
  }

  // ── Staple colour map ──────────────────────────────────────────────────────

  const stapleColorMap = buildStapleColorMap(geometry, design)

  // ── Backbone beads (InstancedMesh) ────────────────────────────────────────

  // Exclude fluorophore beads from the regular bead meshes — they go in iFluoros.
  const assignedGeometry = geometry.filter(n => n.strand_id && !n.is_modification)
  const fluoroGeometry   = geometry.filter(n => n.is_modification)
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
  if (iSpheres.instanceColor) iSpheres.instanceColor.needsUpdate = true
  iCubes.instanceMatrix.needsUpdate   = true
  if (iCubes.instanceColor)   iCubes.instanceColor.needsUpdate   = true

  // ── Fluorophore beads (InstancedMesh) — modification markers at extension tips ─

  const iFluoros = new THREE.InstancedMesh(
    GEO_FLUORO_SPHERE,
    new THREE.MeshPhongMaterial({ color: 0xffffff }),
    Math.max(1, fluoroGeometry.length),
  )
  iFluoros.frustumCulled = false
  iFluoros.name = 'extensionFluorophores'
  root.add(iFluoros)

  const fluoroEntries = []
  let fluoroId = 0

  for (const nuc of fluoroGeometry) {
    const color = MODIFICATION_COLORS[nuc.modification] ?? 0xffffff
    const pos   = new THREE.Vector3(...nuc.backbone_position)
    _tMatrix.compose(pos, ID_QUAT, _tScale.set(1, 1, 1))
    iFluoros.setMatrixAt(fluoroId, _tMatrix)
    iFluoros.setColorAt(fluoroId, _tColor.setHex(color))
    fluoroEntries.push({ instMesh: iFluoros, id: fluoroId, nuc, pos, defaultColor: color })
    fluoroId++
  }

  iFluoros.instanceMatrix.needsUpdate = true
  if (iFluoros.instanceColor) iFluoros.instanceColor.needsUpdate = true

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
  if (iCones.instanceColor) iCones.instanceColor.needsUpdate = true

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
    // Extension beads have no base-pair slabs.
    if (nuc.helix_id.startsWith('__ext_')) continue
    const bnDir  = new THREE.Vector3(...nuc.base_normal)
    const tanDir = new THREE.Vector3(...nuc.axis_tangent)
    const quat   = slabQuaternion(bnDir, tanDir)
    const color  = nucSlabColor(nuc, stapleColorMap, customColors, loopSet)
    const bbPos  = new THREE.Vector3(...nuc.backbone_position)
    const center = slabCenter(bbPos, bnDir, slabParams.distance)

    _tMatrix.compose(center, quat, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
    iSlabs.setMatrixAt(slabId, _tMatrix)
    iSlabs.setColorAt(slabId, _tColor.setHex(color))

    slabEntries.push({ instMesh: iSlabs, id: slabId, nuc, quat, bnDir, bbPos, center, defaultColor: color })
    slabId++
  }

  iSlabs.instanceMatrix.needsUpdate = true
  if (iSlabs.instanceColor) iSlabs.instanceColor.needsUpdate = true

  // ── Domain cylinders (LOD level 2 — one per domain, strand-colored) ─────────
  // One cylinder per non-overhang domain, positioned along the helix axis at
  // the domain's bp extent and colored by the owning strand.
  // Invisible by default; activated by setDetailLevel(2) when far out.
  //
  // Straight helices: InstancedMesh (iHelixCylinders / iOverhangCylinders)
  // Curved  helices:  TubeGeometry per-domain (iCurvedHelixCylinders proxy for
  //                   lerp + individual tube meshes in _curvedCylGroup).

  // Build arrow map once so counting can check isCurved.
  const _arrowByHelixId = new Map(axisArrows.map(a => [a.helixId, a]))

  // Count per-category.  Scaffold domains skipped to avoid z-fighting.
  let _domainCylCount        = 0
  let _curvedDomainCylCount  = 0
  let _overhangCylCount      = 0
  let _curvedOvhgCylCount    = 0
  for (const strand of design.strands) {
    if (strand.strand_type === 'scaffold') continue
    for (const dom of strand.domains) {
      const arrowC = _arrowByHelixId.get(dom.helix_id)
      const curved = arrowC?.isCurved ?? false
      if (dom.overhang_id != null) { if (curved) _curvedOvhgCylCount++;  else _overhangCylCount++ }
      else                         { if (curved) _curvedDomainCylCount++; else _domainCylCount++ }
    }
  }

  // Straight-helix instanced meshes (existing approach).
  const iHelixCylinders = new THREE.InstancedMesh(
    GEO_UNIT_CYL,
    new THREE.MeshLambertMaterial({ color: 0xffffff }),
    Math.max(1, _domainCylCount),
  )
  iHelixCylinders.frustumCulled = false
  iHelixCylinders.visible = false
  iHelixCylinders.name = 'helixCylinders'
  root.add(iHelixCylinders)

  // Curved-helix straight-proxy instanced mesh — used only for lerp cross-fade.
  // Opacity 1 at t=0 (straight), 0 at t=1 (fully deformed, curved tubes take over).
  const iCurvedHelixCylinders = new THREE.InstancedMesh(
    GEO_UNIT_CYL,
    new THREE.MeshLambertMaterial({ color: 0xffffff, transparent: true, opacity: 0 }),
    Math.max(1, _curvedDomainCylCount),
  )
  iCurvedHelixCylinders.frustumCulled = false
  iCurvedHelixCylinders.visible = false
  iCurvedHelixCylinders.name = 'curvedHelixCylindersProxy'
  root.add(iCurvedHelixCylinders)

  // Group of per-domain TubeGeometry meshes for curved helices.
  const _curvedCylGroup = new THREE.Group()
  _curvedCylGroup.name = 'curvedCylGroup'
  _curvedCylGroup.visible = false
  root.add(_curvedCylGroup)

  // Half-cylinder mesh for single-stranded overhang domains (amber, DoubleSide so
  // the inside of the curved surface is visible when viewed at oblique angles).
  const iOverhangCylinders = new THREE.InstancedMesh(
    GEO_HALF_CYL,
    new THREE.MeshLambertMaterial({ color: 0xffffff, side: THREE.DoubleSide }),
    Math.max(1, _overhangCylCount),
  )
  iOverhangCylinders.frustumCulled = false
  iOverhangCylinders.visible = false
  iOverhangCylinders.name = 'overhangCylinders'
  root.add(iOverhangCylinders)

  // Curved-helix straight-proxy for overhang half-cylinders.
  const iCurvedOverhangCylinders = new THREE.InstancedMesh(
    GEO_HALF_CYL,
    new THREE.MeshLambertMaterial({ color: 0xffffff, side: THREE.DoubleSide, transparent: true, opacity: 0 }),
    Math.max(1, _curvedOvhgCylCount),
  )
  iCurvedOverhangCylinders.frustumCulled = false
  iCurvedOverhangCylinders.visible = false
  iCurvedOverhangCylinders.name = 'curvedOverhangCylindersProxy'
  root.add(iCurvedOverhangCylinders)

  // Group of per-domain curved half-tube meshes for overhang domains on curved helices.
  const _curvedOvhgGroup = new THREE.Group()
  _curvedOvhgGroup.name = 'curvedOvhgGroup'
  _curvedOvhgGroup.visible = false
  root.add(_curvedOvhgGroup)

  // Per-domain metadata used by applyUnfoldOffsets / revertToGeometry / setStrandColor.
  // _domainCylData: straight-helix domains.  _curvedDomainCylData: curved-helix domains.
  // Each entry: { helixId, strandId, t0, t1, cylIdx, arrow, defaultColor [, mesh] }
  const _domainCylData        = []
  const _curvedDomainCylData  = []
  const _overhangCylData      = []
  const _curvedOvhgCylData    = []

  let _detailLevel    = 0    // 0=full, 1=beads-only, 2=cylinders
  let _beadScale      = 1.0  // global scale factor applied to all backbone beads
  // Keys for cluster visibility toggle.  Two formats:
  //   'h:<helix_id>'                   — hide the whole helix (helix-level cluster)
  //   'd:<strand_id>:<domain_index>'   — hide specific domain (domain-level cluster)
  let _hiddenNucKeys = new Set()
  const _isNucHidden = nuc =>
    _hiddenNucKeys.has('h:' + nuc.helix_id) ||
    (nuc.domain_index != null && _hiddenNucKeys.has('d:' + nuc.strand_id + ':' + nuc.domain_index))
  let _cylRadiusScale = 1.0  // XZ scale applied to domain cylinders (1 = geometry default 1.125 nm)

  // ── Curved-tube builder ────────────────────────────────────────────────────
  // Builds a TubeGeometry for a domain spanning bp [lo, hi] on a curved helix.
  // Returns { geo, t0Curve, t1Curve } where t0/t1Curve are the curve parameters
  // used (so they can be re-used when rebuilding after a radius change).
  function _buildDomainTubeGeo(arrow, lo, hi, tubRadius, openAngle = 2 * Math.PI) {
    const nSamples  = arrow.samples.length
    const bpSpan    = Math.max(1, arrow.bpLen - 1)
    const halfBpT   = 0.5 / bpSpan
    const t0c = Math.max(0, Math.min(1, (lo - arrow.bpStart) / bpSpan - halfBpT))
    const t1c = Math.max(0, Math.min(1, (hi - arrow.bpStart) / bpSpan + halfBpT))
    if (t1c <= t0c) return null

    const fullCurve = new THREE.CatmullRomCurve3(arrow.samples.map(s => new THREE.Vector3(s[0], s[1], s[2])))
    const nPts = Math.max(4, Math.ceil(nSamples * (t1c - t0c)) + 2)
    const pts  = []
    for (let i = 0; i <= nPts; i++) pts.push(fullCurve.getPoint(t0c + (i / nPts) * (t1c - t0c)))
    const segCurve = new THREE.CatmullRomCurve3(pts)
    const segs     = Math.max(2, nPts)
    const radialSeg = openAngle < 2 * Math.PI ? 4 : 8
    const geo = new THREE.TubeGeometry(segCurve, segs, tubRadius, radialSeg, false)
    return { geo, t0Curve: t0c, t1Curve: t1c }
  }

  {
    const helixMap = new Map(design.helices.map(h => [h.id, h]))
    let cylIdx       = 0   // straight domain instanced-mesh counter
    let curvedIdx    = 0   // curved domain proxy instanced-mesh counter
    let ovhgIdx      = 0   // straight overhang instanced-mesh counter
    let curvedOvhgIdx = 0  // curved overhang proxy instanced-mesh counter

    const CYL_TUBE_R = 1.125 * _cylRadiusScale  // tube radius matching GEO_UNIT_CYL

    for (const strand of design.strands) {
      // Scaffold domains skipped to avoid z-fighting.
      if (strand.strand_type === 'scaffold') continue

      const strandColor = loopSet.has(strand.id) ? C.highlight_red
        : (customColors[strand.id] ?? stapleColorMap.get(strand.id) ?? C.unassigned)

      for (let domIdx = 0; domIdx < strand.domains.length; domIdx++) {
        const dom    = strand.domains[domIdx]
        const isOvhg = dom.overhang_id != null
        const helix  = helixMap.get(dom.helix_id)
        const arrow  = _arrowByHelixId.get(dom.helix_id)
        if (!helix || !arrow) continue

        const lo = Math.min(dom.start_bp, dom.end_bp)
        const hi = Math.max(dom.start_bp, dom.end_bp)

        if (arrow.isCurved) {
          // ── Curved helix: TubeGeometry + straight proxy ─────────────────────
          const openAngle = isOvhg ? Math.PI : 2 * Math.PI
          const built = _buildDomainTubeGeo(arrow, lo, hi, CYL_TUBE_R, openAngle)
          if (built) {
            const tubeMesh = new THREE.Mesh(
              built.geo,
              new THREE.MeshLambertMaterial({
                color: strandColor, transparent: true, opacity: 1,
                side: isOvhg ? THREE.DoubleSide : THREE.FrontSide,
              }),
            )
            tubeMesh.userData = { helixId: dom.helix_id, strandId: strand.id, t0: built.t0Curve, t1: built.t1Curve, isOvhg, defaultColor: strandColor }
            if (isOvhg) _curvedOvhgGroup.add(tubeMesh)
            else        _curvedCylGroup.add(tubeMesh)
          }

          // Straight proxy (straight line between aStart/aEnd, used during lerp t→0).
          const s = arrow.aStart, e = arrow.aEnd
          const axLen = s.distanceTo(e)
          if (axLen >= 0.001) {
            const tRaw0 = (lo - helix.bp_start) * BDNA_RISE_PER_BP / axLen
            const tRaw1 = (hi - helix.bp_start) * BDNA_RISE_PER_BP / axLen
            const hBp   = 0.5 * BDNA_RISE_PER_BP / axLen
            const t0p   = Math.max(0, tRaw0 - hBp)
            const t1p   = Math.min(1, tRaw1 + hBp)
            const p0x = s.x + (e.x - s.x) * t0p, p0y = s.y + (e.y - s.y) * t0p, p0z = s.z + (e.z - s.z) * t0p
            const p1x = s.x + (e.x - s.x) * t1p, p1y = s.y + (e.y - s.y) * t1p, p1z = s.z + (e.z - s.z) * t1p
            _tPos.set((p0x + p1x) * 0.5, (p0y + p1y) * 0.5, (p0z + p1z) * 0.5)
            _physDir.set(p1x - p0x, p1y - p0y, p1z - p0z)
            const pLen = _physDir.length()
            if (pLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(pLen))
            else _cylQ.identity()
            _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, pLen, _cylRadiusScale))
            const iProxy = isOvhg ? iCurvedOverhangCylinders : iCurvedHelixCylinders
            const idxProxy = isOvhg ? curvedOvhgIdx : curvedIdx
            iProxy.setMatrixAt(idxProxy, _tMatrix)
            iProxy.setColorAt(idxProxy, _tColor.setHex(strandColor))
            if (isOvhg) {
              _curvedOvhgCylData.push({ helixId: dom.helix_id, strandId: strand.id, bp_lo: lo, bp_hi: hi, t0: t0p, t1: t1p, cylIdx: curvedOvhgIdx, arrow, defaultColor: strandColor })
              curvedOvhgIdx++
            } else {
              _curvedDomainCylData.push({ helixId: dom.helix_id, strandId: strand.id, bp_lo: lo, bp_hi: hi, t0: t0p, t1: t1p, cylIdx: curvedIdx, arrow, defaultColor: strandColor })
              curvedIdx++
            }
          }
        } else {
          // ── Straight helix: existing instanced-mesh approach ─────────────────
          const s = arrow.aStart, e = arrow.aEnd
          const axLen = s.distanceTo(e)
          if (axLen < 0.001) continue
          const tRaw0 = (lo - helix.bp_start) * BDNA_RISE_PER_BP / axLen
          const tRaw1 = (hi - helix.bp_start) * BDNA_RISE_PER_BP / axLen
          const hBp   = 0.5 * BDNA_RISE_PER_BP / axLen
          const t0     = Math.max(0, tRaw0 - hBp)
          const t1     = Math.min(1, tRaw1 + hBp)
          const d0x = s.x + (e.x - s.x) * t0, d0y = s.y + (e.y - s.y) * t0, d0z = s.z + (e.z - s.z) * t0
          const d1x = s.x + (e.x - s.x) * t1, d1y = s.y + (e.y - s.y) * t1, d1z = s.z + (e.z - s.z) * t1
          _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
          _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
          const cylLen = _physDir.length()
          if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
          else _cylQ.identity()
          _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
          if (isOvhg) {
            // If per-domain ovhg_axes are available, use them directly for the initial
            // cylinder matrix and store world-space endpoints for cluster transforms.
            const ovhgAx = helixAxes?.[dom.helix_id]?.ovhgAxes?.[dom.overhang_id] ?? null
            let wsStart = null, wsEnd = null
            if (ovhgAx) {
              const ws = new THREE.Vector3(...ovhgAx.start)
              const we = new THREE.Vector3(...ovhgAx.end)
              const bpSpan = ovhgAx.bp_max - ovhgAx.bp_min + 1
              const hf = 0.5 / bpSpan
              const t0ov = Math.max(0, (lo - ovhgAx.bp_min) / bpSpan - hf)
              const t1ov = Math.min(1, (hi - ovhgAx.bp_min) / bpSpan + hf)
              const dir = we.clone().sub(ws)
              wsStart = ws.clone().addScaledVector(dir, t0ov)
              wsEnd   = ws.clone().addScaledVector(dir, t1ov)
              _tPos.set((wsStart.x + wsEnd.x) * 0.5, (wsStart.y + wsEnd.y) * 0.5, (wsStart.z + wsEnd.z) * 0.5)
              _physDir.set(wsEnd.x - wsStart.x, wsEnd.y - wsStart.y, wsEnd.z - wsStart.z)
              const cl2 = _physDir.length()
              if (cl2 > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cl2))
              else _cylQ.identity()
              _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cl2, _cylRadiusScale))
            }
            iOverhangCylinders.setMatrixAt(ovhgIdx, _tMatrix)
            iOverhangCylinders.setColorAt(ovhgIdx, _tColor.setHex(strandColor))
            _overhangCylData.push({ helixId: dom.helix_id, strandId: strand.id, domainIndex: domIdx, overhangId: dom.overhang_id, bp_lo: lo, bp_hi: hi, t0, t1, cylIdx: ovhgIdx, arrow, defaultColor: strandColor, wsStart, wsEnd })
            ovhgIdx++
          } else {
            iHelixCylinders.setMatrixAt(cylIdx, _tMatrix)
            iHelixCylinders.setColorAt(cylIdx, _tColor.setHex(strandColor))
            _domainCylData.push({ helixId: dom.helix_id, strandId: strand.id, bp_lo: lo, bp_hi: hi, t0, t1, cylIdx, arrow, defaultColor: strandColor })
            cylIdx++
          }
        }
      }
    }
  }

  iHelixCylinders.instanceMatrix.needsUpdate        = true
  if (iHelixCylinders.instanceColor)         iHelixCylinders.instanceColor.needsUpdate         = true
  iCurvedHelixCylinders.instanceMatrix.needsUpdate  = true
  if (iCurvedHelixCylinders.instanceColor)   iCurvedHelixCylinders.instanceColor.needsUpdate   = true
  iOverhangCylinders.instanceMatrix.needsUpdate     = true
  if (iOverhangCylinders.instanceColor)      iOverhangCylinders.instanceColor.needsUpdate      = true
  iCurvedOverhangCylinders.instanceMatrix.needsUpdate = true
  if (iCurvedOverhangCylinders.instanceColor) iCurvedOverhangCylinders.instanceColor.needsUpdate = true

  // ── Slab param update ──────────────────────────────────────────────────────

  function applySlabParams() {
    for (const entry of slabEntries) {
      const center = slabCenter(entry.bbPos, entry.bnDir, slabParams.distance)
      _tMatrix.compose(center, entry.quat, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
      iSlabs.setMatrixAt(entry.id, _tMatrix)
    }
    iSlabs.instanceMatrix.needsUpdate = true
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
      _setBeadScale(entry, _isNucHidden(entry.nuc) ? 0 : _beadScale)
    }
    for (const entry of coneEntries) {
      _setInstColor(entry, dimmed ? dimHex : entry.defaultColor)
      // Cross-helix cones stay hidden (rendered as arc lines instead).
      if (!entry.isCrossHelix) _setConeXZScale(entry, _isNucHidden(entry.fromNuc) ? 0 : CONE_RADIUS)
    }
    for (const entry of slabEntries) {
      _setInstColor(entry, dimmed ? dimHex : entry.defaultColor)
    }
    const axisOpacity = dimmed ? 0.15 : 1.0
    for (const arrow of axisArrows) {
      for (const m of _arrowMaterials(arrow)) {
        m.opacity     = axisOpacity
        m.transparent = dimmed
      }
    }
  }

  // Iterate every material on an axis arrow (shaft + per-domain segments) so
  // dim/highlight passes can flip opacity/colour without touching node count.
  function* _arrowMaterials(arrow) {
    if (arrow.isCurved) {
      if (arrow.shaft?.material) yield arrow.shaft.material
    } else {
      for (const seg of arrow.segments ?? []) {
        if (seg.mesh?.material) yield seg.mesh.material
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
    for (const arrow of axisArrows) {
      for (const m of _arrowMaterials(arrow)) {
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
  // Fluorophore beads live in fluoroEntries (separate from backboneEntries) and
  // are intentionally NOT added to _nucToEntry — the cone-update path doesn't
  // gate cross-helix cones to radius 0, so including fluoros there would draw
  // visible cones from the strand-end bead to the fluorophore. getNucLivePos
  // falls back to this map so arc endpoints landing on a fluorophore (e.g. the
  // cross-helix arc rendered by unfold_view._arcGroup) update correctly under
  // cluster transforms.
  const _fluoroNucToEntry = new Map()
  for (const entry of fluoroEntries) _fluoroNucToEntry.set(entry.nuc, entry)

  // ── Extension → parent helix map (for cluster rigid transforms) ─────────────
  // Maps extension_id → helix_id of the real terminal helix.
  const _extToRealHelix = new Map()
  for (const cone of coneEntries) {
    const fn = cone.fromNuc, tn = cone.toNuc
    if (!fn.helix_id.startsWith('__ext_') && tn.helix_id.startsWith('__ext_')) {
      const extId = tn.extension_id
      if (extId && !_extToRealHelix.has(extId)) _extToRealHelix.set(extId, fn.helix_id)
    } else if (fn.helix_id.startsWith('__ext_') && !tn.helix_id.startsWith('__ext_')) {
      const extId = fn.extension_id
      if (extId && !_extToRealHelix.has(extId)) _extToRealHelix.set(extId, tn.helix_id)
    }
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
      _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
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
      _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
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

    // 4. Axis sticks.
    for (const arrow of axisArrows) {
      const sa = useStraight ? straightAxesMap.get(arrow.helixId) : null
      const baseStart = sa ? sa.start : arrow.aStart
      const baseEnd   = sa ? sa.end   : arrow.aEnd

      if (arrow.isCurved) {
        arrow.shaft.position.set(0, 0, 0)
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
      } else {
        // Straight helix: lay each per-domain segment along baseStart→baseEnd.
        _layStraightSegments(arrow, baseStart, baseEnd)
      }
    }

    // 5. Helix cylinders (LOD) — reset to per-domain axis positions.
    for (const dom of _domainCylData) {
      const sa = useStraight ? straightAxesMap?.get(dom.helixId) : null
      const s  = sa ? sa.start : dom.arrow.aStart
      const e  = sa ? sa.end   : dom.arrow.aEnd
      const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
      const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
      _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
      _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
      const cylLen = _physDir.length()
      if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
      else _cylQ.identity()
      _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
      iHelixCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
    }
    iHelixCylinders.instanceMatrix.needsUpdate = true

    // 5b. Overhang half-cylinders.
    for (const dom of _overhangCylData) {
      if (dom.wsStart) continue  // shared-stub: stays at current rotated position; stubs don't bend
      const sa = useStraight ? straightAxesMap?.get(dom.helixId) : null
      const s  = sa ? sa.start : dom.arrow.aStart
      const e  = sa ? sa.end   : dom.arrow.aEnd
      const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
      const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
      _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
      _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
      const cylLen = _physDir.length()
      if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
      else _cylQ.identity()
      _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
      iOverhangCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
    }
    iOverhangCylinders.instanceMatrix.needsUpdate = true

    // 5c. Curved-helix proxy cylinders — snap to straight or deformed axis positions.
    for (const dom of _curvedDomainCylData) {
      const sa = useStraight ? straightAxesMap?.get(dom.helixId) : null
      const s  = sa ? sa.start : dom.arrow.aStart
      const e  = sa ? sa.end   : dom.arrow.aEnd
      const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
      const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
      _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
      _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
      const cLen0 = _physDir.length()
      if (cLen0 > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cLen0))
      else _cylQ.identity()
      _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cLen0, _cylRadiusScale))
      iCurvedHelixCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
    }
    iCurvedHelixCylinders.instanceMatrix.needsUpdate = true
    const _cvProxyOp = useStraight ? 1 : 0
    iCurvedHelixCylinders.material.opacity = _cvProxyOp
    for (const mesh of _curvedCylGroup.children)   mesh.material.opacity = 1 - _cvProxyOp
    for (const dom of _curvedOvhgCylData) {
      const sa = useStraight ? straightAxesMap?.get(dom.helixId) : null
      const s  = sa ? sa.start : dom.arrow.aStart
      const e  = sa ? sa.end   : dom.arrow.aEnd
      const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
      const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
      _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
      _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
      const cLen1 = _physDir.length()
      if (cLen1 > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cLen1))
      else _cylQ.identity()
      _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cLen1, _cylRadiusScale))
      iCurvedOverhangCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
    }
    iCurvedOverhangCylinders.instanceMatrix.needsUpdate = true
    iCurvedOverhangCylinders.material.opacity = _cvProxyOp
    for (const mesh of _curvedOvhgGroup.children) mesh.material.opacity = 1 - _cvProxyOp

    // 6. Fluorophore beads — always revert to backbone_position (no straight map).
    for (const entry of fluoroEntries) {
      const bp = entry.nuc.backbone_position
      entry.pos.set(bp[0], bp[1], bp[2])
      _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(1, 1, 1))
      entry.instMesh.setMatrixAt(entry.id, _tMatrix)
    }
    iFluoros.instanceMatrix.needsUpdate = true
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
      // Extension beads (__ext_) are handled by their own method.
      if (entry.nuc.helix_id.startsWith('__ext_')) continue
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
      _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
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
      // Extension beads (__ext_) have no slabs.
      if (slab.nuc.helix_id.startsWith('__ext_')) continue
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

    // 4. Axis sticks.
    for (const arrow of axisArrows) {
      const off = helixOffsets.get(arrow.helixId)
      const ox  = off ? off.x * t : 0
      const oy  = off ? off.y * t : 0
      const oz  = off ? off.z * t : 0

      const sa         = straightAxesMap?.get(arrow.helixId)
      const baseStart  = sa ? sa.start : arrow.aStart
      const baseEnd    = sa ? sa.end   : arrow.aEnd

      if (arrow.isCurved) {
        arrow.shaft.position.set(ox, oy, oz)
        if (arrow.straightShaft && sa) {
          arrow.straightShaft.position.set(
            (sa.start.x + sa.end.x) * 0.5 + ox,
            (sa.start.y + sa.end.y) * 0.5 + oy,
            (sa.start.z + sa.end.z) * 0.5 + oz,
          )
        }
      } else {
        // Straight: lay segments along (baseStart+offset) → (baseEnd+offset).
        _physDir.set(baseStart.x + ox, baseStart.y + oy, baseStart.z + oz)
        _physDir2.set(baseEnd.x + ox, baseEnd.y + oy, baseEnd.z + oz)
        _layStraightSegments(arrow, _physDir, _physDir2)
      }
    }

    // 5. Helix cylinders (LOD) — translate with unfold offset per domain.
    for (const dom of _domainCylData) {
      const off = helixOffsets.get(dom.helixId)
      const ox2 = off ? off.x * t : 0
      const oy2 = off ? off.y * t : 0
      const oz2 = off ? off.z * t : 0
      const sa2 = straightAxesMap?.get(dom.helixId)
      const s   = sa2 ? sa2.start : dom.arrow.aStart
      const e   = sa2 ? sa2.end   : dom.arrow.aEnd
      const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
      const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
      _tPos.set((d0x + d1x) * 0.5 + ox2, (d0y + d1y) * 0.5 + oy2, (d0z + d1z) * 0.5 + oz2)
      _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
      const cylLen = _physDir.length()
      if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
      else _cylQ.identity()
      _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
      iHelixCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
    }
    iHelixCylinders.instanceMatrix.needsUpdate = true

    // 5b. Overhang half-cylinders — translate with unfold offset.
    for (const dom of _overhangCylData) {
      const off = helixOffsets.get(dom.helixId)
      const ox2 = off ? off.x * t : 0
      const oy2 = off ? off.y * t : 0
      const oz2 = off ? off.z * t : 0
      const sa2 = straightAxesMap?.get(dom.helixId)
      const s   = sa2 ? sa2.start : dom.arrow.aStart
      const e   = sa2 ? sa2.end   : dom.arrow.aEnd
      const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
      const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
      _tPos.set((d0x + d1x) * 0.5 + ox2, (d0y + d1y) * 0.5 + oy2, (d0z + d1z) * 0.5 + oz2)
      _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
      const cylLen = _physDir.length()
      if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
      else _cylQ.identity()
      _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
      iOverhangCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
    }
    iOverhangCylinders.instanceMatrix.needsUpdate = true

    // 5c. Curved-helix proxy cylinders — translate with unfold offset (tubes are invisible at t=0 deform).
    for (const dom of _curvedDomainCylData) {
      const off = helixOffsets.get(dom.helixId)
      const ox2 = off ? off.x * t : 0, oy2 = off ? off.y * t : 0, oz2 = off ? off.z * t : 0
      const sa2 = straightAxesMap?.get(dom.helixId)
      const s   = sa2 ? sa2.start : dom.arrow.aStart
      const e   = sa2 ? sa2.end   : dom.arrow.aEnd
      const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
      const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
      _tPos.set((d0x + d1x) * 0.5 + ox2, (d0y + d1y) * 0.5 + oy2, (d0z + d1z) * 0.5 + oz2)
      _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
      const cLenA = _physDir.length()
      if (cLenA > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cLenA))
      else _cylQ.identity()
      _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cLenA, _cylRadiusScale))
      iCurvedHelixCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
    }
    iCurvedHelixCylinders.instanceMatrix.needsUpdate = true
    for (const dom of _curvedOvhgCylData) {
      const off = helixOffsets.get(dom.helixId)
      const ox2 = off ? off.x * t : 0, oy2 = off ? off.y * t : 0, oz2 = off ? off.z * t : 0
      const sa2 = straightAxesMap?.get(dom.helixId)
      const s   = sa2 ? sa2.start : dom.arrow.aStart
      const e   = sa2 ? sa2.end   : dom.arrow.aEnd
      const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
      const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
      _tPos.set((d0x + d1x) * 0.5 + ox2, (d0y + d1y) * 0.5 + oy2, (d0z + d1z) * 0.5 + oz2)
      _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
      const cLenB = _physDir.length()
      if (cLenB > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cLenB))
      else _cylQ.identity()
      _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cLenB, _cylRadiusScale))
      iCurvedOverhangCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
    }
    iCurvedOverhangCylinders.instanceMatrix.needsUpdate = true

    return crossHelixConns
  }

  // ── Cluster base-position snapshot (captured at gizmo attach time) ───────────
  // Keyed so applyClusterTransform applies an incremental transform from these
  // positions rather than re-applying the full formula to already-transformed
  // backbone_position values (which would double the movement).

  let _cbEntries      = new Map()   // `helix_id:bp_index:direction` → THREE.Vector3
  let _cbSlabs        = new Map()   // slab.nuc ref → {bnDir: Vector3, quat: Quaternion}
  let _cbArrows       = new Map()   // helixId → {aStart, aEnd, shaftPos, shaftQuat, ssPos, ssQuat}
  let _cbExtEntries   = new Map()   // `helix_id:bp_index` → THREE.Vector3 for __ext_ beads
  let _cbFluoEntries  = new Map()   // `helix_id:bp_index` → THREE.Vector3 for fluorophore beads
  let _cbOvhgCyls     = new Map()   // _overhangCylData entry → {wsStart, wsEnd}
  let _cbSegments     = new Map()   // arrow.segments entry → {wsStart, wsEnd}
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

    /** Set the global bead display radius (nm).  Resets all backbone bead scales. */
    setBeadRadius(r) {
      _beadScale = r / BEAD_RADIUS
      for (const entry of backboneEntries) _setBeadScale(entry, _beadScale)
    },

    /** Set the domain cylinder display radius (nm).  Rebuilds all cylinder matrices. */
    setCylinderRadius(r) {
      _cylRadiusScale = r / 1.125
      for (const dom of _domainCylData) {
        const s = dom.arrow.aStart, e = dom.arrow.aEnd
        const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
        const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
        _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
        _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
        const cylLen = _physDir.length()
        if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
        else _cylQ.identity()
        _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
        iHelixCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
      }
      iHelixCylinders.instanceMatrix.needsUpdate = true
      for (const dom of _overhangCylData) {
        const s = dom.arrow.aStart, e = dom.arrow.aEnd
        const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
        const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
        _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
        _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
        const cylLen = _physDir.length()
        if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
        else _cylQ.identity()
        _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
        iOverhangCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
      }
      iOverhangCylinders.instanceMatrix.needsUpdate = true

      // Curved-helix proxy matrices (straight proxy follows the same formula).
      for (const dom of _curvedDomainCylData) {
        const s = dom.arrow.aStart, e = dom.arrow.aEnd
        const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
        const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
        _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
        _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
        const cylLen = _physDir.length()
        if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
        else _cylQ.identity()
        _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
        iCurvedHelixCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
      }
      iCurvedHelixCylinders.instanceMatrix.needsUpdate = true
      for (const dom of _curvedOvhgCylData) {
        const s = dom.arrow.aStart, e = dom.arrow.aEnd
        const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
        const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
        _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
        _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
        const cylLen = _physDir.length()
        if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
        else _cylQ.identity()
        _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
        iCurvedOverhangCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
      }
      iCurvedOverhangCylinders.instanceMatrix.needsUpdate = true

      // Rebuild curved tube geometries at new radius.
      for (const mesh of [..._curvedCylGroup.children, ..._curvedOvhgGroup.children]) {
        const { helixId, t0, t1, isOvhg } = mesh.userData
        const arrow = _arrowByHelixId.get(helixId)
        if (!arrow?.samples) continue
        const openAngle = isOvhg ? Math.PI : 2 * Math.PI
        const fullCurve = new THREE.CatmullRomCurve3(arrow.samples.map(s => new THREE.Vector3(s[0], s[1], s[2])))
        const nSamples = arrow.samples.length
        const nPts = Math.max(4, Math.ceil(nSamples * (t1 - t0)) + 2)
        const pts  = []
        for (let i = 0; i <= nPts; i++) pts.push(fullCurve.getPoint(t0 + (i / nPts) * (t1 - t0)))
        const segCurve  = new THREE.CatmullRomCurve3(pts)
        const radialSeg = openAngle < 2 * Math.PI ? 4 : 8
        mesh.geometry.dispose()
        mesh.geometry = new THREE.TubeGeometry(segCurve, Math.max(2, nPts), r, radialSeg, false)
      }
    },

    /** Palette colors assigned at build time, before any custom/group overrides.
     *  Used by design_renderer to revert strands to palette when removed from a group. */
    getPaletteColors() { return stapleColorMap },

    /**
     * In-place nucleotide metadata patch (Fix B part 2).
     *
     * Updates strand_id, strand_type, is_five_prime, is_three_prime, domain_index
     * for the supplied nucleotides without tearing down and rebuilding the whole scene.
     * New strand IDs from nicks are assigned the next palette slot.
     * After updating metadata, callers should invoke setMode() to re-apply mode colours.
     *
     * @param {Array}  partialNucs   — nucleotide objects from the partial geometry response
     * @param {object} customColors  — strandId → hex override (store.strandColors)
     * @param {Set}    loopSet       — strand IDs with circular topology
     */
    patchNucleotides(partialNucs, customColors, loopSet) {
      // Extend palette for any new strand IDs introduced by the operation.
      let paletteIdx = stapleColorMap.size
      for (const nuc of partialNucs) {
        if (nuc.strand_id && nuc.strand_type !== 'scaffold' && !stapleColorMap.has(nuc.strand_id)) {
          stapleColorMap.set(nuc.strand_id, STAPLE_PALETTE[paletteIdx % STAPLE_PALETTE.length])
          paletteIdx++
        }
      }
      // Update each entry's nuc metadata and defaultColor.
      for (const nuc of partialNucs) {
        const key = `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`
        const entry = _keyToEntry.get(key)
        if (!entry) continue
        entry.nuc.strand_id    = nuc.strand_id
        entry.nuc.strand_type  = nuc.strand_type
        entry.nuc.is_five_prime  = nuc.is_five_prime
        entry.nuc.is_three_prime = nuc.is_three_prime
        entry.nuc.domain_index   = nuc.domain_index
        const color = nucColor(nuc, stapleColorMap, customColors, loopSet)
        entry.defaultColor = color
        _setInstColor(entry, color)
      }
      // Also update cone entries that cross the changed helices (strand-ID changed).
      const helixSet = new Set(partialNucs.map(n => n.helix_id))
      for (const cone of coneEntries) {
        const fn = cone.fromNuc, tn = cone.toNuc
        if (!fn || !helixSet.has(fn.helix_id)) continue
        // Re-derive cone color from the (now-updated) fromNuc strand
        const color = nucColor(fn, stapleColorMap, customColors, loopSet)
        cone.defaultColor = color
        _setInstColor(cone, color)
      }
    },

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
      let cylUpdated = false
      for (const dom of _domainCylData) {
        if (dom.strandId === strandId) {
          dom.defaultColor = hexColor
          iHelixCylinders.setColorAt(dom.cylIdx, _tColor.setHex(hexColor))
          cylUpdated = true
        }
      }
      if (cylUpdated && iHelixCylinders.instanceColor) iHelixCylinders.instanceColor.needsUpdate = true
      let ovhgUpdated = false
      for (const dom of _overhangCylData) {
        if (dom.strandId === strandId) {
          dom.defaultColor = hexColor
          iOverhangCylinders.setColorAt(dom.cylIdx, _tColor.setHex(hexColor))
          ovhgUpdated = true
        }
      }
      if (ovhgUpdated && iOverhangCylinders.instanceColor) iOverhangCylinders.instanceColor.needsUpdate = true
      // Curved tube meshes.
      for (const mesh of _curvedCylGroup.children) {
        if (mesh.userData.strandId === strandId) mesh.material.color.setHex(hexColor)
      }
      let curvedUpdated = false
      for (const dom of _curvedDomainCylData) {
        if (dom.strandId === strandId) {
          dom.defaultColor = hexColor
          iCurvedHelixCylinders.setColorAt(dom.cylIdx, _tColor.setHex(hexColor))
          curvedUpdated = true
        }
      }
      if (curvedUpdated && iCurvedHelixCylinders.instanceColor) iCurvedHelixCylinders.instanceColor.needsUpdate = true
      for (const mesh of _curvedOvhgGroup.children) {
        if (mesh.userData.strandId === strandId) mesh.material.color.setHex(hexColor)
      }
      let curvedOvhgUpd = false
      for (const dom of _curvedOvhgCylData) {
        if (dom.strandId === strandId) {
          dom.defaultColor = hexColor
          iCurvedOverhangCylinders.setColorAt(dom.cylIdx, _tColor.setHex(hexColor))
          curvedOvhgUpd = true
        }
      }
      if (curvedOvhgUpd && iCurvedOverhangCylinders.instanceColor) iCurvedOverhangCylinders.instanceColor.needsUpdate = true
    },

    /**
     * Apply a global coloring mode across backbone, slab, cone and cylinder
     * instances.  Re-derives every entry's defaultColor from scratch so that
     * subsequent dim/highlight restores land on the mode-correct colour.
     *
     *   'strand'  — palette/group/custom per strand (the build-time default)
     *   'base'    — A/T/G/C per nucleotide; nucs without a letter fall back to
     *               their strand colour.  Cylinders fall back entirely.
     *   'cluster' — palette per cluster_transforms entry; nucs/cylinders not
     *               covered by any cluster fall back to their strand colour.
     *
     * @param {'strand'|'base'|'cluster'} mode
     * @param {object} design       — current Design (for sequences + clusters)
     * @param {object} effectiveCols — strand_id → hex (strandColors+groups merged)
     * @param {Set<string>} loopSet — circular strand IDs (red overlay in strand)
     */
    applyColoring(mode, design, effectiveCols, loopIds) {
      const m = mode || 'strand'
      const eff = effectiveCols || customColors
      const loop = loopIds instanceof Set ? loopIds : new Set(loopIds ?? [])

      let perNuc = () => null
      let clusterIdxFn = null

      if (m === 'base') {
        const allNucs = backboneEntries.map(e => e.nuc).filter(Boolean)
        const nucLetter = buildNucLetterMap(design, allNucs)
        perNuc = (nuc) => {
          const ch = nucLetter.get(nuc)
          return ch ? BASE_COLORS[ch] : null
        }
      } else if (m === 'cluster') {
        clusterIdxFn = buildClusterLookup(design)
        perNuc = (nuc) => {
          const ci = clusterIdxFn(nuc)
          return ci != null ? STAPLE_PALETTE[ci % STAPLE_PALETTE.length] : null
        }
      }

      const strandHexFor = (sid) => {
        if (sid == null) return C.unassigned
        if (loop.has(sid)) return C.highlight_red
        if (eff[sid] != null) return eff[sid]
        return stapleColorMap.get(sid) ?? C.unassigned
      }
      const strandBeadColor  = (nuc) => {
        if (!nuc?.strand_id) return C.unassigned
        if (nuc.strand_type === 'scaffold') return C.scaffold_backbone
        return strandHexFor(nuc.strand_id)
      }
      const strandSlabColor2 = (nuc) => {
        if (!nuc?.strand_id) return C.unassigned
        if (nuc.strand_type === 'scaffold') return C.scaffold_slab
        return strandHexFor(nuc.strand_id)
      }
      const strandArrowCol2  = (nuc, sid) => {
        const sId = nuc?.strand_id ?? sid
        if (!sId) return C.unassigned
        if (nuc?.strand_type === 'scaffold') return C.scaffold_arrow
        return strandHexFor(sId)
      }

      for (const entry of backboneEntries) {
        const c = perNuc(entry.nuc) ?? strandBeadColor(entry.nuc)
        entry.defaultColor = c
        _setInstColor(entry, c)
      }
      for (const entry of slabEntries) {
        const c = perNuc(entry.nuc) ?? strandSlabColor2(entry.nuc)
        entry.defaultColor = c
        _setInstColor(entry, c)
      }
      for (const entry of coneEntries) {
        const fn = entry.fromNuc
        const c = (fn ? perNuc(fn) : null) ?? strandArrowCol2(fn, entry.strandId)
        entry.defaultColor = c
        _setInstColor(entry, c)
      }

      // Cylinders: skip 'base' (cylinders span multiple bps).  In 'cluster'
      // mode use the cluster lookup keyed by helix+domain; otherwise fall back
      // to the (effective) strand colour.
      const cylColorFor = (dom) => {
        if (clusterIdxFn) {
          const ci = clusterIdxFn({
            helix_id:    dom.helixId,
            strand_id:   dom.strandId,
            domain_index: dom.domainIndex ?? 0,
          })
          if (ci != null) return STAPLE_PALETTE[ci % STAPLE_PALETTE.length]
        }
        return strandHexFor(dom.strandId)
      }

      for (const dom of _domainCylData) {
        const c = cylColorFor(dom)
        dom.defaultColor = c
        iHelixCylinders.setColorAt(dom.cylIdx, _tColor.setHex(c))
      }
      if (iHelixCylinders.instanceColor) iHelixCylinders.instanceColor.needsUpdate = true

      for (const dom of _overhangCylData) {
        const c = cylColorFor(dom)
        dom.defaultColor = c
        iOverhangCylinders.setColorAt(dom.cylIdx, _tColor.setHex(c))
      }
      if (iOverhangCylinders.instanceColor) iOverhangCylinders.instanceColor.needsUpdate = true

      for (const mesh of _curvedCylGroup.children) {
        const ud = mesh.userData ?? {}
        const c = cylColorFor({ helixId: ud.helixId, strandId: ud.strandId, domainIndex: 0 })
        mesh.material.color.setHex(c)
        ud.defaultColor = c
      }
      for (const dom of _curvedDomainCylData) {
        const c = cylColorFor(dom)
        dom.defaultColor = c
        iCurvedHelixCylinders.setColorAt(dom.cylIdx, _tColor.setHex(c))
      }
      if (iCurvedHelixCylinders.instanceColor) iCurvedHelixCylinders.instanceColor.needsUpdate = true

      for (const mesh of _curvedOvhgGroup.children) {
        const ud = mesh.userData ?? {}
        const c = cylColorFor({ helixId: ud.helixId, strandId: ud.strandId, domainIndex: 0 })
        mesh.material.color.setHex(c)
        ud.defaultColor = c
      }
      for (const dom of _curvedOvhgCylData) {
        const c = cylColorFor(dom)
        dom.defaultColor = c
        iCurvedOverhangCylinders.setColorAt(dom.cylIdx, _tColor.setHex(c))
      }
      if (iCurvedOverhangCylinders.instanceColor) iCurvedOverhangCylinders.instanceColor.needsUpdate = true
    },

    /** Look up a backbone entry by "helix_id:bp_index:direction" key (for Fix B part 2). */
    lookupEntry(key) { return _keyToEntry.get(key) ?? null },

    getCylinderMesh() { return iHelixCylinders },
    getOverhangCylinderMesh() { return iOverhangCylinders },
    getCylinderDomainData() { return _domainCylData },
    getOverhangCylinderDomainData() { return _overhangCylData },

    /** Return the _domainCylData entry for a given InstancedMesh instanceId. */
    getCylinderDomainAt(instanceId) { return _domainCylData[instanceId] ?? null },
    /** Return the _overhangCylData entry for a given InstancedMesh instanceId. */
    getOverhangCylinderDomainAt(instanceId) { return _overhangCylData[instanceId] ?? null },

    /**
     * Highlight all cylinders whose strandId is in strandIds (string or array/Set);
     * all other cylinders are left at their defaultColor.
     */
    highlightCylinderStrands(strandIds) {
      const idSet = strandIds instanceof Set ? strandIds : new Set(Array.isArray(strandIds) ? strandIds : [strandIds])
      for (const dom of _domainCylData) {
        const c = idSet.has(dom.strandId) ? 0xffffff : dom.defaultColor
        iHelixCylinders.setColorAt(dom.cylIdx, _tColor.setHex(c))
      }
      if (iHelixCylinders.instanceColor) iHelixCylinders.instanceColor.needsUpdate = true
      for (const dom of _overhangCylData) {
        const c = idSet.has(dom.strandId) ? 0xffffff : dom.defaultColor
        iOverhangCylinders.setColorAt(dom.cylIdx, _tColor.setHex(c))
      }
      if (iOverhangCylinders.instanceColor) iOverhangCylinders.instanceColor.needsUpdate = true
      for (const mesh of _curvedCylGroup.children) {
        const c = idSet.has(mesh.userData.strandId) ? 0xffffff : mesh.material.color.getHex()
        mesh.material.color.setHex(c)
      }
      for (const dom of _curvedDomainCylData) {
        const c = idSet.has(dom.strandId) ? 0xffffff : dom.defaultColor
        iCurvedHelixCylinders.setColorAt(dom.cylIdx, _tColor.setHex(c))
      }
      if (iCurvedHelixCylinders.instanceColor) iCurvedHelixCylinders.instanceColor.needsUpdate = true
      for (const mesh of _curvedOvhgGroup.children) {
        const c = idSet.has(mesh.userData.strandId) ? 0xffffff : mesh.material.color.getHex()
        mesh.material.color.setHex(c)
      }
      for (const dom of _curvedOvhgCylData) {
        const c = idSet.has(dom.strandId) ? 0xffffff : dom.defaultColor
        iCurvedOverhangCylinders.setColorAt(dom.cylIdx, _tColor.setHex(c))
      }
      if (iCurvedOverhangCylinders.instanceColor) iCurvedOverhangCylinders.instanceColor.needsUpdate = true
    },

    /** Restore all cylinders to their default colors. */
    clearCylinderHighlight() {
      for (const dom of _domainCylData) {
        iHelixCylinders.setColorAt(dom.cylIdx, _tColor.setHex(dom.defaultColor))
      }
      if (iHelixCylinders.instanceColor) iHelixCylinders.instanceColor.needsUpdate = true
      for (const dom of _overhangCylData) {
        iOverhangCylinders.setColorAt(dom.cylIdx, _tColor.setHex(dom.defaultColor))
      }
      if (iOverhangCylinders.instanceColor) iOverhangCylinders.instanceColor.needsUpdate = true
      for (const mesh of _curvedCylGroup.children) mesh.material.color.setHex(mesh.userData.defaultColor ?? mesh.material.color.getHex())
      for (const dom of _curvedDomainCylData) {
        iCurvedHelixCylinders.setColorAt(dom.cylIdx, _tColor.setHex(dom.defaultColor))
      }
      if (iCurvedHelixCylinders.instanceColor) iCurvedHelixCylinders.instanceColor.needsUpdate = true
      for (const mesh of _curvedOvhgGroup.children) mesh.material.color.setHex(mesh.userData.defaultColor ?? mesh.material.color.getHex())
      for (const dom of _curvedOvhgCylData) {
        iCurvedOverhangCylinders.setColorAt(dom.cylIdx, _tColor.setHex(dom.defaultColor))
      }
      if (iCurvedOverhangCylinders.instanceColor) iCurvedOverhangCylinders.instanceColor.needsUpdate = true
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
      for (const arrow of axisArrows) {
        if (arrow.isCurved) {
          const m = arrow.shaft?.material
          if (m) { m.color.setHex(color); m.opacity = 1.0; m.transparent = false }
        } else {
          for (const seg of arrow.segments ?? []) {
            seg.mesh.scale.set(scaleXZ, 1, scaleXZ)
            const m = seg.mesh.material
            if (m) { m.color.setHex(color); m.opacity = 1.0; m.transparent = false }
          }
        }
      }
    },

    getDistLabelInfo() { return distLabelInfo },

    applyPhysicsPositions,
    revertToGeometry,
    applyUnfoldOffsets,

    /**
     * Returns a snapshot of every backbone bead's current rendered position,
     * keyed by "helix_id:bp_index:direction".  Used by cadnano_view to capture
     * the unfold-layout positions before starting the cadnano lerp animation.
     * @returns {Map<string, THREE.Vector3>}
     */
    snapshotPositions() {
      const map = new Map()
      for (const entry of backboneEntries) {
        if (entry.nuc.helix_id.startsWith('__ext_')) continue
        const key = `${entry.nuc.helix_id}:${entry.nuc.bp_index}:${entry.nuc.direction}`
        map.set(key, entry.pos.clone())
      }
      return map
    },

    /**
     * Lerp bead positions from unfold-layout positions toward cadnano flat
     * two-track positions.  Called by cadnano_view on each animation frame.
     *
     * @param {Map<string, THREE.Vector3>} cadnanoPosMap
     *   Target positions keyed by "helix_id:bp_index:direction".
     * @param {number} t  Lerp factor [0, 1]; 0 = unfold layout, 1 = cadnano flat.
     * @param {Map<string, THREE.Vector3>} unfoldPosMap
     *   Current positions at t=0 (unfold layout), same key format.
     *   Typically the cadnano_view's snapshot of entry.pos at unfold-activation time.
     */
    applyCadnanoPositions(cadnanoPosMap, t, unfoldPosMap) {
      // 1. Backbone beads.
      for (const entry of backboneEntries) {
        if (entry.nuc.helix_id.startsWith('__ext_')) continue
        const key = `${entry.nuc.helix_id}:${entry.nuc.bp_index}:${entry.nuc.direction}`
        const cp = cadnanoPosMap.get(key)
        const up = unfoldPosMap.get(key)
        if (!cp || !up) continue

        entry.pos.set(
          up.x + (cp.x - up.x) * t,
          up.y + (cp.y - up.y) * t,
          up.z + (cp.z - up.z) * t,
        )
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
      }
      iSpheres.instanceMatrix.needsUpdate = true
      iCubes.instanceMatrix.needsUpdate   = true

      // 2. Cones — cross-helix cones remain hidden (same as unfold mode).
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

        const r = isCrossHelix ? 0 : cone.coneRadius
        _tMatrix.compose(cone.midPos, cone.quat, _tScale.set(r, h, r))
        iCones.setMatrixAt(cone.id, _tMatrix)
      }
      iCones.instanceMatrix.needsUpdate = true

      // 3. Slabs — hide in cadnano mode (beads are flat, orientation meaningless).
      for (const slab of slabEntries) {
        _tMatrix.compose(_tPos.set(0, 0, 0), ID_QUAT, _tScale.set(0, 0, 0))
        iSlabs.setMatrixAt(slab.id, _tMatrix)
      }
      iSlabs.instanceMatrix.needsUpdate = true
    },

    /**
     * Apply FEM equilibrium-shape displacements.
     * Accepts the same array format as applyPhysicsPositions.
     * @param {Array<{helix_id, bp_index, direction, backbone_position}>} updates
     */
    applyFemPositions(updates, amp = 1.0) {
      if (!updates) { revertToGeometry(); return }

      // 1. Backbone beads — optionally amplify displacement from equilibrium.
      // Build helix-endpoint sample map: first and last bp_index per helix, up to 3 helices.
      const _helixSamples = new Map()   // helix_id → {first, last} entries for logging
      const _samples = []
      let _maxDelta = 0

      for (let _i = 0; _i < updates.length; _i++) {
        const upd   = updates[_i]
        const entry = _keyToEntry.get(`${upd.helix_id}:${upd.bp_index}:${upd.direction}`)
        if (!entry) continue
        const bp = upd.backbone_position
        const eq = entry.nuc.backbone_position
        if (amp === 1.0) {
          entry.pos.set(bp[0], bp[1], bp[2])
        } else {
          entry.pos.set(
            eq[0] + amp * (bp[0] - eq[0]),
            eq[1] + amp * (bp[1] - eq[1]),
            eq[2] + amp * (bp[2] - eq[2]),
          )
        }
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)

        const dx = bp[0]-eq[0], dy = bp[1]-eq[1], dz = bp[2]-eq[2]
        const mag = Math.hypot(dx, dy, dz)
        if (mag > _maxDelta) _maxDelta = mag

        // Track first/last bead of each helix for up to 3 helices
        if (_helixSamples.size < 3 || _helixSamples.has(upd.helix_id)) {
          let hs = _helixSamples.get(upd.helix_id)
          if (!hs) { hs = { first: null, last: null }; _helixSamples.set(upd.helix_id, hs) }
          const snap = { hid: upd.helix_id, bp: upd.bp_index, dir: upd.direction.slice(0,3),
                         mdx: bp[0], mdy: bp[1], mdz: bp[2],
                         eqx: eq[0], eqy: eq[1], eqz: eq[2],
                         dx, dy, dz, mag }
          if (!hs.first) hs.first = snap
          hs.last = snap
        }
      }

      for (const [hid, hs] of _helixSamples) {
        const fmt = (s) => `bp${s.bp}:${s.dir}  md=(${s.mdx.toFixed(3)},${s.mdy.toFixed(3)},${s.mdz.toFixed(3)})  eq=(${s.eqx.toFixed(3)},${s.eqy.toFixed(3)},${s.eqz.toFixed(3)})  Δ=(${s.dx.toFixed(3)},${s.dy.toFixed(3)},${s.dz.toFixed(3)}) |Δ|=${s.mag.toFixed(3)} nm`
        _samples.push(`  ${hid}  ${fmt(hs.first)}`)
        if (hs.last !== hs.first) _samples.push(`  ${hid}  ${fmt(hs.last)}`)
      }
      console.log(`[applyFem] ${new Date().toLocaleTimeString()} amp=${amp}× maxΔ=${_maxDelta.toFixed(3)} nm\n` + _samples.join('\n'))
      iSpheres.instanceMatrix.needsUpdate = true
      iCubes.instanceMatrix.needsUpdate   = true

      // 2. Cones — derived from updated backbone positions.
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

      // 3. Slabs — move centers with backbone; update orientation when base normals provided.
      // Base normals come from the P→C1' intra-residue vector computed on the backend.
      // Uses module-level scratch: _slabBnS (MD bnDir), _slabAxisDir (tanDir), _slabTanS
      // (tangential = tanDir×bnDir), _slabBasis, _slabQuatS.  No heap allocation per frame.
      const hasNormals = updates.length > 0 && updates[0].nx !== undefined
      let normalMap = null
      if (hasNormals) {
        normalMap = new Map()
        for (const upd of updates) {
          if (upd.nx !== undefined)
            normalMap.set(`${upd.helix_id}:${upd.bp_index}:${upd.direction}`, upd)
        }
      }
      for (const slab of slabEntries) {
        const entry = _nucToEntry.get(slab.nuc)
        if (!entry) continue
        slab.bbPos.copy(entry.pos)
        if (normalMap) {
          const key = `${slab.nuc.helix_id}:${slab.nuc.bp_index}:${slab.nuc.direction}`
          const upd = normalMap.get(key)
          if (upd) {
            _slabBnS.set(upd.nx, upd.ny, upd.nz)
            _slabAxisDir.set(...slab.nuc.axis_tangent)            // design helix tangent
            _slabTanS.crossVectors(_slabAxisDir, _slabBnS).normalize()  // tangential
            _slabBasis.makeBasis(_slabTanS, _slabAxisDir, _slabBnS)
            _slabQuatS.setFromRotationMatrix(_slabBasis)
            const center = slabCenter(slab.bbPos, _slabBnS, slabParams.distance)
            _tMatrix.compose(center, _slabQuatS, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
          } else {
            const center = slabCenter(slab.bbPos, slab.bnDir, slabParams.distance)
            _tMatrix.compose(center, slab.quat, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
          }
        } else {
          const center = slabCenter(slab.bbPos, slab.bnDir, slabParams.distance)
          _tMatrix.compose(center, slab.quat, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
        }
        iSlabs.setMatrixAt(slab.id, _tMatrix)
      }
      iSlabs.instanceMatrix.needsUpdate = true
    },

    /**
     * Colour backbone beads and slabs by RMSF value.
     * @param {Object} rmsfMap  key → float 0-1 (stiff→flexible)
     */
    applyFemRmsf(rmsfMap) {
      // Blue(stiff) → green → yellow → red(flexible)
      function _rmsfColor(v) {
        const t = Math.max(0, Math.min(1, v))
        if (t < 0.333) {
          // blue → green
          const s = t / 0.333
          const r = Math.round((1 - s) * 0x29)
          const g = Math.round(s * 0xe6)
          const b = Math.round((1 - s) * 0xff)
          return (r << 16) | (g << 8) | b
        } else if (t < 0.667) {
          // green → yellow
          const s = (t - 0.333) / 0.334
          const r = Math.round(s * 0xff)
          const g = 0xe6
          const b = 0
          return (r << 16) | (g << 8) | b
        } else {
          // yellow → red
          const s = (t - 0.667) / 0.333
          const r = 0xff
          const g = Math.round((1 - s) * 0xe6)
          return (r << 16) | (g << 8) | 0
        }
      }
      for (const entry of backboneEntries) {
        const key = `${entry.nuc.helix_id}:${entry.nuc.bp_index}:${entry.nuc.direction}`
        const val = rmsfMap[key]
        if (val !== undefined) _setInstColor(entry, _rmsfColor(val))
      }
      if (iSpheres.instanceColor) iSpheres.instanceColor.needsUpdate = true
      if (iCubes.instanceColor)   iCubes.instanceColor.needsUpdate   = true
      for (const entry of slabEntries) {
        const key = `${entry.nuc.helix_id}:${entry.nuc.bp_index}:${entry.nuc.direction}`
        const val = rmsfMap[key]
        if (val !== undefined) _setInstColor(entry, _rmsfColor(val))
      }
      if (iSlabs.instanceColor) iSlabs.instanceColor.needsUpdate = true
    },

    /** Restore all colours to their pre-FEM defaults. */
    clearFemColors() {
      for (const entry of backboneEntries) _setInstColor(entry, entry.defaultColor)
      if (iSpheres.instanceColor) iSpheres.instanceColor.needsUpdate = true
      if (iCubes.instanceColor)   iCubes.instanceColor.needsUpdate   = true
      for (const entry of slabEntries) _setInstColor(entry, entry.defaultColor)
      if (iSlabs.instanceColor) iSlabs.instanceColor.needsUpdate = true
    },

    /**
     * Switch rendering detail level for LOD (Level of Detail).
     *   0 = Full         — all geometry visible
     *   1 = Beads-only   — slabs hidden (cheaper)
     *   2 = Cylinders    — one cylinder per helix, all bead geometry hidden
     */
    setDetailLevel(level) {
      if (level === _detailLevel) return
      _detailLevel = level
      const coarse = level === 2
      iSpheres.visible        = !coarse
      iCubes.visible          = !coarse
      iCones.visible          = !coarse
      iSlabs.visible          = level === 0
      iFluoros.visible           = !coarse
      iHelixCylinders.visible          = coarse
      iOverhangCylinders.visible       = coarse
      iCurvedHelixCylinders.visible    = coarse
      _curvedCylGroup.visible          = coarse
      iCurvedOverhangCylinders.visible = coarse
      _curvedOvhgGroup.visible         = coarse
      const showArrows = !coarse && _axisArrowsVisible
      for (const arrow of axisArrows) {
        if (arrow.shaft) arrow.shaft.visible = showArrows
        if (arrow.straightShaft) arrow.straightShaft.visible = showArrows
        for (const seg of arrow.segments ?? []) seg.mesh.visible = showArrows
      }
    },

    /**
     * Lerp all geometry from straight positions to deformed positions.
     *
     * @param {Map<string, THREE.Vector3>} straightPosMap
     *   Key: "helix_id:bp_index:direction" → straight backbone position (t=0 anchor).
     * @param {Map<string, {start:THREE.Vector3, end:THREE.Vector3}>} straightAxesMap
     *   Key: helix_id → straight axis start/end (t=0 anchor for arrows).
     * @param {Map<string, THREE.Vector3>} straightBnMap
     *   Key: "helix_id:bp_index:direction" → straight base_normal (cross-strand unit vector).
     *   Used for slab orientation at t=0; avoids the 30° error from inward-radial approximation.
     * @param {number} t  lerp factor in [0, 1]; 0 = straight, 1 = deformed
     */
    applyDeformLerp(straightPosMap, straightAxesMap, straightBnMap, t) {
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
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
      }
      iSpheres.instanceMatrix.needsUpdate = true
      iCubes.instanceMatrix.needsUpdate   = true

      // 2. Cones — direction from the current lerped bead positions (already updated in step 1).
      //    Using fe.pos/te.pos is correct for both cluster rotations (rigid body — all beads
      //    moved together, so bead-to-bead direction is accurate) and XPBD deformations
      //    (shows the actual bent path).  Mixing pre-rotation straight positions with
      //    post-rotation bead positions (the old approach) caused mismatched midPos at t=1.
      for (const cone of coneEntries) {
        const fe = _nucToEntry.get(cone.fromNuc)
        const te = _nucToEntry.get(cone.toNuc)
        if (!fe || !te) continue
        _physDir.copy(te.pos).sub(fe.pos)
        const dist = _physDir.length()
        const h    = Math.max(0.001, dist)
        _physDir.divideScalar(dist || 1)
        cone.quat.setFromUnitVectors(Y_HAT, _physDir)
        cone.coneHeight = h
        cone.midPos.copy(fe.pos).addScaledVector(_physDir, dist * 0.5)
        _tMatrix.compose(cone.midPos, cone.quat, _tScale.set(cone.coneRadius, cone.coneHeight, cone.coneRadius))
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
          _slabAxisDir.copy(sa.end).sub(sa.start).normalize()
          // Use the straight base_normal (cross-strand) from the straight geometry map when
          // available.  Falling back to the inward-radial (axis_projection − sp) is 30° wrong
          // for B-DNA with a 120° minor groove angle.
          const sbn = straightBnMap?.get(key)
          if (sbn) {
            _slabBnS.copy(sbn)
          } else {
            const axisProj = (sp.x - sa.start.x) * _slabAxisDir.x
                           + (sp.y - sa.start.y) * _slabAxisDir.y
                           + (sp.z - sa.start.z) * _slabAxisDir.z
            _slabProj.copy(sa.start).addScaledVector(_slabAxisDir, axisProj)
            _slabBnS.copy(_slabProj).sub(sp).normalize()
          }

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

      // 4. Axis sticks — lerp from straight (sa) to deformed (arrow.aStart/aEnd).
      for (const arrow of axisArrows) {
        const sa  = straightAxesMap?.get(arrow.helixId)
        const sx0 = sa ? sa.start.x + (arrow.aStart.x - sa.start.x) * t : arrow.aStart.x
        const sy0 = sa ? sa.start.y + (arrow.aStart.y - sa.start.y) * t : arrow.aStart.y
        const sz0 = sa ? sa.start.z + (arrow.aStart.z - sa.start.z) * t : arrow.aStart.z
        const sx1 = sa ? sa.end.x   + (arrow.aEnd.x   - sa.end.x)   * t : arrow.aEnd.x
        const sy1 = sa ? sa.end.y   + (arrow.aEnd.y   - sa.end.y)   * t : arrow.aEnd.y
        const sz1 = sa ? sa.end.z   + (arrow.aEnd.z   - sa.end.z)   * t : arrow.aEnd.z

        if (arrow.isCurved) {
          const mat = arrow.shaft?.material
          if (mat) { mat.transparent = true; mat.opacity = t }
          if (arrow.straightShaft && sa) {
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
            }
          }
        } else {
          // Straight: lay segments along the lerped axis line.
          _physDir.set(sx0, sy0, sz0)
          _physDir2.set(sx1, sy1, sz1)
          _layStraightSegments(arrow, _physDir, _physDir2)
        }
      }

      // 5. Straight-helix domain cylinders (LOD) — follow lerped axis endpoints.
      for (const dom of _domainCylData) {
        const sa  = straightAxesMap?.get(dom.helixId)
        const lx0 = sa ? sa.start.x + (dom.arrow.aStart.x - sa.start.x) * t : dom.arrow.aStart.x
        const ly0 = sa ? sa.start.y + (dom.arrow.aStart.y - sa.start.y) * t : dom.arrow.aStart.y
        const lz0 = sa ? sa.start.z + (dom.arrow.aStart.z - sa.start.z) * t : dom.arrow.aStart.z
        const lx1 = sa ? sa.end.x   + (dom.arrow.aEnd.x   - sa.end.x)   * t : dom.arrow.aEnd.x
        const ly1 = sa ? sa.end.y   + (dom.arrow.aEnd.y   - sa.end.y)   * t : dom.arrow.aEnd.y
        const lz1 = sa ? sa.end.z   + (dom.arrow.aEnd.z   - sa.end.z)   * t : dom.arrow.aEnd.z
        const d0x = lx0 + (lx1 - lx0) * dom.t0, d0y = ly0 + (ly1 - ly0) * dom.t0, d0z = lz0 + (lz1 - lz0) * dom.t0
        const d1x = lx0 + (lx1 - lx0) * dom.t1, d1y = ly0 + (ly1 - ly0) * dom.t1, d1z = lz0 + (lz1 - lz0) * dom.t1
        _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
        _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
        const cLen = _physDir.length()
        if (cLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cLen))
        else _cylQ.identity()
        _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cLen, _cylRadiusScale))
        iHelixCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
      }
      iHelixCylinders.instanceMatrix.needsUpdate = true

      // 5b. Straight-helix overhang cylinders (LOD) — same approach.
      for (const dom of _overhangCylData) {
        const sa  = straightAxesMap?.get(dom.helixId)
        const lx0 = sa ? sa.start.x + (dom.arrow.aStart.x - sa.start.x) * t : dom.arrow.aStart.x
        const ly0 = sa ? sa.start.y + (dom.arrow.aStart.y - sa.start.y) * t : dom.arrow.aStart.y
        const lz0 = sa ? sa.start.z + (dom.arrow.aStart.z - sa.start.z) * t : dom.arrow.aStart.z
        const lx1 = sa ? sa.end.x   + (dom.arrow.aEnd.x   - sa.end.x)   * t : dom.arrow.aEnd.x
        const ly1 = sa ? sa.end.y   + (dom.arrow.aEnd.y   - sa.end.y)   * t : dom.arrow.aEnd.y
        const lz1 = sa ? sa.end.z   + (dom.arrow.aEnd.z   - sa.end.z)   * t : dom.arrow.aEnd.z
        const d0x = lx0 + (lx1 - lx0) * dom.t0, d0y = ly0 + (ly1 - ly0) * dom.t0, d0z = lz0 + (lz1 - lz0) * dom.t0
        const d1x = lx0 + (lx1 - lx0) * dom.t1, d1y = ly0 + (ly1 - ly0) * dom.t1, d1z = lz0 + (lz1 - lz0) * dom.t1
        _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
        _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
        const cLen = _physDir.length()
        if (cLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cLen))
        else _cylQ.identity()
        _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cLen, _cylRadiusScale))
        iOverhangCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
      }
      iOverhangCylinders.instanceMatrix.needsUpdate = true

      // 5c. Curved-helix domain cylinders — proxy follows lerped straight axis; tube opacity = t.
      for (const dom of _curvedDomainCylData) {
        const sa  = straightAxesMap?.get(dom.helixId)
        const lx0 = sa ? sa.start.x + (dom.arrow.aStart.x - sa.start.x) * t : dom.arrow.aStart.x
        const ly0 = sa ? sa.start.y + (dom.arrow.aStart.y - sa.start.y) * t : dom.arrow.aStart.y
        const lz0 = sa ? sa.start.z + (dom.arrow.aStart.z - sa.start.z) * t : dom.arrow.aStart.z
        const lx1 = sa ? sa.end.x   + (dom.arrow.aEnd.x   - sa.end.x)   * t : dom.arrow.aEnd.x
        const ly1 = sa ? sa.end.y   + (dom.arrow.aEnd.y   - sa.end.y)   * t : dom.arrow.aEnd.y
        const lz1 = sa ? sa.end.z   + (dom.arrow.aEnd.z   - sa.end.z)   * t : dom.arrow.aEnd.z
        const d0x = lx0 + (lx1 - lx0) * dom.t0, d0y = ly0 + (ly1 - ly0) * dom.t0, d0z = lz0 + (lz1 - lz0) * dom.t0
        const d1x = lx0 + (lx1 - lx0) * dom.t1, d1y = ly0 + (ly1 - ly0) * dom.t1, d1z = lz0 + (lz1 - lz0) * dom.t1
        _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
        _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
        const cLen = _physDir.length()
        if (cLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cLen))
        else _cylQ.identity()
        _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cLen, _cylRadiusScale))
        iCurvedHelixCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
      }
      iCurvedHelixCylinders.instanceMatrix.needsUpdate = true
      iCurvedHelixCylinders.material.opacity = 1 - t
      for (const mesh of _curvedCylGroup.children)   mesh.material.opacity = t
      for (const dom of _curvedOvhgCylData) {
        const sa  = straightAxesMap?.get(dom.helixId)
        const lx0 = sa ? sa.start.x + (dom.arrow.aStart.x - sa.start.x) * t : dom.arrow.aStart.x
        const ly0 = sa ? sa.start.y + (dom.arrow.aStart.y - sa.start.y) * t : dom.arrow.aStart.y
        const lz0 = sa ? sa.start.z + (dom.arrow.aStart.z - sa.start.z) * t : dom.arrow.aStart.z
        const lx1 = sa ? sa.end.x   + (dom.arrow.aEnd.x   - sa.end.x)   * t : dom.arrow.aEnd.x
        const ly1 = sa ? sa.end.y   + (dom.arrow.aEnd.y   - sa.end.y)   * t : dom.arrow.aEnd.y
        const lz1 = sa ? sa.end.z   + (dom.arrow.aEnd.z   - sa.end.z)   * t : dom.arrow.aEnd.z
        const d0x = lx0 + (lx1 - lx0) * dom.t0, d0y = ly0 + (ly1 - ly0) * dom.t0, d0z = lz0 + (lz1 - lz0) * dom.t0
        const d1x = lx0 + (lx1 - lx0) * dom.t1, d1y = ly0 + (ly1 - ly0) * dom.t1, d1z = lz0 + (lz1 - lz0) * dom.t1
        _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
        _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
        const cLen = _physDir.length()
        if (cLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cLen))
        else _cylQ.identity()
        _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cLen, _cylRadiusScale))
        iCurvedOverhangCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
      }
      iCurvedOverhangCylinders.instanceMatrix.needsUpdate = true
      iCurvedOverhangCylinders.material.opacity = 1 - t
      for (const mesh of _curvedOvhgGroup.children)  mesh.material.opacity = t
    },

    /**
     * Lerp all geometry between two arbitrary world-space position states.
     * Unlike applyDeformLerp, both endpoints are explicit Maps — no reference
     * to nuc.backbone_position or internal straight maps.  Used by the animation
     * player to smoothly transition between pre-baked keyframe geometry states.
     *
     * BakedGeometry shape (both fromBaked and toBaked):
     *   { posMap:  Map<"hid:bp:dir", THREE.Vector3>,
     *     axesMap: Map<helix_id, {start, end}>,
     *     bnMap:   Map<"hid:bp:dir", THREE.Vector3> }
     *
     * @param {object} fromBaked  — geometry state at t=0
     * @param {object} toBaked    — geometry state at t=1
     * @param {number} t          — lerp factor in [0, 1]
     */
    applyPositionLerp(fromBaked, toBaked, t, excludeHelixIds = null, fadeOpts = null) {
      if (!fromBaked || !toBaked) return
      const { posMap: fromPosMap, axesMap: fromAxesMap, bnMap: fromBnMap } = fromBaked
      const { posMap: toPosMap,   axesMap: toAxesMap,   bnMap: toBnMap   } = toBaked

      // Helper: returns true if this helix belongs to an excluded (rigid-body) cluster.
      // Handles both real helix IDs and __ext_ extension helices via _extToRealHelix.
      const _isExcluded = excludeHelixIds
        ? (hid) => {
            if (excludeHelixIds.has(hid)) return true
            if (hid.startsWith('__ext_')) {
              const parent = _extToRealHelix.get(hid.slice('__ext_'.length))
              if (parent && excludeHelixIds.has(parent)) return true
            }
            return false
          }
        : () => false

      // ── Per-element fade for "this is how I made this" reveal ────────────
      // fadeOpts: { revealInStrandIds, revealOutStrandIds, revealInHelixIds, revealOutHelixIds }
      // Returns scale-multiplier in [0, 1]:
      //   1.0 → element exists in BOTH from and to (full visible throughout)
      //     t → element only in to-state ("revealing in" — grows from 0 to 1)
      // 1 - t → element only in from-state ("fading out" — shrinks from 1 to 0)
      // Scale-based fade keeps positions intact; instance just shrinks to a
      // point when invisible. Cheap (no shader / per-instance opacity needed).
      const _strandFade = fadeOpts
        ? (sid) => {
            if (!sid) return 1
            if (fadeOpts.revealInStrandIds?.has(sid))  return t
            if (fadeOpts.revealOutStrandIds?.has(sid)) return 1 - t
            return 1
          }
        : () => 1
      const _helixFade = fadeOpts
        ? (hid) => {
            if (!hid) return 1
            if (fadeOpts.revealInHelixIds?.has(hid))  return t
            if (fadeOpts.revealOutHelixIds?.has(hid)) return 1 - t
            return 1
          }
        : () => 1

      // 1. Backbone beads
      // Position lerp is skipped for helices owned by rigid-body cluster
      // transforms (applyClusterTransform handles those). But the FADE scale
      // must still apply to those beads — otherwise default-cluster designs
      // (where every helix belongs to "Cluster 1") never see the fade.
      //
      // PER-NUCLEOTIDE fade granularity: a nucleotide is "new" iff its
      // (helix_id, bp_index, direction) key isn't in fromPosMap. This catches
      // extension-of-existing-strand cases (continuation extrudes) where the
      // strand_id stays the same but new bps appear — per-strand fade alone
      // would miss those and pop them in at t=0. Per-helix is similarly too
      // coarse: a helix that's extended in bp range stays the same helix_id.
      for (const entry of backboneEntries) {
        const isExcluded = _isExcluded(entry.nuc.helix_id)
        const key = `${entry.nuc.helix_id}:${entry.nuc.bp_index}:${entry.nuc.direction}`
        const fp  = fromPosMap?.get(key)
        const tp  = toPosMap?.get(key)

        if (!isExcluded) {
          if (fp && tp) {
            entry.pos.lerpVectors(fp, tp, t)
          } else if (tp) {
            entry.pos.copy(tp)
          } else if (fp) {
            entry.pos.copy(fp)
          }
        }
        // Per-nuc fade from posMap presence:
        //   both       → 1   (existed throughout)
        //   to-only    → t   (new in to-state, fade in)
        //   from-only  → 1-t (removed in to-state, fade out)
        let fade
        if (fp && tp)       fade = 1
        else if (tp)        fade = t
        else if (fp)        fade = 1 - t
        else                fade = 0   // defensive — bead exists in scene but neither baked
        if (isExcluded && fade === 1) continue   // applyClusterTransform already set the matrix
        const s = _beadScale * fade
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(s, s, s))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
      }
      iSpheres.instanceMatrix.needsUpdate = true
      iCubes.instanceMatrix.needsUpdate   = true

      // 2. Cones — per-nucleotide fade based on both endpoint nucs' presence
      // in fromPosMap / toPosMap. A cone exists iff both of its endpoint
      // nucleotides exist; if either endpoint is missing in a side, the cone
      // is missing on that side too. For cluster-owned helices,
      // applyClusterTransform already wrote the matrix; we re-write only
      // when fade != 1.
      for (const cone of coneEntries) {
        const isExcluded = _isExcluded(cone.fromNuc.helix_id) || _isExcluded(cone.toNuc.helix_id)
        const fromKey = `${cone.fromNuc.helix_id}:${cone.fromNuc.bp_index}:${cone.fromNuc.direction}`
        const toKey   = `${cone.toNuc.helix_id}:${cone.toNuc.bp_index}:${cone.toNuc.direction}`
        const fp_f    = fromPosMap?.get(fromKey)
        const fp_t    = fromPosMap?.get(toKey)
        const tp_f    = toPosMap?.get(fromKey)
        const tp_t    = toPosMap?.get(toKey)
        const existedBefore = !!(fp_f && fp_t)
        const existsAfter   = !!(tp_f && tp_t)
        let coneFade
        if (existedBefore && existsAfter)       coneFade = 1
        else if (existsAfter)                   coneFade = t
        else if (existedBefore)                 coneFade = 1 - t
        else                                    coneFade = 0
        if (isExcluded && coneFade === 1) continue   // cluster transform already wrote the matrix

        const fe = _nucToEntry.get(cone.fromNuc)
        const te = _nucToEntry.get(cone.toNuc)
        if (!fe || !te) continue

        if (!isExcluded) {
          // Prefer fromPosMap endpoints when both exist (gives a smooth lerp
          // anchor); otherwise use entry.pos which already holds the lerped
          // or copied per-nuc position from the bead pass above.
          if (fp_f && fp_t) {
            _physDir.copy(fp_t).sub(fp_f)
          } else {
            _physDir.copy(te.pos).sub(fe.pos)
          }
          const dist = _physDir.length()
          const h    = Math.max(0.001, dist)
          _physDir.divideScalar(dist || 1)
          cone.quat.setFromUnitVectors(Y_HAT, _physDir)
          cone.coneHeight = h
          cone.midPos.copy(fe.pos).addScaledVector(_physDir, dist * 0.5)
        }
        // For excluded entries, cone.midPos / cone.quat / cone.coneHeight
        // already reflect the cluster-transformed positions from
        // applyClusterTransform; we just override scale to apply the fade.
        _tMatrix.compose(
          cone.midPos, cone.quat,
          _tScale.set(cone.coneRadius * coneFade, cone.coneHeight * coneFade, cone.coneRadius * coneFade),
        )
        iCones.setMatrixAt(cone.id, _tMatrix)
      }
      iCones.instanceMatrix.needsUpdate = true

      // 3. Slabs — per-nucleotide fade (same granularity as beads). Slab
      // presence in fromBnMap / toBnMap mirrors the bead's posMap presence.
      // For cluster-owned helices, applyClusterTransform already wrote the
      // matrix; we re-write only when fade != 1.
      for (const slab of slabEntries) {
        const isExcluded = _isExcluded(slab.nuc.helix_id)
        const key = `${slab.nuc.helix_id}:${slab.nuc.bp_index}:${slab.nuc.direction}`
        const fbn = fromBnMap?.get(key)
        const tbn = toBnMap?.get(key)
        let slabFade
        if (fbn && tbn)      slabFade = 1
        else if (tbn)        slabFade = t
        else if (fbn)        slabFade = 1 - t
        else                 slabFade = 0
        if (isExcluded && slabFade === 1) continue

        const entry = _nucToEntry.get(slab.nuc)
        if (!entry) continue
        slab.bbPos.copy(entry.pos)

        if (!isExcluded) {
          if (fbn && tbn) {
            _slabBnS.lerpVectors(fbn, tbn, t).normalize()
            // Approximate axis dir from lerped helix endpoints
            const fa = fromAxesMap?.get(slab.nuc.helix_id)
            const ta = toAxesMap?.get(slab.nuc.helix_id)
            if (fa && ta) {
              _physDir.lerpVectors(fa.end, ta.end, t)
              _physDir2.lerpVectors(fa.start, ta.start, t)
              _slabAxisDir.copy(_physDir).sub(_physDir2).normalize()
            } else {
              _slabAxisDir.set(0, 1, 0)
            }
            _slabTanS.crossVectors(_slabAxisDir, _slabBnS).normalize()
            _slabBasis.makeBasis(_slabTanS, _slabAxisDir, _slabBnS)
            slab.bnDir.copy(_slabBnS)
            slab.quat.setFromRotationMatrix(_slabBasis)
          }
        }
        const center_ = slabCenter(slab.bbPos, slab.bnDir, slabParams.distance)
        _tMatrix.compose(
          center_, slab.quat,
          _tScale.set(slabParams.length * slabFade, slabParams.width * slabFade, slabParams.thickness * slabFade),
        )
        iSlabs.setMatrixAt(slab.id, _tMatrix)
      }
      iSlabs.instanceMatrix.needsUpdate = true

      // 4. Axis sticks — lerp from "from" axes (fa) to "to" axes (ta).
      // Per-domain fade: each segment's bp range [bp_lo, bp_hi] is checked
      // against the from/to posMaps for its helix. A segment is "present"
      // on a side iff at least one bp in its range exists in that posMap.
      // This matches the bead/slab/cone treatment and lets a helix carrying
      // both a pre-existing and a freshly-extruded domain fade in only the
      // new domain's axis stick.
      const _bpSetByHelix = (posMap) => {
        const m = new Map()
        if (!posMap) return m
        for (const key of posMap.keys()) {
          const lastColon = key.lastIndexOf(':')
          const midColon  = key.lastIndexOf(':', lastColon - 1)
          if (midColon < 0) continue
          const hid = key.slice(0, midColon)
          const bp  = +key.slice(midColon + 1, lastColon)
          let s = m.get(hid)
          if (!s) { s = new Set(); m.set(hid, s) }
          s.add(bp)
        }
        return m
      }
      const _fromBpsByHelix = _bpSetByHelix(fromPosMap)
      const _toBpsByHelix   = _bpSetByHelix(toPosMap)
      const _segCovers = (bpSetByHelix, helixId, bp_lo, bp_hi) => {
        const s = bpSetByHelix.get(helixId)
        if (!s) return false
        for (let bp = bp_lo; bp <= bp_hi; bp++) if (s.has(bp)) return true
        return false
      }
      const _segFadeFor = (helixId, bp_lo, bp_hi) => {
        const before = _segCovers(_fromBpsByHelix, helixId, bp_lo, bp_hi)
        const after  = _segCovers(_toBpsByHelix,   helixId, bp_lo, bp_hi)
        if (before && after) return 1
        if (after)           return t
        if (before)          return 1 - t
        return 0
      }
      // Returns [lo, hi] of the actual covered bp subrange within [bp_lo, bp_hi]
      // on the given side, or null if no bp in that range is populated. Used
      // to shrink the visible axis stick to match where nucleotides actually
      // exist — finer-grained than per-domain when a single domain spans the
      // whole helix and a continuation extrude has populated only a subrange.
      const _coveredBpRange = (bpSet, bp_lo, bp_hi) => {
        if (!bpSet) return null
        let lo = -1, hi = -1
        for (let bp = bp_lo; bp <= bp_hi; bp++) {
          if (bpSet.has(bp)) {
            if (lo < 0) lo = bp
            hi = bp
          }
        }
        return lo < 0 ? null : [lo, hi]
      }
      // Helix-level presence (any bp in any posMap entry for this helix).
      // Used for curved helices, which have a single shaft tube and can't
      // be split per-domain.
      const _helixPresent = (bpSetByHelix, helixId) => bpSetByHelix.has(helixId)
      const _helixFadeFromBps = (helixId) => {
        const before = _helixPresent(_fromBpsByHelix, helixId)
        const after  = _helixPresent(_toBpsByHelix,   helixId)
        if (before && after) return 1
        if (after)           return t
        if (before)          return 1 - t
        return 0
      }

      for (const arrow of axisArrows) {
        const isExcluded = _isExcluded(arrow.helixId)
        if (!isExcluded) {
          const fa = fromAxesMap?.get(arrow.helixId)
          const ta = toAxesMap?.get(arrow.helixId)
          if (!fa && !ta) {
            // Skip position update; segment scale fade still applies below.
          } else if (!fa || !ta) {
            // Helix only in one of the two states — position from whichever
            // side's axis exists; per-segment scale fade below handles
            // grow/shrink.
            const lone = ta || fa
            arrow.aStart.copy(lone.start)
            arrow.aEnd.copy(lone.end)
            if (arrow.straightShaft) {
              const fadeLone = _helixFadeFromBps(arrow.helixId)
              _physDir.copy(lone.end).sub(lone.start)
              const sLen = _physDir.length()
              if (sLen > 0.001) {
                _physDir.divideScalar(sLen)
                arrow.straightShaft.position.set(
                  (lone.start.x + lone.end.x) * 0.5,
                  (lone.start.y + lone.end.y) * 0.5,
                  (lone.start.z + lone.end.z) * 0.5,
                )
                arrow.straightShaft.quaternion.setFromUnitVectors(Y_HAT, _physDir)
                arrow.straightShaft.scale.set(fadeLone, sLen * fadeLone, fadeLone)
              }
            } else {
              _layStraightSegments(arrow, lone.start, lone.end)
            }
          } else {
            const sx0 = fa.start.x + (ta.start.x - fa.start.x) * t
            const sy0 = fa.start.y + (ta.start.y - fa.start.y) * t
            const sz0 = fa.start.z + (ta.start.z - fa.start.z) * t
            const sx1 = fa.end.x   + (ta.end.x   - fa.end.x)   * t
            const sy1 = fa.end.y   + (ta.end.y   - fa.end.y)   * t
            const sz1 = fa.end.z   + (ta.end.z   - fa.end.z)   * t
            arrow.aStart.set(sx0, sy0, sz0)
            arrow.aEnd.set(sx1, sy1, sz1)
            if (arrow.isCurved) {
              const mat = arrow.shaft?.material
              if (mat) { mat.transparent = true; mat.opacity = t }
              if (arrow.straightShaft) {
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
                }
              }
            } else {
              _physDir.set(sx0, sy0, sz0)
              _physDir2.set(sx1, sy1, sz1)
              _layStraightSegments(arrow, _physDir, _physDir2)
            }
          }
        }

        // Per-bp-range axis-segment recomputation (straight helices). Each
        // segment is positioned + scaled to span the actual covered bp
        // subrange on each side, with endpoints lerped between sides. This
        // overrides anything _layStraightSegments / applyClusterTransform
        // wrote earlier, which assumed the segment spans its full bp range.
        if (!arrow.isCurved && arrow.segments?.length) {
          const fa = fromAxesMap?.get(arrow.helixId)
          const ta = toAxesMap?.get(arrow.helixId)
          const fromBpSet = _fromBpsByHelix.get(arrow.helixId)
          const toBpSet   = _toBpsByHelix.get(arrow.helixId)

          // Helper: project bp [lo, hi+1] onto the axis (start, end). Writes
          // to outStart/outEnd. Uses arrow.bpStart as the bp anchor (assumed
          // common across states; helices don't typically change bp_start).
          const _projectBpRange = (axStart, axEnd, lo, hi, outStart, outEnd) => {
            _physDir.set(axEnd.x - axStart.x, axEnd.y - axStart.y, axEnd.z - axStart.z)
            const aLen = _physDir.length()
            if (aLen < 0.001) { outStart.copy(axStart); outEnd.copy(axStart); return }
            _physDir.divideScalar(aLen)
            const tS = (lo - arrow.bpStart) * BDNA_RISE_PER_BP
            const tE = (hi - arrow.bpStart + 1) * BDNA_RISE_PER_BP
            outStart.copy(axStart).addScaledVector(_physDir, tS)
            outEnd.copy(axStart).addScaledVector(_physDir, tE)
          }

          for (const seg of arrow.segments) {
            const fromRange = _coveredBpRange(fromBpSet, seg.bp_lo, seg.bp_hi)
            const toRange   = _coveredBpRange(toBpSet,   seg.bp_lo, seg.bp_hi)

            if (!fromRange && !toRange) {
              seg.mesh.scale.set(0, 0, 0)
              continue
            }

            // World endpoints of covered subrange on each side (when available).
            let haveFrom = false, haveTo = false
            if (fa && fromRange) {
              _projectBpRange(fa.start, fa.end, fromRange[0], fromRange[1], _segS_from, _segE_from)
              haveFrom = true
            }
            if (ta && toRange) {
              _projectBpRange(ta.start, ta.end, toRange[0], toRange[1], _segS_to, _segE_to)
              haveTo = true
            }

            let segStart, segEnd, fadeXZ
            if (haveFrom && haveTo) {
              _segS.lerpVectors(_segS_from, _segS_to, t)
              _segE.lerpVectors(_segE_from, _segE_to, t)
              segStart = _segS; segEnd = _segE
              fadeXZ = 1
            } else if (haveTo) {
              segStart = _segS_to; segEnd = _segE_to
              fadeXZ = t
            } else if (haveFrom) {
              segStart = _segS_from; segEnd = _segE_from
              fadeXZ = 1 - t
            } else {
              // Coverage exists but no axis on that side — fall back to a
              // pure scale fade using whichever subrange is present, leaving
              // the segment at its current position.
              const f = haveFrom || haveTo ? 1 : 0
              seg.mesh.scale.set(f, f, f)
              continue
            }

            _physDir.set(segEnd.x - segStart.x, segEnd.y - segStart.y, segEnd.z - segStart.z)
            const segLen = _physDir.length()
            if (segLen < 0.001) {
              seg.mesh.scale.set(0, 0, 0)
              continue
            }
            _physDir.divideScalar(segLen)
            seg.mesh.position.set(
              (segStart.x + segEnd.x) * 0.5,
              (segStart.y + segEnd.y) * 0.5,
              (segStart.z + segEnd.z) * 0.5,
            )
            seg.mesh.quaternion.setFromUnitVectors(_AY, _physDir)
            const yScale = segLen / Math.max(0.001, seg.adjLen)
            seg.mesh.scale.set(fadeXZ, yScale * fadeXZ, fadeXZ)
          }
        }
      }

      // 5. Helix shaft cylinders — per-domain fade is more granular than
      // per-helix because a single helix can carry both a scaffold AND a
      // staple domain; an extrude that adds only the scaffold strand should
      // fade in just that domain's cylinder while a pre-existing staple
      // cylinder on the same helix stays solid.
      // For cluster-excluded helices: cluster transform already wrote the
      // matrix, so we only re-write when fade != 1.
      const _writeCylMatrix = (dom, mesh, fade) => {
        const s = dom.arrow.aStart, e = dom.arrow.aEnd
        const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
        const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
        _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
        _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
        const cylLen = _physDir.length()
        if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
        else _cylQ.identity()
        const r = _cylRadiusScale * fade
        _tMatrix.compose(_tPos, _cylQ, _tScale.set(r, cylLen * fade, r))
        mesh.setMatrixAt(dom.cylIdx, _tMatrix)
      }
      const _processCylArr = (arr, mesh) => {
        let touched = false
        for (const dom of arr) {
          const isExcluded = _isExcluded(dom.helixId)
          // Per-domain fade based on bp range coverage in fromPosMap/toPosMap.
          // Falls back to strand+helix fade only when bp_lo/bp_hi aren't
          // available (legacy code paths).
          const fade = (dom.bp_lo != null && dom.bp_hi != null)
            ? _segFadeFor(dom.helixId, dom.bp_lo, dom.bp_hi)
            : Math.min(_strandFade(dom.strandId), _helixFade(dom.helixId))
          if (isExcluded && fade === 1) continue   // cluster transform already wrote the matrix
          _writeCylMatrix(dom, mesh, fade)
          touched = true
        }
        if (touched) mesh.instanceMatrix.needsUpdate = true
      }
      _processCylArr(_domainCylData,       iHelixCylinders)
      _processCylArr(_overhangCylData,     iOverhangCylinders)
      _processCylArr(_curvedDomainCylData, iCurvedHelixCylinders)
      _processCylArr(_curvedOvhgCylData,   iCurvedOverhangCylinders)
    },

    /**
     * Return cross-helix backbone connections at their current world positions.
     * Used by unfold_view.js to build arc overlays for the 3D view.
     */
    getCrossHelixConnections() {
      const conns = []
      // Track cross-helix cone site keys so we can skip crossover records
      // that already have a strand-topology cone (e.g. scaffold routing imports).
      const coneSiteKeys = new Set()

      // Linker strand domain transitions (real OH helix ↔ virtual `__lnk__`
      // helix) are owned by overhang_link_arcs.js, which draws its own
      // anchor → bridge-boundary arc. Skipping them here avoids a duplicate
      // arc per linker side.
      const _isLinkerHelix = (hid) => typeof hid === 'string' && hid.startsWith('__lnk__')

      for (const cone of coneEntries) {
        if (!cone.isCrossHelix) continue
        const fn = cone.fromNuc
        const tn = cone.toNuc
        if (_isLinkerHelix(fn.helix_id) || _isLinkerHelix(tn.helix_id)) continue
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
        const fk = `${fn.helix_id}:${fn.bp_index}:${fn.direction}`
        const tk = `${tn.helix_id}:${tn.bp_index}:${tn.direction}`
        coneSiteKeys.add(`${fk}|${tk}`)
        coneSiteKeys.add(`${tk}|${fk}`)
      }

      // Add connections for crossover records not already covered by strand
      // cones (i.e. crossovers placed without ligation).
      for (const xo of (design.crossovers ?? [])) {
        const ak = `${xo.half_a.helix_id}:${xo.half_a.index}:${xo.half_a.strand}`
        const bk = `${xo.half_b.helix_id}:${xo.half_b.index}:${xo.half_b.strand}`
        if (coneSiteKeys.has(`${ak}|${bk}`)) continue
        if (_isLinkerHelix(xo.half_a.helix_id) || _isLinkerHelix(xo.half_b.helix_id)) continue
        const entryA = _keyToEntry.get(`${xo.half_a.helix_id}:${xo.half_a.index}:${xo.half_a.strand}`)
        const entryB = _keyToEntry.get(`${xo.half_b.helix_id}:${xo.half_b.index}:${xo.half_b.strand}`)
        if (!entryA || !entryB) continue
        const fnuc = entryA.nuc
        const tnuc = entryB.nuc
        const fp = fnuc.backbone_position
        const tp = tnuc.backbone_position
        const color = fnuc.strand_type === 'scaffold'
          ? 0x29b6f6
          : (stapleColorMap.get(fnuc.strand_id) ?? 0x445566)
        conns.push({
          from:        new THREE.Vector3(fp[0], fp[1], fp[2]),
          to:          new THREE.Vector3(tp[0], tp[1], tp[2]),
          color,
          fromHelixId: fnuc.helix_id,
          toHelixId:   tnuc.helix_id,
          strandId:    fnuc.strand_id,
          fromNuc:     fnuc,
          toNuc:       tnuc,
        })
      }

      return conns
    },

    /** Returns the raw axisArrows array for debug hit-testing. */
    getAxisArrows() { return axisArrows },

    /** Show or hide all axis sticks (per-domain segments + curved tube shaft). Persists across LOD changes. */
    setAxisArrowsVisible(visible) {
      _axisArrowsVisible = visible
      for (const arrow of axisArrows) {
        if (arrow.shaft) arrow.shaft.visible = visible
        if (arrow.straightShaft) arrow.straightShaft.visible = visible
        for (const seg of arrow.segments ?? []) seg.mesh.visible = visible
      }
    },

    /**
     * Given a __ext_* synthetic helix ID, return its parent real helix ID.
     * Used by unfold_view.applyClusterArcUpdate to check cluster membership
     * for extension-arc endpoints.
     * Returns null for non-extension helix IDs.
     */
    getExtParentHelixId(extHelixId) {
      if (!extHelixId?.startsWith('__ext_')) return null
      return _extToRealHelix.get(extHelixId.slice('__ext_'.length)) ?? null
    },

    /**
     * Snapshot current rendered positions for the given cluster helices.
     * Must be called once at gizmo attach time, before any drag begins.
     * applyClusterTransform uses these snapshots as the base for incremental transforms,
     * avoiding double-application of already-baked cluster transforms.
     *
     * @param {string[]} helixIds
     */
    captureClusterBase(helixIds, domainIds = null, append = false, { forceAxes = false } = {}) {
      const helixSet = new Set(helixIds)
      const domainKeySet = domainIds?.length
        ? new Set(domainIds.map(d => `${d.strand_id}:${d.domain_index}`))
        : null
      if (!append) {
        _cbEntries.clear()
        _cbSlabs.clear()
        _cbArrows.clear()
        _cbExtEntries.clear()
        _cbFluoEntries.clear()
        _cbOvhgCyls.clear()
        _cbSegments.clear()
      }
      for (const entry of backboneEntries) {
        if (!helixSet.has(entry.nuc.helix_id)) continue
        if (domainKeySet && !domainKeySet.has(`${entry.nuc.strand_id}:${entry.nuc.domain_index}`)) continue
        const key = `${entry.nuc.helix_id}:${entry.nuc.bp_index}:${entry.nuc.direction}`
        _cbEntries.set(key, entry.pos.clone())
      }
      for (const slab of slabEntries) {
        if (!helixSet.has(slab.nuc.helix_id)) continue
        if (domainKeySet && !domainKeySet.has(`${slab.nuc.strand_id}:${slab.nuc.domain_index}`)) continue
        _cbSlabs.set(slab.nuc, { bnDir: slab.bnDir.clone(), quat: slab.quat.clone() })
      }
      // Helix-level axis snapshot (aStart/aEnd + curved-tube transforms). aStart/aEnd
      // are still consumed by overhang half-cylinder math; for partial-coverage clusters
      // they remain anchored to the build-time positions because no domainKeySet match
      // can identify "the helix's overall extent".
      if (!domainKeySet || forceAxes) {
        for (const arrow of axisArrows) {
          if (!helixSet.has(arrow.helixId)) continue
          _cbArrows.set(arrow.helixId, {
            aStart:    arrow.aStart.clone(),
            aEnd:      arrow.aEnd.clone(),
            shaftPos:  arrow.isCurved && arrow.shaft  ? arrow.shaft.position.clone()   : null,
            shaftQuat: arrow.isCurved && arrow.shaft  ? arrow.shaft.quaternion.clone()  : null,
            ssPos:     arrow.isCurved && arrow.straightShaft ? arrow.straightShaft.position.clone()   : null,
            ssQuat:    arrow.isCurved && arrow.straightShaft ? arrow.straightShaft.quaternion.clone()  : null,
          })
        }
        for (const entry of backboneEntries) {
          const nuc = entry.nuc
          if (!nuc.helix_id.startsWith('__ext_')) continue
          const parentHelix = _extToRealHelix.get(nuc.extension_id)
          if (!parentHelix || !helixSet.has(parentHelix)) continue
          _cbExtEntries.set(`${nuc.helix_id}:${nuc.bp_index}`, entry.pos.clone())
        }
        for (const entry of fluoroEntries) {
          const nuc = entry.nuc
          const parentHelix = _extToRealHelix.get(nuc.extension_id)
          if (!parentHelix || !helixSet.has(parentHelix)) continue
          _cbFluoEntries.set(`${nuc.helix_id}:${nuc.bp_index}`, entry.pos.clone())
        }
      }
      // Snapshot overhang cylinder world-space endpoints (shared-stub overhangs only).
      for (const dom of _overhangCylData) {
        if (!dom.wsStart) continue
        if (!helixSet.has(dom.helixId)) continue
        if (domainKeySet && !domainKeySet.has(`${dom.strandId}:${dom.domainIndex}`)) continue
        _cbOvhgCyls.set(dom, { wsStart: dom.wsStart.clone(), wsEnd: dom.wsEnd.clone() })
      }
      // Snapshot per-domain axis segments. Domain filter is enforced per segment so
      // a partial-coverage cluster only captures (and later transforms) segments that
      // belong to it; segments outside the cluster remain anchored to their build-time
      // world-space positions.
      for (const arrow of axisArrows) {
        if (!helixSet.has(arrow.helixId)) continue
        for (const seg of arrow.segments) {
          if (domainKeySet) {
            const k = `${seg.strandId}:${seg.domainIndex}`
            if (!domainKeySet.has(k)) continue
          }
          _cbSegments.set(seg, { wsStart: seg.wsStart.clone(), wsEnd: seg.wsEnd.clone() })
        }
      }
    },

    /**
     * Apply an incremental cluster transform directly to Three.js instance matrices.
     * Called on every gizmo drag event for zero-latency preview.
     *
     * Formula: pos' = R_incr*(base − center) + dummyPos
     * where base = position at captureClusterBase() time, center = dummy position at
     * attach time, dummyPos = current dummy position, R_incr = rotation since attach.
     *
     * This correctly handles re-activation after previous drags because backbone_position
     * in currentGeometry already has the old transform baked in; using the snapshot base
     * instead means the incremental formula never double-applies a prior transform.
     *
     * @param {string[]}         helixIds
     * @param {THREE.Vector3}    centerVec    dummy position at attach time
     * @param {THREE.Vector3}    dummyPosVec  current dummy position
     * @param {THREE.Quaternion} incrRotQuat  R_incr = current_quat * start_quat.invert()
     */
    applyClusterTransform(helixIds, centerVec, dummyPosVec, incrRotQuat, domainIds = null, { forceAxes = false } = {}) {
      const helixSet = new Set(helixIds)
      const domainKeySet = domainIds?.length
        ? new Set(domainIds.map(d => `${d.strand_id}:${d.domain_index}`))
        : null

      // 1. Backbone beads — incremental transform from snapshot base
      for (const entry of backboneEntries) {
        if (!helixSet.has(entry.nuc.helix_id)) continue
        if (domainKeySet && !domainKeySet.has(`${entry.nuc.strand_id}:${entry.nuc.domain_index}`)) continue
        const key  = `${entry.nuc.helix_id}:${entry.nuc.bp_index}:${entry.nuc.direction}`
        const base = _cbEntries.get(key)
        if (!base) continue
        _clusterV.copy(base).sub(centerVec).applyQuaternion(incrRotQuat)
        entry.pos.set(_clusterV.x + dummyPosVec.x, _clusterV.y + dummyPosVec.y, _clusterV.z + dummyPosVec.z)
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
      }

      // 1b. Extension beads — must be updated before cone recompute so that
      //     cones connecting real terminal nucs to __ext_ beads are correct.
      //     (skip for domain-subset clusters unless forceAxes is set)
      if (!domainKeySet || forceAxes) {
        for (const entry of backboneEntries) {
          const nuc = entry.nuc
          if (!nuc.helix_id.startsWith('__ext_')) continue
          const parentHelix = _extToRealHelix.get(nuc.extension_id)
          if (!parentHelix || !helixSet.has(parentHelix)) continue
          const base = _cbExtEntries.get(`${nuc.helix_id}:${nuc.bp_index}`)
          if (!base) continue
          _clusterV.copy(base).sub(centerVec).applyQuaternion(incrRotQuat)
          entry.pos.set(_clusterV.x + dummyPosVec.x, _clusterV.y + dummyPosVec.y, _clusterV.z + dummyPosVec.z)
          _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
          entry.instMesh.setMatrixAt(entry.id, _tMatrix)
        }

        for (const entry of fluoroEntries) {
          const nuc = entry.nuc
          const parentHelix = _extToRealHelix.get(nuc.extension_id)
          if (!parentHelix || !helixSet.has(parentHelix)) continue
          const base = _cbFluoEntries.get(`${nuc.helix_id}:${nuc.bp_index}`)
          if (!base) continue
          _clusterV.copy(base).sub(centerVec).applyQuaternion(incrRotQuat)
          entry.pos.set(_clusterV.x + dummyPosVec.x, _clusterV.y + dummyPosVec.y, _clusterV.z + dummyPosVec.z)
          _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(1, 1, 1))
          entry.instMesh.setMatrixAt(entry.id, _tMatrix)
        }
        iFluoros.instanceMatrix.needsUpdate = true
      }

      iSpheres.instanceMatrix.needsUpdate = true
      iCubes.instanceMatrix.needsUpdate   = true

      // 2. Cones — recompute all from updated entry.pos (handles cross-cluster edges,
      //    including real→__ext_ and intra-__ext_ cones).
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

      // 3. Slabs — rotate base bnDir/quat by R_incr, recompute center from updated bbPos
      for (const slab of slabEntries) {
        if (!helixSet.has(slab.nuc.helix_id)) continue
        if (domainKeySet && !domainKeySet.has(`${slab.nuc.strand_id}:${slab.nuc.domain_index}`)) continue
        const entry    = _nucToEntry.get(slab.nuc)
        const baseData = _cbSlabs.get(slab.nuc)
        if (!entry || !baseData) continue
        slab.bbPos.copy(entry.pos)
        _clusterV.copy(baseData.bnDir).applyQuaternion(incrRotQuat)
        _clusterQ.multiplyQuaternions(incrRotQuat, baseData.quat)
        // Write back so captureClusterBase sees the current rendered orientation on the
        // next animation, not the stale original-geometry values (same reason
        // arrow.aStart/aEnd are written back in step 4).
        slab.bnDir.copy(_clusterV)
        slab.quat.copy(_clusterQ)
        const center_ = slabCenter(slab.bbPos, _clusterV, slabParams.distance)
        _tMatrix.compose(center_, _clusterQ, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
        iSlabs.setMatrixAt(slab.id, _tMatrix)
      }
      iSlabs.instanceMatrix.needsUpdate = true

      // 4. Helix-level axis aStart/aEnd + curved tube transform.
      //    Partial-coverage clusters skip this (only individual segments move; aStart/aEnd
      //    can't represent the helix's overall extent under partial movement).
      if (!domainKeySet || forceAxes) for (const arrow of axisArrows) {
        if (!helixSet.has(arrow.helixId)) continue
        const baseData = _cbArrows.get(arrow.helixId)
        if (!baseData) continue
        _clusterV.copy(baseData.aStart).sub(centerVec).applyQuaternion(incrRotQuat)
        const sx0 = _clusterV.x + dummyPosVec.x, sy0 = _clusterV.y + dummyPosVec.y, sz0 = _clusterV.z + dummyPosVec.z
        _clusterV.copy(baseData.aEnd).sub(centerVec).applyQuaternion(incrRotQuat)
        const sx1 = _clusterV.x + dummyPosVec.x, sy1 = _clusterV.y + dummyPosVec.y, sz1 = _clusterV.z + dummyPosVec.z
        arrow.aStart.set(sx0, sy0, sz0)
        arrow.aEnd.set(sx1, sy1, sz1)

        if (arrow.isCurved) {
          // Rigidly transform the TubeGeometry shaft mesh + straight placeholder.
          if (arrow.shaft && baseData.shaftPos !== null) {
            _clusterV.copy(baseData.shaftPos).sub(centerVec).applyQuaternion(incrRotQuat)
            arrow.shaft.position.set(_clusterV.x + dummyPosVec.x, _clusterV.y + dummyPosVec.y, _clusterV.z + dummyPosVec.z)
            _clusterQ.multiplyQuaternions(incrRotQuat, baseData.shaftQuat)
            arrow.shaft.quaternion.copy(_clusterQ)
          }
          if (arrow.straightShaft && baseData.ssPos !== null) {
            _clusterV.copy(baseData.ssPos).sub(centerVec).applyQuaternion(incrRotQuat)
            arrow.straightShaft.position.set(_clusterV.x + dummyPosVec.x, _clusterV.y + dummyPosVec.y, _clusterV.z + dummyPosVec.z)
            _clusterQ.multiplyQuaternions(incrRotQuat, baseData.ssQuat)
            arrow.straightShaft.quaternion.copy(_clusterQ)
          }
        }
      }

      // 5. Overhang half-cylinders.
      //    Entries with wsStart use world-space snapshot/rotate (per-domain shared-stub fix).
      //    Entries without wsStart fall back to arrow.aStart/aEnd (extrude overhangs, forceAxes).
      {
        let anyOvhg = false
        for (const dom of _overhangCylData) {
          if (!helixSet.has(dom.helixId)) continue
          let d0x, d0y, d0z, d1x, d1y, d1z
          if (dom.wsStart) {
            const snap = _cbOvhgCyls.get(dom)
            if (!snap) continue
            if (domainKeySet && !domainKeySet.has(`${dom.strandId}:${dom.domainIndex}`)) continue
            const ns = _clusterV.copy(snap.wsStart).sub(centerVec).applyQuaternion(incrRotQuat)
            d0x = ns.x + dummyPosVec.x; d0y = ns.y + dummyPosVec.y; d0z = ns.z + dummyPosVec.z
            dom.wsStart.set(d0x, d0y, d0z)
            const ne = _clusterV.copy(snap.wsEnd).sub(centerVec).applyQuaternion(incrRotQuat)
            d1x = ne.x + dummyPosVec.x; d1y = ne.y + dummyPosVec.y; d1z = ne.z + dummyPosVec.z
            dom.wsEnd.set(d1x, d1y, d1z)
          } else {
            if (domainKeySet && !forceAxes) continue
            const s = dom.arrow.aStart, e = dom.arrow.aEnd
            d0x = s.x + (e.x - s.x) * dom.t0; d0y = s.y + (e.y - s.y) * dom.t0; d0z = s.z + (e.z - s.z) * dom.t0
            d1x = s.x + (e.x - s.x) * dom.t1; d1y = s.y + (e.y - s.y) * dom.t1; d1z = s.z + (e.z - s.z) * dom.t1
          }
          _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
          _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
          const cylLen = _physDir.length()
          if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
          else _cylQ.identity()
          _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
          iOverhangCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
          anyOvhg = true
        }
        if (anyOvhg) iOverhangCylinders.instanceMatrix.needsUpdate = true

        // 5b. Curved-helix proxy cylinders — same formula as overhang cylinders above.
        let anyCurved = false
        for (const dom of _curvedDomainCylData) {
          if (!helixSet.has(dom.helixId)) continue
          const s = dom.arrow.aStart, e = dom.arrow.aEnd
          const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
          const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
          _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
          _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
          const cylLen = _physDir.length()
          if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
          else _cylQ.identity()
          _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
          iCurvedHelixCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
          anyCurved = true
        }
        for (const dom of _curvedOvhgCylData) {
          if (!helixSet.has(dom.helixId)) continue
          const s = dom.arrow.aStart, e = dom.arrow.aEnd
          const d0x = s.x + (e.x - s.x) * dom.t0, d0y = s.y + (e.y - s.y) * dom.t0, d0z = s.z + (e.z - s.z) * dom.t0
          const d1x = s.x + (e.x - s.x) * dom.t1, d1y = s.y + (e.y - s.y) * dom.t1, d1z = s.z + (e.z - s.z) * dom.t1
          _tPos.set((d0x + d1x) * 0.5, (d0y + d1y) * 0.5, (d0z + d1z) * 0.5)
          _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
          const cylLen = _physDir.length()
          if (cylLen > 0.001) _cylQ.setFromUnitVectors(Y_HAT, _physDir.divideScalar(cylLen))
          else _cylQ.identity()
          _tMatrix.compose(_tPos, _cylQ, _tScale.set(_cylRadiusScale, cylLen, _cylRadiusScale))
          iCurvedOverhangCylinders.setMatrixAt(dom.cylIdx, _tMatrix)
          anyCurved = true
        }
        if (anyCurved) {
          iCurvedHelixCylinders.instanceMatrix.needsUpdate   = true
          iCurvedOverhangCylinders.instanceMatrix.needsUpdate = true
        }

        // 5c. Per-domain axis segments (world-space cylinders, straight helices).
        //     Each segment moves independently based on its (strandId:domainIndex) match.
        for (const arrow of axisArrows) {
          if (!helixSet.has(arrow.helixId)) continue
          for (const seg of arrow.segments) {
            const snap = _cbSegments.get(seg)
            if (!snap) continue
            const ns = _clusterV.copy(snap.wsStart).sub(centerVec).applyQuaternion(incrRotQuat)
            const d0x = ns.x + dummyPosVec.x, d0y = ns.y + dummyPosVec.y, d0z = ns.z + dummyPosVec.z
            seg.wsStart.set(d0x, d0y, d0z)
            const ne = _clusterV.copy(snap.wsEnd).sub(centerVec).applyQuaternion(incrRotQuat)
            const d1x = ne.x + dummyPosVec.x, d1y = ne.y + dummyPosVec.y, d1z = ne.z + dummyPosVec.z
            seg.wsEnd.set(d1x, d1y, d1z)
            _physDir.set(d1x - d0x, d1y - d0y, d1z - d0z)
            const segLen = _physDir.length()
            if (segLen > 0.001) {
              seg.mesh.position.copy(_clusterV.set(d0x, d0y, d0z).addScaledVector(_physDir, seg.adjLen * 0.5 / segLen))
              seg.mesh.quaternion.setFromUnitVectors(_AY, _physDir.divideScalar(segLen))
            }
          }
        }
      }
    },

    /**
     * Sync the in-memory geometry data (entry.nuc fields) to match the
     * currently rendered positions for the given helices. Used by Plan B's
     * cluster-transform commit path: after the gizmo's live drag has set
     * entry.pos / slab.bnDir to the new cluster-transformed values, we
     * reconcile nuc.backbone_position and nuc.base_normal so the store's
     * currentGeometry array stays consistent (entry.nuc is a shared
     * reference into currentGeometry items, so mutating it propagates).
     *
     * Without this sync, downstream consumers that read currentGeometry
     * (oxDNA / FEM / atomistic / surface mesh / save-to-disk / undo
     * round-trip) would see stale pre-cluster-transform positions even
     * though the on-screen visuals are correct.
     *
     * Note: nuc.base_position and nuc.axis_tangent are not updated here.
     * Consumers that need them precisely should trigger a fresh
     * GET /design/geometry. base_position only affects slab-centre
     * computation and a few specialised exports; updating slab.bnDir is
     * enough for the slab orientation to look right after revertToGeometry.
     */
    commitClusterPositions(helixIds) {
      const helixSet = new Set(helixIds)
      // Extensions (sequence beads on __ext_* helices and fluorophore beads)
      // inherit their parent helix's cluster transform — applyClusterTransform
      // step 1b moves them in lockstep with the parent. Sync their nuc data
      // so cross-helix arcs (rendered from nuc.backbone_position via
      // getCrossHelixConnections) and downstream consumers see post-transform
      // positions; otherwise the bead and the arc disagree.
      const _extParentInSet = (extId) => {
        const parent = _extToRealHelix.get(extId)
        return parent != null && helixSet.has(parent)
      }
      for (const entry of backboneEntries) {
        const hid = entry.nuc.helix_id
        const aff = hid.startsWith('__ext_')
          ? _extParentInSet(entry.nuc.extension_id)
          : helixSet.has(hid)
        if (!aff) continue
        if (!entry.nuc.backbone_position) continue
        entry.nuc.backbone_position[0] = entry.pos.x
        entry.nuc.backbone_position[1] = entry.pos.y
        entry.nuc.backbone_position[2] = entry.pos.z
      }
      for (const entry of fluoroEntries) {
        if (!_extParentInSet(entry.nuc.extension_id)) continue
        if (!entry.nuc.backbone_position) continue
        entry.nuc.backbone_position[0] = entry.pos.x
        entry.nuc.backbone_position[1] = entry.pos.y
        entry.nuc.backbone_position[2] = entry.pos.z
      }
      for (const slab of slabEntries) {
        if (!helixSet.has(slab.nuc.helix_id)) continue
        if (slab.nuc.helix_id.startsWith('__ext_')) continue
        if (!slab.nuc.base_normal) continue
        slab.nuc.base_normal[0] = slab.bnDir.x
        slab.nuc.base_normal[1] = slab.bnDir.y
        slab.nuc.base_normal[2] = slab.bnDir.z
      }
    },

    /**
     * Patch in-place the rendered positions of ds-linker bridge nucs.
     *
     * Called after a cluster commit (Plan B): the backend's
     * /design/refresh-bridges endpoint re-emits bridge nucs from the live OH
     * anchor positions and returns the updated dicts. We locate the matching
     * `backboneEntries` entry for each by `(helix_id, bp_index, direction)`,
     * mutate `entry.nuc.{backbone_position, base_position, base_normal,
     * axis_tangent}` (the shared reference into `currentGeometry`), update
     * `entry.pos`, and re-write the bead matrix. We then recompute slabs and
     * cones whose endpoints touch any updated bridge nuc — they need to track
     * the new positions/orientations so the bridge looks coherent.
     *
     * @param {Array<{helix_id: string, bp_index: number, direction: string,
     *                backbone_position: number[], base_position?: number[],
     *                base_normal?: number[], axis_tangent?: number[]}>} bridgeNucs
     */
    applyBridgeNucsUpdate(bridgeNucs) {
      if (!bridgeNucs?.length) return
      const updateByKey = new Map()
      for (const u of bridgeNucs) {
        updateByKey.set(`${u.helix_id}:${u.bp_index}:${u.direction}`, u)
      }

      const updatedNucs = new Set()
      for (const entry of backboneEntries) {
        const n = entry.nuc
        const key = `${n.helix_id}:${n.bp_index}:${n.direction}`
        const u = updateByKey.get(key)
        if (!u) continue
        if (u.backbone_position && n.backbone_position) {
          n.backbone_position[0] = u.backbone_position[0]
          n.backbone_position[1] = u.backbone_position[1]
          n.backbone_position[2] = u.backbone_position[2]
        }
        if (u.base_position && n.base_position) {
          n.base_position[0] = u.base_position[0]
          n.base_position[1] = u.base_position[1]
          n.base_position[2] = u.base_position[2]
        }
        if (u.base_normal && n.base_normal) {
          n.base_normal[0] = u.base_normal[0]
          n.base_normal[1] = u.base_normal[1]
          n.base_normal[2] = u.base_normal[2]
        }
        if (u.axis_tangent && n.axis_tangent) {
          n.axis_tangent[0] = u.axis_tangent[0]
          n.axis_tangent[1] = u.axis_tangent[1]
          n.axis_tangent[2] = u.axis_tangent[2]
        }
        if (u.backbone_position) {
          entry.pos.set(u.backbone_position[0], u.backbone_position[1], u.backbone_position[2])
        }
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
        updatedNucs.add(n)
      }
      if (!updatedNucs.size) return

      iSpheres.instanceMatrix.needsUpdate = true
      iCubes.instanceMatrix.needsUpdate   = true

      // Cones — recompute any cone with an updated endpoint (handles
      // bridge↔bridge intra-strand cones AND the bridge↔OH cross-helix cone
      // at each side). Cross-helix cones keep their radius-0 invisibility.
      let conesUpdated = false
      for (const cone of coneEntries) {
        if (!updatedNucs.has(cone.fromNuc) && !updatedNucs.has(cone.toNuc)) continue
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
        const r = cone.isCrossHelix ? 0 : cone.coneRadius
        _tMatrix.compose(cone.midPos, cone.quat, _tScale.set(r, h, r))
        iCones.setMatrixAt(cone.id, _tMatrix)
        conesUpdated = true
      }
      if (conesUpdated) iCones.instanceMatrix.needsUpdate = true

      // Slabs — recompute any slab whose nuc was updated, using the fresh
      // base_normal / axis_tangent / backbone_position from the response.
      let slabsUpdated = false
      const _slabBn  = new THREE.Vector3()
      const _slabTan = new THREE.Vector3()
      for (const slab of slabEntries) {
        if (!updatedNucs.has(slab.nuc)) continue
        const n = slab.nuc
        _slabBn.set(n.base_normal[0], n.base_normal[1], n.base_normal[2])
        _slabTan.set(n.axis_tangent[0], n.axis_tangent[1], n.axis_tangent[2])
        slab.bnDir.copy(_slabBn)
        slab.quat.copy(slabQuaternion(_slabBn, _slabTan))
        slab.bbPos.set(n.backbone_position[0], n.backbone_position[1], n.backbone_position[2])
        const center = slabCenter(slab.bbPos, slab.bnDir, slabParams.distance)
        _tMatrix.compose(center, slab.quat, _tScale.set(slabParams.length, slabParams.width, slabParams.thickness))
        iSlabs.setMatrixAt(slab.id, _tMatrix)
        slabsUpdated = true
      }
      if (slabsUpdated) iSlabs.instanceMatrix.needsUpdate = true
    },

    /**
     * Lerp strand extension beads (sequence + fluorophore) toward their 2D unfold positions.
     *
     * @param {Map<string, Map<number, {x,y,z}>>} extArcMap
     *   Maps extension_id → Map<bp_index, target world position at full unfold>.
     * @param {number} unfoldT  Animation progress 0 (3D) → 1 (unfold).
     */
    applyUnfoldOffsetsExtensions(extArcMap, unfoldT, straightPosMap = null) {
      // Sequence beads (in backboneEntries, synthetic __ext_ helix).
      for (const entry of backboneEntries) {
        const nuc = entry.nuc
        if (!nuc.helix_id?.startsWith('__ext_')) continue
        const beadMap = extArcMap?.get(nuc.extension_id)
        const target  = beadMap?.get(nuc.bp_index)
        const sp = straightPosMap?.get(`${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`)
        const gx = sp ? sp.x : nuc.backbone_position[0]
        const gy = sp ? sp.y : nuc.backbone_position[1]
        const gz = sp ? sp.z : nuc.backbone_position[2]
        if (target) {
          entry.pos.set(
            gx + (target.x - gx) * unfoldT,
            gy + (target.y - gy) * unfoldT,
            gz + (target.z - gz) * unfoldT,
          )
        } else {
          entry.pos.set(gx, gy, gz)
        }
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(_beadScale, _beadScale, _beadScale))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
      }
      iSpheres.instanceMatrix.needsUpdate = true
      iCubes.instanceMatrix.needsUpdate   = true

      // Fluorophore beads.
      for (const entry of fluoroEntries) {
        const nuc     = entry.nuc
        const beadMap = extArcMap?.get(nuc.extension_id)
        const target  = beadMap?.get(nuc.bp_index)
        const sp = straightPosMap?.get(`${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`)
        const gx = sp ? sp.x : nuc.backbone_position[0]
        const gy = sp ? sp.y : nuc.backbone_position[1]
        const gz = sp ? sp.z : nuc.backbone_position[2]
        if (target) {
          entry.pos.set(
            gx + (target.x - gx) * unfoldT,
            gy + (target.y - gy) * unfoldT,
            gz + (target.z - gz) * unfoldT,
          )
        } else {
          entry.pos.set(gx, gy, gz)
        }
        _tMatrix.compose(entry.pos, ID_QUAT, _tScale.set(1, 1, 1))
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
      }
      iFluoros.instanceMatrix.needsUpdate = true
    },

    /** Return fluorophore entries for raycasting and selection. */
    getFluoroEntries() { return fluoroEntries },

    /** Returns the live rendered position of a nucleotide entry, or null if not found.
     *  Used by unfold_view to update arc endpoints after cluster transforms.
     *  Falls back to fluoroEntries so cross-helix arcs to fluorophore beads
     *  track cluster transforms (the fluorophore bead is moved by
     *  applyClusterTransform step 1b but lives outside _nucToEntry). */
    getNucLivePos(nuc) {
      return (_nucToEntry.get(nuc) ?? _fluoroNucToEntry.get(nuc))?.pos ?? null
    },

    /**
     * Show or hide nucleotides by cluster membership.
     * Keys use two formats:
     *   'h:<helix_id>'                 — hide the whole helix (helix-level cluster)
     *   'd:<strand_id>:<domain_index>' — hide specific domain (domain-level cluster)
     * This lets two domain-level clusters sharing the same helix be toggled independently.
     * Hidden state survives resetAllToDefault because resetAllToDefault checks _isNucHidden.
     *
     * @param {Set<string>} keys
     */
    setHiddenNucs(keys) {
      _hiddenNucKeys = keys instanceof Set ? keys : new Set(keys)

      for (const entry of backboneEntries) {
        _setBeadScale(entry, _isNucHidden(entry.nuc) ? 0 : _beadScale)
      }
      for (const entry of fluoroEntries) {
        _setBeadScale(entry, _isNucHidden(entry.nuc) ? 0 : _beadScale)
      }
      for (const entry of coneEntries) {
        if (entry.isCrossHelix) continue
        _setConeXZScale(entry, _isNucHidden(entry.fromNuc) ? 0 : CONE_RADIUS)
      }
      for (const entry of slabEntries) {
        const hidden = _isNucHidden(entry.nuc)
        _tMatrix.compose(
          entry.center, entry.quat,
          hidden
            ? _tScale.set(0, 0, 0)
            : _tScale.set(slabParams.length, slabParams.width, slabParams.thickness),
        )
        entry.instMesh.setMatrixAt(entry.id, _tMatrix)
      }
      if (slabEntries.length) iSlabs.instanceMatrix.needsUpdate = true
    },

    /**
     * Show or hide all extension beads and fluorophores.
     * Used by the extensionLocations toolFilter toggle.
     */
    setExtensionsVisible(visible) {
      const s = visible ? 1 : 0
      for (const entry of backboneEntries) {
        if (!entry.nuc.helix_id?.startsWith('__ext_')) continue
        _setBeadScale(entry, s)
      }
      for (const entry of fluoroEntries) {
        _setBeadScale(entry, s)
      }
    },

    /**
     * Log a comparison of each cone's rendered midpoint vs the midpoint
     * implied by its two backbone-bead entry.pos values.
     *
     * Call before and after a cluster rotation to see which cones drift.
     * Rows where err_nm > 0 indicate a stale cone matrix that doesn't match
     * the bead positions it's supposed to connect.
     *
     * @param {string} label  Prefix for the console group (e.g. "BEFORE", "AFTER-XB")
     */
    logConeDebug(label = '') {
      const _tmp = new THREE.Vector3()
      const rows = []
      let mismatchCount = 0

      for (const cone of coneEntries) {
        const fe = _nucToEntry.get(cone.fromNuc)
        const te = _nucToEntry.get(cone.toNuc)
        if (!fe || !te) continue

        _tmp.addVectors(fe.pos, te.pos).multiplyScalar(0.5)
        const err = cone.midPos.distanceTo(_tmp)

        const fromH = cone.fromNuc.helix_id
        const toH   = cone.toNuc.helix_id
        const isCross = fromH !== toH

        // Include cross-helix cones always; include intra-helix only if mismatch
        if (err > 5e-4 || isCross) {
          mismatchCount += err > 5e-4 ? 1 : 0
          rows.push({
            type:         isCross ? 'CROSS' : 'intra',
            from:         `${fromH.length > 16 ? fromH.slice(-12) : fromH}:${cone.fromNuc.bp_index}:${cone.fromNuc.direction[0]}`,
            to:           `${toH.length > 16 ? toH.slice(-12) : toH}:${cone.toNuc.bp_index}:${cone.toNuc.direction[0]}`,
            fromPos:      `(${fe.pos.x.toFixed(3)}, ${fe.pos.y.toFixed(3)}, ${fe.pos.z.toFixed(3)})`,
            toPos:        `(${te.pos.x.toFixed(3)}, ${te.pos.y.toFixed(3)}, ${te.pos.z.toFixed(3)})`,
            midExpected:  `(${_tmp.x.toFixed(3)}, ${_tmp.y.toFixed(3)}, ${_tmp.z.toFixed(3)})`,
            midActual:    `(${cone.midPos.x.toFixed(3)}, ${cone.midPos.y.toFixed(3)}, ${cone.midPos.z.toFixed(3)})`,
            err_nm:       err.toFixed(5),
          })
        }
      }

      const tag = label ? `[ConeDebug:${label}]` : '[ConeDebug]'
      console.group(`${tag}  ${mismatchCount} mismatches / ${coneEntries.length} total cones`)
      if (rows.length) console.table(rows)
      else console.log('No XB cones and no intra-helix mismatches.')
      console.groupEnd()
    },
  }
}
