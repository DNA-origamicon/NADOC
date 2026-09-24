/**
 * Hairpin/self-dimer ⚠ markers for the cadnano path view (pure helpers).
 *
 * pathview.js stays render-only: it places + draws these glyphs over the
 * flagged strand's domain and, on a click that hits one, reports the strand id
 * through its `onHairpinDimerClick` callback (main.js opens the window).
 *
 * World coordinates follow pathview's layout: bp cell centre on x, the domain's
 * track (`fwdY` for FORWARD, `revY` for REVERSE) on y. The glyph sits just
 * outside the helix pair — above a forward track, below a reverse one — and
 * keeps a constant on-screen size.
 */
import { BP_W, CELL_H, GUTTER } from './layout.js'
import { HAIRPIN_DIMER_COLORS } from '../../ui/hairpin_dimer_report.js'

export const HD_MARKER_PX = 16          // glyph size on screen
const HIT_PX = 10                       // click radius on screen
// Amber = the unligated-crossover ⚠; red above the critical Tm.
export const HD_MARKER_COLOR = { warning: '#f5a623', critical: HAIRPIN_DIMER_COLORS.critical }

const _bpCenterX = bp => GUTTER + (bp + 0.5) * BP_W

/**
 * @param {Array} markers  hairpinDimerMarkers(): { strandId, domains, label, tooltip }
 * @param {Map} rowMap     pathview `_rowMap` (helix id → { fwdY, revY, … })
 * @returns {Array<{ strandId, label, tooltip, level, x, y, below }>}  one per marker whose domain is laid out
 */
export function placeHairpinDimerMarkers(markers, rowMap) {
  const out = []
  for (const m of markers ?? []) {
    const d = (m.domains ?? []).find(dom => rowMap?.get(dom.helix_id))
    if (!d) continue
    const info = rowMap.get(d.helix_id)
    const fwd = d.direction === 'FORWARD'
    const mid = (Math.min(d.start_bp, d.end_bp) + Math.max(d.start_bp, d.end_bp)) / 2
    const trackY = fwd ? info.fwdY : info.revY
    out.push({
      strandId: m.strandId, label: m.label, tooltip: m.tooltip, level: m.level ?? 'warning',
      x: _bpCenterX(mid), y: trackY + (fwd ? -CELL_H : CELL_H), below: !fwd,
    })
  }
  return out
}

/** Draw the glyphs; ctx carries the world transform (scale = zoom). */
export function drawHairpinDimerMarkers(ctx, placed, zoom) {
  if (!placed?.length) return
  ctx.save()
  ctx.font = `bold ${HD_MARKER_PX / zoom}px sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.lineWidth = 2.5 / zoom
  ctx.strokeStyle = '#000'
  for (const p of placed) {
    ctx.fillStyle = HD_MARKER_COLOR[p.level] ?? HD_MARKER_COLOR.warning
    ctx.strokeText('⚠', p.x, p.y)
    ctx.fillText('⚠', p.x, p.y)
  }
  ctx.restore()
}

/** The marker under world point (wx, wy), or null. */
export function hitHairpinDimerMarker(placed, wx, wy, zoom) {
  const r = HIT_PX / zoom
  let best = null, bestD = Infinity
  for (const p of placed ?? []) {
    const d = Math.hypot(wx - p.x, wy - p.y)
    if (d <= r && d < bestD) { best = p; bestD = d }
  }
  return best
}
