/**
 * Amber overhang-name label sprites for the assembly view.
 *
 * Extracted verbatim from assembly_renderer.js (both render paths used these:
 * the legacy per-instance path builds a Sprite group per instance, the shared-
 * instancing path builds one sprite per overhang anchor in world space).
 *
 * One reason to change: how an overhang's NAME label looks and where it sits
 * relative to the backbone. Matches overhang_name_overlay.js (the per-design
 * popup) so the assembly view's labels are visually identical.
 */
import * as THREE from 'three'

// Amber overhang-name labels. Matches overhang_name_overlay.js for the
// per-design popup so the assembly view's overhang labels look identical.
export const _OVHG_LABEL_COLOR        = '#f5a623'
export const _OVHG_SPRITE_HEIGHT_BASE = 1.5    // nm
export const _OVHG_RADIAL_OFFSET      = 0.55   // nm — push outward from backbone

export function _makeOverhangNameTexture(text) {
  const fontSize = 64
  const padding  = 16
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
  ctx.fillStyle    = _OVHG_LABEL_COLOR
  ctx.fillText(text, w / 2, h / 2)
  return new THREE.CanvasTexture(canvas)
}

/**
 * Per-instance sprite group of OverhangSpec.label billboards. Mirrors the
 * per-design overhang_name_overlay so the assembly view shows the same
 * amber labels when the user toggles "Show overhang labels". One sprite per
 * overhang that has a non-empty `label`, positioned at the midpoint nuc of
 * the overhang's domain and offset radially out from the backbone.
 *
 * The group is attached to the instance's local Three.js group, so the
 * PartInstance placement transform applies automatically.
 */
// Local-frame label anchors for every overhang with a non-empty label:
// [{overhangId, label, x, y, z}] at the overhang domain's midpoint nuc,
// offset radially out from the backbone. Shared by the per-instance sprite
// builder and the shared path's world-anchor computation.
export function _overhangLabelAnchorsLocal(design, nucleotides) {
  const out = []
  if (!design?.overhangs?.length || !nucleotides?.length) return out

  const labelMap = new Map()
  for (const ovhg of design.overhangs) {
    if (ovhg.label) labelMap.set(ovhg.id, ovhg.label)
  }
  if (labelMap.size === 0) return out

  const byOverhang = new Map()
  for (const nuc of nucleotides) {
    if (!nuc.overhang_id) continue
    if (!byOverhang.has(nuc.overhang_id)) byOverhang.set(nuc.overhang_id, [])
    byOverhang.get(nuc.overhang_id).push(nuc)
  }

  for (const [ovhgId, label] of labelMap) {
    const nucs = byOverhang.get(ovhgId)
    if (!nucs?.length) continue
    nucs.sort((a, b) =>
      a.direction === 'FORWARD' ? a.bp_index - b.bp_index : b.bp_index - a.bp_index,
    )
    const mid = nucs[Math.floor(nucs.length / 2)]
    const [x, y, z] = mid.backbone_position

    let ox = 0, oy = 0
    if (mid.base_normal) {
      const [nx, ny] = mid.base_normal
      const len = Math.hypot(nx, ny)
      if (len > 1e-6) {
        ox = (nx / len) * _OVHG_RADIAL_OFFSET
        oy = (ny / len) * _OVHG_RADIAL_OFFSET
      }
    }
    out.push({ overhangId: ovhgId, label, x: x + ox, y: y + oy, z })
  }
  return out
}
