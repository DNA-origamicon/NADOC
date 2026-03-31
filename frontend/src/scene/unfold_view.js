/**
 * 2D Unfold View — animates helices from their 3D lattice positions to a
 * linear horizontal stack (caDNAno-style Path Panel).
 *
 * Each helix is translated so its axis midpoint sits at (0, −i × spacing, z),
 * stacked top-to-bottom in the order stored in store.unfoldHelixOrder.
 *
 * Cross-helix strand connections (placed crossovers) are always rendered as
 * QuadraticBezierCurve3 arc lines (THREE.Line), replacing the hidden instanced
 * cones.  Arcs are visible in the 3D view too — in 3D they are straight
 * (bow = 0); as the unfold animation plays out (t: 0→1) the bow grows and the
 * endpoints translate with their helices.  Paired arcs on the same helix pair
 * diverge in the )(  direction so they never cross.
 *
 * Usage:
 *   const unfoldView = initUnfoldView(scene, designRenderer, store)
 *   unfoldView.toggle()           // activate / deactivate
 *   unfoldView.setSpacing(3.0)    // change row spacing in nm
 *   unfoldView.isActive()         // → boolean
 *   unfoldView.dispose()
 */

import * as THREE from 'three'
import { store } from '../state/store.js'
import { createGlowLayer } from './glow_layer.js'

const ANIM_DURATION_MS = 500   // linear lerp duration
const ARC_SEGS         = 20    // bezier sample count per arc line
const MAX_BOW_FRAC     = 0.15  // control point bows dist × frac at full unfold

const _ZERO_VEC = new THREE.Vector3(0, 0, 0)

// Scratch vectors reused each frame (never held across async boundaries).
const _sv0     = new THREE.Vector3()
const _sv1     = new THREE.Vector3()
const _sCtrl   = new THREE.Vector3()
// Scratch vectors for extension-endpoint unfold offset computation (_extArcOff).
const _sExtFrom = new THREE.Vector3()
const _sExtTo   = new THREE.Vector3()

