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

export function initUnfoldView(scene, designRenderer, getBluntEnds) {
  let _active     = false
  let _animFrame  = null
  let _currentT   = 0

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
   * The bow direction is computed from the pair grouping using 3D Z positions
   * (this gives the correct )(  divergence once unfolded).
   *
   * @param {Array<{from, to, color, fromHelixId, toHelixId}>} connections
   */
  function _initArcs(connections) {
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

        _arcEntries.push({
          pts, geo, line,
          from3D:      conn.from.clone(),
          to3D:        conn.to.clone(),
          fromHelixId: conn.fromHelixId,
          toHelixId:   conn.toHelixId,
          bowDir,
          color:       conn.color ?? 0x00ccff,
          strandId:    conn.strandId ?? null,
          fromNuc:     conn.fromNuc,
          toNuc:       conn.toNuc,
        })
      }
    }
  }

  /**
   * Update arc line vertex buffers for the current lerp factor t and offsets.
   * At t=0 the arcs are straight (bow=0).  At t=1 they bow outward ()(  shape).
   *
   * @param {number} t  lerp factor in [0, 1]
   * @param {Map<string, THREE.Vector3>} offsets  helix_id → translation (nm)
   */
  function _updateArcPositions(t, offsets) {
    for (const e of _arcEntries) {
      const offFrom = offsets.get(e.fromHelixId) ?? _ZERO_VEC
      const offTo   = offsets.get(e.toHelixId)   ?? _ZERO_VEC

      _sv0.set(
        e.from3D.x + offFrom.x * t,
        e.from3D.y + offFrom.y * t,
        e.from3D.z + offFrom.z * t,
      )
      _sv1.set(
        e.to3D.x + offTo.x * t,
        e.to3D.y + offTo.y * t,
        e.to3D.z + offTo.z * t,
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

    const order = unfoldHelixOrder
      ?? currentDesign.helices.map(h => h.id)

    const helixMap = new Map(currentDesign.helices.map(h => [h.id, h]))
    const offsets  = new Map()

    let row = 0
    for (const helixId of order) {
      const h = helixMap.get(helixId)
      if (!h) continue

      const cx = (h.axis_start.x + h.axis_end.x) / 2
      const cy = (h.axis_start.y + h.axis_end.y) / 2

      offsets.set(helixId, new THREE.Vector3(
        -cx,                   // centre at x = 0
        -row * spacing - cy,   // stack downward
        0,                     // keep z unchanged
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

      designRenderer.applyUnfoldOffsets(offsets, t)
      getBluntEnds?.()?.applyUnfoldOffsets(offsets, t)
      _updateArcPositions(t, offsets)
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
      designRenderer.getHelixCtrl()?.revertToGeometry()
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
      designRenderer.applyUnfoldOffsets(offsets, 1)
      getBluntEnds?.()?.applyUnfoldOffsets(offsets, 1)
      _updateArcPositions(1, offsets)
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
    _initArcs(conns)
    _updateArcPositions(_currentT, offsets)

    if (_active) {
      // Re-position helices and blunt ends at the current unfold fraction so
      // that the scene stays unfolded after a topology mutation (undo/redo etc).
      designRenderer.applyUnfoldOffsets(offsets, _currentT)
      getBluntEnds?.()?.applyUnfoldOffsets(offsets, _currentT)
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
      designRenderer.getHelixCtrl()?.revertToGeometry()
    }
  })

  return {
    toggle,
    activate,
    deactivate,
    setSpacing,
    isActive: () => _active,

    /**
     * Re-apply the current unfold offsets to helices and blunt ends without
     * animating.  Called by blunt_ends after it rebuilds so that label sprites
     * land at their unfolded positions rather than the 3D geometry positions.
     */
    reapplyIfActive() {
      if (!_active) return
      const offsets = _buildOffsets(store.getState().unfoldSpacing)
      designRenderer.applyUnfoldOffsets(offsets, _currentT)
      getBluntEnds?.()?.applyUnfoldOffsets(offsets, _currentT)
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

    dispose() {
      if (_animFrame) cancelAnimationFrame(_animFrame)
      _clearArcs()
      scene.remove(_arcGroup)
    },
  }
}
