import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// No workspace save target; session persistence is disabled by playwright.config.
// All structures are authored through public, feature-recording commands.
const API = `${process.env.NADOC_E2E_API_BASE}/api`

for (const scaffold of [false, true]) for (const swept of [false, true]) {
  test(`${scaffold ? 'scaffold Shift' : 'staple'} crossover in ${swept ? 'swept' : 'original'} frame`, async ({ page, request }) => {
    const errors = trackConsoleErrors(page)
    const doc = `__e2e__crossover-${scaffold}-${swept}`
    const headers = { 'X-NADOC-Doc': doc, 'X-NADOC-Skip-Geometry': '1' }
    const post = async (path, data) => {
      const r = await request.post(`${API}${path}`, { headers, data })
      expect(r.ok(), await r.text()).toBe(true)
      return r.json()
    }
    const cells = [[0, 1], [1, 1]]
    const seed = await post('/design/bundle', { cells, length_bp: 42, name: doc, plane: 'XY', lattice_type: 'HONEYCOMB' })
    const originalFrame = seed.design.helices[0].lattice_frame_id
    const built = await post('/design/sweep', {
      cells, points_nm: [[0, 0, 0], [0, 3, 14]],
      source_helix_id: seed.design.helices[0].id, source_end: 'end',
    })
    expect(built.design.feature_log.map(f => f.op_kind)).toEqual(['bundle-create', 'sweep'])

    // Observe actual painted indicator circles, then click their screen positions.
    await page.addInitScript(() => {
      window.__sprites = []
      const proto = CanvasRenderingContext2D.prototype
      const arc = proto.arc, fill = proto.fill, fillRect = proto.fillRect
      proto.fillRect = function (x, y, w, h) {
        if (this.canvas.id === 'pathview-canvas' && x === 0 && y === 0 &&
            w === this.canvas.width && h === this.canvas.height) window.__sprites = []
        return fillRect.call(this, x, y, w, h)
      }
      proto.arc = function (x, y, ...args) {
        const m = this.getTransform()
        this.__lastCircle = { x: m.a*x + m.c*y + m.e, y: m.b*x + m.d*y + m.f, scale: m.a, bp: Math.round((x-45)/10) }
        return arc.call(this, x, y, ...args)
      }
      proto.fill = function (...args) {
        const color = this.fillStyle
        if (this.canvas.id === 'pathview-canvas' && this.__lastCircle &&
            (color.startsWith('rgba(120, 210, 255,') || color.startsWith('rgba(0, 112, 187,') ||
             color === '#3399dd' || color === '#005fa0')) {
          window.__sprites.push({ ...this.__lastCircle, scaffold: color.startsWith('rgba(0,') || color === '#005fa0' })
        }
        return fill.apply(this, args)
      }
    })
    await page.setViewportSize({ width: 1800, height: 1000 })
    await page.goto(`/cadnano-editor.html?doc=${doc}`)
    await expect.poll(() => page.evaluate(() => window.__sprites.length)).toBeGreaterThan(0)
    await page.keyboard.press('f')
    // An attached Sweep continues the source rows, not a second row block.
    const rowYs = await page.evaluate(() => {
      const ys = swept => [...new Set(window.__sprites.filter(s => !s.scaffold && (s.bp >= 42) === swept).map(s => s.y))].sort((a, b) => a-b)
      return { original: ys(false), swept: ys(true) }
    })
    expect(rowYs.original).toHaveLength(2)
    expect(rowYs.swept).toEqual(rowYs.original)
    const canvas = page.locator('#pathview-canvas')
    const box = await canvas.boundingBox()
    const staple = await page.evaluate(swept => window.__sprites.find(s => !s.scaffold && (s.bp >= 42) === swept), swept)
    expect(staple).toBeTruthy()
    await page.mouse.move(box.x + staple.x, box.y + staple.y)
    if (scaffold) await page.keyboard.down('Shift')
    await expect.poll(() => page.evaluate(({ scaffold, swept }) => window.__sprites.filter(s => s.scaffold === scaffold && (s.bp >= 42) === swept).length, { scaffold, swept })).toBeGreaterThan(0)
    const sprite = await page.evaluate(({ scaffold, swept }) => window.__sprites.find(s => s.scaffold === scaffold && (s.bp >= 42) === swept), { scaffold, swept })
    const response = page.waitForResponse(r => r.url().endsWith('/design/crossovers/place') && r.request().method() === 'POST')
    await page.mouse.click(box.x + sprite.x, box.y + sprite.y)
    const placed = await response
    expect(placed.ok(), await placed.text()).toBe(true)
    await page.keyboard.up('Shift')
    const after = (await placed.json()).design
    expect(after.crossovers).toHaveLength(1)
    const xo = after.crossovers[0]
    const helices = new Map(after.helices.map(h => [h.id, h]))
    const frameA = helices.get(xo.half_a.helix_id).lattice_frame_id
    expect(frameA).toBe(helices.get(xo.half_b.helix_id).lattice_frame_id)
    expect(frameA === originalFrame).toBe(!swept)
    expect(xo.half_a.index).toBe(sprite.bp)
    expect(after.feature_log.length).toBe(built.design.feature_log.length + 1)
    const coverage = design => design.strands.flatMap(s => s.domains.flatMap(d =>
      Array.from({ length: Math.abs(d.end_bp-d.start_bp)+1 }, (_, i) => `${d.helix_id}:${d.direction}:${Math.min(d.start_bp,d.end_bp)+i}`))).sort()
    expect(coverage(after)).toEqual(coverage(built.design))
    const count = () => page.evaluate(async () => {
      const { editorStore } = await import('/src/cadnano-editor/store.js')
      return editorStore.getState().design?.crossovers?.length
    })
    await expect.poll(count).toBe(1)
    await page.keyboard.press('Control+z')
    await expect.poll(count).toBe(0)
    await page.keyboard.press('Control+y')
    await expect.poll(count).toBe(1)
    await page.reload()
    await expect.poll(count).toBe(1)
    await page.keyboard.press('f')
    // Nick a base in this section: shared row picking must retain the real ID.
    const anchor = await page.evaluate(swept => window.__sprites.find(s => !s.scaffold && (s.bp >= 42) === swept), swept)
    const nickBp = swept ? 65 : 25
    await page.locator('#tool-nick').click()
    const nickReply = page.waitForResponse(r => r.url().endsWith('/design/nick') && r.request().method() === 'POST')
    await page.mouse.click(box.x + anchor.x + (nickBp-anchor.bp)*10*anchor.scale, box.y + anchor.y + 9*anchor.scale)
    const nicked = await nickReply
    expect(nicked.ok(), await nicked.text()).toBe(true)
    const nickArgs = nicked.request().postDataJSON()
    expect(nickArgs.bp_index).toBe(nickBp)
    expect(helices.get(nickArgs.helix_id).lattice_frame_id === originalFrame).toBe(!swept)
    expect(coverage((await nicked.json()).design)).toEqual(coverage(built.design))
    await page.keyboard.press('Control+z')
    await page.locator('#tool-select').click()
    // Drag the first gutter row below the second: both segments travel together.
    const source = await page.evaluate(() => window.__sprites.find(s => !s.scaffold && s.bp < 42))
    const gutterY = box.y + source.y + 15*source.scale
    const reorderedReply = page.waitForResponse(r => r.url().endsWith('/design/helices/reorder') && r.request().method() === 'PUT')
    await page.mouse.move(box.x + 20, gutterY)
    await page.mouse.down()
    await page.mouse.move(box.x + 20, gutterY + 65*source.scale, { steps: 6 })
    await page.mouse.up()
    const reordered = await reorderedReply
    expect(reordered.ok(), await reordered.text()).toBe(true)
    const ordered = reordered.request().postDataJSON().ordered_ids
    expect(new Set(ordered).size).toBe(4)
    expect(ordered.map(id => helices.get(id).grid_pos)).toEqual([[1, 1], [1, 1], [0, 1], [0, 1]])
    expect(errors).toEqual([])
  })
}
