/** Read-only fixture exercise: no API mutations or saved structure copies. */
import { test, expect } from '@playwright/test'
import { readFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'

const fixture = resolve(process.cwd(), '..', 'workspace', 'test.nadoc')

for (const columns of [[2], [4], [2, 4]]) test(`internal scaffold selection in columns ${columns.join(",")} previews and commits 116/117 to 127/128 together`, async ({ page }) => {
  test.skip(!existsSync(fixture), 'Requires the reported workspace/test.nadoc fixture')
  await page.goto('/cadnano-editor.html')
  const result = await page.evaluate(async ({ design, columns }) => {
    const { initPathview } = await import('/src/cadnano-editor/pathview.js')
    const { buildContinuedRows } = await import('/src/cadnano-editor/pathview/continued_rows.js')
    const host = document.createElement('div')
    Object.assign(host.style, { position: 'fixed', inset: '0', zIndex: '99999' })
    const canvas = document.createElement('canvas')
    host.append(canvas); document.body.append(host)
    const commits = []
    const view = initPathview(canvas, host, { onBatchMoveCrossovers: moves => commits.push(moves) })
    view.update(design)
    view.setSelectFilter({ scaf: true, stap: false, xover: true, ends: false, line: false, strand: false })
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
    view.fitToContent()
    const pair = design.crossovers.filter(x => columns.some(column => x.half_a.helix_id.startsWith(`h_XY_0_${column}_`)) && [116, 117].includes(x.half_a.index))
    if (pair.length !== columns.length * 2) throw new Error('Reported pair missing')
    const layout = buildContinuedRows(design, { cellOf: h => ({ row: h.grid_pos[0], col: h.grid_pos[1] }), forwardOf: h => (h.grid_pos[0] + h.grid_pos[1]) % 2 === 0 })
    const a = layout.rowMap.get(pair[0].half_a.helix_id)
    const b = layout.rowMap.get(pair[0].half_b.helix_id)
    const y0 = a.fwdY, y1 = b.revY
    const z = view.getZoom(), px = view.getPanX(), py = view.getPanY()
    const at = (x, y) => [px + x * z, py + y * z]
    const rect = canvas.getBoundingClientRect()
    canvas.setPointerCapture = () => {}
    canvas.releasePointerCapture = () => {}
    const dispatch = (type, p, buttons) => canvas.dispatchEvent(new PointerEvent(type, {
      pointerId: 177, button: 0, buttons, clientX: rect.left + p[0], clientY: rect.top + p[1], bubbles: true,
    }))
    const ys = pair.flatMap(x => [x.half_a, x.half_b].map(half => {
      const info = layout.rowMap.get(half.helix_id)
      return half.strand === 'FORWARD' ? info.fwdY : info.revY
    }))
    // Lasso the requested arcs, starting in empty space left of the selection.
    dispatch('pointerdown', at(40 + 114 * 10, Math.min(...ys) - 4), 1)
    dispatch('pointermove', at(40 + 119 * 10, Math.max(...ys) + 4), 1)
    dispatch('pointerup', at(40 + 119 * 10, Math.max(...ys) + 4), 0)
    const ctx = canvas.getContext('2d')
    const previewXs = []
    const originalFill = ctx.fillRect.bind(ctx)
    ctx.fillRect = (x, y, w, h) => {
      if (x === 0 && y === 0 && w === canvas.width && h === canvas.height) previewXs.length = 0
      originalFill(x, y, w, h)
    }
    const originalMove = ctx.moveTo.bind(ctx)
    ctx.moveTo = (x, y) => { if (ctx.strokeStyle === '#00e5ff') previewXs.push(x); originalMove(x, y) }
    const bow = Math.max(10 * .27, Math.abs(y1 - y0) * .07)
    const start = at(40 + 116.5 * 10 - bow / 2, (y0 + y1) / 2)
    const target = at(40 + 127.5 * 10, (y0 + y1) / 2)
    dispatch('pointerdown', start, 1)
    dispatch('pointermove', target, 1)
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
    const during = commits.length
    window.__finishCrossoverDrag = () => { dispatch('pointerup', target, 0); return commits }
    return { during, previewXs, expectedIds: pair.map(x => x.id) }
  }, { design: JSON.parse(readFileSync(fixture, 'utf8')), columns })
  await page.screenshot({ path: test.info().outputPath('pair-preview.png') })
  result.commits = await page.evaluate(() => window.__finishCrossoverDrag())
  expect(result.during).toBe(0)
  expect(result.previewXs.sort((a, b) => a - b)).toEqual(columns.flatMap(() => [1315, 1325]).sort((a, b) => a - b))
  expect(result.commits).toHaveLength(1)
  expect(result.commits[0].map(m => m.new_index).sort((a, b) => a - b)).toEqual(columns.flatMap(() => [127, 128]).sort((a, b) => a - b))
  expect(result.commits[0].map(m => m.crossover_id).sort()).toEqual(result.expectedIds.sort())
})
