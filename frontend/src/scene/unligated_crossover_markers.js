/**
 * Unligated crossover markers — amber ⚠ sprites at the midpoint of each
 * crossover that the backend left unligated because joining its two halves
 * would close a strand into a circle (not a first-class concept in the model).
 *
 * Backend's `unligated_crossover_ids` field on every design-bearing response
 * drives the marker set. Recomputed every response, so the marker auto-clears
 * when the user nicks the affected strand to break the cycle.
 *
 * Architecturally identical to glow_layer.js: one Sprite per marker, a shared
 * canvas-rendered glyph texture, additive-style transparent material so the
 * marker reads against any backdrop.
 */

import * as THREE from 'three'

// Amber matches the broken-delta ⚠ used in feature_log_panel for consistency.
const MARKER_COLOR = '#f5a623'
const MARKER_SCALE = 1.6   // nm — readable but not overpowering against bead clusters

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

const _MATERIAL = new THREE.SpriteMaterial({
  map: _TEXTURE,
  transparent: true,
  depthTest: false,   // always visible, even behind beads/slabs
  depthWrite: false,
})

export function initUnligatedCrossoverMarkers(scene) {
  let _sprites = []   // pool of THREE.Sprite

  function _ensurePool(n) {
    while (_sprites.length < n) {
      const s = new THREE.Sprite(_MATERIAL)
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
     * - design.crossovers gives the half-crossover endpoints.
     * - geometry's nuc.backbone_position gives the midpoint anchor.
     * - unligatedIds (Set or null) filters which crossovers get a marker.
     */
    rebuild(design, geometry, unligatedIds) {
      const ids = unligatedIds instanceof Set
        ? unligatedIds
        : new Set(unligatedIds ?? [])
      const xovers = design?.crossovers ?? []
      if (!geometry?.length || !ids.size || !xovers.length) {
        for (const s of _sprites) s.visible = false
        return
      }
      const nucMap = new Map()
      for (const nuc of geometry) {
        nucMap.set(`${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}`, nuc)
      }

      const placements = []
      for (const xo of xovers) {
        if (!ids.has(xo.id)) continue
        const a = nucMap.get(`${xo.half_a.helix_id}:${xo.half_a.index}:${xo.half_a.strand}`)
        const b = nucMap.get(`${xo.half_b.helix_id}:${xo.half_b.index}:${xo.half_b.strand}`)
        if (!a || !b) continue
        const ap = a.backbone_position
        const bp = b.backbone_position
        placements.push([
          (ap[0] + bp[0]) * 0.5,
          (ap[1] + bp[1]) * 0.5,
          (ap[2] + bp[2]) * 0.5,
        ])
      }

      _ensurePool(placements.length)
      for (let i = 0; i < _sprites.length; i++) {
        const s = _sprites[i]
        if (i < placements.length) {
          s.position.fromArray(placements[i])
          s.visible = true
        } else {
          s.visible = false
        }
      }
    },

    dispose() {
      for (const s of _sprites) scene.remove(s)
      _sprites = []
    },
  }
}
