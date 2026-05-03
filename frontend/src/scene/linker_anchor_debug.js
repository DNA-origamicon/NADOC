/**
 * Linker anchor debug overlay — paints colored sprites with text labels at
 * the key beads of every linker so the user can visually confirm the
 * relax + anchor pipeline is targeting the right beads.
 *
 * Per linker, per side (A and B):
 *   • OH tip                       — red    label "OH(side) tip"
 *   • OH attach-end                — pink   label "OH(side) attach"   (root or free_end)
 *   • Anchor (= comp at attach bp) — green  label "(side) anchor"     (target)
 *   • Bridge boundary bead         — cyan   label "(side) bridge bp" (must coincide with anchor post-relax)
 *
 * Anchor and bridge boundary should be COLOCALIZED post-relax — if not,
 * either the anchor lookup or the bridge axis offset is wrong.
 *
 * Toggleable from Help → "Show Linker Anchor Debug".
 */

import * as THREE from 'three'

const COLOR_OH         = '#ff4d4d'   // red — OH free tip
const COLOR_OH_ATTACH  = '#ff66cc'   // pink — OH attach-end (root / free_end)
const COLOR_ANCHOR     = '#3aff7a'   // green — anchor (complement at attach bp) = target
const COLOR_BRIDGE_BP  = '#4dd2ff'   // cyan — bridge boundary bead (should colocalize with anchor)
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

  function _ohAttachNuc(ohNucs, attach) {
    if (!ohNucs?.length) return null
    const tip = ohNucs.find(n => n.is_five_prime || n.is_three_prime) ?? ohNucs[0]
    if (attach !== 'root' || ohNucs.length < 2) return tip
    const tipBp = tip.bp_index ?? 0
    let best = tip, bestDist = -1
    for (const n of ohNucs) {
      const d = Math.abs((n.bp_index ?? 0) - tipBp)
      if (d > bestDist) { bestDist = d; best = n }
    }
    return best
  }

  function _linkerLengthBp(conn) {
    const v = Number(conn?.length_value)
    if (!Number.isFinite(v) || v <= 0) return 1
    if (conn?.length_unit === 'nm') return Math.max(1, Math.round(v / 0.334))
    return Math.max(1, Math.round(v))
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
      const baseCount = _linkerLengthBp(conn)
      const bridgeHelixId = `__lnk__${conn.id}`
      for (const side of ['a', 'b']) {
        const ovhgId = side === 'a' ? conn.overhang_a_id : conn.overhang_b_id
        const attach = side === 'a' ? conn.overhang_a_attach : conn.overhang_b_attach
        const ohNucs = nucsByOvhg.get(ovhgId) ?? []
        const ohTip = ohNucs.find(n => n.is_five_prime || n.is_three_prime) ?? ohNucs[0]
        if (!ohTip?.backbone_position) continue
        _addSprite(scene, ohTip.backbone_position, `OH${side.toUpperCase()} tip`, COLOR_OH)

        // OH attach-end (root or free_end) — where the bridge structurally
        // bonds. For attach=free_end this == OH tip (the two sprites
        // overlap, which is fine).
        const attachNuc = _ohAttachNuc(ohNucs, attach)
        if (attachNuc?.backbone_position) {
          _addSprite(scene, attachNuc.backbone_position,
            `OH${side.toUpperCase()} attach`, COLOR_OH_ATTACH, SPRITE_SIZE_NM * 0.85)
        }

        // Anchor: COMPLEMENT nuc on the OH's helix at OH's attach-end bp.
        // Direct same-bp lookup (matches backend `_anchor_pos_and_normal`).
        const linkerStrandId = `__lnk__${conn.id}__${side}`
        if (attachNuc) {
          const compAtAttach = (nucsByStrand.get(linkerStrandId) ?? [])
            .find(n => !((n.helix_id ?? '').startsWith('__lnk__'))
                    && n.helix_id === attachNuc.helix_id
                    && n.bp_index === attachNuc.bp_index)
          if (compAtAttach?.backbone_position) {
            _addSprite(scene, compAtAttach.backbone_position,
              `${side.toUpperCase()} anchor`, COLOR_ANCHOR)
          }
        }

        // Bridge boundary bead — bp 0 on side A, bp baseCount-1 on side B.
        // Read from the geometry payload (real nucs emitted by the
        // backend). Should colocalize with the green anchor swatch
        // post-relax; pre-relax there's a visible offset.
        const bridgeBp = side === 'a' ? 0 : (baseCount - 1)
        const bridgeNuc = (nucsByStrand.get(linkerStrandId) ?? [])
          .find(n => n.helix_id === bridgeHelixId && n.bp_index === bridgeBp)
        if (bridgeNuc?.backbone_position) {
          _addSprite(scene, bridgeNuc.backbone_position,
            `${side.toUpperCase()} bridge bp${bridgeBp}`, COLOR_BRIDGE_BP, SPRITE_SIZE_NM * 0.65)
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
