import { test, expect } from '@playwright/test'
import path from 'node:path'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Camera-only UI exercise: no molecular structures or files are authored.
// Reads an existing example; animation changes stay in browser memory.
// Session caching is disabled by the test server; no persistent artifacts.
test('local presentation waits at keyframes, navigates, and restores the editor', async ({ page }) => {
  test.setTimeout(60000)
  const errors = trackConsoleErrors(page)
  await page.goto('/?doc=__e2e__local-animation-presentation')
  await page.waitForFunction(() => !!window.__nadocTest)
  await page.evaluate(async example => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(example)
  }, path.resolve(process.cwd(), '..', 'Examples', '2hb_xover_atoms_test.nadoc'))
  await page.waitForFunction(() => window.__nadocTest.store.getState().currentDesign?.animations?.length > 0)
  await page.evaluate(() => {
    const { store } = window.__nadocTest
    const design = store.getState().currentDesign
    store.setState({ currentDesign: { ...design, animations: [{ id: 'local-test', name: 'Local presentation',
      loop: true, fps: 30, keyframes: [1, 2, 3].map(id => ({ id: String(id),
        text: `Keyframe ${id}`, transition_duration_s: 0.1, hold_duration_s: 0.2 })) }] } })
    document.getElementById('welcome-screen')?.classList.add('hidden')
    // API-only loading skips the File menu's editor-unlock UI wiring.
    document.getElementById('left-panel').classList.remove('locked-hidden')
    for (const button of document.querySelectorAll('#left-tab-strip button')) button.disabled = false
    window.__leftSidebar.refresh()
  })
  await page.locator('.left-tab-btn[data-tab="scene"]').click()
  const button = page.locator('#anim-start-presentation-btn')
  await expect(button).toBeEnabled()
  await button.click()
  await expect(page.locator('#canvas-area')).toHaveClass(/animation-presentation-active/)
  const time = () => page.evaluate(() => window.__nadocTest.animPlayer.getCurrentTime())
  await expect.poll(time).toBeCloseTo(0.3, 3)
  await expect(page.locator('#anim-text-overlay')).toContainText('Keyframe 1')
  await page.waitForTimeout(400)
  expect(await time()).toBeCloseTo(0.3, 3)
  const box = await page.locator('#canvas-area').boundingBox()
  const size = page.viewportSize()
  expect(box.width).toBe(size.width)
  expect(box.height).toBe(size.height)
  await page.keyboard.press('Space')
  await expect.poll(time).toBeCloseTo(0.6, 3)
  await page.keyboard.press('ArrowLeft')
  await expect.poll(time).toBeCloseTo(0.3, 3)
  await page.locator('#canvas').click({ position: { x: 200, y: 200 } })
  await expect.poll(time).toBeCloseTo(0.6, 3)
  await page.keyboard.press('ArrowRight')
  await expect(page.locator('#canvas-area')).not.toHaveClass(/animation-presentation-active/)
  await expect(button).toBeVisible()
  await button.click()
  await expect(page.locator('#canvas-area')).toHaveClass(/animation-presentation-active/)
  await page.keyboard.press('Escape')
  await expect(page.locator('#canvas-area')).not.toHaveClass(/animation-presentation-active/)
  expect(errors).toEqual([])
})
