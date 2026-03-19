/**
 * Overhang Name overlay — renders the label of each OverhangSpec as a
 * billboard sprite at the midpoint of its domain, offset radially outward
 * from the helix axis so it clears the backbone beads.
 *
 * Uses THREE.Sprite (auto-billboarding) with a per-label CanvasTexture.
 * Text is rendered in amber to match the overhang identity.
 *
 * Usage:
 *   const overlay = initOverhangNameOverlay(scene, store)
 *   overlay.setVisible(true/false)
 *   overlay.dispose()
 */

import * as THREE from 'three'

const LABEL_COLOR         = '#f5a623'   // amber — matches overhang identity
const SPRITE_HEIGHT_BASE  = 1.5         // nm — default world-space height
const RADIAL_OFFSET       = 0.55        // nm — extra push outward from backbone

function _makeTexture(text) {
  const fontSize = 64
  const padding  = 16
  // Measure text width with a temporary canvas
  const tmp = document.createElement('canvas')
  const tmpCtx = tmp.getContext('2d')
  tmpCtx.font = `bold ${fontSize}px monospace`
  const w = Math.ceil(tmpCtx.measureText(text).width) + padding * 2
  const h = fontSize + padding * 2

  const canvas = document.createElement('canvas')
  canvas.width  = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  ctx.font         = `bold ${fontSize}px monospace`
  ctx.textAlign    = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillStyle    = LABEL_COLOR
  ctx.fillText(text, w / 2, h / 2)
  return new THREE.CanvasTexture(canvas)
}

export function initOverhangNameOverlay(scene, storeRef) {
  const _group = new THREE.Group()
  scene.add(_group)
  let _visible      = false
  let _spriteHeight = SPRITE_HEIGHT_BASE

  function _disposeGroup() {
    for (const child of [..._group.children]) {
      if (child.material?.map) child.material.map.dispose()
      if (child.material) child.material.dispose()
    }
    _group.clear()
  }

  function rebuild(geometry, design) {
    _disposeGroup()
    if (!geometry || !design) return

    // Collect overhangs that have a label
    const labelMap = new Map()   // overhang_id → label string
    for (const ovhg of (design.overhangs ?? [])) {
      if (ovhg.label) labelMap.set(ovhg.id, ovhg.label)
    }
    if (!labelMap.size) { _group.visible = _visible; return }

    // Group geometry nucs by overhang_id
    const byOverhang = new Map()   // overhang_id → [nuc]
    for (const nuc of geometry) {
      if (!nuc.overhang_id) continue
      if (!byOverhang.has(nuc.overhang_id)) byOverhang.set(nuc.overhang_id, [])
      byOverhang.get(nuc.overhang_id).push(nuc)
    }

    for (const [ovhgId, label] of labelMap) {
      const nucs = byOverhang.get(ovhgId)
      if (!nucs?.length) continue

      // Sort in 5′→3′ order, pick midpoint nuc
      nucs.sort((a, b) =>
        a.direction === 'FORWARD' ? a.bp_index - b.bp_index : b.bp_index - a.bp_index,
      )
      const mid = nucs[Math.floor(nucs.length / 2)]
      const [x, y, z] = mid.backbone_position

      // Offset radially outward using base_normal (cross-strand direction)
      let ox = 0, oy = 0
      if (mid.base_normal) {
        const [nx, ny] = mid.base_normal
        const len = Math.hypot(nx, ny)
        if (len > 1e-6) { ox = (nx / len) * RADIAL_OFFSET; oy = (ny / len) * RADIAL_OFFSET }
      }

      const tex    = _makeTexture(label)
      const aspect = tex.image.width / tex.image.height
      const mat    = new THREE.SpriteMaterial({
        map:         tex,
        depthTest:   false,
        transparent: true,
      })
      const sprite = new THREE.Sprite(mat)
      sprite.scale.set(_spriteHeight * aspect, _spriteHeight, 1)
      sprite.position.set(x + ox, y + oy, z)
      sprite.renderOrder = 12
      _group.add(sprite)
    }

    _group.visible = _visible
  }

  function setVisible(v) {
    _visible = v
    _group.visible = v
  }

  function isVisible() { return _visible }

  function setScale(s) {
    _spriteHeight = s
    for (const sprite of _group.children) {
      // Preserve aspect ratio stored in x vs y
      const aspect = sprite.scale.x / sprite.scale.y
      sprite.scale.set(_spriteHeight * aspect, _spriteHeight, 1)
    }
  }

  function dispose() {
    _disposeGroup()
    scene.remove(_group)
  }

  // Rebuild whenever geometry or design changes
  storeRef.subscribe((newState, prevState) => {
    const geomChanged   = newState.currentGeometry !== prevState.currentGeometry
    const designChanged = newState.currentDesign   !== prevState.currentDesign
    if ((geomChanged || designChanged) && _visible) {
      rebuild(newState.currentGeometry, newState.currentDesign)
    }
    if (newState.showOverhangNames !== prevState.showOverhangNames) {
      const show = newState.showOverhangNames
      setVisible(show)
      if (show) rebuild(newState.currentGeometry, newState.currentDesign)
    }
  })

  return { rebuild, setVisible, isVisible, setScale, dispose }
}
