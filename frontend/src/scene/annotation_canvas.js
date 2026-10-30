/** Draw callouts after photo tiles are assembled, in full-frame coordinates. */
import { annotationIconMarkup } from './annotation_icons.js'

function drawIcon(ctx, key, x, y, size) {
  const markup = annotationIconMarkup(key)
  if (!markup) return
  const svg = new DOMParser().parseFromString(markup, 'image/svg+xml').documentElement
  ctx.save()
  ctx.translate(x, y)
  ctx.scale(size / 24, size / 24)
  for (const node of svg.children) {
    const n = (key, fallback = 0) => Number(node.getAttribute(key) ?? fallback)
    let path
    if (node.tagName === 'path') path = new Path2D(node.getAttribute('d'))
    else {
      path = new Path2D()
      if (node.tagName === 'circle') path.arc(n('cx'), n('cy'), n('r'), 0, Math.PI * 2)
      else if (node.tagName === 'rect') path.roundRect(n('x'), n('y'), n('width'), n('height'), n('rx'))
      else continue
    }
    const fill = node.getAttribute('fill') ?? '#000'
    if (fill !== 'none') { ctx.fillStyle = fill; ctx.fill(path) }
    const stroke = node.getAttribute('stroke')
    if (stroke && stroke !== 'none') {
      ctx.strokeStyle = stroke
      ctx.lineWidth = n('stroke-width', 1)
      ctx.lineCap = node.getAttribute('stroke-linecap') ?? 'butt'
      ctx.lineJoin = node.getAttribute('stroke-linejoin') ?? 'miter'
      ctx.stroke(path)
    }
  }
  ctx.restore()
}

export function drawAnnotationCallouts(ctx, records, scale) {
  ctx.save()
  try {
    ctx.scale(scale, scale)
    // The DOM paints every leader behind every box.
    for (const rec of records) {
      if (!rec.rect || !rec.hasAnchor) continue
      ctx.globalAlpha = 1 - rec.entry.transparency
      ctx.strokeStyle = rec.entry.color
      ctx.lineWidth = 2
      ctx.lineJoin = ctx.lineCap = 'round'
      const points = rec.line.getAttribute('points').split(' ').map(p => p.split(',').map(Number))
      ctx.beginPath()
      points.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))
      ctx.stroke()
      ctx.beginPath()
      ctx.arc(Number(rec.dot.getAttribute('cx')), Number(rec.dot.getAttribute('cy')), 5, 0, Math.PI * 2)
      ctx.stroke()
    }
    for (const rec of records) {
      if (!rec.rect) continue
      const { entry, rect } = rec
      const shelf = entry.calloutType === 'shelf'
      ctx.globalAlpha = 1 - entry.transparency
      ctx.lineWidth = 2
      ctx.strokeStyle = entry.color
      ctx.beginPath()
      if (shelf) {
        ctx.moveTo(rect.x, rect.y + rect.h - 1)
        ctx.lineTo(rect.x + rect.w, rect.y + rect.h - 1)
      } else {
        ctx.roundRect(rect.x + 1, rect.y + 1, rect.w - 2, rect.h - 2, entry.calloutType === 'rounded' ? 15 : 0)
        ctx.fillStyle = 'rgba(13,17,23,0.92)'
        ctx.fill()
      }
      ctx.stroke()
      const iconSize = Math.round(18 * entry.size)
      const x = rect.x + (shelf ? 4 : entry.calloutType === 'rounded' ? 15 : 12)
      const y = rect.y + (shelf ? 2 : 8)
      if (entry.icon) drawIcon(ctx, entry.icon, x, y, iconSize)
      ctx.fillStyle = entry.color
      ctx.font = `600 ${(13 * entry.size).toFixed(1)}px system-ui, sans-serif`
      ctx.textBaseline = 'top'
      // Use actual DOM glyph positions to preserve whitespace and CSS wrapping.
      const node = rec.text.firstChild
      if (!node) continue
      const origin = rec.el.getBoundingClientRect()
      const range = rec.text.ownerDocument.createRange()
      let offset = 0
      const runs = []
      for (const char of entry.text) {
        range.setStart(node, offset)
        offset += char.length
        range.setEnd(node, offset)
        const bounds = range.getBoundingClientRect()
        if (char !== '\n' && bounds.width) {
          const previous = runs.at(-1)
          if (previous && Math.abs(previous.top - bounds.top) < 0.5) previous.text += char
          else runs.push({ text: char, left: bounds.left, top: bounds.top })
        }
      }
      ctx.shadowColor = '#0d1117'
      ctx.shadowBlur = shelf ? 4 * scale : 0
      for (const run of runs) ctx.fillText(run.text, rect.x + run.left - origin.left, rect.y + run.top - origin.top)
      ctx.shadowBlur = 0
    }
  } finally { ctx.restore() }
}
