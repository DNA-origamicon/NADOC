/** Read-only real-part selection timing. No saved structures. Report cleanup uses
 * the smoke config; the caller supplies an isolated temporary workspace. */
import { test, expect } from '@playwright/test'
import path from 'node:path'
import { trackConsoleErrors } from './helpers/scene_harness.js'

test('measure staple selection through a rendered frame', async ({ page, request }) => {
  test.setTimeout(180000)
  const errors = trackConsoleErrors(page)
  const doc = 'e2e-selection-latency-readonly'
  const source = process.env.NADOC_TEMPERATURE_DESIGN || path.resolve('..', 'Examples', 'U6hb.nadoc')
  expect((await request.post(`${process.env.NADOC_E2E_API_BASE}/api/design/load`, {
    headers: { 'X-NADOC-Doc': doc }, data: { path: source },
  })).ok()).toBe(true)
  await page.addInitScript(() => localStorage.setItem('spreadsheet_open', 'true'))
  await page.goto(`/?doc=${doc}&readiness=simulation`)
  await page.waitForFunction(() => window.__nadocTest?.getDesignRenderer()?.getBackboneEntries()?.length > 0, null, { timeout: 60000 })
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('Profiler.enable')
  await cdp.send('Profiler.start')
  for (const mode of ['off', 'domain', 'total']) {
    if (mode !== 'off') await page.locator('[data-vt="stapleTemperature"]').click()
    const timings = await page.evaluate(async () => {
      const { store } = await import('/src/state/store.js')
      const ids = store.getState().currentDesign.strands.filter(s => s.strand_type === 'staple' && !s.is_reference).slice(0, 4).map(s => s.id)
      const values = []
      for (const id of ids) {
        const start = performance.now()
        document.querySelector(`tr[data-strand-id="${id}"] td[data-col="id"]`).click()
        const syncMs = performance.now() - start
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
        values.push({ id, syncMs, frameMs: performance.now() - start, selected: store.getState().selection.primary?.id, highlighted: document.querySelector(`tr[data-strand-id="${id}"]`).classList.contains('sheet-selected') })
      }
      return values
    })
    console.log('SELECTION_TIMINGS', mode, JSON.stringify(timings))
    for (const timing of timings) {
      expect(timing.selected).toBe(timing.id)
      expect(timing.highlighted).toBe(true)
      expect(timing.syncMs).toBeLessThan(150)
    }
  }
  if (process.env.NADOC_SELECTION_SCREENSHOTS) await page.screenshot({ path: path.join(process.env.NADOC_SELECTION_SCREENSHOTS, doc + '.png') })
  const { profile } = await cdp.send('Profiler.stop')
  const nodes = new Map(profile.nodes.map(n => [n.id, n]))
  const hits = new Map()
  for (let i = 0; i < profile.samples.length; i++) {
    const n = nodes.get(profile.samples[i]), f = n.callFrame
    const key = `${f.functionName} ${f.url.replace(/^.*\/src\//, '')}:${f.lineNumber + 1}`
    hits.set(key, (hits.get(key) || 0) + profile.timeDeltas[i] / 1000)
  }
  console.log('SELECTION_PROFILE_SELF_MS', JSON.stringify([...hits].sort((a,b) => b[1]-a[1]).slice(0, 25)))
  expect(errors.filter(e => !/favicon|WebSocket/.test(e))).toEqual([])
})

