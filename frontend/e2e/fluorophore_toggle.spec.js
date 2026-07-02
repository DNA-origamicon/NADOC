import { test, expect } from '@playwright/test'

// Fluorophore view toggle: a design with a Cy3 StrandExtension glows when the
// user turns on View ▸ Fluorescence, and clears when turned off. Fixture built by
// scripts/gen_fluorophore_demo_fixture.py (a staple with a cy3 3' extension).
const FIXTURE = '/home/joshua/NADOC/workspace/playwright_tests/fluorophore_demo.nadoc'

test('fluorophore view toggle glows a Cy3 extension', async ({ page }) => {
  const errors = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })

  await page.goto('/')
  await page.waitForTimeout(1500)

  await page.evaluate(async (p) => {
    const a = await import('/src/api/client.js')
    await a.loadDesign(p)
    await a.getGeometry()
    document.getElementById('welcome-screen')?.classList.add('hidden')
  }, FIXTURE)
  await page.waitForTimeout(1200)

  // The Cy3 fluorophore exists in geometry, but nothing glows until toggled on.
  const before = await page.evaluate(() => {
    const dr = window.__NADOC_DBG__.designRenderer
    const fluoros = (dr.getFluoroEntries?.() ?? []).filter(e => e.nuc?.modification === 'cy3').length
    return { fluoros, glow: dr.fluoroGlowCount() }
  })
  expect(before.fluoros, 'the cy3 extension is in the geometry').toBeGreaterThan(0)
  expect(before.glow).toBe(0)

  // View ▸ Fluorescence ON → fluorophores glow.
  await page.evaluate(() => document.getElementById('menu-view-fluorescence').click())
  await page.waitForTimeout(400)
  const on = await page.evaluate(() => window.__NADOC_DBG__.designRenderer.fluoroGlowCount())
  await page.screenshot({ path: 'e2e/screenshots/fluorophore_toggle.png', fullPage: true })
  expect(on, 'fluorescence toggle rendered glow(s)').toBeGreaterThan(0)

  // Toggle OFF → glow cleared.
  await page.evaluate(() => document.getElementById('menu-view-fluorescence').click())
  await page.waitForTimeout(300)
  const off = await page.evaluate(() => window.__NADOC_DBG__.designRenderer.fluoroGlowCount())
  expect(off).toBe(0)

  expect(errors, `console errors:\n${errors.join('\n')}`).toEqual([])
})