export function initUnfoldView(scene, designRenderer, getBluntEnds, getLoopSkipHighlight, getSequenceOverlay, getOverhangLocations, getCrossoverLocations) {
  let _active       = false
  let _animFrame    = null
  let _currentT     = 0
  let _slicePlane   = null   // set via setSlicePlane(); lerped each frame alongside helices
  let _midZ         = 0   // Z midpoint of the design; set by _buildOffsets
  // Tracks the deform lerp value (0 = straight, 1 = deformed).  Updated by
  // applyDeformLerp() so _updateArcPositions knows which base to use in 3D view.
  let _currentDeformT = 1   // deform view starts active by default

  // Straight geometry maps — base positions for unfold (deform must be off before entering unfold).
  let _straightPosMap  = null   // Map<"hid:bp:dir", THREE.Vector3>
  let _straightAxesMap = null   // Map<helixId, {start: THREE.Vector3, end: THREE.Vector3}>

  function _buildStraightMaps() {
    const { straightGeometry, straightHelixAxes } = store.getState()
    if (straightGeometry) {
      _straightPosMap = new Map()
      for (const nuc of straightGeometry) {
        const bp = nuc.backbone_position
        _straightPosMap.set(
          `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`,
          new THREE.Vector3(bp[0], bp[1], bp[2]),
        )
      }
    }
    if (straightHelixAxes) {
      _straightAxesMap = new Map()
      for (const [helixId, ax] of Object.entries(straightHelixAxes)) {
        _straightAxesMap.set(helixId, {
          start: new THREE.Vector3(...ax.start),
          end:   new THREE.Vector3(...ax.end),
        })
      }
    }
  }

  const _arcGroup = new THREE.Group()
  scene.add(_arcGroup)

  // ── Arc glow (selected crossover arcs) ──────────────────────────────────────
  // One glow sphere per arc vertex — additive green blend sits over the arc line
  // for a radioactive halo effect matching the selected-bead glow.
  const _arcGlowLayer = createGlowLayer(scene, 0x3fb950, 2.0)
  let _arcGlowArcs    = []   // arc wrapper objects (from getArcEntries) currently glowing
  let _arcGlowEntries = []   // {pos: THREE.Vector3}[] — one per vertex per arc

  /** Re-read vertex positions from the merged buffer into the cached glow entries. */
  function _refreshArcGlow() {
    if (!_arcGlowArcs.length) return
    let ei = 0
    for (const arc of _arcGlowArcs) {
      arc._readPositionsInto?.(_arcGlowEntries, ei)
      ei += ARC_SEGS + 1
    }
    _arcGlowLayer.refresh()
  }

  // ── Arc metadata & merged geometry ──────────────────────────────────────────
  // All arcs are merged into at most two THREE.LineSegments objects:
  //   _scaffoldMerged — arcs whose fromNuc is scaffold (always visible)
  //   _stapleMerged   — arcs whose fromNuc is staple (hidden with staplesHidden)
  //
  // This reduces N crossover draw calls to 2, regardless of design size.
  //
  // Each entry in _arcMeta stores per-arc metadata.  The geometry-facing fields
  // are vertIdx (first vertex index in the merged position/color buffers) and
  // merged ('scaffold'|'staple', which merged object owns this arc).

  /**
   * @typedef {{
   *   from3D:       THREE.Vector3,
   *   to3D:         THREE.Vector3,
   *   fromStraight: THREE.Vector3|null,
   *   toStraight:   THREE.Vector3|null,
   *   fromHelixId:  string,
   *   toHelixId:    string,
   *   bowDir:       number,
   *   color:        number,
   *   strandId:     string|null,
   *   fromNuc:      object,
   *   toNuc:        object,
   *   crossover_id: string|null,
   *   merged:       'scaffold'|'staple',
   *   vertIdx:      number,
   * }} ArcMeta
   * @type {ArcMeta[]}
   */
  let _arcMeta = []

  /** @type {{geo: THREE.BufferGeometry, line: THREE.LineSegments, positions: Float32Array, colors: Float32Array}|null} */
  let _scaffoldMerged = null
  /** @type {{geo: THREE.BufferGeometry, line: THREE.LineSegments, positions: Float32Array, colors: Float32Array}|null} */
  let _stapleMerged   = null

  /**
   * Build a merged LineSegments object for the given arc metadata array.
   * Mutates each entry's `vertIdx` to its first vertex position in the buffer.
   * Returns null when arcs is empty.
   */
  function _buildMerged(arcs) {
    if (!arcs.length) return null
    const N         = arcs.length
    const vertCount = N * (ARC_SEGS + 1)
    const positions = new Float32Array(vertCount * 3)
    const colors    = new Float32Array(vertCount * 3)
    // LineSegments uses pairs: each of the ARC_SEGS segments has 2 index entries.
    const idxCount  = N * ARC_SEGS * 2
    const idx       = vertCount > 65535
      ? new Uint32Array(idxCount)
      : new Uint16Array(idxCount)
    const tc = new THREE.Color()
    for (let a = 0; a < N; a++) {
      const base = a * (ARC_SEGS + 1)
      arcs[a].vertIdx = base   // mutate the _arcMeta entry in place
      for (let s = 0; s < ARC_SEGS; s++) {
        idx[(a * ARC_SEGS + s) * 2]     = base + s
        idx[(a * ARC_SEGS + s) * 2 + 1] = base + s + 1
      }
      tc.setHex(arcs[a].color ?? 0x00ccff)
      for (let v = 0; v <= ARC_SEGS; v++) {
        const ci = (base + v) * 3
        colors[ci] = tc.r; colors[ci + 1] = tc.g; colors[ci + 2] = tc.b
      }
    }
    const geo  = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    geo.setAttribute('color',    new THREE.BufferAttribute(colors,    3))
    geo.setIndex(new THREE.BufferAttribute(idx, 1))
    const mat  = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.85 })
    const line = new THREE.LineSegments(geo, mat)
    line.frustumCulled = false
    return { geo, line, positions, colors }
  }

  /** Update the vertex color of a single arc in its merged buffer. */
  function _setArcColor(e, hex) {
    const merged = e.merged === 'scaffold' ? _scaffoldMerged : _stapleMerged
    if (!merged) return
    const tc = new THREE.Color(hex)
    for (let v = 0; v <= ARC_SEGS; v++) {
      const ci = (e.vertIdx + v) * 3
      merged.colors[ci] = tc.r; merged.colors[ci + 1] = tc.g; merged.colors[ci + 2] = tc.b
    }
    merged.geo.attributes.color.needsUpdate = true
  }

  /**
   * Map<crossover_bases_id, {bezierAt: (beadT: number) => THREE.Vector3}>
   * Provides the full-unfold (t=1) arc position for extra-base beads.
   * Rebuilt by _buildXbArcMap() whenever arcs or offsets change.
   */
  let _xbArcMap = new Map()

  /**
   * Map<extension_id, Map<bp_index, {x,y,z}>>
   * Per-bead target world positions for strand extensions at full unfold (t=1).
   * Rebuilt by _buildExtArcMap() whenever arcs or offsets change.
   */
  let _extArcMap = new Map()

  /**
   * Map<extension_id, {termNuc, sign, helixId}>
   * Terminus nucleotide reference + fanout sign (±1) per extension.
   * Rebuilt by _buildExtArcMap() so applyClusterExtArcUpdate can read live positions.
   */
  let _extTermInfo = new Map()

  // ── Arc management ──────────────────────────────────────────────────────────

  function _applyStapleArcVisibility() {
    if (_stapleMerged) _stapleMerged.line.visible = !store.getState().staplesHidden
  }

  function _clearArcs() {
    for (const m of [_scaffoldMerged, _stapleMerged]) {
      if (!m) continue
      _arcGroup.remove(m.line)
      m.geo.dispose()
      m.line.material.dispose()
    }
    _scaffoldMerged = null
    _stapleMerged   = null
    _arcMeta = []
  }

  /**
   * Build persistent arc Line objects from the given cross-helix connections.
   * Each entry stores both the current 3D position (from3D/to3D, used in the
   * 3D view at t=0) and the straight position (fromStraight/toStraight, used
   * as the base when the unfold animation runs with deform off).
   *
   * @param {Array<{from, to, color, fromHelixId, toHelixId, fromNuc, toNuc}>} connections
   * @param {Map<string,THREE.Vector3>|null} straightPosMap
   */
  function _initArcs(connections, straightPosMap) {
    _clearArcs()
    if (!connections.length) return

    // Build a lookup: "strandId:domain_a_index" → crossover, so each arc can
    // be associated with its Crossover ID for the extra-bases context menu.
    const design = store.getState().currentDesign
    const xoByDomainKey = new Map()
    if (design) {
      for (const xo of (design.crossovers ?? [])) {
        xoByDomainKey.set(`${xo.strand_a_id}:${xo.domain_a_index}`, xo)
      }
    }

    // Group by sorted helix pair to determine bow direction.
    const groups = new Map()
    for (const conn of connections) {
      const key = [conn.fromHelixId, conn.toHelixId].sort().join('|')
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key).push(conn)
    }

    for (const conns of groups.values()) {
      const groupCenterZ = conns.reduce((s, c) => s + (c.from.z + c.to.z) / 2, 0) / conns.length

      for (let ci = 0; ci < conns.length; ci++) {
        const conn = conns[ci]
        const arcZ = (conn.from.z + conn.to.z) / 2
        let bowDir
        if (conns.length < 2) {
          bowDir = 1
        } else {
          const zSign = Math.sign(arcZ - groupCenterZ)
          bowDir = zSign !== 0 ? zSign : (ci % 2 === 0 ? 1 : -1)
        }

        const fn = conn.fromNuc
        const tn = conn.toNuc
        const sf = fn && straightPosMap?.get(`${fn.helix_id}:${fn.bp_index}:${fn.direction}`)
        const st = tn && straightPosMap?.get(`${tn.helix_id}:${tn.bp_index}:${tn.direction}`)
        const xoForArc = fn ? xoByDomainKey.get(`${fn.strand_id}:${fn.domain_index}`) : null

        _arcMeta.push({
          from3D:       conn.from.clone(),
          to3D:         conn.to.clone(),
          fromStraight: sf ? sf.clone() : null,
          toStraight:   st ? st.clone() : null,
          fromHelixId:  conn.fromHelixId,
          toHelixId:    conn.toHelixId,
          bowDir,
          color:        conn.color ?? 0x00ccff,
          strandId:     conn.strandId ?? null,
          fromNuc:      conn.fromNuc,
          toNuc:        conn.toNuc,
          crossover_id: xoForArc?.id ?? null,
          merged:       (conn.fromNuc?.strand_type === 'scaffold') ? 'scaffold' : 'staple',
          vertIdx:      0,   // filled in by _buildMerged
        })
      }
    }

    // Build one merged LineSegments per strand type and add to scene group.
    const scaffoldArcs = _arcMeta.filter(e => e.merged === 'scaffold')
    const stapleArcs   = _arcMeta.filter(e => e.merged === 'staple')
    _scaffoldMerged = _buildMerged(scaffoldArcs)
    _stapleMerged   = _buildMerged(stapleArcs)
    if (_scaffoldMerged) _arcGroup.add(_scaffoldMerged.line)
    if (_stapleMerged)   _arcGroup.add(_stapleMerged.line)
  }

  /**
   * Build _xbArcMap so that extra-base beads can track the arc animation.
   * Each entry exposes bezierAt(beadT) → THREE.Vector3 at full unfold (t=1).
   *
   * @param {Map<string, THREE.Vector3>} offsets  helix_id → full-unfold translation
   * @param {Map<string,THREE.Vector3>|null} straightPosMap
   */
  function _buildXbArcMap(offsets, straightPosMap) {
    _xbArcMap = new Map()
    const design = store.getState().currentDesign
    if (!design?.crossover_bases?.length) return

    // Index crossover_bases by crossover_id for fast lookup.
    const cbByCxId = new Map()
    for (const cb of design.crossover_bases) cbByCxId.set(cb.crossover_id, cb)

    for (const e of _arcMeta) {
      if (!e.crossover_id) continue
      const cb = cbByCxId.get(e.crossover_id)
      if (!cb) continue

      // Base positions for this arc at full unfold.
      const sf = (straightPosMap && e.fromNuc)
        ? straightPosMap.get(`${e.fromNuc.helix_id}:${e.fromNuc.bp_index}:${e.fromNuc.direction}`)
        : null
      const st = (straightPosMap && e.toNuc)
        ? straightPosMap.get(`${e.toNuc.helix_id}:${e.toNuc.bp_index}:${e.toNuc.direction}`)
        : null
      const fromBase = sf ?? e.from3D
      const toBase   = st ?? e.to3D

      const offFrom = offsets.get(e.fromHelixId) ?? _ZERO_VEC
      const offTo   = offsets.get(e.toHelixId)   ?? _ZERO_VEC

      // Capture values for closure (offsets may be mutated externally).
      const fx1 = fromBase.x + offFrom.x
      const fy1 = fromBase.y + offFrom.y
      const fz1 = fromBase.z + offFrom.z
      const tx1 = toBase.x + offTo.x
      const ty1 = toBase.y + offTo.y
      const tz1 = toBase.z + offTo.z
      const bowDir = e.bowDir

      _xbArcMap.set(cb.id, {
        bezierAt(beadT) {
          // Full-unfold Bézier: P0 = from anchor+offset, P2 = to anchor+offset.
          const dist = Math.sqrt((tx1 - fx1) ** 2 + (ty1 - fy1) ** 2 + (tz1 - fz1) ** 2)
          const bow  = dist * MAX_BOW_FRAC * bowDir
          const cx   = (fx1 + tx1) * 0.5
          const cy   = (fy1 + ty1) * 0.5
          const cz   = (fz1 + tz1) * 0.5 + bow
          const u = beadT, u2 = 1 - u
          return new THREE.Vector3(
            u2 * u2 * fx1 + 2 * u2 * u * cx + u * u * tx1,
            u2 * u2 * fy1 + 2 * u2 * u * cy + u * u * ty1,
            u2 * u2 * fz1 + 2 * u2 * u * cz + u * u * tz1,
          )
        },
      })
    }
  }

  /**
   * Build _extArcMap so that extension beads track the unfold animation.
   * Maps extension_id → Map<bp_index, {x,y,z}> target at full unfold (t=1).
   *
   * Each sequence bead fans outward (±X) from the strand terminus in the 2D
   * layout.  5′ extensions extend to the left, 3′ to the right.
   *
   * @param {Map<string, THREE.Vector3>} offsets  helix_id → full-unfold translation
   * @param {Map<string,THREE.Vector3>|null} straightPosMap
   */
  function _buildExtArcMap(offsets, straightPosMap) {
    _extArcMap    = new Map()
    _extTermInfo  = new Map()
    const design = store.getState().currentDesign
    if (!design?.extensions?.length) return

    const geometry = store.getState().currentGeometry
    if (!geometry) return

    // Index extension nucleotides by extension_id → Map<bp_index, nuc>
    const extNucs = new Map()
    for (const nuc of geometry) {
      if (!nuc.extension_id) continue
      if (!extNucs.has(nuc.extension_id)) extNucs.set(nuc.extension_id, new Map())
      extNucs.get(nuc.extension_id).set(nuc.bp_index, nuc)
    }

    // Build a nuc lookup keyed by helix_id:bp_index:direction for terminus lookup.
    const nucByKey = new Map()
    for (const nuc of geometry) {
      if (!nuc.helix_id.startsWith('__')) {
        nucByKey.set(`${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`, nuc)
      }
    }

    for (const ext of design.extensions) {
      const nucMap = extNucs.get(ext.id)
      if (!nucMap?.size) continue

      const strand = design.strands.find(s => s.id === ext.strand_id)
      if (!strand) continue

      const termDom = ext.end === 'five_prime'
        ? strand.domains[0]
        : strand.domains[strand.domains.length - 1]
      if (!termDom) continue

      const termBp = ext.end === 'five_prime' ? termDom.start_bp : termDom.end_bp
      const termKey = `${termDom.helix_id}:${termBp}:${termDom.direction}`
      const termStraight = straightPosMap?.get(termKey)
      const helixOff = offsets.get(termDom.helix_id) ?? _ZERO_VEC

      // Store terminus nuc reference and sign for applyClusterExtArcUpdate.
      const termNuc = nucByKey.get(termKey)
      const sign    = ext.end === 'five_prime' ? -1 : 1
      if (termNuc) {
        // Compute per-bead XY offsets relative to the terminus so that
        // applyClusterExtArcUpdate can preserve relative positions under cluster drags.
        const termPos = termNuc.backbone_position  // [x, y, z]
        const relOffsets = new Map()
        for (const [bpIdx, nuc] of nucMap) {
          const bead3D = nuc.backbone_position
          relOffsets.set(bpIdx, { x: bead3D[0] - termPos[0], y: bead3D[1] - termPos[1], z: bead3D[2] - termPos[2] })
        }
        _extTermInfo.set(ext.id, { termNuc, sign, helixId: termDom.helix_id, bpCount: nucMap.size, relOffsets })
      }

      // Each bead's unfold target = its 3D XY position translated by the helix offset.
      // This preserves the bead's position relative to the terminal (no horizontal fanout).
      const beadPosMap = new Map()
      for (const [bpIdx, nuc] of nucMap) {
        const bead3D = nuc.backbone_position  // [x, y, z]
        beadPosMap.set(bpIdx, {
          x: bead3D[0] + helixOff.x,
          y: bead3D[1] + helixOff.y,
          z: bead3D[2],
        })
      }
      _extArcMap.set(ext.id, beadPosMap)
    }
  }

  /**
   * Refresh the straight-position anchors on existing arc entries without
   * rebuilding the arc geometry.  Called when straightGeometry changes.
   */
  function _refreshArcStraightPositions(straightPosMap) {
    if (!straightPosMap) return
    for (const e of _arcMeta) {
      const fn = e.fromNuc
      const tn = e.toNuc
      const sf = fn && straightPosMap.get(`${fn.helix_id}:${fn.bp_index}:${fn.direction}`)
      const st = tn && straightPosMap.get(`${tn.helix_id}:${tn.bp_index}:${tn.direction}`)
      if (sf) e.fromStraight = sf.clone()
      if (st) e.toStraight   = st.clone()
    }
  }

  /**
   * Update arc line vertex buffers for the current lerp factor t and offsets.
   * At t=0 the arcs are straight (bow=0).  At t=1 they bow outward ()(  shape).
   *
   * When straightPosMap is provided the straight positions are used as the
   * animation base (unfold is active, deform is off).  Without it, from3D/to3D
   * (current rendered positions, possibly deformed) are used — correct for the
   * 3D view at t=0.
   *
   * @param {number} t  lerp factor in [0, 1]
   * @param {Map<string, THREE.Vector3>} offsets  helix_id → translation (nm)
   * @param {Map<string,THREE.Vector3>|null} straightPosMap
   */

  /**
   * Resolve the unfold translation offset for one arc endpoint.
   * Real-helix endpoints → look up in `offsets` map (pre-built by _buildOffsets).
   * __ext_* endpoints → derive from _extArcMap: offset = target - base3D,
   *   so  base3D + offset * t  →  base3D at t=0  and  target at t=1.
   * Returns _ZERO_VEC when no offset is available (safe zero-multiply at t=0).
   */
  function _extArcOff(helixId, nuc, base3D, offsets, scratch) {
    if (!helixId?.startsWith('__ext_')) return offsets.get(helixId) ?? _ZERO_VEC
    const extId  = helixId.slice(6)   // '__ext_'.length === 6
    const target = _extArcMap.get(extId)?.get(nuc?.bp_index)
    if (!target) return _ZERO_VEC
    return scratch.set(target.x - base3D.x, target.y - base3D.y, target.z - base3D.z)
  }

  function _updateArcPositions(t, offsets, straightPosMap = null) {
    for (const e of _arcMeta) {
      const merged = e.merged === 'scaffold' ? _scaffoldMerged : _stapleMerged
      if (!merged) continue
      const buf  = merged.positions
      const base = e.vertIdx

      const offFrom = _extArcOff(e.fromHelixId, e.fromNuc, e.from3D, offsets, _sExtFrom)
      const offTo   = _extArcOff(e.toHelixId,   e.toNuc,   e.to3D,   offsets, _sExtTo)

      let bfx, bfy, bfz, btx, bty, btz
      if (straightPosMap) {
        const sf = e.fromStraight ?? e.from3D
        const st = e.toStraight   ?? e.to3D
        bfx = sf.x; bfy = sf.y; bfz = sf.z
        btx = st.x; bty = st.y; btz = st.z
      } else {
        const sf = e.fromStraight
        const st = e.toStraight
        if (sf) {
          bfx = sf.x + (e.from3D.x - sf.x) * _currentDeformT
          bfy = sf.y + (e.from3D.y - sf.y) * _currentDeformT
          bfz = sf.z + (e.from3D.z - sf.z) * _currentDeformT
        } else {
          bfx = e.from3D.x; bfy = e.from3D.y; bfz = e.from3D.z
        }
        if (st) {
          btx = st.x + (e.to3D.x - st.x) * _currentDeformT
          bty = st.y + (e.to3D.y - st.y) * _currentDeformT
          btz = st.z + (e.to3D.z - st.z) * _currentDeformT
        } else {
          btx = e.to3D.x; bty = e.to3D.y; btz = e.to3D.z
        }
      }

      _sv0.set(bfx + offFrom.x * t, bfy + offFrom.y * t, bfz + offFrom.z * t)
      _sv1.set(btx + offTo.x * t,   bty + offTo.y * t,   btz + offTo.z * t)

      const dist = _sv0.distanceTo(_sv1)
      const bow  = dist * MAX_BOW_FRAC * t * e.bowDir
      _sCtrl.set(
        (_sv0.x + _sv1.x) * 0.5,
        (_sv0.y + _sv1.y) * 0.5,
        (_sv0.z + _sv1.z) * 0.5 + bow,
      )

      // Sample quadratic bezier into the merged position buffer.
      for (let j = 0; j <= ARC_SEGS; j++) {
        const u  = j / ARC_SEGS
        const u2 = 1 - u
        const w0 = u2 * u2, w1 = 2 * u2 * u, w2 = u * u
        const bi = (base + j) * 3
        buf[bi]     = w0 * _sv0.x + w1 * _sCtrl.x + w2 * _sv1.x
        buf[bi + 1] = w0 * _sv0.y + w1 * _sCtrl.y + w2 * _sv1.y
        buf[bi + 2] = w0 * _sv0.z + w1 * _sCtrl.z + w2 * _sv1.z
      }
    }
    if (_scaffoldMerged) _scaffoldMerged.geo.attributes.position.needsUpdate = true
    if (_stapleMerged)   _stapleMerged.geo.attributes.position.needsUpdate   = true
  }

  // ── Offset computation ──────────────────────────────────────────────────────

  /**
   * Build a Map<helix_id, THREE.Vector3> where each Vector3 is the translation
   * that moves the helix midpoint to its unfolded row position.
   */
  function _buildOffsets(spacing) {
    const { currentDesign, unfoldHelixOrder } = store.getState()
    if (!currentDesign) return new Map()

    const allIds  = currentDesign.helices.map(h => h.id)
    const base    = unfoldHelixOrder ?? allIds
    // Append helices not in the stored order (e.g. newly-extruded overhangs).
    const baseSet = new Set(base)
    const order   = [...base, ...allIds.filter(id => !baseSet.has(id))]

    const helixMap = new Map(currentDesign.helices.map(h => [h.id, h]))
    const offsets  = new Map()

    // Compute the Z midpoint of the entire design so the camera can be aimed
    // at it when entering unfold mode.  This prevents perspective-camera
    // frustum clipping for imported designs whose helices start at non-zero
    // bp_start (e.g. caDNAno origami with bp_start=408 → axis_start.z ≈ 135 nm).
    // We do NOT translate helices in Z — instead we move the camera target to
    // midZ so the helices animate only in X/Y (no jarring Z movement).
    let minZ = Infinity, maxZ = -Infinity
    for (const helixId of order) {
      const h = helixMap.get(helixId)
      if (!h) continue
      if (h.axis_start.z < minZ) minZ = h.axis_start.z
      if (h.axis_end.z   > maxZ) maxZ = h.axis_end.z
    }
    _midZ = (minZ === Infinity) ? 0 : (minZ + maxZ) / 2

    let row = 0
    for (const helixId of order) {
      const h = helixMap.get(helixId)
      if (!h) continue

      const cx = (h.axis_start.x + h.axis_end.x) / 2
      const cy = (h.axis_start.y + h.axis_end.y) / 2

      offsets.set(helixId, new THREE.Vector3(
        -cx,                // centre at x = 0
        -row * spacing - cy, // stack downward
        0,                  // no Z translation — camera target moves to midZ instead
      ))
      row++
    }
    return offsets
  }

  // ── Animation ───────────────────────────────────────────────────────────────

  function _animate(fromT, toT, offsets, onDone) {
    if (_animFrame) { cancelAnimationFrame(_animFrame); _animFrame = null }
    const startTime = performance.now()
    _buildXbArcMap(offsets, _straightPosMap)
    _buildExtArcMap(offsets, _straightPosMap)

    function frame(now) {
      const raw = Math.min((now - startTime) / ANIM_DURATION_MS, 1)
      const t   = fromT + (toT - fromT) * raw

      designRenderer.applyUnfoldOffsets(offsets, t, _straightPosMap, _straightAxesMap)
      designRenderer.applyUnfoldOffsetsExtraBases(_xbArcMap, t)
      designRenderer.applyUnfoldOffsetsExtensions(_extArcMap, t)
      designRenderer.refreshAllGlow()
      getBluntEnds?.()?.applyUnfoldOffsets(offsets, t, _straightAxesMap)
      _updateArcPositions(t, offsets, _straightPosMap)
      _refreshArcGlow()
      getLoopSkipHighlight?.()?.applyUnfoldOffsets(offsets, t, _straightAxesMap)
      getOverhangLocations?.()?.applyUnfoldOffsets(offsets, t, _straightAxesMap)
      getCrossoverLocations?.()?.applyUnfoldOffsets(offsets, t)
      getSequenceOverlay?.()?.applyUnfoldOffsets(offsets, t, _straightPosMap, _xbArcMap)
      _slicePlane?.applyUnfoldT?.(t)
      _currentT = t

      if (raw >= 1) {
        _animFrame = null
        onDone?.()
      } else {
        _animFrame = requestAnimationFrame(frame)
      }
    }

    _animFrame = requestAnimationFrame(frame)
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  function activate() {
    _buildStraightMaps()
    const spacing = store.getState().unfoldSpacing
    const offsets = _buildOffsets(spacing)
    _active = true
    store.setState({ unfoldActive: true })
    _animate(_currentT, 1, offsets, null)
  }

  function deactivate() {
    const spacing = store.getState().unfoldSpacing
    const offsets = _buildOffsets(spacing)
    _animate(_currentT, 0, offsets, () => {
      _active = false
      store.setState({ unfoldActive: false })
      designRenderer.getHelixCtrl()?.revertToGeometry(_straightPosMap, _straightAxesMap)
      // Arcs stay visible but are now straight (t=0 → bow=0).
    })
  }

  function toggle() {
    if (_active) deactivate()
    else activate()
  }

  function setSpacing(nm) {
    store.setState({ unfoldSpacing: nm })
    if (_active) {
      const offsets = _buildOffsets(nm)
      _buildXbArcMap(offsets, _straightPosMap)
      _buildExtArcMap(offsets, _straightPosMap)
      designRenderer.applyUnfoldOffsets(offsets, 1, _straightPosMap, _straightAxesMap)
      designRenderer.applyUnfoldOffsetsExtraBases(_xbArcMap, 1)
      designRenderer.applyUnfoldOffsetsExtensions(_extArcMap, 1)
      getBluntEnds?.()?.applyUnfoldOffsets(offsets, 1, _straightAxesMap)
      _updateArcPositions(1, offsets, _straightPosMap)
      _refreshArcGlow()
      getLoopSkipHighlight?.()?.applyUnfoldOffsets(offsets, 1, _straightAxesMap)
      getOverhangLocations?.()?.applyUnfoldOffsets(offsets, 1, _straightAxesMap)
      getCrossoverLocations?.()?.applyUnfoldOffsets(offsets, 1)
      getSequenceOverlay?.()?.applyUnfoldOffsets(offsets, 1, _straightPosMap, _xbArcMap)
    }
  }

  // Rebuild arcs whenever geometry or design changes.
  // design_renderer subscribes before this, so _helixCtrl is already rebuilt.
  store.subscribe((newState, prevState) => {
    const geometryChanged = newState.currentGeometry !== prevState.currentGeometry
    const designChanged   = newState.currentDesign   !== prevState.currentDesign

    if (!geometryChanged && !designChanged) return

    // Skip arc rebuild for topology-preserving design changes (cluster-transform patches,
    // config saves, camera-pose updates, etc.).  These patch currentDesign without touching
    // geometry, so backbone_position values are stale — rebuilding arcs would reset their
    // endpoints to the pre-animation positions, undoing whatever applyClusterArcUpdate set.
    // Same guard as design_renderer.js.
    if (designChanged && !geometryChanged) {
      const p = prevState.currentDesign, n = newState.currentDesign
      if (p && n &&
          p.helices.length         === n.helices.length       &&
          p.strands.length         === n.strands.length       &&
          p.crossovers.length      === n.crossovers.length    &&
          p.deformations.length    === n.deformations.length  &&
          p.extensions.length      === n.extensions.length    &&
          p.overhangs.length       === n.overhangs.length     &&
          p.crossover_bases.length === n.crossover_bases.length) return
    }

    // Stop any running animation.
    if (_animFrame) { cancelAnimationFrame(_animFrame); _animFrame = null }

    // Rebuild arcs and re-apply helix offsets at the current lerp position so
    // that undo/redo and topology mutations stay in whatever view mode is active.
    // New-design loads are handled externally: main.js sets unfoldActive: false
    // explicitly, which triggers deactivate() via the unfoldActive listener below.
    const conns   = designRenderer.getCrossHelixConnections()
    const offsets = _buildOffsets(newState.unfoldSpacing)
    _initArcs(conns, _straightPosMap)
    _buildXbArcMap(offsets, _straightPosMap)
    _buildExtArcMap(offsets, _straightPosMap)
    _applyStapleArcVisibility()
    _updateArcPositions(_currentT, offsets, _active ? _straightPosMap : null)
    _refreshArcGlow()

    if (_active) {
      // Re-position helices and blunt ends at the current unfold fraction so
      // that the scene stays unfolded after a topology mutation (undo/redo etc).
      designRenderer.applyUnfoldOffsets(offsets, _currentT, _straightPosMap, _straightAxesMap)
      designRenderer.applyUnfoldOffsetsExtraBases(_xbArcMap, _currentT)
      designRenderer.applyUnfoldOffsetsExtensions(_extArcMap, _currentT)
      getBluntEnds?.()?.applyUnfoldOffsets(offsets, _currentT, _straightAxesMap)
      getLoopSkipHighlight?.()?.applyUnfoldOffsets(offsets, _currentT, _straightAxesMap)
      getOverhangLocations?.()?.applyUnfoldOffsets(offsets, _currentT, _straightAxesMap)
      getCrossoverLocations?.()?.applyUnfoldOffsets(offsets, _currentT)
      getSequenceOverlay?.()?.applyUnfoldOffsets(offsets, _currentT, _straightPosMap, _xbArcMap)
    }

    // Re-apply selection highlight — selection_manager fires before this
    // subscription (it subscribes earlier) so arc colors need reapplying here.
    const sel = newState.selectedObject
    if (sel?.type === 'strand' && sel.data?.strand_id) {
      for (const e of _arcMeta) {
        if (e.strandId === sel.data.strand_id) _setArcColor(e, 0xffffff)
      }
    }
  })

  // Handle unfoldActive being cleared externally (e.g. main.js on new-design
  // load sets unfoldActive: false without going through deactivate()).
  // Reset internal state so the next activate() starts clean.
  store.subscribe((newState, prevState) => {
    if (newState.unfoldActive === prevState.unfoldActive) return
    if (!newState.unfoldActive && _active) {
      if (_animFrame) { cancelAnimationFrame(_animFrame); _animFrame = null }
      _active   = false
      _currentT = 0
      designRenderer.getHelixCtrl()?.revertToGeometry(_straightPosMap, _straightAxesMap)
    }
  })

  // Rebuild straight maps when straight geometry changes (e.g. after undo while unfold is active).
  // Also refresh the straight-position anchors on existing arc entries so that
  // the unfold animation always uses up-to-date straight positions.
  store.subscribe((newState, prevState) => {
    if (newState.straightGeometry  === prevState.straightGeometry &&
        newState.straightHelixAxes === prevState.straightHelixAxes) return
    _buildStraightMaps()
    _refreshArcStraightPositions(_straightPosMap)
    // Re-draw arcs at current t using the fresh straight anchors.
    const offsets = _buildOffsets(store.getState().unfoldSpacing)
    _updateArcPositions(_currentT, offsets, _active ? _straightPosMap : null)
    _refreshArcGlow()
  })

  store.subscribe((newState, prevState) => {
    if (newState.staplesHidden !== prevState.staplesHidden) _applyStapleArcVisibility()
  })

  // Update arc colors when strand colors change (e.g. via color picker).
  store.subscribe((newState, prevState) => {
    if (newState.strandColors === prevState.strandColors) return
    if (!_arcMeta.length) return
    const oldC = prevState.strandColors ?? {}
    const newC = newState.strandColors ?? {}
    for (const e of _arcMeta) {
      if (!e.strandId) continue
      const newHex = newC[e.strandId]
      if (newHex === oldC[e.strandId]) continue
      if (newHex != null) {
        e.color = newHex
        _setArcColor(e, newHex)
      }
    }
  })

  // Update arc colors when strand group membership or group colors change.
  // design_renderer subscribes before this, so _helixCtrl is already rebuilt
  // with the new effective colors by the time this subscriber runs.
  store.subscribe((newState, prevState) => {
    if (newState.strandGroups === prevState.strandGroups) return
    if (!_arcMeta.length) return

    // Mirror _effectiveColors from design_renderer: group color overrides strandColors.
    const sc  = newState.strandColors ?? {}
    const eff = { ...sc }
    for (const g of newState.strandGroups ?? []) {
      if (g.color) {
        const hex = parseInt(g.color.replace('#', ''), 16)
        for (const sid of g.strandIds) eff[sid] = hex
      }
    }

    // For strands with no effective override (palette color), read from the
    // freshly-rebuilt helixCtrl via getCrossHelixConnections().
    const paletteMap = new Map()
    for (const c of designRenderer.getCrossHelixConnections()) {
      if (c.strandId && !(c.strandId in eff)) paletteMap.set(c.strandId, c.color)
    }

    for (const e of _arcMeta) {
      if (!e.strandId) continue
      const newHex = e.strandId in eff ? eff[e.strandId] : paletteMap.get(e.strandId)
      if (newHex == null || newHex === e.color) continue
      e.color = newHex
      _setArcColor(e, newHex)
    }
  })

  return {
    toggle,
    activate,
    deactivate,
    setSpacing,
    isActive:  () => _active,
    getMidZ:   () => _midZ,
    setSlicePlane(sp) { _slicePlane = sp },

    /**
     * Re-apply the current unfold offsets to helices and blunt ends without
     * animating.  Called by blunt_ends after it rebuilds so that label sprites
     * land at their unfolded positions rather than the 3D geometry positions.
     */
    /**
     * Called by deform_view during the deform lerp animation so arcs track
     * the same straight↔deformed transition as the backbone beads.
     * Unfold is always blocked when deform is active, so offsets are zero.
     *
     * @param {Map<string,THREE.Vector3>|null} straightPosMap
     * @param {number} deformT  0 = straight, 1 = deformed
     */
    /**
     * Shift arc endpoints by per-helix translation offsets without entering
     * unfold mode.  Used by expanded spacing (Q) so arcs follow the helices
     * when the design is laterally expanded.
     *
     * Only has an effect when unfold is NOT active (the two views are mutually
     * exclusive; when unfold activates, expanded spacing is forced off).
     *
     * @param {Map<string, THREE.Vector3>} offsets  helix_id → translation delta
     * @param {number} t  animation progress [0, 1]
     */
    applyHelixOffsets(offsets, t) {
      if (_active) return
      _updateArcPositions(t, offsets, null)
      _refreshArcGlow()
    },

    applyDeformLerp(straightPosMap, deformT) {
      if (straightPosMap) _refreshArcStraightPositions(straightPosMap)
      _currentDeformT = deformT
      // Re-draw arcs at t_unfold=0 with no offsets; _updateArcPositions uses
      // _currentDeformT to lerp the base positions.
      _updateArcPositions(0, new Map(), null)
      _refreshArcGlow()
    },

    reapplyIfActive() {
      if (!_active) return
      const offsets = _buildOffsets(store.getState().unfoldSpacing)
      _buildXbArcMap(offsets, _straightPosMap)
      _buildExtArcMap(offsets, _straightPosMap)
      designRenderer.applyUnfoldOffsets(offsets, _currentT, _straightPosMap, _straightAxesMap)
      designRenderer.applyUnfoldOffsetsExtraBases(_xbArcMap, _currentT)
      designRenderer.applyUnfoldOffsetsExtensions(_extArcMap, _currentT)
      getBluntEnds?.()?.applyUnfoldOffsets(offsets, _currentT, _straightAxesMap)
      getLoopSkipHighlight?.()?.applyUnfoldOffsets(offsets, _currentT, _straightAxesMap)
      getOverhangLocations?.()?.applyUnfoldOffsets(offsets, _currentT, _straightAxesMap)
      getCrossoverLocations?.()?.applyUnfoldOffsets(offsets, _currentT)
      _updateArcPositions(_currentT, offsets, _straightPosMap)
      _refreshArcGlow()
      getSequenceOverlay?.()?.applyUnfoldOffsets(offsets, _currentT, _straightPosMap, _xbArcMap)
    },

    /**
     * Return a live view of arc entries for selection / proximity detection.
     * Each entry exposes getMidWorld() and setColor() for the selection manager.
     *
     * @returns {Array<{strandId, fromNuc, toNuc, defaultColor, getMidWorld, setColor}>}
     */
    getArcEntries() {
      return _arcMeta.map(e => ({
        strandId:     e.strandId,
        fromNuc:      e.fromNuc,
        toNuc:        e.toNuc,
        defaultColor: e.color,
        crossover_id: e.crossover_id,
        getMidWorld() {
          const merged = e.merged === 'scaffold' ? _scaffoldMerged : _stapleMerged
          if (!merged) return new THREE.Vector3()
          const bi = (e.vertIdx + Math.floor(ARC_SEGS / 2)) * 3
          return new THREE.Vector3(merged.positions[bi], merged.positions[bi + 1], merged.positions[bi + 2])
        },
        setColor(hex) { _setArcColor(e, hex) },
        /** Write the ARC_SEGS+1 vertex positions for this arc into entries[], starting at startIdx. */
        _readPositionsInto(entries, startIdx) {
          const merged = e.merged === 'scaffold' ? _scaffoldMerged : _stapleMerged
          if (!merged) return
          for (let v = 0; v <= ARC_SEGS; v++) {
            const i = (e.vertIdx + v) * 3
            entries[startIdx + v]?.pos.set(
              merged.positions[i],
              merged.positions[i + 1],
              merged.positions[i + 2],
            )
          }
        },
      }))
    },

    /**
     * Show or clear the radioactive glow on selected crossover arcs.
     * Pass the arc wrapper objects returned by getArcEntries(), or [] to clear.
     */
    updateArcGlow(selectedArcs) {
      _arcGlowArcs = selectedArcs ?? []
      if (!_arcGlowArcs.length) {
        _arcGlowEntries = []
        _arcGlowLayer.clear()
        return
      }
      _arcGlowEntries = _arcGlowArcs.flatMap(() =>
        Array.from({ length: ARC_SEGS + 1 }, () => ({ pos: new THREE.Vector3() }))
      )
      let ei = 0
      for (const arc of _arcGlowArcs) {
        arc._readPositionsInto?.(_arcGlowEntries, ei)
        ei += ARC_SEGS + 1
      }
      _arcGlowLayer.setEntries(_arcGlowEntries)
    },

    /**
     * Update arc endpoints for helices that just moved via a cluster transform,
     * then redraw.  Call this once per animation tick after applyClusterTransform.
     *
     * @param {string[]} helixIds  IDs of helices whose beads have been repositioned.
     */
    applyClusterArcUpdate(helixIds) {
      if (!_arcMeta.length) return
      const helixSet  = new Set(helixIds)
      const helixCtrl = designRenderer.getHelixCtrl?.()
      if (!helixCtrl) return

      // Returns true if helixId (real or __ext_*) belongs to the moving cluster.
      // __ext_* helices are checked via their parent real helix ID.
      const _isAff = (helixId) =>
        helixSet.has(helixId) ||
        (helixId?.startsWith('__ext_') &&
         helixSet.has(helixCtrl.getExtParentHelixId?.(helixId)))

      let changed = false
      for (const e of _arcMeta) {
        const fromAff = _isAff(e.fromHelixId)
        const toAff   = _isAff(e.toHelixId)
        if (!fromAff && !toAff) continue
        if (fromAff && e.fromNuc) {
          const pos = helixCtrl.getNucLivePos(e.fromNuc)
          if (pos) { e.from3D.copy(pos); changed = true }
        }
        if (toAff && e.toNuc) {
          const pos = helixCtrl.getNucLivePos(e.toNuc)
          if (pos) { e.to3D.copy(pos); changed = true }
        }
      }
      if (changed) { _updateArcPositions(0, new Map(), null); _refreshArcGlow() }
    },

    /**
     * Update extension bead positions for helices that just moved via a cluster
     * transform, then re-apply unfold offsets so the beads stay at their correct
     * 2D positions.  Call this once per animation tick after applyClusterTransform.
     *
     * In 3D mode the beads are already moved by applyClusterTransform step 1b so
     * nothing is done.  In unfold mode (t > 0), applyClusterTransform step 1b
     * moves the beads to 3D cluster positions; this function re-applies the 2D
     * unfold targets from _extArcMap (recomputed from the live terminus position).
     *
     * @param {string[]} helixIds  IDs of helices whose beads have been repositioned.
     */
    applyClusterExtArcUpdate(helixIds) {
      if (!_active || !_extTermInfo.size) return
      const helixSet  = new Set(helixIds)
      const helixCtrl = designRenderer.getHelixCtrl?.()
      if (!helixCtrl) return

      const offsets = _buildOffsets(store.getState().unfoldSpacing)
      let changed = false

      for (const [extId, info] of _extTermInfo) {
        if (!helixSet.has(info.helixId)) continue
        const beadMap = _extArcMap.get(extId)
        if (!beadMap) continue

        // Read the live terminus position (updated by applyClusterTransform step 1).
        const livePos = helixCtrl.getNucLivePos(info.termNuc)
        if (!livePos) continue

        // Re-derive the 2D unfold base from the live terminus + (stale) helix offset.
        // helixOff = -midAxis + (0, row*spacing, 0).  For translation-only cluster
        // moves, livePos.x + helixOff.x == livePos.x - oldMid.x, which still gives
        // the correct x-offset of the terminus within the helix row.
        const helixOff = offsets.get(info.helixId) ?? _ZERO_VEC
        const baseX = livePos.x + helixOff.x
        const baseY = livePos.y + helixOff.y

        for (const [bpIdx, pos] of beadMap) {
          const rel = info.relOffsets?.get(bpIdx)
          if (rel) {
            pos.x = baseX + rel.x
            pos.y = baseY + rel.y
            pos.z = livePos.z + rel.z
          } else {
            // Fallback: horizontal fanout (pre-fix behaviour)
            const dist = (bpIdx + 1) * 0.34
            pos.x = baseX + info.sign * dist
            pos.y = baseY
            pos.z = livePos.z
          }
        }
        changed = true
      }

      if (changed) {
        if (window.__extDebugWatch) {
          // Log: _extArcMap targets (just computed) and live entry.pos after application.
          const mapTargets = new Map()
          for (const [eid, bm] of _extArcMap) {
            const sorted = [...bm.entries()].sort((a, b) => a[0] - b[0])
            if (sorted.length) {
              const [fi, fp] = sorted[0]; const [li, lp] = sorted[sorted.length - 1]
              mapTargets.set(eid, { first: { bp: fi, x: fp.x, y: fp.y, z: fp.z }, last: { bp: li, x: lp.x, y: lp.y, z: lp.z } })
            }
          }
          designRenderer.applyUnfoldOffsetsExtensions(_extArcMap, _currentT)
          const liveAfter = new Map()
          for (const e of (designRenderer.getBackboneEntries?.() ?? [])) {
            if (!e.nuc.helix_id?.startsWith('__ext_')) continue
            if (!liveAfter.has(e.nuc.extension_id)) liveAfter.set(e.nuc.extension_id, [])
            liveAfter.get(e.nuc.extension_id).push({ bp: e.nuc.bp_index, x: e.pos.x, y: e.pos.y, z: e.pos.z })
          }
          console.groupCollapsed(`[extDebug] applyClusterExtArcUpdate  t=${_currentT.toFixed(2)}`)
          for (const [eid, beads] of liveAfter) {
            beads.sort((a, b) => a.bp - b.bp)
            const tgt = mapTargets.get(eid)
            const f = beads[0], l = beads[beads.length - 1]
            const fmt = v => `(${v.x.toFixed(3)}, ${v.y.toFixed(3)}, ${v.z.toFixed(3)})`
            console.log(`  ${eid}`)
            console.log(`    first  target=${fmt(tgt?.first ?? f)}  live=${fmt(f)}`)
            console.log(`    last   target=${fmt(tgt?.last  ?? l)}  live=${fmt(l)}`)
          }
          console.groupEnd()
        } else {
          designRenderer.applyUnfoldOffsetsExtensions(_extArcMap, _currentT)
        }
      }
    },

    /** Return a shallow copy of _extArcMap for debugging. */
    getExtArcMap() { return _extArcMap },

    /** Dev — returns _arcMeta entries that have a __ext_* endpoint. */
    getExtArcMeta() {
      return _arcMeta.filter(e =>
        e.fromHelixId?.startsWith('__ext_') || e.toHelixId?.startsWith('__ext_'))
    },

    /**
     * Read the rendered first+last vertex positions for each ext arc from the
     * merged geometry buffer.  Used by __arcDebug.snapRendered() in main.js.
     */
    getExtArcRenderedEndpoints() {
      const out = []
      for (const e of _arcMeta) {
        if (!e.fromHelixId?.startsWith('__ext_') && !e.toHelixId?.startsWith('__ext_')) continue
        const merged = e.merged === 'scaffold' ? _scaffoldMerged : _stapleMerged
        if (!merged) continue
        const buf = merged.positions
        const fi  = e.vertIdx              // first vertex in this arc's segment
        const li  = e.vertIdx + ARC_SEGS   // last vertex
        out.push({
          fromHelixId:  e.fromHelixId,
          toHelixId:    e.toHelixId,
          renderedFrom: { x: buf[fi * 3], y: buf[fi * 3 + 1], z: buf[fi * 3 + 2] },
          renderedTo:   { x: buf[li * 3], y: buf[li * 3 + 1], z: buf[li * 3 + 2] },
        })
      }
      return out
    },

    setArcsVisible(visible) {
      _arcGroup.visible = visible
    },

    dispose() {
      if (_animFrame) cancelAnimationFrame(_animFrame)
      _clearArcs()
      _arcGlowLayer.dispose()
      scene.remove(_arcGroup)
    },
  }
}
