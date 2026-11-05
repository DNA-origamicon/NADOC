import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'

// Fixture must be published by agent_structure_guard before this read-only check.
// Screenshot stays in Playwright's configured output directory. The caller owns
// and removes its isolated workspace/output/fixture root after inspection.
test('renders routed source and swept lattice frames', async ({ page }) => {
  const file = process.env.NADOC_AUTOSTAPLE_REVIEW
  test.skip(!file, 'Requires a guarded, recorded review fixture')
  test.setTimeout(90_000)
  const design = JSON.parse(await readFile(file, 'utf8'))
  const frames = new Map(design.helices.map(h => [h.id, h.lattice_frame_id]))
  const xos = design.crossovers.filter(c => c.process_id === 'auto_crossover')
  expect(new Set(xos.map(c => frames.get(c.half_a.helix_id))).size).toBe(2)
  expect(xos.every(c => frames.get(c.half_a.helix_id) === frames.get(c.half_b.helix_id))).toBe(true)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.goto('/')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async file => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(file)
    // API-only loading avoids library identity writes to the fixture.
    document.getElementById('welcome-screen').classList.add('hidden')
  }, file)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.getBaseCandidates().length)).toBeGreaterThan(0)
  await page.locator('#canvas').click({ position: { x: 20, y: 20 } })
  await page.keyboard.press('f')
  await page.waitForTimeout(1000)
  await page.screenshot({ path: test.info().outputPath('routed.png') })
  expect(errors).toEqual([])
})
