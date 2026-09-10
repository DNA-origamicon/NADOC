import { test, expect } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'

// Import into an isolated document; never load/save the user's original file.
// Names are __e2e__-prefixed for global-teardown if an autosave is introduced.
// Session caching is disabled by playwright.config.js; screenshots stay in the
// configured test output directory and its cleanup reporter removes them.
test('seamless closes cube_pore and visibly warns for an uncloseable section', async ({ page }, testInfo) => {
  test.setTimeout(90000)
  const source = path.resolve(import.meta.dirname, '../../workspace/cube_pore.nadoc')
  test.skip(!existsSync(source), 'Local cube_pore fixture unavailable; backend tests cover a synthetic 6x6.')
  const cube = JSON.parse(readFileSync(source, 'utf8'))
  cube.name = '__e2e__seamless_cube'
  const errors = []
  page.on('pageerror', error => errors.push(String(error)))
  await page.goto('/?doc=__e2e__seamless-cycle')
  await page.waitForSelector('#canvas')
  await page.evaluate(async content => {
    const api = await import('/src/api/client.js')
    await api.importDesign(content)
    // Raw API import leaves File/Open's welcome overlay dismissal to its caller.
    document.getElementById('welcome-screen').classList.add('hidden')
  }, JSON.stringify(cube))
  await page.keyboard.press('f')
  await page.evaluate(() => {
    document.getElementById('autoscaffold-modal').classList.add('visible')
  })
  await page.locator('input[name="as-mode"][value="seamless"]').check()
  const response = page.waitForResponse(r => r.url().endsWith('/design/auto-scaffold-seamless'))
  await page.locator('#as-run').click()
  const routed = await (await response).json()
  expect(routed.end_xovers).toBe(36)
  expect(routed.warnings.filter(w => w.startsWith('[Seamless]'))).toEqual([])
  const strands = routed.design.strands.filter(s => s.strand_type === 'scaffold' && !s.is_reference)
  expect(strands).toHaveLength(1)
  const first = strands[0].domains[0], last = strands[0].domains.at(-1)
  expect(first.helix_id).toBe(last.helix_id)
  expect(first.start_bp - last.end_bp).toBe(first.direction === 'FORWARD' ? 1 : -1)
  await expect(page.locator('#op-progress')).not.toBeVisible()
  await page.keyboard.press('f')
  await page.screenshot({ path: testInfo.outputPath('cube-closed.png') })

  // An odd 3x3 square section has a Hamiltonian path but cannot have a cycle.
  const keep = new Set(cube.helices.filter(h => h.grid_pos[0] < 3 && h.grid_pos[1] < 3).map(h => h.id))
  cube.name = '__e2e__seamless_odd'
  cube.helices = cube.helices.filter(h => keep.has(h.id))
  cube.strands = cube.strands.flatMap(s => s.domains.filter(d => keep.has(d.helix_id)).map((d, i) => ({ ...s, id: `${s.id}_${i}`, domains: [d] })))
  cube.crossovers = []
  cube.feature_log = []
  cube.feature_log_cursor = -1
  await page.evaluate(async content => {
    const api = await import('/src/api/client.js')
    await api.importDesign(content)
    await api.autoScaffoldSeamless()
  }, JSON.stringify(cube))
  await expect(page.locator('.toast--warning').filter({ hasText: 'No closed route' })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('open-warning.png') })
  expect(errors).toEqual([])
})
