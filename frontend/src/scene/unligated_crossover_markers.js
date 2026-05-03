/**
 * Unligated crossover markers — amber ⚠ sprites at the midpoint of each
 * crossover that the backend left unligated because joining its two halves
 * would close a strand into a circle (not a first-class concept in the model).
 *
 * Backend's `unligated_crossover_ids` field on every design-bearing response
 * drives the marker set. Recomputed every response, so the marker auto-clears
 * when the user nicks the affected strand to break the cycle.
 *
 * Two-phase update:
 *   - rebuild(design, geometry, unligatedIds)   — runs on store changes.
 *     Computes the topology key pairs (helix:bp:dir for each half) and
 *     allocates sprites. Initial positions come from the static geometry
 *     payload's nuc.backbone_position.
 *   - refreshPositions(helixCtrl)               — runs every render frame.
 *     Re-reads live bead positions via helixCtrl.lookupEntry and updates
 *     each sprite. This makes the markers track their crossovers through
 *     unfold view, cadnano view, expanded helix spacing, deform tool,
 *     cluster transform, and any other view/transform that mutates bead
 *     positions in place.
 *
 * Architecturally identical to glow_layer.js: one Sprite per marker, a shared
 * canvas-rendered glyph texture, additive-style transparent material so the
 * marker reads against any backdrop.
 */

import * as THREE from 'three'

// Amber matches the broken-delta ⚠ used in feature_log_panel for consistency.
const MARKER_COLOR = '#f5a623'
const MARKER_SCALE = 4.0   // nm — chosen to be clearly visible in 60 nm-scale designs without overwhelming clusters

// One canvas texture, rendered once at module load.
const _TEXTURE = (() => {
  const SIZE = 128
  const canvas = document.createElement('canvas')
  canvas.width = SIZE
  canvas.height = SIZE
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, SIZE, SIZE)
  // Soft shadow so the glyph reads against pale + dark surfaces.
  ctx.shadowColor = 'rgba(0, 0, 0, 0.6)'
  ctx.shadowBlur  = 8
  ctx.fillStyle   = MARKER_COLOR
  ctx.font        = 'bold 96px sans-serif'
  ctx.textAlign   = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText('⚠', SIZE / 2, SIZE / 2 + 4)
  const tex = new THREE.CanvasTexture(canvas)
  tex.needsUpdate = true
  return tex
})()

// Pixel distance below which a marker fades so the user can see the
// crossover beneath it. Linear ramp from full opacity at FADE_OUTER_PX to
// FADE_MIN at FADE_INNER_PX.
const FADE_INNER_PX = 12
const FADE_OUTER_PX = 60
const FADE_MIN      = 0.2

function _newMaterial() {
  // One material per sprite so each can fade independently when the cursor
  // hovers over it. A shared material would tie all marker opacities together.
  return new THREE.SpriteMaterial({
    map: _TEXTURE,
    transparent: true,
    depthTest: false,   // always visible, even behind beads/slabs
    depthWrite: false,
    opacity: 1,
  })
}