test('measure cadnano staple clicks', async ({ page, request }) => {
  test.setTimeout(180000)
  const doc = 'e2e-cadnano-selection-latency-readonly'
  const source = process.env.NADOC_TEMPERATURE_DESIGN || path.resolve('..', 'Examples', 'U6hb.nadoc')
  expect((await request.post(`${process.env.NADOC_E2E_API_BASE}/api/design/load`, {
    headers: { 'X-NADOC-Doc': doc }, data: { path: source },
  })).ok()).toBe(true)
  await page.route('**/src/cadnano-editor/pathview.js', async route => {
    const response = await route.fetch()
    await route.fulfill({ response, body: (await response.text()).replace('  // ── Public interface', `
      window.selectionProbe = {
        selected: () => [..._strandSelectedIds],
        redraw: (uncached = false) => {
          const draw = _trackLayer.draw
          if (uncached) _trackLayer.draw = (context, inputs, paint) => paint(context)
          try { _draw() } finally { _trackLayer.draw = draw }
        },
        points: () => (_design?.strands ?? []).filter(s => s.strand_type === 'staple').flatMap(s => s.domains.map(d => {
          const row = _rowMap.get(d.helix_id), bp = (d.start_bp + d.end_bp) / 2
          if (!row) return null
          const x = _bpCenterX(bp), y = d.direction === 'FORWARD' ? row.fwdY : row.revY
          const hit = _hitTest(x * _zoom + _panX, y * _zoom + _panY)
          if (hit?.strand.id !== s.id || _hitTestCrossoverSprite(x * _zoom + _panX, y * _zoom + _panY)) return null
          return { id: s.id, x: x * _zoom + _panX, y: y * _zoom + _panY }
        }).filter(Boolean)),
      }
      // ── Public interface`) })
  })
  await page.addInitScript(() => localStorage.setItem('editor_spreadsheet_open', 'true'))
  await page.goto(`/cadnano-editor.html?doc=${doc}`)
  await page.waitForFunction(() => window.selectionProbe?.points().length > 0)
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('Profiler.enable')
  await cdp.send('Profiler.start')
  const canvas = page.locator('#pathview-canvas')
  const box = await canvas.boundingBox()
  const points = (await page.evaluate(() => window.selectionProbe.points())).filter(p => p.x > 100 && p.x < box.width - 20 && p.y > 30 && p.y < box.height - 20).filter((p, i, all) => all.findIndex(other => other.id === p.id) === i).slice(0, 4)
  expect(points.length).toBeGreaterThan(0)
  for (const mode of ['off', 'domain', 'total']) {
    if (mode !== 'off') await page.locator('[data-vt="stapleTemperature"]').click()
    for (const point of points) {
      const start = Date.now()
      await page.mouse.click(box.x + point.x, box.y + point.y)
      const selected = await page.evaluate(async () => {
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
        return window.selectionProbe.selected()
      })
      const elapsed = Date.now() - start
      console.log('CADNANO_SELECTION_MS', mode, elapsed, selected)
      expect(selected).toContain(point.id)
      expect.soft(elapsed).toBeLessThan(200)
    }
  }
  if (process.env.NADOC_SELECTION_SCREENSHOTS) await page.screenshot({ path: path.join(process.env.NADOC_SELECTION_SCREENSHOTS, doc + '.png') })
  const comparePixels = () => page.evaluate(() => {
    const canvas = document.getElementById('pathview-canvas'), ctx = canvas.getContext('2d')
    window.selectionProbe.redraw()
    const cached = ctx.getImageData(0, 0, canvas.width, canvas.height).data
    window.selectionProbe.redraw(true)
    const fresh = ctx.getImageData(0, 0, canvas.width, canvas.height).data
    return cached.every((value, i) => value === fresh[i])
  })
  expect(await comparePixels()).toBe(true)
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.wheel(0, -120)
  expect(await comparePixels()).toBe(true)
  await page.locator('[data-vt="grid"]').click()
  expect(await comparePixels()).toBe(true)
  await page.locator('[data-vt="grid"]').click()
  expect(await comparePixels()).toBe(true)
  const { profile } = await cdp.send('Profiler.stop')
  const nodes = new Map(profile.nodes.map(n => [n.id, n])), hits = new Map()
  for (let i = 0; i < profile.samples.length; i++) {
    const f = nodes.get(profile.samples[i]).callFrame
    const key = `${f.functionName} ${f.url.replace(/^.*\/src\//, '')}:${f.lineNumber + 1}`
    hits.set(key, (hits.get(key) || 0) + profile.timeDeltas[i] / 1000)
  }
  console.log('CADNANO_PROFILE_SELF_MS', JSON.stringify([...hits].sort((a,b) => b[1]-a[1]).slice(0, 20)))

})
