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

const ANIM_DURATION_MS = 500   // linear lerp duration
const ARC_SEGS         = 20    // bezier sample count per arc line
const MAX_BOW_FRAC     = 0.15  // control point bows dist × frac at full unfold

const _ZERO_VEC = new THREE.Vector3(0, 0, 0)

// Scratch vectors reused each frame (never held across async boundaries).
const _sv0   = new THREE.Vector3()
const _sv1   = new THREE.Vector3()
const _sCtrl = new THREE.Vector3()

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
  function _updateArcPositions(t, offsets, straightPosMap = null) {
    for (const e of _arcMeta) {
      const merged = e.merged === 'scaffold' ? _scaffoldMerged : _stapleMerged
      if (!merged) continue
      const buf  = merged.positions
      const base = e.vertIdx

      const offFrom = offsets.get(e.fromHelixId) ?? _ZERO_VEC
      const offTo   = offsets.get(e.toHelixId)   ?? _ZERO_VEC

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

    function frame(now) {
      const raw = Math.min((now - startTime) / ANIM_DURATION_MS, 1)
      const t   = fromT + (toT - fromT) * raw

      designRenderer.applyUnfoldOffsets(offsets, t, _straightPosMap, _straightAxesMap)
      designRenderer.applyUnfoldOffsetsExtraBases(_xbArcMap, t)
      getBluntEnds?.()?.applyUnfoldOffsets(offsets, t, _straightAxesMap)
      _updateArcPositions(t, offsets, _straightPosMap)
      getLoopSkipHighlight?.()?.applyUnfoldOffsets(offsets, t, _straightAxesMap)
      getOverhangLocations?.()?.applyUnfoldOffsets(offsets, t, _straightAxesMap)
      getCrossoverLocations?.()?.applyUnfoldOffsets(offsets, t)
      getSequenceOverlay?.()?.applyUnfoldOffsets(offsets, t, _straightPosMap)
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
      designRenderer.applyUnfoldOffsets(offsets, 1, _straightPosMap, _straightAxesMap)
      designRenderer.applyUnfoldOffsetsExtraBases(_xbArcMap, 1)
      getBluntEnds?.()?.applyUnfoldOffsets(offsets, 1, _straightAxesMap)
      _updateArcPositions(1, offsets, _straightPosMap)
      getLoopSkipHighlight?.()?.applyUnfoldOffsets(offsets, 1, _straightAxesMap)
      getOverhangLocations?.()?.applyUnfoldOffsets(offsets, 1, _straightAxesMap)
      getCrossoverLocations?.()?.applyUnfoldOffsets(offsets, 1)
      getSequenceOverlay?.()?.applyUnfoldOffsets(offsets, 1, _straightPosMap)
    }
  }

  // Rebuild arcs whenever geometry or design changes.
  // design_renderer subscribes before this, so _helixCtrl is already rebuilt.
  store.subscribe((newState, prevState) => {
    const geometryChanged = newState.currentGeometry !== prevState.currentGeometry
    const designChanged   = newState.currentDesign   !== prevState.currentDesign

    if (!geometryChanged && !designChanged) return

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
    _applyStapleArcVisibility()
    _updateArcPositions(_currentT, offsets, _active ? _straightPosMap : null)

    if (_active) {
      // Re-position helices and blunt ends at the current unfold fraction so
      // that the scene stays unfolded after a topology mutation (undo/redo etc).
      designRenderer.applyUnfoldOffsets(offsets, _currentT, _straightPosMap, _straightAxesMap)
      designRenderer.applyUnfoldOffsetsExtraBases(_xbArcMap, _currentT)
      getBluntEnds?.()?.applyUnfoldOffsets(offsets, _currentT, _straightAxesMap)
      getLoopSkipHighlight?.()?.applyUnfoldOffsets(offsets, _currentT, _straightAxesMap)
      getOverhangLocations?.()?.applyUnfoldOffsets(offsets, _currentT, _straightAxesMap)
      getCrossoverLocations?.()?.applyUnfoldOffsets(offsets, _currentT)
      getSequenceOverlay?.()?.applyUnfoldOffsets(offsets, _currentT, _straightPosMap)
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
    applyDeformLerp(straightPosMap, deformT) {
      if (straightPosMap) _refreshArcStraightPositions(straightPosMap)
      _currentDeformT = deformT
      // Re-draw arcs at t_unfold=0 with no offsets; _updateArcPositions uses
      // _currentDeformT to lerp the base positions.
      _updateArcPositions(0, new Map(), null)
    },

    reapplyIfActive() {
      if (!_active) return
      const offsets = _buildOffsets(store.getState().unfoldSpacing)
      _buildXbArcMap(offsets, _straightPosMap)
      designRenderer.applyUnfoldOffsets(offsets, _currentT, _straightPosMap, _straightAxesMap)
      designRenderer.applyUnfoldOffsetsExtraBases(_xbArcMap, _currentT)
      getBluntEnds?.()?.applyUnfoldOffsets(offsets, _currentT, _straightAxesMap)
      getLoopSkipHighlight?.()?.applyUnfoldOffsets(offsets, _currentT, _straightAxesMap)
      getOverhangLocations?.()?.applyUnfoldOffsets(offsets, _currentT, _straightAxesMap)
      getCrossoverLocations?.()?.applyUnfoldOffsets(offsets, _currentT)
      _updateArcPositions(_currentT, offsets, _straightPosMap)
      getSequenceOverlay?.()?.applyUnfoldOffsets(offsets, _currentT, _straightPosMap)
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
      }))
    },

    setArcsVisible(visible) {
      _arcGroup.visible = visible
    },

    dispose() {
      if (_animFrame) cancelAnimationFrame(_animFrame)
      _clearArcs()
      scene.remove(_arcGroup)
    },
  }
}
