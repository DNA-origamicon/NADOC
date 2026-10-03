/**
 * glow_layer.js — Radioactive green glow halo for selected strands.
 *
 * Renders a second InstancedMesh of spheres at each selected backbone bead
 * position using additive blending and a semi-transparent green material.
 * The underlying bead color is completely unchanged; the glow sits on top
 * as a separate draw call.
 */

import * as THREE        from 'three'
import { markAttributeRange } from './attribute_updates.js'
import { BEAD_RADIUS }   from './helix_renderer.js'

const GLOW_SCALE   = 2.8        // glow sphere radius relative to BEAD_RADIUS
const GLOW_OPACITY = 0.45

const _geo   = new THREE.SphereGeometry(BEAD_RADIUS, 8, 6)

/**
 * Multi-color glow layer for fluorescence visualisation.
 *
 * Each entry must have:
 *   { pos: THREE.Vector3, emissionColor: number (hex) }
 *
 * Uses one THREE.Sprite per fluorophore with a shared radial-gradient canvas
 * texture.  The SpriteMaterial.color tints the white gradient to the emission
 * color; AdditiveBlending composites it as a soft halo.
 *
 * Scale of 20 = 20 nm diameter = 10 nm radius in scene units (1 unit = 1 nm).
 */

// Shared grayscale radial-gradient texture (white centre → transparent edge).
// Created once and reused by all SpriteMaterials.
const _GLOW_TEX = (() => {
  const SIZE = 128
  const canvas = document.createElement('canvas')
  canvas.width = SIZE; canvas.height = SIZE
  const ctx = canvas.getContext('2d')
  const r = SIZE / 2
  const grad = ctx.createRadialGradient(r, r, 0, r, r, r)
  grad.addColorStop(0.0,  'rgba(255,255,255,1.0)')
  grad.addColorStop(0.25, 'rgba(255,255,255,0.85)')
  grad.addColorStop(0.55, 'rgba(255,255,255,0.35)')
  grad.addColorStop(0.80, 'rgba(255,255,255,0.08)')
  grad.addColorStop(1.0,  'rgba(255,255,255,0.0)')
  ctx.fillStyle = grad
  ctx.fillRect(0, 0, SIZE, SIZE)
  const tex = new THREE.CanvasTexture(canvas)
  tex.needsUpdate = true
  return tex
})()

// Each sprite owns its material: donors of the same color may have different
// quenching. Reuse it across frames and dispose it when the sprite is removed.
function _getSpriteMat(hexColor) {
  return new THREE.SpriteMaterial({
    map:        _GLOW_TEX,
    color:      hexColor,
    blending:   THREE.AdditiveBlending,
    depthWrite: false,
    transparent: true,
  })
}

const FLUORO_GLOW_SCALE = 20   // 20 nm diameter = 10 nm radius

export function createMultiColorGlowLayer(scene) {
  let _sprites = []   // THREE.Sprite[]
  let _entries = []

  function _writeEntries(entries) {
    // Remove sprites whose count doesn't match (rebuild pool).
    if (_sprites.length !== entries.length) {
      for (const s of _sprites) { scene.remove(s); s.material.dispose() }
      _sprites = entries.map(() => {
        const s = new THREE.Sprite(_getSpriteMat(0xffffff))
        s.renderOrder = 1
        scene.add(s)
        return s
      })
    }
    for (let i = 0; i < entries.length; i++) {
      const s   = _sprites[i]
      const ent = entries[i]
      s.material.color.setHex(ent.emissionColor)
      s.material.opacity = Number.isFinite(ent.brightness) ? Math.max(0, Math.min(1, ent.brightness)) : 1
      s.position.copy(ent.pos)
      s.scale.setScalar(ent.scale ?? FLUORO_GLOW_SCALE)
      s.visible = true
    }
  }

  return {
    setEntries(entries) {
      _entries = entries
      _writeEntries(entries)
    },
    refresh() {
      // Re-read current pos values (called during unfold animation).
      for (let i = 0; i < _entries.length; i++) {
        if (_sprites[i]) _sprites[i].position.copy(_entries[i].pos)
      }
    },
    clear() {
      _entries = []
      for (const s of _sprites) { scene.remove(s); s.material.dispose() }
      _sprites = []
    },
    /** Number of active glow sprites (used by e2e to confirm fluorophores glow). */
    count() { return _sprites.length },
    dispose() {
      for (const s of _sprites) { scene.remove(s); s.material.dispose() }
      _sprites = []
      _entries = []
    },
  }
}

export function createGlowLayer(scene, color = 0x3fb950, scale = GLOW_SCALE, name = '') {
  const mat = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity:     GLOW_OPACITY,
    blending:    THREE.AdditiveBlending,
    depthWrite:  false,
  })
  let mesh = new THREE.InstancedMesh(_geo, mat, 1)
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
  mesh.count       = 0
  mesh.name        = name   // optional tag so gesture e2e can find a specific glow layer
  mesh.renderOrder = 1   // draw after the main geometry so additive blending composites correctly
  mesh.frustumCulled = false
  scene.add(mesh)

  let _entries = []   // kept so refresh() can re-read current entry.pos values

  function _ensureCapacity(needed) {
    if (needed <= mesh.instanceMatrix.count) return
    scene.remove(mesh)
    mesh.dispose()
    mesh = new THREE.InstancedMesh(_geo, mat, Math.max(needed, mesh.instanceMatrix.count * 2))
    mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
    mesh.count       = 0
    mesh.name        = name
    mesh.renderOrder = 1
    mesh.frustumCulled = false
    scene.add(mesh)
  }

  function _writeEntries(entries) {
    const count = entries.length
    _ensureCapacity(count)
    const attribute = mesh.instanceMatrix, values = attribute.array
    let first = Infinity, last = -1
    for (let i = 0; i < count; i++) {
      const p = entries[i].pos, size = Math.fround(entries[i].scale ?? scale), offset = i * 16
      const x = Math.fround(p.x), y = Math.fround(p.y), z = Math.fround(p.z)
      if (values[offset] === size && values[offset + 5] === size && values[offset + 10] === size &&
          values[offset + 12] === x && values[offset + 13] === y && values[offset + 14] === z) continue
      values[offset] = values[offset + 5] = values[offset + 10] = size
      values[offset + 12] = x; values[offset + 13] = y; values[offset + 14] = z
      first = Math.min(first, offset); last = offset + 16
    }
    mesh.count = count
    if (last >= 0) markAttributeRange(attribute, first, last - first)
  }

  return {
    /** Position glow spheres over the given backbone entries. */
    setEntries(entries) {
      _entries = entries
      _writeEntries(entries)
    },

    /** Re-read current entry.pos values and update matrices (call after unfold repositioning). */
    refresh() {
      if (_entries.length > 0) _writeEntries(_entries)
    },

    /** Hide all glow spheres. */
    clear() {
      _entries = []
      if (mesh.count === 0) return
      mesh.count = 0
    },

    /** Number of active glow spheres (used by gesture e2e to detect the preview). */
    count() { return mesh.count },

    dispose() {
      scene.remove(mesh); mesh.dispose(); mat.dispose(); _entries = []
    },
  }
}
