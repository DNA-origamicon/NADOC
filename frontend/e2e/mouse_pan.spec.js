import { test, expect } from '@playwright/test'
import { trackConsoleErrors } from './helpers/scene_harness.js'

// Camera-only exercise: no designs, jobs, or files are authored.
test('Ctrl-right drag pans in every desktop camera mode', async ({ page }) => {
  const errors = trackConsoleErrors(page)
  await page.goto('/?doc=__e2e__mouse-pan')
  await page.waitForFunction(() => window.__nadocTest && window.__NADOC_DBG__?.camera)
  await page.evaluate(() => document.getElementById('welcome-screen')?.classList.add('hidden'))
  const pose = () => page.evaluate(() => window.__nadocTest.viewerDiagnostic().camera)
  const direction = p => {
    const v = p.position.map((x, i) => x - p.target[i])
    const length = Math.hypot(...v)
    return v.map(x => x / length)
  }
  const box = await page.locator('#canvas').boundingBox()
  for (const mode of ['turntable', 'trackball', 'multiscale']) {
    await page.locator(`#menu-view-orbit-${mode}`).dispatchEvent('click')
    const before = await pose()
    await page.mouse.move(box.x + box.width * .45, box.y + box.height * .5)
    await page.keyboard.down('Control')
    await page.mouse.down({ button: 'right' })
    await page.mouse.move(box.x + box.width * .6, box.y + box.height * .6, { steps: 12 })
    await page.mouse.up({ button: 'right' })
    await page.keyboard.up('Control')
    const after = await pose()
    expect(Math.hypot(...after.position.map((x, i) => x - before.position[i]))).toBeGreaterThan(.01)
    direction(after).forEach((v, i) => expect(v).toBeCloseTo(direction(before)[i], 5))
    expect(after.target).not.toEqual(before.target)
  }
  expect(errors).toEqual([])
})
