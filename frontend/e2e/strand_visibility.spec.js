import { test, expect } from '@playwright/test'

const DESIGN = '/home/jojo/Work/NADOC/workspace/2hb_2xT.nadoc'

test('strand automation hides beads, cones and slabs in 2hb_2xT', async ({ page }) => {
  await page.goto('/?doc=e2e-strand-visibility')
  await page.waitForSelector('#canvas')
  await page.evaluate(async path => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(path)
    document.getElementById('welcome-screen')?.classList.add('hidden')
  }, DESIGN)
  await expect.poll(() => page.evaluate(() =>
    window.__nadocTest?.store.getState().currentGeometry?.length ?? 0),
  { timeout: 25_000 }).toBeGreaterThan(0)

  const strandId = await page.evaluate(() =>
    window.__nadocTest.store.getState().currentDesign.strands
      .find(s => s.strand_type !== 'scaffold')?.id)
  expect(strandId).toBeTruthy()

  const before = await page.evaluate(id => window.__nadocTest.visibility.strandRenderStats(id), strandId)
  expect(before.visibleBeads).toBeGreaterThan(0)
  expect(before.visibleSlabs).toBeGreaterThan(0)

  await page.screenshot({ path: 'test-results/strand-visibility-2hb_2xT-before.png', fullPage: true })

  await page.evaluate(id => window.__nadocTest.visibility.hideStrands([id]), strandId)
  const hidden = await page.evaluate(id => window.__nadocTest.visibility.strandRenderStats(id), strandId)
  expect(hidden).toMatchObject({ visibleBeads: 0, visibleCones: 0, visibleSlabs: 0 })

  await page.evaluate(() => window.__nadocTest.visibility.undo())
  const restored = await page.evaluate(id => window.__nadocTest.visibility.strandRenderStats(id), strandId)
  expect(restored.visibleBeads).toBe(before.visibleBeads)
  expect(restored.visibleSlabs).toBe(before.visibleSlabs)

  // Visual artifact retained on failure by Playwright; this explicit shot also
  // makes the real 2hb fixture easy to inspect in local validation runs.
  await page.evaluate(id => window.__nadocTest.visibility.hideStrands([id]), strandId)
  await page.screenshot({ path: 'test-results/strand-visibility-2hb_2xT-after.png', fullPage: true })

  // The same hidden-base state survives representation switches. Heavy reps
  // load asynchronously, so wait for the switch to settle before capturing.
  for (const repr of ['cylinders', 'vdw', 'surface']) {
    await page.evaluate(r => window.__nadocTest.setRepresentation(r), repr)
    await page.waitForTimeout(repr === 'cylinders' ? 400 : 1800)
    expect(await page.evaluate(() => window.__nadocTest.visibility.hiddenBaseKeys().length)).toBeGreaterThan(0)
    await page.screenshot({ path: `test-results/strand-visibility-2hb_2xT-${repr}.png`, fullPage: true })
  }
})
