import { test, expect } from '@playwright/test'
import path from 'node:path'

// Persistent inventory: the __e2e__SweepLoopSkip part and its revision store
// are removed by global-teardown even on failure; smoke config disables session
// caching. Only .development-artifacts/sweep-loop-skips.png is retained evidence.
test('Add Loops/Skips realizes a routed sweep through the existing menu', async ({ page }) => {
  test.setTimeout(90_000)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  page.on('response', r => { if (r.status() >= 500) errors.push(`${r.status()} ${r.url()}`) })
  await page.goto('/?doc=__e2e__sweep-loop-skip')
  await expect(page.locator('#canvas')).toBeVisible()
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__SweepLoopSkip')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const points = Array.from({ length: 33 }, (_, i) => { const t = 1.2 * i / 32; return [40 * (1 - Math.cos(t)), 0, 40 * Math.sin(t)] })
    if (!await api.createSweep({ cells: [[0,1],[1,1],[1,2],[1,3],[0,3],[0,2]], points_nm: points, ligate_adjacent: false })) throw new Error('Sweep failed')
    if (!await api.autoScaffoldSeamed()) throw new Error('Scaffold failed')
    if (!await api.addAutoCrossover()) throw new Error('Crossovers failed')
    if (!await api.addAutoBreak()) throw new Error('Break failed')
  })
  await page.locator('#menu-item-tools').hover()
  await page.locator('#menu-item-tools .submenu-item').filter({ hasText: /^Routing/ }).hover()
  await expect(page.locator('#menu-seq-update-routing')).toBeEnabled()
  await page.click('#menu-seq-update-routing')
  const summary = () => page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const d = store.getState().currentDesign
    return { count: d.helices.reduce((n,h) => n + h.loop_skips.length, 0), kind: d.feature_log.at(-1)?.op_kind,
      signs: [...new Set(d.helices.flatMap(h => h.loop_skips.map(m => m.delta)))].sort() }
  })
  await expect.poll(async () => (await summary()).kind).toBe('apply-loop-skips')
  const expected = await summary()
  expect(expected.count).toBeGreaterThan(10)
  expect(expected.signs).toEqual([-1,1])
  await page.evaluate(async () => { await (await import('/src/api/client.js')).undo() })
  expect((await summary()).count).toBe(0)
  await page.evaluate(async () => { await (await import('/src/api/client.js')).redo() })
  expect(await summary()).toEqual(expected)
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    const saved = await fetch('/api/design/export', { headers: { 'X-NADOC-Doc': new URLSearchParams(location.search).get('doc') } })
    if (!saved.ok || !await api.importDesign(await saved.text())) throw new Error('Reload failed')
    store.setState({ showLoopSkips: true })
  })
  expect(await summary()).toEqual(expected)
  await page.locator('#canvas').focus(); await page.keyboard.press('f')
  await page.screenshot({ path: path.resolve(import.meta.dirname, '../../.development-artifacts/sweep-loop-skips.png') })
  expect(errors).toEqual([])
})
