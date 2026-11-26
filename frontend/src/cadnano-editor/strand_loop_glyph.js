/** Compact strand-track loop glyph with an explicit nucleotide count. */
export function drawStrandLoops(ctx, design, rows, bpX, cellHeight, zoom, showReference = true) {
  ctx.save()
  ctx.lineWidth = 1.5 / zoom
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.font = `${Math.max(9 / zoom, cellHeight * 0.48)}px sans-serif`
  for (const strand of design?.strands ?? []) {
    if (strand.is_reference && !showReference) continue
    ctx.strokeStyle = strand.color || (strand.strand_type === 'scaffold' ? '#4488dd' : '#e5ae52')
    ctx.fillStyle = ctx.strokeStyle
    for (const loop of strand.loops ?? []) {
      const row = rows.get(loop.helix_id)
      if (!row) continue
      const x = bpX(loop.bp_index)
      const y = loop.direction === 'FORWARD' ? row.fwdY : row.revY
      const side = loop.direction === 'FORWARD' ? -1 : 1
      const radius = Math.max((5 + String(loop.length).length * 2) / zoom, cellHeight * 0.42)
      ctx.beginPath()
      ctx.moveTo(x, y)
      ctx.bezierCurveTo(x - radius * 2.4, y + side * radius * 2.8,
        x + radius * 2.4, y + side * radius * 2.8, x, y)
      ctx.stroke()
      ctx.fillText(String(loop.length), x, y + side * radius * 2.45)
    }
  }
  ctx.restore()
}
