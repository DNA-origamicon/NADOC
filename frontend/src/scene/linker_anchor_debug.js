/**
 * Linker anchor debug overlay — paints colored sprites with text labels at
 * the four key beads of every linker so the user can visually confirm the
 * relax/snap is targeting the right beads.
 *
 * Per linker, per side (A and B):
 *   • OH tip                  — red    label "OH(side) tip"
 *   • Complement 3' end       — green  label "(side) comp 3'"   (= anchor)
 *   • Bridge first/last bead  — yellow label "(side) bridge"    (snapped)
 *
 * Anchor (complement 3' end) and bridge bead should be COLOCALIZED — if
 * they're not, the snap or anchor lookup is wrong.
 *
 * Toggleable from Help → "Show Linker Anchor Debug".
 */

import * as THREE from 'three'

const COLOR_OH      = '#ff4d4d'   // red
const COLOR_COMP    = '#3aff7a'   // green — anchor
const COLOR_BRIDGE  = '#ffd24d'   // yellow — snapped target
const SPRITE_SIZE_NM = 1.6

function _makeLabelTexture(text, color) {
  const SIZE = 256
  const canvas = document.createElement('canvas')
  canvas.width = SIZE; canvas.height = SIZE
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, SIZE, SIZE)
  // Filled circle as anchor swatch
  ctx.beginPath()
  ctx.arc(SIZE * 0.5, SIZE * 0.42, SIZE * 0.18, 0, Math.PI * 2)
  ctx.fillStyle = color
  ctx.fill()
  ctx.lineWidth = 4
  ctx.strokeStyle = 'rgba(0,0,0,0.85)'
  ctx.stroke()
  // Label
  ctx.shadowColor = 'rgba(0,0,0,0.85)'
  ctx.shadowBlur = 6
  ctx.fillStyle = '#fff'
  ctx.font = 'bold 44px sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(text, SIZE * 0.5, SIZE * 0.78)
  const tex = new THREE.CanvasTexture(canvas)
  tex.needsUpdate = true
  return tex
}

const _materialCache = new Map()
function _materialFor(text, color) {
  const key = `${color}|${text}`
  let m = _materialCache.get(key)
  if (!m) {
    m = new THREE.SpriteMaterial({
      map: _makeLabelTexture(text, color),
      transparent: true, depthTest: false, depthWrite: false,
    })
    _materialCache.set(key, m)
  }
  return m
}

function _addSprite(scene, pos, text, color, scale = SPRITE_SIZE_NM) {
  const s = new THREE.Sprite(_materialFor(text, color))
  s.scale.setScalar(scale)
  s.position.fromArray(pos)
  s.renderOrder = 2000
  scene.add(s)
  return s
}

export function initLinkerAnchorDebug(scene, getDesign, getGeometry, getHelixCtrl) {
  let _sprites = []
  let _visible = false

  function _clear() {
    for (const s of _sprites) scene.remove(s)
    _sprites = []
  }

  function _bridgeFirstBeadAt(connId, side, posA, posB, baseCount) {
    // Mirrors _makeDsLinkerMeshes' boundary snap: with the snap in place,
    // the bridge's first bead on side A IS posA, side B IS posB. So just
    // return the matching anchor.
    return side === 'a' ? posA : posB
  }

  function rebuild() {
    _clear()
    if (!_visible) return
    const design = getDesign?.()
    const geometry = getGeometry?.()
    if (!design?.overhang_connections?.length || !geometry?.length) return

    // Index nucs for fast lookup.
    const nucsByOvhg = new Map()
    const nucsByStrand = new Map()
    for (const n of geometry) {
      const oid = n.overhang_id
      if (oid) {
        if (!nucsByOvhg.has(oid)) nucsByOvhg.set(oid, [])
        nucsByOvhg.get(oid).push(n)
      }
      const sid = n.strand_id
      if (sid) {
        if (!nucsByStrand.has(sid)) nucsByStrand.set(sid, [])
        nucsByStrand.get(sid).push(n)
      }
    }

    for (const conn of design.overhang_connections) {
      for (const side of ['a', 'b']) {
        const ovhgId = side === 'a' ? conn.overhang_a_id : conn.overhang_b_id
        const ohNucs = nucsByOvhg.get(ovhgId) ?? []
        const ohTip = ohNucs.find(n => n.is_five_prime || n.is_three_prime) ?? ohNucs[0]
        if (!ohTip?.backbone_position) continue
        _addSprite(scene, ohTip.backbone_position, `OH${side.toUpperCase()} tip`, COLOR_OH)

        // Complement 3' end (anchor): same logic as _linkerAttachAnchor —
        // farthest-bp nuc in the linker strand on the OH's helix.
        const linkerStrandId = `__lnk__${conn.id}__${side}`
        const compNucs = (nucsByStrand.get(linkerStrandId) ?? [])
          .filter(n => !((n.helix_id ?? '').startsWith('__lnk__'))
                    && n.helix_id === ohTip.helix_id)
        if (compNucs.length) {
          const tipBp = ohTip.bp_index
          const anchor = compNucs.reduce((best, n) =>
            Math.abs(n.bp_index - tipBp) > Math.abs(best.bp_index - tipBp) ? n : best,
            compNucs[0])
          if (anchor.backbone_position) {
            _addSprite(scene, anchor.backbone_position,
              `${side.toUpperCase()} comp 3'`, COLOR_COMP)
            // Bridge first/last bead is snapped to the anchor — paint a
            // slightly smaller yellow swatch ON TOP so user can confirm
            // colocalization (yellow circle should sit inside green).
            _addSprite(scene, anchor.backbone_position,
              `${side.toUpperCase()} bridge`, COLOR_BRIDGE, SPRITE_SIZE_NM * 0.55)
          }
        }
      }
    }
  }

  return {
    isVisible: () => _visible,
    setVisible(v) {
      _visible = !!v
      rebuild()
    },
    rebuild,
    dispose() {
      _clear()
    },
  }
}
