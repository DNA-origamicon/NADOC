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

export function initUnfoldView(scene, designRenderer, getBluntEnds, getLoopSkipHighlight, getSequenceOverlay, getOverhangLocations) {
  let _active       = false
  let _animFrame    = null
  let _currentT     = 0
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

  // ── Arc entries ─────────────────────────────────────────────────────────────
  // Each entry stores the original 3D positions (from3D / to3D) and bow
  // direction so that _updateArcPositions can compute lerped positions each
  // frame without re-querying the design renderer.

  /**
   * @typedef {{
   *   pts:         Float32Array,
   *   geo:         THREE.BufferGeometry,
   *   line:        THREE.Line,
   *   from3D:      THREE.Vector3,
   *   to3D:        THREE.Vector3,
   *   fromHelixId: string,
   *   toHelixId:   string,
   *   bowDir:      number,   // +1 or -1
   *   color:       number,
   *   strandId:    string|null,
   *   fromNuc:     object,
   *   toNuc:       object,
   * }} ArcEntry
   * @type {ArcEntry[]}
   */
  let _arcEntries = []

  // ── Arc management ──────────────────────────────────────────────────────────

  function _applyStapleArcVisibility() {
    const hidden = store.getState().staplesHidden
    for (const e of _arcEntries) {
      if (e.fromNuc?.strand_type === 'scaffold') continue
      e.line.visible = !hidden
    }
  }

  function _clearArcs() {
    for (const e of _arcEntries) {
      _arcGroup.remove(e.line)
      e.geo.dispose()
      e.line.material.dispose()
    }
    _arcEntries = []
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

    // Group by sorted helix pair to determine bow direction.
    const groups = new Map()
    for (const conn of connections) {
      const key = [conn.fromHelixId, conn.toHelixId].sort().join('|')
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key).push(conn)
    }

    for (const conns of groups.values()) {
      // Centre Z of this group (computed from 3D positions, remains fixed).
      const groupCenterZ = conns.reduce((s, c) => s + (c.from.z + c.to.z) / 2, 0) / conns.length

      for (let ci = 0; ci < conns.length; ci++) {
        const conn = conns[ci]
        const arcZ = (conn.from.z + conn.to.z) / 2
        // Single arc → bow +Z.
        // Paired arcs → `()` shape: arc closer to −Z bows −Z, arc closer to +Z
        // bows +Z, so they diverge outward away from each other.  When both arcs
        // share the same Z (rare), fall back to index-based alternation.
        let bowDir
        if (conns.length < 2) {
          bowDir = 1
        } else {
          const zSign = Math.sign(arcZ - groupCenterZ)
          bowDir = zSign !== 0 ? zSign : (ci % 2 === 0 ? 1 : -1)
        }

        const pts = new Float32Array((ARC_SEGS + 1) * 3)
        const geo = new THREE.BufferGeometry()
        geo.setAttribute('position', new THREE.BufferAttribute(pts, 3))
        const mat  = new THREE.LineBasicMaterial({
          color:       conn.color ?? 0x00ccff,
          opacity:     0.85,
          transparent: true,
        })
        const line = new THREE.Line(geo, mat)
        line.frustumCulled = false
        _arcGroup.add(line)

        // Straight positions — used as unfold base so arcs animate from straight
        // geometry even when the design is currently in a deformed state.
        const fn = conn.fromNuc
        const tn = conn.toNuc
        const sf = fn && straightPosMap?.get(`${fn.helix_id}:${fn.bp_index}:${fn.direction}`)
        const st = tn && straightPosMap?.get(`${tn.helix_id}:${tn.bp_index}:${tn.direction}`)

        _arcEntries.push({
          pts, geo, line,
          from3D:        conn.from.clone(),
          to3D:          conn.to.clone(),
          fromStraight:  sf ? sf.clone() : null,
          toStraight:    st ? st.clone() : null,
          fromHelixId:   conn.fromHelixId,
          toHelixId:     conn.toHelixId,
          bowDir,
          color:         conn.color ?? 0x00ccff,
          strandId:      conn.strandId ?? null,
          fromNuc:       conn.fromNuc,
          toNuc:         conn.toNuc,
        })
      }
    }
  }

  /**
   * Refresh the straight-position anchors on existing arc entries without
   * rebuilding the arc geometry.  Called when straightGeometry changes.
   */
  function _refreshArcStraightPositions(straightPosMap) {
    if (!straightPosMap) return
    for (const e of _arcEntries) {
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
    for (const e of _arcEntries) {
      const offFrom = offsets.get(e.fromHelixId) ?? _ZERO_VEC
      const offTo   = offsets.get(e.toHelixId)   ?? _ZERO_VEC

      // Choose base endpoint positions:
      //   - Unfold active (straightPosMap provided): use straight positions as
      //     the translation base (deform is always off when unfold is on).
      //   - 3D view (no straightPosMap): lerp between straight and deformed
      //     positions using _currentDeformT so arcs track the deform animation.
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

      _sv0.set(
        bfx + offFrom.x * t,
        bfy + offFrom.y * t,
        bfz + offFrom.z * t,
      )
      _sv1.set(
        btx + offTo.x * t,
        bty + offTo.y * t,
        btz + offTo.z * t,
      )

      // Control point: midpoint bowed outward in Z, scaled by t.
      const dist = _sv0.distanceTo(_sv1)
      const bow  = dist * MAX_BOW_FRAC * t * e.bowDir
      _sCtrl.set(
        (_sv0.x + _sv1.x) * 0.5,
        (_sv0.y + _sv1.y) * 0.5,
        (_sv0.z + _sv1.z) * 0.5 + bow,
      )

      // Sample quadratic bezier: B(u) = (1−u)²P₀ + 2(1−u)uP₁ + u²P₂
      const pts = e.pts
      for (let j = 0; j <= ARC_SEGS; j++) {
        const u  = j / ARC_SEGS
        const u2 = 1 - u
        const w0 = u2 * u2
        const w1 = 2 * u2 * u
        const w2 = u * u
        const idx = j * 3
        pts[idx]     = w0 * _sv0.x + w1 * _sCtrl.x + w2 * _sv1.x
        pts[idx + 1] = w0 * _sv0.y + w1 * _sCtrl.y + w2 * _sv1.y
        pts[idx + 2] = w0 * _sv0.z + w1 * _sCtrl.z + w2 * _sv1.z
      }
      e.geo.attributes.position.needsUpdate = true
    }
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

    function frame(now) {
      const raw = Math.min((now - startTime) / ANIM_DURATION_MS, 1)
      const t   = fromT + (toT - fromT) * raw

      designRenderer.applyUnfoldOffsets(offsets, t, _straightPosMap, _straightAxesMap)
      getBluntEnds?.()?.applyUnfoldOffsets(offsets, t, _straightAxesMap)
      _updateArcPositions(t, offsets, _straightPosMap)
      getLoopSkipHighlight?.()?.applyUnfoldOffsets(offsets, t, _straightAxesMap)
      getOverhangLocations?.()?.applyUnfoldOffsets(offsets, t, _straightAxesMap)
      getSequenceOverlay?.()?.applyUnfoldOffsets(offsets, t, _straightPosMap)
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
      designRenderer.applyUnfoldOffsets(offsets, 1, _straightPosMap, _straightAxesMap)
      getBluntEnds?.()?.applyUnfoldOffsets(offsets, 1, _straightAxesMap)
      _updateArcPositions(1, offsets, _straightPosMap)
      getLoopSkipHighlight?.()?.applyUnfoldOffsets(offsets, 1, _straightAxesMap)
      getOverhangLocations?.()?.applyUnfoldOffsets(offsets, 1, _straightAxesMap)
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
    _applyStapleArcVisibility()
    _updateArcPositions(_currentT, offsets, _active ? _straightPosMap : null)

    if (_active) {
      // Re-position helices and blunt ends at the current unfold fraction so
      // that the scene stays unfolded after a topology mutation (undo/redo etc).
      designRenderer.applyUnfoldOffsets(offsets, _currentT, _straightPosMap, _straightAxesMap)
      getBluntEnds?.()?.applyUnfoldOffsets(offsets, _currentT, _straightAxesMap)
      getLoopSkipHighlight?.()?.applyUnfoldOffsets(offsets, _currentT, _straightAxesMap)
      getOverhangLocations?.()?.applyUnfoldOffsets(offsets, _currentT, _straightAxesMap)
      getSequenceOverlay?.()?.applyUnfoldOffsets(offsets, _currentT, _straightPosMap)
    }

    // Re-apply selection highlight — selection_manager fires before this
    // subscription (it subscribes earlier) so arc colors need reapplying here.
    const sel = newState.selectedObject
    if (sel?.type === 'strand' && sel.data?.strand_id) {
      for (const e of _arcEntries) {
        if (e.strandId === sel.data.strand_id) {
          e.line.material.color.setHex(0xffffff)
        }
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

  return {
    toggle,
    activate,
    deactivate,
    setSpacing,
    isActive:  () => _active,
    getMidZ:   () => _midZ,

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
      designRenderer.applyUnfoldOffsets(offsets, _currentT, _straightPosMap, _straightAxesMap)
      getBluntEnds?.()?.applyUnfoldOffsets(offsets, _currentT, _straightAxesMap)
      getOverhangLocations?.()?.applyUnfoldOffsets(offsets, _currentT, _straightAxesMap)
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
      return _arcEntries.map(e => ({
        strandId:     e.strandId,
        fromNuc:      e.fromNuc,
        toNuc:        e.toNuc,
        defaultColor: e.color,
        // Current animated midpoint (middle sample of the bezier buffer).
        getMidWorld() {
          const idx = Math.floor(ARC_SEGS / 2) * 3
          return new THREE.Vector3(e.pts[idx], e.pts[idx + 1], e.pts[idx + 2])
        },
        setColor(hex) {
          e.line.material.color.setHex(hex)
        },
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