export function initUnligatedCrossoverMarkers(scene) {
  let _sprites = []   // pool of THREE.Sprite — each has its own material
  // One entry per VISIBLE marker — { keyA, keyB, fallback: [x,y,z] }.
  // refreshPositions iterates this list to read live bead positions; the
  // fallback array is the static geometry midpoint used when helixCtrl
  // can't resolve a key (e.g. before the renderer has built its lookup).
  let _markers = []

  // Reusable scratch — refreshPositions allocates none.
  const _proj = new THREE.Vector3()

  function _ensurePool(n) {
    while (_sprites.length < n) {
      const s = new THREE.Sprite(_newMaterial())
      s.scale.setScalar(MARKER_SCALE)
      s.renderOrder = 1000   // late, so it draws over arcs/beads
      s.visible = false
      scene.add(s)
      _sprites.push(s)
    }
  }

  return {
    /**
     * Rebuild markers from the current design + geometry + unligated set.
     * Sets up the topology key pairs and seeds initial sprite positions
     * from the static geometry payload. Subsequent refreshPositions calls
     * keep the sprites pinned to live bead positions.
     */
    rebuild(design, geometry, unligatedIds) {
      const ids = unligatedIds instanceof Set
        ? unligatedIds
        : new Set(unligatedIds ?? [])
      const xovers = design?.crossovers ?? []
      _markers = []
      if (!geometry?.length || !ids.size || !xovers.length) {
        for (const s of _sprites) s.visible = false
        return
      }
      const nucMap = new Map()
      for (const nuc of geometry) {
        nucMap.set(`${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`, nuc)
      }
      for (const xo of xovers) {
        if (!ids.has(xo.id)) continue
        const ka = `${xo.half_a.helix_id}:${xo.half_a.index}:${xo.half_a.strand}`
        const kb = `${xo.half_b.helix_id}:${xo.half_b.index}:${xo.half_b.strand}`
        const a = nucMap.get(ka)
        const b = nucMap.get(kb)
        if (!a || !b) continue
        const ap = a.backbone_position
        const bp = b.backbone_position
        _markers.push({
          keyA: ka, keyB: kb,
          fallback: [(ap[0] + bp[0]) * 0.5, (ap[1] + bp[1]) * 0.5, (ap[2] + bp[2]) * 0.5],
        })
      }
      _ensurePool(_markers.length)
      for (let i = 0; i < _sprites.length; i++) {
        const s = _sprites[i]
        if (i < _markers.length) {
          s.position.fromArray(_markers[i].fallback)
          s.visible = true
        } else {
          s.visible = false
        }
      }
    },

    /**
     * Per-frame: re-read live bead positions for each marker and pin the
     * sprite to the midpoint. helixCtrl.lookupEntry returns the live entry
     * whose .pos field is updated in place by every view transition
     * (cadnano, unfold, expanded) and transform (deform, cluster move /
     * rotate). Falls back to the static midpoint if lookup misses (e.g.
     * during a transient transition where the entry hasn't been built).
     *
     * cursor (optional) — { camera, canvas, x, y } in canvas-local pixels.
     * When provided, each sprite fades to FADE_MIN opacity as the cursor
     * approaches its screen position so the user can see the crossover
     * underneath.
     *
     * Cheap: at most a few sprites per design, two map lookups + one
     * position write each.
     */
    refreshPositions(helixCtrl, cursor = null) {
      if (!_markers.length || !helixCtrl?.lookupEntry) return
      const w = cursor?.canvas?.clientWidth  ?? 0
      const h = cursor?.canvas?.clientHeight ?? 0
      const haveCursor = cursor && cursor.camera && w > 0 && h > 0
      for (let i = 0; i < _markers.length; i++) {
        const m = _markers[i]
        const ea = helixCtrl.lookupEntry(m.keyA)
        const eb = helixCtrl.lookupEntry(m.keyB)
        const s = _sprites[i]
        if (!s || !s.visible) continue
        if (ea?.pos && eb?.pos) {
          s.position.set(
            (ea.pos.x + eb.pos.x) * 0.5,
            (ea.pos.y + eb.pos.y) * 0.5,
            (ea.pos.z + eb.pos.z) * 0.5,
          )
        } else {
          s.position.fromArray(m.fallback)
        }
        // Hover-fade: project sprite position to canvas-local pixels and
        // compute distance to the cursor. Linear ramp between the two
        // thresholds; clamp to FADE_MIN inside the inner radius. Inactive
        // (full opacity) when no cursor is provided.
        let opacity = 1
        if (haveCursor) {
          _proj.copy(s.position).project(cursor.camera)
          const sx = ( _proj.x * 0.5 + 0.5) * w
          const sy = (-_proj.y * 0.5 + 0.5) * h
          const d = Math.hypot(sx - cursor.x, sy - cursor.y)
          if (d <= FADE_INNER_PX) opacity = FADE_MIN
          else if (d < FADE_OUTER_PX) {
            const t = (d - FADE_INNER_PX) / (FADE_OUTER_PX - FADE_INNER_PX)
            opacity = FADE_MIN + (1 - FADE_MIN) * t
          }
        }
        if (s.material.opacity !== opacity) s.material.opacity = opacity
      }
    },

    dispose() {
      for (const s of _sprites) scene.remove(s)
      _sprites = []
      _markers = []
    },
  }
}
